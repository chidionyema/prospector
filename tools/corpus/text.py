"""Tokenising and structural measurement, shared by every corpus tool here.

Both corpora MUST go through this module. A keyness table computed with one tokeniser on
the human corpus and another on ours would rank the tokenisers, not the writing.

No spaCy, no scipy. Log-likelihood is arithmetic and sentence splitting on this genre is a
regex; adding two heavy dependencies to run `math.log` would be its own kind of defect.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Words, keeping internal apostrophes and hyphens. Numbers are dropped on purpose: a
#: keyness table dominated by "2024" and "£1,299" measures the subject matter, not the voice.
_WORD = re.compile(r"[a-z][a-z'’-]*")

#: A sentence ends at . ! ? followed by space and a capital, or at a paragraph break. Common
#: abbreviations are protected first so "Ltd. The" does not split mid-sentence.
_ABBREV = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|ltd|plc|inc|co|no|vs|e\.g|i\.e|etc|approx|fig|para)\.",
    re.I)
_SENT_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")

#: Hedges. Counted per 1,000 words. A judicial writer hedges — the question is at what RATE,
#: which is exactly what we are measuring rather than asserting.
HEDGES = frozenset("""
may might could would should possibly probably perhaps likely unlikely apparently
seems seem seemed appears appear appeared suggests suggest suggested indicates indicate
arguably potentially generally typically usually often sometimes somewhat relatively
broadly largely mostly partly presumably conceivably plausibly tends tend tended
""".split())

#: Attribution. Who says so, and how often the writer says who.
ATTRIB_WORDS = frozenset("""
said says say told reports reported reporting states stated writes wrote noted notes
argues argued claims claimed describes described found finds confirmed confirms
""".split())
ATTRIB_PHRASES = (
    "according to", "in its view", "on their account", "as set out in", "cited in",
    "quoted in", "in evidence", "the evidence shows", "records show",
)

#: Subordinators, the cheap proxy for clause count that does not need a parser. Counted
#: alongside commas: a clause load is commas + subordinators within one sentence.
SUBORDINATORS = frozenset("""
although though whereas while because since unless until whether if when whenever
which who whom whose that after before once so as
""".split())

#: Single characters, counted by membership.
PUNCT_CLASSES = {
    "comma": ",", "semicolon": ";", "colon": ":", "question": "?",
    "exclamation": "!", "paren": "()", "quote": "\"'“”",
}

#: Dashes and hyphens are counted SEPARATELY, and the distinction is the whole point.
#: A hyphen inside "well-founded" is a compound noun. An em dash, or a hyphen with spaces
#: around it, is a writer stacking clauses — the thing `copy_lint.check_house_dashes` bans.
#: Counted together, our compound-heavy titles ("Front-Door Key-Safe Re-Siting") read as a
#: dash habit, and we would go and fix punctuation that is not there. First measured
#: 2026-08-16: counting them together put our "dash" rate 7x over the human corpus.
_DASH = re.compile(r"[—–]|(?<=\s)-(?=\s)|(?<=\s)--?(?=\S)")
_HYPHEN = re.compile(r"(?<=\w)-(?=\w)")


def tokens(text: str) -> list[str]:
    """Lowercased word tokens. The single definition both corpora use."""
    return _WORD.findall((text or "").lower())


def sentences(text: str) -> list[str]:
    """Sentences, abbreviation-protected. Empty strings never survive."""
    guarded = _ABBREV.sub(lambda m: m.group(0).replace(".", "\x00"), text or "")
    out: list[str] = []
    for para in re.split(r"\n\s*\n", guarded):
        for s in _SENT_END.split(para):
            s = s.replace("\x00", ".").strip()
            if s:
                out.append(s)
    return out


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def ngrams(toks: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]


@dataclass
class Profile:
    """The structural fingerprint of one corpus. Every rate is per 1,000 words so two
    corpora of different sizes compare directly."""
    documents: int = 0
    words: int = 0
    sentence_count: int = 0
    sent_len_mean: float = 0.0
    sent_len_sd: float = 0.0
    sent_len_p5: float = 0.0
    sent_len_p50: float = 0.0
    sent_len_p95: float = 0.0
    long_sentence_rate: float = 0.0      # share of sentences over 25 words
    clause_load_mean: float = 0.0        # commas + subordinators per sentence
    clause_load_p95: float = 0.0
    para_sentences_mean: float = 0.0
    para_words_mean: float = 0.0
    opener_diversity: float = 0.0        # distinct two-word openers / sentences
    hedges_per_1k: float = 0.0
    attribution_per_1k: float = 0.0
    punct_per_1k: dict[str, float] = field(default_factory=dict)
    type_token_ratio: float = 0.0        # on a fixed 10k-word window, size-independent

    def as_row(self) -> dict[str, float]:
        d = {k: v for k, v in self.__dict__.items() if k != "punct_per_1k"}
        d.update({f"punct_{k}_per_1k": v for k, v in self.punct_per_1k.items()})
        return d


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return float(sorted_vals[i])


def profile(docs: list[str]) -> Profile:
    """The eight structural measures over a list of documents.

    Measured across documents, never averaged per document and then averaged again: a
    one-paragraph doc would otherwise weigh as much as a twenty-page decision.
    """
    p = Profile(documents=len(docs))
    lengths: list[int] = []
    loads: list[int] = []
    openers: Counter[tuple[str, ...]] = Counter()
    para_sent: list[int] = []
    para_word: list[int] = []
    all_toks: list[str] = []
    punct = Counter()

    for doc in docs:
        toks = tokens(doc)
        all_toks.extend(toks)
        p.words += len(toks)
        for ch in doc:
            for name, chars in PUNCT_CLASSES.items():
                if ch in chars:
                    punct[name] += 1
        punct["dash"] += len(_DASH.findall(doc))
        punct["hyphen"] += len(_HYPHEN.findall(doc))
        for para in paragraphs(doc):
            ss = sentences(para)
            if ss:
                para_sent.append(len(ss))
                para_word.append(len(tokens(para)))
        for s in sentences(doc):
            st = tokens(s)
            if not st:
                continue
            lengths.append(len(st))
            loads.append(s.count(",") + sum(1 for t in st if t in SUBORDINATORS))
            openers[tuple(st[:2])] += 1

    p.sentence_count = len(lengths)
    if lengths:
        mean = sum(lengths) / len(lengths)
        p.sent_len_mean = mean
        p.sent_len_sd = math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths))
        ordered = sorted(lengths)
        p.sent_len_p5, p.sent_len_p50, p.sent_len_p95 = (
            _pct(ordered, 0.05), _pct(ordered, 0.50), _pct(ordered, 0.95))
        p.long_sentence_rate = sum(1 for x in lengths if x > 25) / len(lengths)
    if loads:
        p.clause_load_mean = sum(loads) / len(loads)
        p.clause_load_p95 = _pct(sorted(loads), 0.95)
    if para_sent:
        p.para_sentences_mean = sum(para_sent) / len(para_sent)
        p.para_words_mean = sum(para_word) / len(para_word)
    if openers:
        p.opener_diversity = len(openers) / sum(openers.values())

    per_1k = (1000 / p.words) if p.words else 0.0
    p.hedges_per_1k = sum(1 for t in all_toks if t in HEDGES) * per_1k
    attrib = sum(1 for t in all_toks if t in ATTRIB_WORDS)
    joined = " ".join(all_toks)
    attrib += sum(joined.count(ph) for ph in ATTRIB_PHRASES)
    p.attribution_per_1k = attrib * per_1k
    p.punct_per_1k = {k: punct[k] * per_1k
                      for k in (*PUNCT_CLASSES, "dash", "hyphen")}
    window = all_toks[:10_000]
    p.type_token_ratio = (len(set(window)) / len(window)) if window else 0.0
    return p


def log_likelihood(a: int, b: int, total_a: int, total_b: int) -> float:
    """Dunning's G2 for one item, SIGNED: positive means over-used in corpus A.

    a/b are the item's frequency in each corpus, total_a/total_b the corpus sizes. This is
    the standard keyness statistic — the same number AntConc reports.
    """
    if total_a <= 0 or total_b <= 0 or (a + b) == 0:
        return 0.0
    e_a = total_a * (a + b) / (total_a + total_b)
    e_b = total_b * (a + b) / (total_a + total_b)
    g2 = 0.0
    if a:
        g2 += a * math.log(a / e_a)
    if b:
        g2 += b * math.log(b / e_b)
    g2 *= 2
    over_in_a = (a / total_a) >= (b / total_b)
    return g2 if over_in_a else -g2


def log_ratio(a: int, b: int, total_a: int, total_b: int) -> float:
    """Effect size to sit beside G2. G2 alone rewards sheer frequency: on a 500k-word
    corpus a trivial difference on a very common word clears any significance threshold.
    Log ratio says how many times more often, which is what a writer can act on.
    """
    fa = (a or 0.5) / total_a
    fb = (b or 0.5) / total_b
    return math.log2(fa / fb)

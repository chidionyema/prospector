"""One definition of every prose measure, used by the linter AND by the corpus tools.

WHY THIS FILE EXISTS, AND WHY IT IS IN `prospector/` RATHER THAN `tools/`.

`docs/PROSE_CORPUS_PROGRAM.md` measures our prose against a human corpus and writes the
result to `prospector/data/prose_target.json`. `register_lint` then grades a pack against
that file. Those are two programs reading one number, and the number only means anything if
BOTH measure the same way: a target built with one tokeniser and enforced with another is a
comparison between tokenisers wearing a style rule's clothes. The fence the programme wrote
down — "a test fails if the shipped target and the code that reads it disagree" — is
satisfied here by CONSTRUCTION rather than by a test. There is one implementation, it lives
on the production side, and `tools/corpus/text.py` imports it.

WHAT IS MEASURED HERE AND WHAT IS NOT. This module counts. It has no thresholds, no
opinions and no config. `prose_target.py` holds the measured intervals and decides what is
outside them; `register_lint` decides what to say about it. Keeping the counting separate is
what let the 2026-08-16 measurement find two defects in its own numbers — a hyphen counted
as a dash, and vocabulary variety that was really document length — without touching a rule.

THE MEASUREMENT BOUNDARIES BELOW ARE NOT LIMITS. `LONG_SENTENCE_WORDS = 25` here does not
say a sentence may not run to 26 words. It says the rate is defined as "the share of
sentences over 25 words", and BOTH corpora are counted that way, so the human interval and
ours are the same measurement. What is allowed is `prose_target.json`'s business.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Bump when any definition below changes in a way that moves a number. The target file
#: records this, so a target measured under one tokeniser can never be read under another.
TOKENISER_VERSION = "1"

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

#: THE ONE CARVE-OUT. We are not adjudicating complaints, so the human corpus's SUBJECT
#: MATTER is not a target — only its FORM is. A keyness table mixes the two: `uk`, `nhs`,
#: `ai` and `data` sit in the same ranking as `none of` and `the passages`, and a voice rule
#: cut from that table without this split would ban the sectors we write about.
#:
#: The split is mechanical, not a judgement per row. English function words are a CLOSED
#: class — you cannot coin a new preposition — so "is every token in this item a function
#: word?" separates form from content without anyone deciding what a topic is.
FUNCTION_WORDS = frozenset("""
a an the this that these those
i you he she it we they me him her us them my your his its our their itself themselves
and or but nor so yet for
in on at by to from with without within into onto over under between among about
against during before after above below through across near per via upon out up down off
is are was were be been being am do does did doing have has had having
will would shall should can could must ought
not no never none neither either both all any some each every few many much more most
less least other another same such own very too also only just even still again
here there then now once ever
of s t re ve ll d m
""".split()) | HEDGES | SUBORDINATORS

#: Our own machinery, named in our own prose. `passages` is the single largest keyness row
#: we have (G2 5139, 1872x the human rate) and it is not subject matter — it is us
#: describing our retrieval to a reader who wants to know what is TRUE. Wrong in any genre,
#: so these are separated out and kept actionable rather than filed under content.
META_WORDS = frozenset("""
passage passages citation citations cite cited query queries retrieval retrieved
corpus dossier
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

#: Vocabulary variety, measured on a FIXED window so document length cannot fake it.
#: Type/token ratio falls as a document grows: every new word is more likely to be one
#: already used. Our documents average 654 words and the human decisions average 1,923, so
#: a raw type/token comparison between the two corpora measures length first and vocabulary
#: second. Measured 2026-08-16: raw TTR said we were at 0.52 against a human 0.29, z=+3.5,
#: which read as "our vocabulary churns". MATTR (moving-average type/token ratio) takes the
#: mean type/token over every 100-word window instead, so a 600-word document and a
#: 4,000-word one are scored on the same window size. 100 is the standard window.
MATTR_WINDOW = 100

#: Measurement boundaries, NOT limits. See the module docstring: these define what the rate
#: counts, on both corpora identically. The human interval for each rate lives in
#: `prospector/data/prose_target.json` and is the only thing that says what is too much.
LONG_SENTENCE_WORDS = 25
HEAVY_SENTENCE_COMMAS = 2


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


def mattr(toks: list[str], window: int = MATTR_WINDOW) -> float:
    """Mean type/token ratio over every `window`-token span. NaN when the text is shorter
    than one window, because there is nothing to average and 0.0 would read as "no variety".

    Rolling counter rather than a set per window: the corpus-level call runs over 500,000
    tokens, and rebuilding a 100-item set half a million times is a minute of nothing.
    """
    if len(toks) < window:
        return float("nan")
    seen: Counter[str] = Counter(toks[:window])
    total = len(seen)
    spans = 1
    for i in range(window, len(toks)):
        out_tok, in_tok = toks[i - window], toks[i]
        seen[out_tok] -= 1
        if seen[out_tok] == 0:
            del seen[out_tok]
        seen[in_tok] += 1
        total += len(seen)
        spans += 1
    return total / spans / window


def classify_item(item: str) -> str:
    """`meta`, `form` or `content` for one keyness row.

    content = subject matter. Under the carve-out above, no rule may be cut from it.
    """
    toks = item.split()
    if not toks:
        return "content"
    if any(t in META_WORDS for t in toks):
        return "meta"
    if all(t in FUNCTION_WORDS for t in toks):
        return "form"
    return "content"


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
    long_sentence_rate: float = 0.0      # share of sentences over LONG_SENTENCE_WORDS
    heavy_sentence_rate: float = 0.0     # share carrying HEAVY_SENTENCE_COMMAS or more
    clause_load_mean: float = 0.0        # commas + subordinators per sentence
    clause_load_p95: float = 0.0
    para_sentences_mean: float = 0.0
    para_words_mean: float = 0.0
    opener_diversity: float = 0.0        # distinct two-word openers / sentences
    hedges_per_1k: float = 0.0
    attribution_per_1k: float = 0.0
    punct_per_1k: dict[str, float] = field(default_factory=dict)
    type_token_ratio: float = 0.0        # WHOLE text up to 10k words — falls as length rises
    mattr: float = 0.0                   # mean TTR per 100-word window — length-independent

    def as_row(self) -> dict[str, float]:
        """NaN measures are DROPPED, not zeroed. `mattr` is undefined on a document shorter
        than one window; a 0.0 in the table would be averaged in as "no vocabulary variety"
        and drag the target down with documents that were never measured."""
        d = {k: v for k, v in self.__dict__.items()
             if k != "punct_per_1k" and not (isinstance(v, float) and math.isnan(v))}
        d.update({f"punct_{k}_per_1k": v for k, v in self.punct_per_1k.items()})
        return d


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return float(sorted_vals[i])


def profile(docs: list[str]) -> Profile:
    """Every structural measure over a list of documents.

    Measured across documents, never averaged per document and then averaged again: a
    one-paragraph doc would otherwise weigh as much as a twenty-page decision.
    """
    p = Profile(documents=len(docs))
    lengths: list[int] = []
    loads: list[int] = []
    heavy = 0
    openers: Counter[tuple[str, ...]] = Counter()
    para_sent: list[int] = []
    para_word: list[int] = []
    all_toks: list[str] = []
    punct: Counter[str] = Counter()

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
            if s.count(",") >= HEAVY_SENTENCE_COMMAS:
                heavy += 1
            openers[tuple(st[:2])] += 1

    p.sentence_count = len(lengths)
    if lengths:
        mean = sum(lengths) / len(lengths)
        p.sent_len_mean = mean
        p.sent_len_sd = math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths))
        ordered = sorted(lengths)
        p.sent_len_p5, p.sent_len_p50, p.sent_len_p95 = (
            _pct(ordered, 0.05), _pct(ordered, 0.50), _pct(ordered, 0.95))
        p.long_sentence_rate = sum(1 for x in lengths if x > LONG_SENTENCE_WORDS) / len(lengths)
        p.heavy_sentence_rate = heavy / len(lengths)
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
    p.mattr = mattr(all_toks)
    return p


def document_measures(text: str) -> dict[str, float]:
    """One document's measures, keyed exactly as `prose_target.json` keys them.

    THE SINGLE PATH from a document to a number. The human target is built by running this
    over every document in the human corpus; the linter grades a pack by running it over the
    pack's prose. Neither side can drift from the other because there is no other side.
    """
    return profile([text]).as_row()

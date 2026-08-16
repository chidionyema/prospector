"""Grade long-form pack prose on REGISTER — does a human write like this?

WHY THIS EXISTS. `prompts/style/voice.md` has carried the register rules since 2026-08-13
and every prose prompt injects them (`tests/invariants/test_house_voice.py`). A prompt
instruction is a request, evaluated by the same process that produces the error, and on
2026-08-14 the founder read a rebuilt pack and said it "reads like llm jargon, no human
writes like this". The rules were live, injected, and did not hold. The founder's own
statement of the problem is the requirement: *"with our listings growing i cant afford to
check every single doc"*. So the check is mechanical, runs on every document of every pack,
and its receipt accrues whether or not it is blocking.

WHAT IS DECIDABLE AND WHAT IS NOT — the same split `check_shelf_copy` makes.

  DECIDABLE, and therefore able to block:
    - a phrase from the banned list appears (`BANNED`);
    - one of the named constructions appears (`CONSTRUCTIONS`);
    - the same sentence appears in two different documents (`register_repeat`).

  STATISTICAL, and therefore rate-gated with the actuator defaulting to OFF:
    - the share of sentences over 25 words (`voice.md`: "Aim under 25 words");
    - the share of sentences carrying two or more commas (`voice.md`: "If a sentence
      needs a second comma-clause to stay upright, split it in two").

  A single "seamless" is a word to fix, not grounds to unlist a pack, so an individual hit
  is ALWAYS a warning and only the RATE can error. That asymmetry is deliberate: it is what
  lets the phrase list grow without any addition being able to strand the shelf.

THRESHOLDS ARE NOT SET HERE, AND THAT IS NOT AN OVERSIGHT. Every rate defaults to 0.0,
which disables blocking, exactly as `max_grammar_defects_per_1k` does. The house rollout is
written down at `config.yaml:1301-1305`: ship the check off, measure the live catalogue,
repair, re-measure zero, then flip. A number chosen before the sweep is a guess wearing a
threshold's clothes.

WHAT IS NEVER GRADED. Fenced code, inline code, URLs, markdown tables and blockquoted lines
are stripped before anything is counted. Blockquotes matter most: on a source-or-die
storefront a quoted passage may contain any phrase on this list, and "correcting" it would
falsify the citation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Tuple

#: Same shape every other check in this codebase returns. See `copy_lint.Problem`.
Problem = Dict[str, str]


def _err(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "error", "where": where, "detail": detail}


def _warn(check: str, where: str, detail: str) -> Problem:
    return {"check": check, "severity": "warning", "where": where, "detail": detail}


# ---------------------------------------------------------------------------
# The lexicon
# ---------------------------------------------------------------------------
#
# HOW TO EDIT THIS LIST. One entry per line, `phrase -> what to write instead`. The phrase
# is matched case-insensitively on word boundaries; a space in the phrase matches any run
# of whitespace, so a line broken across two source lines still matches.
#
# THE BAR FOR ADDING A WORD is that it has no legitimate use anywhere in this catalogue,
# which sells businesses in every sector. That bar is why `foster`, `leverage`, `bespoke`
# and `ecosystem` are NOT here: foster care, financial leverage, bespoke tailoring and a
# supplier ecosystem are all real subjects a pack may be about. The founder confirmed this
# bar on 2026-08-15 against the spec's own R9 list, which named `leverage` and `ecosystem`:
# the spec's list lost, and docs/HOUSE_WRITING_SPEC.md was amended to match this file rather
# than the other way round. `leveraging` stays banned because the tic is the -ing form and
# "using" replaces it everywhere. Words that are merely
# OVERUSED go in `ADVISORY` below, which never blocks.

BANNED_SPEC = """
delve -> look at
delves -> looks at
delving -> looking at
leveraging -> using
it's worth noting that -> (delete it and state the thing)
it is worth noting that -> (delete it and state the thing)
at the end of the day -> (delete it)
in today's fast-paced -> (name the year or the change, or delete it)
when it comes to -> for
navigate the complexities -> deal with
a testament to -> evidence of
underscores the -> shows the
underscoring -> showing
plays a crucial role -> matters because
plays a key role -> matters because
plays a vital role -> matters because
serves as a -> is a
in the realm of -> in
the landscape of -> (name the thing)
tapestry -> (name the thing)
unlock the potential -> (say what it lets them do)
unlocking -> (say what it lets them do)
harness the power -> use
elevate your -> improve your
seamless -> (say what does not break)
seamlessly -> (say what does not break)
cutting-edge -> new
state-of-the-art -> new
game-changer -> (say what changes)
game-changing -> (say what changes)
holistic -> whole
myriad -> many
plethora -> many
empower -> let
empowers -> lets
empowering -> letting
deep dive -> look closely
dive into -> look at
moving forward -> from now on
needless to say -> (delete it)
that being said -> but
actionable -> (say what to do)
impactful -> (say what it changes)
synergy -> (name the two things and what they do together)
synergies -> (name the two things and what they do together)
paradigm -> way
transformative -> (say what it changes)
unparalleled -> (name the comparison)
unmatched -> (name the comparison)
boasts -> has
meticulously -> carefully
carefully crafted -> written
look no further -> (delete it)
rest assured -> (delete it)
the beauty of -> (say the thing plainly)
here's the thing -> (delete it)
make no mistake -> (delete it)
low-hanging fruit -> the easy part
double down -> spend more on
circle back -> come back to
table stakes -> the minimum
north star -> the one thing that matters
key takeaway -> (state it as a sentence)
key takeaways -> (state them as sentences)
best practices -> what works
in conclusion -> (delete it)
to sum up -> (delete it)
resonates with -> (say what they recognise)
curated -> chosen
wide range of -> (say how many, or name them)
a variety of -> (say how many, or name them)
a host of -> (say how many, or name them)
drive growth -> grow
drive value -> (say what it is worth)
drive results -> (say what happens)
"""

# Overused rather than banned. These carry a real meaning in some sectors, so they are
# reported for the writer and never counted toward the blocking rate.
ADVISORY_SPEC = """
robust -> (say what it survives)
crucial -> (say what breaks without it)
pivotal -> (say what turns on it)
vital -> (say what fails without it)
streamline -> (say which step goes away)
journey -> (name the steps)
value proposition -> what it is worth to them
scalable -> (say how big it can get before it breaks)
innovative -> new
comprehensive -> complete
significantly -> (give the number)
substantially -> (give the number)
"""


def _parse_spec(spec: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in spec.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        phrase, _, fix = line.partition("->")
        out[phrase.strip().lower()] = fix.strip()
    return out


BANNED: Dict[str, str] = _parse_spec(BANNED_SPEC)
ADVISORY: Dict[str, str] = _parse_spec(ADVISORY_SPEC)


def _phrase_re(phrase: str) -> re.Pattern:
    # A space in the spec matches any whitespace run, so a phrase broken across two lines of
    # a markdown paragraph still matches. Apostrophes are normalised by `_normalise` before
    # matching, so only the straight form needs to appear here.
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", re.I)


_BANNED_RES: List[Tuple[str, re.Pattern, str]] = [
    (p, _phrase_re(p), fix) for p, fix in BANNED.items()]
_ADVISORY_RES: List[Tuple[str, re.Pattern, str]] = [
    (p, _phrase_re(p), fix) for p, fix in ADVISORY.items()]


# ---------------------------------------------------------------------------
# The constructions
# ---------------------------------------------------------------------------
#
# These are shapes, not words, and they are the half of the problem a word list cannot
# reach. Each entry is (name, pattern, what it does to the reader). Every one of them was
# present in the rebuilt pack the founder rejected on 2026-08-14, which is the evidence
# they are worth matching; none of them is a grammatical error, which is why the grammar
# checker never saw them.

CONSTRUCTIONS: List[Tuple[str, re.Pattern, str]] = [
    ("not_just",
     re.compile(r"(?<![\w-])(?:not|isn't|aren't|wasn't|weren't|is not|are not)\s+just(?![\w-])", re.I),
     "the 'not just X, but Y' shape — say what it is, and drop what it is not"),
    ("trailing_participle",
     re.compile(r",\s+(?:ensuring|allowing|enabling|helping|providing|offering|creating|"
                r"driving|making|highlighting|underscoring|reflecting|leveraging|thereby)(?![\w-])", re.I),
     "a trailing '-ing' clause bolted onto the sentence — start a new sentence and name "
     "who does it"),
    ("adverb_opener",
     re.compile(r"(?:^|(?<=[.!?]\s))\s*(?:Ultimately|Essentially|Fundamentally|Importantly|"
                r"Notably|Crucially|Interestingly|Moreover|Furthermore|Additionally|"
                r"In essence|In short|Simply put|Put simply|That said|Indeed)\b\s*,?", re.M),
     "an empty opener before the sentence starts — the first five words carry the point"),
    ("negation_reveal",
     re.compile(r"(?<![\w-])it'?s\s+not\s+[^.!?]{1,60}[.,;]\s*it'?s\s", re.I),
     "the 'It's not X. It's Y.' reveal — state the thing once"),
    ("not_only_but_also",
     re.compile(r"(?<![\w-])not\s+only\b[^.!?]{1,120}\bbut\s+also(?![\w-])", re.I),
     "'not only… but also' — two sentences, or one list"),
    ("whether_youre",
     re.compile(r"(?<![\w-])whether\s+you'?re(?![\w-])", re.I),
     "'whether you're a X or a Y' — name the one reader this is for"),
    ("rhetorical_answer",
     re.compile(r"\?\s+(?:Absolutely|Simply put|In short|Yes[.,]|No[.,])", re.I),
     "a rhetorical question answered by the writer — ask nothing, or answer a real one"),
    ("the_beauty_of",
     re.compile(r"(?<![\w-])the\s+(?:beauty|magic|trick|secret)\s+of(?![\w-])", re.I),
     "a flourish standing in for the fact — say the fact"),
]


# ---------------------------------------------------------------------------
# What is countable
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
#: A markdown table row, and a quoted line. Both are stripped whole: a table is data, and a
#: blockquote on this storefront is usually somebody else's words.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
_QUOTE_LINE_RE = re.compile(r"^\s*>.*$", re.M)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s.*$", re.M)
#: Straight and curly apostrophes are one character for matching purposes.
_APOS_RE = re.compile(r"[’‘‛]")


def _normalise(text: str) -> str:
    """Strip everything that is not engine-authored running prose."""
    t = _APOS_RE.sub("'", text or "")
    t = _FENCE_RE.sub(" ", t)
    t = _QUOTE_LINE_RE.sub(" ", t)
    t = _TABLE_ROW_RE.sub(" ", t)
    t = _INLINE_CODE_RE.sub(" ", t)
    t = _URL_RE.sub(" ", t)
    return t


#: Sentence boundary: terminal punctuation, optional closing quote/bracket, whitespace, then
#: something that starts a sentence. A decimal ("£5.99 a book") has a digit after the point
#: and never matches; an initialism followed by a capital ("the NHS. They") is a real
#: boundary and does. Abbreviations that end in a point mid-sentence are guarded by name.
_ABBREV_GUARD = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|Mr|Mrs|Ms|Dr|St|No|Fig|approx)\.)$", re.I)
_SENT_SPLIT_RE = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=[A-Z£$"\'(\d])')

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def sentences(text: str) -> List[str]:
    """Split running prose into sentences, ignoring headings and list bullets' markers."""
    body = _HEADING_RE.sub(" ", _normalise(text))
    out: List[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split())
        if not para:
            continue
        buf = ""
        for piece in _SENT_SPLIT_RE.split(para):
            candidate = (buf + " " + piece).strip() if buf else piece.strip()
            if _ABBREV_GUARD.search(candidate):
                buf = candidate
                continue
            buf = ""
            if candidate:
                out.append(candidate)
        if buf:
            out.append(buf)
    return out


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text)


# ---------------------------------------------------------------------------
# Cross-document repetition
# ---------------------------------------------------------------------------
#
# The founder's 2026-08-13 review of pack 8d5e24fbe6c1f5d3 put it at "roughly 40% of the
# reading being re-reading", and named it structural rather than stylistic: "you're selling
# the same 2,500 words three times". A human cannot check that across eight documents times
# a growing catalogue; a hash can, exactly.

_REPEAT_STRIP_RE = re.compile(r"[^a-z0-9 ]+")
#: Below this, a repeat is a phrase two documents legitimately share ("This is the same
#: check as above."), not a paragraph sold twice.
REPEAT_MIN_WORDS = 12


def _repeat_key(sentence: str) -> str:
    return " ".join(_REPEAT_STRIP_RE.sub(" ", sentence.lower()).split())


def cross_document_repeats(texts: Mapping[str, str]) -> List[Tuple[str, str, str, str]]:
    """Sentences that appear in two or more documents.

    Returns `(key, first_doc, second_doc, sentence)` once per repeated sentence, attributed
    to the SECOND document to see it — the first occurrence is the one the reader should
    keep.
    """
    seen: Dict[str, Tuple[str, str]] = {}
    out: List[Tuple[str, str, str, str]] = []
    for name in sorted(texts):
        text = texts[name]
        if not isinstance(text, str):
            continue
        for s in sentences(text):
            if len(_words(s)) < REPEAT_MIN_WORDS:
                continue
            key = _repeat_key(s)
            if not key:
                continue
            if key in seen:
                first_doc, first_sentence = seen[key]
                if first_doc != name:
                    out.append((key, first_doc, name, first_sentence))
            else:
                seen[key] = (name, s)
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

#: `voice.md`: "ONE IDEA PER SENTENCE. Aim under 25 words."
LONG_SENTENCE_WORDS = 25
#: `voice.md`: "If a sentence needs a second comma-clause to stay upright, split it in two."
CLAUSE_LOAD_COMMAS = 2
#: Below this the rates are noise, so they are computed but never blocked on. Mirrors
#: `copy_lint.check_grammar`, which returns [] under 200 words for the same reason.
MIN_WORDS_FOR_RATES = 200


def register_metrics(texts: Mapping[str, str]) -> Dict[str, Any]:
    """Measure the register of a pack's prose. Pure measurement — it rules on nothing.

    This is the function the catalogue sweep calls, so the number a threshold is later set
    from and the number the gate enforces are produced by one piece of code.
    """
    per_doc: Dict[str, Dict[str, Any]] = {}
    total_words = 0
    total_sentences = 0
    long_sentences = 0
    heavy_sentences = 0
    banned_hits: List[Dict[str, Any]] = []
    advisory_hits: List[Dict[str, Any]] = []
    construction_hits: List[Dict[str, Any]] = []

    for name in sorted(texts):
        text = texts[name]
        if not isinstance(text, str) or not text.strip():
            continue
        clean = _normalise(text)
        sents = sentences(text)
        words = sum(len(_words(s)) for s in sents)
        d_long = [s for s in sents if len(_words(s)) > LONG_SENTENCE_WORDS]
        d_heavy = [s for s in sents if s.count(",") >= CLAUSE_LOAD_COMMAS]

        d_banned = [{"phrase": p, "fix": fix, "count": len(rx.findall(clean))}
                    for p, rx, fix in _BANNED_RES if rx.search(clean)]
        d_advisory = [{"phrase": p, "fix": fix, "count": len(rx.findall(clean))}
                      for p, rx, fix in _ADVISORY_RES if rx.search(clean)]
        d_constructions = [{"construction": cname, "note": note, "count": len(rx.findall(clean))}
                           for cname, rx, note in CONSTRUCTIONS if rx.search(clean)]

        for hit in d_banned:
            banned_hits.append({**hit, "where": name})
        for hit in d_advisory:
            advisory_hits.append({**hit, "where": name})
        for hit in d_constructions:
            construction_hits.append({**hit, "where": name})

        per_doc[name] = {
            "words": words,
            "sentences": len(sents),
            "long_sentences": len(d_long),
            "heavy_sentences": len(d_heavy),
            "banned": sum(h["count"] for h in d_banned),
            "constructions": sum(h["count"] for h in d_constructions),
            "advisory": sum(h["count"] for h in d_advisory),
        }
        total_words += words
        total_sentences += len(sents)
        long_sentences += len(d_long)
        heavy_sentences += len(d_heavy)

    repeats = cross_document_repeats(texts)
    banned_count = sum(h["count"] for h in banned_hits)
    construction_count = sum(h["count"] for h in construction_hits)
    per_1k = ((banned_count + construction_count) / total_words * 1000.0) if total_words else 0.0

    return {
        "words": total_words,
        "sentences": total_sentences,
        "banned_count": banned_count,
        "construction_count": construction_count,
        "advisory_count": sum(h["count"] for h in advisory_hits),
        "repeat_count": len(repeats),
        # The headline number. Banned phrases and named constructions together, per thousand
        # words, because both are the same defect seen from two angles and a pack that trades
        # one for the other has not improved.
        "register_per_1k": round(per_1k, 2),
        "long_sentence_rate": round(long_sentences / total_sentences, 4) if total_sentences else 0.0,
        "clause_load_rate": round(heavy_sentences / total_sentences, 4) if total_sentences else 0.0,
        "banned_hits": banned_hits,
        "construction_hits": construction_hits,
        "advisory_hits": advisory_hits,
        "repeats": [{"first_seen_in": a, "repeated_in": b, "sentence": s}
                    for _k, a, b, s in repeats],
        "per_document": per_doc,
    }


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def check_register(texts: Mapping[str, str], *, block: bool = False,
                   max_per_1k: float = 0.0,
                   long_sentence_max_rate: float = 0.0,
                   clause_load_max_rate: float = 0.0,
                   metrics: Dict[str, Any] | None = None) -> List[Problem]:
    """Report register defects in a pack's long-form prose.

    `block` governs only the DECIDABLE finding — the same sentence sold in two documents.
    Every rate has its own actuator and every rate defaults to 0.0, meaning "measure but
    never block"; a rate of 0.0 cannot be breached, so a pack cannot be stranded by a
    threshold nobody set on purpose.

    Individual phrase and construction hits are ALWAYS warnings. They name the line for
    whoever rewrites it; the decision to unlist is taken on the rate, never on one word.

    Pass `metrics` to reuse a measurement already taken (the sweep does this); otherwise it
    is computed here.
    """
    m = metrics if metrics is not None else register_metrics(texts)
    problems: List[Problem] = []

    for hit in m["banned_hits"]:
        problems.append(_warn(
            "register", hit["where"],
            f"{hit['phrase']!r} ×{hit['count']} — write {hit['fix']}"))
    for hit in m["construction_hits"]:
        problems.append(_warn(
            "register", hit["where"],
            f"{hit['construction']} ×{hit['count']} — {hit['note']}"))
    for hit in m["advisory_hits"]:
        problems.append(_warn(
            "register", hit["where"],
            f"{hit['phrase']!r} ×{hit['count']} — overused; consider {hit['fix']}"))

    mk = _err if block else _warn
    for rep in m["repeats"]:
        problems.append(mk(
            "register_repeat", rep["repeated_in"],
            f"this sentence is already in {rep['first_seen_in']}; the buyer pays once and "
            f"reads it twice: {rep['sentence'][:160]!r}"))

    # The rates. Reported at `warning` under their own threshold and `error` above it, so
    # the receipt carries the number either way and the baseline accrues while the actuator
    # is still off.
    if m["words"] >= MIN_WORDS_FOR_RATES:
        if max_per_1k > 0 and m["register_per_1k"] > max_per_1k:
            problems.append(_err(
                "register_rate", "pack",
                f"register defects = {m['register_per_1k']} per 1k words, over the "
                f"{max_per_1k} allowed ({m['banned_count']} banned phrases, "
                f"{m['construction_count']} constructions in {m['words']} words)"))
        if long_sentence_max_rate > 0 and m["long_sentence_rate"] > long_sentence_max_rate:
            problems.append(_err(
                "register_rate", "pack",
                f"{m['long_sentence_rate']:.0%} of sentences run over {LONG_SENTENCE_WORDS} "
                f"words, over the {long_sentence_max_rate:.0%} allowed — one idea per sentence"))
        if clause_load_max_rate > 0 and m["clause_load_rate"] > clause_load_max_rate:
            problems.append(_err(
                "register_rate", "pack",
                f"{m['clause_load_rate']:.0%} of sentences carry two or more comma-clauses, "
                f"over the {clause_load_max_rate:.0%} allowed — split them in two"))
    return problems

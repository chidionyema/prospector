"""House writing spec — the rules Vale cannot check, on the pack lane.

`docs/HOUSE_WRITING_SPEC.md` is the specification; this module is half its enforcement and
`register_lint` is the other half. The split is not arbitrary:

  * `register_lint` owns R1 (sentence length), R2 (clause load) and R9 (banned register).
    It measured those before this spec existed and its lexicon carries a documented bar for
    what may be banned. Duplicating them here would give one rule two definitions.
  * Vale owns the same rule NUMBERS on the storefront lane, over files a human edits.
    It cannot reach a pack: a pack is assembled in memory and zipped, and materialising it
    to lint would put `/usr/local/bin/vale` on the daemon's critical path, which launchd
    does not carry on its PATH.
  * This module owns everything Part Six lists under "What Vale cannot check" — the rules
    that need a sentence's contents, not a token match: R4, R5, R6, R8, R10, Q1, Q2, Q3.

WHY EVERY ACTUATOR DEFAULTS TO OFF. Measured over 2,187 dossiers on 2026-08-15, 43.9% of
sentences break R1 and 13.8% carry a four-item list. A blocking threshold switched on at
that baseline does not improve the writing, it stops the line — every pack fails and the
catalogue stops publishing. Each rate below is recorded on every pack while its actuator is
zero, so the threshold that eventually gets set is one that was seen on real packs. This is
the same sequence `max_grammar_defects_per_1k` and `lint_repetition_block` were introduced
in, for the same reason.

The prose fix is upstream of all of it. A linter is the backstop, not the cure: the cure is
the Stage 1/Stage 2 split in Part Five, where retrieval stops competing with writing for
room inside one sentence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from prospector.register_lint import Problem, _err, _warn, _words, sentences

__all__ = [
    "house_style_metrics",
    "check_house_style",
    "extract_quotes",
    "MIN_QUOTE_WORDS",
    "MAX_SENTENCE_WORDS",
]

#: R1's ceiling as the spec states it. `register_lint.LONG_SENTENCE_WORDS` is 25 and is the
#: number that actually blocks; this one exists so a receipt can report both, because a
#: corpus can sit under one and over the other and "which limit" is then a real question.
MAX_SENTENCE_WORDS = 28

#: Q1. Eight words is the spec's floor for a quote to be a quote rather than a fragment.
MIN_QUOTE_WORDS = 8

# ---------------------------------------------------------------------------
# R4 — parallel constructions of four or more items
# ---------------------------------------------------------------------------
#
# "a, b, c, and d". Three commas before the conjunction means four items. The spec calls a
# four-item list the strongest single tell of generated prose, and the mechanism it names is
# visible in the corpus: the model runs out of content before it runs out of rhythm, so the
# fourth item is where invented vocabulary appears.
#
# The comma count is taken between the first item and the conjunction rather than across the
# sentence, so a sentence with an unrelated subordinate clause earlier does not read as a
# longer list than it is.
_LIST_RE = re.compile(
    r"(?:[^,;:()]+,\s+){3,}(?:and|or)\s+[^,;:()]+", re.I)

# ---------------------------------------------------------------------------
# R5 — a figure with no source in the same sentence
# ---------------------------------------------------------------------------
#
# A figure is a digit carrying a unit: a percentage, a currency amount, a scaled number, or a
# bare integer of three digits or more. A bare "5" is excluded deliberately -- "5 staff",
# "the 5 checks" and "section 5" are not the claims this rule is about, and including them
# made the rule fire on its own headings.
_FIGURE_RE = re.compile(
    r"(?<![\w.])(?:[£$€]\s?\d[\d,.]*\s?(?:k|m|bn|billion|million|thousand)?"
    r"|\d[\d,.]*\s?%"
    r"|\d[\d,.]*\s?(?:k|m|bn|billion|million|thousand)\b"
    r"|\d{3,}(?![\d.]))", re.I)

#: R5 DOES NOT GRADE A DATA LINE. The rule asks whether a CLAIM names its source; a P&L row
#: is not a claim, its numbers derive from assumptions the model states above them, and there
#: is no external source to name. Wired without this, the check reported four findings
#: against the clean pack fixture, every one of them a financial-model line —
#: `- In: £500 - Cost of making and delivering it (12%): £60 - Everything else it takes to
#: run: £200 - **Left over: £240**`. A rule that fires on every financial model is a rule
#: the reader learns to skip. Three or more figures in one segment, or a markdown table row:
#: that is arithmetic being shown, not a claim being made.
_DATA_LINE_FIGURES = 3
_TABLE_ROW_RE = re.compile(r"\|.*\|")

#: A URL is DELETED before a sentence exists: `register_lint.sentences` runs `_normalise`,
#: which substitutes every URL with a space (`register_lint.py:261`) so a link cannot inflate
#: a word count. That is right for measuring register and fatal for R5 — a sentence carrying
#: a figure and a citation link would arrive here with the link gone and read as unsourced.
#: So a URL is replaced with a WORD before splitting, and the word is what R5 looks for.
#: Proven by `test_a_figure_with_a_link_in_the_sentence_passes`, which failed against a
#: regex matching `https?://` — text this module never receives.
_URL_TOKEN = " CITEDURL "
_URL_SUB_RE = re.compile(r"\]\(\s*https?://[^)\s]*\)?|https?://\S+", re.I)

#: What counts as naming a source IN THE SENTENCE, for R5. Deliberately generous: a false
#: negative costs a figure that keeps the source it already had, while a false positive nags
#: a writer to cite something already cited, which is what gets a linter switched off.
_SOURCE_RE = re.compile(
    r"(\bCITEDURL\b|\[\d+\]|\bsources?\b|\baccording to\b|\breported\b|\breports\b"
    r"|\bsays\b|\bsaid\b|\bpublished\b|\bsurveys?\b|\bfigures?\s+from\b"
    r"|\bdata\s+from\b|\bper\s+[A-Z])", re.I)

# ---------------------------------------------------------------------------
# R6 — a quantity word with no quantity
# ---------------------------------------------------------------------------
#
# The spec's list, plus `many`, `several` and `various`, which measured 451 hits between
# them on the corpus against the spec list's 131. A word is only a violation when its own
# sentence carries no digit at all: "numerous" beside a figure is a stylistic choice, while
# "numerous" alone is a number the writer did not have.
_VAGUE_RE = re.compile(
    r"\b(numerous|a trail of|a fraction of|dozens of|significantly|significant"
    r"|substantially|substantial|considerable|many|several|various)\b", re.I)
_ANY_DIGIT = re.compile(r"\d")

# ---------------------------------------------------------------------------
# R8 — a sentence opening on a relative pronoun
# ---------------------------------------------------------------------------
#
# This is the defect the founder read off the live sample page: a reporting verb was
# stripped from "The passages show that A, that B, and that C" and the surviving
# complementisers reported to a verb that was no longer in the sentence. `pack_floors`
# fixes the cause; this catches whatever else produces the shape.
#
# "That is" and "That said" are excluded: both are ordinary English openers with a real
# antecedent, and neither is the orphan this rule exists for.
_ORPHAN_OPEN_RE = re.compile(
    r"^(That|Which|And that|So that)\b(?!\s+(is|was|said|way|much|aside)\b)")

# ---------------------------------------------------------------------------
# R10 — a prediction, or a competitor's behaviour, asserted flat
# ---------------------------------------------------------------------------
#
# The spec calls this the most damaging category, and the reason is the proposition: on a
# source-or-die storefront, one unsourced claim about the future costs more than a hundred
# clumsy sentences. Two live examples from the corpus, both verbatim:
#
#   "Late copiers cannot catch up because the data compounds with every contract."
#   "The point competitors cannot match is the installer referral relationship with ..."
#
# A hit is suppressed when the sentence names a source, because "Gartner forecasts X" is a
# sourced prediction and the spec permits exactly that.
_PREDICTION_RE = re.compile(
    r"\b(cannot catch up|can(?:not|'t) match|will not be able to|won't be able to"
    r"|late (?:copiers|entrants|movers)|competitors? (?:cannot|can't|will|would|never)"
    r"|(?:no one|nobody) (?:can|will|could)|is guaranteed to|will inevitably"
    r"|there is no way (?:for|that))\b", re.I)

# ---------------------------------------------------------------------------
# Q1-Q3 — quotes
# ---------------------------------------------------------------------------
#
# Page furniture. Every token here is something a scraper picks up from chrome rather than
# from the body of a page. "Logo", "Pros & Cons" and "Review 20xx" are the spec's own
# examples, taken off the Capterra card that shipped on the sample page.
_FURNITURE_RE = re.compile(
    r"(\bLogo\b|Pros\s*&\s*Cons|Pros and Cons|Review\s+20\d\d|Features,\s*Integrations"
    r"|\bCookie(s)?\s+(policy|settings|notice)|Accept all|Skip to (?:main )?content"
    r"|Sign in\b|Subscribe to\b|Privacy Policy|All rights reserved|Read more\b"
    r"|\bMenu\b|\bNavigation\b|\bBreadcrumb)", re.I)

#: Q2. Two shapes of splice, both seen live. A sentence-final full stop with no space before
#: a capital is a page title welded to its body ("...Cons.Payapps is..."); an ellipsis inside
#: a quote is two passages joined by the retrieval layer.
_SPLICE_GLUED = re.compile(r"[a-z]{2}\.[A-Z][a-z]")
_SPLICE_ELLIPSIS = re.compile(r"(\.\.\.|…)")

#: A quote must parse as a sentence or a clean clause. The decidable half of that: it starts
#: on something that can begin a sentence, and it does not begin on a conjunction or a
#: dangling preposition.
_QUOTE_BAD_OPEN = re.compile(
    r"^(and|or|but|that|which|with|of|for|to|in|on|at|by|from|as|than|because)\b", re.I)

#: Markdown blockquote lines, and inline runs inside typographic or straight double quotes.
#: Single quotes are NOT read as quotation: an apostrophe in "subcontractors' money" would
#: open one and never close it.
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.+)$", re.M)
_INLINE_QUOTE_RE = re.compile(r"[“\"]([^“”\"]{12,})[”\"]")


def extract_quotes(text: str) -> List[str]:
    """Every span in `text` presented to the buyer as somebody else's words.

    Blockquotes first, then inline runs, deduplicated. The 12-character floor on inline runs
    is not the Q1 length rule -- it keeps ordinary emphasis in double quotes from being
    graded as a citation, which would make Q1 fire on the word "free".
    """
    out: List[str] = []
    seen = set()
    for chunk in _BLOCKQUOTE_RE.findall(text or ""):
        q = " ".join(chunk.split()).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    for chunk in _INLINE_QUOTE_RE.findall(text or ""):
        q = " ".join(chunk.split()).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _quote_problem(q: str) -> Optional[str]:
    """The first rule `q` breaks, as a buyer-facing reason, or None."""
    words = len(_words(q))
    if _FURNITURE_RE.search(q):
        return (f"Q3: page furniture, not evidence — {_FURNITURE_RE.search(q).group(0)!r}. "
                f"Cut the quote; a listing page's chrome is not a source.")
    if _SPLICE_GLUED.search(q) or _SPLICE_ELLIPSIS.search(q):
        return ("Q2: two fragments spliced into one quote. Paraphrase and cite instead.")
    if words < MIN_QUOTE_WORDS:
        return (f"Q1: {words} words. A quote is a complete grammatical unit of at least "
                f"{MIN_QUOTE_WORDS}. Paraphrase and cite instead.")
    if _QUOTE_BAD_OPEN.match(q):
        return ("Q1: the quote opens mid-clause. Start it where the sentence starts, or "
                "paraphrase.")
    return None


def house_style_metrics(texts: Mapping[str, str]) -> Dict[str, Any]:
    """Measure a pack against the house spec. Pure measurement — it rules on nothing.

    Returns rates as well as hits, because the actuators are rates: one long sentence in a
    twelve-thousand-word pack is not the defect the founder described, and a threshold set
    on a count would either block everything or nothing depending on pack length.
    """
    hits: Dict[str, List[Dict[str, str]]] = {
        "R4": [], "R5": [], "R6": [], "R8": [], "R10": [], "quotes": []}
    total_sentences = 0
    total_words = 0
    over_28 = 0
    quotes_seen = 0

    for name in sorted(texts):
        text = texts[name]
        if not isinstance(text, str) or not text.strip():
            continue
        # THE PROSE RULES NEVER GRADE A QUOTED PASSAGE. R5, R6 and R10 ask whether the
        # WRITER sourced a figure, hedged a number or asserted a prediction; a cited source
        # doing any of those is the source's business, and on a source-or-die storefront the
        # one thing we may not do is edit it. So blockquote lines are cut from the prose
        # corpus and read only by the Q rules, which exist precisely to grade quotation.
        # An inline quote inside a sentence stays in the prose corpus: the writer chose to
        # run it into their own clause, so it is their sentence.
        # See `_URL_SUB_RE`: a link must survive `sentences()` as a word or R5 cannot see it.
        prose_only = _BLOCKQUOTE_RE.sub(" ", text)
        for s in sentences(_URL_SUB_RE.sub(_URL_TOKEN, prose_only)):
            total_sentences += 1
            n = len(_words(s))
            total_words += n
            if n > MAX_SENTENCE_WORDS:
                over_28 += 1
            if _LIST_RE.search(s):
                hits["R4"].append({"where": name, "sentence": s[:220]})
            figures = _FIGURE_RE.findall(s)
            if (figures and not _SOURCE_RE.search(s)
                    and len(figures) < _DATA_LINE_FIGURES
                    and not _TABLE_ROW_RE.search(s)):
                hits["R5"].append({"where": name, "sentence": s[:220]})
            m = _VAGUE_RE.search(s)
            if m and not _ANY_DIGIT.search(s):
                hits["R6"].append({"where": name, "sentence": s[:220],
                                   "token": m.group(0).lower()})
            if _ORPHAN_OPEN_RE.match(s):
                hits["R8"].append({"where": name, "sentence": s[:220]})
            if _PREDICTION_RE.search(s) and not _SOURCE_RE.search(s):
                hits["R10"].append({"where": name, "sentence": s[:220]})

        for q in extract_quotes(text):
            quotes_seen += 1
            reason = _quote_problem(q)
            if reason:
                hits["quotes"].append({"where": name, "quote": q[:200], "reason": reason})

    def rate(n: int) -> float:
        return round(n / total_sentences, 4) if total_sentences else 0.0

    return {
        "sentences": total_sentences,
        "words": total_words,
        "quotes": quotes_seen,
        "over_28_words": over_28,
        "over_28_rate": rate(over_28),
        "four_item_lists": len(hits["R4"]),
        "four_item_list_rate": rate(len(hits["R4"])),
        "unsourced_figures": len(hits["R5"]),
        "unsourced_figure_rate": rate(len(hits["R5"])),
        "vague_quantities": len(hits["R6"]),
        "orphan_openers": len(hits["R8"]),
        "flat_predictions": len(hits["R10"]),
        "bad_quotes": len(hits["quotes"]),
        "hits": hits,
    }


def check_house_style(
        texts: Mapping[str, str], *,
        metrics: Optional[Dict[str, Any]] = None,
        block_predictions: bool = False,
        block_quotes: bool = False,
        max_over_28_rate: float = 0.0,
        max_four_item_list_rate: float = 0.0,
        max_unsourced_figure_rate: float = 0.0) -> List[Problem]:
    """Report house-spec defects in a pack's buyer-visible prose.

    Every actuator is off by default and every rate of 0.0 means "measure, never block" --
    a rate cannot exceed 0.0, so a pack can never be stranded by a threshold nobody set on
    purpose. That is the same contract `register_lint.check_register` carries.

    Two actuators are booleans rather than rates, because their defects are decidable rather
    than statistical: a prediction asserted as fact is wrong once, not wrong at a rate, and
    a quote that is page furniture is not evidence at any frequency.
    """
    m = metrics if metrics is not None else house_style_metrics(texts)
    problems: List[Problem] = []

    pred = _err if block_predictions else _warn
    for hit in m["hits"]["R10"]:
        problems.append(pred(
            "house_style", hit["where"],
            f"R10: a claim about the future or about a competitor, with no source in the "
            f"sentence: {hit['sentence']!r}"))

    quote = _err if block_quotes else _warn
    for hit in m["hits"]["quotes"]:
        problems.append(quote(
            "house_quote", hit["where"], f"{hit['reason']} Quote: {hit['quote']!r}"))

    for hit in m["hits"]["R8"]:
        problems.append(_warn(
            "house_style", hit["where"],
            f"R8: sentence opens on a relative pronoun, which usually means its verb was "
            f"cut: {hit['sentence']!r}"))
    for hit in m["hits"]["R4"]:
        problems.append(_warn(
            "house_style", hit["where"],
            f"R4: four or more items in one construction; the last is where invented "
            f"vocabulary appears: {hit['sentence']!r}"))
    for hit in m["hits"]["R6"]:
        problems.append(_warn(
            "house_style", hit["where"],
            f"R6: {hit['token']!r} with no figure in the sentence. Give the number or cut "
            f"it: {hit['sentence']!r}"))
    for hit in m["hits"]["R5"]:
        problems.append(_warn(
            "house_style", hit["where"],
            f"R5: a figure with no source named in the same sentence: {hit['sentence']!r}"))

    # The rates. Reported as errors only above a threshold somebody set deliberately.
    if m["sentences"] >= 40:
        if max_over_28_rate > 0 and m["over_28_rate"] > max_over_28_rate:
            problems.append(_err(
                "house_rate", "pack",
                f"R1: {m['over_28_rate']:.0%} of sentences run over {MAX_SENTENCE_WORDS} "
                f"words, over the {max_over_28_rate:.0%} allowed"))
        if max_four_item_list_rate > 0 and m["four_item_list_rate"] > max_four_item_list_rate:
            problems.append(_err(
                "house_rate", "pack",
                f"R4: {m['four_item_list_rate']:.0%} of sentences carry a four-item list, "
                f"over the {max_four_item_list_rate:.0%} allowed"))
        if (max_unsourced_figure_rate > 0
                and m["unsourced_figure_rate"] > max_unsourced_figure_rate):
            problems.append(_err(
                "house_rate", "pack",
                f"R5: {m['unsourced_figure_rate']:.0%} of sentences carry a figure with no "
                f"source, over the {max_unsourced_figure_rate:.0%} allowed"))
    return problems

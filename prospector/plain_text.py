"""Markdown -> plain text, for fields the storefront renders WITHOUT a markdown parser.

The pack `.md` files are markdown and must stay markdown. But a subset of the same strings
also travels to the Store Catalog as *metadata* (`proofPoint`, `sampleExtract`, `headline`,
`subhead`, `oneLine`, ...), and the storefront prints those as literal text — e.g.
`store_platform/src/Store.Web/src/pages/pack/[id].tsx:469` renders `{line}` straight into JSX.
So a rationale bullet like `- **buyer intent:** growers search for ...` reaches a buyer with the
asterisks showing.

This module is the boundary converter. It strips markup only; it never rewords, truncates
meaning, or invents text, so it cannot manufacture a claim that the moat did not verify.

`_EMPHASIS` deliberately requires non-word delimiters for `_`/`__` so that snake_case tokens
that legitimately appear in buyer-facing prose (`buyer_intent`, `who_pays`) survive intact.

Backslash escapes (`\\*`, `\\[`, ...) are protected as numeric sentinels before the inline
passes run and restored from those sentinels just before return, so a stray emphasis run
cannot eat a backslash-escaped character mid-stream.
"""
from __future__ import annotations

import re
from typing import Iterable, List

# Inline constructs, applied in this order. Images before links (an image is a link with a
# leading `!`), links before emphasis (link text may itself be bold).
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
_CODE_FENCE = re.compile(r"^\s*```.*$", re.MULTILINE)
_CODE_SPAN = re.compile(r"`([^`]+)`")
_EMPHASIS = (
    re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL),
    re.compile(r"\*\*(.+?)\*\*", re.DOTALL),
    re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL),
    re.compile(r"(?<![\w_])___(.+?)___(?![\w_])", re.DOTALL),
    re.compile(r"(?<![\w_])__(.+?)__(?![\w_])", re.DOTALL),
    re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL),
    re.compile(r"~~(.+?)~~", re.DOTALL),
)
# Backslash escapes are protected as `\x00<ord>\x00` so the inline passes cannot eat them.
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
_SENTINEL = "\x00"           # never appears in pack text
_UNSENTINEL = re.compile("\x00(\\d{1,3})\x00")
# Setext heading underlines (`====` / `----`) and thematic breaks (`***`, `___`, `---` of
# any length). Both render as horizontal rules in plain text; both must be dropped.
_SETEXT_OR_HRULE = re.compile(r"^\s{0,3}(?:=+|-{2,}|(?:\*\s*){3,}|(?:_\s*){3,})\s*$")
# Reference link definitions `[id]: url` — metadata, not prose.
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S+.*$")
# Full-reference link form `[text][id]` — its target has been (or will be) defined elsewhere.
_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
# Inline HTML: `<br>` (becomes a newline) and any other tag (just stripped). The storefront
# prints raw text, so neither form is safe to leave behind.
_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
# Leading block markers: heading hashes, blockquote arrows, bullet and ordered-list markers.
_BLOCK_PREFIX = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d{1,3}[.)]\s+)")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$")
_WS = re.compile(r"[ \t]+")


def to_plain_text(
    text: str | None, *, collapse: bool = False, keep_link_urls: bool = False
) -> str:
    """Strip markdown markup, preserving the words verbatim.

    collapse=True folds all whitespace (including newlines) to single spaces — use it for
    single-line catalog fields such as `proofPoint` or `subhead`.

    keep_link_urls=True renders `[text](url)` as `text (url)` instead of dropping the target.
    Use it wherever the URL is the evidence — a sourced excerpt loses its point if the link
    it cites disappears.

    Backslash escapes are protected across the inline passes and restored at the end so
    that stray emphasis runs cannot eat them.
    """
    if not text:
        return ""
    s = _CODE_FENCE.sub("", str(text))
    # Protect backslash escapes BEFORE any inline pass so a stray `*`/`_` cannot swallow
    # the character the backslash was shielding.
    s = _ESCAPED.sub(lambda m: _SENTINEL + str(ord(m.group(1))) + _SENTINEL, s)
    # Drop lines that are pure setext underlines, thematic breaks, or reference-link
    # definitions BEFORE the emphasis loop, otherwise a standalone `***` becomes a stray `*`.
    s = "\n".join(
        line for line in s.split("\n")
        if not _SETEXT_OR_HRULE.match(line)
        and not _REF_DEF.match(line)
        and not _TABLE_RULE.match(line)
    )
    # Inline HTML — `<br>` becomes a newline, everything else is just dropped.
    s = _BR_TAG.sub("\n", s)
    s = _HTML_TAG.sub("", s)
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1 (\2)" if keep_link_urls else r"\1", s)
    s = _REF_LINK.sub(r"\1", s)
    s = _CODE_SPAN.sub(r"\1", s)
    for pattern in _EMPHASIS:
        # Repeat until stable: nested emphasis (`**bold _and_ italic**`) needs more than one pass.
        prev = None
        while prev != s:
            prev = s
            s = pattern.sub(r"\1", s)

    lines: List[str] = []
    for line in s.split("\n"):
        if _TABLE_RULE.match(line):
            continue
        line = _BLOCK_PREFIX.sub("", line)
        lines.append(_WS.sub(" ", line).strip())
    s = "\n".join(lines)

    # Restore the backslash escapes last, after every inline pass is done.
    s = _UNSENTINEL.sub(lambda m: chr(int(m.group(1))), s)

    if collapse:
        return " ".join(s.split())
    # Never leave more than one blank line behind after stripping block markers.
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# ─────────────────────────────── the publish pass ────────────────────────────
#
# `to_plain_text` above answers "is this markdown?". The pass below answers a different
# question: "is this fit for a stranger to read?". Five defect classes were measured on the
# live kill log (400 published entries, 2026-08-07) and every one of them reached either a
# public web page or a pack `.md` a buyer downloads:
#
#   1. bare passage ids   34 entries   "Passages 9fa810377aee4d8f and 10481947a354f7f9 show"
#   2. empty citations     6 entries   "...orthotic insoles (,,), and budget alternatives"
#   3. truncation         54 entries   "...planting dates and……"
#   4. confidence floats  14 entries   "gates are all UNVERIFIABLE at confidence 0.0"
#   5. register            2 entries   "the target buyer profile is a broke body"
#
# It lives HERE, in the generator, and not in the storefront, because the pack documents are
# opened offline from a zip: a web-side repair would leave the paid deliverable dirty.
#
# CORRECTNESS RULE FOR EVERY PATTERN BELOW: match on word boundaries and anchored shapes,
# never a bare substring. This repo has been burned twice by the opposite — a bare HTTP-code
# substring benched a live provider (memory `substring-http-codes-bench-a-live-brain.md`),
# and an unanchored `/ape/` matched "shape". So the id pattern requires exactly sixteen
# hex characters BETWEEN WORD BOUNDARIES plus at least one digit, and the register denylist
# is `\b`-anchored on both ends of a two-word phrase.

# A passage id as the engine mints it: exactly 16 lowercase hex chars (`source_id` in
# models.py, and the same width `tools/make_kill_log.CITATION_REF` resolves). Two fences keep
# it off ordinary English:
#   * `\b...\b` with the length pinned inside a lookahead, so a 17+ char hex run does NOT
#     match a 16-char prefix of itself, and a hex-looking substring of a longer word cannot
#     match at all;
#   * at least one DIGIT is required, so an all-letter word in the a-f alphabet (the only
#     way English could collide — "deafbeefacedface") is never eaten. Real 16-char English
#     words ("responsibilities", "characteristics") contain letters outside a-f and cannot
#     match under any circumstance.
# `(?-i:...)` pins the character class case-SENSITIVE even though several of the patterns
# below carry `re.I` for their English words. Without it, `re.I` leaked into the class and
# "The reference 9FA810377AEE4D8F appears" lost an uppercase token that is somebody's
# contract reference, not one of our ids. The engine only ever mints lowercase.
_HEX = r"\b(?=(?-i:[0-9a-f]{16})\b)(?=(?-i:[0-9a-f]*[0-9]))(?-i:[0-9a-f]{16})\b"
_HEX_ID = re.compile(_HEX)

# Words that only ever LABEL a reference. They carry no argument, so they leave with the id.
_REF_LABEL = r"(?:source[_\s]?ids?|citations?|references?|refs?|e\.g\.,?)"
# Words that are ALSO ordinary prose ("the passages show ..."). The word stays, the id goes.
_REF_NOUN = r"(?:passages?|sources?)"

# Separator between ids in a list, including the Oxford form ", and ". It has to swallow the
# WHOLE separator: leaving "and" behind is how `Passages <id>, <id>, and <id> show` became
# "The passagesand show" in a first cut of this pass.
_SEP = r"(?:\s*(?:,|;|&)\s*(?:and\s+)?|\s+and\s+)"
# `citation: <id>` / `source_id: <id>, <id>` — label and ids both go.
_LABELLED_IDS = re.compile(rf"\s*\b{_REF_LABEL}\s*[:,]?\s*(?:{_HEX}{_SEP}?)+", re.I)
# `Passages <id>, <id> and <id> show ...` — the noun survives so the sentence still reads.
_NOUN_IDS = re.compile(rf"\b({_REF_NOUN})\b\s*[:,]?\s*(?:{_HEX}{_SEP}?)+", re.I)
# `Passages,, and show ...` — an UPSTREAM stripper already took the ids out and left the
# separators standing (live corpus, 2026-08-07). Two or more separators in a row is the tell;
# one comma is ordinary English ("the sources, and the evidence, show") and never fires here.
_ORPHAN_NOUN_SEPS = re.compile(rf"\b({_REF_NOUN})\b(?:\s*[,;]){{2,}}\s*(?:and\s+|&\s+)?(?=[a-z])",
                               re.I)
# `<id>: 'quoted evidence'` — the id is a label for what follows.
_ID_LABEL = re.compile(rf"{_HEX}\s*:\s*")
# `... at <id>)` / `from <id> ($1.3B)` — the preposition dangles if only the id is removed.
_PREPOSED_ID = re.compile(rf"\s*\b(?:at|from|in|of|via|per|by|see|cf\.?)\s+{_HEX}", re.I)
# `; <id> confirms ...` — the id is the SUBJECT of its clause, so deleting it leaves a verb
# with nothing in front of it. Only fires at a clause opening followed by a lowercase word,
# which is why "spec sheet <id> and an Iowa memo" (mid-phrase) falls through to plain removal.
_SUBJECT_ID = re.compile(
    rf"(^|[.;:]\s+|\b(?:and|but|while|whereas|although|though|because|since|where|when)\s+)"
    rf"(?:{_HEX})(?=\s+[a-z])",
    re.I,
)
_BARE_ID = re.compile(rf"\s*{_HEX}\s*")
# A bracketed span, non-nested, capped so a runaway match cannot swallow a paragraph.
_BRACKETED = re.compile(r"(\s*)([(\[])([^()\[\]]{0,600}?)([)\]])")
# An UNCLOSED reference run at the very end of a truncated string:
# "... complaints [eaebe2a03a52cfc4, 577baafcaff7fa6f, 99…"
_OPEN_ID_TAIL = re.compile(r"\s*[(\[][^()\[\]]*?[0-9a-f]{8,}[^()\[\]]*$")
# Defect class 2 verbatim: a citation marker whose ids were stripped upstream, leaving the
# punctuation behind — `(,)`, `(,,)`, `(,,,,)`, `()`. The leading space goes with it so the
# repair cannot orphan a space before the next comma.
_EMPTY_MARKER = re.compile(r"\s*[(\[][\s,;:]*[)\]]")

# Confidence figures. A bare `0.0` in marketing prose reads as "0% confident" and argues
# against the verdict it is attached to, so the DEFAULT is to omit it (the QA report inside
# the pack is the one place it may stay — see `publish_pass(keep_confidence_figures=True)`).
# Every pattern demands the word AND a number adjacent to it, so "Freelancer Confidence
# Index", "treated in confidence" and "Confidence is tempered because..." never fire.
#
# The last row is the same figure wearing no label: `(pain_reality 0.43, payer_solvency 0.4)`.
# It is safe to anchor on because the gate names are a CLOSED vocabulary the engine owns
# (kill_filter / verify), so the rule cannot fire on a number in ordinary prose; the gate name
# survives and only the float leaves.
_GATE = (r"(?:pain_reality|payer_solvency|value_durability|incumbency|distribution"
         r"|route_to_market|legality|currency|buyer_intent|source_or_die|adversarial_decisive)")
_QUALIFIER = r"(?:very\s+|fairly\s+|relatively\s+)?(?:low|high|moderate|modest|weak|strong)?\s*"
_CONFIDENCE: tuple[tuple[re.Pattern[str], str], ...] = (
    # PARENTHESISED float, e.g. "..., with a low confidence (0.43)." Every other row here
    # demands the digits be ADJACENT to the word; a `(` between them is enough to slip past all
    # of them, which is how `store_platform/.../kill-log.json` row 392 published a raw 0.43 on
    # 2026-08-07 with the pass already live. The qualifier is consumed too, so removing the
    # figure cannot strand "with a low ." in the sentence. Must precede the adjacency rules.
    (re.compile(r"\s*,?\s*\b(?:at|of|with|to|on|around)\s+(?:only\s+|just\s+|about\s+)?(?:a\s+)?"
                rf"{_QUALIFIER}confidence\s*\(\s*\d(?:\.\d+)?\s*\)", re.I), ""),
    # Same figure with no preposition in front: "confidence (0.43)" keeps the word, drops the number.
    (re.compile(r"(\bconfidence\b)\s*\(\s*\d(?:\.\d+)?\s*\)", re.I), r"\1"),
    (re.compile(r"\s*\b(?:at|of|with|to|on|around)\s+(?:only\s+|just\s+|about\s+)?(?:a\s+)?"
                r"confidence\s+(?:of\s+)?\d(?:\.\d+)?\b", re.I), ""),
    (re.compile(r"\s*\b(?:at|of|with|to|around)\s+(?:only\s+|just\s+|about\s+)?"
                r"\d(?:\.\d+)?\s+confidence\b", re.I), ""),
    (re.compile(r"\s*,?\s*\bconf\b\.?\s*(?:of\s+)?\d(?:\.\d+)?\b", re.I), ""),
    (re.compile(r"\s*\bconfidence\s*[:=]?\s*(?:of\s+)?\d(?:\.\d+)?\b", re.I), ""),
    (re.compile(r"\s*\b\d(?:\.\d+)?\s+confidence\b", re.I), ""),
    (re.compile(rf"\b({_GATE})\b\s*[:=]?\s+\d(?:\.\d+)?\b"), r"\1"),
)
_HAS_CONFIDENCE_FIGURE = re.compile(
    r"\bconf(?:idence)?\b\.?\s*[:=]?\s*\(?\s*\d(?:\.\d+)?\b", re.I)
# The one-sentence scale note the QA report must carry if it keeps its figures.
CONFIDENCE_SCALE_NOTE = (
    "Confidence below is on a 0 to 1 scale: 0 means no retrieved passage spoke to the "
    "check either way, and 1 means the retrieved passages settled it outright."
)

# WHY THIS EXISTS: the verdict brain writes about real buyer groups, and two published kill
# reasons described one as "a broke body". Carers are one of our largest buyer segments, so a
# phrase like that is a reputational liability on a public page and is nobody's idea of an
# analyst's register. The replacement says the same measured thing without the sneer.
#
# A MAPPING, not a one-off replace, because this class of phrase recurs: add a row, get the
# rule everywhere prose ships. Both ends are `\b`-anchored and the surrounding quotes are
# absorbed so `'broke body'` does not keep its scare-quotes; the anchoring is what stops a
# rule ever firing inside a longer innocent word.
REGISTER_DENYLIST: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\"'‘’“”]?\bbroke\s+bod(?:y|ies)\b"
                r"[\"'‘’“”]?", re.I),
     "buyer group under severe financial strain"),
    (re.compile(r"[\"'‘’“”]?\bskint\b[\"'‘’“”]?", re.I),
     "under acute financial strain"),
)

# Sentence boundary. `e.g.` / `i.e.` are excluded, otherwise a truncated reason gets cut back
# to an abbreviation and loses its argument. A decimal ("£2.99") cannot match: the dot has to
# be followed by whitespace or end-of-string.
_SENTENCE_END = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\.)[.!?][\"'’)\]]?(?=\s|$)")
_ENDS_SENTENCE = re.compile(r"[.!?][\"'’)\]]?$")
# A trailing ellipsis, including one wearing a closing quote: `...your testing...'`. Without
# the optional closer, `_SENTENCE_END` read that final `.'` as a finished sentence and the
# published entry kept its ellipsis.
_TRAILING_ELLIPSIS = re.compile(r"[\s,;:]*(?:…|\.\.\.)+[\s.…]*[\"'’)\]]?\s*$")


def _strip_confidence(text: str) -> str:
    for pattern, replacement in _CONFIDENCE:
        text = pattern.sub(replacement, text)
    return text


def _strip_ids(text: str) -> str:
    """Remove passage ids and repair the sentence they were embedded in."""
    text = _LABELLED_IDS.sub("", text)
    text = _NOUN_IDS.sub(_noun_only, text)
    text = _ORPHAN_NOUN_SEPS.sub(_noun_only, text)
    text = _ID_LABEL.sub("", text)
    text = _PREPOSED_ID.sub("", text)
    text = _SUBJECT_ID.sub(lambda m: f"{m.group(1)}the passage", text)
    return _BARE_ID.sub(" ", text)


def _noun_only(match: re.Match[str]) -> str:
    """`Passages <id> and <id> directly show` -> `The passages directly show`.

    Sentence-initial and capitalised, the bare noun ("Passages directly show") reads as a
    dropped article, so the article is restored. Mid-sentence the noun is returned as-is.
    """
    noun = match.group(1)
    before = match.string[: match.start()].rstrip()
    at_sentence_start = not before or bool(_ENDS_SENTENCE.search(before))
    if at_sentence_start and noun[:1].isupper():
        noun = f"The {noun.lower()}"
    # The match may have eaten the separator that stood between the noun and the next word;
    # without this, "Passages <id>, <id>, and <id> show" collapses to "The passagesand show".
    tail = match.string[match.end():]
    return f"{noun} " if tail[:1].isalnum() else noun


def _clean_bracketed(text: str) -> str:
    """Clean inside every bracketed span; drop the span when only its ids were holding it up.

    `(citation: 9fa8...)` and `(passages 9fa8..., 1048...)` are pure references and go whole.
    `(FairPay, source 6ee8...)` and `(9c2c..., HunterLab)` name something real, so the span
    survives with the reference machinery taken out.
    """
    def repl(match: re.Match[str]) -> str:
        lead, opener, inner, closer = match.groups()
        if not _HEX_ID.search(inner):
            return match.group(0)
        cleaned = _tidy(_strip_ids(inner))
        # A label word left holding the door open once its id is gone: "(FairPay, source)".
        cleaned = re.sub(rf"[,;]?\s*\b(?:{_REF_LABEL}|{_REF_NOUN})\b\s*:?\s*$", "", cleaned,
                         flags=re.I)
        cleaned = re.sub(rf"^\s*\b(?:{_REF_LABEL}|{_REF_NOUN})\b\s*:?\s*[,;]?\s*", "", cleaned,
                         flags=re.I)
        cleaned = _tidy(cleaned).strip(" ,;:")
        if not re.search(r"[0-9A-Za-z]", cleaned):
            return ""
        return f"{lead}{opener}{cleaned}{closer}"

    return _BRACKETED.sub(repl, text)


def _tidy(text: str) -> str:
    """Repair the punctuation a removal leaves behind, without touching the words.

    Run to a FIXED POINT, because these rules feed each other: `model, and,, show` (an
    upstream stripper's leftovers) needs the doubled-comma rule, then the dangling-`and`
    rule, then the doubled-comma rule again. One pass each left `model,, show`, which is
    also how the pass failed its own idempotence test.
    """
    for _ in range(4):
        cleaned = _tidy_once(text)
        if cleaned == text:
            break
        text = cleaned
    return text


def _tidy_once(text: str) -> str:
    text = _EMPTY_MARKER.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"([(\[])[\s,;:]+", r"\1", text)
    text = re.sub(r"[\s,;:]+([)\]])", r"\1", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;])(?:\s*[,;])+", r"\1", text)
    # ", ." after a clause was removed from the end of a sentence: "free rivals,."
    text = re.sub(r"[,;:]+([.!?])", r"\1", text)
    text = re.sub(r"\s+\b(and|or)\b\s*([,.;:])", r"\2", text)
    text = re.sub(r"([,;])\s*\b(?:and|or)\b\s*([,;])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _repair_truncation(text: str, *, require_sentence: bool) -> str:
    """End on a complete sentence, or return "" so the caller can omit the field.

    A trailing ellipsis is always treated as truncation. `require_sentence=True` additionally
    treats "does not end in terminal punctuation" as truncation — that is the right test for
    prose that is meant to be sentences (a kill reason, a pack paragraph) and the WRONG test
    for a headline or a bullet, which legitimately ends on a noun.

    Never cuts mid-word and never leaves an ellipsis behind: the only cut point is the end of
    a sentence. If no sentence survives, the honest answer is nothing at all — a fragment
    rendered under a buy button is worse than an absent field.
    """
    stripped = text.rstrip()
    if not stripped:
        return ""
    truncated = bool(_TRAILING_ELLIPSIS.search(stripped)) or (
        require_sentence and not _ENDS_SENTENCE.search(stripped)
    )
    if not truncated:
        return stripped
    stripped = _TRAILING_ELLIPSIS.sub("", stripped).rstrip()
    ends = list(_SENTENCE_END.finditer(stripped))
    if not ends:
        return ""
    return stripped[: ends[-1].end()].rstrip()


def publish_pass(
    text: str | None,
    *,
    sentences: bool = False,
    keep_confidence_figures: bool = False,
) -> str:
    """The single gate every engine-authored string passes before a buyer can read it.

    Runs the five repairs described at the top of this section — passage ids, empty citation
    markers, truncation, confidence floats, register — and nothing else. It never rewords a
    claim, never adds a fact, and never invents a citation, so it cannot manufacture something
    the moat did not verify; it only removes machinery that was never meant to be published
    and repairs the punctuation that removal leaves behind.

    sentences=True enforces a complete-sentence ending and returns "" when none survives.
    Use it for prose that is meant to be sentences (a kill reason, a pack paragraph); leave
    it False for headlines, card lines and bullets, which legitimately end on a noun.

    keep_confidence_figures=True leaves `confidence 0.42` in place. It exists for exactly one
    surface, the QA report inside the pack, where the figure is the subject rather than a
    stray internal — and `publish_pass_document` pairs it with `CONFIDENCE_SCALE_NOTE` so the
    number never appears without the scale that makes it mean something.

    Idempotent by construction: every rule removes a shape it cannot reintroduce, so
    publish_pass(publish_pass(x)) == publish_pass(x). `tests/unit/test_publish_pass.py` pins
    that, along with the word-boundary non-firing cases.
    """
    if not text:
        return ""
    s = str(text)
    if not keep_confidence_figures:
        s = _strip_confidence(s)
    s = _OPEN_ID_TAIL.sub("", s) if _HEX_ID.search(s) or "…" in s else s
    s = _clean_bracketed(s)
    s = _strip_ids(s)
    for pattern, replacement in REGISTER_DENYLIST:
        s = pattern.sub(replacement, s)
    s = _tidy(s)
    s = _repair_truncation(s, require_sentence=sentences)
    return s.strip()


_FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")


def publish_pass_document(
    markdown: str | None, *, keep_confidence_figures: bool = False
) -> str:
    """`publish_pass` over a markdown DOCUMENT, preserving its structure.

    Pack documents are opened offline from the zip, so they are the one surface a web-side
    repair can never reach — which is why the pass is installed in the generator.

    Applied line by line rather than to the whole string: a document is not one sentence, and
    a whole-string truncation repair would cut a ten-page build spec back to its last full
    stop. Leading indentation is preserved (it is list nesting), fenced code blocks are passed
    through untouched, and a line is only truncation-repaired when it actually ends in an
    ellipsis — a heading has no full stop and is not truncated.

    keep_confidence_figures=True is the QA-report path: figures stay, and the one-sentence
    scale note is inserted once so no number appears without its scale.
    """
    if not markdown:
        return ""
    out: List[str] = []
    in_fence = False
    for line in str(markdown).split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or not line.strip():
            out.append(line)
            continue
        indent = line[: len(line) - len(line.lstrip())]
        cleaned = publish_pass(
            line.strip(), keep_confidence_figures=keep_confidence_figures
        )
        if cleaned:
            out.append(indent + cleaned)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if keep_confidence_figures and _HAS_CONFIDENCE_FIGURE.search(body) \
            and CONFIDENCE_SCALE_NOTE not in body:
        lines = body.split("\n")
        # After the document's own title, so the note reads as a preface and not as the doc.
        at = 1 if lines and lines[0].lstrip().startswith("#") else 0
        lines[at:at] = ["", f"_{CONFIDENCE_SCALE_NOTE}_"] if at else [f"_{CONFIDENCE_SCALE_NOTE}_", ""]
        body = "\n".join(lines)
    return body


# Engine bookkeeping prefixes on a kill `reason`. The page renders the gate separately, so
# the restatement is noise. Two formats are in the corpus (older `Gate '...' fired —` and
# newer `It failed on: ... (`gate`) —`), plus the verdict brain's own `refuted (conf 0.4):`.
_REASON_PREFIXES = (
    re.compile(r"^Gate '[^']+' fired\s*[—–-]\s*"),
    re.compile(r"^It failed on:.*?\(`[^`]+`\)\s*[—–-]\s*"),
    re.compile(r"^refuted \(conf [\d.]+\):\s*"),
)


def nodash(s: str | None) -> str:
    """Strip em-dashes and en-dashes — the universal AI writing tell.

    Replaces them with `, ` (the most natural English substitution) and collapses any leftover
    whitespace. Compound words like "out-of-hours" and "slip-resistance" are preserved because
    the regex only matches dashes surrounded by whitespace.

    A dash BETWEEN DIGITS is a range, and a comma changes what it means. Measured against the
    live catalogue on 2026-08-06, 13 fields depend on that: "Mothers 25-45", "Gen Z gig workers
    (18-27)", "for 2025-2026". Rewriting those as "Mothers 25, 45" states something the source
    did not, which on a source-or-die storefront is the worse of the two defects. Those become
    a hyphen, which drops the tell and keeps the range.

    Lives here, next to the publish pass, so the kill log and the pack documents cannot
    diverge on it. Kept in lock-step with the TypeScript `nodash()` in
    `store_platform/src/Store.Web/src/lib/text.ts`.
    """
    if not s:
        return ""
    s = re.sub(r"(\d)\s*[—–]\s*(\d)", r"\1-\2", s)
    s = s.replace("—", ", ").replace("–", ", ")
    s = re.sub(r"\s+-\s+", ", ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Tidy up the spaces the dash substitution leaves behind: "Brand , X" → "Brand, X".
    return re.sub(r"\s+([.,;])", r"\1", s)


def clean_reason(reason: str | None) -> str:
    """A kill dossier's `reason`, ready to publish — or "" when nothing publishable survives.

    Shared by `tools/make_kill_log.py` and any other surface that renders a verdict, so the
    kill log and the pack documents cannot drift apart on what "clean" means. Returns "" when
    the reason is a fragment with no complete sentence; the caller drops the entry rather than
    printing half an argument.
    """
    text = str(reason or "").strip()
    for prefix in _REASON_PREFIXES:
        text = prefix.sub("", text).strip()
    return publish_pass(nodash(text), sentences=True)


def plain_lines(lines: Iterable[str] | None, *, drop_empty: bool = True) -> List[str]:
    """to_plain_text(collapse=True) over a list of single-line fields (e.g. sampleExtract)."""
    out = [to_plain_text(x, collapse=True) for x in (lines or [])]
    return [x for x in out if x] if drop_empty else out


def has_markup(text: str | None) -> bool:
    """True when `text` still carries markdown that a plain-text renderer would expose.

    Used by the tests and the publish-time assertion — the check that would have caught
    `**buyer intent:**` before it reached a storefront.
    """
    if not text:
        return False
    return to_plain_text(text, collapse=True) != " ".join(str(text).split())

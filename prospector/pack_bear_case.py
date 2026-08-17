"""What would sink this — the case against, collected in one place and made in full.

WHY THIS FILE EXISTS
--------------------
Everything that could kill the venture is already in the pack, and that is the problem: it is
scattered as a hedge inside each plan. Measured 2026-08-14 across 62 live packs, the phrase
"assumption — unverified" appears a median of 11 times per pack and 58 times in the worst one.
Past about the fifth, a hedge stops reading as honesty and starts reading as a template — the
reader skims them, and the one that actually mattered goes past with the rest.

A newspaper does not sprinkle the counter-argument through the piece. It gives it a section,
states it at full strength, and lets the reader weigh it. That is what this is.

WHAT IT DOES NOT DO
-------------------
It does not invent risks. There is no generic "the market may not adopt it" paragraph, because
nothing retrieved supports one and a risk register padded with universal risks hides the
specific ones. Every entry here is a check the engine actually ran and could not settle, a
check the evidence went AGAINST, or a weakness the financial model named about its own inputs.
A dossier where all seven checks came back supported and the model named no weakness produces
"" and no section, which is the honest output.

The counterpart to `pack_reference.py`: that one holds the evidence, this one holds the case
against. Both render from the dossier with no model call, which is what lets either be
backfilled onto a pack already sold.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List

from .dossier import check_label, link_inline_citations, source_index

FILENAME = "What_Would_Sink_This.md"
TITLE = "What would sink this"

# The heading `artifacts._render_financial_model` writes above the model's own stated
# weaknesses (`artifacts.py:425`). Read rather than re-derived: those strings come from the
# model's structured JSON and are already claim-checked, so lifting them here moves text that
# has passed the gates instead of generating text that has not.
_FIN_WEAKNESS_HEADING = "### Where this is weakest"
_FIN_UNKNOWN_HEADING = "### What we could not work out"
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _section_body(markdown: str, heading: str) -> str:
    """The body under one exact heading, up to the next heading of any level.

    Returns "" when the heading is absent, which is the common case: the financial model only
    prints a weaknesses block when the model supplied one.
    """
    text = str(markdown or "")
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    nxt = _HEADING.search(rest)
    return (rest[:nxt.start()] if nxt else rest).strip()


#: A list item in any of the shapes a model writes one: `-`, `*`, `+`, `•`, or an ordered
#: item up to `99.` / `99)`. Leading whitespace is stripped first, so an indented sub-bullet
#: is an item like any other — it is content, and the alternative was dropping it.
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(?P<text>.+?)\s*$")


def _bullets(body: str) -> List[str]:
    """The discrete items in a weaknesses block, however the model chose to format it.

    PROSE IS CONTENT — 2026-08-15
    -----------------------------
    This used to recognise `- `, `* ` and single-digit ordered items and nothing else, and
    return `[]` for anything else. `[]` then meant "there is nothing here" to `_financial_block`
    — while `financial_md_after_absorbing` deleted the block anyway, because it only looked for
    the heading. A model that wrote its weaknesses as a paragraph instead of a list therefore
    had that paragraph DELETED from `04_Financial_Model.md` and never copied into the bear
    case: claim-checked prose that existed in the dossier, was paid for, and appeared in
    neither shipped document, under a pointer telling the reader to go read it in a section
    that did not contain it.

    The formatting fix (`+ `, `10.`–`99.`, `1)`, indented items) and the prose fallback are the
    same fix from two directions: this function's answer is now "what is in this block",
    never "was it formatted the way I expected". A paragraph comes back as one item.
    """
    out: List[str] = [m.group("text").strip()
                      for m in (_LIST_ITEM.match(ln) for ln in body.splitlines())
                      if m is not None]
    out = [b for b in out if b]
    if out:
        return out
    # No list markers at all: fall back to paragraphs, blank-line separated, each one item.
    # Lines within a paragraph are joined the way markdown itself would reflow them.
    paragraphs = [" ".join(block.split())
                  for block in re.split(r"\n\s*\n", body.strip())]
    return [p for p in paragraphs if p]


def _refuted_block(rows: Iterable[Any], index: dict) -> List[str]:
    rows = list(rows)
    if not rows:
        return []
    out = ["## Where the evidence went against us", "",
           "These are not doubts. We looked, and what we found argues the other way. Read these "
           "before you spend a weekend on this.", ""]
    for chk in rows:
        name = str(getattr(chk, "check_name", "") or "")
        out.append(f"### {check_label(name)}")
        out.append("")
        rationale = link_inline_citations(
            str(getattr(chk, "rationale", "") or "").strip(), index)
        if rationale:
            out += [rationale, ""]
    return out


def _unproven_block(rows: Iterable[Any], index: dict) -> List[str]:
    rows = list(rows)
    if not rows:
        return []
    out = ["## What we could not settle, and what it would take", "",
           "Each of these is a thing that has to be true for the venture to work, and a thing we "
           "searched for and did not find enough to rule either way. They are the questions to "
           "answer first, in the order they would kill you.", ""]
    for chk in rows:
        name = str(getattr(chk, "check_name", "") or "")
        out.append(f"### {check_label(name)}")
        out.append("")
        rationale = link_inline_citations(
            str(getattr(chk, "rationale", "") or "").strip(), index)
        if rationale:
            out += [rationale, ""]
        # Three, not five, and framed as a head start rather than as a log of what our
        # retrieval did. These are the only raw engine strings left anywhere in the pack, and
        # they earn it: the question is genuinely open, settling it is genuinely the reader's
        # next move, and knowing what has already been tried is what stops them repeating it.
        # `pack_reference` printed the same list under the same headings until 2026-08-15.
        queries = [str(q).strip() for q in (getattr(chk, "queries", None) or []) if str(q).strip()]
        if queries:
            out += ["We looked and came back short. If you want to settle it, these are the "
                    "angles already tried, so you can start past them:", ""]
            out += [f"- {q}" for q in queries[:3]]
            out.append("")
    return out


def _absorbed_blocks(financial_md: str) -> "dict[str, List[str]]":
    """Which of the financial model's own blocks this section takes, and the lines it takes them as.

    ONE DEFINITION, TWO CALLERS — 2026-08-15
    ----------------------------------------
    The copy side and the delete side used to answer the question separately and could
    disagree, which is the only way content can be lost: `_financial_block` copied a block
    only when `_bullets` parsed an item out of it, while `financial_md_after_absorbing`
    deleted the block whenever the HEADING existed. A prose weaknesses block satisfied the
    second condition and not the first, so it was deleted from `04_Financial_Model.md` and
    never written into the bear case — with the model left pointing at it under "Where these
    numbers are softest … set out in **What would sink this**".

    Both callers now read this. A block absent from the returned mapping was not copied, and
    therefore is not deleted; a block present was copied verbatim, and is. The two conditions
    are no longer two conditions.
    """
    taken: "dict[str, List[str]]" = {}
    weakest = _bullets(_section_body(financial_md, _FIN_WEAKNESS_HEADING))
    if weakest:
        taken[_FIN_WEAKNESS_HEADING] = [f"- {w}" for w in weakest] + [""]
    unknown = _section_body(financial_md, _FIN_UNKNOWN_HEADING)
    if unknown:
        taken[_FIN_UNKNOWN_HEADING] = [
            "It also could not work out the following, and left them blank rather than "
            "filling them in:", "", unknown, ""]
    return taken


def _financial_block(financial_md: str) -> List[str]:
    taken = _absorbed_blocks(financial_md)
    if not taken:
        return []
    out = ["## Where the numbers are softest", "",
           "The arithmetic in the financial model is exact. Its INPUTS are estimates, and these "
           "are the ones it flagged about itself.", ""]
    for heading in (_FIN_WEAKNESS_HEADING, _FIN_UNKNOWN_HEADING):
        out += taken.get(heading, [])
    return out


def financial_md_after_absorbing(financial_md: str, bear_section_title: str) -> str:
    """`04_Financial_Model.md` with the two blocks this module lifted replaced by a pointer.

    `_financial_block` copies "Where this is weakest" and "What we could not work out" out of
    the financial model VERBATIM. Both documents then ship, so the buyer reads the same text
    twice: measured on pack e698149e137fc164 on 2026-08-15, "The numbers" and "What would sink
    this" shared FIFTEEN whole sentences, the largest single-pair overlap in the pack.

    Deleting the copy was the wrong direction. The bear case is where a reader goes to find out
    what could go wrong, and the softest inputs in the model belong there; the financial model
    is where they go for the arithmetic. So the content moves and the model keeps a pointer,
    which is a smaller document that has lost nothing — every sentence removed here is printed
    under "Where the numbers are softest" in the section this points at.

    Called only when `render()` returned a body. If the bear case was omitted (a thin dossier
    refutes nothing and leaves nothing unproven) the financial model keeps its own weaknesses,
    because in that case nothing absorbed them.

    What may be deleted is decided by `_absorbed_blocks`, the same function `_financial_block`
    copies from — so a block can never be deleted here without having been copied there. See
    that function for the prose block this lost.
    """
    text = str(financial_md or "")
    if not text:
        return text
    taken = _absorbed_blocks(text)
    if not taken:
        return text
    for heading in (_FIN_WEAKNESS_HEADING, _FIN_UNKNOWN_HEADING):
        if heading not in taken:
            continue
        start = text.find(heading)
        if start < 0:
            continue
        rest = text[start + len(heading):]
        nxt = _HEADING.search(rest)
        end = start + len(heading) + (nxt.start() if nxt else len(rest))
        text = text[:start] + text[end:]
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip()
    return text + (
        "\n\n### Where these numbers are softest\n\n"
        "The arithmetic above is exact. Its inputs are estimates, and the model flagged some "
        f"of its own as weaker than others. Those are set out in **{bear_section_title}**, "
        "with everything else that could go wrong, so the case against is in one place rather "
        "than split across two sections.\n")


def render(dossier: Any, financial_md: str = "") -> str:
    """The case against, as markdown, or "" when the dossier names nothing against it.

    `financial_md` is the already-rendered `04_Financial_Model.md`, passed the same way
    `pack_card.render` takes it: the model's weaknesses are text that has already been through
    the claim-check, so lifting them beats regenerating them.
    """
    checks = list(getattr(dossier, "checks", None) or [])
    index = source_index(dossier) if checks else {}

    refuted = [c for c in checks if _verdict(c) == "refuted"]
    unproven = [c for c in checks if _verdict(c) == "unverifiable"]

    body: List[str] = []
    body += _refuted_block(refuted, index)
    body += _unproven_block(unproven, index)
    body += _financial_block(financial_md)
    if not body:
        return ""

    out = [f"# {TITLE}", "",
           "Every pack we publish has cleared the same gates, and clearing them is not the same "
           "as being safe. This section is the case against, made at full strength and in one "
           "place, so it is not something you have to assemble yourself out of caveats.", "",
           "Nothing here is new. It is what the checks in this pack could not prove, what they "
           "found against, and what the model said about its own numbers, collected.", "",
           "---", ""]
    out += body
    out += ["---", "",
            "If one of these turns out to be true, this is not a business, and you want to know "
            "that in week two rather than in month six. The last section of this pack turns the "
            "worst of them into something you can test in thirty days.", ""]
    return "\n".join(out).rstrip() + "\n"

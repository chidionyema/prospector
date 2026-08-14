"""The pack's action document — `05_First_Week_Checklist.md`.

THE DEFECT
----------
Measured 2026-08-13 across every bundle on disk: **127 of 127 first-week checklists were the
same six lines**, differing only in the title and a quoted buyer sentence. The template
(`pack_floors.first_week_checklist_md`) is wired unconditionally at `bridge.py:1536`, so a
model-written checklist was never a possibility — the floor WAS the document.

Worse than generic, it was written in the engine's vocabulary, which `prompts/artifacts.md`
forbids for every other document in the pack:

    1. Re-read the QA report kill/pass gates and list every SUPPORTED citation URL.
    2. Confirm the buyer (`who_pays`) matches reality for your market — dossier says: ...

A buyer who paid £320 for a plan was handed instructions to audit our own audit trail, with a
snake_case field name printed in a code span.

WHY THIS IS DERIVED RATHER THAN WRITTEN BY A MODEL
--------------------------------------------------
The same constraint that shaped `pack_card` and `pack_table`: whatever fixes this must also
reach the packs already sold. A model call cannot — it costs money per pack, it is not
reproducible, and it cannot run against a zip. So every specific below comes from structure
that is already on disk: a field on the candidate, a verdict on a check, or a `##` heading in
one of the pack's own plan documents. Nothing is scraped out of model prose, because prose
shape varies per pack and a heuristic that misreads it puts a nonsense instruction in the one
document the buyer is meant to ACT on.

Where a specific is missing the step is dropped, not guessed. A nine-step plan that is nine
real steps beats a ten-step plan with a blank in it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

FILENAME = "05_First_Week_Checklist.md"

BUILD_SPEC = "01_Blueprint_BuildSpec.md"
GTM_PLAN = "02_Marketing_Plan_GTM.md"
OPS_PLAN = "03_Operations_Plan.md"
FINANCIAL_MODEL = "04_Financial_Model.md"

_HEADING_RE = re.compile(r"^##\s+(?P<body>\S.*?)\s*$", re.M)
# "## 4. The council file" — the numbering is the document's own, and quoting a heading with
# its number inside a sentence reads as a footnote marker.
_LEADING_NUM_RE = re.compile(r"^\d+[.)]\s*")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")

# Openers. Every plan document starts by restating what the thing is, which is the one section
# a buyer standing in week one does not need pointed out to them.
_OPENER_RE = re.compile(
    r"what this is|in one paragraph|in one line|what we are selling|what you are running|"
    r"who it is for|overview|introduction|summary",
    re.I)


def _plain(text: Any) -> str:
    return _EMPHASIS_RE.sub("", str(text or "")).strip()


# The GTM step tells the buyer to pick ONE CHANNEL, so it may only quote a heading that is
# actually about channels. "The buyer, stated precisely" is a working heading by every test
# above and quoting it there would instruct someone to pick a channel out of a section that
# names no channel — a specific detail that is worse than the generic sentence it replaced.
_CHANNEL_RE = re.compile(
    r"where|channel|launch|reach|acquisi|go after|outreach|first 90|distribution|find them",
    re.I)


def first_working_heading(markdown: str, must_match: "re.Pattern[str] | None" = None
                         ) -> Optional[str]:
    """The first `##` heading that tells the reader to DO something, or None.

    Headings are used rather than sentences on purpose: a heading is structure the renderer
    wrote, so reading one back is deterministic. Model prose is not, and a checklist that
    quotes half a sentence out of a paragraph is how a pack ends up instructing its buyer to
    do something the document never said.
    """
    for raw in _HEADING_RE.findall(str(markdown or "")):
        body = _LEADING_NUM_RE.sub("", _plain(raw))
        if not body or _OPENER_RE.search(body):
            continue
        if must_match is not None and not must_match.search(body):
            continue
        return body
    return None


def _first_sentence(text: Any, cap: int = 200) -> str:
    body = " ".join(_plain(text).split())
    if not body:
        return ""
    m = re.search(r"^(.{20,%d}?[.!?])\s" % cap, body + " ")
    if m:
        return m.group(1).strip()
    return body if len(body) <= cap else ""


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _labels(checks: Any, verdict: str) -> List[str]:
    from .dossier import check_label
    return [check_label(str(getattr(c, "check_name", "") or ""))
            for c in (checks or []) if _verdict(c) == verdict]


def render(dossier: Any, docs: Optional[Dict[str, str]] = None) -> str:
    """The fortnight plan as markdown, or "" when there is nothing specific to say.

    "" hands the caller back to `pack_floors.first_week_checklist_md`. That is the honest
    fallback: a generic template is a poor document, but a document with "read the section on
    ." in it is a broken one, and this renderer only earns its place when the pack it is
    describing actually gave it something to point at.
    """
    docs = docs or {}
    cand = getattr(dossier, "candidate", None)
    title = str(getattr(cand, "title", "") or "").strip()
    one_liner = str(getattr(cand, "one_liner", "") or "").strip()
    # The whole description when it does not break into a sentence inside the cap. Measured on
    # disk: 24 of 75 buyer descriptions are a single clause longer than 200 characters, and
    # returning "" for those dropped a THIRD of the catalogue back onto the generic template —
    # a shortening rule quietly deciding which packs get the good document.
    who_raw = " ".join(_plain(getattr(cand, "who_pays", "")).split())
    who = _first_sentence(who_raw) or who_raw
    checks = list(getattr(dossier, "checks", None) or [])

    build_head = first_working_heading(docs.get(BUILD_SPEC, ""))
    gtm_head = first_working_heading(docs.get(GTM_PLAN, ""), _CHANNEL_RE)
    ops_head = first_working_heading(docs.get(OPS_PLAN, ""))
    unproven = _labels(checks, "unverifiable")
    refuted = _labels(checks, "refuted")

    # The buyer is the spine of week one. Without it there is no plan worth printing and the
    # generic floor is the more honest document.
    if not who:
        return ""

    week_one: List[str] = [
        f"Find five of them and talk to all five: **{who}** Not a survey and not a poll — five "
        "conversations, in the order you can get them. If you cannot find five in a week, that "
        "is the finding, and it cost you a week instead of a year.",
    ]
    if unproven:
        rest = "" if len(unproven) < 2 else (
            " The other open questions are listed beside it: " + _join(
                [f"*{q}*" for q in unproven[1:]]) + ".")
        week_one.append(
            f"Put the question we could not answer to them directly: **{unproven[0]}** We "
            "searched and found nothing that settles it, which is why it sits in *Evidence and "
            f"Constraints* as an assumption rather than a finding.{rest} Five buyers can answer "
            "in an afternoon what the open web could not.")
    if refuted:
        week_one.append(
            "Read what the evidence says AGAINST this before you build anything — "
            f"{_join([f'*{q}*' for q in refuted])} came back the wrong way. It is at the top of "
            "*Evidence and Constraints*, marked to be read first, and it is the cheapest place "
            "in this pack to change your mind.")
    if FINANCIAL_MODEL in docs:
        week_one.append(
            f"Say the price out loud to those five. It is in *{FINANCIAL_MODEL}*, with the "
            "arithmetic behind it. Nobody flinching means it is too low; everybody flinching "
            "means the model is wrong — and either way you know in week one, for nothing.")
    if GTM_PLAN in docs:
        where = f"“{gtm_head}” in *{GTM_PLAN}*" if gtm_head else f"*{GTM_PLAN}*"
        week_one.append(
            f"Pick ONE channel out of {where} and ignore the rest until it works. A plan that "
            "runs three channels badly in week one tells you nothing about any of them.")

    week_two: List[str] = []
    if build_head:
        week_two.append(
            f"Cut “{build_head}” in *{BUILD_SPEC}* down to what one person can finish "
            "in five days, and build only that. Everything you removed is still written down; "
            "none of it is lost by starting smaller.")
    else:
        week_two.append(
            f"Build the smallest version described in *{BUILD_SPEC}* — the one that answers "
            "whatever your five buyers asked about most — and nothing beyond it.")
    if ops_head:
        week_two.append(
            f"Work through *{OPS_PLAN}* from “{ops_head}” onwards while there is "
            "no customer waiting. Every hour of it is cheaper now than it is the day a real "
            "one arrives.")
    week_two += [
        "Ask one of the five to pay. Today's version, today's price. A yes is the only "
        "evidence in this pack that we could not go and get for you.",
        "Write down what changed your mind. You now know things about this buyer that nothing "
        "we retrieved could tell us, and week three should be built on those, not on this "
        "document.",
    ]

    lines: List[str] = [f"# Your first fortnight — {title}" if title else "# Your first fortnight",
                        ""]
    if one_liner:
        lines += [one_liner, ""]
    lines += [
        "Ten working days, in order. Every step points at the document in this pack that tells "
        "you how, so nothing here needs reading twice.",
        "",
        "## Week one — find out whether anybody pays",
        "",
    ]
    lines += [f"{i}. {s}" for i, s in enumerate(week_one, 1)]
    lines += ["", "## Week two — put it in front of them", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(week_two, len(week_one) + 1)]
    lines += [
        "",
        "---",
        "",
        "Nothing above assumes you finished the step before it perfectly. If week one says no, "
        "stop — that is the pack having done its job, and it is why the price is what it is "
        "rather than what a month of building would have cost you.",
        "",
    ]
    return "\n".join(lines)


def _join(items: List[str]) -> str:
    """"a, b and c" — the pack's own prose voice, never "a, b, c"."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"

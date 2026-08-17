"""P4: the evidence, explained once, in one place.

THE DEFECT, MEASURED (2026-08-14, 62 live packs read from R2 — not `publish/bundles/`)
--------------------------------------------------------------------------------------
The founder's reading of `8d5e24fbe6c1f5d3`: "we sell the same 2,500 words three times."
Verbatim repetition turned out to be a poor way to see it — identical sentences across
different files account for only 0.4% of the corpus (3,398 of 795,429 words). The repetition
is a PARAPHRASE, which is the expensive kind: the same fact rewritten in fresh words in each
plan, so a reader cannot skim past it.

Two measurements find it:

  * near-duplicate paragraphs across different files (token Jaccard >= 0.45): 28,186 words,
    3.5% of the corpus — e.g. `08b22037fc2afc07`, build spec vs ops plan, jac 0.65:
    "The legal ground under this is real and citable. The Care Act 2014 places a duty on
    councils to assess any adult..." / "The legal ground under the product is solid and
    published. The Care Act 2014 gives adults a legal entitlement...";
  * the same CITED SOURCE leaned on by all three plan files: **median 11 per pack, max 29**
    (62 of 62 packs). That is the six-themes-three-times pattern the founder described,
    generalised — and worse than six.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
It renders one document from the DOSSIER — the machine-readable evidence record — so the
shared constraints and their sources are stated once, in the buyer's words, with every source
listed a single time. No model call, nothing invented: every line here is a field that already
exists on disk, which is what makes it safe to backfill onto packs already sold.

It does NOT rewrite the three plans. Removing a paraphrase from prose is a judgement about
meaning, and this repo does not make those deterministically. Stopping the plans from
re-explaining what this document now holds is a GENERATION change (the prompts), and it takes
effect on new packs only. Said plainly rather than implied: this file makes the evidence
readable once; it does not shorten the pack a buyer already owns.

THE ASSUMPTIONS REGISTER MOVED OUT OF THIS FILE (2026-08-15)
------------------------------------------------------------
It was rendered here AND by `pack_bear_case._unproven_block` — same `unverifiable` rows, same
`check_label` headings, same rationales, same searches, in two sections of the same pack. It
now lives only in the bear case, because an unproven assumption is an argument about whether
to build and that is what "What would sink this" is for, while this document is the appendix.

The reasoning that shaped it still holds and still applies there: the programme doc asks for
"assumption, cost to confirm, test, cost of test", and the money column is deliberately absent.
Nothing in the dossier prices what a test costs, so a priced column would be a number we made
up — the exact failure the catalogue exists to avoid (`source-or-die`). What IS on disk is the
searches the engine actually ran, so the register says what would settle a question instead of
guessing what settling it costs.

Shape-agnostic by construction: every read is a `getattr`, because two objects reach here — a
live `Dossier` from the generator and the `SimpleNamespace` tree `pack_manifest.dossier_from_dict`
builds for the backfill, whose verdicts are plain strings.
"""
from __future__ import annotations

from typing import Any, Iterable, List

from . import admissibility, models
from .dossier import _host, check_label, link_inline_citations, source_index

FILENAME = "Evidence_and_Constraints.md"

_VERDICT_LINE = {
    "supported": "The evidence backs this up.",
    "refuted": "The evidence goes against this. Read this one before you build.",
    "unverifiable": "We looked and could not settle it. Treat it as an assumption.",
}


def _verdict(chk: Any) -> str:
    return str(getattr(getattr(chk, "verdict", None), "value", getattr(chk, "verdict", "")) or
               "").strip().lower()


def _sources_of(chk: Any) -> List[Any]:
    return list(getattr(chk, "sources", None) or [])


def _source_line(src: Any) -> str:
    url = str(getattr(src, "url", "") or "").strip()
    if not url:
        return ""
    label = admissibility.provenance_label(url)
    name = _host(url) or url
    return f"- [{name}]({url})" + (f" — {label}" if label else "")


def render(dossier: Any) -> str:
    """The consolidated evidence document as markdown, or "" when there is nothing to say.

    An empty string is the correct output for a dossier with no checks: an evidence document
    listing no evidence reads, to a buyer, as a pack that was never verified — strictly worse
    than shipping no such document at all. The caller treats "" as "do not add this file".
    """
    checks = list(getattr(dossier, "checks", None) or [])
    if not checks:
        return ""

    index = source_index(dossier)
    cand = getattr(dossier, "candidate", None)
    title = str(getattr(cand, "title", "") or "").strip()

    out: List[str] = []
    out.append("# Evidence and Constraints")
    out.append("")
    if title:
        out.append(f"Everything the plans in this pack lean on, for **{title}**, gathered in one "
                   "place so you read it once.")
    else:
        out.append("Everything the plans in this pack lean on, gathered in one place so you "
                   "read it once.")
    out.append("")
    out.append("The build spec, the go-to-market plan and the operations plan each apply these "
               "findings to their own job. None of them re-argues the evidence. It is here.")
    out.append("")

    settled = [c for c in checks if _verdict(c) in ("supported", "refuted")]

    if settled:
        out.append("---")
        out.append("")
        out.append("## What we checked, and what it means for you")
        out.append("")
        for chk in settled:
            name = str(getattr(chk, "check_name", "") or "")
            out.append(f"### {check_label(name)}")
            out.append("")
            out.append(_VERDICT_LINE.get(_verdict(chk), ""))
            out.append("")
            rationale = link_inline_citations(
                str(getattr(chk, "rationale", "") or "").strip(), index)
            if rationale:
                out.append(rationale)
                out.append("")
            lines = [ln for ln in (_source_line(s) for s in
                                   models.distinct_sources([chk])) if ln]
            if lines:
                out.append("Where this came from:")
                out.append("")
                out.extend(lines)
                out.append("")

    # The assumptions register USED to be emitted here as well.
    #
    # `pack_bear_case._unproven_block` walks the same `unverifiable` rows, prints the same
    # `check_label` heading, the same rationale and the same searches. Two sections of the same
    # pack rendering the same rows from the same fields is not a paraphrase problem that needs
    # judgement — it is one list, printed twice, and it was the largest structural duplicate in
    # the pack the founder read on 2026-08-15.
    #
    # The bear case keeps it. An unproven assumption is an argument about whether to build, and
    # that is what "What would sink this" is for; this document is the evidence appendix. The
    # ownership is safe rather than conditional: `pack_bear_case.render` returns a body whenever
    # `unproven` is non-empty (`pack_bear_case.py:193-196`), so the register cannot vanish by
    # both sections deciding the other has it.
    out.extend(_all_sources(checks))
    return "\n".join(out).rstrip() + "\n"


def _all_sources(checks: Iterable[Any]) -> List[str]:
    """One list, one entry per page, whatever the check that fetched it.

    `source_id` is minted per retrieval, so the same URL fetched for two checks used to appear
    twice — `lulu.com/create/print-books` was listed twice in the pack the founder read.
    `models.distinct_sources` is the single definition of "one source", shared with the cover
    stat so the two can never disagree.
    """
    sources = [s for s in models.distinct_sources(list(checks))
               if str(getattr(s, "url", "") or "").strip()]
    if not sources:
        return []
    out = ["---", "", "## Every source, once", "",
           f"{len(sources)} pages, each listed a single time. Where a page is a forum post or a "
           "statistics aggregator rather than a primary record, it says so.", ""]
    for src in sources:
        line = _source_line(src)
        if line:
            out.append(line)
    out.append("")
    return out

#!/usr/bin/env python3
"""Bake one grounded PASS dossier into a static JSON for the free "Report #00" page.

The storefront on Fly has no endpoint that serves a full verification dossier (the detail
DTO only carries a few sample lines). The free sample needs the WHOLE thing: every check,
its verdict, its rationale, and its clickable sources. Rather than add an API surface, we
bake the chosen dossier into src/data/sample-report.json at build time. It is one fixed,
real report, so static is correct and reproducible.

Source-or-die: only real dossier content is emitted. Nothing is invented.

Usage:  python tools/make_sample_report.py <pack_id>
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

OUT = "store_platform/src/Store.Web/src/data/sample-report.json"

# Human, refutational framing for each gate (matches the storefront's voice).
CHECK_LABELS = {
    "buyer_intent": "Is anyone actually trying to buy this?",
    "pain_reality": "Is the pain real, or imagined?",
    "pain_acuity": "Is the pain real, or imagined?",
    "value_durability": "Will the value last, or evaporate?",
    "incumbency": "Have the big players already won?",
    "incumbent": "Have the big players already won?",
    "payer_solvency": "Can the payer actually pay?",
    "distribution": "Is there a route to reach the market?",
    "route_to_market": "Can it actually reach buyers?",
    "currency": "Is real money flowing here today?",
    "claims_verifiable": "Do its own claims hold up to checking?",
    "legality": "Is there a legal landmine?",
    "moat": "Is there anything to defend?",
}


# One implementation, imported rather than re-typed. This file used to carry its own copy, and it
# had already drifted: it lacked the numeric-range rule, so "for 2025-2026" came out of the kill log
# with its range intact and out of the free report as "for 2025, 2026". Three twins were declared
# "byte-for-byte identical" (see the header of
# `store_platform/src/Store.Web/src/lib/text.ts`) and only two of the three were.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from make_kill_log import CITATION_REF, citation_ids, nodash  # noqa: E402

from prospector.plain_text import publish_pass  # noqa: E402


def readable(text: str, *, sentences: bool) -> str:
    """A dossier string as a buyer may see it: the publish pass, then the dash rule.

    THE GATE THIS PAGE WAS SKIPPING
    -------------------------------
    `plain_text.publish_pass` describes itself as "the single gate every engine-authored string
    passes before a buyer can read it" (:429). This tool never called it. `resolve_citations`
    below handles the ONE shape it was written for — a parenthesised or bracketed run of full
    16-hex ids — and everything else the pass repairs went straight to the page::

        $ .venv/bin/python - <<'PY'   # on the baked fixture, 2026-08-15
        ... 30 bracket ids across 9 of 9 check rationales, e.g. pain_reality -> 5, incumbency -> 5
        ... incumbency ends: "...chasing retention on its due date in the UK [c33885f45"

    Those rationales are the body text of the free sample and of the home page's evidence strip.
    A 16-hex blob in brackets reads as a fabricated citation to anyone who does not know the
    internal format, which is the exact impression the page exists to prevent — the same finding
    `resolve_citations` records for the premortem panel, arrived at again one field over.

    `sentences=True` is for prose that is meant to be sentences and enforces a complete ending;
    it returns "" when none survives, so it is wrong for the short candidate fields (a one-liner
    legitimately ends on a noun) and right for a rationale.

    `nodash` runs AFTER, not before: the pass repairs punctuation left behind by its own
    removals, and the dash rule is a house style applied to whatever text survives that.
    """
    return nodash(publish_pass(text or "", sentences=sentences))


def sources_by_id(dossier: dict) -> dict[str, dict]:
    """Every retrieved source in the dossier, keyed by the hash its prose cites."""
    index: dict[str, dict] = {}
    for check in dossier.get("checks") or []:
        for source in check.get("sources") or []:
            sid, url = source.get("source_id"), source.get("url")
            if sid and url:
                index[sid] = source
    return index


def resolve_citations(text: str, index: dict[str, dict]) -> tuple[str, list[dict]]:
    """Lift inline `(a95e55366ce78462)` hashes out of prose and return them as real sources.

    The free report is the page whose entire argument is "every claim is traceable, open one and
    check it". It shipped the raw hashes: "...(a95e55366ce78462)... (e646bf90d84a4530,
    a95e55366ce78462)" printed literally in the premortem panel, which has no citation chips under
    it, so the one block with visible references was the one block whose references were unusable
    (desktop-sample-full.png, 2026-08-06). To a reader who does not know the internal format, a
    16-hex blob in parentheses reads as a fabricated citation, which is the precise impression this
    page exists to prevent.

    A hash that resolves becomes a chip alongside the prose. One that does not is dropped rather
    than shown unresolved, the same rule `make_kill_log.py` already applies.
    """
    found: list[dict] = []
    seen: set[str] = set()
    for sid in citation_ids(text):
        src = index.get(sid)
        if not src or src.get("url") in seen:
            continue
        seen.add(src["url"])
        found.append(source_chip(src))
    cleaned = CITATION_REF.sub("", text or "")
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    # `readable` after the chip lift, not instead of it: this function's job is to turn ids into
    # CHIPS, and the publish pass's job is everything else an engine-authored string carries.
    # Running both is safe because the pass is idempotent by construction (plain_text.py:446).
    return readable(cleaned, sentences=True), found


# A first line that is a document TITLE, versus one that is the first heading inside the document.
# `source_label` took the first non-empty line unconditionally, so 2 of the 11 chips on /sample read
# "INTRODUCTORY NOTES" (a section heading lifted out of an NHQB checklist PDF) and "- Sample Report"
# (a bullet), neither of which names a publisher (measured on the baked JSON, 2026-08-06). On a page
# whose argument is "open it and check", a chip the reader cannot attribute is worse than no chip.
# All-caps is the tell for a heading; one word or a stub is the tell for a fragment.
def source_title(src: dict) -> str:
    """The document's own title, or "" when the first line is a fragment rather than a title."""
    text = (src.get("text") or "").strip()
    first = next((ln.strip(" #-*•\t") for ln in text.splitlines() if ln.strip(" #-*•\t")), "")
    if not first or len(first) > 90:
        return ""
    if first.isupper() or len(first) < 12 or len(first.split()) < 2:
        return ""
    return first


def source_chip(src: dict) -> dict:
    """A citation the reader can attribute at a glance: the host, plus a title when it adds one.

    The host is never omitted. It is the part a reader can judge before clicking, and it is what
    `tools/make_kill_log.py` has always emitted (`citations[].domain`), so the two public evidence
    pages now describe a source the same way instead of one showing a domain and the other a title.
    """
    url = src.get("url", "")
    return {
        "url": url,
        "domain": urlparse(url).netloc.removeprefix("www.") or "source",
        "label": nodash(source_title(src)),
    }


def report_fields(pid: str, d: dict) -> dict:
    """Every field the storefront's evidence components read, derived from one dossier dict.

    Split out of `main` on 2026-08-15 so `tools/build_sample_fixture.py` can emit a SUPERSET of
    this shape rather than a replacement. The fixture is read by five components, not one::

        $ rg -l "data/sample-report" store_platform/src/Store.Web/src
        components/marketing/CheckSequence.tsx
        components/marketing/EvidenceRecordPanel.tsx
        components/marketing/HeroEvidenceStrip.tsx
        components/marketing/PackSpecimen.tsx
        __tests__/sampleReportData.test.ts

    `HeroEvidenceStrip` is on the HOME page. Emitting the new /sample shape alone would therefore
    have broken the homepage's evidence strip while looking like a change to /sample — which is
    what happened in draft on 2026-08-15, caught by `rg` before anything was committed. One
    function with two callers is what stops that recurring: the shape those five components read
    can no longer be dropped by editing the other generator.
    """
    c = d["candidate"]
    tags = c.get("tags", {}) or {}
    pm = tags.get("commodity_premortem")
    pm = pm if isinstance(pm, dict) else {}

    checks_out = []
    supported = 0
    total_sources = 0
    for ch in d.get("checks", []):
        v = ch.get("verdict")
        if v == "supported":
            supported += 1
        srcs, seen = [], set()  # dedup WITHIN a check so each gate shows its own citation
        for s in ch.get("sources") or []:
            url = s.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            srcs.append(source_chip(s))
        total_sources += len(srcs)
        name = ch.get("check_name", "")
        checks_out.append({
            "name": CHECK_LABELS.get(name, name.replace("_", " ").capitalize()),
            "key": name,
            "verdict": v,
            "confidence": round(float(ch.get("confidence") or 0), 2),
            "rationale": readable(ch.get("rationale", ""), sentences=True),
            "sources": srcs,
        })

    adv = d.get("adversarial") or {}
    index = sources_by_id(d)
    kill_case, kill_srcs = resolve_citations(adv.get("kill_case", ""), index)
    alt, alt_srcs = resolve_citations(
        pm.get("strongest_free_or_commodity_alternative", ""), index
    )
    durable, durable_srcs = resolve_citations(
        pm.get("why_durable_anyway", "") or pm.get("why_durable", ""), index
    )
    # One chip row under the panel: the three paragraphs argue one case and cite the same pages.
    premortem_srcs, seen_urls = [], set()
    for src in kill_srcs + alt_srcs + durable_srcs:
        if src["url"] in seen_urls:
            continue
        seen_urls.add(src["url"])
        premortem_srcs.append(src)

    return {
        "id": pid,
        "title": c.get("title"),
        # sentences=False: these three are card lines and legitimately end on a noun, so the
        # complete-sentence rule would blank them rather than clean them.
        "oneLiner": readable(c.get("one_liner", ""), sentences=False),
        "whoPays": readable(c.get("who_pays", ""), sentences=False),
        "whyNow": readable(c.get("why_now", ""), sentences=False),
        "verifiedAt": d.get("created_at"),
        "supported": supported,
        "total": len(d.get("checks", [])),
        "sourceCount": total_sources,
        "scores": d.get("score", {}).get("scores", {}),
        "premortem": {
            "strongestAlternative": alt,
            "whyDurable": durable,
            "sources": premortem_srcs,
        },
        "adversarial": {
            "killCase": kill_case,
            "decisive": bool(adv.get("decisive")),
        },
        "checks": checks_out,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: make_sample_report.py <pack_id>", file=sys.stderr)
        return 2
    pid = sys.argv[1]
    d = json.load(open(f"store/dossiers/{pid}.pass.json", encoding="utf-8"))
    report = report_fields(pid, d)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT}: {report['title']!r}  {report['supported']}/{report['total']} supported, "
          f"{report['sourceCount']} sources across {len(report['checks'])} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Bake the public kill log — the ideas the filter rejected, and the sourced reason why.

Why this exists
---------------
The storefront asks a stranger for £49 on the strength of "these survived six brutal
checks", and offers no way to see the brutality. The obvious fix is customer testimonials,
which we cannot honestly show: there are no reviews to quote, and inventing "Sarah T." is
both a lie and a criminal offence under the DMCCA 2024 fake-review provisions. Inventing
social proof on a storefront whose entire pitch is source-or-die would also be
self-refuting — a buyer who checks one claim and finds it fabricated has no reason to
believe the other forty-three.

The honest proof is the one we already own and never showed anyone: the rejects.

    kill dossiers: 960
    pass dossiers: 103

960 ideas researched and shot to publish the handful on the shelf. Every kill carries a
cited reason, because the engine's own rule is that a KILL is grounded evidence rather than
the model's opinion. That is a claim about rigour that a competitor cannot copy and a
reader can check, which is exactly what a testimonial is not.

What ships and what does not
----------------------------
Only substantive kills. 511 of the 960 fired on `min_composite`, whose reason reads
"Composite 0.0000 below threshold 3.2" — true, and worth nothing to a reader. Publishing
those would pad the page and teach visitors the log is filler. 446 kills carry a real
argument; those are the ones with something to say.

Citations are resolved, not stripped. Kill reasons reference passages by hash — "(b94f6135
b2f6fc5d)" — which is noise on a page and, worse, looks like a fake citation. Each hash is
looked up in the dossier's own retrieved sources and emitted as a real URL the reader can
open. A reference that cannot be resolved is dropped rather than shown unresolved.

Usage:  python tools/make_kill_log.py [--limit N]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

OUT = "store_platform/src/Store.Web/src/data/kill-log.json"
# The home page wants only the headline count. Importing the full log there would ship every
# entry in the home page bundle for the sake of one number, so the totals are split out.
OUT_TOTALS = "store_platform/src/Store.Web/src/data/kill-log-totals.json"
DOSSIERS = "store/dossiers"

# Gate names in the engine's vocabulary, rendered as the question the check actually asks.
# Matches the voice tools/make_sample_report.py already uses for the free report.
GATE_LABELS = {
    "adversarial_decisive": "It did not survive the adversarial pass",
    "incumbency": "Incumbents already own the space",
    "value_durability": "The value would not last",
    "moat_ungrounded": "The defensibility claim was not grounded",
    "payer_solvency": "The payer cannot actually pay",
    "legality": "There is a legal landmine",
    "route_to_market": "There is no route to reach buyers",
    "distribution": "There is no route to reach buyers",
    "source_or_die": "Its own claims could not be sourced",
    "pain_reality": "The pain was not real",
    "currency": "No real money is flowing here today",
    "buyer_intent": "Nobody is trying to buy this",
}

# Gates whose reason text is boilerplate about our own process rather than an argument about
# the market. `min_composite` (511 kills) reads "Composite 0.0000 below threshold 3.2".
# `moat_ungrounded` (43 kills) reads "no publish-critical check was grounded-supported" — only
# 14 distinct sentences across all 43, so publishing them would print the same paragraph
# thirty times. `source_or_die` (5) is the same shape: "only 0 grounded-supported check(s)
# (need 1)". All are honest and all are worthless to a reader deciding whether to trust the
# filter, and a log padded with filler argues against itself.
BOILERPLATE_GATES = {"min_composite", "moat_ungrounded", "source_or_die"}

# A kill whose whole reason is a number tells a reader nothing. This is the line between
# "we rejected it" and "here is an argument you can check".
MIN_REASON_CHARS = 160

# Safety rail, not a moral filter. These reasons are auto-generated judgements about real
# markets, and 2 of 446 currently use language like "fraud" or "illegal" about a practice.
# Neither names a company, but the cost of publishing an accusation is asymmetric against
# the value of one more entry, so they are held back for a human to clear.
ACCUSATORY = re.compile(
    r"\b(scam|fraud|fraudulent|illegal|criminal|incompeten\w*|dishonest)\b", re.I
)

# Passage references the engine embeds in prose, as (hash) or [hash], and frequently as a GROUP:
# `(de2144c0a07e8f21, b72e61d1b7222bd7)`. This pattern matched a lone hash only, so every grouped
# reference survived `_clean_reason` untouched and printed as a hex blob on the public page, in 16
# of the 60 published entries (2026-08-06). The same omission cost those entries their citation
# chips, because `findall` fed the resolver too: a grouped reference resolved to nothing, so the
# kills with the MOST supporting passages were the ones rendered with none.
CITATION_REF = re.compile(r"\s*[\(\[]\s*([0-9a-f]{16}(?:[,;]\s*[0-9a-f]{16})*)\s*[\)\]]")


def citation_ids(text: str) -> list[str]:
    """Every passage hash referenced in `text`, in order, flattened out of its groups."""
    out: list[str] = []
    for group in CITATION_REF.findall(text or ""):
        out.extend(re.split(r"[,;]\s*", group))
    return list(dict.fromkeys(out))


def nodash(s: str | None) -> str:
    """Strip em-dashes and en-dashes — the universal AI writing tell.

    Replaces them with `, ` (the most natural English substitution) and collapses
    any leftover whitespace. Compound words like "out-of-hours" and "slip-resistance"
    are preserved because the regex only matches dashes surrounded by whitespace.

    Mirrors the same pattern in tools/make_sample_report.py so the published voice
    is consistent across the kill-log and the free sample report. The post-processor
    runs at publish time, here, so the underlying dossiers and the engine's verdicts
    are untouched — no moat change, only cosmetic normalisation.

    A dash BETWEEN DIGITS is a range, and a comma changes what it means. Measured against the
    live catalogue on 2026-08-06, 13 fields depend on that: "Mothers 25-45", "Gen Z gig workers
    (18-27)", "for 2025-2026". Rewriting those as "Mothers 25, 45" states something the source
    did not, which on a source-or-die storefront is the worse of the two defects. Those become a
    hyphen, which drops the tell and keeps the range.

    Kept in lock-step with the TypeScript `nodash()` in
    `store_platform/src/Store.Web/src/lib/text.ts`.
    """
    if not s:
        return ""
    s = re.sub(r"(\d)\s*[\u2014\u2013]\s*(\d)", r"\1-\2", s)
    s = s.replace("\u2014", ", ").replace("\u2013", ", ")
    s = re.sub(r"\s+-\s+", ", ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Tidy up the spaces the dash substitution leaves behind: "Brand , X" → "Brand, X".
    return re.sub(r"\s+([.,;])", r"\1", s)


def _sources_by_id(dossier: dict) -> dict[str, str]:
    """Every retrieved source in the dossier, keyed by the hash its prose cites."""
    index: dict[str, str] = {}
    for check in dossier.get("checks") or []:
        for source in check.get("sources") or []:
            source_id, url = source.get("source_id"), source.get("url")
            if source_id and url:
                index[source_id] = url
    return index


# The engine's own `reason` field is frequently cut mid-sentence: 67 of the 636 kill dossiers with
# a substantive reason end without terminal punctuation (11%, measured 2026-08-06), e.g.
# "...so they do not offset the sol". Published raw, that put 26 of the 60 entries on the public
# page ending mid-WORD, with no ellipsis and no expand control -- on the one page whose entire job
# is to look rigorous, where it reads as broken rather than concise.
#
# Trimming to the last complete sentence is the honest repair at publish time. Fixing whatever
# truncates the verdict upstream in the engine is the real one; this only stops the storefront
# shipping the damage.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?(?=\s|$)")

# Below this share of the text, the last full stop is too early to trim to: a reason whose first
# sentence ends at 20% would lose four fifths of its argument to a cosmetic fix. Those keep their
# text and get an explicit ellipsis, which says "cut" rather than pretending to be finished.
_TRIM_KEEP_RATIO = 0.75


def _whole_sentences(text: str) -> str:
    """End on a sentence boundary, or say plainly that the text was cut."""
    stripped = text.rstrip()
    if not stripped:
        return stripped
    ends = list(_SENTENCE_END.finditer(stripped))
    if ends:
        cut = ends[-1].end()
        # A reason that already ends in punctuation hits this with cut == len and is returned whole.
        if cut >= len(stripped) * _TRIM_KEEP_RATIO:
            return stripped[:cut]
    return stripped.rstrip(",;:-") + "…"


def _clean_reason(reason: str) -> str:
    """Strip the engine's internal prefix and inline hashes, keeping only the argument.

    Two prefix formats are in the corpus — the older `Gate 'incumbency' fired — ...` and the
    newer `It failed on: Do incumbents already own this? (`incumbency`) — ...`. Both restate
    the gate, which the page renders separately, so both go. `nodash()` is applied last to
    sweep the em/en-dashes the LLM verdict uses for parenthetical clauses.
    """
    text = re.sub(r"^Gate '[^']+' fired\s*[—–-]\s*", "", reason).strip()
    text = re.sub(r"^It failed on:.*?\(`[^`]+`\)\s*[—–-]\s*", "", text).strip()
    text = re.sub(r"^refuted \(conf [\d.]+\):\s*", "", text).strip()
    text = CITATION_REF.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Last, after the citation hashes are stripped: removing a trailing "(a1b2…)" can itself leave
    # the sentence looking finished when it is not, so the boundary check has to see the final text.
    return _whole_sentences(nodash(re.sub(r"\s+([.,;])", r"\1", text)))


def build(limit: int) -> dict:
    kills, passes = [], 0
    for path in glob.glob(f"{DOSSIERS}/*.pass.json"):
        passes += 1
    for path in glob.glob(f"{DOSSIERS}/*.kill.json"):
        try:
            with open(path, encoding="utf-8") as handle:
                dossier = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        kills.append(dossier)

    gate_counts = Counter(d.get("gate_fired") or "unknown" for d in kills)
    entries = []
    for dossier in kills:
        gate = dossier.get("gate_fired") or ""
        reason = str(dossier.get("reason") or "")
        if gate in BOILERPLATE_GATES or len(reason) <= MIN_REASON_CHARS:
            continue
        if ACCUSATORY.search(reason):
            continue

        index = _sources_by_id(dossier)
        citations = []
        for ref in citation_ids(reason):
            url = index.get(ref)
            if not url:
                continue  # never render a reference we cannot resolve to a real page
            citations.append({"url": url, "domain": urlparse(url).netloc.removeprefix("www.")})

        candidate = dossier.get("candidate") or {}
        entries.append({
            "title": nodash(candidate.get("title")),
            "oneLiner": nodash(candidate.get("one_liner")),
            "gate": gate,
            "gateLabel": GATE_LABELS.get(gate, "It failed a check"),
            "reason": _clean_reason(reason),
            "citations": citations[:4],
            "date": str(dossier.get("created_at") or "")[:10],
        })

    # Newest first: the log is evidence the filter is still running, not a historical artifact.
    entries.sort(key=lambda e: e["date"], reverse=True)
    entries = [e for e in entries if e["title"]][:limit]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "killed": len(kills),
            "passed": passes,
            "shown": len(entries),
            "byGate": dict(gate_counts.most_common()),
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=60,
                        help="How many kills to publish (newest first, default 60).")
    args = parser.parse_args()

    payload = build(args.limit)
    for path, data in ((OUT, payload), (OUT_TOTALS, payload["totals"])):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    totals = payload["totals"]
    cited = sum(1 for e in payload["entries"] if e["citations"])
    print(f"wrote {OUT}")
    print(f"  {totals['killed']} killed / {totals['passed']} passed "
          f"({totals['killed'] / max(1, totals['killed'] + totals['passed']):.1%} rejected)")
    print(f"  published {totals['shown']} kills, {cited} carrying a resolvable source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

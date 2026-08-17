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
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The publish pass — the ONE gate every engine-authored string crosses before a stranger can
# read it. It lives in the engine (prospector/plain_text.py) rather than here, because the
# same five defect classes reach the pack `.md` files a buyer opens offline from a zip, where
# a fix on this side of the fence would never arrive. `_clean_reason` used to own a private
# half of this logic; that is now `plain_text.clean_reason` so the kill log and the pack
# generator cannot drift apart on what "publishable" means.
from prospector.plain_text import clean_reason, nodash, publish_pass  # noqa: E402

OUT = "store_platform/src/Store.Web/src/data/kill-log.json"
# The home page wants only the headline count. Importing the full log there would ship every
# entry in the home page bundle for the sake of one number, so the totals are split out.
OUT_TOTALS = "store_platform/src/Store.Web/src/data/kill-log-totals.json"
# The SAME argument as OUT_TOTALS above, one level further in.
#
# `/kill-log` is an instrument over the whole dataset, so it wants every entry it can get: at
# --limit 400 that file is ~507 KB. But two home page components (`LiveKillCard` and the hero's
# `AmbientKillColumn`) render nothing but struck-through NAMES, and a static JSON import cannot be
# tree-shaken -- an array is one value, so importing it for two fields ships all seven. Pointing
# the home page at the full log would therefore have put half a megabyte of reasons and citations
# into the bundle of the one page that never displays them.
#
# This file carries `title`, `gate` and `gateLabel` and nothing else, for the newest
# PREVIEW_LIMIT kills. `gateLabel` is what the consumers RENDER; `gate` is kept because it is the
# stable key to filter or group on, and a component that needs to branch on which check fired
# must not have to string-match a sentence to do it.
OUT_NAMES = "store_platform/src/Store.Web/src/data/kill-log-names.json"
# `/how-it-works` illustrates each of the six checks with one real kill, so unlike the home page it
# needs WHOLE entries (reason, citations), not just names. It does not need four hundred of them.
#
# This file is exactly `entries[:PREVIEW_LIMIT]` with every field intact, which is byte-for-byte
# what `kill-log.json` used to contain before the log was raised from 60 to 400 for the /kill-log
# instrument. Pointing /how-it-works here therefore preserves its behaviour exactly, including
# which example each check draws, while keeping the 452 KB full log out of that page's bundle.
OUT_EXAMPLES = "store_platform/src/Store.Web/src/data/kill-log-examples.json"
PREVIEW_LIMIT = 60
DOSSIERS = "store/dossiers"

# Gate names in the engine's vocabulary, rendered as the question the check actually asks.
# Matches the voice tools/make_sample_report.py already uses for the free report.
GATE_LABELS = {
    "adversarial_decisive": "It did not survive the adversarial pass",
    # "Incumbents" is banned in reader-facing copy (founder, 2026-08-16). It is the word a
    # consultant uses for "the companies already selling this", and the reader has to translate it
    # before they can judge the kill. This label is printed 190 times on /kill-log, so the ban
    # has to hold here rather than at the render site.
    "incumbency": "The space is already taken",
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
CITATION_REF = re.compile(
    r"\s*[\(\[]\s*(?:sources?\s*:?\s*)?([0-9a-f]{16}(?:[,;]\s*[0-9a-f]{16})*)\s*[\)\]]"
)


def citation_ids(text: str) -> list[str]:
    """Every passage hash referenced in `text`, in order, flattened out of its groups."""
    out: list[str] = []
    for group in CITATION_REF.findall(text or ""):
        out.extend(re.split(r"[,;]\s*", group))
    return list(dict.fromkeys(out))


# `nodash` now lives in prospector/plain_text.py next to the publish pass, and is imported
# above. It is re-exported here because the storefront's TypeScript twin
# (`store_platform/src/Store.Web/src/lib/text.ts`) and this module's tests both refer to it by
# this name; the behaviour is unchanged, only the home.
__all__ = ["nodash", "citation_ids", "build", "main"]


def _sources_by_id(dossier: dict) -> dict[str, str]:
    """Every retrieved source in the dossier, keyed by the hash its prose cites."""
    index: dict[str, str] = {}
    for check in dossier.get("checks") or []:
        for source in check.get("sources") or []:
            source_id, url = source.get("source_id"), source.get("url")
            if source_id and url:
                index[source_id] = url
    return index


# The engine's own `reason` field is frequently cut mid-sentence: 67 of the 636 kill dossiers
# with a substantive reason end without terminal punctuation (11%, measured 2026-08-06), e.g.
# "...so they do not offset the sol". Published raw, that put 26 of the 60 entries on the public
# page ending mid-WORD, on the one page whose entire job is to look rigorous.
#
# The repair is now `plain_text.publish_pass(sentences=True)`, and it is stricter than the rule
# it replaces: the old `_whole_sentences` kept a long fragment and appended an ellipsis when the
# last full stop fell before 75% of the text. An ellipsis is still a sentence that stops mid
# thought, so the rule is now absolute — trim to the last COMPLETE sentence, and if none
# survives return "" and DROP the entry (see `build` below) rather than print a fragment.
#
# Fixing whatever truncates the verdict upstream in the engine is still the real repair; this
# only stops the storefront and the pack shipping the damage.


def _clean_reason(reason: str) -> str:
    """Strip the engine's internal prefix, then run the shared publish pass.

    Kept as a module-level name because it is the seam this module's tests bind to, but it now
    holds no logic of its own: `plain_text.clean_reason` is the single implementation shared
    with pack generation.
    """
    return clean_reason(reason)


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
        # Every published string goes through the publish pass. `title` and `oneLiner` are
        # headline-shaped, so `sentences=False`: they legitimately end on a noun and must not
        # be emptied for it. `reason` is prose and gets the strict form via `_clean_reason`.
        clean = _clean_reason(reason)
        if not clean:
            # No complete sentence survived — the reason was a fragment all the way down.
            # Dropping the entry is the honest outcome; the log has ~512 eligible kills and
            # publishes 400, so this costs nothing but a swap for the next-newest kill.
            continue
        entries.append({
            "title": publish_pass(nodash(candidate.get("title"))),
            "oneLiner": publish_pass(nodash(candidate.get("one_liner"))),
            "gate": gate,
            "gateLabel": publish_pass(GATE_LABELS.get(gate, "It failed a check")),
            "reason": clean,
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
    # 400, not 60. /kill-log is a dataset instrument (sortable, filterable, per-entry anchors) and
    # 60 rows is not a dataset, it is a sample. 400 is not an arbitrary raise either: it is close
    # to the ceiling of what CAN be published, because BOILERPLATE_GATES excludes the three
    # score-only gates and those account for 818 of the 1,330 kills. Roughly 512 kills carry an
    # actual argument; the rest have nothing to show.
    parser.add_argument("--limit", type=int, default=400,
                        help="How many kills to publish (newest first, default 400).")
    args = parser.parse_args()

    payload = build(args.limit)
    # `gateLabel` travels with `gate`, and that is the whole fix for a leak measured on prod
    # 2026-08-08: the home page rendered "killed by value durability" and the ambient column
    # rendered "payer solvency", because this slim file carried the engine's gate id and dropped
    # the buyer-facing label that line 230 had already computed one screen above. Both consumers
    # then reached for the only string they had and de-underscored it, which is how an internal
    # identifier became the hero's copy.
    #
    # Deriving the label in the component instead was the other option and is worse in a way that
    # is measurable, not aesthetic: `src/lib/checks.ts` covers the SIX filter checks, and 65 of
    # these 60-row previews' gates are `adversarial_decisive` or `currency`, which it has no entry
    # for. A component-side map would have left those rendering the slug. GATE_LABELS covers all
    # twelve gates and falls back to "It failed a check", so no gate can leak, including one added
    # tomorrow. It also makes the hero and /kill-log agree by construction rather than by two
    # lists staying in sync, which is the promise `LiveKillCard`'s own header comment makes.
    names = [
        {"title": entry["title"], "gate": entry["gate"], "gateLabel": entry["gateLabel"]}
        for entry in payload["entries"][:PREVIEW_LIMIT]
    ]
    examples = {
        "generatedAt": payload["generatedAt"],
        "totals": payload["totals"],
        "entries": payload["entries"][:PREVIEW_LIMIT],
    }
    for path, data in (
        (OUT, payload),
        (OUT_TOTALS, payload["totals"]),
        (OUT_NAMES, names),
        (OUT_EXAMPLES, examples),
    ):
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

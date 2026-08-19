#!/usr/bin/env python
"""E12 — per-check grounding YIELD, offline, zero LLM.

The question this answers: when a candidate dies on `moat_ungrounded` or `source_or_die`,
is it because retrieval brought back nothing, or because what it brought back did not
answer the check?

Those two diagnoses point at opposite fixes. "Nothing came back" is a provider/outage
problem (the R2 rail, the rate gate). "Something came back and it did not answer" is a
query-targeting problem, and no amount of provider health fixes it.

Run:  .venv/bin/python tools/experiments/e12_grounding_yield.py [--since 2026-08-0]

Writes receipts next to this file so the numbers in
docs/COMMERCIAL_READINESS_PROGRAM.md §18 can be re-derived rather than trusted.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-0",
                    help="created_at prefix filter (default: August 2026)")
    args = ap.parse_args()

    per = collections.defaultdict(
        lambda: dict(n=0, unv=0, sup=0, ref=0, cits=[], conf=[], rf=0))
    qsrc = collections.Counter()
    gates = collections.Counter()
    ungrounded_cits: list[int] = []
    dossiers = 0

    for f in glob.glob(str(store_root() / "dossiers" / "*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        if not (d.get("created_at") or "").startswith(args.since):
            continue
        dossiers += 1
        if (d.get("decision") or "").lower() == "kill":
            gates[d.get("gate_fired")] += 1
        if d.get("gate_fired") == "moat_ungrounded":
            ungrounded_cits.append(sum(len(c.get("citations") or [])
                                       for c in d.get("checks") or []))
        for c in d.get("checks") or []:
            p = per[c.get("check_name") or "?"]
            p["n"] += 1
            v = c.get("verdict")
            if v == "unverifiable":
                p["unv"] += 1
            elif v == "supported":
                p["sup"] += 1
            elif v == "refuted":
                p["ref"] += 1
            p["cits"].append(len(c.get("citations") or []))
            p["conf"].append(float(c.get("confidence") or 0))
            p["rf"] += bool(c.get("retrieval_failed"))
            if c.get("query_source"):
                qsrc[c["query_source"]] += 1

    if not dossiers:
        print(f"no dossiers matching created_at prefix {args.since!r}")
        return 1

    kills = sum(gates.values())
    grounding_kills = gates.get("moat_ungrounded", 0) + gates.get("source_or_die", 0)

    print("=" * 78)
    print(f"E12 — GROUNDING YIELD  (dossiers={dossiers}, kills={kills}, since={args.since})")
    print("=" * 78)
    print("\nKILL GATES:")
    for g, n in gates.most_common():
        print(f"    {str(g):<22} {n:>5}")
    print(f"\ngrounding-QUALITY kills (moat_ungrounded + source_or_die): "
          f"{grounding_kills}/{kills} = {100.0 * grounding_kills / max(1, kills):.1f}%")

    if ungrounded_cits:
        print("\nDID RETRIEVAL ACTUALLY FAIL ON THOSE?  citations per moat_ungrounded dossier:")
        print(f"    mean={statistics.mean(ungrounded_cits):.1f} "
              f"median={statistics.median(ungrounded_cits)} "
              f"zero-citation dossiers={sum(1 for s in ungrounded_cits if s == 0)}"
              f"/{len(ungrounded_cits)}")
        print("    (zero-citation ~= 0 means retrieval WORKED and the passages did not answer)")

    print(f"\n{'check':<20}{'n':>5}{'unverif%':>10}{'supp%':>8}{'ref%':>7}"
          f"{'cites':>8}{'conf':>7}{'retr_fail':>10}")
    print("-" * 75)
    rows = []
    for k, p in sorted(per.items(), key=lambda x: -x[1]["unv"] / max(1, x[1]["n"])):
        n = p["n"]
        rows.append(dict(check=k, n=n, unverifiable_pct=round(100 * p["unv"] / n, 1),
                         supported_pct=round(100 * p["sup"] / n, 1),
                         refuted_pct=round(100 * p["ref"] / n, 1),
                         mean_citations=round(statistics.mean(p["cits"]), 2),
                         mean_confidence=round(statistics.mean(p["conf"]), 3),
                         retrieval_failed=p["rf"]))
        print(f"{k:<20}{n:>5}{100 * p['unv'] / n:>9.1f}%{100 * p['sup'] / n:>7.1f}%"
              f"{100 * p['ref'] / n:>6.1f}%{statistics.mean(p['cits']):>8.1f}"
              f"{statistics.mean(p['conf']):>7.2f}{p['rf']:>10}")

    # E1 eligibility: the config key is NOT general — only checks with an entity template
    # can receive the hybrid arm. Listing any other check is silently inert.
    import sys
    sys.path.insert(0, str(REPO))
    from prospector.verify import _ENTITY_TEMPLATES  # noqa: E402
    eligible = set(_ENTITY_TEMPLATES)
    print(f"\nE1 hybrid arm ELIGIBLE checks (have an entity template): {sorted(eligible)}")
    worst = [r["check"] for r in rows[:3]]
    print(f"three worst-grounded checks: {worst}")
    blocked = [c for c in worst if c not in eligible]
    if blocked:
        print(f"  !! {blocked} are worst-grounded but have NO entity template — listing them in")
        print("     retrieval.hybrid_entity_checks is INERT (verify.py:241-243 returns []).")
        print("     Extending _ENTITY_TEMPLATES is a CODE change, not a config change.")

    print(f"\nquery_source present on checks: {dict(qsrc) or 'ABSENT in this window'}")

    out = Path(__file__).with_name("e12_grounding_yield_receipts.json")
    out.write_text(json.dumps(dict(
        since=args.since, dossiers=dossiers, kills=kills,
        gates=dict(gates), grounding_quality_kills=grounding_kills,
        moat_ungrounded_citations=ungrounded_cits,
        per_check=rows, query_source=dict(qsrc),
        entity_template_eligible=sorted(eligible),
    ), indent=2))
    print(f"\nreceipts -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

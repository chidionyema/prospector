"""E-103a — how many of the six checks does a vet actually run? The ceiling on check concurrency.

E-101f capped the screen line at 3.66x on moat calls, so the next lever in the verify step is
CONCURRENCY: the six checks run one after another (`verify.py:1118`, a plain `for` loop over
`run_order`) and kill-fast returns the moment a hard gate fires. Running them together would cut
wall clock to the slowest single check.

The ceiling on that is not a code question, it is a corpus question, and it is answerable with no
run at all: **a vet that already stops after one check cannot be made faster by running six at
once.** So the expected saving is the mean number of checks a vet performs, and that number is
sitting in every dossier as `len(checks)`.

Two things this measures that a mean alone would hide:

  1. The distribution BY DECISION. A KILL that stops at check 1 and a PASS that runs all six are
     different populations, and the engine's mix of them decides the answer. Reporting only the
     pooled mean would let a corpus that is 90% one-check KILLs look like a 2x opportunity.
  2. The WASTE. Concurrency runs checks that kill-fast would have skipped. Cost is explicitly not a
     constraint in this programme (founder, 2026-08-20), but an unrecorded 6x on brain calls is a
     number somebody will later be surprised by, so it is printed beside the saving.

The speedup reported is on CHECK COUNT, which equals wall clock only if every check takes the same
time. It does not: a check that retrieves nothing returns faster than one that reads four passages.
The receipt therefore states this as an UPPER BOUND, and the honest version needs per-check timings,
which the dossiers do not carry.

Reads the local dossier copy. Zero paid calls, zero network.

    tools/experiments/e103a_kill_fast_depth.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def main() -> int:
    files = sorted((REPO / "store" / "dossiers").glob("*.json"))
    if not files:
        raise SystemExit(f"no dossiers under {REPO / 'store' / 'dossiers'}")

    depth_by_decision: dict[str, Counter[int]] = {}
    gate_first: Counter[str] = Counter()
    # `store/dossiers/*.json` is not all dossiers. 123 of the 2,929 files here are `<id>.lint.json`,
    # the pack linter's output, which has no `checks` key at all. The first version of this file
    # counted them as "unreadable", which reads as data corruption in a store that is fine. Skipped
    # by SUFFIX, and counted separately, so a genuinely broken dossier still shows up as one.
    skipped_not_dossiers, n_bad = 0, 0
    for f in files:
        if f.name.endswith(".lint.json"):
            skipped_not_dossiers += 1
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            n_bad += 1
            continue
        checks = d.get("checks")
        if not isinstance(checks, list):
            n_bad += 1
            continue
        decision = str(d.get("decision") or "?")
        depth_by_decision.setdefault(decision, Counter())[len(checks)] += 1
        gate_first[str(d.get("gate_fired") or "none")] += 1

    total = sum(sum(c.values()) for c in depth_by_decision.values())
    all_depths = Counter()
    for c in depth_by_decision.values():
        all_depths.update(c)

    def mean(c: Counter[int]) -> float:
        n = sum(c.values())
        return sum(k * v for k, v in c.items()) / n if n else 0.0

    n_checks_max = max(all_depths) if all_depths else 0
    pooled = mean(all_depths)
    out = {
        "dossiers_read": total, "unreadable": n_bad,
        "skipped_not_dossiers": skipped_not_dossiers,
        "store": str(REPO / "store" / "dossiers"),
        "note": "the LAPTOP dossier copy; production's store is on Fly at /data/store",
        "checks_run_distribution": {str(k): v for k, v in sorted(all_depths.items())},
        "mean_checks_run": round(pooled, 3),
        "max_checks_in_run_order": n_checks_max,
        "by_decision": {
            k: {"n": sum(c.values()), "mean_checks_run": round(mean(c), 3),
                "distribution": {str(d): n for d, n in sorted(c.items())}}
            for k, c in sorted(depth_by_decision.items())
        },
        "first_gate_fired": dict(gate_first.most_common()),
        "upper_bound_speedup_on_checks": round(pooled, 3),
        "brain_calls_multiplier_if_concurrent": (
            round(n_checks_max / pooled, 3) if pooled else None),
        "caveat": ("speedup is on CHECK COUNT and is an UPPER BOUND on wall clock: concurrent "
                   "wall clock is the SLOWEST check, not the mean one, and the dossiers carry no "
                   "per-check timings. A serial run of n equal checks becomes 1; a serial run of n "
                   "unequal checks becomes max(n), which is worse than n/mean."),
    }

    print(f"{total} dossiers, {n_bad} unreadable, "
          f"{skipped_not_dossiers} skipped (.lint.json, not dossiers)\n")
    print(f"{'decision':14s}{'n':>7s}{'mean checks run':>18s}   distribution")
    for k, v in out["by_decision"].items():
        print(f"{k:14s}{v['n']:7d}{v['mean_checks_run']:18.2f}   {v['distribution']}")
    print(f"\npooled mean checks run: {pooled:.2f} of {n_checks_max}")
    print(f"UPPER BOUND speedup from running the checks concurrently: {pooled:.2f}x")
    print(f"brain calls if concurrent: {out['brain_calls_multiplier_if_concurrent']}x more")
    print("\nfirst gate fired:", out["first_gate_fired"])

    dest = HERE / "e103a_kill_fast_depth_receipts.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print("\nreceipt:", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

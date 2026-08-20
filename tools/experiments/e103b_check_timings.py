"""E-103b — the honest number for check concurrency: per-check wall time from the audit trail.

E-103a bounded check concurrency at 4.99x, but that bound is on CHECK COUNT. Concurrent wall clock
is the SLOWEST check, not the mean one, so the real figure is `sum(durations) / max(durations)` per
vet, and it is lower by however skewed the per-check distribution is.

The engine already records what is needed and nobody had read it that way. Every check writes one
`check_result` audit row (`prospector/verify.py:1133`) carrying `ts`, `candidate_id`, `check`, `idx`
and `total`, and every vet is bracketed by `candidate_start` / `candidate_done`.

**THE UNIT IS THE SPAN *AND* THE PROCESS, AND GETTING IT WRONG PRODUCED TWO WRONG NUMBERS BEFORE
THIS ONE.** Both were caught by the same cheap check — count what you grouped and divide.

Version 1 grouped by `(run_id, pid, candidate_id)` and took the gap between consecutive
`check_result` rows as a check's duration. Measured on production's own trail: between two such rows
for one candidate there were **839 audit rows covering 150 complete vets of 157 other candidates**.
The engine interleaves candidates, so the gap spanned everything the daemon did in between. It
reported `buyer_intent` at a p50 of 3,273 seconds — 55 minutes for one check — beside
`payer_solvency` at 26 seconds, and a speedup of 2.5x. All artefact.

Version 2 bracketed on `candidate_start` .. `candidate_done` but keyed the open span on
`candidate_id` ALONE, having over-corrected away from the pid. It produced **7,417 check timings
inside 309 spans — 24 checks per vet, when the run order tops out at NINE**. That arithmetic is the
whole disproof and it costs one division. Several daemon processes vet the same candidate at the
same time, so their rows landed in one span and every duration was measured against whichever
process wrote last. The tell in the output was a per-check p50 of 0.638s beside a p90 of 356s: a
bimodal distribution that no single check has, made of real durations and cross-process gaps mixed
together.

This version uses both: `(run_id, pid, candidate_id)` as the key AND the `candidate_start` ..
`candidate_done` bracket. Bracketing also removes version 1's stated limitation — `candidate_start`
gives the start of check 1, so no check has to be dropped.

**The invariant is asserted, not eyeballed.** `checks_per_vet_max` is printed and the file refuses to
report if it exceeds the run order's nine. That is the guard for this class: a grouping error always
shows up as too many members per group, whatever caused it.

**This runs on the PRODUCTION engine host, read-only.** The laptop store stopped updating at the
cutover (this document's section 7), and there is no audit directory on the laptop at all. It reads
the given files and writes nothing.

    python3 e103b_check_timings.py /data/store/scheduler/audit/2026-08-20.jsonl [more...]
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime


def main() -> int:
    # 9 is the length of the run order (`prospector/verify.py`); E-103a measured a max of 9 checks
    # run in any real dossier. A group holding more than that is a grouping error, not a long vet.
    MAX_CHECKS_PER_VET = 9

    spans: list[tuple[datetime, list[tuple[str, datetime]]]] = []
    open_span: dict[tuple, tuple[datetime, list]] = {}
    n_rows = n_checks = 0
    n_unclosed = 0

    for path in sys.argv[1:]:
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                n_rows += 1
                ev = r.get("event")
                if ev not in ("candidate_start", "candidate_done", "check_result"):
                    continue
                cid = r.get("candidate_id")
                if not cid:
                    continue
                # The pid is part of the identity. Several daemon processes vet the same candidate
                # concurrently here, and without the pid their rows merge into one impossible span.
                key = (r.get("run_id"), r.get("pid"), cid)
                ts = datetime.fromisoformat(r["ts"])
                if ev == "candidate_start":
                    if key in open_span:
                        n_unclosed += 1     # a vet that never wrote candidate_done; drop it
                    open_span[key] = (ts, [])
                elif ev == "check_result":
                    if key in open_span:
                        open_span[key][1].append((str(r.get("check")), ts))
                        n_checks += 1
                elif ev == "candidate_done":
                    got = open_span.pop(key, None)
                    if got and got[1]:
                        spans.append(got)

    durations: list[float] = []
    per_check: dict[str, list[float]] = defaultdict(list)
    ratios: list[float] = []
    for start, checks in spans:
        prev = start
        d, names = [], []
        for name, ts in checks:
            d.append((ts - prev).total_seconds())
            names.append(name)
            prev = ts
        if any(x < 0 for x in d):
            continue
        durations.extend(d)
        for nm, x in zip(names, d):
            per_check[nm].append(x)
        if len(d) >= 2 and max(d) > 0:
            ratios.append(sum(d) / max(d))

    # THE OTHER HALF OF THE GUARD BELOW. `MAX_CHECKS_PER_VET` catches over-grouping; nothing caught
    # UNDER-grouping, and the empty case is not a small version of a result, it is no result at all.
    # Measured 2026-08-20: run with no arguments, this file printed a complete, well-formed JSON
    # object of zeros and nulls and exited 0. Read quickly that is indistinguishable from "the
    # engine did no work", which during an outage is exactly what a reader expects to see — so the
    # empty read would have been believed. Memories `a-guard-that-iterates-an-empty-list-passes`
    # and `pytest-exits-zero-when-it-collects-nothing` are this same class.
    if not sys.argv[1:]:
        raise SystemExit(
            "no audit files given. Usage: e103b_check_timings.py "
            "/data/store/scheduler/audit/YYYY-MM-DD.jsonl [more...]  "
            "Refusing to print a table of zeros that reads like a measured result.")
    if not n_rows:
        raise SystemExit(
            f"read 0 audit rows from {len(sys.argv[1:])} file(s): {sys.argv[1:]}. Either the paths "
            f"are wrong or the files are empty. Refusing to report.")
    if not spans:
        raise SystemExit(
            f"read {n_rows} audit rows but bracketed 0 vets. Nothing here has both a "
            f"candidate_start and a candidate_done, so there is no span to time. Refusing to "
            f"report.")

    worst = max((len(c) for _, c in spans), default=0)
    if worst > MAX_CHECKS_PER_VET:
        raise SystemExit(
            f"a vet came out with {worst} checks and the run order has at most "
            f"{MAX_CHECKS_PER_VET}. The grouping is wrong, so every duration below is a mixture of "
            f"different vets' work. Refusing to report. This exact check caught two earlier "
            f"versions of this file; see its docstring.")

    def q(vals, p):
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(p * len(s)))], 3) if s else None

    out = {
        "files": sys.argv[1:],
        "audit_rows_read": n_rows,
        "vets_bracketed_by_start_and_done": len(spans),
        "check_result_rows_inside_a_span": n_checks,
        "checks_per_vet_max": worst,
        "checks_per_vet_mean": round(n_checks / len(spans), 2) if spans else None,
        "vets_with_no_candidate_done_dropped": n_unclosed,
        "unit": "one candidate_start .. candidate_done span; check 1 is timed from candidate_start",
        "per_check_seconds": {
            "mean": round(statistics.fmean(durations), 3) if durations else None,
            "p50": q(durations, 0.50), "p90": q(durations, 0.90), "p99": q(durations, 0.99),
            "max": round(max(durations), 3) if durations else None,
        },
        "by_check_name": {
            k: {"n": len(v), "mean": round(statistics.fmean(v), 3), "p50": q(v, 0.50),
                "p90": q(v, 0.90)}
            for k, v in sorted(per_check.items(), key=lambda kv: -statistics.fmean(kv[1]))
        },
        "concurrency_speedup_sum_over_max": {
            "mean": round(statistics.fmean(ratios), 3) if ratios else None,
            "p50": q(ratios, 0.50), "p90": q(ratios, 0.90), "p10": q(ratios, 0.10),
            "n": len(ratios),
            "meaning": "serial wall time divided by the slowest single check, per vet",
        },
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Commit gate: projected GENERATION time must fit its share of the tick deadline.

Replaces the k/batch_size ratio check (verify_engine_change.sh check 4, removed
2026-08-14). That ratio was built on `generation.candidates_per_signal`, a value the
daemon path never reads: `run_scheduled.py` always passes an explicit
`k=schedule.batch_size` into `run_signal`, and `generate.py` only falls back to
`candidates_per_signal` when k is None. The 2026-08-13 change 5->50 and the 2026-08-14
cut 50->20 both did nothing on the daemon path — the guarded value was inert, and the
ratio it produced would have blocked a legitimate batch_size raise while proving
nothing about time.

This guard projects WALL-CLOCK generation time from the values the daemon actually
uses, with the SAME wave-planning function the runtime runs
(`prospector.generate.plan_wave` — one formula, so projection and behaviour cannot
drift):

    per_lane_k   = ceil(batch_size / n_lanes)
    n_calls, ask = plan_wave(per_lane_k, n_forms, n_lenses, max_per_call, min_ask)
    total_calls  = n_lanes * WAVES_ASSUMED * n_calls
    projected_s  = total_calls * P50_CALL_S * (1 + TRUNC_RETRIES * TRUNC_RATE)
                   / EFFECTIVE_CONCURRENCY
    ASSERT projected_s <= gen_budget_frac * PROSPECTOR_TICK_DEADLINE_S

Two rails, one number: `schedule.gen_budget_frac` is also what the RUNTIME budget in
`run_scheduled._default_generate` enforces, so a config this guard passes is a config
whose generation phase the daemon will actually cut off at the same bound if the
projection turns out optimistic.

Constants and their provenance (each env-overridable for a deliberate exception):
  P50_CALL_S (default 200)  — measured 2026-08-14 live against api.minimax.io
      (MiniMax-M3, the daemon's exact rendered generation prompt, max_tokens 32768,
      scratchpad ab_ask): 193.8s for a completed ask=4 call, 240.0s for one that hit
      max_tokens. Deliberately the M3 tail, not the healthy claude_cli-headed chain
      (whose whole generation phase was 2.9 min on 2026-08-11) — the guard must hold
      on the chain that actually caused the 2026-08-14 force-exit.
  TRUNC_RATE (default 0.25) — 2026-08-14 launchd.err.log: 39 truncation events
      ("re-asking"/"truncated at max_tokens") against ~150 generation-path MiniMax
      calls.
  TRUNC_RETRIES (default from PROSPECTOR_MINIMAX_TRUNCATION_RETRIES, else 2)
      — operator.py `_RETRY_TRUNCATED_MAX`.
  EFFECTIVE_CONCURRENCY (default from PROSPECTOR_MINIMAX_CONCURRENCY, else 3)
      — operator.py `_throttle` is a process-wide semaphore; concurrent lanes share it,
      so lane parallelism does not multiply throughput past this.
  WAVES_ASSUMED (default 2) — wave 1 plus one backfill wave. Measured 2026-08-14:
      waves 2-3 added +0 candidates ("Generation wave 2: +0"); the runtime budget rail
      bounds anything beyond the projection.

Exit 0 with the numbers printed, exit 1 (with the same numbers) on breach or on an
unreadable config — a guard that cannot evaluate must fail, not wave through.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    import yaml
    try:
        with open(args.config) as f:
            c = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        print(f"   FAIL: cannot read {args.config}: {e}")
        return 1

    sched = c.get("schedule") or {}
    gen = c.get("generation") or {}
    batch = sched.get("batch_size")
    if not batch:
        print(f"   FAIL: schedule.batch_size missing/zero in {args.config}")
        return 1

    lanes = 1
    if c.get("active_lane"):
        lanes = 1
    elif c.get("active_lanes"):
        lanes = max(1, len(c["active_lanes"]))

    n_forms = len(gen.get("structural_forms") or []) or 1
    n_lenses = 5  # historical lens fan-out ("[5 parallel calls]", launchd.err.log);
    # only reaches the formula on the legacy min_ask<=1 branch.
    max_per_call = int(gen.get("max_per_call", 10) or 10)
    min_ask = int(gen.get("min_ask", 5) or 1)

    from prospector.generate import plan_wave  # the runtime's own formula

    per_lane_k = math.ceil(batch / lanes)
    n_calls, ask = plan_wave(per_lane_k, n_forms, n_lenses, max_per_call, min_ask)

    waves = int(os.environ.get("PROSPECTOR_GEN_WAVES_ASSUMED", "2"))
    p50 = float(os.environ.get("PROSPECTOR_GEN_P50_CALL_S", "200"))
    trunc_rate = float(os.environ.get("PROSPECTOR_GEN_TRUNC_RATE", "0.25"))
    trunc_retries = int(os.environ.get("PROSPECTOR_MINIMAX_TRUNCATION_RETRIES", "2"))
    conc = int(os.environ.get("PROSPECTOR_MINIMAX_CONCURRENCY", "3"))

    deadline = float(os.environ.get("PROSPECTOR_TICK_DEADLINE_S", "10800"))
    try:
        frac = max(0.0, float(sched.get("gen_budget_frac", 0.35)))
    except (TypeError, ValueError):
        frac = 0.35
    if frac == 0:
        # Rail disabled in config: the guard then bounds against the WHOLE deadline,
        # because that is what an unbudgeted generation phase can actually consume.
        frac = 1.0
    budget = frac * deadline

    total_calls = lanes * waves * n_calls
    projected = total_calls * p50 * (1 + trunc_retries * trunc_rate) / max(1, conc)

    print(f"   batch_size={batch} lanes={lanes} per_lane_k={per_lane_k} "
          f"min_ask={min_ask} -> {n_calls} call(s)/wave x ask={ask}")
    print(f"   projected T_gen = {lanes}x{waves}x{n_calls} calls x {p50:.0f}s "
          f"x (1 + {trunc_retries}x{trunc_rate}) / {conc} = {projected:.0f}s")
    print(f"   budget = {frac:.2f} x {deadline:.0f}s deadline = {budget:.0f}s")
    if projected > budget:
        print(f"   FAIL: projected generation time {projected:.0f}s exceeds its "
              f"{budget:.0f}s share of the tick. Lower schedule.batch_size, raise "
              f"generation.min_ask, or justify a bigger share via "
              f"schedule.gen_budget_frac / PROSPECTOR_TICK_DEADLINE_S — with a "
              f"measured tick behind it.")
        return 1
    print(f"   OK: headroom {budget - projected:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

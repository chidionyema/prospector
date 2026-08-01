#!/usr/bin/env python3
"""Decide whether this machine is currently capable of producing a trustworthy test result.

Why this exists
---------------
"State is a probe, not a paragraph" applied to the test signal. On 2026-07-31 the clean-tree
.NET suite failed three times running on a test nobody had touched:

    StorageWiringTests.Download_url_honours_a_custom_ttl
    X-Amz-Expires was 594, expected 600 (or 599)     # then 596, then 597

The assertion straddles two clock reads. Under load those reads drifted six seconds apart,
so the failure was the machine, not the code. The dangerous half is the converse: a run that
comes back green under the same conditions is equally uninformative, and green is the one
nobody re-runs. A suite result is evidence only if you can say what the box was doing while
it ran, so this prints that alongside every verdict.

What it measures
----------------
Load average per core, and the *rate* of paging — not the cumulative counters. Cumulative
numbers say nothing about now: this machine showed `Swapouts: 20,388,478` pages, which is
22 hours of history, while the live swapout rate was 0.0/s. macOS's own summary is no
better: `memory_pressure` reported "System-wide memory free percentage: 66%" in the same
minute `top` reported `PhysMem: 16G used ... 32M unused`, because the two count reclaimable
memory differently. Sampling a delta over a short window is the only reading that answers
"is the box thrashing right now".

Calibration status: PROVISIONAL, and deliberately visible rather than buried.
LOAD_PER_CORE_LIMIT below is reasoned, not fitted — see its comment. The `--record` mode
appends every sample to a JSONL so these can eventually be set from a distribution of real
good and bad runs instead of from one reading taken on a bad afternoon.

Usage
-----
    python3 scripts/load_gate.py                     # probe + verdict, exit 1 if degraded
    python3 scripts/load_gate.py --warn-only         # never fails; just annotates
    python3 scripts/load_gate.py --label "dotnet suite" --record store/load_samples.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# ── Thresholds ───────────────────────────────────────────────────────────────────────────
# Reasoned, not fitted. load/core == 1.0 is a fully subscribed machine. A single honest
# build already sits near 1.0 (each of vitest/next/dotnet defaults to ~one worker per core),
# and two concurrent agents near 2.0, so a limit of 4.0 does not fire on legitimate work.
# The condition proven to corrupt results was load/core 30-49 (load 364-592 on 12 cores),
# an order of magnitude above this line. Tighten it once --record has a real distribution.
LOAD_PER_CORE_LIMIT = 4.0

# Corroborating, not decisive: paging rate confirms *why* load is high (blocked on faults
# rather than computing). 100/s is the reading taken at load/core 14.6 on a box that was
# visibly thrashing, so it is an observed-bad value, not an observed-good boundary. It is
# reported always and only escalates a verdict that load has already called degraded.
SWAPIN_RATE_WARN = 100.0

SAMPLE_WINDOW_S = 2.0


def _vm_stat() -> dict[str, int]:
    """Parse vm_stat's page counters. Returns {} on any non-macOS or unexpected output."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    counters: dict[str, int] = {}
    for line in out.splitlines():
        match = re.match(r'"?([^":]+)"?:\s+(\d+)', line.strip())
        if match:
            counters[match.group(1).strip()] = int(match.group(2))
    return counters


def probe(window_s: float = SAMPLE_WINDOW_S) -> dict:
    """Sample the machine over `window_s` and return the reading plus a verdict."""
    cores = os.cpu_count() or 1
    before = _vm_stat()
    started = time.monotonic()
    time.sleep(window_s)
    elapsed = time.monotonic() - started
    after = _vm_stat()

    def rate(key: str) -> float | None:
        if key not in before or key not in after or elapsed <= 0:
            return None
        return (after[key] - before[key]) / elapsed

    load1 = os.getloadavg()[0]
    per_core = load1 / cores
    swapins = rate("Swapins")
    degraded = per_core > LOAD_PER_CORE_LIMIT

    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cores": cores,
        "load1": round(load1, 2),
        "load_per_core": round(per_core, 2),
        "swapins_per_s": None if swapins is None else round(swapins, 1),
        "decompressions_per_s": (lambda r: None if r is None else round(r, 1))(rate("Decompressions")),
        "pageins_per_s": (lambda r: None if r is None else round(r, 1))(rate("Pageins")),
        "verdict": "DEGRADED" if degraded else "OK",
        "limit_load_per_core": LOAD_PER_CORE_LIMIT,
    }


def render(sample: dict, label: str | None) -> str:
    tag = f" [{label}]" if label else ""
    thrash = ""
    if sample["swapins_per_s"] is not None and sample["swapins_per_s"] > SWAPIN_RATE_WARN:
        thrash = f"  (paging: {sample['swapins_per_s']}/s swapins — blocked on faults, not computing)"
    lines = [
        f"[load-gate]{tag} {sample['verdict']}  "
        f"load {sample['load1']} on {sample['cores']} cores = "
        f"{sample['load_per_core']}/core (limit {sample['limit_load_per_core']}){thrash}",
    ]
    if sample["verdict"] == "DEGRADED":
        lines.append(
            "[load-gate] A suite result taken now is NOT evidence — green or red. "
            "Timing-sensitive assertions fail spuriously at this load "
            "(proven: X-Amz-Expires 594/596/597 vs 599-600). Re-run when this reads OK."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--warn-only", action="store_true",
                        help="Print the verdict but always exit 0.")
    parser.add_argument("--label", default=None, help="Tag identifying the run being gated.")
    parser.add_argument("--record", default=None, metavar="PATH",
                        help="Append the sample as JSONL, for calibrating the thresholds.")
    parser.add_argument("--json", action="store_true", help="Emit the raw sample instead.")
    parser.add_argument("--window", type=float, default=SAMPLE_WINDOW_S,
                        help=f"Sampling window in seconds (default {SAMPLE_WINDOW_S}).")
    args = parser.parse_args()

    sample = probe(args.window)
    if args.label:
        sample["label"] = args.label

    print(json.dumps(sample) if args.json else render(sample, args.label), flush=True)

    if args.record:
        try:
            with open(args.record, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(sample) + "\n")
        except OSError as exc:
            # Never fail a run because telemetry could not be written.
            print(f"[load-gate] could not record sample: {exc}", file=sys.stderr)

    return 0 if (args.warn_only or sample["verdict"] == "OK") else 1


if __name__ == "__main__":
    sys.exit(main())

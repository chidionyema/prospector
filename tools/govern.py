#!/usr/bin/env python3
"""Run a heavy build/test command under a machine-wide concurrency ceiling.

Why
---
`prospector/cli_governor.py` bounds LLM CLI subprocesses. Nothing bounded the other half of
the load: `next build`, `vitest run`, `dotnet test`, `npm ci`. Each of those defaults to
roughly one worker per core, so on this 12-core box a single agent claims ~12 workers and
three concurrent agents claim ~36. Measured on 2026-07-31 while three checkouts were
building at once:

    Load Avg: 364.13, 486.05, 379.26          # 12 cores
    CPU usage: 54.77% user, 26.73% sys, 18.49% idle
    PhysMem:   16G used (3806M wired, 2343M compressor), 32M unused
    Swapouts:  19,988,973 pages               # ~76GB over 22h uptime

18% idle CPU at load 364 is not a compute shortage — those processes are blocked on page
faults. The box is RAM-bound, so the thing worth rationing is how many memory-hungry build
processes exist at once, not how many cores they are allowed to touch.

The cost is not just slowness. Under that load the suite stops being evidence: the presign
TTL assertion in `StorageWiringTests.Download_url_honours_a_custom_ttl` failed three times
running with `X-Amz-Expires` of 594, 596 and 597 against an expected 599-600, purely
because the two clock reads it straddles drifted apart. A green run and a red run are
equally uninformative at that point. See `scripts/load_gate.py`.

Usage
-----
    python3 tools/govern.py -- npm run build
    python3 tools/govern.py --name test --slots 1 -- dotnet test Foo.csproj

Exit code is the child's, so this is transparent to any caller (CI, npm scripts, make).

Deliberately NOT a wrapper that also caps `-j`/`--maxWorkers`: per-tool worker counts
belong in each tool's checked-in config (`vitest.config.ts`, `xunit.runner.json`) where
they apply to every invocation by anyone, including one that forgets this shim. This layer
answers a different question — how many heavy commands may run *at all*.
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector.cli_governor import make_governor  # noqa: E402

# One less than half the cores, floored at 2. The binding constraint is RAM, not cores: a
# `next build` peaked at 592MB RSS here and a `dotnet test` run is comparable, against a
# baseline of ~7GB already held by editors and browsers on a 16GB machine. Two heavy
# commands is what fits without touching swap; the point is that the third one waits
# instead of pushing the machine into the compressor.
DEFAULT_SLOTS = 2

# Long enough that a queued build is never killed for waiting behind a legitimate one
# (a full `next build` + `dotnet test` here runs into minutes), short enough that a
# genuinely wedged holder surfaces within an hour rather than blocking a CI job forever.
DEFAULT_TIMEOUT_S = 3600.0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="govern.py",
        description="Run a command holding one machine-wide heavy-task slot.",
    )
    parser.add_argument("--name", default="heavy",
                        help="Slot namespace. Commands sharing a name share a ceiling.")
    parser.add_argument("--slots", type=int, default=DEFAULT_SLOTS,
                        help=f"Concurrent holders allowed machine-wide (default {DEFAULT_SLOTS}).")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="Seconds to wait for a slot before giving up.")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="Command to run, after a literal --")
    args = parser.parse_args()

    cmd = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not cmd:
        parser.error("no command given (expected: govern.py [opts] -- CMD ...)")

    governor = make_governor(args.slots, args.name)
    waited_from = time.monotonic()
    # Try once without announcing anything: the uncontended case is the common one and it
    # should stay silent, so this shim does not add noise to every build's output.
    if not governor.acquire(timeout=0):
        print(
            f"[govern] waiting for a '{args.name}' slot "
            f"({args.slots} machine-wide, all busy) — this build has not hung",
            file=sys.stderr, flush=True,
        )
        if not governor.acquire(timeout=args.timeout):
            print(
                f"[govern] gave up after {args.timeout:.0f}s waiting for a '{args.name}' slot. "
                f"Inspect holders with: lsof ~/.prospector/cli_slots/{args.name}/",
                file=sys.stderr, flush=True,
            )
            return 75  # EX_TEMPFAIL — a retry may succeed; this is not a test failure
        print(f"[govern] slot acquired after {time.monotonic() - waited_from:.0f}s",
              file=sys.stderr, flush=True)

    child: subprocess.Popen | None = None

    def forward(signum: int, _frame: object) -> None:
        # Without this, Ctrl-C or a CI cancel kills the shim and orphans the real build,
        # which keeps its memory and leaves the slot looking free while the load persists.
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, forward)

    try:
        child = subprocess.Popen(cmd)
        return child.wait()
    except FileNotFoundError:
        print(f"[govern] command not found: {cmd[0]}", file=sys.stderr)
        return 127
    finally:
        # Belt and braces. The kernel drops the flock when this process exits anyway, which
        # is what makes the ceiling safe against SIGKILL, but releasing explicitly frees the
        # slot fractionally sooner for whoever is queued behind us.
        governor.release()


if __name__ == "__main__":
    sys.exit(main())

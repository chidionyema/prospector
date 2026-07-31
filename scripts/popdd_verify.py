#!/usr/bin/env python3
"""
Prospector POPDD Test Runner

Runs the Prospector test suite and signs the result into a POPDD chain,
demonstrating POPDD works as an integrated audit-trail component in
this project.

Usage:
    python scripts/popdd_verify.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from popdd_agent import PopddAgent

ROOT = Path(__file__).parent.parent

# Wall-clock ceiling for the whole suite. This is a HANG detector, not a performance
# budget — set it well above the real runtime so a merely-slow suite never reads as a
# failure. Measured 2026-07-30: 679 tests, 168.81s pytest-internal / 174.65s process.
# The previous 180s ceiling left 3% headroom, so commits failed non-deterministically
# under load once the control-center detach tests (+58 tests) landed. Override with
# POPDD_TEST_TIMEOUT for a slower machine.
TEST_TIMEOUT_SECONDS = int(os.environ.get("POPDD_TEST_TIMEOUT", "600"))


def main() -> int:
    agent = PopddAgent.at_path(ROOT)

    agent.sign_generic(
        action="test-run:start",
        target="prospector:test-suite",
        **{"verdict": "STARTED", "command": "pytest -q --tb=no -rf"},
    )

    print("Running Prospector test suite...")
    # -rf forces the "short test summary info" section listing every FAILED/ERROR node id.
    # Without it a failure was recorded only as a COUNT, which made a flake unattributable:
    # the 517/518 run of 2026-07-29 could not be traced to a test name after the fact.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # A timeout used to propagate as an uncaught traceback, which killed the process
        # before "test-run:complete" was ever signed. The chain was then left with a
        # dangling STARTED entry (receipts seq 24 and 25 of 2026-07-30) that looked like
        # a crashed run rather than a timeout. Sign the verdict, then fail closed.
        agent.sign_generic(
            action="test-run:complete",
            target="prospector:test-suite",
            **{
                "verdict": "TIMEOUT",
                "passed": 0,
                "failed": 0,
                "failedTests": [],
                "exitCode": None,
                "timeoutSeconds": TEST_TIMEOUT_SECONDS,
            },
        )
        print(
            f"\n❌ Test suite exceeded {TEST_TIMEOUT_SECONDS}s and was killed.\n"
            "   This is a hang, not a slow suite — find it with:\n"
            "     .venv/bin/python -m pytest -q --tb=no -rf --durations=15\n"
            "   If the suite is legitimately this slow, raise POPDD_TEST_TIMEOUT.\n"
        )
        return 1

    passed, failed = 0, 0
    failed_tests = []
    for line in result.stdout.splitlines():
        m = re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", line)
        if m:
            failed = int(m.group(1))
        # e.g. "FAILED tests/scheduler/test_alerts.py::test_x - AssertionError: ..."
        m = re.match(r"(?:FAILED|ERROR)\s+(\S+)", line)
        if m:
            failed_tests.append(m.group(1))

    verdict = "PASS" if result.returncode == 0 and failed == 0 else "FAIL"
    agent.sign_generic(
        action="test-run:complete",
        target="prospector:test-suite",
        **{
            "verdict": verdict,
            "passed": passed,
            "failed": failed,
            "failedTests": failed_tests,
            "exitCode": result.returncode,
        },
    )

    verify = agent.verify_chain()
    # (auto-saved by PopddAgent)

    print(f"\n{'=' * 60}")
    print("  Prospector POPDD Run Complete")
    print(f"{'=' * 60}")
    print(f"  Test verdict:  {verdict} ({passed} passed, {failed} failed)")
    for nodeid in failed_tests:
        print(f"    FAILED       {nodeid}")
    if failed and not failed_tests:
        print("    (failure count reported but no node ids parsed — check pytest output format)")
    print(f"  Chain valid:   {verify['valid']}")
    print(f"{'=' * 60}\n")
    return 0 if verify['valid'] and verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

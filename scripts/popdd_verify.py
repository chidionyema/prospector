#!/usr/bin/env python3
"""
Prospector POPDD Test Runner

Runs the Prospector test suite and signs the result into a POPDD chain,
demonstrating POPDD works as an integrated audit-trail component in
this project.

Usage:
    python scripts/popdd_verify.py
"""

import re
import subprocess
import sys
from pathlib import Path

from popdd_agent import PopddAgent

ROOT = Path(__file__).parent.parent


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
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

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

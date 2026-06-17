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

from popdd import HmacSigner, ReceiptChain

ROOT = Path(__file__).parent.parent
KEY_PATH = ROOT / ".lux" / "keys" / "agent.pem"
RECEIPTS_DIR = ROOT / ".lux" / "receipts"


def main() -> int:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

    signer = HmacSigner(HmacSigner.load_or_create_key(KEY_PATH))
    chain = ReceiptChain(signer, agent_id="prospector-pipeline")

    chain.append(
        action="test-run:start",
        target="prospector:test-suite",
        proof={"verdict": "STARTED", "command": "pytest -q --tb=no"},
    )

    print("Running Prospector test suite...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

    passed, failed = 0, 0
    for line in result.stdout.splitlines():
        m = re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", line)
        if m:
            failed = int(m.group(1))

    verdict = "PASS" if result.returncode == 0 and failed == 0 else "FAIL"
    chain.append(
        action="test-run:complete",
        target="prospector:test-suite",
        proof={
            "verdict": verdict,
            "passed": passed,
            "failed": failed,
            "exitCode": result.returncode,
        },
    )

    verify = chain.verify()
    chain_path = RECEIPTS_DIR / f"prospector-test-{result.returncode}.jsonl"
    chain.save(chain_path)

    print(f"\n{'=' * 60}")
    print("  Prospector POPDD Run Complete")
    print(f"{'=' * 60}")
    print(f"  Test verdict:  {verdict} ({passed} passed, {failed} failed)")
    print(f"  Chain valid:   {verify.valid}")
    print(f"  Chain path:    {chain_path}")
    print(f"{'=' * 60}\n")
    return 0 if verify.valid and verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

"""A gate tested only on the case it refuses has not been shown safe to install.

INCIDENT. On 2026-08-23 two guards on this estate refused correct work in one evening: the LAW 32
documentation gate read the first word of a commit subject as the feature name, and the hook
router refused outright in any repository shipping no pre-push, which left four of six
repositories here unable to push at all. Both had been tested on the bad case only.

So this asserts the rule, not the implementation: the ratchet must ALLOW the repository exactly as
it stands, and must REFUSE a change that adds a reference to a vendor being left. Either half
failing alone is a defect.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vendor_ratchet.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_it_allows_the_repository_as_it_stands():
    """The ALLOW half. A gate everyone has to bypass measures nothing."""
    result = _run("--check")
    assert result.returncode == 0, (
        "the ratchet refuses the repository as committed, so every honest change would have to "
        f"bypass it:\n{result.stdout}{result.stderr}"
    )


def test_it_refuses_a_new_reference_to_a_vendor_we_are_leaving(tmp_path):
    """The REFUSE half, driven through git so the counter sees the file the way CI would."""
    added = ROOT / "deploy" / "_ratchet_probe_delete_me.sh"
    added.write_text("#!/bin/sh\nfly deploy -a a-new-dependency\n")
    try:
        # The counter reads `git ls-files`, so an untracked file is invisible to it. --intent-to-add
        # makes it tracked without staging content, which is the state a real commit passes through.
        subprocess.run(["git", "add", "-N", str(added)], cwd=ROOT, check=True, capture_output=True)
        result = _run("--check")
        assert result.returncode == 1, (
            "the ratchet allowed a brand new `fly deploy` call-site:\n"
            f"{result.stdout}{result.stderr}"
        )
        assert "_ratchet_probe_delete_me.sh" in result.stdout, (
            "it refused without naming the file that caused it, so the next agent has to derive "
            f"the diff by hand:\n{result.stdout}"
        )
    finally:
        subprocess.run(
            ["git", "rm", "-q", "--cached", "--force", str(added)],
            cwd=ROOT, capture_output=True,
        )
        added.unlink(missing_ok=True)


def test_it_allows_again_once_the_new_reference_is_gone():
    """A gate that stays red after the cause is removed is an outage, not a guard."""
    result = _run("--check")
    assert result.returncode == 0, (
        f"still refusing after the probe file was removed:\n{result.stdout}{result.stderr}"
    )

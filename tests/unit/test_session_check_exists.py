"""The script the operating rules name must exist, must run, and must stay read-only.

`scripts/session_check.py` is the first of the ways-of-working rules made mechanical, and
global CLAUDE.md tells every session to run it before ending. Nothing guarded it. A rename,
a deletion, or an import error would leave every session getting
`[Errno 2] No such file or directory` from the one command that is supposed to catch
unshipped work -- and a session that skipped the command looks exactly the same.

The read-only assertion is the load-bearing one. The script is run at the end of a session,
often unattended. If it ever grew the ability to commit, push or merge, a hygiene check
would become an unattended write to a shared repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "session_check.py"


def test_session_check_script_exists() -> None:
    assert SCRIPT.is_file(), (
        f"{SCRIPT} is missing. Global CLAUDE.md tells every session to run it before ending, "
        "so a session cannot follow the rule without it."
    )


def test_session_check_help_runs() -> None:
    """--help exercises import and argument parsing without touching git or the network."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--local" in proc.stdout, proc.stdout


def test_session_check_is_read_only() -> None:
    """It reports; it never ships on your behalf.

    Every git and gh call it makes must be one that reads. This asserts on the source rather
    than on behaviour because the failure being guarded against is someone adding a --fix in
    good faith, and a behavioural test would have to run the write to catch it.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    for verb in ("commit", "push", "merge", "prune", "reset", "checkout"):
        assert f'"{verb}"' not in source, (
            f'session_check.py passes "{verb}" to a subprocess. It must stay read-only: '
            "it runs at the end of a session, often unattended."
        )

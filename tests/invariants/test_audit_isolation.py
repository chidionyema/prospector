"""The test suite must never write to the production audit log.

store/scheduler/audit/<today>.jsonl is evidence: it is what we read to decide what the
daemon actually did. On 2026-07-31 six `brain_fallthrough` rows carrying fixture values
("served": "b", "last_err": "gemini cli exhausted: reset after 2h0m0s") sat in the
production log at pytest pids and read exactly like a live moat failure — the wrong
verdict was drawn from them before the pids were matched to test runs.

The guard is the autouse `_isolate_audit_log` fixture in tests/conftest.py. These tests
fail if that fixture is removed or stops working.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import prospector.audit as A

REAL_AUDIT_DIR = Path("store/scheduler/audit")
REPO_ROOT = Path(A.__file__).resolve().parent.parent


def _real_log_size() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REAL_AUDIT_DIR / f"{today}.jsonl"
    return path.stat().st_size if path.exists() else 0


def test_audit_dir_is_not_the_production_dir():
    assert A._AUDIT_DIR.resolve() != REAL_AUDIT_DIR.resolve()


def test_writing_an_audit_row_leaves_the_production_log_untouched():
    before = _real_log_size()
    A.audit("brain_fallthrough", served="test-brain", skipped=["a(test)"], last_err="test")
    assert _real_log_size() == before, (
        "a test wrote to the production audit log — the _isolate_audit_log fixture in "
        "tests/conftest.py is not in effect"
    )


def test_the_row_did_land_in_the_redirected_log():
    """Isolation must redirect the write, not silence it — otherwise this proves nothing."""
    A.audit("search", provider="fixture", query="q", returned_n=0, status="ok")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    written = (A._AUDIT_DIR / f"{today}.jsonl").read_text()
    # Rows are compact JSON (no space after ':') — the separator that made a grep for
    # '"pid": 46335' silently match nothing on 2026-07-31.
    assert '"provider":"fixture"' in written


def test_the_default_audit_dir_does_not_follow_the_cwd(tmp_path):
    """The trail belongs to the checkout that owns the code, not to whoever launched it.

    The default used to be the relative string "store/scheduler/audit", so a process that
    imported prospector from another directory wrote ITS store instead. That is not a
    hypothetical: `~/Documents/code/sentinel-loop/store/scheduler/audit/2026-06-26.jsonl`
    holds 10KB of real prospector rows, and two worktrees have their own partial copies —
    evidence that reads as missing from here, and as someone else's from there.

    Runs in a subprocess with cwd=tmp_path because the defect is fixed at import time and
    cannot be observed in a process that already imported the module. Env is scrubbed of
    PROSPECTOR_AUDIT_DIR so the conftest isolation fixture cannot mask the result.

    The subprocess deliberately only IMPORTS and prints — it never calls audit(). An
    unpatched child writing a row would land it in the real production log, which is the
    precise pollution the rest of this file exists to prevent. The two asserts below cover
    both halves anyway: an absolute repo-anchored path (the write would go to the right
    place) and an absent tmp store/ (the import no longer creates a tree on its own).
    """
    import os
    env = {k: v for k, v in os.environ.items() if k != "PROSPECTOR_AUDIT_DIR"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    out = subprocess.run(
        [sys.executable, "-c", "from prospector.audit import _AUDIT_DIR; print(_AUDIT_DIR)"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert Path(out).is_absolute(), f"default audit dir is cwd-relative: {out!r}"
    assert Path(out) == REPO_ROOT / "store" / "scheduler" / "audit"
    assert not (tmp_path / "store").exists(), (
        "merely importing prospector from an unrelated directory created a store/ tree there"
    )

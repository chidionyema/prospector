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

from datetime import datetime, timezone
from pathlib import Path

import prospector.audit as A

REAL_AUDIT_DIR = Path("store/scheduler/audit")


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

"""A fresh store must survive N processes opening it at once.

This pins the defect that broke CI on 2026-08-15, three runs out of three, without ever
naming a test: `tests/integration/test_api.py` imports `prospector.api`, which builds
`Store(cfg)` at MODULE scope, so every pytest-xdist worker constructs a Store against the
same database within milliseconds of the others. `_connect` then issued
`PRAGMA journal_mode=WAL` unconditionally; that transition takes an EXCLUSIVE lock and
does NOT honour the connect timeout's busy handler, so the losers raised
`sqlite3.OperationalError: database is locked` during COLLECTION. gw0 and gw1 disagreed
about what they had collected and xdist aborted the run.

Two things about the shape of this test are deliberate:

* It uses `subprocess`, not `multiprocessing`. A spawned multiprocessing pool under pytest
  hangs on this codebase, and separate interpreters are a truer model of xdist workers
  anyway — the lock is held across PROCESSES, and threads in one process would share a
  connection cache and never reproduce it.
* It runs against a fresh temp directory every round, because that is the only state in
  which the bug exists. A developer's `store/prospector.db` is already WAL, so the pragma
  is a no-op and the race never opens — which is exactly why this passed locally for
  everyone while CI died.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Constructs a Store the way `prospector.api` does at import time, against a store dir
# handed in on argv. Exits non-zero (with the sqlite error on stderr) if it cannot.
_CHILD = """
import sys
sys.path.insert(0, {root!r})
from prospector.config import load_config
from prospector.store import Store
cfg = load_config()
cfg.store["dir"] = sys.argv[1]
Store(cfg)
"""


@pytest.mark.parametrize("workers", [6])
def test_concurrent_store_construction_does_not_lock_the_database(tmp_path, workers):
    for round_index in range(4):
        store_dir = tmp_path / f"round{round_index}"
        store_dir.mkdir()
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", _CHILD.format(root=str(REPO_ROOT)), str(store_dir)],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(workers)
        ]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            assert proc.returncode == 0, (
                "a concurrent opener failed to construct a Store on a fresh database; "
                f"round {round_index}: {err.decode(errors='replace').strip()[-2000:]}"
            )
        assert (store_dir / "prospector.db").exists()

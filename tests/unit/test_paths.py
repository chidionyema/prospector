"""`prospector.paths` — resolution happens per call, and the overrides reach imported modules.

The whole value of this module is the second property. `tests/conftest.py` had to work around
its absence in prose: "audit.py binds _AUDIT_DIR at import (audit.py:66), so setenv alone is a
no-op for an already-imported module" — the binding that wrote fixture rows into the production
audit log and 1,874 fixture `LAW:` lines into the durable ledger. A test that only checked
`store_path()` returns the right string would not have caught that; the ones here import a
consumer FIRST and then move the root.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from prospector import paths

ROOT = Path(__file__).resolve().parents[2]


def test_anchor_is_the_repo_containing_the_package():
    assert paths.ANCHOR == ROOT
    assert (paths.ANCHOR / "prospector" / "paths.py").is_file()


def test_defaults_ignore_the_working_directory(tmp_path, monkeypatch):
    """The defect in one assertion: cwd moves, the resolved store does not."""
    monkeypatch.delenv(paths.REPO_ROOT_ENV, raising=False)
    monkeypatch.delenv(paths.STORE_ROOT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.store_root() == ROOT / "store"
    assert paths.repo_path("config.yaml") == ROOT / "config.yaml"


def test_repo_root_override_moves_the_store_with_it(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.STORE_ROOT_ENV, raising=False)
    monkeypatch.setenv(paths.REPO_ROOT_ENV, str(tmp_path))
    assert paths.repo_root() == tmp_path
    assert paths.store_path("scheduler", "q.jsonl") == tmp_path / "store" / "scheduler" / "q.jsonl"


def test_store_root_override_wins_over_repo_root(tmp_path, monkeypatch):
    """A fixture that only wants runtime state redirected must not have to fake a whole repo."""
    monkeypatch.setenv(paths.REPO_ROOT_ENV, str(tmp_path / "repo"))
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path / "elsewhere"))
    assert paths.store_root() == tmp_path / "elsewhere"
    assert paths.repo_path("config.yaml") == tmp_path / "repo" / "config.yaml"


def test_the_override_reaches_a_module_that_was_imported_first(tmp_path, monkeypatch):
    """The property a module-level constant cannot have.

    `tools.unlist_killed` is imported at the top of this test session, long before the env var
    is set. If it had kept `QUEUE = Path("store/scheduler/pending_unlist.jsonl")` this would
    still point at the production queue.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import unlist_killed  # noqa: PLC0415 - imported here on purpose, before the setenv

    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path))
    assert unlist_killed._queue() == tmp_path / "scheduler" / "pending_unlist.jsonl"
    assert unlist_killed._done() == tmp_path / "scheduler" / "pending_unlist.done.jsonl"


def test_resolution_is_not_cached_between_calls(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path / "a"))
    first = paths.store_path("x")
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path / "b"))
    assert paths.store_path("x") != first


def test_a_subprocess_inherits_the_override(tmp_path):
    """Most of the affected code runs as its own process (the daemon, the backfill driver,
    the cockpit runner), so the override has to survive the fork, not just the import."""
    env = {**os.environ, paths.STORE_ROOT_ENV: str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c",
         "from prospector import paths; print(paths.store_path('dossiers'))"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == str(tmp_path / "dossiers")

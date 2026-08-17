"""The shelf-coverage probe must read the store, not the directory its code sits in.

Production moved to its own checkout on 2026-08-17 (`prospector-live`) with
`PROSPECTOR_STORE_DIR` pinned back at the canonical store in the developer checkout. This
tool built both of its paths from `__file__`, so it looked for
`prospector-live/store/prospector.db`, which does not exist. Every live tick's recovery step
failed with `sqlite3.OperationalError: unable to open database file`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "verify_pass_shelf_coverage.py"


def _load():
    """Import the tool by path — `tools/` is a script directory, not a package."""
    spec = importlib.util.spec_from_file_location("verify_pass_shelf_coverage", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load()


def _make_db(store: Path, cid: str = "abc123") -> None:
    store.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(store / "prospector.db")
    conn.execute("CREATE TABLE dossiers (candidate_id TEXT, created_at TEXT, "
                 "decision TEXT, provisional INT, tombstone TEXT)")
    conn.execute("INSERT INTO dossiers VALUES (?, '2026-08-17', 'pass', 0, NULL)", (cid,))
    conn.commit()
    conn.close()


def test_store_dir_env_wins_over_the_code_location(mod, tmp_path, monkeypatch):
    store = tmp_path / "canonical-store"
    store.mkdir()
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))
    assert mod._store("/some/other/checkout") == str(store)


def test_store_dir_falls_back_to_repo_store(mod, monkeypatch):
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    assert mod._store("/checkout") == os.path.join("/checkout", "store")


def test_blank_store_dir_is_treated_as_unset(mod, monkeypatch):
    # launchd hands through an empty string for an unset key rather than omitting it.
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", "   ")
    assert mod._store("/checkout") == os.path.join("/checkout", "store")


def test_passes_reads_the_pinned_store_not_the_repo(mod, tmp_path, monkeypatch):
    """The exact production shape: the code checkout has NO store, the pinned one does."""
    code_checkout = tmp_path / "prospector-live"
    code_checkout.mkdir()
    store = tmp_path / "prospector" / "store"
    _make_db(store)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))

    rows = mod._passes(str(code_checkout))

    assert rows == [("abc123", "2026-08-17")]


def test_passes_without_the_env_var_still_reads_repo_store(mod, tmp_path, monkeypatch):
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    repo = tmp_path / "prospector"
    _make_db(repo / "store", cid="def456")

    assert mod._passes(str(repo)) == [("def456", "2026-08-17")]


def test_why_reads_the_lint_record_from_the_pinned_store(mod, tmp_path, monkeypatch):
    code_checkout = tmp_path / "prospector-live"
    code_checkout.mkdir()
    store = tmp_path / "prospector" / "store"
    (store / "dossiers").mkdir(parents=True)
    (store / "dossiers" / "abc123.lint.json").write_text(json.dumps(
        {"ok": True, "pack_complete": True}))
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(store))

    # Without the fix this reads prospector-live/store/dossiers/, finds nothing, and reports
    # every pack as "never published" — a false accusation, not a missing answer.
    assert mod._why(str(code_checkout), "abc123").startswith("READY")

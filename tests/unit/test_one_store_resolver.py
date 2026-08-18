"""There is exactly one store, so there is exactly one answer to where it is.

WHY THIS EXISTS. Measured 2026-08-18 on the running Fly engine: `/app/store/listings` held four
listing files and `/app/store/pricing` four rationales, written that afternoon, while the real
store is the volume at `/data/store`. `/app` is the image layer, so the next deploy erases them.

The cause was two resolvers reading two different environment variables. `config.store_root()`
read `PROSPECTOR_STORE_DIR`, which production sets. `paths.store_root()` read
`PROSPECTOR_STORE_ROOT`, which nothing sets, so every `paths.store_path(...)` caller fell back to
a root derived from `__file__` -- the documented trap, reintroduced in a second module.

These tests fail if the two ever disagree again.
"""
from __future__ import annotations

import importlib

from prospector import config, paths


def test_paths_and_config_agree_on_the_production_variable(monkeypatch, tmp_path):
    """PROSPECTOR_STORE_DIR is what the plists and the Fly engine export. Both must honour it."""
    monkeypatch.delenv("PROSPECTOR_STORE_ROOT", raising=False)
    monkeypatch.delenv("PROSPECTOR_REPO_ROOT", raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "data" / "store"))
    importlib.reload(paths)
    assert paths.store_root() == config.store_root()
    assert paths.store_root() == tmp_path / "data" / "store"


def test_store_root_still_wins_so_a_fixture_can_redirect(monkeypatch, tmp_path):
    """A developer box exports STORE_DIR for the daemon. A test redirecting the store must still
    win, or the suite reads and writes the real catalogue."""
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "daemon"))
    monkeypatch.setenv("PROSPECTOR_STORE_ROOT", str(tmp_path / "fixture"))
    importlib.reload(paths)
    assert paths.store_root() == tmp_path / "fixture"


def test_no_third_resolver_appears(monkeypatch, tmp_path):
    """Every store path in the package must come from one of the two agreeing resolvers. A module
    that derives its own from __file__ is how this bug arrived, twice."""
    monkeypatch.delenv("PROSPECTOR_STORE_ROOT", raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "one"))
    importlib.reload(paths)
    assert paths.store_path("listings") == config.store_root() / "listings"
    assert paths.store_path("scheduler", "x.jsonl") == config.store_root() / "scheduler" / "x.jsonl"

"""Two store-root resolvers must agree.

`prospector.config.store_root()` reads `PROSPECTOR_STORE_DIR`. `prospector.paths.store_root()`
read `PROSPECTOR_STORE_ROOT` and nothing else. Every deployment sets only the first, so the two
functions returned different directories in production.

Measured on the production engine on 2026-08-18:

    paths=  /app/store      <- container filesystem, thrown away by the next deploy
    config= /data/store     <- the mounted volume

Sixteen files written that morning (eight listings, eight pricing rationales) were in the copy a
deploy destroys. `prospector/ops/readers.py` resolves through `paths.store_path()` at eleven
sites, so the ops console read a root the engine never wrote to.

These tests fail on the old code and pass on the new.
"""
from __future__ import annotations

from pathlib import Path

from prospector import config, paths


def test_store_dir_env_moves_both_resolvers(monkeypatch, tmp_path):
    """The variable the deployments set must move `paths` as well as `config`."""
    monkeypatch.delenv(paths.STORE_ROOT_ENV, raising=False)
    monkeypatch.delenv(paths.REPO_ROOT_ENV, raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "data" / "store"))

    assert paths.store_root() == config.store_root()
    assert paths.store_root() == tmp_path / "data" / "store"


def test_store_root_env_still_wins(monkeypatch, tmp_path):
    """Test fixtures set `PROSPECTOR_STORE_ROOT` to redirect one test; it keeps priority."""
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path / "fixture"))
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "deployment"))

    assert paths.store_root() == tmp_path / "fixture"


def test_empty_is_unset(monkeypatch, tmp_path):
    """An exported-but-empty variable is not a path.

    `config.store_root()` already `.strip()`s and treats empty as unset. A plist or a Dockerfile
    that exports the name without a value would otherwise send the store to the process cwd.
    """
    monkeypatch.delenv(paths.REPO_ROOT_ENV, raising=False)
    monkeypatch.setenv(paths.STORE_ROOT_ENV, "  ")
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "data"))
    assert paths.store_root() == tmp_path / "data"

    monkeypatch.setenv("PROSPECTOR_STORE_DIR", "")
    assert paths.store_root() == paths.repo_root() / "store"


def test_no_env_at_all_is_the_repo_store(monkeypatch):
    monkeypatch.delenv(paths.STORE_ROOT_ENV, raising=False)
    monkeypatch.delenv("PROSPECTOR_STORE_DIR", raising=False)
    monkeypatch.delenv(paths.REPO_ROOT_ENV, raising=False)

    assert paths.store_root() == paths.ANCHOR / "store"
    assert isinstance(paths.store_path("scheduler", "heartbeat.json"), Path)

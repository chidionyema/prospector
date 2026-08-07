"""Where this repo writes — resolved when it is asked, never bound at import.

The defect class this exists to close
-------------------------------------
A module-level ``Path("store/...")`` is wrong twice, and both failures are silent:

1. **It is cwd-relative.** The daemon, the cockpit, the backfill drivers and every manual CLI
   run get their cwd from whatever launched them. `com.prospector.backup.plist` sets
   `WorkingDirectory`; a shell one-liner, a worktree, a cron entry or an editor's run button
   does not. When cwd is not the repo root the process happily creates a *second* `store/`
   next to wherever it started and writes real state into it, and nothing raises — the bug
   surfaces later as "the queue is empty" or "that listing never got archived".

2. **It is bound before any test fence can move it.** `tests/conftest.py` documents this in
   its own words: "audit.py binds _AUDIT_DIR at import (audit.py:66), so setenv alone is a
   no-op for an already-imported module." That binding is how pytest wrote fixture rows into
   the production audit log and 1,874 fixture `LAW:` lines into the durable ledger — junk that
   then fed the generator prompt as "concepts mathematically proven to fail".

Anchoring to ``__file__`` fixes (1) but not (2): it just makes the wrong target deterministic.
Resolving on every call fixes both, which is why these are functions and not constants.

Usage
-----
    from prospector import paths

    def _queue() -> Path:
        return paths.store_path("scheduler", "pending_unlist.jsonl")

Call it at the point of use. Assigning ``QUEUE = paths.store_path(...)`` at module level
re-introduces exactly the binding this module exists to remove.

Overrides
---------
``PROSPECTOR_STORE_ROOT`` moves everything under ``store/``; ``PROSPECTOR_REPO_ROOT`` moves the
repo anchor itself (and therefore ``store/`` too, unless the first is also set). Both are read
per call, so a fixture that sets them with ``monkeypatch.setenv`` works on an already-imported
module — the case the audit-log fence had to work around by patching a module attribute.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["ANCHOR", "repo_root", "repo_path", "store_root", "store_path"]

#: The repo this file lives in. A constant is correct HERE and only here: it describes the
#: location of the source tree, which cannot change while the process runs.
ANCHOR = Path(__file__).resolve().parent.parent

REPO_ROOT_ENV = "PROSPECTOR_REPO_ROOT"
STORE_ROOT_ENV = "PROSPECTOR_STORE_ROOT"


def repo_root() -> Path:
    """The repo root, honouring `PROSPECTOR_REPO_ROOT`."""
    override = os.environ.get(REPO_ROOT_ENV)
    return Path(override) if override else ANCHOR


def repo_path(*parts: str) -> Path:
    """A path relative to the repo root (`config.yaml`, `prompts/`, ...)."""
    return repo_root().joinpath(*parts)


def store_root() -> Path:
    """The runtime state root, honouring `PROSPECTOR_STORE_ROOT` then `PROSPECTOR_REPO_ROOT`."""
    override = os.environ.get(STORE_ROOT_ENV)
    return Path(override) if override else repo_root() / "store"


def store_path(*parts: str) -> Path:
    """A path under `store/` — `store_path("scheduler", "pending_unlist.jsonl")`."""
    return store_root().joinpath(*parts)

"""The CLI governor's ceiling must be machine-wide, not per-checkout.

Regression test for a bug that hid inside the fix for the original one. `cli_governor.py`
was written to replace per-process `threading.Semaphore`s with a cross-process flock
ceiling, but it anchored its slot directory to the checkout containing the module:

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

A git worktree is a full checkout, so every worktree got its own slot directory and its own
private ceiling. On 2026-07-31 this machine held seven worktrees, five carrying their own
copy of the module — so a configured cap of 8 was really a cap of up to 40 concurrent CLI
subprocesses on 12 cores. Proven at the time by building two governors with `n=1` from two
different worktrees and watching both acquire.

These tests encode that measurement so the anchor cannot quietly return to `__file__`.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

from prospector import cli_governor

REPO = Path(__file__).resolve().parents[2]


def _load_copy(tmp_path: Path, tag: str):
    """Load a second copy of the module from a different directory.

    This is the whole point: it stands in for the same code running out of another git
    worktree, which is exactly how the original bug reached production.
    """
    pkg = tmp_path / tag / "prospector"
    pkg.mkdir(parents=True)
    shutil.copy(cli_governor.__file__, pkg / "cli_governor.py")
    spec = importlib.util.spec_from_file_location(f"cli_governor_{tag}", pkg / "cli_governor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slot_root_is_outside_the_checkout(monkeypatch):
    monkeypatch.delenv("PROSPECTOR_CLI_SLOTS", raising=False)
    root = Path(cli_governor._slot_root("scope_test"))
    assert REPO not in root.parents, (
        f"slot root {root} lives inside the checkout, so every worktree gets its own "
        "ceiling and the cap multiplies by the number of checkouts"
    )


def test_two_checkouts_share_one_ceiling(tmp_path, monkeypatch):
    """n=1 must mean one holder on the machine, not one holder per copy of the module."""
    monkeypatch.delenv("PROSPECTOR_CLI_SLOTS", raising=False)
    other = _load_copy(tmp_path, "worktree_b")

    assert other._slot_root("shared_ceiling") == cli_governor._slot_root("shared_ceiling")

    here = cli_governor.make_governor(1, "shared_ceiling")
    there = other.make_governor(1, "shared_ceiling")

    assert here.acquire(timeout=1) is True
    try:
        assert there.acquire(timeout=1) is False, (
            "a second checkout acquired a slot the first one was holding — the ceiling is "
            "per-checkout again"
        )
    finally:
        here.release()

    # And the slot must be genuinely reusable afterwards: a ceiling that never releases is
    # a deadlock, which would be a worse failure than the oversubscription it replaced.
    assert there.acquire(timeout=5) is True
    there.release()


def test_env_override_isolates_a_run(tmp_path, monkeypatch):
    """PROSPECTOR_CLI_SLOTS is the deliberate escape hatch — it must actually take effect."""
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "private"))
    root = Path(cli_governor._slot_root("isolated"))
    assert str(tmp_path) in str(root)
    assert os.path.isdir(root)

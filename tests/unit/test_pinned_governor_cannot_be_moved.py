"""The "1 claude cli" ceiling is only real if the slot DIRECTORY is fixed too.

`claude_cli._clamped` (claude_cli.py:93) refuses any width above `MAX_CLAUDE_CLI = 1`, and
it does that correctly. It bounds the width of ONE governor. It never bounded the NUMBER of
governors, and `cli_governor._slot_root` used to take the address of the slot directory from
the environment:

    PROSPECTOR_CLI_SLOTS=/tmp/mine  ->  /tmp/mine/claude/slot_0.lock
    unset                           ->  ~/.prospector/cli_slots/claude/slot_0.lock

Two different files, so two processes each holding "the only slot" ran two claude CLI
subprocesses and no guard fired. Found on 2026-08-21 by walking into it, the day after the
founder set the ceiling at one ("1 claude cli, not 4", reaffirmed "1 claude cli rule stands").

$HOME is the same hole through a different door: `os.path.expanduser("~")` returns $HOME when
it is set, so `HOME=/tmp/mine` moves the shared directory just as well.

These tests pin both doors shut for the pinned brands, and pin the escape hatch that replaced
them — an explicit `root=` argument, which takes a code change a reviewer can see rather than
an environment variable a running process can export.
"""
from __future__ import annotations

import os

import pytest

from prospector import cli_governor
from prospector.cli_governor import PINNED_BRANDS, make_governor


def test_claude_is_pinned():
    """If this list ever loses "claude" the rest of this file passes while proving nothing."""
    assert "claude" in PINNED_BRANDS


def test_env_override_does_not_move_a_pinned_brand(monkeypatch, tmp_path):
    monkeypatch.delenv("PROSPECTOR_CLI_SLOTS", raising=False)
    shared = cli_governor._slot_root("claude")
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "private"))
    moved = cli_governor._slot_root("claude")
    assert moved == shared, "PROSPECTOR_CLI_SLOTS moved the claude slot directory"
    assert not str(moved).startswith(str(tmp_path))


def test_env_override_still_moves_an_unpinned_brand(monkeypatch, tmp_path):
    """The hatch is narrowed, not removed: cursor and the tools still get a private pool."""
    assert "cursor" not in PINNED_BRANDS
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "private"))
    root = cli_governor._slot_root("cursor")
    assert str(root).startswith(str(tmp_path)), root


def test_home_does_not_move_a_pinned_brand(monkeypatch, tmp_path):
    """$HOME is read by expanduser, so a process could export it and get a private pool."""
    monkeypatch.delenv("PROSPECTOR_CLI_SLOTS", raising=False)
    real = cli_governor._slot_root("claude")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli_governor._slot_root("claude") == real
    assert not str(cli_governor._slot_root("claude")).startswith(str(tmp_path))


def test_second_governor_on_the_same_root_cannot_acquire(tmp_path):
    """The ceiling itself, in the only way that proves it: the second holder is refused.

    Run on an explicit private root so this never competes with a live daemon for the real
    slot files — that coupling already broke every commit once (see
    tests/faults/test_grounding_contention.py).
    """
    root = str(tmp_path / "slots")
    a = make_governor(1, "claude", root=root)
    b = make_governor(1, "claude", root=root)
    assert a.acquire(timeout=1) is True
    try:
        assert b.acquire(timeout=0.5) is False, "a ceiling of 1 must refuse the second holder"
    finally:
        a.release()
    assert b.acquire(timeout=1) is True
    b.release()


def test_explicit_root_is_honoured_for_a_pinned_brand(tmp_path):
    """The replacement hatch has to work, or the tests above just break the test suite."""
    root = str(tmp_path / "slots")
    sem = make_governor(1, "claude", root=root)
    assert sem.acquire(timeout=1)
    try:
        assert os.path.exists(os.path.join(root, "claude", "slot_0.lock"))
    finally:
        sem.release()


@pytest.mark.parametrize("value", ["relative/dir", "1"])
def test_relative_override_is_still_refused_for_an_unpinned_brand(monkeypatch, tmp_path, value):
    """A relative value reads like a slot COUNT; honouring it creates a pool under the cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", value)
    root = cli_governor._slot_root("cursor")
    assert not str(root).startswith(str(tmp_path)), root

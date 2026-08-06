"""The CLI cwd pool: one STABLE directory per concurrency slot.

Two properties pull against each other here, and the first implementation bought one by
paying the other on every call:

  * COLLISION SAFETY — two concurrent `claude -p` sharing a cwd clobber each other's Claude
    Code session state (PROVEN 2026-07-02, `claude_cli.py`: concurrency=2 → 0/3 candidates,
    serialized → 2/3). `mkdtemp` per call bought this.
  * CACHE WARMTH — a cwd never seen before is a cold prompt cache. `mkdtemp` per call
    guaranteed one on EVERY call: measured 2026-08-06, 8.6x the cost for identical output.

Binding the cwd to the governor's slot index gives both at once, because holding
`slot_i.lock` is already a machine-wide `LOCK_EX` flock. These tests exist so a future
change cannot quietly restore either failure: `test_concurrent_calls_never_share_a_cwd`
is the 2026-07-02 regression, `test_sequential_calls_reuse_one_cwd` is the cost one.

All tests point PROSPECTOR_CLI_SLOTS at a tmpdir. Without that they contend for the
machine-wide slot files with the live daemon and hang or flake.
"""
from __future__ import annotations

import json
import os
import threading

import pytest

from prospector import claude_cli
from prospector.cli_governor import make_governor


@pytest.fixture
def pooled(tmp_path, monkeypatch):
    """claude_cli wired to a private slot root and a private neutral cwd."""
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "slots"))
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    monkeypatch.setattr(claude_cli, "_NEUTRAL_CWD", str(neutral))
    monkeypatch.setattr(claude_cli, "_CLI_SEM", make_governor(2, "claude_test"))
    # record_usage writes to the real telemetry store; a unit test must not touch it.
    monkeypatch.setattr(claude_cli, "_record_claude_usage", lambda *a, **k: None)
    return neutral


class _Proc:
    returncode = 0
    stderr = ""
    stdout = json.dumps({"type": "result", "subtype": "success", "result": "ok"})


def _fake_run(record, gate=None):
    def run(cmd, **kw):
        record.append(kw["cwd"])
        if gate is not None:
            # Force genuine overlap: neither call may return until both are inside.
            gate.wait(timeout=5)
        return _Proc()
    return run


def _call():
    return claude_cli._attempt_claude_cli(["claude"], 10, False, 5)


# --- the cost property -------------------------------------------------------------------

def test_sequential_calls_reuse_one_cwd(pooled, monkeypatch):
    """Back-to-back calls must land in the SAME directory, or the prompt cache is cold.

    This is the $191-450/day regression: `mkdtemp` per call made every one of these a
    distinct path, and a distinct path is a distinct Claude Code session slug.
    """
    seen: list[str] = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(seen))

    for _ in range(4):
        assert _call() == "ok"

    assert len(set(seen)) == 1, f"expected one stable cwd, got {sorted(set(seen))}"


def test_cwd_survives_the_call(pooled, monkeypatch):
    """The directory must NOT be deleted afterwards — deleting it is what threw the cache away."""
    seen: list[str] = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(seen))

    _call()

    assert os.path.isdir(seen[0]), "slot cwd was removed; the next call would run cold"


# --- the 2026-07-02 collision property ---------------------------------------------------

def test_concurrent_calls_never_share_a_cwd(pooled, monkeypatch):
    """The regression guard for 2026-07-02: overlapping calls get DISTINCT directories.

    `gate` holds both fake subprocesses open simultaneously, so this fails if the pool ever
    hands the same path to two in-flight callers.
    """
    seen: list[str] = []
    lock = threading.Lock()
    gate = threading.Barrier(2)

    def run(cmd, **kw):
        with lock:
            seen.append(kw["cwd"])
        gate.wait(timeout=5)
        return _Proc()

    monkeypatch.setattr(claude_cli.subprocess, "run", run)

    threads = [threading.Thread(target=_call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert len(seen) == 2, f"both calls must have run; got {seen}"
    assert len(set(seen)) == 2, f"concurrent calls shared a cwd: {seen}"


def test_slot_is_released_and_reused(pooled, monkeypatch):
    """A released slot returns to the pool — otherwise the pool leaks and starves."""
    seen: list[str] = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(seen))

    for _ in range(6):
        _call()

    # 6 sequential calls, 2 slots: every call takes the first free slot, so all reuse slot_0.
    assert set(seen) == {os.path.join(str(pooled), "slot_0")}


# --- the neutrality property that must not be lost in the move -------------------------

def test_cwd_stays_outside_the_repo(pooled, monkeypatch):
    """Running inside REPO_ROOT loads the project CLAUDE.md and the CLI goes meta instead of
    emitting candidate JSON (PROVEN 2026-07-02). The pool must not walk the cwd back in."""
    seen: list[str] = []
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(seen))

    _call()

    resolved = os.path.realpath(seen[0])
    repo = os.path.realpath(claude_cli.REPO_ROOT)
    assert not resolved.startswith(repo + os.sep), f"{resolved} is inside the repo"


# --- the governor contract the pool rests on -------------------------------------------

def test_slot_index_is_exclusive_across_processes(tmp_path, monkeypatch):
    """The whole design rests on this: two holders can never be told the same index.

    Two SEPARATE governor objects on one slot root stand in for two processes — the same
    substitution `cli_governor`'s own docstring uses for the per-checkout ceiling bug.
    """
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "slots"))
    a, b = make_governor(2, "excl"), make_governor(2, "excl")
    c = make_governor(2, "excl")

    assert a.acquire(timeout=1) and b.acquire(timeout=1)
    try:
        assert {a.current_slot(), b.current_slot()} == {0, 1}
        assert c.acquire(timeout=0.5) is False, "ceiling of 2 admitted a third holder"
    finally:
        a.release()
        b.release()

    assert a.current_slot() is None, "index outlived the slot it names"


def test_current_slot_is_none_when_unheld(tmp_path, monkeypatch):
    """A caller that holds nothing must get None, so `claude_cli` falls back to mkdtemp
    rather than silently sharing `slot_0` with a real holder."""
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "slots"))
    assert make_governor(2, "unheld").current_slot() is None

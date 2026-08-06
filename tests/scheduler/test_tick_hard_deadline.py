"""The tick hard deadline must leave a receipt before it force-exits the daemon.

WHY THIS FILE EXISTS (measured 2026-08-06 on the live estate)
-------------------------------------------------------------
`store/scheduler/launchd.err.log` holds 18 `TICK HARD DEADLINE` lines, and
`store/scheduler/ticks.jsonl` + `alerts.jsonl` hold **zero** rows mentioning
`tick_hard_deadline`. That reads as "the receipt is broken". It is not — it is history:

    deadline values ever printed : 3x (1800s), 15x (2700s)   -- and never 4500s or 10800s
    batch values ever printed    : 18x batch=20              -- config is batch_size 15 today
    last such line               : line 3591 of 10483        -- 6,892 lines since, none

`51382cf` (2026-07-02 19:54) shipped `_force_exit_hung_tick` as a bare `os._exit(2)` with no
bookkeeping at all, on a 2700s deadline. `267e193` (2026-07-02 23:56) added the bookkeeping and
moved the deadline to 4500s; `711cab8` (2026-07-31) moved it to 10800s. Every one of the 18 lines
carries a pre-`267e193` constant, so every one of them was printed by code that could not have
written a receipt.

The consequence is the thing this file fixes: **the bookkeeping path has never once executed in
production**, and until now it had no test either — a force-exit that is supposed to explain
itself, unproven in both directions. `grep -rn "_force_exit_hung_tick" tests/` returned nothing.
"""
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

from prospector.scheduler import run_scheduled as rs


def _cfg(store_dir) -> types.SimpleNamespace:
    # `store_dir` — NOT `store.dir`. `run_scheduled._store_dir` reads the flat attribute and
    # falls back to the RELATIVE literal "store", so a cfg missing it writes into whatever
    # `store/` sits under the cwd — the live store, under pytest. (An earlier version of this
    # comment blamed 110 epoch-stamped rows on that fallback; re-measured, they are daemon ticks
    # under a bad clock — see prospector/scheduler/paths.py.) The real Config carries an absolute path
    # (`load_config('config.yaml').store_dir` -> /Users/.../prospector/store), so production is
    # cwd-independent; a test that gets this wrong silently tests production instead of tmp_path.
    return types.SimpleNamespace(store_dir=str(store_dir))


def _run_force_exit_in_child(cfg, tick: dict) -> int:
    """Call the real force-exit in a forked child, because it ends with `os._exit(2)`.

    Monkeypatching `os._exit` away would test a different function: the whole question is whether
    the receipt lands *before* an unconditional process kill, so the kill has to be real.
    """
    pid = os.fork()
    if pid == 0:  # pragma: no cover — the child never returns to pytest
        try:
            rs._force_exit_hung_tick(15, cfg, tick)
        finally:
            os._exit(99)  # only reachable if the function forgot to exit
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


@pytest.fixture()
def store(tmp_path):
    (tmp_path / "scheduler").mkdir(parents=True)
    return tmp_path


def test_the_force_exit_writes_a_tick_row_and_an_alert_before_it_kills_the_daemon(store):
    tick = {"ts": "2026-08-06T00:00:00+00:00", "allowed": True, "dry_run": False,
            "result": None, "error": None}

    assert _run_force_exit_in_child(_cfg(store), tick) == 2, (
        "exit 2 is the contract with launchd KeepAlive: the daemon must die so a clean one "
        "relaunches. 99 means the function returned without exiting."
    )

    rows = [json.loads(l) for l in (store / "scheduler" / "ticks.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert "tick_hard_deadline" in rows[0]["error"], (
        "without this row a repeating deadline breach is indistinguishable from a daemon that "
        "never ran — proven live 2026-07-02 (4h of relaunch loops, zero tick rows)"
    )
    assert str(rs._TICK_HARD_DEADLINE_S) in rows[0]["error"]
    assert "batch=15" in rows[0]["error"]

    alerts = [json.loads(l)
              for l in (store / "scheduler" / "alerts.jsonl").read_text().splitlines()]
    assert [a["severity"] for a in alerts] == ["critical"], (
        "a force-exit is not a warning; it is the daemon killing itself"
    )
    assert "tick_hard_deadline" in alerts[0]["message"]


def test_the_receipt_goes_to_the_configured_store_not_the_cwd(store, tmp_path, monkeypatch):
    """Pins the trap that polluted the live store: the receipt must follow `store_dir`."""
    elsewhere = tmp_path / "cwd"
    (elsewhere / "store" / "scheduler").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)

    tick = {"ts": "2026-08-06T00:00:00+00:00", "allowed": True, "dry_run": False,
            "result": None, "error": None}
    assert _run_force_exit_in_child(_cfg(store), tick) == 2

    assert (store / "scheduler" / "ticks.jsonl").exists()
    assert not (elsewhere / "store" / "scheduler" / "ticks.jsonl").exists(), (
        "a receipt written relative to the cwd lands in whichever checkout happens to be current"
    )


def test_bookkeeping_failure_still_force_exits(store, monkeypatch):
    """A broken sink must not turn a hung daemon into a hung daemon that also never dies."""
    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(rs, "_append_tick", boom)
    tick = {"ts": "2026-08-06T00:00:00+00:00", "allowed": True, "dry_run": False,
            "result": None, "error": None}
    assert _run_force_exit_in_child(_cfg(store), tick) == 2


def test_a_deadline_breach_with_no_cfg_still_exits(store):
    """The timer is armed with cfg+tick today, but the parameters are optional — pin the floor."""
    assert _run_force_exit_in_child(None, None) == 2


def test_the_timer_is_armed_with_the_cfg_and_tick_it_needs_for_the_receipt(monkeypatch, store):
    """The receipt is only possible if `run_tick` passes cfg and tick into the Timer.

    `51382cf` armed it as `args=(batch_size,)`. The bookkeeping added in `267e193` is dead code
    unless the call site hands it the two objects it writes, and nothing else asserts that.
    """
    armed: dict = {}

    class _FakeTimer:
        def __init__(self, interval, fn, args=()):
            armed["interval"] = interval
            armed["fn"] = fn
            armed["args"] = args
            self.daemon = False

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(rs.threading, "Timer", _FakeTimer)
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda *a, **k: None)

    cfg = _cfg(store)
    cfg.spend = types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0,
                                      daily_subscription_cap_usd=0.0)
    cfg.schedule = {"batch_size": 15}

    tick = rs.run_tick(cfg, generate_fn=lambda _c, _b: {"dossiers": 1, "passes": 0,
                                                       "defers": 0, "provisional": 0})

    assert armed["fn"] is rs._force_exit_hung_tick
    assert armed["interval"] == rs._TICK_HARD_DEADLINE_S
    assert len(armed["args"]) == 3, "batch_size alone leaves the receipt unwritable"
    assert armed["args"][1] is cfg
    assert armed["args"][2] is tick

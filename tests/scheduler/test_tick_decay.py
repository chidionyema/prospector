"""The decay sweep must actually run inside a tick.

THIS FILE IS THE ANTI-REGRESSION FOR AN UNWIRED RAIL. `decay.py::run_decay_loop` was fully
implemented and fully tested and had ZERO production callers — its only importer was
`tests/sim/test_decay.py`. A green suite could not see that, because the tests WERE the callers.
So these tests assert the wiring (does a tick call it?) rather than the loop's own logic.

`resume_deferred` was the identical bug six weeks earlier. Two occurrences make it a class.
"""
from __future__ import annotations

import types

import prospector.run as prun
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 3}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
    )


def test_a_tick_actually_runs_the_decay_sweep(tmp_path, monkeypatch):
    """The wiring test. If this fails, `reverify_due_at` is a write-only field again."""
    seen = {}
    monkeypatch.setattr(prun, "run_decay_sweep",
                        lambda cfg, *, limit=None: seen.update(limit=limit) or
                        {"total_due": 7, "revetted": 2, "delisted": 1})

    tick = rs.run_tick(_cfg(tmp_path, decay_per_tick=2),
                       generate_fn=lambda c, n: {"dossiers": n})

    assert seen == {"limit": 2}, "the tick did not call the decay sweep"
    assert tick["result"]["decayed"]["revetted"] == 2


def test_the_default_is_not_zero(tmp_path, monkeypatch):
    """Shipping the rail switched off reproduces the exact bug it was written to fix, so the
    default must be a positive number and this test is the fence on that decision."""
    seen = {}
    monkeypatch.setattr(prun, "run_decay_sweep",
                        lambda cfg, *, limit=None: seen.update(limit=limit) or {})

    rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: {"dossiers": n})   # no decay_per_tick

    assert seen.get("limit"), "decay_per_tick defaulted to 0/None — the rail ships disabled"
    assert rs._DECAY_PER_TICK_DEFAULT > 0


def test_decay_can_be_switched_off(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(prun, "run_decay_sweep",
                        lambda cfg, *, limit=None: called.append(limit))

    tick = rs.run_tick(_cfg(tmp_path, decay_per_tick=0),
                       generate_fn=lambda c, n: {"dossiers": n})

    assert called == []
    assert "decayed" not in tick["result"]


def test_a_failing_decay_sweep_does_not_take_down_the_tick(tmp_path, monkeypatch):
    """Maintenance must never be able to stop generation. The tick records the error and goes on."""
    def boom(cfg, *, limit=None):
        raise RuntimeError("moat is on fire")

    monkeypatch.setattr(prun, "run_decay_sweep", boom)

    tick = rs.run_tick(_cfg(tmp_path, decay_per_tick=2),
                       generate_fn=lambda c, n: {"dossiers": n})

    assert tick["result"]["dossiers"] == 3, "a decay failure must not lose the generation result"
    assert "moat is on fire" in tick["result"]["decayed"]["error"]


def test_bad_decay_per_tick_config_falls_back_to_the_default(tmp_path):
    assert rs._decay_per_tick(_cfg(tmp_path, decay_per_tick="banana")) == rs._DECAY_PER_TICK_DEFAULT
    assert rs._decay_per_tick(_cfg(tmp_path, decay_per_tick=-5)) == 0

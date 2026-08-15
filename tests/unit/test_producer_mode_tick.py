"""The daemon can be the PRODUCER half of the split — and saying so must not page the founder.

WHAT THIS PINS

1. `schedule.producer_mode` is OFF by default, and off means the tick is BYTE-IDENTICAL to the
   one that has always run: the drain runs, `run_signal` is called with `vet=True, publish=True`.
   A flag that changes behaviour when unset is a migration, not a flag.
2. ON makes the daemon a pure producer: no drain pass, `vet=False`, `publish=False`. Both halves
   move together — leaving the drain on would put the tick back on the moat's clock, which is the
   entire thing the split exists to end (`run_scheduled.producer_mode`).
3. The tick summary says which kind of tick it was (`mode="producer"`, `queued=N`) and
   `alerts_for_tick` reads it. THIS IS THE LOAD-BEARING ONE. A producer parks every survivor as a
   DEFER row, so `defers == dossiers` on every healthy tick — the exact trigger of the CRITICAL
   "Moat outage: all N candidates DEFERRED" page, and `passes == 0` is the `zero_yield` WARNING.
   Un-taught, the alerter would page CRITICAL on EVERY producer tick, and a channel that always
   fires is a channel the founder stops reading — which costs the next real outage its alert.
4. Producer-awareness is NOT blanket silence: a producer that generated NOTHING still alerts, and
   a non-producer result with the same numbers still pages. The suppression is scoped to the two
   verdict-shaped checks a producer cannot possibly satisfy.
"""
from __future__ import annotations

import types

import pytest

from prospector.scheduler import alerts as alerts_mod
from prospector.scheduler import run_scheduled


def _cfg(**schedule):
    sched = {"resume_per_tick": 3}
    sched.update(schedule)
    return types.SimpleNamespace(schedule=sched)


def _stub_tick(monkeypatch, dossiers=()):
    """Capture what the tick asks of the drain and of `run_signal`, running neither."""
    seen: dict = {"drained": 0, "kwargs": {}}

    def fake_drain(_cfg, n):
        seen["drained"] += 1
        seen["drain_n"] = n
        return 0

    def fake_run_signal(_text, **kwargs):
        seen["kwargs"] = kwargs
        return list(dossiers)

    monkeypatch.setattr(run_scheduled, "_drain_pass", fake_drain)
    monkeypatch.setattr("prospector.run.run_signal", fake_run_signal)
    monkeypatch.setattr("prospector.run._resolve_lanes", lambda *a, **k: None)
    return seen


def _dossier(decision="defer", provisional=False):
    return types.SimpleNamespace(
        decision=types.SimpleNamespace(value=decision), provisional=provisional)


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

def test_producer_mode_is_off_by_default_and_reads_the_config():
    assert run_scheduled.producer_mode(types.SimpleNamespace(schedule={})) is False
    assert run_scheduled.producer_mode(_cfg(producer_mode=True)) is True
    # Garbage must not silently become a producer — `bool("no")` is True, so the reader is
    # pinned on the string form an operator would actually type into YAML by mistake.
    assert run_scheduled.producer_mode(_cfg(producer_mode=0)) is False


def test_the_default_tick_is_unchanged(monkeypatch):
    """The flag is a no-op until it is set. Without this, the split's blast radius is every
    tick, not the ticks that opted in."""
    seen = _stub_tick(monkeypatch, [_dossier("pass")])

    out = run_scheduled._default_generate(_cfg(), 15)

    assert seen["drained"] == 1, "the classic tick still drains at its head"
    assert seen["kwargs"].get("vet") is not False, "and still vets"
    assert seen["kwargs"].get("publish") is True, "and still publishes"
    assert "mode" not in out, "a classic tick must not claim to be a producer"


def test_producer_mode_generates_and_queues_but_does_not_vet_publish_or_drain(monkeypatch):
    seen = _stub_tick(monkeypatch, [_dossier(), _dossier()])

    out = run_scheduled._default_generate(_cfg(producer_mode=True), 15)

    assert seen["drained"] == 0, (
        "a producer must not drain — the consumer owns the queue, and draining here would put "
        "the tick back on the moat's clock")
    assert seen["kwargs"].get("vet") is False
    assert seen["kwargs"].get("publish") is False
    assert out.get("mode") == "producer"
    assert out.get("queued") == 2, "a producer's success metric is rows handed to the queue"
    assert "resumed" not in out, "no drain pass ran, so there is no resumed count to report"


# ---------------------------------------------------------------------------
# The alert the split would otherwise fire on every tick
# ---------------------------------------------------------------------------

def _tick(result):
    return {"allowed": True, "ts": "2026-08-15T00:00:00+00:00", "result": result}


def test_the_same_numbers_page_CRITICAL_when_the_tick_is_not_a_producer():
    """The control. This is what a producer tick's result looks like to the un-taught alerter,
    and it proves the suppression below is doing real work rather than asserting a no-op."""
    fired = alerts_mod.alerts_for_tick(
        _tick({"dossiers": 12, "passes": 0, "defers": 12, "provisional": 0}))

    assert [a["key"] for a in fired] == ["moat_deferred"]
    assert fired[0]["severity"] == alerts_mod.CRITICAL


def test_a_healthy_producer_tick_is_silent():
    """All-DEFER and zero-PASS are a producer's NORMAL output, not an outage."""
    fired = alerts_mod.alerts_for_tick(
        _tick({"dossiers": 12, "passes": 0, "defers": 12, "provisional": 0,
               "mode": "producer", "queued": 12}))

    assert fired == [], f"a working producer must not page; got {[a['key'] for a in fired]}"


def test_a_producer_that_generated_nothing_still_alerts():
    """Producer-awareness is scoped, not blanket. 'Generated nothing' is the ONE failure this
    half can have, and it is the failure the barren-streak alert was built for."""
    fired = alerts_mod.alerts_for_tick(
        _tick({"dossiers": 0, "passes": 0, "defers": 0, "provisional": 0,
               "mode": "producer", "queued": 0}))

    assert [a["key"] for a in fired] == ["barren_generation"]


def test_a_producer_barren_STREAK_still_escalates_to_critical():
    fired = alerts_mod.alerts_for_tick(
        _tick({"dossiers": 0, "passes": 0, "defers": 0, "provisional": 0,
               "mode": "producer", "queued": 0}),
        consecutive_barren=3)

    assert [a["key"] for a in fired] == ["barren_streak"]
    assert fired[0]["severity"] == alerts_mod.CRITICAL


def test_a_producer_tick_that_FAILED_still_pages():
    """The mode branch sits below the error and moat-blind gates on purpose: a crash is a crash
    whichever half crashed."""
    tick = _tick({"dossiers": 0, "mode": "producer"})
    tick["error"] = "boom"

    assert [a["key"] for a in alerts_mod.alerts_for_tick(tick)] == ["tick_error"]


@pytest.mark.parametrize("mode", ["", "consumer", None, "PRODUCER "])
def test_only_the_exact_producer_marker_suppresses(mode):
    """A typo'd or absent marker must fail SAFE — towards the page, never towards silence."""
    fired = alerts_mod.alerts_for_tick(
        _tick({"dossiers": 12, "passes": 0, "defers": 12, "provisional": 0, "mode": mode}))

    assert [a["key"] for a in fired] == ["moat_deferred"]

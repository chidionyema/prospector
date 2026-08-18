"""A drain-only tick must be supervised by the same two backstops a generating tick gets.

THE HOLE THIS CLOSES (found live 2026-08-06, minutes after the backlog brake was deployed and
while it was engaged on a 343-row backlog). The brake's whole purpose is that when generation is
suppressed, the drain-only branch becomes the daemon's ENTIRE workload — it runs `resume_deferred`,
which is network- and LLM-bound, for ~82 min a pass. That branch had neither backstop:

  * the in-process guard `threading.Timer(_TICK_HARD_DEADLINE_S, _force_exit_hung_tick)` was armed
    AFTER the suppressed branch had already `return`ed, so no deadline ever covered the drain;
  * `_write_heartbeat(phase="draining")` wrote a phase that `_liveness` had no branch for — it
    matched neither `generating`, `sleeping`, nor `evaluating|idle`, so it fell through to
    `return True, "alive"` and the external watchdog reported a hung drain as healthy, forever;
  * `_drain_pass` catches `except Exception` by design (a drain failure must not cost the tick its
    batch), so the work can never fail loudly either.

Net: a wedged re-vet hung the daemon indefinitely, invisible to both rails. That is precisely the
2026-07-01 incident — a trickled LLM response body defeats per-recv socket timeouts, the daemon sat
wedged 34+ min, and the alert-only watchdog watched it dead for 8.5h — re-opened on a new path.

The second half of this file guards the naive fix. A drain-only pass is long BY DESIGN (15 rows at
the measured ~5.5 min/candidate ≈ 82 min), so giving `draining` the 45-min budget that
`evaluating`/`idle` use would SIGKILL a perfectly healthy drain on every brake tick — the exact
failure this module already carries 47 logged instances of.
"""
from __future__ import annotations

import time
import types

import pytest

from prospector.scheduler import run_scheduled as rs


@pytest.fixture(autouse=True)
def _default_tick_deadline(monkeypatch):
    """Judge every budget below against the SHIPPED deadline, not the one this machine sets.

    `rs._TICK_HARD_DEADLINE_S` is read from `PROSPECTOR_TICK_DEADLINE_S` at import time, for
    tuning a manual run without a code change. Every budget in `_liveness` is derived from it,
    so a machine that sets it moves the numbers these tests assert.

    Measured 2026-08-18 on main: the CI runners have it set to 60, so `stall_min` was 11 minutes
    and `test_a_long_but_healthy_drain_is_not_killed` failed with "82 min ... (deadline 1 min
    should have force-exited it)" -- a green suite on every laptop and a red main, for a reason
    in neither the diff nor the repository. The tests that WANT a different deadline still
    monkeypatch it themselves; this only stops the ambient one leaking in.
    """
    monkeypatch.delenv("PROSPECTOR_TICK_DEADLINE_S", raising=False)
    monkeypatch.setattr(rs, "_TICK_HARD_DEADLINE_S", rs._TICK_DEADLINE_DEFAULT_S)


def _cfg(tmp_path, **schedule):
    # recover_per_tick 0 because these tests time the drain against a sub-second deadline. Pack
    # recovery spawns a python child that opens the real catalogue; on a machine that has one it
    # ran for longer than the deadline, and on a machine that does not it failed and reported the
    # error into the tick. Either way the thing under test here -- was the deadline cancelled --
    # was measured against the wrong clock.
    sched = {"batch_size": 15, "backlog_cap": 100, "recover_per_tick": 0}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
        operator=["claude_cli"],
    )


@pytest.fixture
def brake_engaged(monkeypatch):
    """Force the drain-only branch: backlog over the cap, and a moat that can rule.

    `_moat_blind_reason` is stubbed rather than left to the real health store because the moat
    preflight outranks the brake (it has its own test); these tests are about SUPERVISION of the
    branch, and a leaked dead mark from another test would silently skip it and pass vacuously.
    """
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 343)
    monkeypatch.setattr(rs, "_moat_blind_reason", lambda cfg: None)


@pytest.fixture
def force_exits(monkeypatch):
    """Capture the force-exit instead of calling `os._exit(2)` and killing the test runner."""
    fired = []
    monkeypatch.setattr(rs, "_force_exit_hung_tick",
                        lambda *a, **kw: fired.append({"args": a, "kwargs": kw}))
    return fired


def _never_generate(cfg, n):  # pragma: no cover — a suppressed tick must never reach this
    raise AssertionError("generation ran during a suppressed tick")


# ------------------------------------------------------- the deadline actually covers the drain

def test_a_wedged_drain_hits_the_hard_deadline_and_force_exits(tmp_path, brake_engaged,
                                                               force_exits, monkeypatch):
    """The load-bearing test. Not "was a Timer constructed" — a real deadline against a drain that
    genuinely does not return. Before the fix this asserted nothing because the Timer covering the
    drain did not exist; the branch returned before it was armed."""
    monkeypatch.setattr(rs, "_TICK_HARD_DEADLINE_S", 0.1)
    monkeypatch.setattr(rs, "_drain_pass", lambda cfg, n: time.sleep(0.6))

    rs.run_tick(_cfg(tmp_path), generate_fn=_never_generate)

    assert force_exits, (
        "a drain that never returns must force-exit so launchd KeepAlive relaunches a clean "
        "daemon — otherwise it hangs forever, and `_liveness` calls it alive")
    assert force_exits[0]["kwargs"]["phase"] == "the drain", (
        "a breach on a batch_size=0 tick that reports 'during generation' sends the next reader "
        "to the wrong half of the daemon")


def test_a_healthy_drain_cancels_its_deadline(tmp_path, brake_engaged, force_exits, monkeypatch):
    """The mirror image: the guard must not fire on a drain that finished. A deadline that is
    never cancelled force-exits the daemon mid-sleep on the NEXT cadence."""
    monkeypatch.setattr(rs, "_TICK_HARD_DEADLINE_S", 0.3)
    monkeypatch.setattr(rs, "_drain_pass", lambda cfg, n: {"resumed": 15})

    rs.run_tick(_cfg(tmp_path), generate_fn=_never_generate)
    time.sleep(0.5)  # past the deadline the tick armed

    assert force_exits == [], "the deadline must be cancelled the instant the drain returns"


def test_the_deadline_is_cancelled_even_if_the_drain_raises(tmp_path, brake_engaged,
                                                            force_exits, monkeypatch):
    """`_drain_pass` swallows exceptions today, but the cancel must not DEPEND on that: if it ever
    raises, a leaked timer force-exits a healthy daemon some minutes later, and the tick row would
    blame a deadline breach that never happened. Hence `finally`, not a trailing call."""
    monkeypatch.setattr(rs, "_TICK_HARD_DEADLINE_S", 0.3)

    def _boom(cfg, n):
        raise RuntimeError("drain blew up")

    monkeypatch.setattr(rs, "_drain_pass", _boom)

    with pytest.raises(RuntimeError):
        rs.run_tick(_cfg(tmp_path), generate_fn=_never_generate)
    time.sleep(0.5)

    assert force_exits == [], "a raising drain must still cancel its deadline"


def test_generation_keeps_naming_generation(tmp_path, monkeypatch):
    """`_force_exit_hung_tick` gained a `phase` kwarg; the generation call site passes positional
    args and must keep its original wording, or every existing runbook and log grep for
    'exceeded during generation' goes silent."""
    tick = {}
    rec = []
    monkeypatch.setattr(rs, "_append_tick", lambda cfg, t: rec.append(t))
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda cfg, t: None)
    monkeypatch.setattr(rs.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit):
        rs._force_exit_hung_tick(15, _cfg(tmp_path), tick)

    assert "during generation (batch=15)" in tick["error"]


# --------------------------------------------- the watchdog can SEE a drain, without killing one

def _beat(tmp_path, *, phase, age_min):
    import json
    from datetime import datetime, timedelta, timezone
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    (d / "heartbeat.json").write_text(json.dumps({"ts": ts.isoformat(), "pid": 4242, "phase": phase}))
    return _cfg(tmp_path)


def test_a_wedged_drain_is_reported_dead_not_alive(tmp_path):
    """Before the fix `draining` matched no branch in `_liveness` and fell through to the trailing
    `return True` — a hung drain was reported healthy for as long as it hung. This is the active
    form of the "looked alive for 15h" guard."""
    cfg = _beat(tmp_path, phase="draining", age_min=rs._TICK_HARD_DEADLINE_S / 60 + 30)

    ok, reason = rs._liveness(cfg)

    assert ok is False, "a drain older than the hard deadline is wedged, not working"
    assert "draining" in reason


def test_a_long_but_healthy_drain_is_not_killed(tmp_path):
    """THE ANTI-REGRESSION. 15 rows at the measured ~5.5 min/candidate is ~82 min of legitimate
    work. Reusing the 45-min `evaluating`/`idle` budget here would SIGKILL a healthy drain on
    every single brake tick, and — because the brake stays engaged until the backlog clears —
    would mean the backlog could never clear at all."""
    ok, reason = rs._liveness(_beat(tmp_path, phase="draining", age_min=82))

    assert ok is True, f"82 min is a normal 15-row drain pass, not a stall: {reason}"


def test_draining_shares_the_deadline_derived_budget(tmp_path, monkeypatch):
    """Derived from `_TICK_HARD_DEADLINE_S`, never restated as a literal, so the in-process
    deadline always force-exits FIRST and the watchdog stays the backstop. A hardcoded number here
    silently strands that coupling when the deadline moves — proven once already, when the old
    hardcoded 55 assumed the old 45-min deadline."""
    monkeypatch.setattr(rs, "_TICK_HARD_DEADLINE_S", 600)  # 10 min

    assert rs._liveness(_beat(tmp_path, phase="draining", age_min=5))[0] is True
    assert rs._liveness(_beat(tmp_path, phase="draining", age_min=25))[0] is False


def test_every_heartbeat_phase_has_a_liveness_budget(tmp_path):
    """The bug was a phase with no branch, which is silent: it reports healthy. Any phase added
    later must fail here rather than re-open the hole."""
    stale = rs._TICK_HARD_DEADLINE_S / 60 + 120
    uncovered = [p for p in ("generating", "draining", "evaluating", "idle", "sleeping")
                 if rs._liveness(_beat(tmp_path, phase=p, age_min=stale))[0] is True]

    assert uncovered == [], f"phases fall through to 'alive' when stale: {uncovered}"

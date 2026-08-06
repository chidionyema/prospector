"""A spend ceiling that stops the drain does not save the money, it defers it.

`spend.daily_subscription_cap_usd` existed and was unarmable. `guard.evaluate()` returns
`can_run=False` for it, and `run_tick` (`run_scheduled.py:562-565`) returns on `not can_run`
BEFORE reaching the drain — so arming it freezes the backlog at whatever it is when the cap
trips. That is the 0efe40e defect ("stopping the treadmill also stopped the only thing paying
it down") reintroduced through the money rail instead of through PAUSE, and it is not a
theoretical cost: every unresolved row still owes a full re-vet, so the hard stop defers the
spend AND holds the rows hostage while it does so.

The measured consequence of it being unarmable: `daily_subscription_cap_usd` sat at 0.0 while
2026-08-06 recorded $438.68 of subscription-equivalent burn against no ceiling of any kind —
the metered `daily_cap_usd: 20.0` governs 4.4% of consumption and structurally cannot see the
CLI leg.

`daily_subscription_soft_cap_usd` is the ceiling that can actually be armed: stop DIGGING,
keep RESOLVING. The tests below pin BOTH halves — that it suppresses generation, and that the
drain survives it. The second is the whole point; a soft cap that stopped the drain would just
be the hard cap with a different name.
"""
from __future__ import annotations

import types

import pytest

from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.guard import GuardDecision


def _cfg(tmp_path, *, soft=0.0, hard=0.0, **schedule):
    sched = {"batch_size": 15}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0,
                                    daily_subscription_cap_usd=hard,
                                    daily_subscription_soft_cap_usd=soft),
        schedule=sched,
        operator=["claude_cli"],
    )


def _decision(*, can_run=True, subscription=0.0, hard=0.0):
    return GuardDecision(
        can_run=can_run,
        reason="ok",
        today_spend_usd=0.0,
        daily_cap_usd=20.0,
        paused=False,
        today_subscription_usd=subscription,
        daily_subscription_cap_usd=hard,
        day="2026-08-06",
    )


# --------------------------------------------------------------------------- the brake itself

def test_off_by_default(tmp_path):
    """0.0 must change nothing on an existing deployment, matching backlog_cap's precedent."""
    assert rs._generation_suppressed(_cfg(tmp_path), _decision(subscription=9_999.0)) == ""


def test_below_the_cap_generates_normally(tmp_path):
    cfg = _cfg(tmp_path, soft=150.0)
    assert rs._generation_suppressed(cfg, _decision(subscription=149.99)) == ""


def test_at_the_cap_suppresses_generation(tmp_path):
    cfg = _cfg(tmp_path, soft=150.0)
    reason = rs._generation_suppressed(cfg, _decision(subscription=150.0))
    assert "subscription soft cap" in reason
    assert "150.00" in reason
    assert "drains" in reason  # the reason must SAY the drain continues


def test_reason_names_the_spend_not_the_queue(tmp_path):
    """When both brakes would fire, the operator must be told it was the money."""
    cfg = _cfg(tmp_path, soft=150.0, backlog_cap=1)
    reason = rs._generation_suppressed(cfg, _decision(subscription=500.0))
    assert "subscription soft cap" in reason
    assert "backlog brake" not in reason


def test_backlog_brake_still_fires_when_spend_is_fine(tmp_path, monkeypatch):
    """No over-reach: adding the money brake must not shadow the queue brake."""
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 400)
    cfg = _cfg(tmp_path, soft=150.0, backlog_cap=100)
    reason = rs._generation_suppressed(cfg, _decision(subscription=1.0))
    assert "backlog brake" in reason


def test_no_decision_is_a_no_op(tmp_path):
    """Callers that cannot supply a guard decision must not be broken by the new trigger."""
    cfg = _cfg(tmp_path, soft=1.0)
    assert rs._generation_suppressed(cfg) == ""


def test_garbage_cap_disables_the_brake_and_does_not_crash(tmp_path):
    """A brake that crashes the daemon is worse than no brake (same rule as backlog_cap)."""
    cfg = _cfg(tmp_path, soft="not-a-number")
    assert rs._generation_suppressed(cfg, _decision(subscription=9_999.0)) == ""


def test_soft_above_hard_warns_that_the_drain_will_not_survive(tmp_path, caplog):
    """A contradiction the operator must hear about: the hard wall halts the whole tick
    first, so the soft brake never fires and the drain stops with it."""
    cfg = _cfg(tmp_path, soft=200.0, hard=100.0)
    with caplog.at_level("WARNING"):
        rs._generation_suppressed(cfg, _decision(subscription=250.0, hard=100.0))
    assert any("drain will NOT keep running" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------- the half that actually matters: drain

@pytest.fixture
def hermetic(monkeypatch):
    """Silence the tick's side effects so only the branch under test is observable."""
    monkeypatch.setattr(rs, "_write_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_append_tick", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_moat_blind_reason", lambda cfg: "")
    drained: list = []
    monkeypatch.setattr(rs, "_drain_pass", lambda cfg, n: drained.append(n) or {"resumed": n})
    return drained


def _guard_returning(monkeypatch, decision):
    monkeypatch.setattr(rs, "guard_from_config",
                        lambda cfg: types.SimpleNamespace(evaluate=lambda: decision))


def test_soft_cap_tick_still_drains(tmp_path, monkeypatch, hermetic):
    """THE POINT. Generation is suppressed and the drain still runs, so the backlog goes DOWN
    while the brake is engaged and the brake releases itself at the day roll-over."""
    cfg = _cfg(tmp_path, soft=150.0)
    _guard_returning(monkeypatch, _decision(subscription=500.0))
    generated: list = []
    tick = rs.run_tick(cfg, generate_fn=lambda c, n: generated.append(n) or {})

    assert generated == []                         # dug nothing
    assert hermetic and hermetic[0] > 0            # drained something
    assert tick["batch_size"] == 0
    assert "subscription soft cap" in tick["generation_suppressed"]


def test_hard_cap_tick_drains_NOTHING(tmp_path, monkeypatch, hermetic):
    """The trap this change routes around, pinned so it cannot be mistaken for the soft path.
    `can_run=False` returns before the drain — the backlog freezes."""
    cfg = _cfg(tmp_path, hard=100.0)
    _guard_returning(monkeypatch, _decision(
        can_run=False, subscription=500.0, hard=100.0))
    generated: list = []
    tick = rs.run_tick(cfg, generate_fn=lambda c, n: generated.append(n) or {})

    assert generated == []
    assert hermetic == []                          # <- the defect, documented
    assert tick["allowed"] is False


def test_under_both_caps_generates(tmp_path, monkeypatch, hermetic):
    """Guard rail: the new brake must not suppress a healthy tick."""
    cfg = _cfg(tmp_path, soft=150.0)
    _guard_returning(monkeypatch, _decision(subscription=10.0))
    generated: list = []
    rs.run_tick(cfg, generate_fn=lambda c, n: generated.append(n) or {})
    assert generated == [15]

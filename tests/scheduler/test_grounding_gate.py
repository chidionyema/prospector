"""Generation is gated on a RATE (is retrieval working now), not on a STOCK (queue depth).

THE DEFECT THIS REPLACES. `schedule.backlog_cap` suppressed generation whenever the count of
drainable rows crossed a threshold. Measured against the live store on 2026-08-06:

  * 154 of 154 drainable rows carry `retrieval_degraded=1` — every one of them.
  * The flag is not tautological: of 1,483 non-tombstoned rows only 180 (12%) are degraded.
    1,220 KILLs and 83 PASSes were generated and fully ruled with `degraded=0`.
  * So generation VOLUME does not mint backlog; failed RETRIEVAL does.
  * The backlog is therefore burst-shaped, not treadmill-shaped: 95 rows created 2026-06-24,
    44 on 2026-08-06, 0-4 on every other day across six weeks.
  * Consequence, live: remove the 2026-06-24 burst and the backlog is 59, under the cap of 100.
    A six-week-old outage was why the daemon generated nothing that afternoon — and draining
    those old rows does nothing at all to make new retrieval succeed.

A stock brake has unbounded memory; a rate gate has none. These tests pin BOTH halves of the
replacement: that a degraded stack suppresses generation, and that a healthy one does not — plus
the property that made the old brake dangerous, that recovery needs no state file and no reset.
"""
from __future__ import annotations

import time
import types

import pytest

from prospector.scheduler import run_scheduled as rs
from prospector.scheduler.guard import GuardDecision

#: The real probe, bound at import — before tests/conftest.py's autouse `_no_live_grounding_probe`
#: swaps the module attribute for a healthy stub. The four tests in "the probe itself" below are
#: the only ones that must run the genuine implementation.
_REAL_PROBE = rs._probe_grounding_once


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 15}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0,
                                    daily_subscription_cap_usd=0.0,
                                    daily_subscription_soft_cap_usd=0.0),
        schedule=sched,
        operator=["claude_cli"],
    )


def _decision(*, subscription=0.0):
    return GuardDecision(
        can_run=True, reason="ok", today_spend_usd=0.0, daily_cap_usd=20.0, paused=False,
        today_subscription_usd=subscription, daily_subscription_cap_usd=0.0, day="2026-08-06",
    )


def _probe_returning(monkeypatch, kind, exc=None):
    monkeypatch.setattr(rs, "_probe_grounding_once", lambda cfg, timeout_s: (kind, exc))


# ------------------------------------------------------------------ the gate's three outcomes

def test_healthy_grounding_generates(tmp_path, monkeypatch):
    _probe_returning(monkeypatch, "")
    assert rs._grounding_degraded_reason(_cfg(tmp_path)) == ""


def test_failed_probe_suppresses_generation(tmp_path, monkeypatch):
    _probe_returning(monkeypatch, "error", RuntimeError("ddg: connection reset"))
    reason = rs._grounding_degraded_reason(_cfg(tmp_path))
    assert "grounding degraded" in reason
    assert "connection reset" in reason      # the operator gets the cause, not just the verdict
    assert "drains" in reason                # and is told the drain survives it


def test_timed_out_probe_fails_CLOSED_on_generation(tmp_path, monkeypatch):
    """A probe we could not complete is not evidence that retrieval works. Generating into a
    stack we cannot confirm is exactly what mints DEFER rows."""
    _probe_returning(monkeypatch, "timeout")
    reason = rs._grounding_degraded_reason(_cfg(tmp_path))
    assert "grounding degraded" in reason
    assert str(rs._TICK_PROBE_TIMEOUT_S) in reason


def test_gate_is_switchable_off(tmp_path, monkeypatch):
    """An escape hatch for an operator whose retrieval probe is itself the broken thing."""
    _probe_returning(monkeypatch, "error", RuntimeError("boom"))
    cfg = _cfg(tmp_path, gate_generation_on_grounding=False)
    assert rs._grounding_degraded_reason(cfg) == ""


def test_gate_is_ON_by_default(tmp_path, monkeypatch):
    """Unlike backlog_cap and the soft cap, this one defaults ON — it is the causal condition,
    so the safe default is to not dig while the stack is down."""
    _probe_returning(monkeypatch, "error", RuntimeError("boom"))
    assert "grounding degraded" in rs._grounding_degraded_reason(_cfg(tmp_path))


def test_recovery_needs_no_state_file_and_no_reset(tmp_path, monkeypatch):
    """THE POINT OF CHOOSING A RATE. The same cfg, same store, same everything: the only input
    that changed is whether retrieval answers. The old stock brake stayed engaged for six weeks
    after the outage that filled it had ended."""
    cfg = _cfg(tmp_path)
    _probe_returning(monkeypatch, "error", RuntimeError("outage"))
    assert rs._grounding_degraded_reason(cfg) != ""
    _probe_returning(monkeypatch, "")
    assert rs._grounding_degraded_reason(cfg) == ""


# ------------------------------------------------------------- ordering inside _generation_suppressed

def test_cause_is_reported_before_symptom(tmp_path, monkeypatch):
    """When retrieval is down AND the queue is deep, the operator must be told retrieval is
    down. The queue is downstream of exactly that; 'backlog brake' would send them to drain
    old rows, which cannot fix new retrieval."""
    _probe_returning(monkeypatch, "error", RuntimeError("ddg down"))
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 400)
    reason = rs._generation_suppressed(_cfg(tmp_path, backlog_cap=100), _decision())
    assert "grounding degraded" in reason
    assert "backlog brake" not in reason


def test_money_still_outranks_grounding(tmp_path, monkeypatch):
    """No over-reach: the spend brake is a liability rail and stays first."""
    _probe_returning(monkeypatch, "error", RuntimeError("ddg down"))
    cfg = _cfg(tmp_path)
    cfg.spend.daily_subscription_soft_cap_usd = 150.0
    reason = rs._generation_suppressed(cfg, _decision(subscription=500.0))
    assert "subscription soft cap" in reason


def test_pause_file_still_outranks_grounding(tmp_path, monkeypatch):
    _probe_returning(monkeypatch, "error", RuntimeError("ddg down"))
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / rs._GENERATION_PAUSE_FILENAME).write_text("")
    assert "generation paused" in rs._generation_suppressed(_cfg(tmp_path), _decision())


def test_backlog_cap_zero_never_suppresses(tmp_path, monkeypatch):
    """What config.yaml now ships. A backlog of 10,000 must not stop generation when the only
    thing that puts rows there is working."""
    _probe_returning(monkeypatch, "")
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 10_000)
    assert rs._generation_suppressed(_cfg(tmp_path, backlog_cap=0), _decision()) == ""


def test_backlog_cap_is_retained_not_deleted(tmp_path, monkeypatch):
    """Kept as a floor-of-last-resort against unbounded queue growth: an operator who sets it
    still gets it, and it still fires on a HEALTHY stack."""
    _probe_returning(monkeypatch, "")
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 400)
    reason = rs._generation_suppressed(_cfg(tmp_path, backlog_cap=100), _decision())
    assert "backlog brake" in reason


# ------------------------------------------------------------------------ the probe itself

class _FakeProvider:
    def __init__(self, *, boom=None, sleep=0.0):
        self.boom, self.sleep, self.calls = boom, sleep, []

    def search(self, q, k=1):
        self.calls.append(q)
        if self.sleep:
            time.sleep(self.sleep)
        if self.boom:
            raise self.boom
        return []


def test_probe_reports_healthy(tmp_path, monkeypatch):
    import prospector.retrieval as R
    provider = _FakeProvider()
    monkeypatch.setattr(R, "make_provider", lambda cfg: provider)
    assert _REAL_PROBE(_cfg(tmp_path), 5) == ("", None)
    assert provider.calls, "the probe must actually issue a search"


def test_probe_carries_the_exception_to_the_caller(tmp_path, monkeypatch):
    import prospector.retrieval as R
    boom = RuntimeError("no provider configured")
    monkeypatch.setattr(R, "make_provider", lambda cfg: _FakeProvider(boom=boom))
    kind, exc = _REAL_PROBE(_cfg(tmp_path), 5)
    assert kind == "error" and exc is boom


def test_probe_is_hard_bounded(tmp_path, monkeypatch):
    """An unbounded probe on the tick path would wedge the daemon loop the way it once wedged
    startup. The bound is wall-clock, not cooperative — a provider that never returns must not
    hold the tick."""
    import prospector.retrieval as R
    monkeypatch.setattr(R, "make_provider", lambda cfg: _FakeProvider(sleep=30))
    started = time.monotonic()
    kind, exc = _REAL_PROBE(_cfg(tmp_path), 0.2)
    assert (kind, exc) == ("timeout", None)
    assert time.monotonic() - started < 5, "the probe joined for longer than its timeout"


def test_probe_unwraps_the_disk_cache(tmp_path, monkeypatch):
    """LOAD-BEARING, not an optimisation. The probe query is fixed, so after the first-ever run
    it is a cache hit — and a cache hit 'passes' a completely dead retrieval stack (observed
    2026-07-28: audit row provider=cache, cache_hit=true)."""
    import prospector.retrieval as R
    inner = _FakeProvider()
    cache = object.__new__(R.DiskCache)          # avoids binding to the constructor signature
    cache.inner = inner
    cache.search = lambda q, k=1: pytest.fail("probe hit the cache instead of the live provider")
    monkeypatch.setattr(R, "make_provider", lambda cfg: cache)
    assert _REAL_PROBE(_cfg(tmp_path), 5) == ("", None)
    assert inner.calls, "the probe must reach the live provider behind the cache"


# ---------------------------------------------------------------- the tick: suppressed, still drains

@pytest.fixture
def hermetic(monkeypatch):
    monkeypatch.setattr(rs, "_write_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_append_tick", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda *a, **k: None)
    monkeypatch.setattr(rs, "_moat_blind_reason", lambda cfg: "")
    monkeypatch.setattr(rs, "guard_from_config",
                        lambda cfg: types.SimpleNamespace(evaluate=lambda: _decision()))
    drained: list = []
    monkeypatch.setattr(rs, "_drain_pass", lambda cfg, n: drained.append(n) or {"resumed": n})
    return drained


def test_degraded_tick_drains_and_does_not_generate(tmp_path, monkeypatch, hermetic):
    """The half that matters. Suppressing generation must never suppress the cure — that was
    0efe40e's defect, and it is the reason this is a `generation_suppressed` reason rather than
    an early return from run_tick."""
    _probe_returning(monkeypatch, "error", RuntimeError("ddg down"))
    generated: list = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: generated.append(n) or {})

    assert generated == []
    assert hermetic and hermetic[0] > 0
    assert tick["batch_size"] == 0
    assert "grounding degraded" in tick["generation_suppressed"]


def test_healthy_tick_generates_with_a_deep_backlog(tmp_path, monkeypatch, hermetic):
    """The live regression this change fixes: 154 drainable rows and a healthy stack must
    produce candidates. Before it, the daemon generated nothing all afternoon."""
    _probe_returning(monkeypatch, "")
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 154)
    generated: list = []
    tick = rs.run_tick(_cfg(tmp_path, backlog_cap=0),
                       generate_fn=lambda c, n: generated.append(n) or {})

    assert generated == [15]
    assert tick.get("generation_suppressed", "") == ""

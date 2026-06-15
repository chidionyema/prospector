"""CircuitBreaker state machine (Part 9 resilience).

The breaker is what stops one transient timeout from permanently dead-listing a
grounding provider for the whole run (the bug behind the 13-DEFER cascade). These
tests drive every transition deterministically via an injected clock — no sleeps."""
from __future__ import annotations

from prospector.breaker import CircuitBreaker, CLOSED, OPEN, HALF_OPEN


class FakeClock:
    """Manually-advanced monotonic clock so cooldown transitions are deterministic."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def _br(threshold=3, cooldown=60.0):
    clk = FakeClock()
    return CircuitBreaker("p", failure_threshold=threshold,
                          cooldown_s=cooldown, clock=clk), clk


def test_starts_closed_and_allows():
    br, _ = _br()
    assert br.state == CLOSED
    assert br.allow() is True


def test_transient_failures_below_threshold_stay_closed():
    """A single (or sub-threshold) transient failure must NOT retire the provider —
    this is the exact bug: one slow search dead-listing gemini for the whole run."""
    br, _ = _br(threshold=3)
    br.record_failure()
    br.record_failure()
    assert br.state == CLOSED
    assert br.allow() is True


def test_opens_after_consecutive_threshold():
    br, _ = _br(threshold=3)
    br.record_failure()
    br.record_failure()
    br.record_failure()
    assert br.state == OPEN
    assert br.allow() is False


def test_success_resets_consecutive_counter():
    br, _ = _br(threshold=3)
    br.record_failure()
    br.record_failure()
    br.record_success()           # streak broken
    br.record_failure()
    assert br.state == CLOSED     # not 3-in-a-row anymore


def test_exhaustion_trips_immediately():
    """A quota/credit wall (hard=True) opens on the FIRST failure — retrying a spent
    quota just burns budget."""
    br, _ = _br(threshold=3)
    br.record_failure(hard=True)
    assert br.state == OPEN
    assert br.allow() is False


def test_half_open_after_cooldown_admits_one_probe():
    br, clk = _br(threshold=1, cooldown=60.0)
    br.record_failure(hard=True)
    assert br.allow() is False            # still in cooldown
    clk.advance(60.0)
    assert br.state == HALF_OPEN          # cooldown elapsed
    assert br.allow() is True             # first probe admitted
    assert br.allow() is False            # only ONE probe in flight


def test_half_open_probe_success_closes():
    br, clk = _br(threshold=1, cooldown=30.0)
    br.record_failure(hard=True)
    clk.advance(30.0)
    assert br.allow() is True             # probe
    br.record_success()
    assert br.state == CLOSED
    assert br.allow() is True             # fully back in service


def test_half_open_probe_failure_reopens_and_restarts_cooldown():
    br, clk = _br(threshold=1, cooldown=30.0)
    br.record_failure(hard=True)
    clk.advance(30.0)
    assert br.allow() is True             # probe
    br.record_failure()                   # probe failed
    assert br.state == OPEN
    assert br.allow() is False            # cooldown restarted, not immediately half-open
    clk.advance(30.0)
    assert br.allow() is True             # recovers again after fresh cooldown

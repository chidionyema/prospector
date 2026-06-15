"""Per-provider circuit breaker (Part 9 resilience).

The failover chain used to RETIRE a provider permanently on its first failure.
That conflates a transient hiccup (one timeout under contention) with a dead
provider: a single slow gemini search would retire gemini for the whole run, so
every later search piled onto the slower claude fallback, saturated it, and the
run cascaded into DEFER. The breaker fixes that by separating two things the old
code merged:

  - a TRANSIENT failure (timeout / bad exit / queue saturation) only counts toward
    a threshold; the provider stays in service until it fails `failure_threshold`
    times IN A ROW.
  - an EXHAUSTION (quota/credit wall) trips the breaker immediately — retrying a
    spent quota just wastes the budget.

An open breaker is not permanent: after `cooldown_s` it half-opens and lets ONE
probe through. Probe succeeds → closed (provider is back). Probe fails → open
again, cooldown restarts. So a provider that recovers mid-run is picked back up
instead of being dead-listed for the duration.

The clock is injected (`clock=time.monotonic` by default) so tests drive state
transitions deterministically without sleeping.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

CLOSED = "closed"      # healthy — requests flow
OPEN = "open"          # tripped — requests skipped until cooldown elapses
HALF_OPEN = "half_open"  # cooldown elapsed — one probe in flight to test recovery


class CircuitBreaker:
    """Thread-safe breaker for a single provider.

    Usage from the failover loop:
        if not br.allow():        # skip an OPEN provider still in cooldown
            continue
        try:
            result = provider()   # the actual call
            br.record_success()
        except ProviderExhausted:
            br.record_failure(hard=True)
        except Exception:
            br.record_failure()
    """

    def __init__(self, name: str, *, failure_threshold: int = 3,
                 cooldown_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        """Current state, lazily transitioning OPEN→HALF_OPEN once cooldown elapses.
        Read-only callers (tests, telemetry) see the same view allow() would act on."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        # caller holds the lock
        if (self._state == OPEN and self._opened_at is not None
                and self._clock() - self._opened_at >= self.cooldown_s):
            self._state = HALF_OPEN
            self._probe_in_flight = False

    def allow(self) -> bool:
        """Return True if a request may proceed right now.

        CLOSED → always. OPEN → only after cooldown (then transitions to HALF_OPEN
        and admits exactly ONE probe). HALF_OPEN → admits the single probe, then
        refuses further requests until the probe resolves via record_*()."""
        with self._lock:
            self._maybe_half_open()
            if self._state == CLOSED:
                return True
            if self._state == HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        """A call succeeded — fully reset to CLOSED."""
        with self._lock:
            self._state = CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self, *, hard: bool = False) -> None:
        """A call failed. `hard=True` (quota/credit exhaustion) trips immediately;
        otherwise the breaker opens only once failures reach `failure_threshold`
        in a row. A failure during a half-open probe re-opens and restarts cooldown."""
        with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures += 1
            was_half_open = self._state == HALF_OPEN
            if hard or was_half_open or self._consecutive_failures >= self.failure_threshold:
                self._state = OPEN
                self._opened_at = self._clock()

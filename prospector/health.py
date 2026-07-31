"""Persistent, time-aware provider health (Part 9 resilience, cross-run).

The circuit breaker (breaker.py) is in-RUN memory on a monotonic clock — it forgets
everything when the process exits, so every fresh run re-discovers that a free-tier
brain is out of quota by paying its full timeout again. But an exhaustion error tells
us exactly WHEN the quota resets ("reset after 6h54m27s" / retryDelayMs). This module
captures that on a WALL clock and persists it to store/, so:

  - the moment one call learns a provider is dead-until-T, every later call THIS run
    skips it for free (no re-probe), and
  - the NEXT run (minutes or hours later) reads the file at startup and skips it from
    call #1 until T passes — then transparently retries it (self-healing).

It is deliberately separate from the breaker: the breaker handles in-run transient
flakiness (monotonic, testable, no I/O); this handles persistent quota windows (wall
clock, shared across processes via a JSON file). A provider is skipped if EITHER says
so. When every provider is skipped the caller raises ProviderExhaustedError exactly as
before -> DEFER, never a false kill. The moat is untouched: this only reorders/【skips】
which grounding/brain is asked, never what counts as evidence or a verdict.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from .telemetry import logger

HEALTH_PATH = Path(__file__).resolve().parent.parent / "store" / "provider_health.json"

# The non-critical chain (generation, prescreen, scoring on DeepSeek→MiniMax→Gemini-flash)
# records its quota exhaustion to a SEPARATE file. This is the founder-fence invariant:
# a non-critical provider going dead must never blind the moat (and vice versa). Same
# class, different file — the two health states are physically independent.
NONCRITICAL_HEALTH_PATH = (
    Path(__file__).resolve().parent.parent / "store" / "provider_health_noncritical.json"
)

# Clamp a parsed reset window to something sane: never shorter than this (a real quota
# window is minutes+), never longer than a day (so a mis-parse can't blacklist forever).
_MIN_DEAD_S = 60.0
_MAX_DEAD_S = 24 * 3600.0

# When a provider is clearly exhausted but the error carries no parseable reset time,
# assume a 1h window — long enough to stop wasteful re-probing, short enough that a
# real recovery is picked up soon (is_dead self-expires, then the provider is retried).
DEFAULT_EXHAUSTION_S = 3600.0


class ProviderHealth:
    """Reads/writes per-provider 'dead until <epoch>' marks to a JSON file.

    Thread-safe and process-safe-enough for our single-host, supervised batches: each
    mutation rewrites the small file atomically (tmp + replace). `now` is injectable
    for tests."""

    def __init__(self, path: Path = HEALTH_PATH, *, clock=time.time):
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, ValueError):
            return {}
        except Exception as e:  # corrupt/unreadable -> treat as no knowledge, never crash a run
            logger.warning(f"provider_health unreadable, ignoring: {e}", extra={"path": str(self._path)})
            return {}

    def _save(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            tmp.replace(self._path)
        except Exception as e:  # health is an optimisation; persistence failure must not break a run
            logger.warning(f"provider_health unwritable, continuing: {e}", extra={"path": str(self._path)})

    def dead_until(self, name: str) -> Optional[float]:
        """Epoch until which `name` is known-exhausted, or None if not / expired."""
        entry = self._load().get(name)
        if not entry:
            return None
        until = float(entry.get("dead_until", 0) or 0)
        return until if until > self._clock() else None

    def is_dead(self, name: str) -> bool:
        return self.dead_until(name) is not None

    def mark_exhausted(self, name: str, dead_for_s: float) -> None:
        """Record that `name` is out of quota for `dead_for_s` seconds from now."""
        dead_for_s = max(_MIN_DEAD_S, min(_MAX_DEAD_S, float(dead_for_s)))
        until = self._clock() + dead_for_s
        with self._lock:
            data = self._load()
            data[name] = {"dead_until": until, "marked_at": self._clock(),
                          "dead_for_s": round(dead_for_s, 1)}
            self._save(data)
        logger.warning(
            f"Provider {name!r} marked exhausted for ~{int(dead_for_s)}s (persisted)",
            extra={"provider": name, "dead_for_s": round(dead_for_s, 1)})

    def clear(self, name: str) -> None:
        """A successful call proves `name` is alive — drop any stale dead mark."""
        with self._lock:
            data = self._load()
            if name in data:
                del data[name]
                self._save(data)


_DEFAULT: Optional[ProviderHealth] = None
_DEFAULT_LOCK = threading.Lock()
_NONCRITICAL: Optional[ProviderHealth] = None
_NONCRITICAL_LOCK = threading.Lock()


def get_health() -> ProviderHealth:
    """Process-wide shared instance so the (moat) operator chain and the grounding chain
    consult/record the SAME persisted health file."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = ProviderHealth()
    return _DEFAULT


def get_noncritical_health() -> ProviderHealth:
    """Process-wide health instance for the non-critical chain, backed by a SEPARATE
    file (provider_health_noncritical.json). Founder-fence: non-critical exhaustion
    must never pollute the moat's health, so the moat is never falsely blinded."""
    global _NONCRITICAL
    if _NONCRITICAL is None:
        with _NONCRITICAL_LOCK:
            if _NONCRITICAL is None:
                _NONCRITICAL = ProviderHealth(path=NONCRITICAL_HEALTH_PATH)
    return _NONCRITICAL

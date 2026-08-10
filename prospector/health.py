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

import fcntl
import json
import os
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

# BACKPRESSURE (HTTP 429 / "overloaded") is not a spent allowance — the provider is alive and
# asking for a shorter queue. It gets the floor, not the hour. Measured 2026-08-06: nine
# 3600s marks on a `claude_cli` that answered a direct probe OK; see errors.py.
TRANSIENT_EXHAUSTION_S = _MIN_DEAD_S  # 60s

# HALF-OPEN PROBE. The docstring above has always promised self-healing ("then transparently
# retries it"), but the only retry was at the FAR END of the window: `is_dead` returned True
# for the whole hour and `FallbackOperator._raw` skips a dead brain without probing it. So a
# provider that recovered after 90 seconds stayed benched for 3600, and every ruling in that
# window fell to the emergency tail and came back `provisional` — owing a full re-vet for an
# answer the moat could have given.
#
# Now: after _PROBE_AFTER_S, exactly ONE caller is let through to try the provider for real.
# Success clears the mark (operator.py already calls `clear` on success); failure re-marks with
# a doubled window (strike count), so a genuinely dead brain still backs off geometrically
# instead of being hammered. The claim is written to the shared JSON file under the lock, so
# two threads — or the daemon and a drain in separate processes — cannot both take the probe.
_PROBE_AFTER_S = 120.0
_PROBE_BACKOFF_MULT = 2.0
_MAX_STRIKES = 6  # 120s -> 2h of probe spacing; the dead_until window still caps skipping


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
        """Epoch until which `name` is known-exhausted, or None if not / expired.

        This is the RAW mark, deliberately unaffected by the half-open probe: readers that
        REPORT state (the state probe, the control centre, alerts) want the truth, not the
        one call that is being let through to measure it."""
        entry = self._load().get(name)
        if not entry:
            return None
        until = float(entry.get("dead_until", 0) or 0)
        return until if until > self._clock() else None

    def is_dead(self, name: str) -> bool:
        """True if `name` should be SKIPPED on this call.

        False either because the window expired, OR because this caller just claimed the
        half-open probe slot — the circuit is half-open and this one call finds out for real.
        A False therefore means "try it", not "known healthy"; the caller learns the truth by
        making the call, and `clear()` on success is what actually ends the outage."""
        if self.dead_until(name) is None:
            return False
        return not self._claim_probe(name)

    def _probe_spacing(self, strikes: int) -> float:
        """Seconds between half-open probes after `strikes` consecutive failures."""
        return _PROBE_AFTER_S * (_PROBE_BACKOFF_MULT ** (min(max(strikes, 1), _MAX_STRIKES) - 1))

    def _claim_probe(self, name: str) -> bool:
        """Atomically take the single probe slot for `name`, or return False.

        The claim is written to the shared file under an OS-level lock, so concurrent vet
        workers — and a daemon and a `vet --resume` drain running as SEPARATE PROCESSES
        against the same store/ — cannot each decide they are the prober and stampede a
        struggling brain. That stampede is not hypothetical: the 2026-08-06 flap happened
        with exactly those two processes competing for the same subscription CLI.

        Until 2026-08-10 the only guard here was `self._lock`, a `threading.Lock()` — real
        within one process, but each process constructs its OWN `ProviderHealth` with its OWN
        lock object, so two processes reading the same not-yet-claimed `probe_at` could both
        pass the check and both return True for the same slot: reproduced directly, two
        independent `ProviderHealth` instances pointed at one file both claimed the sole probe.
        `fcntl.flock` on a dedicated lock file is a real mutex machine-wide — kernel-released on
        close or process death, the same mechanism `cli_governor.py`/`jsonl_atomic.py` already
        use on this host — so the load-decide-write sequence below is now atomic across
        processes, not just across threads. `self._lock` stays too: it keeps the fast path
        (two threads in one process) from taking a syscall for something Python can already
        serialize."""
        now = self._clock()
        lock_path = self._path.with_suffix(".lock")
        with self._lock:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                data = self._load()
                entry = data.get(name)
                if not entry:
                    return False
                if float(entry.get("probe_at", 0) or 0) > now:
                    return False
                entry["probe_at"] = now + self._probe_spacing(int(entry.get("strikes", 1) or 1))
                entry["probes"] = int(entry.get("probes", 0) or 0) + 1
                data[name] = entry
                self._save(data)
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(lock_fd)
        logger.info(
            f"Provider {name!r} half-open: letting one call through to re-probe",
            extra={"provider": name})
        return True

    def mark_exhausted(self, name: str, dead_for_s: float, *, error: str = "") -> None:
        """Record that `name` is out of quota (or backpressured) for `dead_for_s` seconds.

        Consecutive marks — a half-open probe that failed again — escalate `strikes`, which
        widens the spacing between probes. Any successful call calls `clear()` and resets it,
        so an isolated blip never accumulates into a long back-off.

        `error` is persisted and logged in the MESSAGE, not only in `extra`. It used to live
        in `extra` alone, which this project's formatter drops: on 2026-08-06 the log showed
        nine `marked exhausted for ~3600s` lines and not one of them said why, so the shape of
        the failure had to be inferred from timing. A mark that cannot be diagnosed from the
        log is a mark that gets mis-tuned."""
        dead_for_s = max(_MIN_DEAD_S, min(_MAX_DEAD_S, float(dead_for_s)))
        now = self._clock()
        with self._lock:
            data = self._load()
            prev = data.get(name) or {}
            # A mark that is still live means this is a REPEAT failure (the probe went out and
            # came back dead), not a fresh incident.
            repeat = float(prev.get("dead_until", 0) or 0) > now
            strikes = (int(prev.get("strikes", 0) or 0) + 1) if repeat else 1
            # The first re-probe is deliberately much sooner than the window: the window is a
            # guess parsed from (or defaulted for) an error string; the probe is a measurement.
            probe_in = min(self._probe_spacing(strikes), dead_for_s)
            data[name] = {"dead_until": now + dead_for_s, "marked_at": now,
                          "dead_for_s": round(dead_for_s, 1), "strikes": strikes,
                          "probe_at": now + probe_in,
                          "last_error": (error or "")[:200]}
            self._save(data)
        logger.warning(
            f"Provider {name!r} marked exhausted for ~{int(dead_for_s)}s "
            f"(strike {strikes}, re-probe in ~{int(probe_in)}s): {(error or 'no error text')[:160]}",
            extra={"provider": name, "dead_for_s": round(dead_for_s, 1),
                   "strikes": strikes, "error": (error or "")[:200]})

    def clear(self, name: str) -> None:
        """A successful call proves `name` is alive — drop any stale dead mark.

        Logged at WARNING when it ends a live outage, so recovery is as visible in the log as
        the failure was. A self-healing system that heals silently is indistinguishable from
        one that never broke, and that is how nine marks in 70 minutes went unnoticed."""
        with self._lock:
            data = self._load()
            entry = data.pop(name, None)
            if entry is None:
                return
            self._save(data)
        if float(entry.get("dead_until", 0) or 0) > self._clock():
            logger.warning(
                f"Provider {name!r} RECOVERED on a live call after "
                f"{int(entry.get('strikes', 1) or 1)} strike(s); dead mark cleared",
                extra={"provider": name, "strikes": entry.get("strikes")})


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


def moat_brains(cfg) -> list[str]:
    """The trusted verdict brains on this config's chain, in order."""
    from prospector.operator import MOAT_PRIMARY
    ops = getattr(cfg, "operator", None) or []
    ops = [ops] if isinstance(ops, str) else list(ops)
    return [str(o) for o in ops if str(o) in MOAT_PRIMARY]


def verdict_brains(cfg) -> list[str]:
    """EVERY brain on this config's verdict chain, trusted or provisional, in order.

    The counterpart to `moat_brains`. Added 2026-08-08 with the minimax re-add: with a
    provisional tail configured, "can any brain rule at all?" and "can a brain rule
    FINALLY?" stopped being the same question, and answering the first with the second is
    what would have made the fallback inert (see `moat_blind_reason(trusted_only=...)`).
    """
    ops = getattr(cfg, "operator", None) or []
    ops = [ops] if isinstance(ops, str) else list(ops)
    return [str(o) for o in ops]


def moat_blind_reason(cfg, *, trusted_only: bool = True) -> str:
    """Why no moat work can run right now, or "" if some brain can still rule.

    ONE implementation, two callers: the scheduler's generation preflight
    (`scheduler/run_scheduled.py::_moat_blind_reason`) and the drain's preflight
    (`run.py::_cmd_resume`). It lives here rather than in either caller because
    `run_scheduled` imports `run` — so `run` can never import `run_scheduled` back — and
    because a duplicated moat classifier is the same defect shape as the exhaustion
    classifier that `errors.looks_exhausted` exists to prevent: two copies drift, and the
    one that drifts is the one nobody is watching.

    `trusted_only` is the one thing the two callers do NOT share, and the asymmetry is the
    point (founder directive 2026-08-08, re-adding minimax to `operator:`):

      * **The drain passes True** (the default, so a new caller is safe by construction).
        Re-vetting a `provisional` row on a provisional brain re-stamps it `provisional` —
        the row does not move, the money is spent, and the drain's own CLI load is what
        keeps the trusted brain benched. A drain that cannot finalise must not run.
      * **Generation passes False.** Generating while a provisional tail is alive produces
        rows that CAN be ruled — provisionally now, finally on re-vet — which is exactly the
        trade the founder accepted. Had generation stayed trusted-only, the re-add would have
        been inert: the daemon would still skip every tick whenever claude_cli was dead,
        which is the only time the fallback exists to matter.

    Uses `dead_until()`, NOT `is_dead()`: `is_dead` can CLAIM the half-open probe slot, and
    a bookkeeping check must never consume the one call whose job is to measure recovery.
    This reads the mark; it does not spend the probe.

    Returns "" when no brain of the requested kind is configured at all — that is a config
    error, and it should surface downstream as a loud failure rather than a quiet skip.
    """
    import time as _time
    brains = moat_brains(cfg) if trusted_only else verdict_brains(cfg)
    if not brains:
        return ""
    health = get_health()
    marks = {b: health.dead_until(b) for b in brains}
    if any(v is None for v in marks.values()):
        return ""
    now = _time.time()
    detail = ", ".join(f"{b} for {int(v - now)}s more" for b, v in sorted(marks.items()))
    # Wording is deliberately NOT derived from `trusted_only`: on a trusted-only chain both
    # callers inspect the identical brain set, and their reasons must then be byte-identical so
    # a drift between them is visible. The brains are named in `detail` either way.
    return f"moat blind: every brain it can rule with is marked dead ({detail})"

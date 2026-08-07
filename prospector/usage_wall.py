"""Prospector's half of the estate-wide Claude usage-wall marker.

THE PROBLEM
Otto's coordinator and Prospector's scheduler are two always-on daemons drawing on ONE
Claude subscription. When the CLI answers `Claude AI usage limit reached|<epoch>`, the
process that saw it knows exactly when capacity returns — and the other one does not. It
keeps spawning `claude -p` into a wall it cannot see, and every attempt costs a process
spawn, a task slot and a CLI-usage entry. Measured 2026-08-07 23:44 on this machine: Otto
recorded a wall lifting at 23:59:05 (`observed_by: otto-coordinator`) while Prospector's
daemon (pid 11795) had no code path that could read it.

THE CONTRACT IS THE FILE, NOT A SHARED LIBRARY
The marker is plain JSON at ~/.hermes/state/claude_usage_limit.json, written atomically by
either side:

    {"reset_at": <epoch>, "observed_at": <epoch>, "observed_by": "<name>",
     "source": "<first 200 chars of the text that proved it>"}

This module reads and writes that path DIRECTLY and imports nothing from ~/.hermes. The two
codebases stay decoupled: the marker is a fact about the shared account, not a library
either side depends on. `~/.hermes/scripts/claude_usage_limit.py` states the same contract
from the other side, and the schema here must match it field for field.

FAIL OPEN, NEVER CLOSED
An absent, malformed, unreadable or implausible marker means "no known wall" and never
raises. Failing closed on a corrupt file would stall the daemon indefinitely on a bug in
its own reader — strictly worse than the hammering this exists to stop. In particular a
`reset_at` further out than `_MAX_WALL_S` is treated as corrupt rather than clamped: the
epoch field has appeared as milliseconds before, and a millisecond value read as seconds
lands in the year 58000. Clamping such a value would still bench the daemon for the full
maximum; ignoring it costs one wasted call instead.

RECIPROCITY IS THE POINT
Reading alone fixes half the problem. `observe()` exists so that when PROSPECTOR is the
process that hits the wall first, Otto stops hammering too.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Optional

from .errors import limit_window_seconds

logger = logging.getLogger(__name__)

#: Overridable for tests ONLY. Production always reads the estate-wide path — a per-process
#: marker would recreate the split-brain this module exists to close.
_MARKER_ENV = "PROSPECTOR_USAGE_WALL_MARKER"
_DEFAULT_MARKER = "~/.hermes/state/claude_usage_limit.json"

#: The CLI emits an epoch after a pipe: "Claude AI usage limit reached|1786123456".
_PIPE_EPOCH_RE = re.compile(r"usage limit reached\s*\|\s*(\d{9,13})", re.I)

#: The same trigger vocabulary as the Hermes side. Both processes must agree on what counts
#: as a wall, or one will record markers the other would not and vice versa.
_WALL_MARKERS = ("usage limit", "session limit", "rate limit", "quota exceeded")

#: A real wall carries no timestamp sometimes. Break the hot retry loop without inventing an
#: outage of our own: 15 min, matching CLAUDE_LIMIT_COOLDOWN_S on the Hermes side.
DEFAULT_COOLDOWN_S = float(os.environ.get("CLAUDE_LIMIT_COOLDOWN_S", "900"))

#: No wall may exceed a week — the longest real limit this account meets. Beyond this the
#: value is a bug, not a wall. Matches `errors._MAX_WINDOW_S`.
_MAX_WALL_S = 7 * 24 * 3600.0


def marker_path() -> str:
    return os.path.expanduser(os.environ.get(_MARKER_ENV, _DEFAULT_MARKER))


def parse_reset_epoch(text: str) -> Optional[float]:
    """The absolute reset epoch carried by the CLI's own `|<epoch>` suffix, or None.

    Accepts seconds and milliseconds: the field has appeared as both, and a millisecond
    value read as seconds blocks effectively forever.
    """
    m = _PIPE_EPOCH_RE.search(text or "")
    if not m:
        return None
    val = float(m.group(1))
    if val > 1e11:              # milliseconds
        val /= 1000.0
    return val


def looks_like_wall(text: str) -> bool:
    low = (text or "").lower()
    return any(t in low for t in _WALL_MARKERS)


def read(now: Optional[float] = None) -> Optional[dict]:
    """The live marker as a dict, or None when absent, unreadable, expired or implausible."""
    ref = time.time() if now is None else now
    path = marker_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        reset = float(data.get("reset_at", 0))
    except (TypeError, ValueError):
        return None
    if reset <= ref:
        return None
    if reset > ref + _MAX_WALL_S:
        # Corrupt, not a wall. Fail OPEN and say so loudly — silently ignoring it would hide
        # a writer bug in the other codebase for as long as it kept happening.
        logger.warning(
            "Ignoring implausible usage-wall marker: reset_at is %.0fs away (max %.0fs); "
            "treating the account as available. path=%s observed_by=%s",
            reset - ref, _MAX_WALL_S, path, data.get("observed_by"))
        return None
    return data


def blocked_for(now: Optional[float] = None) -> float:
    """Seconds until the wall lifts, or 0.0 when there is no known wall."""
    ref = time.time() if now is None else now
    data = read(now=ref)
    return max(0.0, float(data["reset_at"]) - ref) if data else 0.0


def is_blocked(now: Optional[float] = None) -> bool:
    return blocked_for(now=now) > 0.0


def reason(now: Optional[float] = None) -> str:
    """A one-line cause for a tick log / dead mark, or "" when the account is available.

    Names the observer and the reset time because the operator's next question is always
    "which daemon saw this, and when do I get capacity back".
    """
    ref = time.time() if now is None else now
    data = read(now=ref)
    if not data:
        return ""
    reset = float(data["reset_at"])
    return (f"claude usage wall: capacity returns "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(reset))} "
            f"({(reset - ref) / 60:.1f} min), observed by {data.get('observed_by', '?')}")


def observe(text: str, observed_by: str = "prospector", now: Optional[float] = None,
            cooldown_s: Optional[float] = None) -> Optional[float]:
    """Record a usage wall proved by `text`. Returns the reset epoch, or None if `text` does
    not actually show a wall.

    Precedence for the reset time: the CLI's own `|<epoch>` suffix, then any reset window
    `errors.limit_window_seconds` can parse out of the message, then a short cooldown. The
    provider knows when its own quota returns; we are only ever guessing.

    Never raises for a reason the caller cares about — this runs on an error path, and a
    failure to record a wall must not replace the original error with a bookkeeping one.
    """
    ref = time.time() if now is None else now
    if not looks_like_wall(text):
        return None

    reset = parse_reset_epoch(text)
    if reset is None or reset <= ref:
        window = limit_window_seconds(text)
        reset = ref + (window if window and window > 0
                       else (DEFAULT_COOLDOWN_S if cooldown_s is None else cooldown_s))
    reset = min(reset, ref + _MAX_WALL_S)

    # A wall never gets SHORTER by being observed again — two daemons hitting it in the same
    # second must not race each other into an early resume.
    existing = read(now=ref)
    if existing and float(existing.get("reset_at", 0)) > reset:
        return float(existing["reset_at"])

    payload = {"reset_at": reset, "observed_at": ref, "observed_by": observed_by,
               "source": (text or "")[:200]}
    path = marker_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)   # atomic; a reader never sees a half-written marker
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        logger.warning("Could not record usage wall at %s: %s", path, e)
        return None
    logger.critical("Recorded claude usage wall until %s (%.1f min) — observed by %s",
                    time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(reset)),
                    (reset - ref) / 60, observed_by)
    return reset

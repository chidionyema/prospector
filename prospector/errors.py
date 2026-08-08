"""Shared error types for provider failover.

ProviderExhaustedError is the failover SIGNAL: a provider (LLM brain or grounding
search) reports it is out of credit/quota for the rest of this run. Fallback
wrappers catch it, retire that provider, and try the next one. It is deliberately
distinct from a generic transient failure (retried in place) and from a legitimate
empty result (real evidence of nothing — never a failover).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional


class ProviderExhaustedError(RuntimeError):
    """Raised when a provider is out of quota/credit and cannot serve this run.

    Carries the provider name so the fallback layer can log which brain/search
    backend retired and which one took over.

    `retry_after_s` is the bench window when the RAISER already knows it exactly, and it
    outranks every text-derived guess. The alternative — writing the reset into the message
    and re-parsing it downstream — was measured failing on 2026-08-08: the usage-wall preflight
    formatted a known 14-minute reset as "capacity returns 2026-08-08 22:37:45 (14.0 min)",
    `limit_window_seconds` returned None on that prose, and `claude_cli` took the 1h
    `DEFAULT_EXHAUSTION_S` instead. The moat sat benched for 46 minutes it had no reason to,
    every ruling in that window fell to the emergency tail and came back `provisional`, and
    nothing could publish. A number that is known must never be re-derived from prose.
    """

    def __init__(self, message: str, *, provider: str = "",
                 retry_after_s: Optional[float] = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.retry_after_s = retry_after_s


class FixtureMiss(RuntimeError):
    """Raised by FixtureProvider when no fixture entry matches the query.

    FallbackSearchProvider catches this and falls through to the next provider,
    so fixture gaps don't silently produce [] results that block live search.
    """


class GroundingInfrastructureError(RuntimeError):
    """ALL search providers are dead (402/401/429/auth). Not a content verdict —
    infrastructure collapse. The daemon must HALT, not defer, to stop burning LLM
    credits on candidates that can never be verified."""


class SearchProviderError(RuntimeError):
    """Raised by a search provider that RAN but failed at the infrastructure level —
    e.g. SearXNG returns HTTP 200 with zero results because every upstream engine timed
    out or was blocked. This is NOT a content verdict ("found nothing") and NOT a config
    skip (ProviderUnavailable): the provider is broken right now. FallbackSearchProvider
    lets this hit the generic exception path so it (a) fails over to the next provider and
    (b) counts against the breaker, retiring a persistently-dead provider after the
    threshold so the chain stops paying its latency on every check."""


class ProviderUnavailable(RuntimeError):
    """Raised by a search provider that is NOT CONFIGURED to run (e.g. its API key
    is missing), as opposed to one that ran and legitimately found nothing.

    This distinction is critical: a keyless provider returning [] is INDISTINGUISHABLE
    from a working provider finding zero passages, so the fallback would treat the skip
    as a successful empty result and short-circuit the chain — leaving the moat blind.
    FallbackSearchProvider catches this (like FixtureMiss) and falls through to the next
    provider WITHOUT counting it against the provider's breaker.
    """


# Exhaustion is not one thing, and the two shapes must NOT share a blackout window.
#
# PERMANENT — the account has no allowance left. Waiting a few seconds cannot help; only a
# quota reset or a billing action does. A long dead-window is correct here and saves real
# money: re-probing a broke account every 60s forever is the bug this list was written for.
#
# TRANSIENT — the provider is alive and applying backpressure (HTTP 429, "overloaded",
# "too many requests"). It wants a shorter queue, not a different brain.
#
# Treating the second as the first is what turned a slow-down into an outage. Measured
# 2026-08-06 on the live daemon: `claude_cli` was marked dead-for-3600s NINE times inside 70
# minutes (08:25, 09:06, 09:07:07 x2, 09:07:11 x2, 09:08, 09:09, 09:36) while a direct
# `env -u ANTHROPIC_API_KEY claude -p` probe answered OK on demand. Each failure took ~3s
# (09:06:21 -> 09:06:24) — the shape of backpressure, not of a spent quota. Every mark blinded
# the moat for an hour because `FallbackOperator._raw` skips a dead brain WITHOUT probing it,
# so the emergency tail ruled instead and all 15 verdicts in the 09:23 batch came back
# `provisional` — each one owing a full re-vet later for an answer the moat could have given.
_PERMANENT_MARKERS = (
    "quota_exhausted",
    "exhausted your capacity",
    "terminalquotaerror",
    "resource_exhausted",
    "insufficient_quota",
    "insufficient balance",
    "credit balance is too low",
    "payment required",
    "usage limit",
)
# The allowance-limit shape, as a regex rather than more literals. Proven 2026-08-06 against the
# tuple above, which held "usage limit" but NOT the words the Claude Code CLI actually emits:
#     "...,"api_error_status":429,"result":"You've hit your monthly spend limit · raise it at
#      claude.ai/settings/usage?from=cc_cli_limit_message"
# It says SPEND limit, not USAGE limit. So the real message classified `transient` (60s) purely
# on the incidental \b429\b, and the daemon re-probed a hard monthly cap every 60s — the live log
# shows strikes 2, 3, 4 escalating inside three seconds. Worse, the same message WITHOUT a 429
# scored NOT_EXHAUSTION at all, which is the dangerous half: a failure `looks_exhausted` misses
# never becomes ProviderExhaustedError, so verify.py takes its generic-exception path and the
# billing failure is recorded as an `unverifiable` check instead of deferring the candidate.
# "rate limit" is deliberately NOT matched here — it stays transient, in _TRANSIENT_MARKERS.
# A long window is cheap now: health.py's half-open probe re-tests at ~120s, so classifying an
# allowance limit PERMANENT costs at most one extra probe if the allowance is actually restored.
# 2026-08-06: `session limit` and `5-hour limit` were missing, and that is the DANGEROUS half
# described immediately above — not a missed hour of failover, but a limit that never becomes a
# ProviderExhaustedError at all, so verify.py takes its generic-exception path and the outage is
# recorded as an `unverifiable` check instead of deferring the candidate. Proven before the fix:
#     classify_exhaustion("5-hour limit reached; try again later") -> ""   (NOT_EXHAUSTION)
# `\d+-hour` is bounded to a leading digit run so "hour limit" alone (e.g. prose about rate
# limits per hour) still does not match.
_ALLOWANCE_LIMIT_RE = re.compile(
    r"\b(spend|usage|monthly|weekly|daily|hourly|session)\s+limit\b"
    r"|\b(?:[0-9]+|five)[-\s]?hour\s+limit\b")
_TRANSIENT_MARKERS = (
    "rate_limit",
    "rate limit",
    "too many requests",
    "overloaded_error",
    "overloaded",
    "server_busy",
)
# HTTP status codes must be matched on a WORD BOUNDARY, never as bare substrings. Proven
# 2026-08-06 against the previous list, which held "429" and "402" as plain `in` tests:
#     looks_exhausted("connection reset after 4291 bytes") -> True
#     looks_exhausted("req_id=a429f0 timeout")             -> True
#     looks_exhausted("Error: 4290 tokens")                -> True
# Any request id, byte count or token count containing those three digits bought an hour-long
# moat blackout. `\b429\b` matches "HTTP 429 Too Many Requests" and none of the three above.
_HTTP_TRANSIENT_RE = re.compile(r"\b(429|503|529)\b")
_HTTP_PERMANENT_RE = re.compile(r"\b402\b")
# "billing" was also a bare substring, so "billing address invalid" classified as exhaustion.
# It only means "out of allowance" next to a word that says so.
_BILLING_RE = re.compile(r"\bbilling\b[^.\n]{0,60}\b(limit|quota|credits?|plan|upgrade)\b")
# DELIBERATELY NOT HERE: 401 / "unauthorized". That is a bad or expired credential, not a spent
# allowance, and marking it exhausted would bury a config error under a silent hour-long
# failover — the opposite of what this list is for. It should fail loudly on every call.

PERMANENT = "permanent"
TRANSIENT = "transient"
NOT_EXHAUSTION = ""


def classify_exhaustion(text: str) -> str:
    """Classify an adapter's error text as PERMANENT, TRANSIENT or NOT_EXHAUSTION.

    PERMANENT wins ties: a message carrying both a 429 and "credit balance is too low" is a
    spent account being rate-limited on the way out, and the expensive mistake is to keep
    re-probing it. The caller turns this into a dead-window length (see health.py)."""
    t = (text or "").lower()
    if (any(m in t for m in _PERMANENT_MARKERS) or _HTTP_PERMANENT_RE.search(t)
            or _BILLING_RE.search(t) or _ALLOWANCE_LIMIT_RE.search(t)):
        return PERMANENT
    if any(m in t for m in _TRANSIENT_MARKERS) or _HTTP_TRANSIENT_RE.search(t):
        return TRANSIENT
    return NOT_EXHAUSTION


def cause_context(text: str, width: int = 140, limit: int = 3) -> str:
    """Every exhaustion marker found ANYWHERE in `text`, with surrounding context.

    Why this exists, and why it lives next to the markers rather than in an adapter.

    An adapter that must shorten a payload before logging it has to choose a slice, and every
    fixed slice is a bet about where the cause sits. `claude_cli.py` bet on the TAIL
    (`proc.stdout.strip()[-300:]`), which is right for prose — a CLI that dies printing an
    error prints it last — and a bet nonetheless under `--output-format json`, where the tail
    is trailing metadata and the cause is a `result` field somewhere in the middle.

    THIS IS A DEFENSIVE CHANGE, NOT A FIX FOR AN OBSERVED MISS. It is documented that way
    because the first write-up of it claimed the opposite and was wrong. Measured 2026-08-07
    on the actual payload that ended E3 run #6, recovered untruncated from
    `tools/experiments/e3_concurrency_knee_receipts.json`:

        detail length                     300      (the tail slice, exactly full)
        'monthly spend limit' sits        167 chars from the end
        classify_exhaustion(detail)  ->   'permanent'

    The bet PAID on that payload, with 133 characters of margin: the account's spend-limit
    message reached the classifier, `looks_exhausted` was True, and every call in the receipt
    is a `ProviderExhaustedError` — which `run_claude_cli` raises only on that branch. What
    this function removes is the margin, not a live defect: it is 133 characters of luck about
    how much metadata trails the `result` field, and no test anywhere pinned it.

    Scanning for the MARKER instead of guessing at an offset is shape-agnostic — prose, JSON,
    or a truncated fragment of either — and it reuses the single marker vocabulary that
    `classify_exhaustion` already rules on, so the two can never disagree about what counts as
    a cause. The payload in `tests/unit/test_errors_limits.py` that DOES defeat the tail slice
    is constructed, and is labelled there as constructed.
    """
    t = (text or "")
    low = t.lower()
    hits: list[str] = []
    seen: set[int] = set()
    for marker in (*_PERMANENT_MARKERS, *_TRANSIENT_MARKERS):
        i = low.find(marker)
        if i < 0:
            continue
        start = max(0, i - width // 2)
        # Collapse overlapping windows so three markers in one sentence do not print it thrice.
        if any(abs(start - s) < width // 2 for s in seen):
            continue
        seen.add(start)
        hits.append(t[start:start + width].strip())
        if len(hits) >= limit:
            break
    for rx in (_HTTP_PERMANENT_RE, _BILLING_RE, _ALLOWANCE_LIMIT_RE, _HTTP_TRANSIENT_RE):
        if len(hits) >= limit:
            break
        m = rx.search(low)
        if not m:
            continue
        start = max(0, m.start() - width // 2)
        if any(abs(start - s) < width // 2 for s in seen):
            continue
        seen.add(start)
        hits.append(t[start:start + width].strip())
    return " ⋯ ".join(hits)


def looks_exhausted(text: str) -> bool:
    """True if an error string indicates quota/credit exhaustion OR backpressure (-> failover).

    Unchanged contract for every existing caller: both shapes still fail over to the next
    brain and still raise ProviderExhaustedError. What changed is that the CALLER can now ask
    `classify_exhaustion` how long to stay away, instead of every failure costing an hour."""
    return classify_exhaustion(text) != NOT_EXHAUSTION


# Providers tell us WHEN the quota resets; we parse it to persist a precise dead-window
# instead of guessing. Two shapes seen in the wild:
#   retryDelayMs: 24846193.66814            (Gemini CLI structured error)
#   "...quota will reset after 6h54m27s"    (human string in the same payload)
_RETRY_MS = re.compile(r"retrydelayms[\"']?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_RESET_HMS = re.compile(r"reset(?:\s+\w+){0,3}?\s+after\s+([0-9hms\s]+)", re.I)
_HMS_PART = re.compile(r"([0-9]+)\s*([hms])", re.I)


def parse_reset_seconds(text: str, now: Optional["_dt.datetime"] = None) -> Optional[float]:
    """Seconds until a quota resets, parsed from an exhaustion error, or None.

    Prefers the machine-precise retryDelayMs; falls back to an 'Xh Ym Zs' phrase.
    Returns None when nothing parseable is present (caller picks a default window)."""
    t = text or ""
    m = _RETRY_MS.search(t)
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except ValueError:
            pass
    phrase = _RESET_HMS.search(t)
    if phrase:
        total = 0
        for value, unit in _HMS_PART.findall(phrase.group(1)):
            mult = {"h": 3600, "m": 60, "s": 1}[unit.lower()]
            total += int(value) * mult
        if total > 0:
            return float(total)
    # `now` is threaded through purely so callers and tests can pin the clock; every existing
    # caller passes nothing and gets the previous behaviour.
    return _parse_absolute_reset(t, now=now)


# --- Limit CLASSES: a 5-hour window is not a week is not a spent account -----------------------
#
# THE GAP THIS CLOSES (2026-08-06). Everything above parses only RELATIVE durations —
# `retryDelayMs` and "reset after 6h54m27s". A grep across `prospector/` for
# `5[- ]hour|five[- ]hour|weekly limit|resets? at|reset_at|session limit` returned ZERO matches,
# so Claude Code's limits — which are stated as an ABSOLUTE wall-clock reset — parsed to nothing
# and fell through to DEFAULT_EXHAUSTION_S (3600s). The daemon then re-probed a brain that was
# guaranteed dead once an hour for up to a WEEK: every probe a full-price failed call, every tick
# logged `moat_blind`. Nothing distinguished a 5-hour window from a weekly cap from a spent
# account, so all three were served the same one-hour guess.
#
# These are limit CLASSES, not exhaustion classes: `classify_exhaustion` still decides
# PERMANENT vs TRANSIENT (and PERMANENT still wins ties). This decides HOW LONG to stay away,
# and only refines the window — it never resurrects a brain the classifier benched.
LIMIT_SESSION_5H = "session_5h"
LIMIT_WEEKLY = "weekly"
LIMIT_NONE = ""

#: Fallback windows, used ONLY when the provider states no reset time we can parse.
DEFAULT_LIMIT_WINDOW_S = {
    LIMIT_SESSION_5H: 5 * 3600,
    LIMIT_WEEKLY: 7 * 24 * 3600,
}

#: A weekly cap is the one limit nothing automatic can clear, so it is worth naming separately
#: even when the same words could be read as a session cap. Checked FIRST for that reason.
_WEEKLY_LIMIT_RE = re.compile(
    r"\bweekly\s+limit\b|\blimit\s+resets?\s+(?:on|next)\s+\w+day\b|\bper[-\s]week\b", re.I)
_SESSION_5H_RE = re.compile(
    r"\b(?:5|five)[-\s]?hour\b|\bsession\s+limit\b|\bcurrent\s+session\b", re.I)

# "resets at 2026-08-07T00:00:00Z" / "resets on 2026-08-07 00:00"
_RESET_AT_ISO = re.compile(
    r"resets?\s+(?:at|on)\s+"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?"
    r"(?:Z|[+-][0-9]{2}:?[0-9]{2})?)", re.I)
# "resets at 5pm" / "resets at 17:00" — no date, so it means the NEXT such wall-clock time.
_RESET_AT_CLOCK = re.compile(r"resets?\s+at\s+([0-9]{1,2})(?::([0-9]{2}))?\s*(am|pm)?\b", re.I)

#: No parsed window may exceed this. A malformed or far-future timestamp must not bench a brain
#: for a month; a week is the longest real limit this system meets.
_MAX_WINDOW_S = 7 * 24 * 3600


def _parse_absolute_reset(text: str, now: Optional[_dt.datetime] = None) -> Optional[float]:
    """Seconds until an ABSOLUTE reset time stated in `text`, or None.

    Returns None (not a negative or zero) for an already-past reset: that means the window has
    expired and the caller should use its own default rather than treat the brain as live.
    """
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    t = text or ""

    m = _RESET_AT_ISO.search(t)
    if m:
        raw = m.group(1).replace(" ", "T")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            when = _dt.datetime.fromisoformat(raw)
        except ValueError:
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
            delta = (when - now).total_seconds()
            if delta > 0:
                return float(min(delta, _MAX_WINDOW_S))

    m = _RESET_AT_CLOCK.search(t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        meridiem = (m.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when <= now:                      # that time already passed today -> tomorrow
                when += _dt.timedelta(days=1)
            return float(min((when - now).total_seconds(), _MAX_WINDOW_S))
    return None


def classify_limit(text: str) -> str:
    """Classify WHICH limit was hit: LIMIT_WEEKLY, LIMIT_SESSION_5H, or LIMIT_NONE.

    Weekly is checked first and wins: it is the only class nothing automatic can clear, so
    mistaking it for a session cap costs a week of hourly full-price probes, while mistaking a
    session cap for weekly costs at most one delayed half-open probe (health.py re-probes).
    """
    t = text or ""
    if _WEEKLY_LIMIT_RE.search(t):
        return LIMIT_WEEKLY
    if _SESSION_5H_RE.search(t):
        return LIMIT_SESSION_5H
    return LIMIT_NONE


def limit_window_seconds(text: str, now: Optional[_dt.datetime] = None) -> Optional[float]:
    """How long to bench a provider given its error text, or None to use the caller's default.

    Precedence: a STATED reset time (relative or absolute) always beats a class default, because
    the provider knows when its own quota returns and we are only guessing. Only when nothing is
    parseable does the limit class supply a window.
    """
    stated = parse_reset_seconds(text, now=now)
    if stated is not None and stated > 0:
        return float(min(stated, _MAX_WINDOW_S))
    klass = classify_limit(text)
    if klass:
        return float(DEFAULT_LIMIT_WINDOW_S[klass])
    return None

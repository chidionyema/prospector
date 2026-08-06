"""Shared error types for provider failover.

ProviderExhaustedError is the failover SIGNAL: a provider (LLM brain or grounding
search) reports it is out of credit/quota for the rest of this run. Fallback
wrappers catch it, retire that provider, and try the next one. It is deliberately
distinct from a generic transient failure (retried in place) and from a legitimate
empty result (real evidence of nothing — never a failover).
"""
from __future__ import annotations

import re
from typing import Optional


class ProviderExhaustedError(RuntimeError):
    """Raised when a provider is out of quota/credit and cannot serve this run.

    Carries the provider name so the fallback layer can log which brain/search
    backend retired and which one took over.
    """

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


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
_ALLOWANCE_LIMIT_RE = re.compile(r"\b(spend|usage|monthly|weekly|daily)\s+limit\b")
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


def parse_reset_seconds(text: str) -> Optional[float]:
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
    return None

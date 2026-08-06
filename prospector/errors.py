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


# Substrings that mean "this account/model is out of allowance for now" across the
# claude CLI and the Anthropic APIs. Matched case-insensitively
# against an adapter's error text to classify a failure as exhaustion (-> failover).
_EXHAUSTION_MARKERS = (
    "quota_exhausted",
    "exhausted your capacity",
    "terminalquotaerror",
    "resource_exhausted",
    "rate_limit",
    "rate limit",
    "429",
    "insufficient_quota",
    "insufficient balance",
    "credit balance is too low",
    "billing",
    "usage limit",
    # 402 = "you are out of money", the most PERMANENT failure a metered brain has, and it was
    # the one shape this list missed. Measured 2026-08-06: deepseek answered every call with
    #   RuntimeError: DeepSeek call failed: HTTP Error 402: Payment Required
    # None of the markers above appear in that string, so the failure classified as transient:
    # `FallbackOperator._raw` sets `hard = isinstance(e, ProviderExhaustedError)`, so
    # `mark_exhausted` never ran and deepseek never appeared in
    # store/provider_health_noncritical.json — while cursor_cli, which does raise
    # ProviderExhaustedError, was correctly marked dead_until in the same file at the same time.
    # The breaker alone then re-probed a permanently-broke account every cooldown_s (60s),
    # forever, at the head of the chain. `errors.py:36` already documents 402 as exhaustion for
    # the retrieval side; the brain side simply never learned it.
    "402",
    "payment required",
)
# DELIBERATELY NOT HERE: 401 / "unauthorized". That is a bad or expired credential, not a spent
# allowance, and marking it exhausted would bury a config error under a silent hour-long
# failover — the opposite of what this list is for. It should fail loudly on every call.


def looks_exhausted(text: str) -> bool:
    """True if an error string indicates quota/credit exhaustion (-> failover)."""
    t = (text or "").lower()
    return any(m in t for m in _EXHAUSTION_MARKERS)


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

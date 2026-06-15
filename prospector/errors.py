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
# gemini + claude CLIs and the Anthropic/Google APIs. Matched case-insensitively
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
    "credit balance is too low",
    "billing",
    "usage limit",
)


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

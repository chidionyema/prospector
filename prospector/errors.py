"""Shared error types for provider failover.

ProviderExhaustedError is the failover SIGNAL: a provider (LLM brain or grounding
search) reports it is out of credit/quota for the rest of this run. Fallback
wrappers catch it, retire that provider, and try the next one. It is deliberately
distinct from a generic transient failure (retried in place) and from a legitimate
empty result (real evidence of nothing — never a failover).
"""
from __future__ import annotations


class ProviderExhaustedError(RuntimeError):
    """Raised when a provider is out of quota/credit and cannot serve this run.

    Carries the provider name so the fallback layer can log which brain/search
    backend retired and which one took over.
    """

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.provider = provider


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

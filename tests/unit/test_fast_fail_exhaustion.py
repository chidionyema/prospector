"""Fast-fail on exhaustion: an unmistakable QUOTA_EXHAUSTED / rate-limit signature must
short-circuit the retry loop — retrying a quota error (with an even LONGER adaptive
timeout) just burns ~timeout seconds per attempt re-confirming a dead provider. A
transient error still gets its full retry budget."""
from __future__ import annotations

import pytest

from prospector import gemini_cli, claude_cli
from prospector.errors import ProviderExhaustedError


def test_gemini_exhaustion_skips_remaining_retries(monkeypatch):
    calls = {"n": 0}

    def fake_attempt(cmd, timeout, web, queue_timeout=None):
        calls["n"] += 1
        raise RuntimeError("gemini cli exit 1: reason: 'QUOTA_EXHAUSTED', retryDelayMs: 5000")

    monkeypatch.setattr(gemini_cli, "_attempt_gemini_cli", fake_attempt)
    monkeypatch.setattr(gemini_cli.time, "sleep", lambda *_: None)   # no real backoff sleeps
    with pytest.raises(ProviderExhaustedError):
        gemini_cli.run_gemini_cli("p", web=True, retries=2)
    assert calls["n"] == 1            # one attempt, NOT retries+1 (=3)


def test_gemini_transient_uses_full_retry_budget(monkeypatch):
    calls = {"n": 0}

    def fake_attempt(cmd, timeout, web, queue_timeout=None):
        calls["n"] += 1
        raise RuntimeError("connection reset by peer")     # transient, not exhaustion

    monkeypatch.setattr(gemini_cli, "_attempt_gemini_cli", fake_attempt)
    monkeypatch.setattr(gemini_cli.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError):
        gemini_cli.run_gemini_cli("p", web=True, retries=2)
    assert calls["n"] == 3            # transient error retried fully (retries+1)


def test_claude_exhaustion_skips_remaining_retries(monkeypatch):
    calls = {"n": 0}

    def fake_attempt(cmd, timeout, web, queue_timeout=None):
        calls["n"] += 1
        raise RuntimeError("claude cli: 429 rate limit exceeded")

    monkeypatch.setattr(claude_cli, "_attempt_claude_cli", fake_attempt)
    monkeypatch.setattr(claude_cli.time, "sleep", lambda *_: None)
    with pytest.raises(ProviderExhaustedError):
        claude_cli.run_claude_cli("p", web=True, retries=2)
    assert calls["n"] == 1

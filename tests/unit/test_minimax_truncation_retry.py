"""M3 spending its whole budget on reasoning is a coin landing badly, not a verdict.

Measured 2026-08-14 on the retitle of the live shelf: the SAME 14 packs truncated at pack 2
on one run and at pack 5 on the next, and the packs that failed the first time succeeded on
the second. With claude_cli removed from the non-critical chain (config.yaml:70, founder
directive) and StandardCompute out of free trial, MiniMax is the only tier left — so a
truncation that raises on the first occurrence stops generation, prescreen, score and retitle
alike, one pack at a time.
"""
from __future__ import annotations

import pytest

from prospector.operator import MiniMaxOperator, _MiniMaxTruncated


@pytest.fixture
def op(monkeypatch) -> MiniMaxOperator:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    return MiniMaxOperator()


def _scripted(outcomes):
    """A `_raw_once` that plays `outcomes` in order: an exception is raised, a str returned."""
    calls = []

    def fake(self, system, user, temperature):
        calls.append((system, user))
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    return fake, calls


def test_a_truncated_response_is_re_asked_and_the_second_answer_is_returned(op, monkeypatch):
    fake, calls = _scripted([_MiniMaxTruncated("truncated at max_tokens"), '{"ok": 1}'])
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    assert op._raw("sys", "user", 0.0) == '{"ok": 1}'
    assert len(calls) == 2
    assert calls[0] == calls[1], "the re-ask must send the same prompt, not a repaired one"


def test_the_re_asks_are_bounded_and_then_it_fails_over_as_an_ordinary_error(op, monkeypatch):
    """Three failures in a row is a prompt problem, not a coin toss. The exception that
    escapes must be a plain RuntimeError so `FallbackOperator` treats it as a normal tier
    failure — NOT a ProviderExhaustedError, because nothing is exhausted."""
    from prospector.errors import ProviderExhaustedError

    fake, calls = _scripted([_MiniMaxTruncated("t")] * 5)
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    with pytest.raises(RuntimeError) as excinfo:
        op._raw("sys", "user", 0.0)
    assert len(calls) == MiniMaxOperator._RETRY_TRUNCATED_MAX + 1 == 3
    assert not isinstance(excinfo.value, ProviderExhaustedError)
    assert "truncated" in str(excinfo.value) or "t" in str(excinfo.value)


def test_a_clean_first_answer_costs_exactly_one_call(op, monkeypatch):
    """The retry must not become a tax on the normal path: a 32k-token budget is burned by
    every extra attempt."""
    fake, calls = _scripted(['{"ok": 1}'])
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    assert op._raw("sys", "user", 0.0) == '{"ok": 1}'
    assert len(calls) == 1


def test_any_other_failure_is_not_retried(op, monkeypatch):
    """Only a truncation earns a re-ask on THIS budget. A 402 must reach the chain at once, so
    the next tier answers instead of paying two more full-budget calls first.

    A stall is the other retriable case and carries its own, narrower budget — see
    `test_minimax_stall_retry.py`. It is deliberately not counted here: the two failures have
    opposite costs (a truncation is detected after a full emitted body, a stall after 90s of
    nothing), so one shared counter would price them the same."""
    fake, calls = _scripted([RuntimeError("MiniMax call failed: HTTP Error 402"), '{"ok": 1}'])
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    with pytest.raises(RuntimeError, match="402"):
        op._raw("sys", "user", 0.0)
    assert len(calls) == 1

"""Silence on the wire is a coin landing badly, not a verdict — and it was never retried.

M3 emits its reasoning as `<think>…</think>` INSIDE `delta.content` (`_raw_once` strips it with
`_RE_THINK` before deciding a response is truncated), so a call that is reasoning is streaming
bytes the whole time. `_STALL_TIMEOUT_S` therefore measures SILENCE, and silence is server-side
queueing or a wedged socket: transient, and worth exactly the same re-ask a truncation already
earned.

Measured over `store/scheduler/launchd.err.log` (259,412 lines, 2026-08-06 → 2026-08-15):

    345  read operation timed out          <- retried 0 times before this module
     23  spent its whole budget reasoning  <- retried 2 times each
     13  exceeded 600s hard deadline       <- retried 0 times

231 of the terminal failures read `Generation chain EXHAUSTED` and 172 were marketing/artifact
copy, against 67 verdict failures — because `noncritical_operator: [minimax]` is one tier deep
while the moat chain has two. Until that asymmetry is fixed, the first stall on a generation
batch loses the whole batch.
"""
from __future__ import annotations

import pytest

from prospector.errors import ProviderExhaustedError
from prospector.operator import MiniMaxOperator, _MiniMaxDeadline, _MiniMaxStalled


@pytest.fixture
def op(monkeypatch) -> MiniMaxOperator:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    return MiniMaxOperator()


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """The backoff is real seconds. Capture it instead of paying it."""
    slept: list[float] = []
    monkeypatch.setattr("prospector.operator.time.sleep", slept.append)
    return slept


def _scripted(outcomes):
    calls = []

    def fake(self, system, user, temperature):
        calls.append((system, user))
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    return fake, calls


# ---------------------------------------------------------------- classification

def test_a_read_timeout_is_classified_stalled_not_a_flat_failure(op, monkeypatch):
    """THE defect. `socket.timeout` carries the message the 345 log lines carry, and IS
    `TimeoutError` on 3.10+. Before this, it fell through to the bare `RuntimeError` arm and
    `_raw` had no arm that could catch it."""
    def boom(req, *, stall_timeout, total_deadline):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("prospector.operator._read_sse_bounded", boom)
    with pytest.raises(_MiniMaxStalled, match="timed out"):
        op._raw_once("sys", "user", 0.0)


def test_the_hard_deadline_is_NOT_retried(op, monkeypatch):
    """The deliberate asymmetry. A stall is 90s of silence — cheap to detect, worth one
    re-ask. The hard deadline is 600s of a live stream that never stopped, so a re-ask buys a
    second 600s and puts one call's worst case at 1205s inside a tick budget. It must reach the
    chain as an ordinary RuntimeError on the first occurrence."""
    def boom(req, *, stall_timeout, total_deadline):
        raise _MiniMaxDeadline("streamed response exceeded 600s hard deadline")

    monkeypatch.setattr("prospector.operator._read_sse_bounded", boom)
    with pytest.raises(RuntimeError, match="deadline") as excinfo:
        op._raw_once("sys", "user", 0.0)
    assert not isinstance(excinfo.value, _MiniMaxStalled)


def test_an_allowance_notice_is_still_exhaustion_even_if_it_mentions_a_timeout(op, monkeypatch):
    """The stall arm matches the substring `timed out`, so it MUST sit below the exhaustion
    classifier: a permanent failure that happens to say 'timed out' would otherwise be retried
    forever against a dead account instead of benching the brain."""
    def boom(req, *, stall_timeout, total_deadline):
        raise RuntimeError("credit balance is too low; the request timed out waiting")

    monkeypatch.setattr("prospector.operator._read_sse_bounded", boom)
    with pytest.raises(ProviderExhaustedError):
        op._raw_once("sys", "user", 0.0)


# ---------------------------------------------------------------- retry budget

def test_a_stall_is_re_asked_and_the_second_answer_is_returned(op, monkeypatch, no_real_sleep):
    fake, calls = _scripted([_MiniMaxStalled("The read operation timed out"), '{"ok": 1}'])
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    assert op._raw("sys", "user", 0.0) == '{"ok": 1}'
    assert len(calls) == 2
    assert calls[0] == calls[1], "the re-ask must send the same prompt"
    assert no_real_sleep == [MiniMaxOperator._RETRY_STALL_BACKOFF_S], \
        "one backoff, paid before the re-ask and never after the last failure"


def test_the_stall_budget_is_one_and_then_it_fails_over_normally(op, monkeypatch):
    """Narrower than the truncation budget on purpose: a stall costs its full 90s bound before
    it is even detected, and if the cause is server-side queueing a wide budget feeds it."""
    fake, calls = _scripted([_MiniMaxStalled("timed out")] * 5)
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    with pytest.raises(RuntimeError) as excinfo:
        op._raw("sys", "user", 0.0)
    assert len(calls) == MiniMaxOperator._RETRY_STALL_MAX + 1 == 2
    assert not isinstance(excinfo.value, ProviderExhaustedError), \
        "nothing is exhausted — the chain must fail over to the next tier, not bench the brain"


def test_a_clean_first_answer_still_costs_exactly_one_call(op, monkeypatch, no_real_sleep):
    fake, calls = _scripted(['{"ok": 1}'])
    monkeypatch.setattr(MiniMaxOperator, "_raw_once", fake)
    assert op._raw("sys", "user", 0.0) == '{"ok": 1}'
    assert len(calls) == 1
    assert no_real_sleep == []

"""MiniMax streams, so "slow" and "dead" stop being the same measurement.

THE DEFECT, MEASURED
--------------------
On a non-streamed completion the first byte arrives only when the model has FINISHED, so
time-to-first-byte is the whole generation time and a per-recv socket timeout grades duration,
not liveness. `store/prospector.jsonl` (`operation=minimax_raw_call`), 406 calls since
2026-08-12, read on 2026-08-14:

    failures  116/406 = 28.6%    23% of them at 239-246s  — exactly the 240s per-recv cap
                                  9% of them at 246-310s  — exactly the 300s hard deadline
    successes 290/406            60% completed under 60s — the provider was alive throughout

In one measured tick that cost six whole generation batches (`Generation chain EXHAUSTED ...
MiniMax call failed: The read operation timed out`) while MiniMax was answering other calls in
the same minute. Raising the cap only moves the cliff — 120s was raised to 240s in July for this
same symptom. A duration bound cannot grade a call whose duration is invisible until it ends.

Streamed, tokens arrive from ~1.3s (probed live 2026-08-14) so the socket timeout measures
SILENCE, which is what actually distinguishes slow from dead.

These tests emulate real socket semantics: the fake response raises `socket.timeout` when a gap
between chunks exceeds the timeout the caller passed to `urlopen`, exactly as urllib does.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request

import pytest

from prospector import operator as op_mod
from prospector.operator import MiniMaxOperator

# ---------------------------------------------------------------------------
# A fake stream with a real socket's timeout behaviour
# ---------------------------------------------------------------------------

class _FakeSSE:
    """Iterable HTTP response over a scripted SSE body.

    `frames` is a list of `(gap_seconds, line_bytes)`. A gap longer than the socket timeout
    raises `socket.timeout` — the per-recv contract urllib actually provides.
    """

    def __init__(self, frames, timeout, endless=False):
        self._frames = list(frames)
        self._timeout = timeout
        self._endless = endless
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        if not self._frames:
            if self._endless:  # a body that never ends — only the hard deadline can stop it
                time.sleep(0.02)
                return b'data: {"choices":[{"delta":{"content":"."}}]}\n'
            raise StopIteration
        gap, line = self._frames.pop(0)
        if gap > self._timeout:
            time.sleep(self._timeout)
            raise socket.timeout("The read operation timed out")
        time.sleep(gap)
        return line

    def close(self):
        self.closed = True


def _sse(*events: dict) -> bytes:
    return b"data: " + json.dumps(events[0]).encode() + b"\n"


def _frames(pieces, *, gap=0.0, finish="stop", usage=None):
    out = [(gap, _sse({"choices": [{"delta": {"content": p}}]})) for p in pieces]
    out.append((gap, _sse({"choices": [{"delta": {}, "finish_reason": finish}]})))
    if usage is not None:
        out.append((gap, _sse({"choices": [], "usage": usage})))
    out.append((gap, b"data: [DONE]\n"))
    return out


@pytest.fixture()
def op(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(MiniMaxOperator, "_RETRY_429_BASE_S", 0.01, raising=False)
    return MiniMaxOperator()


def _serve(monkeypatch, frames, *, endless=False, capture=None):
    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture["timeout"] = timeout
            capture["payload"] = json.loads(req.data.decode())
        return _FakeSSE(frames, timeout, endless=endless)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


# ---------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------

def test_a_slow_but_flowing_stream_is_not_a_timeout(op, monkeypatch):
    """THE defect. A call whose TOTAL duration exceeds the socket timeout still succeeds,
    because the socket timeout now bounds each GAP. Under the old whole-body read this exact
    call was `The read operation timed out` and took a generation batch down with it."""
    monkeypatch.setattr(MiniMaxOperator, "_STALL_TIMEOUT_S", 0.25, raising=False)
    monkeypatch.setattr(MiniMaxOperator, "_TOTAL_DEADLINE_S", 30.0, raising=False)
    pieces = ["<think>", "reasoning " * 3, "</think>", '{"ok": true}']
    _serve(monkeypatch, _frames(pieces, gap=0.1))

    t0 = time.time()
    out = op._raw("s", "u", 0.0)
    elapsed = time.time() - t0

    assert '{"ok": true}' in out
    assert elapsed > 0.25, (
        f"the call finished in {elapsed:.2f}s — it did not outlive the {0.25}s stall bound, "
        "so this test is not exercising the defect it is named for")


def test_silence_longer_than_the_stall_timeout_still_fails(op, monkeypatch):
    """The other half: a wedged stream must still die, and quickly. Liveness detection is the
    thing being preserved, not traded away."""
    monkeypatch.setattr(MiniMaxOperator, "_STALL_TIMEOUT_S", 0.2, raising=False)
    monkeypatch.setattr(MiniMaxOperator, "_TOTAL_DEADLINE_S", 30.0, raising=False)
    frames = [(0.01, _sse({"choices": [{"delta": {"content": "<think>"}}]})),
              (99.0, b'data: never\n')]
    _serve(monkeypatch, frames)

    t0 = time.time()
    with pytest.raises(RuntimeError, match="timed out"):
        op._raw("s", "u", 0.0)
    assert time.time() - t0 < 5, "a dead stream must fail on the stall bound, not the deadline"


def test_the_hard_deadline_still_bounds_an_endless_stream(op, monkeypatch):
    """A body that trickles forever resets every per-recv timer. This is the 46-hour wedge
    (`test_no_unbounded_provider_reads.py`) and only the total deadline can stop it."""
    monkeypatch.setattr(MiniMaxOperator, "_STALL_TIMEOUT_S", 5.0, raising=False)
    monkeypatch.setattr(MiniMaxOperator, "_TOTAL_DEADLINE_S", 0.5, raising=False)
    _serve(monkeypatch, [], endless=True)

    t0 = time.time()
    with pytest.raises(RuntimeError, match="deadline"):
        op._raw("s", "u", 0.0)
    assert time.time() - t0 < 5


def test_the_two_bounds_measure_different_things(op):
    """A stall bound at or above the deadline is the old single-number compromise wearing two
    names, and would silently restore the defect."""
    assert MiniMaxOperator._STALL_TIMEOUT_S < MiniMaxOperator._TOTAL_DEADLINE_S
    assert MiniMaxOperator._TOTAL_DEADLINE_S > 300, (
        "the hard deadline is no larger than the old 300s cap that was cutting live calls off")


# ---------------------------------------------------------------------------
# The request, and the meter it feeds
# ---------------------------------------------------------------------------

def test_the_request_asks_for_a_stream_and_for_its_usage(op, monkeypatch):
    """`include_usage` is not decoration: without it an OpenAI-compatible stream omits the usage
    block entirely and every MiniMax call would book 0 tokens into the spend ledger."""
    cap: dict = {}
    _serve(monkeypatch, _frames(['{"ok": true}']), capture=cap)
    op._raw("s", "u", 0.0)

    assert cap["payload"]["stream"] is True
    assert cap["payload"]["stream_options"]["include_usage"] is True
    assert cap["timeout"] == MiniMaxOperator._STALL_TIMEOUT_S, (
        "the socket timeout passed to urlopen must be the STALL bound")


def test_usage_from_the_stream_reaches_the_spend_ledger(op, monkeypatch):
    """The usage block moved from the response body to the stream's last event. If nothing reads
    it there, spend silently reports zero for the cheapest-but-most-called brain."""
    seen: dict = {}
    from prospector import telemetry
    monkeypatch.setattr(telemetry, "record_usage", lambda **kw: seen.update(kw))
    _serve(monkeypatch, _frames(['{"ok": true}'],
                                usage={"prompt_tokens": 187, "completion_tokens": 50,
                                       "total_tokens": 237}))
    op._raw("s", "u", 0.0)

    assert (seen.get("input_tokens"), seen.get("output_tokens"), seen.get("total_tokens")) \
        == (187, 50, 237)


def test_the_reassembled_content_matches_the_non_streamed_shape(op, monkeypatch):
    """Callers parse `<think>…</think>` + JSON out of one string. Streaming must hand back the
    same string the non-streamed `message.content` did, or every downstream parser changes."""
    _serve(monkeypatch, _frames(["<thi", "nk>\nreason\n</think>", "\n\n", '{"ok": true}']))
    assert op._raw("s", "u", 0.0) == '<think>\nreason\n</think>\n\n{"ok": true}'


def test_a_partial_frame_mid_stream_is_not_a_failed_call(op, monkeypatch):
    """SSE carries keep-alives, comments and split frames. Any of those raising would convert a
    healthy call into a chain failover."""
    frames = [(0.0, b": keep-alive\n"),
              (0.0, b"\n"),
              (0.0, b"data: {not json\n"),
              (0.0, _sse({"choices": [{"delta": {"content": '{"ok": true}'}}]})),
              (0.0, b"data: [DONE]\n")]
    _serve(monkeypatch, frames)
    assert op._raw("s", "u", 0.0) == '{"ok": true}'


# ---------------------------------------------------------------------------
# Truncation: an HTTP success carrying no answer
# ---------------------------------------------------------------------------

def test_a_reasoning_only_truncation_fails_over_instead_of_being_retried(op, monkeypatch):
    """Measured 2026-08-14: 142,992 chars that ended `</think>\\n\\n`. finish_reason=length means
    the budget went entirely on reasoning, so retrying the SAME prompt on the SAME model is three
    guaranteed failures. Named as a call failure, it fails over on the first one."""
    _serve(monkeypatch, _frames(["<think>", "reasoning", "</think>", "\n\n"], finish="length"))
    with pytest.raises(RuntimeError, match="truncated at max_tokens"):
        op._raw("s", "u", 0.0)


def test_a_complete_answer_that_merely_ends_at_the_cap_is_kept(op, monkeypatch):
    """The truncation rule must fire on "no answer", never on "long answer" — otherwise it
    throws away good JSON that happened to finish on the boundary."""
    _serve(monkeypatch, _frames(["<think>r</think>", '{"ok": true}'], finish="length"))
    assert '{"ok": true}' in op._raw("s", "u", 0.0)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_minimax_no_longer_reads_the_whole_body_at_once(op, monkeypatch):
    """The old transport is what the defect lives in; a partial refactor that leaves MiniMax on
    it would keep failing while every test above still passed."""
    def boom(*a, **k):
        raise AssertionError("MiniMax used the non-streaming whole-body read")

    monkeypatch.setattr(op_mod, "_urlopen_read_bounded", boom)
    _serve(monkeypatch, _frames(['{"ok": true}']))
    assert op.complete_json("s", "u") == {"ok": True}

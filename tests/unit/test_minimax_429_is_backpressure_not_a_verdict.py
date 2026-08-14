"""A 429 is the provider asking us to slow down, not telling us it is dead.

THE INCIDENT, measured 2026-08-09. The first run that routed the £49 pack prose to MiniMax
produced **281 `HTTP Error 429: Too Many Requests`** and zero sellable packs across 29
dossiers. MiniMax was not the weak link: the same run logged a 34,200-char `ops_plan` and a
29,888-char `gtm_plan`, both coherent. It was request pressure — `generate_artifacts` and
`generate_marketing_content` each fan out 4 concurrent calls (artifacts.py:438/634/815) at
`max_tokens: 32768`, and when the resulting empties failed `validate_pack` the driver retried
the WHOLE pack 3x. The flakiness budget was feeding the thing causing the flakiness.

Why the 429 was fatal rather than survivable: `Operator.complete_json`'s retry loop catches
only ParseError/JSONDecodeError/ValueError, so a `ProviderExhaustedError` propagates straight
past it — no retry, no sleep — even though `errors.classify_exhaustion` already grades 429 as
TRANSIENT. A transient signal was reaching a caller with no path to wait it out.

These tests pin the two rails and, deliberately, the ORDER of the fix: the retry must happen
inside `_raw`, below `complete_json`, because that is the only layer that can distinguish
backpressure from exhaustion.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector import operator as op_mod
from prospector.errors import ProviderExhaustedError
from prospector.operator import MiniMaxOperator

# The transport moved to a bounded SSE stream on 2026-08-14 (a duration bound could not tell
# a slow MiniMax call from a dead one — see test_minimax_streams_so_slow_is_not_dead.py), so
# the seam these tests fake is `_read_sse_bounded` and its return is (content, usage, finish).
# What is under test here is unchanged: backpressure is waited out, everything else fails over.
_OK_STREAM = ('{"ok": true}', {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
              "stop")


def _op(monkeypatch) -> MiniMaxOperator:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    o = MiniMaxOperator()
    # Backoff exists to be waited out, not to make the suite slow.
    monkeypatch.setattr(MiniMaxOperator, "_RETRY_429_BASE_S", 0.01, raising=False)
    return o


def test_a_429_is_retried_and_the_call_still_succeeds(monkeypatch):
    """The regression itself. Two 429s then a 200 used to surface as a hard failure and an
    empty artifact; it must now come back as the answer the provider was willing to give."""
    calls = {"n": 0}

    def fake(req, stall_timeout=None, total_deadline=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("HTTP Error 429: Too Many Requests")
        return _OK_STREAM

    monkeypatch.setattr(op_mod, "_read_sse_bounded", fake)
    assert _op(monkeypatch).complete_json("s", "u") == {"ok": True}
    assert calls["n"] == 3, "the 429s were not retried"


def test_backoff_is_bounded_and_then_it_is_an_honest_exhaustion(monkeypatch):
    """We ask, we wait, and if it is still saying no we stop claiming otherwise. Unbounded
    retry would turn a real quota wall into a hang."""
    calls = {"n": 0}

    def fake(req, stall_timeout=None, total_deadline=None):
        calls["n"] += 1
        raise OSError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(op_mod, "_read_sse_bounded", fake)
    o = _op(monkeypatch)
    with pytest.raises(ProviderExhaustedError):
        o._raw("s", "u", 0.0)
    assert calls["n"] == MiniMaxOperator._RETRY_429_MAX + 1


def test_the_delay_actually_grows(monkeypatch):
    """Retrying at a fixed interval against a rate limiter is just a slower storm."""
    slept: list[float] = []
    monkeypatch.setattr(op_mod.time, "sleep", slept.append)
    monkeypatch.setattr(op_mod, "_read_sse_bounded",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("HTTP Error 429: x")))
    o = _op(monkeypatch)
    with pytest.raises(ProviderExhaustedError):
        o._raw("s", "u", 0.0)
    assert slept == sorted(slept) and slept[-1] > slept[0], f"not backing off: {slept}"


def test_a_non_429_failure_is_not_slowed_down(monkeypatch):
    """Scope. A 500 or a timeout must fail over to the next tier immediately — spending the
    backoff on those would delay every real outage by design."""
    calls = {"n": 0}

    def fake(req, stall_timeout=None, total_deadline=None):
        calls["n"] += 1
        raise OSError("HTTP Error 500: Internal Server Error")

    monkeypatch.setattr(op_mod, "_read_sse_bounded", fake)
    with pytest.raises(RuntimeError):
        _op(monkeypatch)._raw("s", "u", 0.0)
    assert calls["n"] == 1


def test_429_matches_on_a_word_boundary_not_a_substring(monkeypatch):
    """This repo has already paid for the bare-substring version once: a request id containing
    the digits of an HTTP code benched a live brain (memory:
    substring-http-codes-bench-a-live-brain). A body that merely CONTAINS 429 is not a 429."""
    calls = {"n": 0}

    def fake(req, stall_timeout=None, total_deadline=None):
        calls["n"] += 1
        raise OSError("MiniMax call failed: request id req-84291337 truncated at 4296 bytes")

    monkeypatch.setattr(op_mod, "_read_sse_bounded", fake)
    with pytest.raises(RuntimeError):
        _op(monkeypatch)._raw("s", "u", 0.0)
    assert calls["n"] == 1, "a request id was mistaken for backpressure"


def test_concurrent_callers_are_bounded_by_the_semaphore(monkeypatch):
    """The burst that caused the incident was CONCURRENT, not sequential — 8 simultaneous
    calls per pack. A per-call sleep cannot bound that; only a process-wide slot count can."""
    limit = 2
    monkeypatch.setattr(MiniMaxOperator, "_throttle", threading.Semaphore(limit), raising=False)
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake(req, stall_timeout=None, total_deadline=None):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1
        return _OK_STREAM

    monkeypatch.setattr(op_mod, "_read_sse_bounded", fake)
    o = _op(monkeypatch)
    threads = [threading.Thread(target=lambda: o._raw("s", "u", 0.0)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert live["peak"] <= limit, f"{live['peak']} concurrent requests against a limit of {limit}"

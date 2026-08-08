"""E3 must stop the sweep on a PERMANENT exhaustion, and must not pool the partial level.

2026-08-07: run #6 hit the account's monthly spend limit part-way through and then spent 50
more calls, every one failing identically. Worse than the waste, it POOLED those zero-throughput
waves into the same rows as the good ones, so the printed table attributed a billing outage to
N — N=6 and N=4 read "18 ok / 18 bad" and "16 ok / 16 bad", exactly one dead rep each.

A permanent exhaustion is the end of the measurement, not a datum about concurrency. TRANSIENT
backpressure is deliberately NOT an abort: a call that is slow or 429'd under load is the
signal E3 exists to capture.

The CLI is stubbed, so this test spends nothing.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
E3_PATH = REPO / "tools" / "experiments" / "e3_concurrency_knee.py"


def _load_e3():
    spec = importlib.util.spec_from_file_location("_e3_under_test", E3_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub_cli(monkeypatch, behaviour):
    """Install a fake prospector.claude_cli whose run_claude_cli follows `behaviour`.

    `_worker` imports claude_cli INSIDE the function (the governor binds at import), so
    replacing the module in sys.modules before the call is enough — no real subprocess, no
    governor, no spend.
    """
    calls: list[str] = []

    def run_claude_cli(prompt, timeout=None, retries=0, **kw):
        calls.append(prompt)
        return behaviour(len(calls), prompt)

    fake = types.ModuleType("prospector.claude_cli")
    fake._MAX_CLI = 4
    fake.run_claude_cli = run_claude_cli
    monkeypatch.setitem(sys.modules, "prospector.claude_cli", fake)
    return calls


def _echo(_i, prompt):
    return prompt.rsplit(": ", 1)[-1]


def test_permanent_exhaustion_aborts_and_stops_spending(monkeypatch):
    """After the first spend-limit failure the worker must issue no further calls."""
    e3 = _load_e3()

    def behaviour(i, prompt):
        # 2 warm calls (1 wave at n=2) + 2 measured, then the allowance dies.
        if i <= 4:
            return _echo(i, prompt)
        raise RuntimeError(
            "claude cli exit 1: API Error: Your monthly spend limit has been reached.")

    calls = _stub_cli(monkeypatch, behaviour)
    # 16 calls at n=2 is 8 measured waves; the abort must cut it far short of that.
    res = e3._worker(n=2, calls=16, warm_waves=1)

    assert res["aborted"], "a permanent exhaustion must set `aborted`"
    assert "monthly spend limit" in res["aborted"]
    assert res["waves"] == 8, "the PLANNED wave count is still reported"
    assert res["waves_run"] < res["waves"], "the sweep must stop short of the plan"
    # 2 warm + 2 ok + 2 failing = 6. Without the abort this would run all 18.
    assert len(calls) == 6, f"kept spending after exhaustion: {len(calls)} calls"


def test_transient_failure_does_not_abort(monkeypatch):
    """A 429 under load is the signal, not the end of the run — it must be measured."""
    e3 = _load_e3()

    def behaviour(i, prompt):
        if i == 5:
            raise RuntimeError("claude cli exit 1: api_error_status: 429 overloaded_error")
        return _echo(i, prompt)

    calls = _stub_cli(monkeypatch, behaviour)
    res = e3._worker(n=2, calls=8, warm_waves=1)

    assert res["aborted"] is None, "transient backpressure must not abort the level"
    assert len(calls) == 2 + 8, "every planned call must still run"
    assert sum(1 for c in res["calls"] if c["outcome"] == "error") == 1


def test_clean_run_reports_no_abort(monkeypatch):
    e3 = _load_e3()
    _stub_cli(monkeypatch, _echo)
    res = e3._worker(n=4, calls=8, warm_waves=1)

    assert res["aborted"] is None
    assert res["waves_run"] == res["waves"] == 2
    assert all(c["outcome"] == "ok" for c in res["calls"])


@pytest.mark.parametrize("msg,should_abort", [
    ("claude cli exit 1: Your monthly spend limit has been reached.", True),
    ("claude cli exit 1: credit balance is too low", True),
    ("claude cli exit 1: api_error_status: 429", False),
    ("claude cli exit 1: overloaded_error", False),
    ("claude cli exit 1: something unrecognised entirely", False),
])
def test_abort_uses_the_shared_classifier(monkeypatch, msg, should_abort):
    """The abort rule must be `errors.classify_exhaustion`, not a private string list.

    CLAUDE.md: permanence is classified by ONE shared, tested function. A second opinion here
    is how a failure the classifier misses gets retried forever in one place and aborted in
    another.
    """
    e3 = _load_e3()

    def behaviour(i, prompt):
        if i <= 2:
            return _echo(i, prompt)
        raise RuntimeError(msg)

    _stub_cli(monkeypatch, behaviour)
    res = e3._worker(n=1, calls=6, warm_waves=1)
    assert bool(res["aborted"]) is should_abort, msg

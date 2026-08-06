"""A call that billed must reach the ledger even when we dislike what it returned.

`_attempt_claude_cli` recorded usage on the SUCCESS path only: `_record_claude_usage` sat
after the `is_error` check, after the empty-`result` check, and after the non-zero-exit
check. Every one of those paths costs exactly as much as a success — the API request is
already paid for by the time the payload exists — and every one of them was free in our own
books.

Measured 2026-08-06 (the daemon uses one cwd per call, so transcripts and `claude -p`
invocations are 1:1, which makes the comparison decisive):

    daemon calls with a costed transcript   1,926
    daemon calls in store/prospector.jsonl  1,568
    unrecorded                                358  (18.6%)  =  $104.89 in ONE day

$104.89 / 358 = $0.293 per call, against a $0.265 measured mean for calls that DID record —
these were real calls of ordinary size, not noise.

This is not a cost saving. It is the difference between a ledger and a guess, and
`spend.daily_subscription_cap_usd` (config.yaml:997) is now a real ceiling reading this leg:
a ceiling fed by a meter that under-counts by 18.6% halts 18.6% too late.
"""
from __future__ import annotations

import json

import pytest

from prospector import claude_cli


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FreeSlot:
    """Never blocks, never touches disk — so the suite does not compete with the live
    daemon for real CLI slots (see tests/unit/test_claude_cli_failure_reason.py)."""
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


@pytest.fixture(autouse=True)
def _no_governor(monkeypatch):
    monkeypatch.setattr(claude_cli, "_CLI_SEM", _FreeSlot())


@pytest.fixture
def recorded(monkeypatch):
    """Capture every `_record_claude_usage` call instead of writing the real ledger."""
    calls: list[dict] = []
    monkeypatch.setattr(claude_cli, "_record_claude_usage",
                        lambda data, web: calls.append(data))
    return calls


def _run_returning(monkeypatch, proc: _FakeProc):
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda cmd, **kw: proc)


USAGE = {"input_tokens": 12, "output_tokens": 34, "cache_read_input_tokens": 10_400}
BILLED = {"usage": USAGE, "total_cost_usd": 0.293}


def _attempt():
    return claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)


def test_is_error_result_is_still_recorded(monkeypatch, recorded):
    """The largest leg of the 18.6%: a well-formed payload we then reject.
    Before the fix this raised straight past the meter."""
    _run_returning(monkeypatch, _FakeProc(0, stdout=json.dumps({**BILLED, "is_error": True})))
    with pytest.raises(RuntimeError):
        _attempt()
    assert len(recorded) == 1
    assert recorded[0]["total_cost_usd"] == 0.293


def test_error_during_execution_is_recorded(monkeypatch, recorded):
    payload = {**BILLED, "subtype": "error_during_execution"}
    _run_returning(monkeypatch, _FakeProc(0, stdout=json.dumps(payload)))
    with pytest.raises(RuntimeError):
        _attempt()
    assert len(recorded) == 1


def test_empty_result_is_recorded(monkeypatch, recorded):
    """A blank `result` costs a full generation. It billed; it counts."""
    _run_returning(monkeypatch, _FakeProc(0, stdout=json.dumps({**BILLED, "result": ""})))
    with pytest.raises(RuntimeError):
        _attempt()
    assert len(recorded) == 1


def test_nonzero_exit_carrying_json_is_recorded(monkeypatch, recorded):
    """An exit code is not a promise about the payload."""
    _run_returning(monkeypatch, _FakeProc(1, stdout=json.dumps(BILLED)))
    with pytest.raises(RuntimeError):
        _attempt()
    assert len(recorded) == 1


def test_nonzero_exit_with_prose_records_nothing_and_does_not_crash(monkeypatch, recorded):
    """The normal refusal shape: prose on stdout, no usage block, nothing to bank.
    The meter must no-op silently rather than invent a row or raise."""
    _run_returning(monkeypatch, _FakeProc(1, stdout="Credit balance is too low"))
    with pytest.raises(RuntimeError) as e:
        _attempt()
    assert "Credit balance is too low" in str(e.value)
    assert recorded == []


def test_success_records_exactly_once(monkeypatch, recorded):
    """Regression guard on the fix itself: recording moved EARLIER, before the branch.
    If the old success-path call had been left in place, this would be 2 and every healthy
    call would double-count — an over-count halts the daemon early, which is the same class
    of failure in the opposite direction."""
    _run_returning(monkeypatch, _FakeProc(0, stdout=json.dumps({**BILLED, "result": "OK"})))
    assert _attempt() == "OK"
    assert len(recorded) == 1


def test_a_broken_meter_cannot_swallow_the_dead_brain_trace(monkeypatch):
    """The reason `_safe_record` exists. `looks_exhausted` reads the RuntimeError message to
    retire a spent brain (392ce4c). If the recorder raised, its exception would replace that
    message and the brain would be re-probed forever."""
    def boom(data, web):
        raise ValueError("ledger disk full")
    monkeypatch.setattr(claude_cli, "_record_claude_usage", boom)
    payload = {**BILLED, "is_error": True, "result": "Claude usage limit reached"}
    _run_returning(monkeypatch, _FakeProc(0, stdout=json.dumps(payload)))
    with pytest.raises(RuntimeError) as e:
        _attempt()
    assert "usage limit" in str(e.value)
    assert "ledger disk full" not in str(e.value)


def test_non_dict_payload_is_not_recorded(monkeypatch, recorded):
    """A JSON list is a valid parse and an invalid response; it must not reach the meter."""
    _run_returning(monkeypatch, _FakeProc(0, stdout="[1, 2, 3]"))
    with pytest.raises(RuntimeError):
        _attempt()
    assert recorded == []

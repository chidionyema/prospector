"""A dead moat must say WHY, in a string the exhaustion classifier can read.

`claude -p` prints its refusal on STDOUT, not stderr (measured 2026-08-06: an unfunded
ANTHROPIC_API_KEY makes it exit 1 with "Credit balance is too low" on stdout while stderr
carries only an unrelated connectors warning). `_attempt_claude_cli` used to build its error
from `proc.stderr` alone, so the daemon logged the empty `claude cli exit 1: ` for every
failure — and because `looks_exhausted("")` is False, the HEAD of MOAT_PRIMARY was never
marked exhausted and got re-probed on every single call.

The markers were never the problem: "credit balance is too low" and "usage limit" are both in
`errors._EXHAUSTION_MARKERS`. They simply never reached the classifier.
"""
from __future__ import annotations

import subprocess

import pytest

from prospector import claude_cli
from prospector.errors import ProviderExhaustedError, looks_exhausted


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FreeSlot:
    """Stand-in for the machine-wide flock governor: never blocks, never touches disk,
    so the suite does not compete with the live daemon for real CLI slots."""
    def acquire(self, timeout=None):
        return True

    def release(self):
        return None


@pytest.fixture(autouse=True)
def _no_governor(monkeypatch):
    monkeypatch.setattr(claude_cli, "_CLI_SEM", _FreeSlot())


def _run_returning(monkeypatch, proc: _FakeProc, seen: list | None = None):
    def fake_run(cmd, **kwargs):
        if seen is not None:
            seen.append(cmd)
        return proc
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)


CREDIT = "Credit balance is too low"
LIMIT = "Claude usage limit reached. Your limit will reset at 9pm."


def test_stdout_reason_reaches_the_error_message(monkeypatch):
    """The reason the CLI printed must survive into the exception the daemon logs."""
    _run_returning(monkeypatch, _FakeProc(1, stdout=CREDIT, stderr=""))
    with pytest.raises(RuntimeError) as e:
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)
    assert CREDIT in str(e.value)


def test_stdout_reason_is_visible_to_the_exhaustion_classifier(monkeypatch):
    """The point of carrying the reason: `looks_exhausted` can act on it.
    Before the fix the message was `claude cli exit 1: ` and this was False."""
    _run_returning(monkeypatch, _FakeProc(1, stdout=CREDIT, stderr=""))
    with pytest.raises(RuntimeError) as e:
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)
    assert looks_exhausted(str(e.value)) is True


def test_usage_limit_on_stdout_also_classifies(monkeypatch):
    """The subscription seat's own exhaustion shape, not just the metered-key one."""
    _run_returning(monkeypatch, _FakeProc(1, stdout=LIMIT, stderr=""))
    with pytest.raises(RuntimeError) as e:
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)
    assert looks_exhausted(str(e.value)) is True


def test_stderr_reason_still_reported(monkeypatch):
    """Regression guard: stderr was the ONLY stream before; it must not be dropped."""
    _run_returning(monkeypatch, _FakeProc(2, stdout="", stderr="segfault in tokenizer"))
    with pytest.raises(RuntimeError) as e:
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)
    assert "segfault in tokenizer" in str(e.value)
    assert "exit 2" in str(e.value)


def test_both_streams_are_carried_when_both_speak(monkeypatch):
    _run_returning(monkeypatch, _FakeProc(1, stdout=CREDIT, stderr="connectors disabled"))
    with pytest.raises(RuntimeError) as e:
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)
    msg = str(e.value)
    assert CREDIT in msg and "connectors disabled" in msg


def test_exhaustion_on_stdout_retires_the_brain_instead_of_retrying(monkeypatch):
    """The behaviour this bug actually cost us, end to end through run_claude_cli:
    a spent seat must raise ProviderExhaustedError on the FIRST attempt so the fallback
    layer retires it — not a plain RuntimeError re-probed on every call forever."""
    seen: list = []
    _run_returning(monkeypatch, _FakeProc(1, stdout=CREDIT, stderr=""), seen)
    monkeypatch.setattr(claude_cli.time, "sleep", lambda *_: None)
    with pytest.raises(ProviderExhaustedError):
        claude_cli.run_claude_cli("p", retries=2)
    assert len(seen) == 1          # one attempt, not retries+1 (=3)


def test_transient_failure_still_gets_its_full_retry_budget(monkeypatch):
    """No over-reach: a non-exhaustion exit must NOT be promoted to exhaustion."""
    seen: list = []
    _run_returning(monkeypatch, _FakeProc(1, stdout="connection reset by peer", stderr=""), seen)
    monkeypatch.setattr(claude_cli.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError) as e:
        claude_cli.run_claude_cli("p", retries=2)
    assert not isinstance(e.value, ProviderExhaustedError)
    assert len(seen) == 3


def test_success_path_unchanged(monkeypatch):
    """Guard rail: the failure-reporting change must not touch a healthy call."""
    ok = _FakeProc(0, stdout='{"result": "OK", "is_error": false, "usage": {}}')
    _run_returning(monkeypatch, ok)
    assert claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False) == "OK"


def test_timeout_is_not_swallowed(monkeypatch):
    """A hung CLI is a different failure from a refused one; it must still surface."""
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        claude_cli._attempt_claude_cli([claude_cli.CLAUDE_BIN, "-p", "x"], 5, False)

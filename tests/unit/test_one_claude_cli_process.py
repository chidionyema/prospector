"""ONE claude CLI process. Never four.

Founder directive 2026-08-20, verbatim: "for the last tine i donnt want 4 claude processes,
its epensive. this should never have happencd" / "1 cludclaude cli" / "not 4" / "this needs
to be enforce ruthlessly" / "i alredy wanred you about this".

This file is the "ruthlessly". A memory file is the floor, never the answer: the class here
is a knob that four different layers can turn -- config.yaml, the dashboard settings overlay,
PROSPECTOR_CLAUDE_CONCURRENCY and the dataclass default -- so a note on any one of them still
leaves three doors open. `claude_cli.MAX_CLAUDE_CLI` closes all four by clamping, and these
tests fail if the clamp is loosened at any layer.

The measurement that produced the directive, taken inside the prospector-engine container:
four concurrent `claude` Node runtimes (pids 4072, 4056, 4064, 4058) on a shared-cpu-2x slice
drove host steal to 91.7% with user at 6.8%. 20 of 34 console reads then hit a 30s ceiling;
importing console_api measured 6078ms under that load against 125ms on the same machine idle.
Money is the other half: each `claude -p` spends the subscription allowance, so four spend it
four times faster and hit usage_wall four times sooner, taking the failover chain with it.
"""
from __future__ import annotations

import pytest

from prospector import claude_cli
from prospector.cli_governor import make_governor
from prospector.config import load_config


@pytest.fixture(autouse=True)
def _private_slots(monkeypatch, tmp_path):
    """Never compete with the live daemon for the machine-wide slot files.

    claude's governor is backed by lock FILES under ~/.prospector/cli_slots, deliberately
    shared by every prospector process on this machine (cli_governor._slot_root). Without
    this the acquire below is graded against whatever the real scheduler is holding, which
    is how tests/faults/test_grounding_contention.py once blocked every commit in the estate.
    """
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "cli_slots"))
    monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
    original = claude_cli._MAX_CLI
    yield
    monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
    claude_cli.configure_concurrency(original)


def test_the_ceiling_is_one():
    assert claude_cli.MAX_CLAUDE_CLI == 1, (
        "founder directive 2026-08-20: one claude CLI process, not four")


def test_config_yaml_declares_one():
    assert load_config().retrieval.claude_concurrency == 1


def test_the_dataclass_default_is_one():
    from prospector.config import Retrieval

    assert Retrieval().claude_concurrency == 1


@pytest.mark.parametrize("asked", [2, 3, 4, 8, 40])
def test_config_cannot_raise_it(asked):
    """The path a config.yaml edit or a dashboard overlay write actually takes."""
    claude_cli.configure_concurrency(asked)
    assert claude_cli._MAX_CLI == 1, f"config asked for {asked} and got it"


@pytest.mark.parametrize("asked", ["2", "4", "8"])
def test_the_env_var_cannot_raise_it_either(monkeypatch, asked):
    """PROSPECTOR_CLAUDE_CONCURRENCY used to PIN the value and win outright.

    That made it the widest door of the four: an ops escape hatch that could put four
    runtimes back on the box without touching a tracked file. It still pins DOWNWARD -- a
    deployment may run fewer -- but it can no longer pin upward.
    """
    monkeypatch.setenv("PROSPECTOR_CLAUDE_CONCURRENCY", asked)
    claude_cli.configure_concurrency(1)
    assert claude_cli._MAX_CLI == 1


def test_a_junk_env_value_does_not_widen_it(monkeypatch):
    """Fail toward the ceiling, never away from it."""
    monkeypatch.setenv("PROSPECTOR_CLAUDE_CONCURRENCY", "lots")
    claude_cli.configure_concurrency(4)
    assert claude_cli._MAX_CLI == 1


def test_the_governor_actually_refuses_a_second_process():
    """The assertions above grade a number. This one grades the machine.

    A clamped integer that never reached the semaphore would pass every test above and still
    let four subprocesses run, which is the exact shape of failure this file exists for: the
    slot files ARE the ceiling, so the second acquire has to come back False.
    """
    claude_cli.configure_concurrency(4)
    sem = make_governor(claude_cli._MAX_CLI, "claude_one_process_test")
    assert sem.acquire(timeout=1), "the first process must get the slot"
    try:
        assert not sem.acquire(timeout=0.2), "a SECOND claude CLI process got a slot"
    finally:
        sem.release()

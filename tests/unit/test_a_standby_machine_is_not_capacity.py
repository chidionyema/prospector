"""A standby machine registers as a runner and can never hold a job. Grade it as a fault.

WHAT HAPPENED. On 2026-08-19 CI had been failing all day with builds dying as "The self-hosted
runner lost communication with the server", which reads as a flaky test. Ten of prospector-ci's
twelve machines were STANDBYS, cloned from 8e4530a7712248 by `fly machine clone`. On an app with
no services a clone is created as a standby of its source: it exists to take over only if the
source machine's HOST fails, so Fly stops it again whenever anything starts it.

Every instrument agreed and every instrument was wrong. `fly machine list` said 12 machines.
`fly status` said 12. GitHub said 11 registered runners, because the standbys DO register while
briefly started. The number that could actually hold a build was 2. The standbys took jobs and
were then stopped mid-build by Fly, through the Machines API, which the machine event log records
as `stop | user` — indistinguishable from a person or a script, which is why hours went into
hunting a caller that did not exist.

THE CLASS: an action whose result looks like capacity on every instrument and is not. The only
field that tells the truth is the machine's CONFIG, because state is the one thing a standby gets
right. So the probe reads config, and this test is what keeps it reading config.

The matching refusal lives in ~/.claude/scripts/rule-guard.py (`rule_clone_makes_a_standby`), so
no agent session on the box can create one; this test is the half that survives a fresh machine
and a clone made from the Fly dashboard, where no hook can see it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "ci_fleet_probe.py"


def _load():
    spec = importlib.util.spec_from_file_location("ci_fleet_probe", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _machine(mid: str, state: str = "started", standby_for: list[str] | None = None) -> dict:
    """The shape `fly machine list --json` returns, trimmed to what grade() reads."""
    return {"id": mid, "state": state, "region": "lhr",
            "config": {"standbys": list(standby_for)} if standby_for else {}}


def _grade(monkeypatch, machines: list[dict]) -> dict:
    """Run grade() against a fabricated fleet. No network, no flyctl, no gh."""
    mod = _load()

    def fake_json(cmd, timeout=45):
        joined = " ".join(str(c) for c in cmd)
        if "machine list" in joined:
            return machines, ""
        if "secrets list" in joined:
            return [{"Name": "GITHUB_RUNNER_PAT"}], ""
        if "actions/runners" in joined:
            # One online runner per started machine, standbys included: they really do
            # register, which is the whole reason the count looked healthy.
            return [{"status": "online", "busy": False}
                    for m in machines if m.get("state") == "started"], ""
        if "status=queued" in joined:
            return {"n": 0}, ""
        return [], ""

    monkeypatch.setattr(mod, "_json_out", fake_json)
    return mod.grade({"app": "prospector-ci", "repo": "chidionyema/prospector"},
                     fly="/usr/bin/fly", gh="/usr/bin/gh")


def test_a_started_standby_is_reported_as_a_fault(monkeypatch):
    """It is started, it registers, and it still cannot hold a job. That is a problem."""
    out = _grade(monkeypatch, [_machine("aaa"), _machine("bbb", standby_for=["aaa"])])

    assert out["standbys"] == ["bbb"], (
        "the probe must name which machines are standbys; the whole failure was that no "
        "instrument distinguished them"
    )
    joined = " ".join(out["problems"])
    assert "STANDBY" in joined.upper(), (
        f"a standby must be graded a PROBLEM, not a note. problems={out['problems']}"
    )


def test_usable_capacity_excludes_standbys(monkeypatch):
    """`started` counted 12 while 2 could work. `usable` is the number that does not lie."""
    machines = [_machine("aaa"), _machine("ccc")] + [
        _machine(f"sb{i}", standby_for=["aaa"]) for i in range(10)
    ]
    out = _grade(monkeypatch, machines)

    assert out["started"] == 12, "all twelve really are in the started state"
    assert out["usable"] == 2, (
        f"real capacity was 2, not 12 — usable={out['usable']}. This exact gap is what cost "
        f"2026-08-19: every count on every screen said 12."
    )


def test_a_fleet_with_no_standbys_is_not_faulted(monkeypatch):
    """The check must be silent on a healthy fleet, or it will be ignored on a sick one."""
    out = _grade(monkeypatch, [_machine("aaa"), _machine("bbb")])

    assert out["standbys"] == []
    assert out["usable"] == 2
    assert not any("standby" in p.lower() for p in out["problems"]), (
        f"a healthy fleet must raise no standby problem. problems={out['problems']}"
    )


def test_the_problem_carries_the_repair_command(monkeypatch):
    """A fault that does not say how to fix it costs another session to re-derive."""
    out = _grade(monkeypatch, [_machine("aaa"), _machine("bbb", standby_for=["aaa"])])

    joined = " ".join(out["problems"])
    assert "--standby-for" in joined, (
        f"the repair command must be in the message. problems={out['problems']}"
    )
    assert "bbb" in joined, "the repair command must name the machine that needs repairing"


@pytest.mark.parametrize("state", ["stopped", "created", "suspended"])
def test_a_standby_counts_as_a_standby_whatever_its_state(monkeypatch, state):
    """Fly stops standbys, so most of the time they are found stopped. Config decides, not state."""
    out = _grade(monkeypatch, [_machine("aaa"), _machine("bbb", state=state, standby_for=["aaa"])])

    assert out["standbys"] == ["bbb"], (
        f"a {state} standby is still a standby; reading state instead of config is the bug"
    )

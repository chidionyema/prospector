"""The fleet keeper starts stopped CI machines, and cannot be quietly turned into a no-op.

These pin the 2026-08-19 outage: ten of twelve `prospector-ci` machines sat `stopped` for
hours, capacity was 2/12, `main`'s CI run queued and never got a machine, and every check in
the estate graded the fleet as fine because the declared floor was 2.

Two of these tests are guards rather than unit tests. `test_the_keeper_never_runs_on_the_fleet
_it_heals` and `test_the_floor_that_notices_is_above_the_floor_that_collapsed` fail if someone
undoes the fix in the obvious, well-meaning way -- by making the workflow match every other
workflow, or by folding the new floor back onto the old one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _keeper():
    spec = importlib.util.spec_from_file_location("ci_fleet_keeper",
                                                  ROOT / "scripts/ci_fleet_keeper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _keeper()


def _m(mid, state):
    return {"id": mid, "state": state}


# --------------------------------------------------------------------------- #
# What to start
# --------------------------------------------------------------------------- #
def test_the_outage_of_2026_08_19_is_repaired_to_the_floor_and_no_further():
    """Ten of twelve stopped, floor 6: start four, not ten.

    Starting all ten would work and would also quietly quadruple the bill. The floor is the
    number the estate can justify paying for; growing past it is `deploy/runners.sh up`.
    """
    fleet = [_m(f"m{i}", "started") for i in range(2)] + \
            [_m(f"m{i}", "stopped") for i in range(2, 12)]
    p = K.plan(fleet, floor=6)
    assert p["started"] == 2 and p["total"] == 12
    assert p["short"] == 4
    assert len(p["start"]) == 4
    assert p["ok"] is False


def test_a_healthy_fleet_starts_nothing_so_two_overlapping_runs_cannot_fight():
    p = K.plan([_m(f"m{i}", "started") for i in range(8)], floor=6)
    assert p["start"] == [] and p["ok"] is True and p["short"] == 0


def test_a_machine_that_is_already_started_is_never_in_the_start_list():
    """Fly's start is idempotent, so sending it would be harmless -- and the report would lie.

    "STARTED m0" for a machine that was already running is the kind of line that sends the next
    reader looking for a fault that never existed.
    """
    p = K.plan([_m("m0", "started"), _m("m1", "stopped")], floor=2)
    assert p["start"] == ["m1"]


def test_an_app_with_no_machines_is_impossible_rather_than_silently_fine():
    """Zero machines is not zero work. Starting cannot help; something has to create them."""
    p = K.plan([], floor=6)
    assert p["impossible"] is True
    assert p["start"] == []


def test_states_other_than_started_all_count_as_down():
    """`stopped` is what we saw; `suspended`, `failed` and `created` are equally unable to work."""
    fleet = [_m("a", "stopped"), _m("b", "suspended"), _m("c", "failed"), _m("d", "created")]
    assert K.plan(fleet, floor=4)["short"] == 4


# --------------------------------------------------------------------------- #
# What to reap
# --------------------------------------------------------------------------- #
def test_only_an_offline_busy_runner_is_a_phantom():
    """Both halves of the test are load-bearing, and dropping either one destroys capacity.

    An ONLINE busy runner is doing its job -- deregistering it kills a live build, which is the
    exact failure the phantoms came from. An OFFLINE idle runner is just a stopped machine, and
    `plan()` fixes that by starting it.
    """
    runners = [
        {"id": 1, "name": "live",    "status": "online",  "busy": True},
        {"id": 2, "name": "idle",    "status": "online",  "busy": False},
        {"id": 3, "name": "stopped", "status": "offline", "busy": False},
        {"id": 4, "name": "phantom", "status": "offline", "busy": True},
    ]
    assert [r["name"] for r in K.phantoms(runners)] == ["phantom"]


# --------------------------------------------------------------------------- #
# Reading the contract
# --------------------------------------------------------------------------- #
def test_the_app_name_is_read_from_the_runners_own_fly_toml():
    assert K.read_app() == "prospector-ci"


def test_the_floor_comes_from_the_contract_not_from_the_code():
    declared = yaml.safe_load((ROOT / "ops/config/ci_capacity.yaml").read_text())
    assert K.read_floor() == declared["fleet"]["min_started"]


def test_a_contract_without_the_key_falls_back_rather_than_crashing(tmp_path):
    """The keeper must still run against an older checkout; a missing key is not an outage."""
    p = tmp_path / "c.yaml"
    p.write_text("box:\n  cpus: 4\n")
    assert K.read_floor(p) == K.DEFAULT_MIN_STARTED
    assert K.read_floor(tmp_path / "absent.yaml") == K.DEFAULT_MIN_STARTED


# --------------------------------------------------------------------------- #
# The two guards
# --------------------------------------------------------------------------- #
def test_the_keeper_runs_where_this_estate_actually_has_compute():
    """It ran on `ubuntu-latest` until 2026-08-20, and that was a correct argument about a
    runner this account does not have.

    The argument was: a self-hosted runner cannot start a dead self-hosted fleet, so the keeper
    must sit somewhere else. Sound, and moot. A GitHub-hosted job cannot start here at all --
    run 32343624520 concluded `failure` having run ZERO steps, its log 404s, and the only record
    anywhere is the annotation "The job was not started because recent account payments have
    failed or your spending limit needs to be increased." The founder has ruled that this is
    permanent: we are not paying GitHub. So the real choice was fleet-versus-nothing, plus an
    hourly red main that no code change could clear.

    What the move costs is one case, named honestly: a TOTAL fleet outage, where no machine is
    left to pick the job up. Partial outages -- some machines stopped, others alive -- are the
    common case and are what this now repairs unattended. `scripts/ci_fleet_keeper.py` talks to
    https://api.machines.dev/v1 and never inspects the box it runs on, so even a runner started
    from a stale image heals the fleet correctly.

    A hosted runner in ANY job of this file is the regression to catch: it would look like a
    tidy restoration of the old argument and would silently be a job that cannot start.
    """
    wf = yaml.safe_load((ROOT / ".github/workflows/ci-fleet-keeper.yml").read_text())
    for name, job in wf["jobs"].items():
        assert "ubuntu-latest" not in str(job["runs-on"]), (
            f"job `{name}` asks for a GitHub-hosted runner. This account cannot start one: the "
            f"job concludes `failure` with zero steps and no log, which reads as nothing at all. "
            f"Target the fleet -- vars.CI_LIGHT_RUNS_ON || vars.CI_RUNS_ON || 'fly'."
        )
    assert "CI_RUNS_ON" in str(wf["jobs"]["keep"]["runs-on"]), (
        "the keeper must target the pool this estate owns, by variable rather than by a "
        "hardcoded label, so the fleet can be renamed without editing every workflow"
    )


def test_the_keeper_is_not_parked_behind_a_switch_nobody_will_flip():
    """A gate on a repository variable was the wrong ending, and this is the test that says so.

    Between 2026-08-20 09:00 and 12:30 this workflow carried
    `if: vars.HOSTED_RUNNERS_AVAILABLE == 'yes'`, so it SKIPPED instead of failing. That stopped
    the red and it also stopped the repair, for ever: the variable was only ever going to be set
    after paying GitHub, and the founder's answer to that is no. A check parked behind a switch
    nobody will flip is a check the estate has lost while still carrying its file, its tests and
    its name on the workflow list.

    There are two honest endings for a job that cannot run where it was written: move it to
    compute we own, or delete it. This one moved.
    """
    wf = yaml.safe_load((ROOT / ".github/workflows/ci-fleet-keeper.yml").read_text())
    text = (ROOT / ".github/workflows/ci-fleet-keeper.yml").read_text()
    for name, job in wf["jobs"].items():
        assert "if" not in job, (
            f"job `{name}` is gated by `if: {job.get('if')}`. If it cannot run, move it or "
            f"delete it -- do not park it behind a condition and leave the file looking alive."
        )
    assert "HOSTED_RUNNERS_AVAILABLE" not in text, (
        "that variable was the parking gate and is gone. Nothing should reference it: it would "
        "read as a switch somebody could flip, and there is no plan under which anybody does."
    )
    assert "api.machines.dev" in (ROOT / "scripts/ci_fleet_keeper.py").read_text(), (
        "the reason the keeper can run on the fleet at all is that it asks Fly's API rather "
        "than the machine it is running on. If that stops being true, this move stops being safe."
    )


def test_the_workflow_has_a_trigger_github_will_actually_honour():
    """`on:` is the boolean True under YAML 1.1, and a webhook name is not a trigger.

    `.github/workflows/ci-autoscale.yml` used `on: workflow_job`, which GitHub rejects outright:
    35 of its 40 runs were push startup-failures with zero jobs, so it never executed a single
    step and nothing anywhere was red. A workflow GitHub cannot start reports nothing.
    """
    doc = yaml.safe_load((ROOT / ".github/workflows/ci-fleet-keeper.yml").read_text())
    triggers = doc.get("on", doc.get(True))
    assert set(triggers) <= {"schedule", "workflow_dispatch", "push", "pull_request",
                             "workflow_call"}
    assert "schedule" in triggers, "a keeper nobody schedules is a report nobody reads"


def test_the_floor_that_notices_is_above_the_floor_that_collapsed():
    """The whole lesson of 2026-08-19, as an assertion.

    `autoscale_min` and `pools.*.runners` were both 2, so a fleet at 2 of 12 graded as healthy.
    A floor set to the minimum survivable number cannot detect a collapse to the minimum
    survivable number. If someone ever folds `fleet.min_started` back onto those numbers, this
    fails and says why.
    """
    c = yaml.safe_load((ROOT / "ops/config/ci_capacity.yaml").read_text())
    floor = c["fleet"]["min_started"]
    assert floor > c["autoscale_min"], (
        f"fleet.min_started ({floor}) must exceed autoscale_min ({c['autoscale_min']}); "
        "equal numbers is what made the 2/12 collapse invisible"
    )
    for pool, spec in c["pools"].items():
        assert floor > spec["runners"], (
            f"fleet.min_started ({floor}) must exceed pools.{pool}.runners ({spec['runners']})"
        )


def test_the_keeper_is_a_button_on_the_ops_console():
    """Founder directive 2026-08-19: everything running must be visible from the ops dashboard."""
    from prospector.ops import console_api as capi
    paths = {t["path"] for t in capi.TOOLS}
    assert "scripts/ci_fleet_keeper.py" in paths

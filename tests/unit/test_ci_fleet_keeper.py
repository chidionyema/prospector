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

import pytest
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
def test_the_keeper_never_runs_on_the_fleet_it_heals():
    """A self-hosted runner cannot start a dead self-hosted fleet.

    Every other workflow here targets the `fly` pool, so making this one match is the obvious
    tidy-up -- and it would make the keeper unable to run in exactly the situation it exists
    for: no runner is left to pick the job up.
    """
    wf = yaml.safe_load((ROOT / ".github/workflows/ci-fleet-keeper.yml").read_text())
    for name, job in wf["jobs"].items():
        assert job["runs-on"] == "ubuntu-latest", (
            f"job {name} must stay on a GitHub-hosted runner; a self-hosted runner cannot "
            "start a dead self-hosted fleet"
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

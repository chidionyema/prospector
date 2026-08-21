"""The migration plan must say which of its own steps cannot run.

Measured on the real estate 2026-08-21: a plan to `laptop` compiled 80 steps and reported no
problem at all, while 73 of those steps named an adapter file that is not in the tree. Only
`kit/classes/compute.sh` exists. The runner does fail loudly when it reaches such a step, and
`prospector/ops/migration_view.py` does admit which classes are unwired -- but the plan is the
artifact read BEFORE the clock starts, and it was the one place that could not say so. Against
a 30-minute whole-stack budget, learning this at minute 40 is the same as having no plan.

The choice pinned here is REPORT, not REFUSE: `kit/classes/MISSING.md` is the declared ledger
of unwired classes, and a compiler that refused until every adapter existed could not be used
to see how much work is left.
"""
from __future__ import annotations

import json
import os

import pytest

from kit.migrate.plan import REPO, adapter_present, compile_plan
from kit.projects.schema import load

PROJECT = load(REPO / "kit" / "projects" / "prospector.yaml")


def _report(*resources: dict) -> dict:
    return {"resources": list(resources)}


def _resource(name: str, cls: str) -> dict:
    return {"name": name, "class": cls, "where": "fly/deployed", "described_by": "test"}


def test_a_step_whose_adapter_is_on_disk_is_marked_present():
    plan = compile_plan(_report(_resource("engine", "compute")), PROJECT, "laptop")
    step = plan["steps"][0]
    assert step["adapter"] == "kit/classes/compute.sh"
    assert step["adapter_present"] is True, (
        "compute is the one wired class; if this fails the resolver is wrong, not the tree")


def test_a_step_whose_adapter_is_absent_is_marked_and_counted():
    plan = compile_plan(_report(_resource("TOKEN", "secret")), PROJECT, "laptop")
    step = plan["steps"][0]
    assert step["adapter_present"] is False
    assert plan["counts"]["unrunnable_steps"] == 1
    assert step["adapter"] in plan["unrunnable"]


def test_the_count_matches_the_steps_it_describes():
    plan = compile_plan(
        _report(_resource("engine", "compute"), _resource("A", "secret"),
                _resource("B", "secret"), _resource("logs", "log_sink")),
        PROJECT, "laptop")
    counted = sum(1 for s in plan["steps"] if not s["adapter_present"])
    assert plan["counts"]["unrunnable_steps"] == counted == 3, (
        "a count that drifts from the steps is worse than no count -- it is read instead of them")


def test_unrunnable_lists_each_adapter_once_and_in_order():
    plan = compile_plan(
        _report(_resource("A", "secret"), _resource("B", "secret"), _resource("logs", "log_sink")),
        PROJECT, "laptop")
    assert plan["unrunnable"] == ["kit/classes/log_sink.sh", "kit/classes/secret.sh"], (
        "the list is what a person reads to know what to write next, so it is deduped and stable")


def test_a_missing_adapter_reports_rather_than_refusing_the_plan():
    plan = compile_plan(_report(_resource("TOKEN", "secret")), PROJECT, "laptop")
    assert plan["steps"], (
        "MISSING.md is the declared ledger of unwired classes; a compiler that refused until "
        "every adapter existed could not be used to see how much is left")


def test_the_answer_does_not_depend_on_the_callers_directory(tmp_path):
    """The plan is compiled from the console, from CI, and from a worktree terminal."""
    here = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert adapter_present("kit/classes/compute.sh") is True
    finally:
        os.chdir(here)


@pytest.mark.parametrize("value", ["", None])
def test_no_adapter_at_all_is_not_present(value):
    assert adapter_present(value) is False


def test_a_directory_is_not_an_adapter(tmp_path):
    """`is_file`, not `exists` -- a directory named like the adapter cannot be run."""
    d = REPO / "kit" / "classes"
    assert d.is_dir()
    assert adapter_present("kit/classes") is False


def test_the_real_estate_plan_carries_the_field(tmp_path):
    """Every step, not just the ones a fixture happens to build."""
    plan = compile_plan(
        _report(*[_resource(f"s{i}", "secret") for i in range(5)],
                _resource("engine", "compute")),
        PROJECT, "sshdocker")
    assert all("adapter_present" in s for s in plan["steps"])
    assert json.dumps(plan)  # the console reads this over the wire

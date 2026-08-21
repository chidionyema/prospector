"""The migration plan must say which of its own steps cannot run.

Measured on the real estate 2026-08-21: a plan to `laptop` compiled 80 steps and reported no
problem at all, while 73 of those steps named an adapter file that is not in the tree -- at the time
one adapter existed. The runner does fail loudly when it reaches such a step, and
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
import re
from dataclasses import replace

import pytest

from kit.migrate.plan import REPO, adapter_present, compile_plan
from kit.projects.schema import CLASS_ADAPTERS, load

PROJECT = load(REPO / "kit" / "projects" / "prospector.yaml")


def _unwired(*classes: str):
    """The same project, with those classes pointed at an adapter that cannot be on disk.

    The three tests below used to pin `secret` as the absent one, which was true the day they
    were written and false the day `kit/classes/secret.sh` landed. A test that names today's
    unwired class is grading the tree, not the compiler, and it fails on the commit that fixes
    the thing it was protecting. The behaviour under test is "a step whose adapter file is not
    there is marked and counted", and that has to hold after all ten adapters exist.
    """
    classes_ = dict(PROJECT.classes)
    for name in classes:
        decl = classes_[name]
        classes_[name] = replace(decl, adapter=f"{decl.adapter}.absent")
    return replace(PROJECT, classes=classes_)


def _missing_ledger() -> list[str]:
    """The classes `kit/classes/MISSING.md` declares unwired, read from the file itself."""
    text = (REPO / "kit" / "classes" / "MISSING.md").read_text()
    return re.findall(r"^- `([a-z_]+)`", text, re.MULTILINE)


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
    plan = compile_plan(_report(_resource("TOKEN", "secret")), _unwired("secret"), "laptop")
    step = plan["steps"][0]
    assert step["adapter_present"] is False
    assert plan["counts"]["unrunnable_steps"] == 1
    assert step["adapter"] in plan["unrunnable"]


def test_the_count_matches_the_steps_it_describes():
    plan = compile_plan(
        _report(_resource("engine", "compute"), _resource("A", "secret"),
                _resource("B", "secret"), _resource("logs", "log_sink")),
        _unwired("secret", "log_sink"), "laptop")
    counted = sum(1 for s in plan["steps"] if not s["adapter_present"])
    assert plan["counts"]["unrunnable_steps"] == counted == 3, (
        "a count that drifts from the steps is worse than no count -- it is read instead of them")


def test_unrunnable_lists_each_adapter_once_and_in_order():
    plan = compile_plan(
        _report(_resource("A", "secret"), _resource("B", "secret"), _resource("logs", "log_sink")),
        _unwired("secret", "log_sink"), "laptop")
    assert plan["unrunnable"] == ["kit/classes/log_sink.sh.absent", "kit/classes/secret.sh.absent"], (
        "the list is what a person reads to know what to write next, so it is deduped and stable")


def test_the_real_tree_agrees_with_the_missing_ledger():
    """The one test here that IS about the tree, and it reads the ledger instead of naming a class.

    `kit/classes/MISSING.md` is the declared list of unwired classes and `tests/e2e/` already
    fails when it drifts from disk. This ties the third artifact to the same fact: what the plan
    calls unrunnable is exactly what the ledger says is not written yet. It self-updates as
    adapters land, so it cannot go stale the way the pinned-class version did.
    """
    declared = sorted(PROJECT.classes)
    plan = compile_plan(
        _report(*[_resource(f"r-{cls}", cls) for cls in declared]), PROJECT, "laptop")
    expected = sorted(CLASS_ADAPTERS[cls] for cls in _missing_ledger())
    assert plan["unrunnable"] == expected, (
        "the plan and MISSING.md disagree about which classes are wired; one of them is lying "
        "to whoever reads it before starting the clock")


def test_a_missing_adapter_reports_rather_than_refusing_the_plan():
    plan = compile_plan(_report(_resource("TOKEN", "secret")), _unwired("secret"), "laptop")
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

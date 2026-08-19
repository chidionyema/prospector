"""A PR must not build while main is red, and main's redness must be visible.

Founder directive 2026-08-19: "i dont see hwy any pr should run when nain is red" and
"this nust be visibke so it can be fied as priority".

The incident this pins. Main was red on one test. Twenty-one PR runs were queued ahead of
main's own fix run on three live runners, so main could not get a machine, and every queued
run was doomed to fail on main's defect after ~26 minutes of a heavy runner. Nothing in the
workflow expressed that main's colour outranks every PR's.

These tests fail if the gate is removed, moved off the first step, loses its escape hatch,
or stops failing open.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
GATE = "Main must be green before any PR builds"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(CI.read_text())


@pytest.fixture(scope="module")
def gate(workflow):
    steps = workflow["jobs"]["changes"]["steps"]
    assert steps, "the changes job has no steps"
    assert steps[0].get("name") == GATE, (
        "the main-is-red gate must be the FIRST step of `changes`. Anything ahead of it is "
        f"work spent on a PR that cannot pass. First step is {steps[0].get('name')!r}."
    )
    return steps[0]


def test_the_gate_only_stops_pull_requests(gate):
    """A push to main and a workflow_dispatch must never be gated on main's own colour."""
    cond = " ".join(gate["if"].split())
    assert "github.event_name == 'pull_request'" in cond, (
        "the gate must apply to pull_request events only — gating main's own run on main's "
        f"colour deadlocks the repo. Condition: {cond!r}"
    )


def test_the_pr_that_fixes_main_can_still_build(gate):
    """The `fixes-main` hatch must be read LIVE, never from the frozen event payload.

    `github.event.pull_request.labels` is a snapshot taken when the run started. Measured
    2026-08-19: this gate refused PR #443 — the PR that carries the gate and fixes main —
    because the label arrived ninety seconds after the run did. A hatch that is shut at the
    moment it is needed is not a hatch. Founder: "this should obviosly eclude nain, basi
    edge case".
    """
    assert "github.event.pull_request.labels" not in gate["if"], (
        "the frozen event payload must not decide the hatch"
    )
    script = gate["with"]["script"]
    assert "listLabelsOnIssue" in script
    assert "labels.includes('fixes-main')" in script


def test_the_gate_reads_mains_last_completed_run(gate):
    script = gate["with"]["script"]
    assert "listWorkflowRuns" in script
    assert "branch: 'main'" in script
    assert "status: 'completed'" in script, (
        "an in-progress run has conclusion null; grading it would block every PR whenever "
        "main happens to be mid-build"
    )


def test_the_gate_fails_open(gate):
    """A gate that blocks the whole repo on its own bug is worse than the problem it polices."""
    script = gate["with"]["script"]
    assert "core.warning" in script, "an API error must warn and pass, not fail"
    assert "catch (e)" in script, "the API call must be wrapped so a transport error fails open"
    assert "if (!latest)" in script, "a main with no completed CI run at all must fail open"


def test_the_gate_names_main_as_the_priority_and_says_how_to_proceed(gate):
    """'this nust be visibke so it can be fied as priority' — the message is the visibility."""
    script = gate["with"]["script"]
    assert "FIX MAIN FIRST" in script, "the failure must name main as the top priority"
    assert "latest.html_url" in script, "the failure must link the failing run on main"
    assert "core.summary" in script, (
        "the verdict must reach the run summary page, not only the step log"
    )
    assert "core.setFailed" in script, "the gate must actually fail the job"


@pytest.mark.parametrize("job", ["python", "engine", "dotnet", "nextjs", "ops-console"])
def test_every_heavy_job_is_stopped_by_the_gate(workflow, job):
    """The gate only saves runner time if the expensive jobs cannot start without `changes`."""
    needs = workflow["jobs"][job]["needs"]
    needs = [needs] if isinstance(needs, str) else needs
    assert "changes" in needs, (
        f"{job} does not declare `needs: changes`, so it would build even after the "
        "main-is-red gate refused the run"
    )


def test_main_mid_run_also_stops_a_pr_build(gate):
    """A PR must not take a runner while main's own CI is queued or running.

    Measured 2026-08-19: main's five heavy jobs sat queued while eight of eleven runners ran
    PR jobs, and the starvation was self-sustaining — every runner a PR job freed was taken
    by the next queued PR job. Founder: "nain should be priority over feaature branches ...
    this should never happen".
    """
    script = gate["with"]["script"]
    assert "'in_progress'" in script and "'queued'" in script
    assert "main gets the machines before any feature branch" in script


def test_the_mid_run_check_runs_before_the_green_check(gate):
    """An in-flight main run is the more urgent fact, and a stale green would hide it."""
    script = gate["with"]["script"]
    assert script.index("CHECK 1") < script.index("CHECK 2")


def test_a_wedged_main_run_does_not_block_the_whole_repo(gate):
    """A main run stuck queued for hours is broken, not in flight.

    Without the age filter, one wedged run would stop every PR in the repo — a bigger outage
    than the one the gate exists to prevent.
    """
    script = gate["with"]["script"]
    assert "STALE_MINUTES" in script
    assert "run_started_at" in script


def test_the_mid_run_check_fails_open(gate):
    """A gate that cannot read GitHub must let work through, not become a second outage."""
    script = gate["with"]["script"]
    assert "Could not read main's live runs" in script
    assert "active = []" in script

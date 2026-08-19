"""A merge must not strand every PR it did not merge.

`.github/workflows/automerge.yml` fires on `workflow_run: [completed]` and acts only on the PRs
whose head is that run's sha (`listPullRequestsAssociatedWithCommit`). That scoping is
deliberate and correct -- it is what stops a green verdict merging code the verdict never
covered. Its side effect was not planned for: the merge moves main, so every OTHER open PR is
now behind main, and nothing will ever run CI on them again. Automerge never fires for them, so
they sit open and green forever and no check anywhere goes red.

Measured 2026-08-19, with 28 PRs open and nothing merging: #388, #405, #424, #431 and #442 were
each MERGEABLE/CLEAN with every check SUCCESS and `behind_by == 2`, untouched for hours. The
queue starves itself, one stranded PR per merge.

The fix is a post-merge sweep that updates the branches of PRs that are green AND behind, which
dispatches CI on them, which brings them back through this same job. These tests are what fails
if that sweep is removed, silenced, or has its dispatch dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "automerge.yml"

# `pulls.list` is a PREFIX of `pulls.listFiles`, which the merge loop calls first. Anchoring
# the "after the merge" assertions on the short form found the merge loop and read it as the
# sweep, so two tests passed against code that was not the code under test. The comma is the
# only thing that distinguishes the two calls.
SWEEP_ANCHOR = "github.rest.pulls.list,"

# Where the sweep STOPS. Slicing to end-of-file instead let the post-merge `dispatching CI on
# main` call satisfy "the sweep dispatches CI": deleting the sweep's own dispatch left all
# nine tests green, which is precisely the silent-rescue bug they exist to catch.
SWEEP_END = "dispatching CI on main"


@pytest.fixture(scope="module")
def source() -> str:
    assert WORKFLOW.exists(), f"{WORKFLOW} is gone"
    return WORKFLOW.read_text()


@pytest.fixture(scope="module")
def script(source: str) -> str:
    """The inline github-script body, with comment lines stripped.

    The sweep's own comments quote the API calls they explain, so a test that searched the raw
    text would find `updateBranch` in prose and call the feature present after someone deleted
    the code.
    """
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))


@pytest.fixture(scope="module")
def sweep(script: str) -> str:
    """Just the post-merge sweep block, bounded at both ends."""
    start = script.index(SWEEP_ANCHOR)
    return script[start : script.index(SWEEP_END, start)]


def test_the_workflow_is_valid_yaml(source: str) -> None:
    assert yaml.safe_load(source), "automerge.yml does not parse"


def test_the_sweep_exists_and_looks_at_every_open_pr(script: str) -> None:
    """The bug was scope. The rescue has to read PRs this run was never told about."""
    assert SWEEP_ANCHOR in script, (
        "the post-merge sweep is gone. Without it a merge strands every other green PR: "
        "automerge only ever sees the PRs at the completed run's sha, so a PR that falls "
        "behind main has no future run to rescue it and stays open forever."
    )
    assert re.search(r"state:\s*'open'", script), "the sweep no longer asks for OPEN pull requests"


def test_the_sweep_runs_only_after_a_merge_landed(script: str) -> None:
    """Nothing is stranded until main moves. Sweeping on a run that merged nothing would
    dispatch CI for no reason, on a fleet whose scarcity is the whole problem."""
    guard = script.index("if (!merged) return")
    assert script.index(SWEEP_ANCHOR) > guard, "the sweep now runs even when no merge happened"


def test_the_sweep_updates_the_branch_and_dispatches_ci(sweep: str) -> None:
    """An update alone is silent. A push made with GITHUB_TOKEN starts no workflow run, so
    without the dispatch the PR is updated, no CI runs, automerge never fires, and the PR is
    exactly as stuck as before -- with a misleading new commit on it."""
    assert "github.rest.pulls.updateBranch" in sweep, "the sweep no longer updates the branch"
    assert "createWorkflowDispatch" in sweep, (
        "the sweep updates the branch but dispatches nothing. A GITHUB_TOKEN push starts no "
        "run, so the rescue would be silent and the PR would stay stranded."
    )
    assert "expected_head_sha" in sweep, (
        "the sweep no longer pins the head it saw, so it can update a branch someone pushed to "
        "while this job was deciding"
    )


def test_the_sweep_skips_pull_requests_that_are_not_green(sweep: str) -> None:
    """A red PR is not stranded on us. Updating it spends a CI run to re-prove a failure its
    author already has to fix."""
    assert "checks.listForRef" in sweep, (
        "the sweep no longer reads check runs, so it can rescue a red PR"
    )
    for verdict in ("'success'", "'skipped'"):
        assert verdict in sweep, f"the green test no longer accepts {verdict}"
    assert "mergeable_state" not in sweep, (
        "mergeable_state is computed lazily and answers `unknown` on a first read, so using it "
        "would skip exactly the PRs the sweep exists to rescue"
    )


def test_the_sweep_skips_pull_requests_that_are_not_behind(sweep: str) -> None:
    assert "behind_by" in sweep, (
        "the sweep no longer checks behind_by, so it would update branches that are already "
        "current and dispatch CI runs for nothing"
    )


def test_the_sweep_respects_draft_and_the_hold_labels(sweep: str) -> None:
    assert "pr.draft" in sweep, "the sweep no longer skips drafts"
    assert "HOLD" in sweep, (
        "the sweep no longer honours the hold/do-not-merge/wip labels, so a held PR gets CI "
        "dispatched on it anyway"
    )


def test_the_sweep_is_capped_and_the_cap_is_configurable(source: str, sweep: str) -> None:
    """Each rescue dispatches a CI run that fans out to as many as seven jobs on a nine-machine
    fleet. An uncapped sweep across 28 open PRs would queue main's own post-merge run behind
    them, which is the failure this whole workflow exists to prevent."""
    assert "sweepMax" in sweep, "the sweep is no longer capped"
    cfg = yaml.safe_load(source)
    declared = (cfg.get("env") or {}).get("SWEEP_MAX")
    assert declared is not None, (
        "SWEEP_MAX is no longer declared in the workflow env, so the cap can only be changed by "
        "editing the script body"
    )
    assert 1 <= int(declared) <= 8, (
        f"SWEEP_MAX is {declared}. The CI fleet is nine machines and one PR run takes several; "
        f"a cap above 8 starves main's own run."
    )


def test_a_failed_rescue_does_not_fail_the_merge_job(sweep: str) -> None:
    """The merge already landed. A PR that could not be updated is exactly as stuck as it was
    and the next merge tries again -- turning the job red would report a non-event as an
    incident and train everyone to ignore it."""
    assert "core.warning" in sweep, "the sweep's failure path no longer warns"
    assert "core.setFailed" not in sweep, (
        "a failed rescue now fails the job, which reports a merge that succeeded as a failure"
    )

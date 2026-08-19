"""A workflow that subscribes to an event GitHub does not have never runs a job.

WHY THIS EXISTS. `.github/workflows/ci-autoscale.yml` shipped on 2026-08-19 with
`on: workflow_job`. There is no `workflow_job` trigger -- it is a webhook event GitHub sends to
apps, and it is not on the list a workflow may subscribe to. GitHub rejected the file at parse
time, so every push created a run that FAILED before a single job existed. Five runs, five
failures, zero jobs, and the runner pool never scaled once. Measured:

    gh api repos/chidionyema/prospector/actions/runs/32257716670/jobs --jq .total_count  ->  0

Nothing caught it, and nothing could have: a workflow that fails at parse time writes no log,
produces no annotation on any check suite, and reports its name as its own file path. The only
signal was the runs list, and only if someone thought to filter it by that one workflow.

So the check is here, offline, on the file. Two things are graded, both of which fail silently
in production:

  THE TRIGGER EXISTS       an invented `on:` key means the workflow can never run.
  THE NAMED WORKFLOW EXISTS  `on.workflow_run.workflows` matches by NAME. Rename the upstream
                           workflow and the subscriber simply stops firing -- no error anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# The events a workflow may subscribe to, from GitHub's "Events that trigger workflows".
# `workflow_job`, `workflow_run` and `check_run` look alike and only two of them are here,
# which is exactly the trap.
REAL_TRIGGERS = {
    "branch_protection_rule", "check_run", "check_suite", "create", "delete",
    "deployment", "deployment_status", "discussion", "discussion_comment", "fork",
    "gollum", "issue_comment", "issues", "label", "merge_group", "milestone",
    "page_build", "public", "pull_request", "pull_request_review",
    "pull_request_review_comment", "pull_request_target", "push", "registry_package",
    "release", "repository_dispatch", "schedule", "status", "watch", "workflow_call",
    "workflow_dispatch", "workflow_run",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _on(doc: dict):
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1 says so), so reading
    # doc["on"] finds nothing and a broken file would pass this test by being unreadable.
    return doc.get("on", doc.get(True))


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.glob("*.y*ml"))


def test_there_are_workflows_to_grade():
    # A glob that matches nothing passes every test below it. Memory:
    # a-guard-that-iterates-an-empty-list-passes.
    assert len(_workflow_files()) >= 5


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_trigger_is_a_real_github_event(path: Path):
    on = _on(_load(path))
    assert on is not None, f"{path.name} declares no `on:` trigger at all"
    keys = [on] if isinstance(on, str) else list(on)
    unknown = sorted(set(keys) - REAL_TRIGGERS)
    assert not unknown, (
        f"{path.name} subscribes to {unknown}, which GitHub does not accept. The file is "
        f"rejected at parse time: every run fails with zero jobs and no log."
    )


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_run_names_a_workflow_that_exists(path: Path):
    on = _on(_load(path))
    if not isinstance(on, dict):
        return
    spec = on.get("workflow_run")
    if not isinstance(spec, dict):
        return
    wanted = spec.get("workflows") or []
    known = {(_load(p).get("name") or p.name) for p in _workflow_files()}
    missing = sorted(set(wanted) - known)
    assert not missing, (
        f"{path.name} waits on {missing}, and no workflow in this repository carries that "
        f"name. It would never fire, and nothing would report an error."
    )

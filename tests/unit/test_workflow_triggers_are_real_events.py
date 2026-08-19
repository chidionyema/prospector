"""A workflow whose trigger is not a real trigger event can never run.

THE INCIDENT (2026-08-19). `.github/workflows/ci-autoscale.yml` was written, reviewed and merged
with `on: workflow_job`. `workflow_job` is a WEBHOOK event; it is not one of the events that can
start a workflow. GitHub therefore rejected the file and recorded a startup failure against it on
every push instead. Measured: of the last 40 runs, 35 shown were `event: push`,
`conclusion: failure`, with **0 jobs**, and **0** were `event: workflow_job`. `gh run view` said
only "This run likely failed because of a workflow file issue".

So the CI pool was never autoscaled, and the evidence that it was never autoscaled looked exactly
like ordinary red-branch noise. That is the failure mode this test exists to stop: a mechanism that
cannot run, failing in a way nobody reads.

THE CLASS is "a workflow that can never execute, failing silently". A memory file does not close it
— the next invalid trigger will be typed by a different agent in a different session. This test
does, because it runs in the same python lane every branch already has to pass.

Reference: docs/STACK_FLAKINESS_AUDIT.md §1, docs/PLATFORM_MANIFESTO.md L11.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"

# The events GitHub accepts as workflow triggers.
# https://docs.github.com/actions/reference/events-that-trigger-workflows
# Anything outside this set is either a webhook-only event (workflow_job, deployment_review,
# installation, ...) or a typo, and either way the workflow never runs.
VALID_TRIGGERS = frozenset({
    "branch_protection_rule", "check_run", "check_suite", "create", "delete",
    "deployment", "deployment_status", "deployment_protection_rule", "discussion",
    "discussion_comment", "fork", "gollum", "issue_comment", "issues", "label",
    "merge_group", "milestone", "page_build", "public", "pull_request",
    "pull_request_review", "pull_request_review_comment", "pull_request_target", "push",
    "registry_package", "release", "repository_dispatch", "schedule", "status", "watch",
    "workflow_call", "workflow_dispatch", "workflow_run",
})


def _triggers(text: str) -> set[str]:
    """The trigger names declared by one workflow file.

    YAML 1.1 resolves a bare `on` key to the boolean True, so the key is looked up as both. A
    reader that only checks the string "on" finds nothing and passes every file vacuously — which
    is the same shape of defect as the one being guarded against.
    """
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        return set()
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))


def test_there_are_workflows_to_check() -> None:
    """A guard that iterates an empty list passes without checking anything."""
    assert len(_workflow_files()) >= 5


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_trigger_is_a_real_workflow_event(path: Path) -> None:
    declared = _triggers(path.read_text(encoding="utf-8"))
    assert declared, f"{path.name} declares no `on:` trigger, so it can never run"
    bogus = sorted(declared - VALID_TRIGGERS)
    assert not bogus, (
        f"{path.name} triggers on {bogus}, which GitHub does not accept as a workflow trigger. "
        "The workflow will never run; GitHub records a failed 0-job run on every push instead. "
        "See docs/STACK_FLAKINESS_AUDIT.md §1."
    )


def test_the_check_can_actually_fail() -> None:
    """Prove the reader sees the real defect, using the exact file that shipped broken."""
    broken = "name: x\non:\n  workflow_job:\n    types: [queued]\njobs: {}\n"
    assert _triggers(broken) - VALID_TRIGGERS == {"workflow_job"}


def test_the_check_reads_a_bare_on_key() -> None:
    """`on:` unquoted is the boolean True in YAML 1.1. Miss that and every file passes vacuously."""
    assert _triggers("name: x\non: [push]\njobs: {}\n") == {"push"}
    assert _triggers('name: x\n"on":\n  push:\n    branches: [main]\njobs: {}\n') == {"push"}

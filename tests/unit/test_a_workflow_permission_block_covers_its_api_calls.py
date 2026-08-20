"""An explicit `permissions:` block sets every scope it does not list to `none`.

WHAT HAPPENED. 2026-08-19T20:53:41Z. `.github/workflows/automerge.yml` merged PR #451 onto main,
then its stranded-PR sweep called `GET /commits/<sha>/check-runs` and got
`403 Resource not accessible by integration`. The workflow's permissions block listed
contents/pull-requests/actions and not `checks: read`, and an explicit block is a WHITELIST: every
scope absent from it is set to `none`, not left at the repository default. The throw killed the job
before its next step, `dispatching CI on main` -- so the merge landed and main was never graded.
The founder's standing rule is "if main is not green nothing else can ever be green", and for four
minutes nothing could tell whether it was.

THE SECOND HALF, which is why this is a test and not a one-line fix. A JOB-level permissions block
REPLACES the top-level one outright; it does not add to it. `e2e-live-smoke.yml` grants
`issues: write` at the top and then re-declares `permissions: {contents: write}` on the
visual-baselines job, which makes four unguarded `github.rest.issues.*` calls. That job is normally
skipped, so the 403 had never fired -- a defect with no symptom until the day someone dispatches it.

THE CLASS: a permission a workflow needs but does not declare. It fails as a 403 at RUN time, on a
line that has usually already changed the world, and when the call is inside a try/catch it does
not fail at all -- it warns into a log nobody reads while the mechanism it powers silently does
nothing. `issues.addLabels` in automerge.yml was in exactly that state: the `needs-rebase` label
that makes a stuck PR visible had never once been applied.

So the refusal has to happen before merge, statically, which is what this test is. It reads every
API call each job makes, computes that job's EFFECTIVE permissions the way GitHub computes them,
and fails if a call's scope is not granted. An API method missing from SCOPES is also a failure:
adding a call you have not thought about the permission for is the mistake being prevented.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

CALL_RE = re.compile(r"github\.rest\.([a-zA-Z]+)\.([a-zA-Z]+)")

# scope needed by each API method. A tuple means ANY ONE of them is enough -- the Issues API
# applied to a pull request number is satisfied by `pull-requests: write` as well as
# `issues: write`, and the call site cannot be known statically.
SCOPES: dict[str, tuple[str, ...]] = {
    "actions.approveWorkflowRun": ("actions:write",),
    "actions.cancelWorkflowRun": ("actions:write",),
    "actions.createWorkflowDispatch": ("actions:write",),
    "actions.listJobsForWorkflowRun": ("actions:read",),
    "actions.listWorkflowRuns": ("actions:read",),
    "actions.listWorkflowRunsForRepo": ("actions:read",),
    "actions.reRunWorkflowFailedJobs": ("actions:write",),
    "checks.listForRef": ("checks:read",),
    "git.deleteRef": ("contents:write",),
    "issues.addLabels": ("issues:write", "pull-requests:write"),
    "issues.create": ("issues:write",),
    "issues.createComment": ("issues:write", "pull-requests:write"),
    "issues.listForRepo": ("issues:read",),
    "issues.listLabelsOnIssue": ("issues:read", "pull-requests:read"),
    "issues.update": ("issues:write",),
    "pulls.get": ("pull-requests:read",),
    "pulls.list": ("pull-requests:read",),
    "pulls.listFiles": ("pull-requests:read",),
    "pulls.merge": ("pull-requests:write",),
    "pulls.updateBranch": ("pull-requests:write",),
    "repos.compareCommits": ("contents:read",),
    "repos.getBranch": ("contents:read",),
    "repos.getCommit": ("contents:read",),
    "repos.listCommits": ("contents:read",),
    "repos.listPullRequestsAssociatedWithCommit": ("pull-requests:read",),
}

RANK = {"none": 0, "read": 1, "write": 2}


def _granted(perms, want: str) -> bool:
    """Does this permissions value grant `scope:level`? write satisfies read."""
    scope, level = want.split(":")
    if perms in ("write-all",):
        return True
    if perms in ("read-all",):
        return RANK[level] <= RANK["read"]
    if not isinstance(perms, dict):
        return False
    return RANK.get(str(perms.get(scope, "none")), 0) >= RANK[level]


def _jobs_with_calls():
    """(workflow, job, effective permissions, sorted calls) for every job that calls the API."""
    out = []
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text())
        if not isinstance(doc, dict):
            continue
        top = doc.get("permissions")
        for name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            calls = sorted({f"{a}.{b}" for a, b in CALL_RE.findall(json.dumps(job))})
            if not calls:
                continue
            # A job block REPLACES the top-level one. This line is the whole bug.
            effective = job["permissions"] if "permissions" in job else top
            out.append((wf.name, name, effective, calls))
    return out


JOBS = _jobs_with_calls()


def test_the_workflow_directory_was_actually_read():
    """A glob that matches nothing turns every test below into a silent pass."""
    assert WORKFLOWS, f"no workflows found under {ROOT / '.github' / 'workflows'}"
    assert JOBS, "no job calls github.rest.* -- the parser stopped seeing calls it used to see"


@pytest.mark.parametrize("wf,job,perms,calls", JOBS, ids=[f"{w}:{j}" for w, j, _, _ in JOBS])
def test_every_api_call_has_the_permission_it_needs(wf, job, perms, calls):
    if perms is None:
        pytest.skip(
            f"{wf}:{job} declares no permissions block, so the repository default applies and "
            f"nothing is silently set to none. This test grades WHITELISTS."
        )

    unknown = [c for c in calls if c not in SCOPES]
    assert not unknown, (
        f"{wf}:{job} calls {unknown}, which is not in SCOPES. Add it with the scope GitHub's REST "
        f"docs list for that endpoint. An undeclared call is the mistake this test exists to stop."
    )

    missing = [(c, SCOPES[c]) for c in calls if not any(_granted(perms, s) for s in SCOPES[c])]
    assert not missing, (
        f"{wf}:{job} has permissions {perms} and will get 403 "
        f"'Resource not accessible by integration' on: "
        + "; ".join(f"{c} (needs one of {' or '.join(s)})" for c, s in missing)
        + ". Remember a job-level block REPLACES the top-level one -- re-declare every scope the "
        "job still needs, do not assume it inherits."
    )


def test_a_job_block_is_read_as_a_replacement_not_a_merge():
    """Pin the rule the fixture encodes, so nobody 'fixes' it into an inheriting merge."""
    doc = {"permissions": {"issues": "write", "contents": "read"},
           "jobs": {"j": {"permissions": {"contents": "write"},
                          "steps": [{"run": "github.rest.issues.create()"}]}}}
    top = doc["permissions"]
    job = doc["jobs"]["j"]
    effective = job["permissions"] if "permissions" in job else top

    assert effective == {"contents": "write"}
    assert not _granted(effective, "issues:write"), (
        "a job-level block must DROP the top-level issues:write. If this ever passes, GitHub "
        "changed the semantics and the parser above needs to change with it."
    )


@pytest.mark.parametrize(
    "perms,want,ok",
    [
        ({"checks": "read"}, "checks:read", True),
        ({"checks": "write"}, "checks:read", True),   # write satisfies read
        ({"checks": "read"}, "checks:write", False),  # read does not satisfy write
        ({"contents": "write"}, "checks:read", False),  # the automerge 403, exactly
        ({}, "checks:read", False),                   # an empty block grants nothing
        ("write-all", "checks:write", True),
        ("read-all", "checks:write", False),
    ],
)
def test_the_grant_check_itself(perms, want, ok):
    assert _granted(perms, want) is ok

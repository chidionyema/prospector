"""The PR cleanup holds `actions: write`. Prove it can only ever cancel dead work.

WHY THIS FILE EXISTS. `.github/workflows/cancel-ci-on-pr-close.yml` cancels CI runs. It is the
only workflow in this repository whose whole purpose is to destroy other jobs, it runs
unattended on every closed pull request, and until 2026-08-20 it had no test of any kind. The
pipeline failure ledger (`test_the_pipeline_failure_ledger.py`) is what said so out loud.

Cancelling is the most misdiagnosable failure in this estate: a cancelled run and a failing run
look identical in `gh run list`, in the checks API and in the PR UI. So a bug here does not
present as "the cleanup is broken". It presents as "CI is flaky", and costs a day.

Every assertion below is an invariant this workflow has ALREADY broken once:

  * It cancelled its own run, so every closed PR carried a red `cancel` check that no re-run
    could clear -- the workflow only fires on `pull_request: closed`. Measured on PR #308:
    "cancelled in_progress run 32094965534", its own id.
  * It shelled out to `gh`, which is not installed on our self-hosted runners. Every invocation
    printed `gh: command not found`, the `|| true` turned that into an empty id list, and the
    job went green having cancelled nothing for a day. Proof: run 32169451195.
  * It was pinned to `ubuntu-latest`, which this account cannot start, so it failed on every
    PR and made every pull request in the repo non-green.

And one it has not broken, which is the reason to write the test now rather than after: the
query is scoped by the PR's head branch. Widen it -- drop the branch, or key on the base -- and
the next merge to main cancels main's own post-merge CI run. That run is the one the whole
estate reads to decide whether main is green.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "cancel-ci-on-pr-close.yml"


@pytest.fixture(scope="module")
def text() -> str:
    assert WORKFLOW.exists(), f"{WORKFLOW} is gone; the ledger row naming it needs updating too"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc(text: str) -> dict:
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def script(text: str) -> str:
    """The github-script body. Everything destructive happens in here."""
    marker = "script: |"
    i = text.find(marker)
    assert i >= 0, "no github-script step found; this workflow no longer works the way it did"
    return text[i + len(marker):]


def test_it_only_fires_when_a_pull_request_closes(doc):
    """A wider trigger means it runs while work is live, which is when cancelling costs."""
    # PyYAML reads a bare `on:` key as the boolean True. Accept either spelling rather than
    # asserting on a quirk of the parser.
    on = doc.get("on", doc.get(True))
    assert on is not None, "the workflow declares no triggers at all"
    assert set(on) == {"pull_request"}, (
        f"this workflow may only fire on pull_request; found {sorted(on)}. Anything else runs it "
        f"against branches whose work is still live."
    )
    assert on["pull_request"]["types"] == ["closed"], (
        f"only `closed`; found {on['pull_request'].get('types')}"
    )


def test_the_query_is_scoped_to_the_closed_pull_requests_own_branch(script):
    """The single assertion that keeps it away from main.

    `listWorkflowRunsForRepo` without a branch returns EVERY run in the repository, main's
    post-merge run included. That run is what every probe, every gate and every agent reads to
    decide whether main is green, and cancelling it is indistinguishable from it failing.
    """
    assert re.search(r"const\s+branch\s*=\s*context\.payload\.pull_request\.head\.ref", script), (
        "the branch must come from the closed PR's own HEAD ref. Taking it from the base, or "
        "from context.ref, points this at main."
    )
    listing = re.search(r"listWorkflowRunsForRepo\s*,\s*\{([^}]*)\}", script, re.S)
    assert listing, "could not find the run listing call; it may have been restructured"
    assert re.search(r"\bbranch\b", listing.group(1)), (
        f"the listing call must be scoped by branch, or it returns every run in the repository "
        f"including main's. Found: {listing.group(1).strip()}"
    )


def test_it_never_cancels_main(script, text):
    """Belt and braces: no literal main anywhere in the destructive path."""
    assert not re.search(r"branch\s*[:=]\s*['\"]main['\"]", script), (
        "this workflow must never name main as a cancellation target"
    )
    assert "context.payload.pull_request.base" not in script, (
        "the base ref of a closed PR is main. Scoping the cancellation by it cancels main's runs."
    )


def test_it_refuses_to_cancel_its_own_run(script):
    """PR #308: it cancelled itself, and the red check could never be cleared.

    It fires only on `pull_request: closed`, so there is no event left that could re-run it. The
    PR is stuck red forever.
    """
    assert re.search(r"const\s+self\s*=\s*context\.runId", script), (
        "the job must capture its own run id"
    )
    assert re.search(r"run\.id\s*===?\s*self", script), (
        "the loop must skip its own run. Without this every closed PR is reddened by its own "
        "cleanup, and nothing can clear it."
    )


def test_one_failed_cancel_does_not_fail_the_job(script):
    """A run that finishes between the list and the cancel answers 409. That is success."""
    assert "try {" in script and "catch" in script, (
        "the cancel call must be wrapped: a 409 from an already-finished run is a race, not a "
        "fault, and failing the job on it reddens the PR for doing its job correctly"
    )
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*(core\.setFailed|throw)", script), (
        "the catch must not fail or rethrow; see above"
    )


def test_it_does_not_shell_out_to_a_cli_the_runners_do_not_have(text):
    """It was a silent no-op for a day because `gh` is not installed on our runners.

    The `|| true` on the list call turned `gh: command not found` into an empty id list, so the
    loop iterated nothing and the job went green. A workflow that cannot work must not be able
    to look like one that did.
    """
    assert not re.search(r"^\s*run:\s", text, re.M), (
        "no shell steps: this workflow must talk to the API through actions/github-script, which "
        "uses the node the runner already ships. Proof of what a CLI costs: run 32169451195."
    )
    assert "actions/github-script" in text


def test_it_runs_where_this_account_can_actually_start_a_runner(doc):
    """Pinned to `ubuntu-latest` it failed on every PR, because we cannot start hosted runners."""
    runs_on = doc["jobs"]["cancel"]["runs-on"]
    assert "vars.CI_LIGHT_RUNS_ON" in runs_on or "vars.CI_RUNS_ON" in runs_on, (
        f"runs-on must resolve through the repository variables that name our own fleet; "
        f"found {runs_on!r}. A hard 'ubuntu-latest' cannot start here and reddens every PR."
    )


def test_its_permissions_are_the_narrowest_that_still_work(doc):
    """`actions: write` is the power to destroy any job in the repository. Nothing else is needed
    unless the workflow says out loud what it did.

    An explicit permissions block is a whitelist, so this also proves the workflow cannot write
    contents or packages even if a future edit tries to.

    `pull-requests: write` is allowed on ONE condition, checked below rather than waved through:
    the script must actually post a comment. Founder, 2026-08-20, on a pipeline that cancelled,
    reverted and blocked without ever saying why -- "the whole loop hapens in the dark". A robot
    that destroys a running job and leaves no note on the pull request is that darkness, and the
    scope that lifts it is this one. Grant it only to a workflow that uses it: an unused write
    scope is power with no purpose, which is exactly what the rest of this test refuses.
    """
    perms = doc["permissions"]
    assert perms.get("actions") == "write", "it cannot cancel without actions: write"
    assert perms.get("contents") == "read", "it never needs to write contents"

    allowed = {"actions", "contents"}
    script = doc["jobs"]["cancel"]["steps"][-1]["with"]["script"]
    if "issues.createComment" in script:
        allowed.add("pull-requests")
    else:
        assert perms.get("pull-requests") != "write", (
            "pull-requests: write is granted but the script no longer comments. Drop the scope, "
            "or put the explanation back -- those are the only two honest states.")

    extra = {k: v for k, v in perms.items() if k not in allowed and v == "write"}
    assert not extra, f"unnecessary write scopes: {extra}"

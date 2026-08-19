"""A workflow that checks the LIVE site must alert when it fails, and stand the alert down.

WHY THIS TEST EXISTS
--------------------
`e2e-live-smoke.yml` went red on 2026-08-19 and stayed red for 30 hours. Nobody was told.
Its whole notification path was a non-zero exit code and an uploaded artifact, both of which
live on a run page nobody opens. The daily 07:00 UTC schedule makes it worse rather than
better: that trigger exists to catch breakage with no commit behind it, so there is not even
a push author who might notice the red tick.

The fix (issue #415) adds two steps: one opens or comments on a single issue labelled
`live-red` when a check fails, and one closes it when they all pass. The label is the state, so
an OPEN `live-red` issue means live is red right now and no open issue means it is not.

WHAT THIS TEST PINS
-------------------
The mechanical half of "never make the same mistake twice". A live-checking workflow can lose
its alert in one careless edit — delete a step, drop the `issues: write` permission, or change
the label on one side only — and nothing would report it, because the alert is exactly the
thing that only runs when something else is already broken. Every assertion below fails on one
of those edits.

It does NOT try to test that the alert WORKS end to end; that needs GitHub. It tests that the
alert is wired: present, permitted, on a condition that can actually fire, and agreeing with
itself about the label.

WHY IT NO LONGER READS THE `if:` STRING LITERALLY (rewritten 2026-08-19)
-----------------------------------------------------------------------
This test used to find the alarm by grepping for a step whose condition was exactly
`failure()`, and the stand-down by grepping for exactly `success()`. That is the shape of the
evidence, not its content, and it failed in both directions at once:

* It PASSED for eight weeks on a workflow whose alarm never ran. The two steps were attached to
  the `visual-baselines` job, which is gated on `workflow_dispatch` + `inputs.update_visual_
  baselines`. On the daily schedule and on every deploy that job is SKIPPED, and a skipped job
  runs no steps. The literal `if: failure()` was present the whole time and reported nothing.
* It then FAILED on the fix. Moving the alarm into its own job is the only way to make it run,
  and inside that job bare `failure()` reads THAT job's status — the alarm job runs no checks,
  so it is always success and the alarm would still never fire. The correct condition there is
  `contains(needs.*.result, 'failure')`, which the old grep did not recognise.

So the alarm is now located by what its script DOES (opens the issue / closes the issue) and
its condition is graded on whether it CAN fire in that case. A test that pins one spelling
blocks the only correct fix and blesses the broken version.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# Workflows that assert against the LIVE site rather than against a build. Add to this list
# when another one appears; a live check with no alert is the defect this test names.
LIVE_CHECK_WORKFLOWS = ["e2e-live-smoke.yml"]

# The one label that carries the state. Both the raise step and the stand-down step must use
# it, or the alarm opens issues that nothing ever closes.
STATE_LABEL = "live-red"

# A condition that can fire when a graded job failed. Either the step sits in a job that runs
# the checks (`failure()`), or it sits in a job that WAITS on them and reads their results.
# The lookbehind matters: `!contains(needs.*.result, 'failure')` is the stand-down condition
# and must never be mistaken for the alarm.
FIRES_ON_FAILURE = re.compile(r"(?<![!\w])(?:failure\(\)|contains\([^)]*needs[^)]*'failure'\))")

# A condition that fires only when nothing failed. `success()` in a checking job, or the
# negated needs form in a job that waits on them.
FIRES_ON_PASS = re.compile(r"(?<![!\w])success\(\)|!\s*contains\([^)]*needs[^)]*'failure'\)")


def _load(name: str) -> dict:
    path = WORKFLOWS / name
    assert path.exists(), f"{name} is missing from {WORKFLOWS}"
    # `on:` parses to the boolean True in YAML 1.1, which is why nothing here reads it.
    return yaml.safe_load(path.read_text())


def _steps(doc: dict) -> list[tuple[str, dict, dict]]:
    """(job name, job, step) for every step in the workflow.

    The job comes back with the step because permissions and `needs:` live on the JOB, and
    both decide whether the step can do its work.
    """
    return [(name, job, step)
            for name, job in doc["jobs"].items()
            for step in job.get("steps", [])]


def _script(step: dict) -> str:
    return str(step.get("with", {}).get("script", ""))


def _cond(step: dict) -> str:
    return str(step.get("if", "")).strip()


def _effective_permissions(doc: dict, job: dict) -> dict | None:
    """What the job's GITHUB_TOKEN actually carries.

    A job-level `permissions:` block REPLACES the top-level one outright — it does not merge
    with it and does not add to it. Reading the top-level block for a job that has its own is
    how a test passes while the job it grades gets a 403.
    """
    perms = job.get("permissions", doc.get("permissions"))
    return perms if isinstance(perms, dict) else None


#: `issues.create(` and NOT `issues.createComment(`. The stand-down step comments on the issue
#: to say the site recovered, so a substring match on "issues.create" files it as an alarm
#: raiser and then fails it for having a stand-down condition.
OPENS_THE_ISSUE = re.compile(r"issues\.create\s*\(")


def _raisers(doc: dict) -> list[tuple[str, dict, dict]]:
    """Steps that OPEN the alarm, found by what they do rather than by their condition."""
    return [t for t in _steps(doc) if OPENS_THE_ISSUE.search(_script(t[2]))]


def _closers(doc: dict) -> list[tuple[str, dict, dict]]:
    """Steps that STAND THE ALARM DOWN."""
    return [t for t in _steps(doc) if "state: 'closed'" in _script(t[2])]


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_it_can_write_the_issue_it_needs_to_write(name: str) -> None:
    """`issues: write` is the permission the alert needs. Without it the step throws 403.

    A 403 inside a step that only runs on failure is the quietest possible failure: the run was
    already red, so the extra red step reads as more of the same.

    This grades the EFFECTIVE permission of the job holding the alarm. The alarm used to live in
    a job whose own block was `permissions: {contents: write}`, which replaces the top-level
    grant entirely — so every `issues.*` call in it would have 403'd while a check of the
    top-level block said the workflow was fine.
    """
    doc = _load(name)
    alarm = _raisers(doc) + _closers(doc)
    assert alarm, f"{name} has no step that opens or closes the `{STATE_LABEL}` issue"

    for job_name, job, _step in alarm:
        perms = _effective_permissions(doc, job)
        assert isinstance(perms, dict), (
            f"{name} job `{job_name}` writes issues under no explicit permissions block"
        )
        assert perms.get("issues") == "write", (
            f"{name} job `{job_name}` cannot write issues, so its alert cannot fire "
            f"(effective permissions={perms})"
        )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_a_failure_raises_the_alarm(name: str) -> None:
    """A step opens the issue, and its condition can actually fire when a check failed."""
    doc = _load(name)
    raisers = _raisers(doc)
    assert raisers, (
        f"{name} has no step that opens an issue. A red run that tells nobody is the 30-hour "
        f"outage of 2026-08-19."
    )

    for job_name, _job, step in raisers:
        cond = _cond(step)
        assert FIRES_ON_FAILURE.search(cond), (
            f"{name} job `{job_name}` opens the alarm on `if: {cond or '<always>'}`, which "
            f"cannot fire on a failed check. Use `failure()` inside a checking job, or "
            f"`contains(needs.*.result, 'failure')` inside a job that waits on them."
        )

    script = "\n".join(_script(s) for _n, _j, s in raisers)
    assert "issues.createComment" in script, (
        f"{name} failure step never comments, so a daily cron against a broken site would "
        f"open one issue per day instead of appending to the open one"
    )
    assert STATE_LABEL in script, (
        f"{name} failure step does not use the `{STATE_LABEL}` label, so the stand-down step "
        f"will never find the issue it opened"
    )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_a_pass_stands_the_alarm_down(name: str) -> None:
    """The alert clears itself. Self-healing first — an alert a human must close is stale by
    the second day, and a stale alert is indistinguishable from a real one."""
    doc = _load(name)
    closers = _closers(doc)
    assert closers, (
        f"{name} has no step that closes the issue, so a `{STATE_LABEL}` issue would stay open "
        f"after the site recovered and the label would stop meaning anything"
    )

    for job_name, _job, step in closers:
        cond = _cond(step)
        assert FIRES_ON_PASS.search(cond), (
            f"{name} job `{job_name}` stands the alarm down on `if: {cond or '<always>'}`, "
            f"which does not establish that the checks passed. Use `success()` inside a "
            f"checking job, or `!contains(needs.*.result, 'failure')` in one that waits."
        )
        assert not FIRES_ON_FAILURE.search(cond), (
            f"{name} job `{job_name}` would close the `{STATE_LABEL}` issue on a run where a "
            f"check FAILED, reporting the site green with no evidence. if: {cond}"
        )

    script = "\n".join(_script(s) for _n, _j, s in closers)
    assert STATE_LABEL in script, (
        f"{name} success step looks for a different label than the failure step opens"
    )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_the_alarm_is_not_gated_on_a_trigger_that_rarely_runs(name: str) -> None:
    """The defect this whole file failed to catch for eight weeks, pinned directly.

    The alarm steps sat in a job gated on `workflow_dispatch` + an input, so on the daily
    schedule and on every deploy the job was skipped and the alarm never ran. Five consecutive
    red runs opened zero issues. Any condition on the alarm's JOB that names an event or an
    input makes the alarm conditional on someone asking for it by hand — which is exactly when
    nobody needs telling.
    """
    doc = _load(name)
    for job_name, job, _step in _raisers(doc) + _closers(doc):
        cond = str(job.get("if", ""))
        assert "workflow_dispatch" not in cond and "inputs." not in cond, (
            f"{name} job `{job_name}` holds the alarm but only runs on a manual trigger "
            f"(if: {cond}). On the schedule and on deploys it is skipped, and a skipped job "
            f"runs no steps — this is the 30-hour silence of 2026-08-19, exactly."
        )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_the_report_still_uploads_whatever_happens(name: str) -> None:
    """The alert links to the run; the run must still carry the evidence.

    `if: always()` on the upload is what makes the alert actionable rather than just loud.
    """
    steps = _steps(_load(name))
    uploads = [s for _n, _j, s in steps if "upload-artifact" in str(s.get("uses", ""))]
    assert uploads, f"{name} uploads no report, so its alert would link to an empty run"
    assert any(str(s.get("if", "")).strip() == "always()" for s in uploads), (
        f"{name} only uploads its report on success, which is the one case nobody needs it"
    )

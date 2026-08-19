"""A workflow that checks the LIVE site must alert when it fails, and stand the alert down.

WHY THIS TEST EXISTS
--------------------
`e2e-live-smoke.yml` went red on 2026-08-19 and stayed red for 30 hours. Nobody was told.
Its whole notification path was a non-zero exit code and an uploaded artifact, both of which
live on a run page nobody opens. The daily 07:00 UTC schedule makes it worse rather than
better: that trigger exists to catch breakage with no commit behind it, so there is not even
a push author who might notice the red tick.

The fix (issue #415) adds two steps: `if: failure()` opens or comments on one issue labelled
`live-red`, and `if: success()` closes it. The label is the state, so an OPEN `live-red`
issue means live is red right now and no open issue means it is not.

WHAT THIS TEST PINS
-------------------
The mechanical half of "never make the same mistake twice". A live-checking workflow can lose
its alert in one careless edit — delete a step, drop the `issues: write` permission, or change
the label on one side only — and nothing would report it, because the alert is exactly the
thing that only runs when something else is already broken. Every assertion below fails on one
of those edits.

It does NOT try to test that the alert WORKS end to end; that needs GitHub. It tests that the
alert is wired: present, permitted, on the right conditions, and agreeing with itself about
the label.
"""

from __future__ import annotations

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


def _load(name: str) -> dict:
    path = WORKFLOWS / name
    assert path.exists(), f"{name} is missing from {WORKFLOWS}"
    # `on:` parses to the boolean True in YAML 1.1, which is why nothing here reads it.
    return yaml.safe_load(path.read_text())


def _steps(doc: dict) -> list[dict]:
    return [step for job in doc["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_it_can_write_the_issue_it_needs_to_write(name: str) -> None:
    """`issues: write` is the permission the alert needs. Without it the step throws 403.

    A 403 inside an `if: failure()` step is the quietest possible failure: the run was already
    red, so the extra red step reads as more of the same.
    """
    doc = _load(name)
    perms = doc.get("permissions")
    assert isinstance(perms, dict), f"{name} has no explicit permissions block"
    assert perms.get("issues") == "write", (
        f"{name} cannot write issues, so its alert cannot fire (permissions={perms})"
    )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_a_failure_raises_the_alarm(name: str) -> None:
    """Exactly one step runs on failure and it talks to the issues API."""
    steps = _steps(_load(name))
    raisers = [s for s in steps if str(s.get("if", "")).strip() == "failure()"]
    assert raisers, (
        f"{name} has no `if: failure()` step. A red run that tells nobody is the 30-hour "
        f"outage of 2026-08-19."
    )
    script = "\n".join(str(s.get("with", {}).get("script", "")) for s in raisers)
    assert "issues.create" in script, f"{name} failure step never opens an issue"
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
    steps = _steps(_load(name))
    closers = [s for s in steps if str(s.get("if", "")).strip() == "success()"]
    assert closers, (
        f"{name} has no `if: success()` step, so a `{STATE_LABEL}` issue would stay open after "
        f"the site recovered and the label would stop meaning anything"
    )
    script = "\n".join(str(s.get("with", {}).get("script", "")) for s in closers)
    assert "state: 'closed'" in script, f"{name} success step never closes the issue"
    assert STATE_LABEL in script, (
        f"{name} success step looks for a different label than the failure step opens"
    )


@pytest.mark.parametrize("name", LIVE_CHECK_WORKFLOWS)
def test_the_report_still_uploads_whatever_happens(name: str) -> None:
    """The alert links to the run; the run must still carry the evidence.

    `if: always()` on the upload is what makes the alert actionable rather than just loud.
    """
    steps = _steps(_load(name))
    uploads = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
    assert uploads, f"{name} uploads no report, so its alert would link to an empty run"
    assert any(str(s.get("if", "")).strip() == "always()" for s in uploads), (
        f"{name} only uploads its report on success, which is the one case nobody needs it"
    )

"""No CI workflow may stop a machine in the runner fleet.

WHY THIS TEST EXISTS
--------------------
On 2026-08-19, `.github/workflows/ci-autoscale.yml` landed on main as dad8cb7c (#396). It ran
`deploy/runners.sh autoscale`, whose scale-down loop reads the GitHub busy-runner list with
`|| true`. `secrets.GITHUB_TOKEN` cannot read that endpoint at all -- it needs repo ADMIN -- so
the list came back empty, every started machine read as idle, and the loop stopped machines that
were in the middle of a build.

Measured: machine 8ee06eb7701628 logged `stop stopping` at 14:50:51Z and `crash stopped
requested_stop=True` at 14:51:58Z, 15 minutes into PR #425's python job. Nine PRs died the same
way -- #383 #387 #390 #391 #407 #414 #424 #427 #431 -- each with step 6 concluding `null` and the
annotation "The self-hosted runner lost communication with the server". That annotation is
indistinguishable from a failing test unless you open it, so the estate spent a day diagnosing
phantom test failures. #396's own merge commit was one of the casualties, which is why main went
red on the commit that introduced the autoscaler and did not recover.

Founder decision, 2026-08-19: no autoscaling until spun-up machines are proven reliable, and it
must not be possible to switch it back on by accident. The workflow is disabled at GitHub and
deleted from the repo; this test is what fails if either comes back.

`deploy/runners.sh autoscale` itself is left alone deliberately -- PRs #423 and #424 are fixing
its fail-open read. Fixing the function is fine. Wiring it to an automatic trigger is not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: Marker a future author must add, with the founder's sign-off, to turn this back on.
UNBLOCK_MARKER = "autoscale-reinstated-with-founder-signoff"

_AUTOSCALE = re.compile(r"runners\.sh\s+autoscale\b")
_FLY_STOP = re.compile(r"\bfly\s+machines?\s+stop\b")


def _workflow_texts() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS.glob("*.yml"))]


def test_the_autoscale_workflow_is_gone() -> None:
    stale = WORKFLOWS / "ci-autoscale.yml"
    assert not stale.exists(), (
        f"{stale} is back. It stopped Fly machines mid-build and killed nine PRs on "
        "2026-08-19, including its own merge commit. Autoscaling stays off until the "
        "busy-runner read is proven (it needs a repo-admin PAT secret, which this repo does "
        "not have) and the founder says the fleet is reliable."
    )


@pytest.mark.parametrize("name,text", _workflow_texts(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_workflow_invokes_the_autoscaler(name: str, text: str) -> None:
    if UNBLOCK_MARKER in text:
        return
    assert not _AUTOSCALE.search(text), (
        f".github/workflows/{name} runs `runners.sh autoscale`. Its scale-down reads the "
        "busy-runner list with `|| true`, so a failed read empties the list, every machine "
        "reads as idle, and it stops runners that are mid-build. That killed PRs #383 #387 "
        "#390 #391 #407 #414 #424 #427 #431 on 2026-08-19."
    )


@pytest.mark.parametrize("name,text", _workflow_texts(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_workflow_stops_a_machine(name: str, text: str) -> None:
    if UNBLOCK_MARKER in text:
        return
    assert not _FLY_STOP.search(text), (
        f".github/workflows/{name} runs `fly machine stop`. A runner stopped mid-job fails "
        'as "The self-hosted runner lost communication with the server", which reads as a '
        "failing test and cost this estate a day on 2026-08-19. Stopping machines is a manual "
        "action taken against a checked busy list, never a step in a workflow."
    )

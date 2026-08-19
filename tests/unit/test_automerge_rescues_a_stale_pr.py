"""The branch-update repair must be reachable from a FAILED run, and a red PR must never merge.

THE DEADLOCK, 2026-08-19. `automerge.yml` refuses to merge a pull request that sits behind main,
and updates the branch instead. That repair was gated on `workflow_run.conclusion == 'success'`,
so it could only ever run for a pull request that did not need it. A PR behind main inherits
main's failures. Its run concludes FAILURE. The job never started. The branch was never updated.
It stayed red forever.

Measured that morning: main was red on one test that none of them wrote, and thirteen open pull
requests were sitting in that loop with no way out except a person pushing to each one by hand.

The class: **the repair path was gated on the condition that proves repair is unnecessary.**

Both halves are pinned here because loosening the gate is exactly the change that could let red
code land. `proved` is the only thing that may authorise a merge, and it still means green.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "automerge.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_scan_sees_a_real_workflow() -> None:
    """Guard the guard: an empty read would pass a negative assertion over nothing."""
    text = _text()
    assert "name: Auto-merge green PRs" in text
    assert "pulls.merge" in text
    assert len(text.splitlines()) > 100


def test_a_failed_run_still_reaches_the_job() -> None:
    text = _text()
    assert "conclusion == 'failure'" in text, (
        "automerge only runs on a green CI run, so a pull request that is red BECAUSE it is "
        "behind main can never be updated: the repair is gated on not needing it"
    )


def test_only_a_green_run_may_merge() -> None:
    """Widening the trigger must not widen what can land."""
    text = _text()
    assert "const proved = context.payload.workflow_run.conclusion === 'success'" in text, (
        "the merge is no longer gated on a green run"
    )
    assert re.search(r"if \(!proved\) \{", text), (
        "nothing refuses the merge on a failed run; a red pull request could land"
    )
    # The refusal has to come BEFORE the merge call, or it refuses nothing.
    assert text.index("if (!proved) {") < text.index("await github.rest.pulls.merge("), (
        "the !proved refusal sits after the merge call, so it cannot stop it"
    )


def test_the_update_path_comes_before_the_refusal() -> None:
    """A stale red PR must be updated, not stopped. That ordering IS the fix."""
    text = _text()
    assert text.index("updateBranch") < text.index("if (!proved) {"), (
        "the !proved refusal runs before the behind-main update, so a stale red pull request is "
        "dropped instead of repaired -- which is the deadlock this file exists to break"
    )

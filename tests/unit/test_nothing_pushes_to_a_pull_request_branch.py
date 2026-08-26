"""No workflow may push to an open pull request's branch.

THE INCIDENT, 2026-08-20. Fifteen pull requests were open and none had merged in thirty hours.
Three separate batch branches were cut to close them and all three failed, each time for the
same reason nobody could see.

`pulls.updateBranch` pushes `Merge branch 'main' into <branch>` onto a pull request. GitHub
closes a pull request when its own HEAD COMMIT becomes reachable from main -- not when its
content does. So the moment that push lands, the pull request's head is a commit that is not
inside whatever branch was cut to close it, and the pull request stays open after its own work
has already merged.

The batch sets it off with its own merge. Cut a branch containing fifteen heads, merge it, main
moves, this fires on all fifteen, every head moves, and not one of them closes.

Measured. #480 merged to main at 0fa8f9a6. Four minutes later:

    26d5a7ec  github-actions[bot]  03:38:04  Merge branch 'main' into feat/deploy-every-service-from-the-console  (#477)
    f53bf864  github-actions[bot]  03:38:08  Merge branch 'main' into integrate/2026-08-20-eleven                 (#510)

No person touched either branch.

WHY THIS TEST AND NOT A NOTE. The call lived in TWO files, `automerge.yml` and
`pr-keeper.yml`, written weeks apart by different sessions, each solving a real problem the
same way. Removing it from one leaves the bleeding running from the other, which is exactly
what nearly happened on 2026-08-20: the first fix touched only `automerge.yml`. A third file
would do it again. This test is what refuses the third file.

Founder rule, 2026-08-20: "always merge main into feature branch before raising pr". Updating
somebody else's branch is the author's job, and no automation here does it for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: Every way this repository has actually reached the endpoint, plus the raw URL. The REST path
#: is PUT /repos/{o}/{r}/pulls/{n}/update-branch, so anything naming it is the same push.
FORBIDDEN = (
    "updateBranch",
    "update-branch",
)


def _workflows() -> list[Path]:
    return sorted(p for p in WORKFLOWS.glob("*.yml"))


def _code_only(text: str) -> str:
    """The workflow with its comment lines removed.

    Both YAML comments and the `//` comments inside an `actions/github-script` body go. The
    removals this test guards are DOCUMENTED in place -- the comment explaining why the call is
    gone names the call -- so a test reading raw text would find the prose and report the defect
    it exists to catch.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        kept.append(line)
    return "\n".join(kept)


def test_there_are_workflows_to_grade() -> None:
    assert _workflows(), f"no workflows found under {WORKFLOWS}"


@pytest.mark.parametrize("wf", _workflows(), ids=lambda p: p.name)
def test_no_workflow_updates_someone_elses_branch(wf: Path) -> None:
    code = _code_only(wf.read_text())
    found = [token for token in FORBIDDEN if token in code]
    assert not found, (
        f"{wf.name} calls {found}, which pushes a merge commit onto an open pull request's "
        f"branch.\n\n"
        f"That moves the pull request's head. GitHub closes a pull request only when its own "
        f"head commit is reachable from main, so a moved head drops it out of whatever branch "
        f"was cut to close it -- and a batch cut to clear a backlog triggers this with its own "
        f"merge, on every pull request at once. Measured 2026-08-20: fifteen pull requests, "
        f"three failed batches, thirty hours.\n\n"
        f"A branch that is behind main is its AUTHOR's to update. Label it, comment on it, "
        f"report it -- do not push to it."
    )


@pytest.mark.parametrize("wf", _workflows(), ids=lambda p: p.name)
def test_the_workflow_still_parses(wf: Path) -> None:
    """Cheap, and it catches the usual way a deletion goes wrong: a block removed by hand
    leaving the YAML valid-looking but structurally broken."""
    assert yaml.safe_load(wf.read_text()) is not None, f"{wf.name} does not parse"

"""Auto-merge must not finish green having merged nothing.

WHY THIS EXISTS. Measured 2026-08-19: PR #374 was green on every check and `mergeStateStatus`
DIRTY. `automerge.yml` caught the refused merge and called `core.warning`, so the job succeeded.
Nothing anywhere reported that finished, proven work could not land. The workflow's own header
already tells this story about `gh: command not found` -- "A workflow that silently does nothing
is worse than one that fails" -- and the very next branch down did it again.

WHAT THIS CAN AND CANNOT PROVE. It reads the workflow source. It cannot run GitHub, so it cannot
prove the job goes red in production; it proves the failure path reaches `core.setFailed` and that
the swallowing call is gone. That is the whole of what a text check is worth here, and it is
stated rather than implied. The live proof is a red automerge run on a conflicted PR.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "automerge.yml"


@pytest.fixture(scope="module")
def source() -> str:
    return WORKFLOW.read_text()


def _strip_comments(text: str) -> str:
    """Comments describe the fix; only code performs it. A source scan that reads its own
    explanation is grading the prose -- a mistake this estate has made before."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))


def test_the_workflow_exists_where_the_test_looks(source):
    """A path typo would make every assertion below vacuous."""
    assert "Auto-merge green PRs" in source


def test_a_refused_merge_fails_the_job(source):
    code = _strip_comments(source)
    assert "core.setFailed(" in code, (
        "a merge this job could not make must fail it; core.warning leaves the run green")


def test_the_old_swallowing_warning_is_gone(source):
    """The exact line that hid #374 for hours."""
    code = _strip_comments(source)
    assert not re.search(r"core\.warning\(`could not merge", code)


def test_the_failure_is_reported_even_when_nothing_merged_at_all(source):
    """`if (!merged) return` sits between the loop and the end of the script. Reporting after it
    would say nothing in the one case that matters most: a run where every PR was refused."""
    code = _strip_comments(source)
    fail_at = code.index("core.setFailed(")
    early_return = code.index("if (!merged) return")
    assert fail_at < early_return, "setFailed is unreachable when no pull request merged"


def test_a_head_that_moved_stays_a_warning(source):
    """409 means somebody pushed after CI ran. The next green run merges it, so failing the job
    would page a person about something already fixing itself."""
    code = _strip_comments(source)
    assert "e.status === 409" in code


def test_the_stuck_pull_request_is_labelled_so_it_is_visible_without_reading_logs(source):
    code = _strip_comments(source)
    assert "needs-rebase" in code
    assert "addLabels" in code


def test_the_visibility_label_does_not_also_block_the_merge(source):
    """`needs-rebase` must never join HOLD, or clearing the conflict would not be enough to land
    it and the fix would create a second stuck state."""
    hold = re.search(r"const HOLD = new Set\(\[([^\]]*)\]\)", source)
    assert hold, "the HOLD set moved; this test can no longer see it"
    assert "needs-rebase" not in hold.group(1)


def test_a_pull_request_behind_main_is_not_merged(source):
    """The stale-base failure of 2026-08-19. #372, #373 and #377 were each green on their own
    base; landing all three made main red on three tests, and all seventeen open PRs inherited
    them. `pulls.merge`'s `sha` argument only asserts the HEAD did not move -- it says nothing
    about the base -- so the refusal has to be explicit."""
    code = _strip_comments(source)
    assert "compareCommits(" in code, (
        "nothing asks whether the head is behind main, so a stale branch still merges")
    assert re.search(r"behind_by\s*>\s*0", code), (
        "behind_by is read but never used as the refusal")
    merge_at = code.index("pulls.merge(")
    behind_at = code.index("behind_by")
    assert behind_at < merge_at, "the staleness check must run before the merge, not after"


def test_an_updated_branch_gets_a_ci_run_of_its_own(source):
    """updateBranch pushes with GITHUB_TOKEN, and a GITHUB_TOKEN push starts no workflow run.
    Without the dispatch the PR is updated and then waits forever for a run that cannot exist."""
    code = _strip_comments(source)
    assert "updateBranch(" in code, "a PR behind main is never brought up to date"
    assert re.search(r"createWorkflowDispatch\(\s*\{owner, repo, workflow_id: 'ci\.yml', ref: pr\.head\.ref\}",
                     code), "the updated branch gets no CI run, so the merge can never be retried"


def test_the_job_accepts_the_runs_it_dispatches_itself(source):
    """A dispatched run's event is `workflow_dispatch`, not `pull_request`. Gating on
    `pull_request` alone would drop the very run this workflow started."""
    assert "workflow_run.event == 'workflow_dispatch'" in source, (
        "CI dispatched on an updated branch never comes back here, so nothing merges it")

"""The keeper must re-run a REFUSED build and never a FAILED one, and it proves it in node.

Two stalls that are not the author's fault, and the whole risk of fixing them:

* A branch behind main is graded against a base it does not contain. `automerge.yml` refreshes
  one only when it is already GREEN (`if (!green) continue`, automerge.yml:318), so behind-and-red
  is swept by nobody, and nothing happens at all at the moment a pull request is raised.
* `ci.yml`'s `changes` job refuses to build while main is red -- measured on job 96275945832:
  `##[error]main's CI is IN_PROGRESS at b0fe4adf.` That refusal is recorded as a FAILED run, and
  when main recovers nothing re-runs it.

The danger is the second one. "Re-run a red pull request" and "re-run a pull request that was
never actually built" look identical from the outside, and a keeper that blurs them spends a
runner to turn one red into the same red, over and over, on every merge to main. So the tests
that matter most here are the ones asserting it does NOTHING: `TestItLeavesARealFailureAlone`.

These tests EXECUTE the workflow's script in node against a stubbed Octokit rather than grepping
the YAML, for the reason in memory `the-green-guard-reverted-the-head-not-the-cause`: an
automated actor with write scopes whose decision logic had never been run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-keeper.yml"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HEAD = "1111111111111111111111111111111111111111"


def _script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text())
    for step in doc["jobs"]["keep"]["steps"]:
        if "github-script" in step.get("uses", ""):
            return step["with"]["script"]
    raise AssertionError("the workflow has no github-script step")


def pull(number=7, *, draft=False, labels=(), head_ref="feat/x", head_sha=HEAD, fork=False):
    return {
        "number": number,
        "draft": draft,
        "labels": [{"name": n} for n in labels],
        "head": {
            "sha": head_sha,
            "ref": head_ref,
            "repo": {"full_name": "someone/fork" if fork else "o/r"},
        },
    }


EARLY = "2026-08-20T00:30:00Z"  # a run that started while main was still red
MAIN_GREEN = "2026-08-20T01:00:00Z"
LATE = "2026-08-20T01:30:00Z"  # a run that started after main had recovered


def run(*, conclusion="success", status="completed", number=1, name="CI", run_id=99,
        created_at=EARLY):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion,
            "run_number": number, "created_at": created_at}


def _run(*, prs, behind=0, runs=(), jobs=(), event="workflow_run",
         update_error=None, compare_error=None, main_green_at=MAIN_GREEN) -> dict:
    """Execute the keeper in node against a stubbed Octokit and return every call it made."""
    stubs = {
        "prs": prs,
        "behind": behind,
        "runs": list(runs),
        "jobs": list(jobs),
        "event": event,
        "update_error": update_error,
        "compare_error": compare_error,
        "main_green_at": main_green_at,
    }
    harness = """
const S = %s
const calls = {dispatch: [], update: [], label: [], comment: [], cancel: []}
const logs = []
const boom = (m) => { throw new Error(m) }

const process = {env: {MAIN_GREEN_AT: S.main_green_at || ''}}
const core = {
  info: (m) => logs.push(['info', m]),
  warning: (m) => logs.push(['warning', m]),
  notice: (m) => logs.push(['notice', m]),
  setOutput: () => {},
}
const context = {
  repo: {owner: 'o', repo: 'r'},
  eventName: S.event,
  payload: {pull_request: S.prs[0]},
}
const github = {rest: {
  pulls: {
    get: async () => ({data: S.prs[0]}),
    list: async () => ({data: S.prs}),
    updateBranch: async (a) => {
      calls.update.push(a)
      if (S.update_error) boom(S.update_error)
      return {data: {}}
    },
  },
  repos: {
    compareCommits: async () => S.compare_error
      ? boom(S.compare_error) : {data: {behind_by: S.behind}},
  },
  actions: {
    listWorkflowRunsForRepo: async () => ({data: {workflow_runs: S.runs}}),
    listJobsForWorkflowRun: async () => ({data: {jobs: S.jobs}}),
    createWorkflowDispatch: async (a) => { calls.dispatch.push(a); return {data: {}} },
    cancelWorkflowRun: async (a) => { calls.cancel.push(a); return {data: {}} },
  },
  issues: {
    addLabels: async (a) => { calls.label.push(a); return {data: {}} },
    createComment: async (a) => { calls.comment.push(a); return {data: {}} },
  },
}}

const main = async () => {
%s
}
main().then(() => console.log(JSON.stringify({calls, logs})))
""" % (json.dumps(stubs), _script())
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestItRefreshesWhatIsBehindMain:
    """The founder's ask, 2026-08-20: a branch should carry main before it is judged."""

    def test_a_behind_and_red_branch_is_brought_up_to_date(self):
        out = _run(prs=[pull()], behind=4, runs=[run(conclusion="failure")],
                   jobs=[{"name": "python", "conclusion": "failure"}])
        assert len(out["calls"]["update"]) == 1
        assert out["calls"]["update"][0]["expected_head_sha"] == HEAD

    def test_the_update_is_pinned_to_the_head_it_read(self):
        """Without expected_head_sha an author's push during this run is silently overwritten."""
        out = _run(prs=[pull()], behind=1, runs=[])
        assert out["calls"]["update"][0]["expected_head_sha"] == HEAD

    def test_the_refreshed_branch_gets_ci_dispatched(self):
        """updateBranch pushes with GITHUB_TOKEN, from which GitHub starts no run. Without the
        dispatch the branch is refreshed and then graded by nobody, which is worse than before:
        its only run now describes a sha that is no longer its head."""
        out = _run(prs=[pull()], behind=2, runs=[])
        assert [d["workflow_id"] for d in out["calls"]["dispatch"]] == ["ci.yml"]
        assert out["calls"]["dispatch"][0]["ref"] == "feat/x"

    def test_a_branch_level_with_main_is_not_touched(self):
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="success")])
        assert out["calls"]["update"] == []

    def test_a_green_behind_branch_is_left_to_automerge(self):
        """automerge.yml sweeps green-and-behind and merges afterwards. Two workflows updating
        one branch at the same moment is two merge commits and a race between them."""
        out = _run(prs=[pull()], behind=5, runs=[run(conclusion="success")])
        assert out["calls"]["update"] == []
        assert out["calls"]["dispatch"] == []


class TestItReRunsARefusalAndNotAFailure:
    def test_a_build_refused_because_main_was_red_is_re_run(self):
        """`changes` is the only job that refuses on the state of ANOTHER branch, so a run in
        which it is the sole failure graded nothing about this pull request at all."""
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="failure")],
                   jobs=[{"name": "changes", "conclusion": "failure"},
                         {"name": "python", "conclusion": "skipped"}])
        assert [d["ref"] for d in out["calls"]["dispatch"]] == ["feat/x"]

    def test_the_aggregator_does_not_count_as_a_second_failure(self):
        """THE case this workflow exists for, taken from the four pull requests it was written
        against. Measured 2026-08-20, #497/#495/#489/#481 each report their failed jobs as
        exactly `changes, ci-ok` -- never `changes` alone, because `ci-ok` is the
        `if: always()` aggregator at ci.yml:1328 and restates whatever its needs did.

        The first draft of this script asked for `changes` to be the SOLE failure. It would
        have fired on none of the four, and the tests would still have been green.
        """
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="failure")],
                   jobs=[{"name": "changes", "conclusion": "failure"},
                         {"name": "ci-ok", "conclusion": "failure"}])
        assert [d["ref"] for d in out["calls"]["dispatch"]] == ["feat/x"]

    def test_a_refusal_recorded_after_main_recovered_is_not_re_run(self):
        """The loop bound. A `changes` job failing for a permanent reason of its own would
        otherwise be re-dispatched once on every merge to main, for ever, each re-run failing
        the same way and arming the next one."""
        out = _run(prs=[pull()], behind=0,
                   runs=[run(conclusion="failure", created_at=LATE)],
                   jobs=[{"name": "changes", "conclusion": "failure"},
                         {"name": "ci-ok", "conclusion": "failure"}])
        assert out["calls"]["dispatch"] == []

    def test_a_refusal_recorded_before_main_recovered_is_re_run(self):
        """The control for the test above: same shape, earlier timestamp, opposite answer."""
        out = _run(prs=[pull()], behind=0,
                   runs=[run(conclusion="failure", created_at=EARLY)],
                   jobs=[{"name": "changes", "conclusion": "failure"},
                         {"name": "ci-ok", "conclusion": "failure"}])
        assert len(out["calls"]["dispatch"]) == 1

    def test_a_head_that_was_never_built_is_dispatched(self):
        out = _run(prs=[pull()], behind=0, runs=[])
        assert len(out["calls"]["dispatch"]) == 1

    def test_a_cancelled_run_is_asked_again(self):
        """A cancelled run proves nothing in either direction, so there is nothing to act on."""
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="cancelled")])
        assert len(out["calls"]["dispatch"]) == 1

    def test_it_reads_the_newest_run_not_the_first_returned(self):
        out = _run(prs=[pull()], behind=0, runs=[
            run(conclusion="failure", number=1, run_id=1),
            run(conclusion="success", number=2, run_id=2),
        ])
        assert out["calls"]["dispatch"] == []


class TestItLeavesARealFailureAlone:
    """The tests that stop this workflow becoming a machine for burning runners on red."""

    def test_a_genuine_test_failure_is_not_re_run(self):
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="failure")],
                   jobs=[{"name": "python", "conclusion": "failure"}])
        assert out["calls"]["dispatch"] == []

    def test_a_refusal_alongside_a_real_failure_is_not_re_run(self):
        """If anything other than `changes` failed, the pull request was really graded."""
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="failure")],
                   jobs=[{"name": "changes", "conclusion": "failure"},
                         {"name": "dotnet", "conclusion": "failure"}])
        assert out["calls"]["dispatch"] == []

    def test_a_green_pull_request_is_not_re_run(self):
        out = _run(prs=[pull()], behind=0, runs=[run(conclusion="success")])
        assert out["calls"]["dispatch"] == []

    def test_a_run_still_in_flight_is_never_interrupted(self):
        """The answer is arriving. Touching the branch now throws it away and starts again."""
        out = _run(prs=[pull()], behind=9, runs=[run(status="in_progress", conclusion=None)])
        assert out["calls"]["dispatch"] == []
        assert out["calls"]["update"] == []

    def test_it_cancels_nothing_ever(self):
        """Every path here queues instead. `ci.yml` is `cancel-in-progress: false`, so a
        dispatch costs time and can never destroy another session's in-flight work -- and
        cancelling a peer's run is the specific harm this estate has already paid for."""
        out = _run(prs=[pull()], behind=3, runs=[run(conclusion="failure")],
                   jobs=[{"name": "changes", "conclusion": "failure"}])
        assert out["calls"]["cancel"] == []
        assert "cancelWorkflowRun" not in _script()


class TestItRespectsWhoOwnsTheBranch:
    def test_a_draft_is_left_alone(self):
        out = _run(prs=[pull(draft=True)], behind=6, runs=[])
        assert out["calls"]["update"] == [] and out["calls"]["dispatch"] == []

    @pytest.mark.parametrize("label", ["hold", "do-not-merge", "wip"])
    def test_a_held_pull_request_is_left_alone(self, label):
        out = _run(prs=[pull(labels=[label])], behind=6, runs=[])
        assert out["calls"]["update"] == [] and out["calls"]["dispatch"] == []

    def test_a_fork_branch_is_left_to_its_author(self):
        """This token cannot push to a fork, and updateBranch fails there in a way that reads
        as a conflict -- so it would label an innocent contributor `needs-rebase`."""
        out = _run(prs=[pull(fork=True)], behind=6, runs=[])
        assert out["calls"]["update"] == [] and out["calls"]["label"] == []

    def test_the_labels_are_read_back_and_not_taken_from_the_event(self):
        """Labels in a pull_request payload are frozen at the moment the event fired, so a
        `hold` added seconds earlier would be invisible -- memory
        `pr-labels-in-the-event-payload-are-frozen`."""
        assert "pulls.get" in _script()


class TestWhenGitCannotDoIt:
    def test_a_conflicting_branch_is_labelled_and_told_why(self):
        out = _run(prs=[pull()], behind=4, runs=[], update_error="merge conflict")
        assert out["calls"]["label"][0]["labels"] == ["needs-rebase"]
        body = out["calls"]["comment"][0]["body"]
        assert "merge conflict" in body
        assert "git rebase origin/main" in body

    def test_it_does_not_say_it_twice(self):
        """A keeper that comments on every run turns a stuck branch into an unreadable thread."""
        out = _run(prs=[pull(labels=["needs-rebase"])], behind=4, runs=[],
                   update_error="merge conflict")
        assert out["calls"]["label"] != []
        assert out["calls"]["comment"] == []

    def test_the_comment_warns_against_a_blind_force_push(self):
        """This workflow pushes a merge onto someone's branch. An author who force-pushes
        without fetching drops it, and their next push is rejected non-fast-forward."""
        out = _run(prs=[pull()], behind=4, runs=[], update_error="merge conflict")
        assert "fetch before you push" in out["calls"]["comment"][0]["body"]

    def test_one_broken_pull_request_does_not_strand_the_rest(self):
        """A keeper that throws on number three never reaches four to twenty, and the ones it
        never reached look exactly like the ones it decided to skip."""
        out = _run(prs=[pull(1), pull(2, head_ref="feat/y")], behind=0, runs=[],
                   compare_error=None)
        assert len(out["calls"]["dispatch"]) == 2

    def test_a_read_that_throws_is_a_warning_not_a_dead_job(self):
        out = _run(prs=[pull()], behind=0, runs=[], compare_error="403 from compareCommits")
        assert any(kind == "warning" for kind, _ in out["logs"])


class TestTheWorkflowItself:
    def test_it_fires_when_a_pull_request_is_raised(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        trigger = doc.get("on") or doc.get(True)
        assert set(trigger["pull_request"]["types"]) == {
            "opened", "reopened", "ready_for_review"}

    def test_it_does_not_fire_on_every_push_to_a_branch(self):
        """`synchronize` would fight the author on every push, and updateBranch itself raises
        one -- which is how a workflow updates a branch in a loop until the runner budget is
        gone."""
        doc = yaml.safe_load(WORKFLOW.read_text())
        trigger = doc.get("on") or doc.get(True)
        assert "synchronize" not in trigger["pull_request"]["types"]

    def test_it_wakes_when_main_goes_green(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        trigger = doc.get("on") or doc.get(True)
        assert trigger["workflow_run"]["workflows"] == ["CI"]
        guard = doc["jobs"]["keep"]["if"]
        assert "head_branch == 'main'" in guard
        assert "conclusion == 'success'" in guard

    def test_it_cannot_run_two_at_once(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert doc["concurrency"]["group"] == "pr-keeper"
        assert doc["concurrency"]["cancel-in-progress"] is False

    def test_it_asks_for_no_more_permission_than_it_uses(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert doc["permissions"] == {
            "contents": "write", "pull-requests": "write",
            "actions": "write", "issues": "write",
        }

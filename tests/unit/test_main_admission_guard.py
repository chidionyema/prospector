"""Nothing reaches main except through a green pull request -- and the guard proves it in node.

GitHub will not protect main on this plan. Measured 2026-08-20, both endpoints answer 403:

    gh api repos/chidionyema/prospector/branches/main/protection
    gh api repos/chidionyema/prospector/rulesets
    {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature."}

`scripts/guard_main_push.py` is the LOCAL half of the replacement and is pinned by
`tests/unit/test_main_push_guard.py`. It only protects a checkout that installed the hook, so it
cannot see a merge clicked in the GitHub UI, a `gh pr merge`, or a push from a machine that never
ran `setup_worktree.sh`. `.github/workflows/main-admission-guard.yml` is the SERVER half, and it
sees all three.

These tests EXECUTE the workflow's decide script in node against a stubbed Octokit. They do not
grep the YAML for keywords: a guard whose tests pass on a broken guard is worse than no tests,
because it reports a safety it is not providing. That lesson is memory
`the-green-guard-reverted-the-head-not-the-cause` -- an automated actor with destructive power
whose blame logic had never been run.

The behaviour that matters most is that it FAILS OPEN. Every uncertainty admits the commit. It
reverts only on positive evidence that no green CI run exists, because a guard that reverts
because of its own bug is worse than the hole it closes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "main-admission-guard.yml"

# `needs_tool`, not `skipif(shutil.which(...))`. The skipif spelling deleted this whole
# file from CI without a word for as long as the fleet ran our own runner image, which
# ships no language runtimes. tests/conftest.py::_require_tools carries the measurement.
pytestmark = pytest.mark.needs_tool("node")

ZERO = "0" * 40
SHA = "abcdef1234567890abcdef1234567890abcdef12"
HEAD = "1111111111111111111111111111111111111111"


def _script() -> str:
    """The decide step's script, lifted off disk so the test can never drift from the workflow."""
    doc = yaml.safe_load(WORKFLOW.read_text())
    for step in doc["jobs"]["admit"]["steps"]:
        if step.get("id") == "decide":
            return step["with"]["script"]
    raise AssertionError("the workflow has no step with id 'decide'")


def _run(*, commit=None, commit_error=None, branch_head=SHA, branch_error=None,
         recent=None, recent_error=None, pull=None, pull_error=None,
         runs=None, runs_error=None, after=SHA) -> dict:
    """Execute the decide script in node against a stubbed Octokit, and return its outputs.

    Every seam the script touches is a parameter, so each test can make exactly one of them
    behave badly and assert the script still admits rather than reverts.
    """
    stubs = {
        "commit": commit,
        "commit_error": commit_error,
        "branch_head": branch_head,
        "branch_error": branch_error,
        "recent": recent if recent is not None else [],
        "recent_error": recent_error,
        "pull": pull,
        "pull_error": pull_error,
        "runs": runs if runs is not None else [],
        "runs_error": runs_error,
        "after": after,
    }
    harness = """
const S = %s
const outputs = {}
const logs = []
const boom = (m) => { throw new Error(m) }

const core = {
  info: (m) => logs.push(['info', m]),
  warning: (m) => logs.push(['warning', m]),
  notice: (m) => logs.push(['notice', m]),
  setOutput: (k, v) => { outputs[k] = v },
}
const context = {
  repo: {owner: 'o', repo: 'r'},
  payload: {after: S.after},
}
const github = {rest: {
  repos: {
    getCommit: async () => S.commit_error ? boom(S.commit_error) : {data: S.commit},
    getBranch: async () => S.branch_error
      ? boom(S.branch_error) : {data: {commit: {sha: S.branch_head}}},
    listCommits: async () => S.recent_error ? boom(S.recent_error) : {data: S.recent},
  },
  pulls: {get: async () => S.pull_error ? boom(S.pull_error) : {data: S.pull}},
  actions: {listWorkflowRunsForRepo: async () => S.runs_error
    ? boom(S.runs_error) : {data: {workflow_runs: S.runs}}},
}}

;(async () => {
%s
})().then(
  () => console.log(JSON.stringify({outputs, logs})),
  (e) => { console.log(JSON.stringify({threw: String(e && e.message || e)})); }
)
""" % (json.dumps(stubs), _script())
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr[-800:]}"
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "threw" not in result, f"the decide script threw: {result['threw']}"
    return result


def _commit(subject, *, body="", parents=1, author="Someone"):
    message = subject if not body else f"{subject}\n\n{body}"
    return {
        "commit": {"message": message, "author": {"name": author}},
        "parents": [{"sha": f"p{i}"} for i in range(parents)],
    }


def _green_pr(number=451):
    return (
        _commit(f"feat(thing): do the thing (#{number})"),
        {"head": {"sha": HEAD}},
        [{"id": 99, "name": "CI", "conclusion": "success", "status": "completed"}],
    )


class TestItRejectsWhatWasNeverProved:
    def test_a_commit_naming_no_pull_request_is_reverted(self):
        """A plain `git push origin main`. The local hook cannot see one from another machine."""
        out = _run(commit=_commit("fix(thing): pushed straight to main"))["outputs"]
        assert out["go"] == "yes"
        assert "pushed straight to main" in out["why"]
        assert out["sha"] == SHA

    def test_a_pull_request_with_no_green_ci_run_is_reverted(self):
        """This is #460, exactly: merged by hand at 22:05 with its own run already failing."""
        out = _run(
            commit=_commit("fix(triage): register the tool (#460)"),
            pull={"head": {"sha": HEAD}},
            runs=[{"id": 7, "name": "CI", "conclusion": "failure", "status": "completed"}],
        )["outputs"]
        assert out["go"] == "yes"
        assert "#460" in out["why"] and "failure" in out["why"]

    def test_a_pull_request_with_no_ci_run_at_all_is_reverted(self):
        """A parked run produces zero jobs and never concludes; it is not evidence of anything."""
        out = _run(
            commit=_commit("feat(x): y (#471)"),
            pull={"head": {"sha": HEAD}}, runs=[],
        )["outputs"]
        assert out["go"] == "yes"
        assert "no CI run at all" in out["why"]

    def test_a_cancelled_ci_run_is_not_a_green_one(self):
        """`conclusion` has six values. A guard that only knows `failure` is blind to four."""
        out = _run(
            commit=_commit("feat(x): y (#472)"),
            pull={"head": {"sha": HEAD}},
            runs=[{"id": 8, "name": "CI", "conclusion": "cancelled", "status": "completed"}],
        )["outputs"]
        assert out["go"] == "yes"

    def test_a_green_run_of_some_other_workflow_does_not_count(self):
        """Auto-merge and the deploys are green constantly. Only CI grades the code."""
        out = _run(
            commit=_commit("feat(x): y (#473)"),
            pull={"head": {"sha": HEAD}},
            runs=[{"id": 9, "name": "Auto-merge green PRs", "conclusion": "success"}],
        )["outputs"]
        assert out["go"] == "yes"

    def test_the_reverted_commit_carries_enough_to_write_the_issue(self):
        out = _run(commit=_commit("fix: direct", author="Ada"))["outputs"]
        assert out["sha"] == SHA
        assert out["subject"] == "fix: direct"
        assert out["author"] == "Ada"
        assert out["parents"] == "1"


class TestItAdmitsWhatWasProved:
    def test_a_squash_merge_with_a_green_run_is_admitted(self):
        commit, pull, runs = _green_pr()
        out = _run(commit=commit, pull=pull, runs=runs)["outputs"]
        assert out["go"] == "no"
        assert "proved green by run 99" in out["why"]

    def test_a_merge_commit_is_read_the_same_way(self):
        out = _run(
            commit=_commit("Merge pull request #451 from o/branch", parents=2),
            pull={"head": {"sha": HEAD}},
            runs=[{"id": 99, "name": "CI", "conclusion": "success"}],
        )["outputs"]
        assert out["go"] == "no"

    def test_the_founder_override_trailer_admits_a_direct_push(self):
        out = _run(commit=_commit(
            "hotfix: stop the bleeding",
            body="Founder-override: production is down and the queue can wait"))["outputs"]
        assert out["go"] == "no"
        assert "Founder-override" in out["why"]

    def test_a_revert_is_admitted_so_two_guards_cannot_loop(self):
        """main-green-guard.yml putting main back. Reverting the repair restores the breakage."""
        out = _run(commit=_commit('Revert "feat(x): the thing that broke main"'))["outputs"]
        assert out["go"] == "no"
        assert "is a revert" in out["why"]

    def test_closes_in_the_body_never_credits_an_unrelated_pull_request(self):
        """The SUBJECT only. A body saying `Closes #451` on a direct push must not admit it."""
        out = _run(commit=_commit(
            "fix: pushed by hand", body="Closes #451\n\nsome more text"))["outputs"]
        assert out["go"] == "yes"
        assert "names no pull request" in out["why"]


class TestItFailsOpen:
    """Every uncertainty admits. A guard that reverts on its own bug is worse than the hole."""

    def test_an_unreadable_commit_admits(self):
        out = _run(commit_error="HTTP 502")["outputs"]
        assert out["go"] == "no"
        assert "failing open" in out["why"]

    def test_an_unreadable_branch_head_admits(self):
        out = _run(commit=_commit("fix: direct"), branch_error="HTTP 502")["outputs"]
        assert out["go"] == "no"
        assert "failing open" in out["why"]

    def test_an_unreadable_commit_list_admits(self):
        out = _run(commit=_commit("fix: direct"), recent_error="HTTP 403")["outputs"]
        assert out["go"] == "no"
        assert "failing open" in out["why"]

    def test_a_pull_request_it_cannot_read_admits(self):
        out = _run(commit=_commit("feat: x (#999)"), pull_error="HTTP 404")["outputs"]
        assert out["go"] == "no"
        assert "failing open" in out["why"]

    def test_a_run_list_it_cannot_read_admits(self):
        out = _run(
            commit=_commit("feat: x (#451)"),
            pull={"head": {"sha": HEAD}}, runs_error="HTTP 403")["outputs"]
        assert out["go"] == "no"
        assert "failing open" in out["why"]

    def test_a_parentless_commit_admits_because_it_could_not_be_reverted(self):
        out = _run(commit=_commit("initial commit", parents=0))["outputs"]
        assert out["go"] == "no"
        assert "no parent" in out["why"]


class TestItWillNotRaceOrStorm:
    def test_it_stands_down_once_main_has_moved_on(self):
        """Somebody is already dealing with it. Never race a human."""
        out = _run(commit=_commit("fix: direct"), branch_head="deadbeef" * 5)["outputs"]
        assert out["go"] == "no"
        assert "already moved" in out["why"]

    def test_one_revert_per_hour(self):
        out = _run(
            commit=_commit("fix: direct"),
            recent=[{"sha": "9" * 40, "commit": {
                "message": 'Revert "x"\n\nReverted by main-admission-guard: because'}}],
        )["outputs"]
        assert out["go"] == "no"
        assert "within the" in out["why"] and "hour" in out["why"]

    def test_another_guards_revert_does_not_count_against_this_one(self):
        """main-green-guard's reverts are its own. Sharing the counter would disarm both."""
        out = _run(
            commit=_commit("fix: direct"),
            recent=[{"sha": "8" * 40, "commit": {
                "message": 'Revert "y"\n\nReverted by main-green-guard: because'}}],
        )["outputs"]
        assert out["go"] == "yes"


class TestTheWorkflowItself:
    def test_it_fires_on_a_push_to_main(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        # `on` is YAML 1.1's boolean true, which is why this is not doc["on"].
        trigger = doc.get("on") or doc.get(True)
        assert trigger["push"]["branches"] == ["main"]

    def test_a_branch_deletion_is_not_graded(self):
        """A delete pushes the zero sha and there is nothing to grade."""
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert ZERO in doc["jobs"]["admit"]["if"]

    def test_it_cannot_run_two_at_once(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert doc["concurrency"]["group"] == "main-admission-guard"
        assert doc["concurrency"]["cancel-in-progress"] is False

    def test_the_issue_is_opened_before_the_push(self):
        """A revert nobody was told about is how work disappears."""
        doc = yaml.safe_load(WORKFLOW.read_text())
        names = [s.get("name", "") for s in doc["jobs"]["admit"]["steps"]]
        assert names.index("Open the issue first, so the revert can never be silent") < \
            names.index("Revert it and push")

    def test_it_asks_for_no_more_permission_than_it_uses(self):
        """Every scope here is spent, and none of the ones absent is.

        `actions` was `read` until 2026-08-20 and is now `write`, for one measured reason: a
        `GITHUB_TOKEN` push starts no workflow run, so after the revert nothing re-deploys and
        nothing re-grades main by itself. The repair has to be dispatched, and a dispatch is a
        write. `packages` and `deployments` stay absent -- this workflow touches neither.
        """
        doc = yaml.safe_load(WORKFLOW.read_text())
        assert doc["permissions"] == {
            "contents": "write", "actions": "write",
            "pull-requests": "read", "issues": "write",
        }


class TestItPutsTheEstateBackAndNotJustGit:
    """Reverting git is not reverting production, and that gap is what this class pins.

    The bad commit's own push fires the deploy workflows immediately, so production is already
    running the code by the time the guard reverts it. The revert push cannot start anything --
    GitHub creates no run from a `GITHUB_TOKEN` push -- so without an explicit dispatch the fix
    reaches production only when some unrelated merge next happens to ship it.
    """

    def _repair(self) -> str:
        doc = yaml.safe_load(WORKFLOW.read_text())
        for step in doc["jobs"]["admit"]["steps"]:
            if step.get("name") == "Put the estate back, not just git":
                return step["with"]["script"]
        raise AssertionError("the workflow no longer repairs the estate after a revert")

    def test_the_repair_runs_only_when_something_was_reverted(self):
        doc = yaml.safe_load(WORKFLOW.read_text())
        step = next(s for s in doc["jobs"]["admit"]["steps"]
                    if s.get("name") == "Put the estate back, not just git")
        assert step["if"] == "steps.decide.outputs.go == 'yes'"

    def test_the_repair_runs_after_the_push_and_not_before(self):
        """Dispatching CI on main before the revert lands grades the commit being deleted."""
        doc = yaml.safe_load(WORKFLOW.read_text())
        names = [s.get("name", "") for s in doc["jobs"]["admit"]["steps"]]
        assert names.index("Revert it and push") < \
            names.index("Put the estate back, not just git")

    def test_it_re_grades_main(self):
        """Without this, main's newest CI conclusion stays the red one at the deleted sha, and
        `ci.yml`'s `changes` job goes on refusing every open pull request because of it."""
        assert "'ci.yml'" in self._repair()

    def test_it_cancels_the_ci_run_at_the_reverted_sha(self):
        """ci.yml on main is `cancel-in-progress: false`, so the repair run would otherwise
        queue behind a run that is grading a commit no longer on main."""
        script = self._repair()
        assert "cancelWorkflowRun" in script
        assert "run.status === 'completed'" in script

    def test_it_never_cancels_a_deploy(self):
        """Measured 2026-08-20: the three deploy workflows are all `cancel-in-progress: false`,
        so the repair queues behind a bad deploy in flight and converges. Cancelling one
        mid-run instead would leave a half-deployed app."""
        script = self._repair()
        for wf in ("deploy-engine.yml", "deploy-web.yml", "deploy-api.yml"):
            assert wf in script
        # The only cancel in the script is guarded by a CI name check.
        assert script.count("cancelWorkflowRun") == 1
        assert "run.name !== 'CI'" in script

    # DELETED 2026-08-20: test_the_deploy_map_has_not_drifted_from_automerge and
    # test_the_deploy_inputs_have_not_drifted_from_automerge.
    #
    # Both compared this workflow's DEPLOY/INPUTS objects against a SECOND copy of them in
    # .github/workflows/automerge.yml. That file was deleted on founder decision the same day,
    # so there is no second copy to drift from and the comparison could only ever fail.
    #
    # The map still needs grading, and it is graded better now: it is compared against the three
    # deploy workflows' OWN `on.push.paths`, in both directions, by
    # tests/unit/test_every_deploy_ships_on_green_main.py. That is the source the two copies were
    # both hand-transcribed from, so checking against it catches a drift that agreeing copies
    # would have hidden.

    def test_a_failed_dispatch_does_not_fail_the_job(self):
        """The revert is already pushed by this point. Throwing here would leave the run red
        over the recoverable half of the work and hide that the important half succeeded."""
        script = self._repair()
        assert "core.warning(`could not dispatch" in script
        assert "run it by hand" in script

    def test_a_truncated_file_list_deploys_everything(self):
        """`getCommit` returns at most 300 files. Reading a truncated list as the whole truth
        would skip the deploy for a path that fell off the end."""
        script = self._repair()
        assert "files.length >= 300" in script
        assert "paths === null || paths.some(" in script

    def test_the_repair_is_written_into_the_issue(self):
        """A repair nobody can see is a repair nobody can check."""
        assert "createComment" in self._repair()

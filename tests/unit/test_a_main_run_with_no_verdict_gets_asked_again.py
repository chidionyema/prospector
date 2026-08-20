"""A cancelled CI run on main leaves main's colour UNKNOWN, and nothing used to look.

`main-green-guard.yml`'s other two jobs both require `conclusion == 'failure'`. Measured
2026-08-20: main's runs at 802a2e4b and fe6fcd13 both ended `cancelled` with zero jobs, so the
guard skipped (runs 32314822031 and 32314849990). Main was red on two tests for the whole of
that time with no machine watching, because "red" was never established.

An unknown main is a non-green main to `ci.yml`'s `changes` step, so every pull request skipped
every build job -- and a skipped job renders neutral grey rather than red. Four pull requests
were merged by hand on that appearance.

These tests execute the `restart` job's own script in node against a stubbed Octokit. They pin
the three things that make it safe: it asks for a verdict and never reverts, it stands aside
when main's verdict is already coming, and it stops after MAX_ATTEMPTS rather than fighting a
person who cancelled a run on purpose.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "main-green-guard.yml"
SHA = "a2e35ae2a62e0000000000000000000000000000"
OTHER = "802a2e4b00000000000000000000000000000000"

HARNESS = r"""
const scenario = JSON.parse(process.argv[2])
const script = process.argv[3]

const calls = {dispatched: [], issues: [], infos: [], notices: [], warnings: [],
               errors: [], failed: []}
const core = {
  info: m => calls.infos.push(String(m)),
  notice: m => calls.notices.push(String(m)),
  warning: m => calls.warnings.push(String(m)),
  error: m => calls.errors.push(String(m)),
  setFailed: m => calls.failed.push(String(m)),
}
const context = {repo: {owner: 'chidionyema', repo: 'prospector'},
                 payload: {workflow_run: scenario.workflow_run}}
const github = {rest: {
  actions: {
    listWorkflowRuns: async () => {
      if (scenario.listThrows) throw new Error(scenario.listThrows)
      return {data: {workflow_runs: scenario.runs || []}}
    },
    createWorkflowDispatch: async a => {
      if (scenario.dispatchThrows) throw new Error(scenario.dispatchThrows)
      calls.dispatched.push(a)
    },
  },
  issues: {
    create: async a => {
      if (scenario.issueThrows) throw new Error(scenario.issueThrows)
      calls.issues.push(a)
    },
  },
}}

const body = new Function('github', 'context', 'core',
  '"use strict"; return (async () => {' + script + '})()')
body(github, context, core)
  .then(() => process.stdout.write(JSON.stringify(calls)))
  .catch(e => process.stdout.write(JSON.stringify({...calls, threw: String(e && e.message)})))
"""


def _doc():
    return yaml.safe_load(WORKFLOW.read_text())


def _script() -> str:
    steps = _doc()["jobs"]["restart"]["steps"]
    return textwrap.dedent(steps[0]["with"]["script"])


def _run(scenario: dict, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS)
    proc = subprocess.run(
        [node, str(harness), json.dumps(scenario), _script()],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout, proc.stderr
    out = json.loads(proc.stdout)
    assert "threw" not in out, out["threw"]
    return out


def _wr(conclusion="cancelled", sha=SHA):
    return {"conclusion": conclusion, "head_sha": sha, "head_branch": "main"}


def _row(run_id, sha=SHA, status="completed", conclusion="cancelled"):
    return {"id": run_id, "head_sha": sha, "status": status, "conclusion": conclusion}


class TestItAsksForTheVerdictAgain:
    def test_a_cancelled_main_run_is_dispatched_again(self, tmp_path):
        out = _run({"workflow_run": _wr(),
                    "runs": [_row(32311937136)]}, tmp_path)
        assert len(out["dispatched"]) == 1
        assert out["dispatched"][0]["workflow_id"] == "ci.yml"
        assert out["dispatched"][0]["ref"] == "main"
        assert any("attempt 2 of 3" in n for n in out["notices"]), out["notices"]

    def test_it_never_reverts_anything(self, tmp_path):
        """The whole point. A cancelled run is not evidence that the code is wrong."""
        out = _run({"workflow_run": _wr(), "runs": [_row(1)]}, tmp_path)
        assert out["dispatched"] and not out["issues"] and not out["failed"]

    def test_runs_at_other_commits_do_not_count_towards_the_ceiling(self, tmp_path):
        """Otherwise a busy main exhausts the budget for a commit that never got one run."""
        out = _run({"workflow_run": _wr(),
                    "runs": [_row(1, sha=OTHER), _row(2, sha=OTHER), _row(3, sha=OTHER)]},
                   tmp_path)
        assert len(out["dispatched"]) == 1


class TestItStandsAsideWhenMainIsAlreadyAnswering:
    def test_a_queued_main_run_means_the_verdict_is_coming(self, tmp_path):
        out = _run({"workflow_run": _wr(),
                    "runs": [_row(99, status="queued", conclusion=None), _row(1)]}, tmp_path)
        assert out["dispatched"] == []
        assert any("already has 1 CI run" in i for i in out["infos"]), out["infos"]

    def test_an_in_progress_main_run_means_the_same(self, tmp_path):
        out = _run({"workflow_run": _wr(),
                    "runs": [_row(99, status="in_progress", conclusion=None)]}, tmp_path)
        assert out["dispatched"] == []


class TestItStopsRatherThanFightingAPerson:
    def test_the_third_verdictless_run_opens_an_issue_instead_of_a_fourth(self, tmp_path):
        out = _run({"workflow_run": _wr(),
                    "runs": [_row(1), _row(2), _row(3)]}, tmp_path)
        assert out["dispatched"] == []
        assert len(out["issues"]) == 1
        assert "a2e35ae2" in out["issues"][0]["title"]
        assert out["errors"], "the ceiling must be reported, not swallowed"

    def test_a_refused_issue_does_not_crash_the_job(self, tmp_path):
        out = _run({"workflow_run": _wr(), "runs": [_row(1), _row(2), _row(3)],
                    "issueThrows": "403 no issues scope"}, tmp_path)
        assert out["dispatched"] == [] and out["warnings"]


class TestItFailsSafe:
    def test_an_unreadable_run_list_does_not_dispatch_and_does_not_fail_the_job(self, tmp_path):
        """A guard that cannot read must not also block, and must not act on nothing."""
        out = _run({"workflow_run": _wr(), "listThrows": "403 forbidden"}, tmp_path)
        assert out["dispatched"] == [] and out["failed"] == []
        assert any("could not list" in w for w in out["warnings"]), out["warnings"]

    def test_a_refused_dispatch_is_reported_as_a_failure(self, tmp_path):
        """This one MUST be loud: main is stuck with no verdict and nothing else is looking."""
        out = _run({"workflow_run": _wr(), "runs": [_row(1)],
                    "dispatchThrows": "422 workflow disabled"}, tmp_path)
        assert out["failed"], out


class TestTheTriggerCoversEveryVerdictlessEnding:
    def test_it_fires_on_cancelled_timed_out_and_stale(self):
        cond = _doc()["jobs"]["restart"]["if"]
        for word in ("cancelled", "timed_out", "stale"):
            assert f"'{word}'" in cond, f"{word} is a verdictless ending and must be covered"

    def test_it_only_ever_looks_at_main(self):
        cond = _doc()["jobs"]["restart"]["if"]
        assert "head_branch == 'main'" in cond

    def test_failure_stays_with_the_jobs_that_can_revert(self):
        """`failure` is a verdict. Restarting it would loop against a genuinely broken main."""
        assert "'failure'" not in _doc()["jobs"]["restart"]["if"]

    def test_the_job_runs_no_shell_and_checks_nothing_out(self):
        """Its only power is `createWorkflowDispatch`. Keep it that way."""
        steps = _doc()["jobs"]["restart"]["steps"]
        assert len(steps) == 1
        assert steps[0]["uses"].startswith("actions/github-script@")
        assert "run" not in steps[0] and "with" in steps[0]

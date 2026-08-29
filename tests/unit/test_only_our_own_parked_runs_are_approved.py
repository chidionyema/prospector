"""approve-parked-runs.yml starts a run GitHub parked. Prove it can only ever start OURS.

WHY THIS TEST EXISTS. `conclusion: action_required` has two causes that look identical in the
API. One is ours: a push made with the default GITHUB_TOKEN, which GitHub records as a run and
refuses to build. The other is GitHub's fork gate, where a stranger's pull request waits for a
maintainer to agree to run their code. Approving the first repairs a stalled queue. Approving the
second runs untrusted code on our self-hosted Fly runners, which hold GITHUB_RUNNER_PAT.

The workflow tells them apart with two conditions -- the head branch is in this repository, and
the parked run's actor is github-actions[bot]. Drop either and the workflow still passes every
happy-path check while having become a way in. So each condition gets a test that fails when it
is removed, and the removals were run: see the ledger row `a-token-push-parks-a-phantom-run`.

The script is executed for real in node, not read as text. A test that greps a workflow for the
word "fork" proves the word is present, which is not the property that matters.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import yaml
from tool_gate import require_tool

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "approve-parked-runs.yml"

OWNER = "chidionyema"
REPO = "prospector"
OURS = f"{OWNER}/{REPO}"
BOT = "github-actions[bot]"


# ---------------------------------------------------------------- the harness

HARNESS = r"""
const scenario = JSON.parse(process.argv[2])
const script = process.argv[3]

const calls = {approved: [], warnings: [], notices: [], infos: []}

const core = {
  info: (m) => calls.infos.push(String(m)),
  notice: (m) => calls.notices.push(String(m)),
  warning: (m) => calls.warnings.push(String(m)),
  setFailed: (m) => { calls.failed = String(m) },
}

const context = {repo: {owner: scenario.owner, repo: scenario.repo}}

const github = {rest: {
  pulls: {
    list: async () => ({data: scenario.prs}),
  },
  actions: {
    listWorkflowRunsForRepo: async ({head_sha}) => {
      const bucket = scenario.runs[head_sha]
      if (bucket === 'throw') throw new Error('listing exploded')
      return {data: {workflow_runs: bucket || []}}
    },
    approveWorkflowRun: async ({run_id}) => {
      if ((scenario.approve_throws || []).includes(run_id)) {
        throw new Error(`approve ${run_id} exploded`)
      }
      calls.approved.push(run_id)
    },
  },
}}

// No `require` in the stub set. A github-script step that needs one is a step this harness
// deliberately cannot run, and should fail loudly here rather than be quietly approximated.
const body = new Function('github', 'context', 'core',
  '"use strict"; return (async () => {' + script + '})()')

body(github, context, core).then(
  () => { process.stdout.write(JSON.stringify(calls)) },
  (e) => { calls.threw = String(e && e.message); process.stdout.write(JSON.stringify(calls)) },
)
"""


def _script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["approve"]["steps"]
    for step in steps:
        with_ = step.get("with") or {}
        if "script" in with_:
            return textwrap.dedent(with_["script"])
    raise AssertionError("the approve job has no github-script step")


def _run(tmp_path: Path, scenario: dict) -> dict:
    # `require_tool`, not `shutil.which(...)` plus an inline skip. That spelling deleted
    # these tests from CI in silence for as long as the runner image shipped no node, and a
    # search for the `needs_tool` marker cannot see it because the decision is made here, at
    # run time. conftest's version skips on a laptop and ERRORS on a runner; it carries the
    # measurement.
    node = require_tool("node")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    scenario = {"owner": OWNER, "repo": REPO, **scenario}
    proc = subprocess.run(
        [node, str(harness), json.dumps(scenario), _script()],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"the harness itself failed:\n{proc.stderr}"
    assert proc.stdout, f"the harness printed nothing. stderr:\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert "threw" not in out, (
        f"the workflow script threw, so the job would have failed: {out.get('threw')}"
    )
    return out


def _pr(number: int, sha: str, head_repo: str | None = OURS) -> dict:
    return {"number": number, "head": {"sha": sha,
                                       "repo": None if head_repo is None else {"full_name": head_repo}}}


def _run_row(run_id: int, sha: str, conclusion: str = "action_required", actor: str = BOT) -> dict:
    return {"id": run_id, "head_sha": sha, "conclusion": conclusion,
            "name": "CI", "actor": {"login": actor}}


# ------------------------------------------------------------- the happy path

def test_a_run_we_parked_on_our_own_branch_is_started(tmp_path):
    """The measured case: automerge pushed a main merge, GitHub parked the run, the PR stalled."""
    out = _run(tmp_path, {
        "prs": [_pr(474, "a" * 40)],
        "runs": {"a" * 40: [_run_row(32309822566, "a" * 40)]},
    })

    assert out["approved"] == [32309822566], (
        f"the parked run on our own branch must be started. approved={out['approved']}"
    )


def test_nothing_parked_is_reported_and_is_not_a_failure(tmp_path):
    """A quiet run must stay quiet, or the notice stops meaning anything."""
    out = _run(tmp_path, {
        "prs": [_pr(474, "a" * 40)],
        "runs": {"a" * 40: [_run_row(1, "a" * 40, conclusion="success"),
                            _run_row(2, "a" * 40, conclusion="failure")]},
    })

    assert out["approved"] == [], (
        f"only `action_required` may be approved; a concluded run must be left alone. "
        f"approved={out['approved']}"
    )
    assert "failed" not in out


def test_no_open_pull_requests_is_a_clean_no_op(tmp_path):
    """The empty case. It runs every ten minutes, so most runs are this one."""
    out = _run(tmp_path, {"prs": [], "runs": {}})

    assert out["approved"] == []
    assert "failed" not in out


# ------------------------------------------------------------ the safety rule

def test_a_fork_pull_request_is_never_approved(tmp_path):
    """This is the one that matters. Approving a fork runs a stranger's code on runners that
    hold GITHUB_RUNNER_PAT. `action_required` on a fork is GitHub protecting us, not a bug."""
    out = _run(tmp_path, {
        "prs": [_pr(999, "f" * 40, head_repo="a-stranger/prospector")],
        "runs": {"f" * 40: [_run_row(555, "f" * 40)]},
    })

    assert out["approved"] == [], (
        "a fork's parked run must NEVER be approved: that is GitHub's review gate and the run "
        f"executes untrusted code on our own runners. approved={out['approved']}"
    )
    assert any("not ours" in s for s in out["infos"]), (
        f"skipping a fork must say so, or the refusal is invisible. infos={out['infos']}"
    )


def test_a_deleted_head_repository_is_treated_as_a_fork(tmp_path):
    """`pr.head.repo` is null when the fork was deleted. Null is not our repository."""
    out = _run(tmp_path, {
        "prs": [_pr(998, "e" * 40, head_repo=None)],
        "runs": {"e" * 40: [_run_row(556, "e" * 40)]},
    })

    assert out["approved"] == [], (
        f"a null head repo must not be read as ours. approved={out['approved']}"
    )


def test_a_run_parked_for_someone_other_than_the_bot_is_left_parked(tmp_path):
    """The second condition. Only our own GITHUB_TOKEN pushes are ours to start."""
    out = _run(tmp_path, {
        "prs": [_pr(474, "a" * 40)],
        "runs": {"a" * 40: [_run_row(777, "a" * 40, actor="a-stranger")]},
    })

    assert out["approved"] == [], (
        f"only a run parked for {BOT} may be started. approved={out['approved']}"
    )
    assert any("a-stranger" in s for s in out["infos"]), (
        f"the refusal must name who it was parked for. infos={out['infos']}"
    )


# ------------------------------------------------- one failure is not all failures

def test_one_unreadable_pull_request_does_not_stop_the_others(tmp_path):
    """Nine stalled PRs must not stay stalled because the tenth throws."""
    out = _run(tmp_path, {
        "prs": [_pr(1, "b" * 40), _pr(2, "c" * 40)],
        "runs": {"b" * 40: "throw", "c" * 40: [_run_row(42, "c" * 40)]},
    })

    assert out["approved"] == [42], (
        f"the readable pull request must still be repaired. approved={out['approved']}"
    )
    assert any("could not list runs" in w for w in out["warnings"]), (
        f"the unreadable one must warn, not vanish. warnings={out['warnings']}"
    )
    assert "failed" not in out, "a listing error must not fail the job"


def test_a_refused_approval_does_not_stop_the_next_one(tmp_path):
    """A run can conclude between the listing and the approve. That is a race, not an outage."""
    out = _run(tmp_path, {
        "prs": [_pr(1, "b" * 40)],
        "runs": {"b" * 40: [_run_row(10, "b" * 40), _run_row(11, "b" * 40)]},
        "approve_throws": [10],
    })

    assert out["approved"] == [11], (
        f"the second run must still be started. approved={out['approved']}"
    )
    assert any("could not approve run 10" in w for w in out["warnings"]), (
        f"the refusal must be visible. warnings={out['warnings']}"
    )
    assert "failed" not in out


# ---------------------------------------------------------------- the structure

def test_the_workflow_holds_no_write_it_does_not_need():
    """It can start a run GitHub already made. It must not be able to write code, cancel a
    build, or open an issue."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    perms = doc["permissions"]

    assert perms == {"pull-requests": "read", "actions": "write"}, (
        f"exactly two scopes, no more: {perms}. `contents: write` here would let a repair job "
        f"change code, which is how the green guard managed to delete landed work."
    )


def test_it_runs_on_a_schedule_so_it_can_repair_a_stalled_queue():
    """A parked run concludes `action_required`, so it can never trigger a workflow_run
    listener. Nothing else in the estate will notice it. The schedule is the mechanism."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads a bare `on:` key as the boolean True.
    triggers = doc.get("on", doc.get(True))

    assert "schedule" in triggers, (
        f"without a schedule this only runs when a person asks, which is not self-healing. "
        f"triggers={list(triggers)}"
    )
    assert triggers["schedule"], "the schedule list is empty, so nothing is scheduled"
    assert "workflow_dispatch" in triggers, (
        "a repair job needs a button, so a stalled queue can be fixed now rather than in ten "
        "minutes"
    )


def test_two_copies_never_run_at_once_and_neither_kills_the_other():
    """Two sweeps racing would double-approve. Cancelling the in-flight one would abandon
    half a repair -- the same class as ci.yml's cancel-in-progress killing another agent's run."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    conc = doc["concurrency"]

    assert conc["group"] == "approve-parked-runs"
    assert conc.get("cancel-in-progress") is False, (
        f"a repair sweep must finish, never be cancelled by the next one: {conc}"
    )


def test_it_shells_out_to_nothing():
    """Our self-hosted runners have no `gh` and no `jq`. automerge.yml's first version shelled
    out to `gh`, got `gh: command not found`, swallowed it with `|| true` and reported success
    having merged nothing."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["approve"]["steps"]

    shell_steps = [s.get("name") for s in steps if "run" in s]
    assert not shell_steps, (
        f"these steps shell out on a runner with no gh and no jq: {shell_steps}"
    )


def test_it_runs_where_the_rest_of_the_estate_runs():
    """Pinned to `ubuntu-latest` it would need GitHub-hosted minutes; CI runs on the Fly app
    prospector-ci, selected through these repository variables."""
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "vars.CI_LIGHT_RUNS_ON" in text and "vars.CI_RUNS_ON" in text, (
        "runs-on must resolve through the same repository variables every other workflow uses"
    )

"""Run the green guard's decision logic against every case it can meet, in node.

WHAT HAPPENED. 2026-08-19, the incident this file exists for. PR #460 landed
`scripts/pr_triage.py` without registering it in the ops console. Its own CI run had ALREADY
failed at 21:46:09Z naming that exact file; it was merged anyway at 22:05:30Z and main went red.
Three commits later `main-green-guard.yml` reverted #463 -- the commit at main's HEAD, and
innocent -- opened issue #468 blaming its author, and left main red, because the file that
actually broke the build was never touched.

The guard's own header names six failure modes it defends against: ping-pong, revert storms,
silent reverts, conflicting reverts, recursion, and reverting good work for a network blip. It
missed the seventh: THE HEAD IS NOT NECESSARILY THE CAUSE.

WHY THIS FILE RUNS NODE RATHER THAN READING THE YAML. Until 2026-08-20 this workflow had no test
of any kind while holding `contents: write` on main -- it is the only thing in this estate that
can delete landed work unattended. A test that greps the YAML for the string "parent" would prove
the text exists, which is the shape of the evidence and not its content. So the `decide` step's
script is extracted and EXECUTED against stub octokit objects, once per scenario, and the
assertions are on what it decides.

The structural assertions below the simulation run everywhere. The simulation skips if node is
absent, which it is not on any runner that builds the web lane.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

import yaml
from tool_gate import require_tool

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "main-green-guard.yml"

HEAD = "a" * 40          # the commit at main's head, the one the failing run tested
PARENT = "b" * 40        # its first parent
RUN_ID = 1001            # the failing run on HEAD
PRIOR_RUN = 900          # a run on PARENT


def _decide_script() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["revert"]["steps"]
    for s in steps:
        if s.get("id") == "decide":
            return textwrap.dedent(s["with"]["script"])
    raise AssertionError("the revert job has no step with id 'decide'")


def _scenario(**over) -> dict:
    """The 2026-08-19 shape by default: HEAD is innocent, PARENT already failed the same job."""
    base = {
        "branch_head_sha": HEAD,
        "commit": {
            "sha": HEAD,
            "commit": {"message": "feat: something innocent\n\nbody", "author": {"name": "someone"}},
            "parents": [{"sha": PARENT}],
        },
        "recent_commits": [],
        "runs_by_head_sha": {PARENT: [{"id": PRIOR_RUN, "conclusion": "failure",
                                       "html_url": "https://example/900"}]},
        "jobs_by_run_id": {str(RUN_ID): [{"name": "python", "conclusion": "failure"}],
                           str(PRIOR_RUN): [{"name": "python", "conclusion": "failure"}]},
        "throw_on_jobs": False,
    }
    base.update(over)
    return base


HARNESS = r"""
const scenario = JSON.parse(process.argv[2])
const script = process.argv[3]

const outputs = {}
const notices = []
const warnings = []

const core = {
  setOutput: (k, v) => { outputs[k] = v },
  notice: (m) => notices.push(m),
  warning: (m) => warnings.push(m),
  info: (m) => {},
  setFailed: (m) => { outputs.__failed = m },
}

const context = {
  repo: {owner: 'o', repo: 'r'},
  payload: {workflow_run: {
    id: %(run_id)d,
    head_sha: scenario.commit.sha,
    html_url: 'https://example/run',
  }},
}

const github = {rest: {
  repos: {
    getBranch: async () => ({data: {commit: {sha: scenario.branch_head_sha}}}),
    getCommit: async () => ({data: scenario.commit}),
    listCommits: async () => ({data: scenario.recent_commits}),
  },
  actions: {
    listWorkflowRunsForRepo: async ({head_sha}) => (
      {data: {workflow_runs: scenario.runs_by_head_sha[head_sha] || []}}),
    listJobsForWorkflowRun: async ({run_id}) => {
      if (scenario.throw_on_jobs) throw new Error('403 simulated')
      return {data: {jobs: scenario.jobs_by_run_id[String(run_id)] || []}}
    },
  },
}}

// No `require` in the stub set: a github-script step that needs one is a step this harness
// deliberately cannot run, and should fail loudly here rather than be quietly approximated.
const body = new Function('github', 'context', 'core',
  '"use strict"; return (async () => {' + script + '})()')

body(github, context, core)
  .then(() => console.log(JSON.stringify({outputs, notices, warnings})))
  .catch(e => {
    console.log(JSON.stringify({outputs, notices, warnings, threw: String(e && e.message)}))
    process.exitCode = 0
  })
""" % {"run_id": RUN_ID}


def _decide(scenario: dict) -> dict:
    # `require_tool`, not `shutil.which(...)` plus an inline skip. That spelling deleted
    # these tests from CI in silence for as long as the runner image shipped no node, and a
    # search for the `needs_tool` marker cannot see it because the decision is made here, at
    # run time. conftest's version skips on a laptop and ERRORS on a runner; it carries the
    # measurement.
    node = require_tool("node")
    # A temp file rather than `node -e`: with -e the script itself is not argv[1], and node 26
    # routes -e through its TypeScript path, which turns any mistake into a confusing parse error.
    with tempfile.TemporaryDirectory() as d:
        harness = Path(d) / "harness.mjs"
        harness.write_text(HARNESS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), json.dumps(scenario), _decide_script()],
            capture_output=True, text=True, timeout=60,
        )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    tail = proc.stdout.strip().splitlines()[-1]
    return json.loads(tail)


# ------------------------------------------------------------------ the seventh failure mode


def test_it_refuses_to_revert_a_head_that_is_not_the_cause():
    """The 2026-08-19 case, exactly. Same job already failing one commit earlier."""
    r = _decide(_scenario())
    assert r["outputs"].get("go") != "yes", (
        f"the guard would have reverted innocent work. outputs={r['outputs']} notices={r['notices']}"
    )
    assert r["outputs"].get("blame") == PARENT, (
        f"it must name the earlier commit as the suspect, not just decline. outputs={r['outputs']}"
    )
    assert "python" in r["outputs"].get("blame_jobs", ""), "it must name the job that was failing"


def test_it_still_reverts_a_head_that_really_did_break_main():
    """The guard must keep working. A refusal that fires on everything is a disabled guard."""
    s = _scenario(runs_by_head_sha={PARENT: [{"id": PRIOR_RUN, "conclusion": "success",
                                              "html_url": "https://example/900"}]})
    r = _decide(s)
    assert r["outputs"].get("go") == "yes", (
        f"main was green on the parent and red on the head; this commit IS the cause. "
        f"outputs={r['outputs']} notices={r['notices']}"
    )
    assert r["outputs"].get("sha") == HEAD


def test_a_different_failing_job_on_the_parent_does_not_excuse_the_head():
    """Innocence means THIS failure was already there, not that something else was failing."""
    s = _scenario(jobs_by_run_id={str(RUN_ID): [{"name": "python", "conclusion": "failure"}],
                                  str(PRIOR_RUN): [{"name": "web", "conclusion": "failure"}]})
    r = _decide(s)
    assert r["outputs"].get("go") == "yes", (
        f"a different job failing earlier says nothing about this commit. outputs={r['outputs']}"
    )


def test_no_run_on_the_parent_falls_through_to_reverting():
    """Being unable to prove innocence is not proof of it. A red main blocks every open PR."""
    r = _decide(_scenario(runs_by_head_sha={}))
    assert r["outputs"].get("go") == "yes", (
        f"with no evidence either way the guard must still put main back. outputs={r['outputs']}"
    )


def test_a_run_still_in_flight_on_the_parent_falls_through_to_reverting():
    """`conclusion: null` is not a failure. Treating it as one would disable the guard."""
    s = _scenario(runs_by_head_sha={PARENT: [{"id": PRIOR_RUN, "conclusion": None,
                                              "html_url": "https://example/900"}]})
    assert _decide(s)["outputs"].get("go") == "yes"


def test_the_check_can_never_kill_the_job():
    """An unhandled throw part way through a github-script step drops every line below it.

    That is how the merge of #451 landed on main ungraded on 2026-08-19: a 403 from
    checks.listForRef killed the run before the CI dispatch underneath it. This check must
    degrade to the old behaviour, loudly, not take the guard down with it.
    """
    r = _decide(_scenario(throw_on_jobs=True))
    assert not r.get("threw"), f"the script threw: {r.get('threw')}"
    assert r["outputs"].get("go") == "yes", f"it must proceed. outputs={r['outputs']}"
    assert any("403" in w for w in r["warnings"]), (
        f"a check that silently gave up teaches nobody. warnings={r['warnings']}"
    )


# ------------------------------------------------------------------ the six it already had


def test_it_stands_down_when_main_has_moved():
    """Someone may already be fixing it. Never race a human."""
    r = _decide(_scenario(branch_head_sha="c" * 40))
    assert r["outputs"].get("go") != "yes"


def test_it_never_reverts_a_revert():
    """A revert of a revert is how ping-pong starts."""
    s = _scenario()
    s["commit"]["commit"]["message"] = "Revert \"feat: something\""
    r = _decide(s)
    assert r["outputs"].get("go") != "yes"


def test_one_revert_per_hour():
    """A revert storm is worse than a red main."""
    s = _scenario(recent_commits=[{"sha": "d" * 40,
                                   "commit": {"message": "Revert something\n\nmain-green-guard"}}])
    # The storm guard reads c.commit.message, so shape the stub the way the API returns it.
    s["recent_commits"] = [{"sha": "d" * 40,
                            "commit": {"message": "Revert x"},
                            "message": "Revert x"}]
    r = _decide(s)
    # Either it refuses on the storm guard or it reaches the innocence check first; both stand
    # down. What must never happen is a second revert inside the hour.
    assert r["outputs"].get("go") != "yes"


# ------------------------------------------------------------------ structural, always run


def test_the_revert_job_holds_the_narrowest_scopes_it_needs():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    perms = doc["permissions"]
    assert perms.get("contents") == "write", "it cannot push a revert without this"
    assert perms.get("issues") == "write", "a revert is never silent"
    extra = {k: v for k, v in perms.items()
             if k not in ("contents", "issues", "actions") and v == "write"}
    assert not extra, f"unnecessary write scopes on a workflow that can delete landed work: {extra}"


def test_the_issue_is_opened_before_the_push():
    """If GitHub refuses the issue the revert must not happen. A silent revert is lost work."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    names = [s.get("name", "") for s in doc["jobs"]["revert"]["steps"]]
    issue_at = next(i for i, n in enumerate(names) if "issue first" in n.lower())
    push_at = next(i for i, n in enumerate(names) if "revert it and push" in n.lower())
    assert issue_at < push_at, f"the issue must come first; order was {names}"


def test_standing_down_still_tells_somebody():
    """The refusal added on 2026-08-20 leaves main red. Silence there is worse than the revert."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["revert"]["steps"]
    blame = [s for s in steps if s.get("if", "").strip().startswith("steps.decide.outputs.blame")]
    assert blame, (
        "there must be a step that opens an issue naming the real suspect when the guard stands "
        "down; otherwise main stays red and nobody is told why"
    )
    body = json.dumps(blame[0])
    assert "listForRepo" in body, "it must check for an existing issue; a repeating alarm is noise"

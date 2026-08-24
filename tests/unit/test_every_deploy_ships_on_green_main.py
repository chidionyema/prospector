"""Every deployable component ships when main moves, or this file goes red.

THE ROUTE TO PRODUCTION CHANGED ON 2026-08-20, and this file changed with it.

Until then `.github/workflows/automerge.yml` did the merging, and a push made with the default
GITHUB_TOKEN starts no workflow runs -- so the merge commit automerge created could not trigger
any deploy by itself, and an explicit `workflow_dispatch` was the only route to production. That
hand-written dispatch list drifted from the workflows' own path filters and cost a day of silent
non-delivery: `deploy-api.yml` last ran at 2026-08-18T05:01:55Z while #358 and #342 changed
Store.Api and merged that evening, and `deploy-web.yml` last ran from a push at
2026-08-18T13:33:57Z while #349, #363 and #365 changed Store.Web after it. Nothing failed.
Nothing was red. The code just never reached production
(`docs/incidents/INC-2026-08-19-automerge-shipped-only-the-engine.json`).

automerge.yml was DELETED on 2026-08-20 by founder decision -- "no autonerge goee autodeploy
stays" -- because the branch update it performed moved fifteen pull request heads and jammed the
board for thirty hours. A human `gh pr merge` is not a GITHUB_TOKEN push, so the merge commit now
DOES start workflow runs, and every deploy workflow's own `on.push` is the primary route to
production. The first test below is the one that pins that.

The dispatch map did not die with automerge. `.github/workflows/merge-when-green.yml` carries it
now, for the one case where a push still cannot start anything: merge-when-green merges with
GITHUB_TOKEN, so it has to dispatch every deploy itself. The comparison of its path regexes
against each workflow's own `on.push.paths` lives in
tests/unit/test_merge_when_green_dispatches_what_the_push_could_not.py. What that file does NOT
check -- that the `-f key=value` inputs it sends are ones the deploy workflow declares -- is the
last two tests here.

main-admission-guard.yml carried the same map until 2026-08-21, and was deleted along with
main-green-guard.yml when the repository went public and ruleset `strict` made ci-ok a required
check with no bypass actors. Nothing pushes to main any more, so nothing has to be reverted off
it, and the three tests here that read the guard's DEPLOY and INPUTS objects went with it. What
replaced them is tests/unit/test_ci_ok_is_the_required_check.py.

A missing deploy leaves no artifact, so no alert in this estate can fire on it. Every alert here
fires on something that ran and failed. This test is the only machine that can see an action that
did not happen, and it sees it by comparing the two lists that must agree.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
MERGER = WORKFLOWS / "merge-when-green.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _on(doc: dict) -> dict:
    """`on:` is the YAML 1.1 boolean `true`, so PyYAML keys it as `True`, not `"on"`. A test that
    reads `doc["on"]` here gets a KeyError and reads as a missing trigger."""
    return doc.get(True, doc.get("on")) or {}


def _deploy_workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("deploy-*.yml"))


def _push(path: Path) -> dict:
    return (_on(_load(path)).get("push") or {})


def _push_paths(path: Path) -> list[str]:
    return list(_push(path).get("paths") or [])


def _dispatched_inputs() -> dict[str, dict[str, str]]:
    """What merge-when-green.yml actually sends: `gh workflow run <wf> --ref main -f k=v ...`.

    Read out of the shell rather than kept in a list here, so a change to the workflow drags this
    check along with it instead of leaving a copy behind to drift -- which is the failure mode
    this whole file exists for.
    """
    out: dict[str, dict[str, str]] = {}
    for line in MERGER.read_text(encoding="utf-8").splitlines():
        m = re.search(r"gh workflow run (deploy-[\w.-]+\.yml)\b(.*)", line)
        if m:
            out[m.group(1)] = dict(re.findall(r"-f (\w+)=(\S+)", m.group(2)))
    return out


def test_there_is_at_least_one_deploy_workflow_to_grade():
    """Anti-vacuity. Rename the deploy workflows and every parametrized test below silently
    collects nothing, which reads as a pass."""
    found = [p.name for p in _deploy_workflows()]
    assert len(found) >= 3, f"expected engine, api and web deploys, found {found}"


@pytest.mark.parametrize("wf", [p.name for p in _deploy_workflows()])
def test_every_deploy_ships_on_a_push_to_main(wf: str):
    """The primary route to production since automerge.yml was deleted on 2026-08-20.

    A deploy workflow with no `push` trigger ships only when somebody remembers to dispatch it by
    hand, which is the exact silent non-delivery this file was written for. `branches: [main]` is
    asserted too: a deploy that also fired on a feature branch would put unreviewed code in
    production, which is a worse failure than not shipping.
    """
    push = _push(WORKFLOWS / wf)
    assert push, (
        f"{wf} has no on.push trigger. Merging a change to what it deploys would ship nothing, "
        f"and nothing would be red -- that is the 2026-08-18 incident, exactly.")
    assert push.get("branches") == ["main"], (
        f"{wf} deploys on pushes to {push.get('branches')!r}. It must be main and only main.")
    assert _push_paths(WORKFLOWS / wf), (
        f"{wf} watches no paths, so every merge in the repo deploys it")


def test_the_ops_console_is_one_of_the_parts_that_ships_this_way():
    """The founder asked for the ops console to autodeploy on a green main like every other part.
    It ships inside the engine image, so deploy-engine.yml must watch its source."""
    globs = _push_paths(WORKFLOWS / "deploy-engine.yml")
    assert any("Ops.Console" in g for g in globs), (
        f"deploy-engine.yml does not watch the ops console source: {globs}")


def test_the_merger_dispatches_every_deploy_workflow():
    """Anti-vacuity for the test below, and the same drift the deleted guard had: a deploy
    workflow the merger does not know about never ships from a merge the merger made."""
    sent = _dispatched_inputs()
    missing = {p.name for p in _deploy_workflows()} - set(sent)
    assert not missing, (
        f"merge-when-green.yml never dispatches {sorted(missing)}, so a merge it makes ships "
        f"nothing for that component and nothing goes red")


@pytest.mark.parametrize("wf", [p.name for p in _deploy_workflows()])
def test_each_deploy_declares_every_input_the_merger_sends(wf: str):
    """`gh workflow run` fails outright on an input the workflow does not declare, and an input
    left out silently takes the workflow's own default -- which is how a production deploy
    quietly becomes a dry run. Both directions are checked."""
    trigger = _on(_load(WORKFLOWS / wf)).get("workflow_dispatch")
    assert trigger is not None, (
        f"{wf} has no workflow_dispatch trigger, so merge-when-green.yml cannot start it at all. "
        f"Its merge push is made with GITHUB_TOKEN and starts nothing.")
    declared = (trigger or {}).get("inputs") or {}
    sent = _dispatched_inputs().get(wf, {})

    undeclared = sorted(set(sent) - set(declared))
    assert not undeclared, (
        f"merge-when-green.yml sends {undeclared} to {wf}, which does not declare it. "
        f"`gh workflow run` rejects the whole call, so nothing deploys.")

    risky = {k for k, v in declared.items()
             if isinstance(v, dict) and ("default" in v or v.get("required"))}
    assert risky <= set(sent), (
        f"{wf} declares {sorted(risky - set(sent))} with a default or as required, and "
        f"merge-when-green.yml does not pass it. Relying on another file's default is how a "
        f"production deploy becomes a dry run.")

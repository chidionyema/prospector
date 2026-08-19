"""Every deployable component ships when main goes green, or this file goes red.

A push made with the default GITHUB_TOKEN starts no workflow runs. So once
`.github/workflows/automerge.yml` began doing the merging, the merge commit it creates could not
trigger any deploy workflow by itself, and an explicit `workflow_dispatch` became the only route
to production.

That list of dispatches was written by hand from another file's `on.push.paths`, kept in step by
a comment. It drifted, and the drift cost a day of silent non-delivery: `deploy-api.yml` last ran
at 2026-08-18T05:01:55Z while #358 and #342 changed Store.Api and merged that evening, and
`deploy-web.yml` last ran from a push at 2026-08-18T13:33:57Z while #349, #363 and #365 changed
Store.Web after it. Nothing failed. Nothing was red. The code just never reached production
(`docs/incidents/INC-2026-08-19-automerge-shipped-only-the-engine.json`).

A missing dispatch leaves no artifact, so no alert in this estate can fire on it. Every alert
here fires on something that ran and failed. This test is the only machine that can see an action
that did not happen, and it sees it by comparing the two lists that must agree.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
AUTOMERGE = WORKFLOWS / "automerge.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _on(doc: dict) -> dict:
    """`on:` is the YAML 1.1 boolean `true`, so PyYAML keys it as `True`, not `"on"`. A test that
    reads `doc["on"]` here gets a KeyError and reads as a missing trigger."""
    return doc.get(True, doc.get("on")) or {}


def _script() -> str:
    return _load(AUTOMERGE)["jobs"]["merge"]["steps"][0]["with"]["script"]


def _deploy_map() -> dict[str, re.Pattern]:
    """automerge.yml's `DEPLOY` object: one workflow filename to one path regex."""
    block = re.search(r"const DEPLOY = \{(.*?)\n\}", _script(), re.S)
    assert block, "automerge.yml no longer declares a DEPLOY object of workflow -> path regex"
    out = {}
    for name, body in re.findall(r"'([\w.-]+\.yml)':\s*/(.+?)/,", block.group(1)):
        out[name] = re.compile(body)
    assert out, "the DEPLOY object parsed to nothing"
    return out


def _inputs_map() -> dict[str, dict]:
    """automerge.yml's `INPUTS` object, read as the dispatch payload per workflow."""
    block = re.search(r"const INPUTS = \{(.*?)\n\}", _script(), re.S)
    assert block, "automerge.yml no longer declares an INPUTS object"
    out = {}
    for name, body in re.findall(r"'([\w.-]+\.yml)':\s*\{(.*?)\},", block.group(1)):
        pairs = re.findall(r"(\w+):\s*'([^']*)'", body)
        out[name] = dict(pairs)
    return out


def _deploy_workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("deploy-*.yml"))


def _push_paths(path: Path) -> list[str]:
    return list(((_on(_load(path)).get("push") or {}).get("paths")) or [])


def _sample(glob: str) -> str:
    """One concrete filename a path filter must match. `**` crosses directory separators, `*` does
    not, and everything else is a literal."""
    if glob.endswith("/**"):
        return glob[:-2] + "a/b.txt"
    return glob.replace("**", "a/b").replace("*", "a")


def test_there_is_at_least_one_deploy_workflow_to_grade():
    """Anti-vacuity. Rename the deploy workflows and every parametrized test below silently
    collects nothing, which reads as a pass."""
    found = [p.name for p in _deploy_workflows()]
    assert len(found) >= 3, f"expected engine, api and web deploys, found {found}"


def test_every_deploy_workflow_is_dispatched_after_a_merge():
    """The defect itself: a deployable component that automerge does not know about."""
    listed = set(_deploy_map())
    on_disk = {p.name for p in _deploy_workflows()}
    assert on_disk <= listed, (
        f"{sorted(on_disk - listed)} exist(s) but automerge.yml never dispatches it, so merging a "
        f"change to it will not deploy it. Add it to the DEPLOY object with the paths it watches.")
    assert listed <= on_disk, (
        f"automerge.yml dispatches {sorted(listed - on_disk)}, which is not a workflow on disk")


@pytest.mark.parametrize("wf", [p.name for p in _deploy_workflows()])
def test_the_dispatch_paths_match_the_workflows_own_push_filter(wf: str):
    """Both directions.

    A path the workflow watches but automerge does not: merging that file deploys nothing.
    A path automerge carries but the workflow no longer watches: automerge deploys on a change
    the workflow itself would ignore, which is the same drift pointing the other way.
    """
    pattern = _deploy_map()[wf]
    globs = _push_paths(WORKFLOWS / wf)
    assert globs, f"{wf} has no on.push.paths to compare against"

    for glob in globs:
        assert pattern.match(_sample(glob)), (
            f"{wf} watches {glob!r} on push, but automerge.yml's regex does not match "
            f"{_sample(glob)!r}. A merge touching that path would not deploy.")

    # And back the other way: every alternation branch in the regex must be something the
    # workflow actually watches.
    body = pattern.pattern
    assert body.startswith("^(") and body.endswith(")"), (
        f"{wf}'s regex is no longer a single ^(a|b|c) alternation, so this direction of the "
        f"comparison cannot be made. Rewrite it or rewrite this test deliberately.")
    prefixes = [g[:-2] for g in globs if g.endswith("**")]
    for branch in body[2:-1].split("|"):
        literal = branch.replace("\\/", "/").replace("\\.", ".").rstrip("$")
        assert literal in globs or literal in prefixes, (
            f"automerge.yml deploys {wf} for {literal!r}, which is not in its on.push.paths "
            f"({globs}). One of the two is stale.")


@pytest.mark.parametrize("wf", [p.name for p in _deploy_workflows()])
def test_each_deploy_can_actually_be_dispatched_with_what_automerge_sends(wf: str):
    """A dispatch that names an input the workflow does not declare is rejected by the API, and a
    required input left out takes the workflow's own default - which is how a production deploy
    quietly becomes a dry run."""
    doc = _load(WORKFLOWS / wf)
    trigger = _on(doc).get("workflow_dispatch")
    assert trigger is not None, (
        f"{wf} has no workflow_dispatch trigger, so automerge cannot start it at all. A merge is "
        f"the only other route and a GITHUB_TOKEN merge starts nothing.")

    declared = (trigger or {}).get("inputs") or {}
    sent = _inputs_map().get(wf, {})

    assert not (set(sent) - set(declared)), (
        f"automerge sends {sorted(set(sent) - set(declared))} to {wf}, which does not declare "
        f"it. createWorkflowDispatch rejects the whole call.")

    required = {k for k, v in declared.items() if isinstance(v, dict) and v.get("required")}
    assert required <= set(sent), (
        f"{wf} requires {sorted(required - set(sent))} and automerge does not send it")

    # Inputs with a default are the dangerous ones: omitting them succeeds and does something
    # other than what was meant. Name them explicitly.
    defaulted = {k for k, v in declared.items()
                 if isinstance(v, dict) and "default" in v} - required
    assert defaulted <= set(sent), (
        f"{wf} declares {sorted(defaulted - set(sent))} with a default that automerge does not "
        f"override. Relying on another file's default is how a prod deploy becomes a test one.")


def test_a_deploy_only_follows_a_green_ci_run():
    """The whole pipeline rests on automerge running after CI passed, not beside it."""
    wr = _on(_load(AUTOMERGE))["workflow_run"]
    assert wr["workflows"] == ["CI"], f"automerge no longer waits on CI: {wr['workflows']}"
    assert "completed" in wr["types"]
    gate = _load(AUTOMERGE)["jobs"]["merge"]["if"]
    assert "conclusion == 'success'" in gate, (
        f"automerge's gate no longer requires a successful CI run: {gate}")


def test_the_ops_console_is_one_of_the_parts_that_ships_this_way():
    """The founder asked for the ops console to autodeploy on a green main like every other part.
    It ships inside the engine image, so deploy-engine.yml must watch its source."""
    globs = _push_paths(WORKFLOWS / "deploy-engine.yml")
    assert any("Ops.Console" in g for g in globs), (
        f"deploy-engine.yml does not watch the ops console source: {globs}")
    assert _deploy_map()["deploy-engine.yml"].match(
        "store_platform/src/Ops.Console/src/pages/index.tsx"), (
        "automerge does not dispatch the engine deploy for an ops console change")


def test_the_dispatch_list_and_the_inputs_list_name_the_same_workflows():
    """Two objects, one fact. A workflow in DEPLOY but not INPUTS is dispatched with `undefined`
    inputs and takes every default."""
    assert set(_deploy_map()) == set(_inputs_map()), (
        f"DEPLOY has {sorted(_deploy_map())}, INPUTS has {sorted(_inputs_map())}")

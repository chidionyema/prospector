"""The deploy dispatch must outlive every optional thing automerge does after a merge.

Measured 2026-08-19T21:09:32Z, run 32302397871. The merge step logged `merged #453`, then threw:

    RequestError [HttpError]: Resource not accessible by integration
    url: https://api.github.com/repos/chidionyema/prospector/commits/<sha>/check-runs
    x-accepted-github-permissions: 'checks=read'

`github.rest.checks.listForRef` in the stranded-PR sweep asks for check runs, and the workflow's
`permissions:` block named contents, pull-requests and actions but not checks. A workflow that
declares any permissions gets `none` for every scope it does not name, so the call was refused.

Two separate defects, and this file holds one test for each.

1. A permission the script uses and does not declare. Nothing failed at the point of the mistake:
   the merge had already landed, so code reached main and the run went red for a reason that
   reads like a merge problem.
2. The dispatch that ships that code was the LAST thing in the script, after a best-effort
   sweep. Any throw anywhere above it skipped the deploy for a merge that had already happened.
   Four merges landed that evening (#451 #453 #459 #462) and deploy-engine last ran at 17:44Z on
   66e8b28a, leaving production 9 commits behind main with nothing red to say so.

The order is the fix: what must happen because code LANDED goes above what is best effort.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

AUTOMERGE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "automerge.yml"

#: octokit namespace -> the token permission scopes that grant it, any one of which is enough.
#: `issues.addLabels` is used on pull requests, and `pull-requests: write` grants labels there,
#: so either scope satisfies it.
SCOPES: dict[str, tuple[str, ...]] = {
    "actions": ("actions",),
    "checks": ("checks",),
    "git": ("contents",),
    "issues": ("issues", "pull-requests"),
    "pulls": ("pull-requests",),
    "repos": ("contents",),
}


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(AUTOMERGE.read_text())


@pytest.fixture(scope="module")
def script(doc: dict) -> str:
    return doc["jobs"]["merge"]["steps"][0]["with"]["script"]


def test_every_api_namespace_the_script_uses_is_declared(doc: dict, script: str) -> None:
    declared = set(doc["permissions"])
    used = set(re.findall(r"github\.rest\.([a-zA-Z]+)\.", script))
    unknown = used - set(SCOPES)
    assert not unknown, (
        f"automerge.yml calls github.rest.{sorted(unknown)}, which this test cannot grade. "
        f"Add it to SCOPES with the permission GitHub's docs require for that endpoint."
    )
    missing = {ns: SCOPES[ns] for ns in used if not (set(SCOPES[ns]) & declared)}
    assert not missing, (
        f"the script calls these namespaces with no permission declared: {missing}. "
        f"A workflow with a permissions block gets `none` for every scope it omits, so the call "
        f"is refused at 403 mid-run, after merges have already landed."
    )


def test_the_deploy_dispatch_runs_before_the_best_effort_sweep(script: str) -> None:
    dispatch = script.index("dispatching CI on main")
    sweep = script.index("const sweepMax")
    assert dispatch < sweep, (
        "the deploy dispatch is below the stranded-PR sweep again. The sweep is best effort; "
        "the dispatch is the only thing that puts merged code into production. A throw in the "
        "sweep then skips a deploy for code that has already merged."
    )


def test_no_deploy_is_skipped_by_an_early_return(script: str) -> None:
    """`if (toDeploy.size === 0) ... return` was fine while the dispatch was last. Above the
    sweep it would skip the sweep on every merge that needs no deploy, which is most of them."""
    tail = script[script.index("dispatching CI on main"):script.index("const sweepMax")]
    assert "return" not in tail, (
        "the dispatch block returns early. It now runs before the sweep, so a return here "
        "silently disables the stranded-PR rescue."
    )

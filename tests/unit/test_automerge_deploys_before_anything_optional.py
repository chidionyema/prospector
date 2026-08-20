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


def test_nothing_optional_runs_between_the_merge_and_the_deploy_dispatch(script: str) -> None:
    """The ordering rule, stated as what it actually protects.

    The original defect was a best-effort stranded-PR sweep sitting ABOVE the dispatch: any
    throw in it skipped the deploy for code that had already merged. The sweep was deleted on
    2026-08-20 (it worked by pushing to open PR branches, which is what stopped three batches
    from closing anything -- see tests/unit/test_nothing_pushes_to_a_pull_request_branch.py).

    So the assertion is no longer "dispatch before sweep". It is the rule that produced it:
    once a merge has landed, NOTHING may run before the dispatch that ships it. Any code
    inserted between them can throw, and merged code then never reaches production with nothing
    red to say so -- four merges on 2026-08-19 (#451 #453 #459 #462) left production nine
    commits behind main exactly that way.
    """
    merged_guard = script.index("if (!merged) return")
    # Cut at the START of the dispatch's own line. Slicing at the marker itself leaves the
    # first half of `core.info('dispatching CI on main')` in the region and reports the
    # dispatch as the thing that was inserted before the dispatch.
    dispatch = script.rindex("\n", 0, script.index("dispatching CI on main"))
    between = script[merged_guard + len("if (!merged) return") : dispatch]
    code = [
        line
        for line in between.splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]
    assert not code, (
        f"code was inserted between the merge guard and the deploy dispatch: {code}. "
        f"Anything here can throw, and a throw here skips the deploy for code that has ALREADY "
        f"merged -- green everywhere, production behind main, nothing to say so. Put it after "
        f"the dispatch."
    )

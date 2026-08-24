"""A workflow triggered only by `push: main` never runs on this repository.

THE INCIDENT, 2026-08-24. `container images` was added and merged as #702 at 10:25:58Z. Four
minutes later there was no run for the merge commit 7142f8d1 and none was coming. GitHub does not
emit workflow-triggering events for a push made with `GITHUB_TOKEN`, and on this repository main
is only ever written by merge-when-green.yml, which merges with exactly that token. So a workflow
whose only main trigger is `push: branches: [main]` is not slow or flaky: it does not run, and it
reports nothing while not running, which is the failure shape this estate keeps paying for.

merge-when-green.yml already knew this -- it dispatches ci.yml and the three deploys by hand under
a step named "Start what the merge push could not". Nothing made the next workflow join that list.

THE SWEEP, run when this test was written. Six workflows carry `push: main`. Five were dispatched.
The one that was not is `k8s-manifests.yml`, and its history proves the consequence: 13 runs, every
one `pull_request`. The estate's admission gate had graded proposals and had never once graded
main. Both it and container-images.yml were added to the dispatch step in the same commit.

WHAT THIS CANNOT SEE. It reads the workflow files, not GitHub. If the dispatch step is present but
the token loses `actions: write`, every `gh workflow run` here fails, the `|| echo` swallows it,
and this test still passes. The receipt for that is a run list, not a file: `gh run list --workflow
<name> --limit 30 --json event` should show `workflow_dispatch` rows on main after a merge.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DISPATCHER = WORKFLOWS / "merge-when-green.yml"

# Events a bot merge to main DOES produce, so a workflow carrying one is reachable without being
# dispatched. `workflow_run` chains off another workflow; `schedule` fires on its own clock.
_SELF_STARTING = {"schedule", "workflow_run", "repository_dispatch", "workflow_call"}


def dispatched_workflows(dispatcher_text: str) -> set[str]:
    """The workflow files merge-when-green starts by hand after it lands a merge."""
    return set(re.findall(r"gh workflow run ([\w.-]+\.yml)", dispatcher_text))


def unreachable_on_main(triggers: dict, name: str, dispatched: set[str]) -> bool:
    """True when a merge to main starts this workflow by no route at all.

    Pure, so the test below can hand it a workflow that must be refused without adding a broken
    workflow to the repository to create one.
    """
    push = triggers.get("push")
    if not isinstance(push, dict) or "main" not in (push.get("branches") or []):
        return False  # it does not claim to run on main; not this rule's business
    if set(triggers) & _SELF_STARTING:
        return False
    return name not in dispatched


def _triggers(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML resolves a bare `on:` key to the boolean True. Both spellings appear in the wild.
    on = doc.get("on", doc.get(True))
    return on if isinstance(on, dict) else {}


def test_every_workflow_that_claims_to_run_on_main_can_actually_start():
    dispatched = dispatched_workflows(DISPATCHER.read_text(encoding="utf-8"))
    assert dispatched, (
        "merge-when-green.yml dispatches nothing. Either the step was deleted -- in which case "
        "CI itself no longer runs on main -- or the pattern this test reads has changed."
    )
    stranded = [p.name for p in sorted(WORKFLOWS.glob("*.yml"))
                if unreachable_on_main(_triggers(p), p.name, dispatched)]
    assert not stranded, (
        f"these workflows say `push: branches: [main]` and nothing starts them: {stranded}.\n"
        "A merge made with GITHUB_TOKEN emits no event a workflow can see, and main is only "
        "written by merge-when-green.yml. Add `gh workflow run <name> --ref main` to its "
        '"Start what the merge push could not" step, or give the workflow a trigger that fires '
        "on its own."
    )


def test_the_checker_refuses_a_workflow_nothing_would_start():
    """The must-fail half. Without it, a checker that always returns False passes above."""
    assert unreachable_on_main(
        {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}},
        "not-dispatched.yml", {"ci.yml"})


@pytest.mark.parametrize(
    "triggers,name,dispatched",
    [
        # named in the dispatch step
        ({"push": {"branches": ["main"]}}, "ci.yml", {"ci.yml"}),
        # starts itself off another workflow's completion
        ({"push": {"branches": ["main"]}, "workflow_run": {}}, "keeper.yml", set()),
        # runs on a clock, so it reaches main on its own
        ({"push": {"branches": ["main"]}, "schedule": []}, "drill.yml", set()),
        # never claimed to run on main in the first place
        ({"pull_request": {"branches": ["main"]}}, "pr-only.yml", set()),
        ({"workflow_dispatch": None}, "manual.yml", set()),
    ],
)
def test_the_checker_permits_a_workflow_something_starts(triggers, name, dispatched):
    """The must-permit half. A guard that refuses correct work is an outage (LAW 38).

    Note `workflow_dispatch` alone does NOT make a workflow reachable: a human or another
    workflow still has to invoke it, which is the hand this rule exists to remove. It counts
    only when merge-when-green is the one invoking it, which is the first case above.
    """
    assert not unreachable_on_main(triggers, name, dispatched)


def test_the_two_workflows_the_sweep_found_are_named():
    """The instances, pinned. If someone removes either dispatch line the general test above
    catches it, but naming them here says which incident this was and stops a silent revert
    reading as a refactor."""
    dispatched = dispatched_workflows(DISPATCHER.read_text(encoding="utf-8"))
    for name in ("container-images.yml", "k8s-manifests.yml"):
        assert name in dispatched, (
            f"{name} was added to the dispatch step on 2026-08-24 and is gone. "
            "It has no other route to main."
        )

"""`merge-when-green.yml` must dispatch every workflow its own merge push cannot start.

A merge made by that workflow pushes to main with GITHUB_TOKEN, and GitHub starts no workflow run
from a GITHUB_TOKEN event. `main-admission-guard.yml` stated the same fact about its revert push,
above its `permissions:` block and again at :310. So every workflow that runs `on.push` to main
has to be dispatched by hand from the merging workflow, or a merge it performs lands and never
reaches production: the queue drains, every pull request reads as merged, and production stops
tracking main with nothing red anywhere.

Until 2026-08-26 this file graded a map of path patterns copied from the three Fly deploy
workflows. Those workflows were deleted with the Fly pipeline (crew#203, founder ruling R1), and
the hand-off is now `container-images.yml` (publishes the commit-tagged image, no paths filter)
plus `k8s-manifests.yml`, which Flux rolls out from `deploy/k8s/overlays/oke`. The rule is the
same and the copy that can drift is now a list of names rather than a list of regexes, so the
grading reads both sides out of the files and compares sets.

`main-admission-guard.yml:381` recorded that the two tests which used to grade exactly this drift
were deleted with `automerge.yml` on 2026-08-20. This is that grading, restored, and widened by
the case the originals did not have: a push-to-main workflow added later that nobody adds to the
dispatch list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
MERGER = WORKFLOWS / "merge-when-green.yml"


def _on_block(doc: dict) -> dict:
    """The `on:` mapping. PyYAML reads a bare `on:` key as the boolean True."""
    return doc.get("on") or doc.get(True) or {}


def _runs_on_push_to_main(path: Path) -> bool:
    doc = yaml.safe_load(path.read_text()) or {}
    push = _on_block(doc).get("push") or {}
    return isinstance(push, dict) and "main" in (push.get("branches") or [])


def _push_to_main_workflows() -> set[str]:
    return {
        p.name
        for p in WORKFLOWS.glob("*.yml")
        if p.name != MERGER.name and _runs_on_push_to_main(p)
    }


def _dispatched() -> set[str]:
    """The workflow names the merger actually dispatches, read out of the file, never retyped.

    Retyping them here would grade this test's copy instead of the one that runs, which is the
    same defect the test exists to catch.
    """
    return set(re.findall(r"gh workflow run ([a-z0-9-]+\.yml)", MERGER.read_text()))


def test_the_merger_dispatches_something() -> None:
    """A list that parsed to nothing would make every assertion below vacuously true."""
    assert MERGER.exists(), f"{MERGER} is missing; nothing merges a green pull request"
    assert _dispatched(), "no `gh workflow run` found in merge-when-green.yml"


def test_there_is_a_push_to_main_workflow_to_grade() -> None:
    """Anti-vacuity for the other side of the comparison."""
    assert _push_to_main_workflows(), (
        "no workflow runs on push to main; the glob or the parser is wrong"
    )


@pytest.mark.parametrize("name", sorted(_push_to_main_workflows()))
def test_every_push_to_main_workflow_is_dispatched_by_the_merger(name: str) -> None:
    """A workflow that a human merge would start, and a robot merge would not."""
    assert name in _dispatched(), (
        f"{name} runs on a push to main but merge-when-green.yml never dispatches it, so a merge "
        f"it performs would land without starting it. Add `gh workflow run {name} --ref main` "
        f"beside the other dispatches."
    )


@pytest.mark.parametrize("name", sorted(_dispatched()))
def test_every_dispatched_workflow_exists_and_accepts_dispatch(name: str) -> None:
    """The other direction: a dispatch of a workflow that was deleted or never took
    `workflow_dispatch` fails at merge time with `could not dispatch`, which the merger
    swallows into an echo."""
    path = WORKFLOWS / name
    assert path.exists(), f"merge-when-green.yml dispatches {name}, which is not on disk"
    doc = yaml.safe_load(path.read_text()) or {}
    assert "workflow_dispatch" in _on_block(doc), (
        f"{name} has no workflow_dispatch trigger, so `gh workflow run {name}` is refused"
    )

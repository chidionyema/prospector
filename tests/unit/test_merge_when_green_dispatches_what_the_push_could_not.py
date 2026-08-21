"""`merge-when-green.yml` must dispatch exactly what its own merge push cannot start.

A merge made by that workflow pushes to main with GITHUB_TOKEN, and GitHub starts no workflow run
from a GITHUB_TOKEN event. `main-admission-guard.yml` states the same fact about its revert push,
above its `permissions:` block and again at :310. So the deploys that a human merge would have
triggered have to be dispatched by hand, from a map of path patterns held in the merging
workflow.

That map is a COPY of each deploy workflow's own `paths:` filter, and a copy drifts. When the
copy is narrower than the original, a merge that should have shipped the engine silently ships
nothing: the queue drains, every pull request reads as merged, and production stops tracking main
with nothing red anywhere.

`main-admission-guard.yml:381` records that the two tests which used to grade exactly this drift
were deleted with `automerge.yml` on 2026-08-20. This is that grading, restored, and widened by
the case the originals did not have: a deploy workflow added later that nobody adds to the map.
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


def _push_paths(path: Path) -> list[str] | None:
    """The workflow's `on.push.paths` for main, or None when it does not deploy on a push."""
    doc = yaml.safe_load(path.read_text())
    push = _on_block(doc).get("push") or {}
    if "main" not in (push.get("branches") or []):
        return None
    return push.get("paths")


def _dispatch_map() -> dict[str, str]:
    """The workflow name -> regex map actually shipped, read out of the file, never retyped.

    Retyping it here would grade this test's copy instead of the one that runs, which is the
    same defect the test exists to catch.
    """
    text = MERGER.read_text()
    names = re.findall(r"gh workflow run (deploy-[a-z]+\.yml)", text)
    patterns = re.findall(r"if want '(\^\([^']+\))'", text)
    assert len(names) == len(patterns), (
        f"{len(names)} dispatch call(s) but {len(patterns)} path pattern(s); the parser below "
        f"no longer matches the file's shape, so this test is grading nothing"
    )
    return dict(zip(names, patterns))


def test_the_merger_dispatches_something() -> None:
    """A map that parsed to nothing would make every assertion below vacuously true."""
    assert MERGER.exists(), f"{MERGER} is missing; nothing merges a green pull request"
    assert _dispatch_map(), "no deploy dispatch found in merge-when-green.yml"


@pytest.mark.parametrize("name", sorted(_dispatch_map()))
def test_every_declared_path_is_dispatched(name: str) -> None:
    """Each pattern must match every path its own deploy workflow declares."""
    pattern = re.compile(_dispatch_map()[name])
    declared = _push_paths(WORKFLOWS / name)
    assert declared, f"{name} no longer deploys on a push to main; the map needs re-reading"
    for entry in declared:
        # `paths:` is a glob and the map is a regex. A `**` stands for at least one segment, so
        # a concrete sample under it is what the deploy would actually have seen.
        sample = entry.replace("**", "x/y.txt").rstrip("/")
        assert pattern.search(sample), (
            f"{name} deploys on a push touching {entry!r}, but merge-when-green.yml would not "
            f"dispatch it. A merge of such a change would land and never reach production."
        )


def test_no_deploy_workflow_is_left_out_of_the_map() -> None:
    """A deploy workflow added later, and not added to the map, ships nothing after a merge."""
    mapped = set(_dispatch_map())
    on_push, skipped = set(), []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == MERGER.name:
            continue
        paths = _push_paths(path)
        if paths is None:
            continue
        text = path.read_text()
        if "fly deploy" in text or "deploy" in path.name:
            on_push.add(path.name)
        else:
            skipped.append(path.name)
    # The exclusions are printed, never dropped. An allow-list whose miss case is silent is how
    # ten critical findings were lost in eighteen hours on this estate.
    print(f"on push to main and NOT treated as a deploy: {skipped or 'none'}")
    missing = on_push - mapped
    assert not missing, (
        f"{sorted(missing)} deploy on a push to main but merge-when-green.yml never dispatches "
        f"them, so a merge it performs would not ship them"
    )

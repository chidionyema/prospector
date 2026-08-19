"""A squash-merged branch must count as merged, or the gc can never mark anything safe.

WHY THIS EXISTS. `scripts/worktree_gc.py` decided "nothing would be lost" with
`git merge-base --is-ancestor <HEAD> origin/main` alone. This repo squash-merges: the merge
is a NEW commit with a new sha, so a merged branch's HEAD is never an ancestor of main.
Every merged branch therefore read as unfinished work, forever.

Measured 2026-08-19: 35 worktrees, `SAFE TO REMOVE (0)`, while
`fix/session-check-script-exists` at 1a90fb41 had merged as PR #367 twenty minutes earlier.
A garbage collector that can never collect is why 35 accumulated in the first place.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "worktree_gc.py"


def _load():
    spec = importlib.util.spec_from_file_location("worktree_gc", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_ancestry_is_not_the_only_merged_test() -> None:
    """The decision must consult the merged-PR set, not ancestry alone."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "merge-base" in source, "the ancestry check disappeared; this test is now wrong"
    assert "branch not in merged" in source, (
        "worktree_gc decides 'holds commits not in origin/main' on sha-ancestry alone. "
        "Under squash-merge that marks every merged branch as unfinished, so the gc can "
        "never mark a worktree safe."
    )


def test_merged_branches_parses_gh_output(monkeypatch) -> None:
    mod = _load()

    def fake_run(cmd, **kw):
        assert cmd[:3] == ["gh", "pr", "list"], cmd
        assert "merged" in cmd, "must ask for MERGED pull requests only"
        return subprocess.CompletedProcess(
            cmd, 0, stdout="fix/one\nfeat/two\n\n  chore/three  \n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    merged, err = mod.merged_branches()
    assert err is None
    assert merged == {"fix/one", "feat/two", "chore/three"}


def test_merged_branches_reports_failure_rather_than_claiming_none(monkeypatch) -> None:
    """A failed `gh` call must be distinguishable from "no branch has merged".

    Returning an empty set silently would make every worktree read as unmerged again --
    the exact bug, wearing a different hat.
    """
    mod = _load()

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gh: not logged in\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    merged, err = mod.merged_branches()
    assert merged == set()
    assert err and "not logged in" in err

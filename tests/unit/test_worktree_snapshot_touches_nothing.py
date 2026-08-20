"""A snapshot of somebody else's dirty worktree must change nothing about that worktree.

WHY THIS EXISTS. The whole point of `scripts/worktree_snapshot.py` is that it runs against trees
another live session owns. If it staged, committed, moved HEAD or wrote a file, it would be doing
the exact meddling it was written to avoid -- and the damage would land in a session that has no
idea it happened. The safety claim is `GIT_INDEX_FILE` plus `git rm --cached`, and both are one
typo from destroying work: `git rm` without `--cached` DELETES FILES.

So this builds a real repository with a real worktree, dirties it, snapshots it, and asserts the
tree is byte-for-byte where it was. It is deliberately not a source scan.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import worktree_snapshot as ws  # noqa: E402


def _clean_git_env() -> dict[str, str]:
    """The ambient environment minus every GIT_* variable.

    Belt and braces. `tests/conftest.py` already strips these process-wide before any test runs,
    which is the mechanism that protects the whole suite. This second copy exists because THIS is
    the file that destroyed a committer's index on 2026-08-20 — 1,979 entries down to 4, and
    "10 passed" printed underneath — and the next person to read it should find the trap named at
    the exact line that sprang it rather than one directory up.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
                       env=_clean_git_env())
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit, plus a worktree carrying uncommitted work."""
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "config", "user.email", "t@t")
    git(main, "config", "user.name", "t")
    (main / ".gitignore").write_text("node_modules/\n")
    (main / "kept.txt").write_text("original\n")
    (main / "store").mkdir()
    (main / "store" / "runtime.json").write_text("{}\n")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "first")
    return main


@pytest.fixture
def dirty(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt-dirty"
    git(repo, "worktree", "add", "-q", "--detach", str(wt))
    (wt / "kept.txt").write_text("edited by another session\n")   # modified
    (wt / "brand-new.py").write_text("print('only here')\n")      # untracked, the real risk
    (wt / ".env").write_text("SECRET_KEY=do-not-capture\n")       # must never be captured
    (wt / "store" / "runtime.json").write_text('{"pytest": "wrote this"}\n')
    return wt


def state_of(wt: Path) -> tuple[str, str, dict[str, str]]:
    """Everything that must be identical afterwards."""
    files = {str(p.relative_to(wt)): p.read_text()
             for p in sorted(wt.rglob("*")) if p.is_file() and ".git" not in p.parts}
    return git(wt, "status", "--porcelain"), git(wt, "rev-parse", "HEAD"), files


def test_the_fixture_really_is_dirty(dirty: Path):
    """Every assertion below is vacuous against a clean tree."""
    assert git(dirty, "status", "--porcelain").strip()


def test_the_worktree_is_untouched(dirty: Path):
    before = state_of(dirty)
    sha, err = ws.snapshot(dirty)
    assert sha and not err, err
    assert state_of(dirty) == before, "the snapshot changed the worktree it was copying"


def test_the_snapshot_holds_the_uncommitted_work(dirty: Path):
    sha, err = ws.snapshot(dirty)
    assert sha and not err, err
    assert git(dirty, "show", f"{sha}:kept.txt") == "edited by another session"
    assert git(dirty, "show", f"{sha}:brand-new.py") == "print('only here')"


def test_the_secret_is_not_in_the_snapshot(dirty: Path):
    """A secrets file pushed to a remote branch is worse than the work being lost."""
    sha, err = ws.snapshot(dirty)
    assert sha and not err, err
    listing = git(dirty, "ls-tree", "-r", "--name-only", sha)
    assert ".env" not in listing.splitlines()
    with pytest.raises(subprocess.CalledProcessError):
        git(dirty, "show", f"{sha}:.env")


def test_runtime_state_stays_at_its_committed_content(dirty: Path):
    """`store/` is TRACKED, so a bare `git add -A` captures whatever pytest last wrote there.

    It is pinned back to HEAD rather than dropped from the tree. Dropping it would record a
    DELETION of every runtime file, which is how a clean worktree first read as work."""
    sha, err = ws.snapshot(dirty)
    assert sha and not err, err
    assert git(dirty, "show", f"{sha}:store/runtime.json") == "{}", "pytest's write leaked in"
    assert (dirty / "store" / "runtime.json").read_text() == '{"pytest": "wrote this"}\n', (
        "the worktree's own copy was altered")


def test_a_clean_worktree_yields_no_snapshot(repo: Path, tmp_path: Path):
    """The paired negative. A tree with nothing uncommitted must produce nothing, or the tool
    would push a branch per worktree every time it ran."""
    clean = tmp_path / "wt-clean"
    git(repo, "worktree", "add", "-q", "--detach", str(clean))
    assert ws.dirty_paths(clean) == []
    sha, err = ws.snapshot(clean)
    assert not sha
    assert "identical" in err


def test_a_tree_dirty_only_with_runtime_state_yields_no_snapshot(repo: Path, tmp_path: Path):
    """The case that would otherwise fire on every worktree that ever ran the suite."""
    wt = tmp_path / "wt-runtime"
    git(repo, "worktree", "add", "-q", "--detach", str(wt))
    (wt / "store" / "runtime.json").write_text('{"noise": 1}\n')
    assert ws.dirty_paths(wt) == []


def test_the_snapshot_parent_is_the_worktree_head(dirty: Path):
    """A snapshot whose parent is anything else would be unreadable as a diff: the tree is up to
    113 commits behind main, and re-parenting it onto main would show that gap as the work."""
    sha, err = ws.snapshot(dirty)
    assert sha and not err, err
    assert git(dirty, "rev-parse", f"{sha}^") == git(dirty, "rev-parse", "HEAD")


def test_two_worktrees_with_the_same_basename_get_different_branches():
    """A basename is not unique. Two trees called wt-converge exist on this disk, and pushing
    both under one name failed the WHOLE push with `receives from more than one src` -- so twelve
    good snapshots were lost to two colliding names, on 2026-08-19."""
    a = Path("/tmp/claude-501/x/3fa47c70-1111-2222-3333-444455556666/scratchpad/wt-converge")
    b = Path("/Users/someone/Documents/code/wt-converge")
    assert ws.branch_name(a) != ws.branch_name(b)
    assert ws.branch_name(a).endswith("-3fa47c70")
    assert ws.branch_name(b).endswith("-shared")


def test_the_branch_name_is_stable_for_the_same_worktree():
    """Re-running must overwrite the same branch, not accumulate one per run."""
    p = Path("/tmp/x/3fa47c70-1111-2222-3333-444455556666/scratchpad/wt-ci")
    assert ws.branch_name(p) == ws.branch_name(p)

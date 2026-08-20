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
import shutil
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


def test_a_worktree_whose_objects_live_in_another_clone_is_still_pushed(tmp_path, monkeypatch):
    """One cross-owned worktree must not take every other snapshot down with it.

    WHY THIS EXISTS, measured 2026-08-20. This machine carries TWO clones of prospector sharing
    one origin -- ~/Documents/code/prospector and one under iCloud Drive -- and each clone's
    .git/worktrees/ registers trees whose objects live in the OTHER clone's store. `snapshot()`
    runs `commit-tree` with the worktree as cwd, so the commit lands in that worktree's store,
    while the push used to run from `repo`. Pushing a sha `repo` cannot see fails with
    `fatal: bad object`, and a push is ATOMIC IN ITS ARGUMENT LIST: the whole batch dies. It
    happened in both directions on the same day -- 44 snapshots lost to `wt-method`, then 15
    lost to `prospector-live`.

    The assertion that matters is the one about the OTHER worktree. A test that only checked the
    cross-owned tree would pass on a fix that pushed it and silently dropped the rest.
    """
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    origin = tmp_path / "origin.git"

    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(origin), "seed")
    git(seed, "config", "user.email", "t@t")
    git(seed, "config", "user.name", "t")
    (seed / "kept.txt").write_text("original\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "first")
    git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")

    clones = {}
    for name in ("a", "b"):
        git(tmp_path, "clone", "-q", str(origin), name)
        clones[name] = tmp_path / name
        git(clones[name], "config", "user.email", "t@t")
        git(clones[name], "config", "user.name", "t")

    trees = {}
    for name in ("a", "b"):
        wt = tmp_path / f"wt-{name}"
        git(clones[name], "worktree", "add", "-q", "--detach", str(wt))
        (wt / "kept.txt").write_text(f"uncommitted work in {name}\n")
        trees[name] = wt

    # Cross-registration, exactly as it exists on this machine: clone A lists wt-b, but wt-b/.git
    # still points at clone B, so wt-b's objects are written to B's store and A cannot see them.
    shutil.copytree(clones["b"] / ".git" / "worktrees" / "wt-b",
                    clones["a"] / ".git" / "worktrees" / "wt-b")
    listed = git(clones["a"], "worktree", "list", "--porcelain")
    assert str(trees["b"]) in listed, "fixture is vacuous: clone A does not list the foreign tree"
    assert ws.git(["cat-file", "-t", git(trees["b"], "rev-parse", "HEAD")],
                  clones["a"])[0] == 0
    monkeypatch.setattr(sys, "argv",
                        ["worktree_snapshot.py", "--push", "--repo", str(clones["a"]),
                         "--prefix", "snap/test"])
    rc = ws.main()

    refs = git(origin, "for-each-ref", "--format=%(refname)")
    assert "snap/test/wt-a-shared" in refs, (
        "the snapshot of clone A's OWN worktree was lost as collateral of the foreign one")
    assert "snap/test/wt-b-shared" in refs, "the cross-owned worktree was never pushed"
    assert rc == 0, "a run that pushed everything must not report failure"

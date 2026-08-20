"""Running the snapshotter twice must not be refused, and the prefix must be TODAY.

WHY THIS EXISTS. Measured 2026-08-20 03:36 BST. Every session start runs
`scripts/checkout_currency.py --fix`, whose first fence is "nothing is lost": snapshot the dirty
worktrees to origin, and refuse to move the checkout if that fails. It had been failing since the
previous day with

    ! [rejected]  ... (non-fast-forward)
    hint: Updates were rejected because a pushed branch tip is behind its remote counterpart

so the checkout the whole mechanism exists to keep current was frozen, and the hook line above it
read `hook success:`. Two defects, one symptom:

  1. The branch prefix came from `git log -1 --format=%cs` -- the HEAD commit's date -- and the
     variable holding it was called `today`. HEAD was a day old, so every run landed in
     yesterday's namespace where every branch already existed.
  2. Even with the right date, a SECOND run on the same day pushes a new commit to a branch name
     derived only from the worktree. The new commit's parent is that worktree's HEAD, not the
     earlier snapshot, so it is a non-fast-forward and git refuses it. A branch name with no
     content in it can only be written once.

The fix is a name that carries the content and a commit that is a pure function of it. These
tests push to a real bare remote twice, because that is the only place the defect was visible:
report mode was green throughout.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import worktree_snapshot as ws  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture
def estate(tmp_path: Path, monkeypatch) -> Path:
    """A repo whose HEAD commit is BACKDATED, with a bare origin and one dirty worktree."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))

    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "config", "user.email", "t@t")
    git(main, "config", "user.name", "t")
    # Nothing installs this repo's pre-push hook, but be explicit: the estate's hook would
    # otherwise run against a fixture and grade it.
    git(main, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (main / "kept.txt").write_text("original\n")
    git(main, "add", "-A")
    old = "2020-01-02T03:04:05+00:00"
    monkeypatch.setenv("GIT_AUTHOR_DATE", old)
    monkeypatch.setenv("GIT_COMMITTER_DATE", old)
    git(main, "commit", "-q", "-m", "first")
    monkeypatch.delenv("GIT_AUTHOR_DATE")
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    git(main, "remote", "add", "origin", str(bare))

    wt = tmp_path / "wt-one"
    git(main, "worktree", "add", "-q", "--detach", str(wt))
    (wt / "kept.txt").write_text("uncommitted work\n")
    return main


def run(repo: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "worktree_snapshot.py"),
                        "--repo", str(repo), *args],
                       capture_output=True, text=True, check=False, cwd=str(repo))
    return p.returncode, p.stdout + p.stderr


def remote_branches(repo: Path) -> list[str]:
    out = git(repo, "ls-remote", "--heads", "origin")
    return sorted(line.split("refs/heads/")[1] for line in out.splitlines() if line.strip())


def test_the_second_push_of_unchanged_work_is_not_refused(estate: Path):
    """The live failure, reproduced: two runs, no edit between them."""
    code, first = run(estate, "--push")
    assert code == 0, first
    before = remote_branches(estate)
    assert len(before) == 1, before

    code, second = run(estate, "--push")
    assert code == 0, second
    assert "rejected" not in second and "non-fast-forward" not in second
    # And it added nothing, because nothing changed. Same content, same branch, same commit.
    assert remote_branches(estate) == before


def test_changed_work_lands_beside_the_earlier_snapshot_instead_of_over_it(estate: Path):
    """A force-push would make the promise 'nothing is lost' false for the first snapshot."""
    assert run(estate, "--push")[0] == 0
    first = remote_branches(estate)
    (estate.parent / "wt-one" / "kept.txt").write_text("a later, different edit\n")

    code, out = run(estate, "--push")
    assert code == 0, out
    after = remote_branches(estate)
    assert len(after) == 2, after
    assert set(first) < set(after), "the earlier snapshot was overwritten, not kept"


def test_the_prefix_is_todays_date_and_not_the_head_commits(estate: Path):
    """The fixture's only commit is dated 2020-01-02. The branch must not be filed under it."""
    assert run(estate, "--push")[0] == 0
    branch = remote_branches(estate)[0]
    assert branch.startswith(f"snapshot/{dt.date.today().isoformat()}/"), branch
    assert "2020-01-02" not in branch


def test_the_branch_name_carries_the_snapshot_content(estate: Path):
    """Without this the name can only ever be written once."""
    assert run(estate, "--push")[0] == 0
    branch = remote_branches(estate)[0]
    sha = git(estate, "ls-remote", "origin", f"refs/heads/{branch}").split()[0]
    tree = git(estate, "rev-parse", f"{sha}^{{tree}}")
    assert branch.endswith(tree[:8]), f"{branch} does not name the tree {tree[:8]} it holds"


def test_the_same_dirty_tree_snapshots_to_the_same_commit_twice(estate: Path):
    """Determinism is what makes the re-push a no-op rather than a fight."""
    wt = estate.parent / "wt-one"
    a, err_a = ws.snapshot(wt)
    b, err_b = ws.snapshot(wt)
    assert a and b, (err_a, err_b)
    assert a == b


def test_a_run_that_can_find_no_worktree_says_so_instead_of_reporting_nothing_to_do(tmp_path: Path):
    """`--repo` exists because __file__ is /tmp when the SessionStart hook runs this from
    origin/main. Pointed at a directory that is not a repository, the honest answer is a
    failure, not the green line 'No worktree holds uncommitted work'."""
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    code, out = run(empty)
    assert code != 0, out
    assert "No worktree holds uncommitted work" not in out

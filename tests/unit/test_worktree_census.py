"""The probe that finds work living in one place with nothing watching it.

Every test here runs against a REAL git repository built in a temp directory, with a real bare
remote. A census of worktrees mocked out of subprocess calls would be a census of the mocks: the
one question this answers — does any remote ref contain this commit — is a git question.

The negative fixture is the point, per the estate rule that a gate must prove it can fail: a
worktree with an unpushed commit must be reported, and the SAME worktree must stop being reported
once the commit is pushed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import worktree_census as census  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          timeout=60, check=True)
    return proc.stdout.strip()


@pytest.fixture()
def estate(tmp_path: Path):
    """A bare remote, a clone with one commit on main, and nothing else yet."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                   capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hello\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "first")
    git(repo, "push", "-u", "origin", "main")
    return repo


def _worktree_with_a_commit(repo: Path, name: str) -> Path:
    path = repo.parent / name
    git(repo, "worktree", "add", "-b", name, str(path), "main")
    (path / f"{name}.txt").write_text("work\n")
    git(path, "add", f"{name}.txt")
    git(path, "commit", "-m", f"work in {name}")
    return path


def test_a_worktree_whose_commits_are_on_no_remote_is_reported(estate):
    """THE NEGATIVE FIXTURE. Measured on 2026-08-19: 13 worktrees in this estate were in exactly
    this state, holding up to 34 commits each, and nothing said so."""
    path = _worktree_with_a_commit(estate, "feat-unpushed")
    row = census.survey(path)
    assert row["only_here"] is True
    assert row["ahead"] == 1
    assert row["remote_ref"] == ""


def test_the_same_worktree_stops_being_reported_once_it_is_pushed(estate):
    """The other half of the fixture. A probe that reports every worktree is not measuring
    anything."""
    path = _worktree_with_a_commit(estate, "feat-pushed")
    assert census.survey(path)["only_here"] is True
    git(path, "push", "-u", "origin", "feat-pushed")
    row = census.survey(path)
    assert row["only_here"] is False
    assert "feat-pushed" in row["remote_ref"]


def test_containment_counts_not_the_branch_name(estate):
    """A commit pushed under a DIFFERENT name is still safe. Judging by branch name would report
    it as lost — which is what the dead-branch guard's rescue does: it pushes to a fresh name."""
    path = _worktree_with_a_commit(estate, "feat-renamed")
    sha = git(path, "rev-parse", "HEAD")
    git(path, "push", "origin", f"{sha}:refs/heads/rescued-2")
    assert census.survey(path)["only_here"] is False


def test_uncommitted_changes_are_counted(estate):
    path = _worktree_with_a_commit(estate, "feat-dirty")
    (path / "scratch.txt").write_text("not committed\n")
    assert census.survey(path)["dirty"] == 1


def test_a_worktree_with_no_commits_of_its_own_is_not_flagged(estate):
    """Clean and level with main. Flagging this would drown the real ones."""
    path = estate.parent / "idle"
    git(estate, "worktree", "add", "--detach", str(path), "main")
    row = census.survey(path)
    assert row["only_here"] is False
    assert row["ahead"] == 0


def test_a_worktree_whose_folder_was_deleted_is_reported_not_skipped(estate):
    """git keeps listing it. Silently dropping it hides a tree that may have held work."""
    path = _worktree_with_a_commit(estate, "feat-gone")
    for child in sorted(path.rglob("*"), reverse=True):
        child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
    path.rmdir()
    assert census.survey(path)["missing"] is True


def test_the_census_lists_every_worktree_and_puts_the_risky_ones_first(estate):
    _worktree_with_a_commit(estate, "feat-a")
    git(estate, "worktree", "add", "--detach", str(estate.parent / "clean"), "main")
    rows = census.census(estate)
    assert len(rows) == 3                      # the main checkout plus two
    assert rows[0]["only_here"] is True        # riskiest first, so a long list still reads


def test_report_mode_exits_zero_and_strict_mode_does_not(estate, capsys):
    """Report mode before fix mode. A probe that fails the build merely by existing gets deleted
    rather than acted on — so the exit code is opt-in."""
    _worktree_with_a_commit(estate, "feat-b")
    assert census.main(["--repo", str(estate)]) == 0
    assert "ONLY HERE" in capsys.readouterr().out
    assert census.main(["--repo", str(estate), "--strict"]) == 1


def test_strict_mode_is_green_when_everything_is_pushed(estate):
    path = _worktree_with_a_commit(estate, "feat-c")
    git(path, "push", "-u", "origin", "feat-c")
    assert census.main(["--repo", str(estate), "--strict"]) == 0


def test_json_output_is_json(estate, capsys):
    """The console reads this. A table it has to parse would drift the moment a column moves."""
    import json
    _worktree_with_a_commit(estate, "feat-d")
    census.main(["--repo", str(estate), "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert any(r["only_here"] for r in rows)

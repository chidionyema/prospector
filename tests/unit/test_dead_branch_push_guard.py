"""The push guard that stops work landing on a branch GitHub already deleted.

The incident it comes from is in the module docstring of `scripts/guard_dead_branch_push.py`. What
is pinned here is the part that decides, plus the part a guard usually gets wrong: PROVING IT CAN
FAIL. A fence that only has a green fixture is a fence nobody has seen refuse anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import guard_dead_branch_push as guard  # noqa: E402

ZERO = "0" * 40
SHA = "9feccbeaa3d12b3ec96b8523415d575a93176ad5"
GUARD = Path(__file__).resolve().parents[2] / "scripts" / "guard_dead_branch_push.py"


def _run(stdin: str, env_extra: dict[str, str] | None = None, path: str = "") -> subprocess.CompletedProcess:
    """The whole script, end to end, the way git runs it."""
    import os

    env = dict(os.environ)
    env.pop(guard.OVERRIDE, None)
    if path:
        env["PATH"] = path
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True, env=env, timeout=60
    )


# --------------------------------------------------------------------------------------------
# Which pushes are even looked at
# --------------------------------------------------------------------------------------------


def test_a_push_that_creates_a_branch_is_the_only_case_checked():
    """A remote sha of zeros is git saying the branch does not exist yet. Everything else — a
    normal update, a deletion — is left alone, so the guard costs nothing on the common path."""
    creates = f"refs/heads/feat/x {SHA} refs/heads/feat/x {ZERO}"
    assert guard.created_branches(creates) == ["feat/x"]


def test_updating_an_existing_branch_is_not_checked():
    updates = f"refs/heads/feat/x {SHA} refs/heads/feat/x abc1234"
    assert guard.created_branches(updates) == []


def test_deleting_a_branch_is_not_checked():
    deletes = f"(delete) {ZERO} refs/heads/feat/x {SHA}"
    assert guard.created_branches(deletes) == []


def test_a_tag_is_not_a_branch():
    """Tags are created by definition and have no PR behind them. Treating one as a branch would
    block every release tag."""
    tags = f"refs/tags/v1 {SHA} refs/tags/v1 {ZERO}"
    assert guard.created_branches(tags) == []


def test_several_refs_in_one_push_are_all_considered():
    text = "\n".join([
        f"refs/heads/a {SHA} refs/heads/a {ZERO}",
        f"refs/heads/b {SHA} refs/heads/b def4567",
        f"refs/heads/c {SHA} refs/heads/c {ZERO}",
    ])
    assert guard.created_branches(text) == ["a", "c"]


def test_junk_on_stdin_is_ignored_not_fatal():
    """git writes nothing on stdin for some pushes. A guard that crashes on an empty line blocks
    a push for a reason that has nothing to do with branches."""
    assert guard.created_branches("") == []
    assert guard.created_branches("garbage\n\n") == []


# --------------------------------------------------------------------------------------------
# THE GATE MUST PROVE IT CAN FAIL. A fake `gh` on PATH answers for GitHub.
# --------------------------------------------------------------------------------------------


@pytest.fixture()
def fake_gh(tmp_path: Path):
    """Builds a `gh` that returns whatever the test wants, and puts it first on PATH."""

    def build(stdout: str, code: int = 0) -> str:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        script = bin_dir / "gh"
        script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{stdout}\nEOF\nexit {code}\n")
        script.chmod(0o755)
        return f"{bin_dir}:/usr/bin:/bin"

    return build


def test_it_blocks_a_push_that_recreates_a_merged_branch(fake_gh):
    """THE NEGATIVE FIXTURE. On 2026-08-19 this exact push was allowed and the work sat on a
    branch with no PR."""
    path = fake_gh('[{"number": 364}]')
    got = _run(f"refs/heads/process/incident-loop {SHA} refs/heads/process/incident-loop {ZERO}", path=path)
    assert got.returncode == 1
    assert "PR #364" in got.stdout
    assert "process/incident-loop" in got.stdout
    # It says what to do instead, because a block with no next step gets overridden on reflex.
    assert "cherry-pick" in got.stdout


def test_it_allows_a_genuinely_new_branch(fake_gh):
    path = fake_gh("[]")
    got = _run(f"refs/heads/feat/brand-new {SHA} refs/heads/feat/brand-new {ZERO}", path=path)
    assert got.returncode == 0, got.stdout


def test_it_blocks_rather_than_shrugs_when_github_cannot_be_asked(fake_gh):
    """A guard that waves the push through whenever it cannot check is a warning, and a warning
    is not a fence. Memory: a-warning-fence-is-not-a-fence.md."""
    path = fake_gh("could not connect", code=1)
    got = _run(f"refs/heads/feat/x {SHA} refs/heads/feat/x {ZERO}", path=path)
    assert got.returncode == 1
    assert "cannot ask GitHub" in got.stdout


def test_no_gh_on_the_machine_blocks_too(tmp_path: Path):
    """The runners have no `gh` (memory: self-hosted-runners-have-no-gh-cli.md). Missing must not
    read as clean."""
    empty = tmp_path / "empty"
    empty.mkdir()
    got = _run(f"refs/heads/feat/x {SHA} refs/heads/feat/x {ZERO}", path=str(empty))
    assert got.returncode == 1


def test_the_override_is_one_variable_and_it_works(fake_gh):
    """Recreating a branch on purpose is a real thing to want. The escape hatch is named in the
    refusal message, so it is a decision rather than a workaround somebody has to invent."""
    path = fake_gh('[{"number": 364}]')
    got = _run(
        f"refs/heads/process/incident-loop {SHA} refs/heads/process/incident-loop {ZERO}",
        env_extra={guard.OVERRIDE: "1"},
        path=path,
    )
    assert got.returncode == 0


def test_a_normal_push_makes_no_network_call_at_all(tmp_path: Path):
    """With no `gh` anywhere, updating an existing branch still succeeds — proof the common path
    never asks GitHub anything."""
    empty = tmp_path / "empty"
    empty.mkdir()
    got = _run(f"refs/heads/feat/x {SHA} refs/heads/feat/x abc1234", path=str(empty))
    assert got.returncode == 0


# --------------------------------------------------------------------------------------------
# It is wired in, not just written
# --------------------------------------------------------------------------------------------


def test_the_pre_push_hook_actually_calls_the_guard():
    """A guard nobody runs is a file. This is the line that makes it a fence."""
    hook = (Path(__file__).resolve().parents[2] / ".githooks" / "pre-push").read_text()
    assert "guard_dead_branch_push.py" in hook


def test_the_hook_feeds_stdin_through():
    """git hands the refs on stdin. A hook that calls the guard without passing stdin gives it an
    empty push to inspect, which passes every time — a fence that can never refuse."""
    hook = (Path(__file__).resolve().parents[2] / ".githooks" / "pre-push").read_text()
    assert "refs=" in hook and 'printf "%s"' in hook

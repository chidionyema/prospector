"""The push guard that stops work landing on a branch GitHub already deleted.

The incident it comes from is in the module docstring of `scripts/guard_dead_branch_push.py`. What
is pinned here is the part that decides, plus the part a guard usually gets wrong: PROVING IT CAN
FAIL. A fence that only has a green fixture is a fence nobody has seen refuse anything.

It is pinned as a CLASS, never as the branch that taught it: every branch a push would create is
checked, and both ways a PR finishes — merged, or closed without merging — count as spent. The one
name that is never blocked is a branch with an OPEN PR, because that push is just updating it.
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
    # THE AUTO-FIX IS OFF UNLESS A TEST ASKS FOR IT, and this is a safety fence, not tidiness.
    # A rescue runs a real `git push`. A test that left it on, with the real git on PATH, would
    # push a branch to the real origin from the test suite.
    env[guard.NO_AUTOFIX] = "1"
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
    path = fake_gh('[{"number": 364, "state": "MERGED"}]')
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
    path = fake_gh('[{"number": 364, "state": "MERGED"}]')
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


def test_a_closed_pr_spends_the_name_just_like_a_merged_one(fake_gh):
    """THE CLASS, not the one branch. A PR closed without merging leaves the same dead name: the
    branch gets deleted, and pushing it again puts work somewhere nobody is looking. Blocking only
    the merged half would have been a fence around one instance of the failure."""
    path = fake_gh('[{"number": 401, "state": "CLOSED"}]')
    got = _run(f"refs/heads/feat/abandoned {SHA} refs/heads/feat/abandoned {ZERO}", path=path)
    assert got.returncode == 1
    assert "PR #401" in got.stdout
    assert "closed without merging" in got.stdout


def test_an_open_pr_on_the_same_name_is_never_blocked(fake_gh):
    """The branch was recreated and something is already watching it, so the work is not stranded.
    Refusing here would break the ordinary case of re-pushing a branch after a local reset."""
    path = fake_gh('[{"number": 500, "state": "OPEN"}, {"number": 364, "state": "MERGED"}]')
    got = _run(f"refs/heads/feat/live {SHA} refs/heads/feat/live {ZERO}", path=path)
    assert got.returncode == 0, got.stdout


def test_every_created_branch_in_one_push_is_checked_not_just_the_first(fake_gh):
    """`git push --all` creates several at once. A guard that inspected only the first ref would
    pass the push that carried the dead branch in second place."""
    path = fake_gh('[{"number": 364, "state": "MERGED"}]')
    text = "\n".join([
        f"refs/heads/feat/one {SHA} refs/heads/feat/one {ZERO}",
        f"refs/heads/feat/two {SHA} refs/heads/feat/two {ZERO}",
    ])
    got = _run(text, path=path)
    assert got.returncode == 1
    assert "feat/one" in got.stdout and "feat/two" in got.stdout


# --------------------------------------------------------------------------------------------
# IT FIXES THE PUSH, it does not only refuse it.
#
# Every test here runs against a FAKE git as well as a fake gh. The rescue really does run
# `git push`, so a test that let the real git through would push to the real origin.
# --------------------------------------------------------------------------------------------


@pytest.fixture()
def fake_estate(tmp_path: Path):
    """A fake `git` and `gh` that record every call, so the fix can be inspected command by
    command. `feat/dead` has a merged PR; any name with a suffix is free."""
    bin_dir = tmp_path / "estate"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    common = f'''#!/usr/bin/env python3
import json, sys, pathlib
argv = sys.argv[1:]
pathlib.Path({str(log)!r}).open("a").write(" ".join(argv) + "\\n")
'''

    (bin_dir / "gh").write_text(common + '''
if argv[:2] == ["pr", "list"]:
    head = argv[argv.index("--head") + 1]
    # A name with a numeric suffix is one the guard invented: free by construction.
    print("[]" if head.rsplit("-", 1)[-1].isdigit() else '[{"number": 364, "state": "MERGED"}]')
elif argv[:2] == ["pr", "create"]:
    print("https://github.com/o/r/pull/999")
sys.exit(0)
''')
    (bin_dir / "git").write_text(common + '''
if argv[:1] == ["ls-remote"]:
    print("")          # nothing on the remote by that name
elif argv[:1] == ["log"]:
    print("feat: the rescued commit")
sys.exit(0)
''')
    for name in ("gh", "git"):
        (bin_dir / name).chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin", log


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_it_pushes_the_work_to_a_free_name_and_opens_a_draft_pr(fake_estate):
    """The whole point. Founder, 2026-08-19: "the guard could auto fix also". Detection was never
    the hard part — the manual recovery is what went wrong, because the cherry-pick conflicted."""
    path, log = fake_estate
    got = _run(
        f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
        env_extra={guard.NO_AUTOFIX: "0"},
        path=path,
    )
    assert got.returncode == 1, got.stdout          # the ORIGINAL push still must not happen
    assert "DID IT FOR YOU" in got.stdout
    assert "feat/dead-2" in got.stdout
    assert "pull/999" in got.stdout

    calls = _calls(log)
    assert any(c.startswith(f"push --no-verify origin {SHA}:refs/heads/feat/dead-2") for c in calls), calls


def test_the_pr_it_opens_is_a_draft(fake_estate):
    """This repo auto-merges on green. A hook that opened an ordinary PR could ship code to main
    that no human asked to ship, which would be a worse bug than the one being fixed."""
    path, log = fake_estate
    _run(f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
         env_extra={guard.NO_AUTOFIX: "0"}, path=path)
    create = [c for c in _calls(log) if c.startswith("pr create")]
    assert create and "--draft" in create[0], create


def test_the_fix_never_touches_the_working_tree(fake_estate):
    """It pushes `<sha>:refs/heads/<name>`, which needs no local branch. A hook that moved HEAD
    under a running `git push` would be the worse bug."""
    path, log = fake_estate
    _run(f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
         env_extra={guard.NO_AUTOFIX: "0"}, path=path)
    forbidden = ("checkout", "reset", "branch -m", "rebase", "cherry-pick", "commit")
    assert not [c for c in _calls(log) if c.startswith(forbidden)], _calls(log)


def test_a_rescue_that_fails_falls_back_to_the_recipe_and_claims_nothing(tmp_path: Path):
    """Half a fix reported as a whole one is worse than no fix. When the push fails the message
    says so and prints the manual steps."""
    bin_dir = tmp_path / "broken"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(
        '#!/bin/sh\ncase "$*" in *--head*-[0-9]*) echo "[]";; *pr\\ list*) '
        'echo \'[{"number": 364, "state": "MERGED"}]\';; esac\nexit 0\n')
    (bin_dir / "git").write_text(
        '#!/bin/sh\ncase "$1" in ls-remote) echo "";; push) echo "denied" >&2; exit 1;; esac\nexit 0\n')
    for name in ("gh", "git"):
        (bin_dir / name).chmod(0o755)

    got = _run(f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
               env_extra={guard.NO_AUTOFIX: "0"}, path=f"{bin_dir}:/usr/bin:/bin")
    assert got.returncode == 1
    assert "could not rescue" in got.stdout
    assert "DID IT FOR YOU" not in got.stdout
    assert "cherry-pick" in got.stdout


def test_the_rescue_push_cannot_re_enter_the_guard(fake_estate):
    """The fix is itself a push. Without the fence the guard would inspect its own rescue, decide
    the new branch is being created, and ask GitHub about it forever."""
    path, _log = fake_estate
    got = _run(f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
               env_extra={guard.RECURSION: "1"}, path=path)
    assert got.returncode == 0


def test_a_free_name_must_be_free_on_both_the_remote_and_in_the_pr_list():
    """Checking only one of the two lands on a name a CLOSED pr already burned — the exact failure
    being fixed, recreated by the fix."""
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "git":                                   # -2 exists on the remote
            out = "abc refs/heads/feat/x-2" if cmd[-1] == "feat/x-2" else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        taken = '[{"number": 9}]' if cmd[cmd.index("--head") + 1] == "feat/x-3" else "[]"
        return subprocess.CompletedProcess(cmd, 0, taken, "")

    assert guard.fresh_name("feat/x", run=run) == "feat/x-4"


def test_off_by_one_variable(fake_estate):
    """Somebody will want the refusal without the fix. One variable, and the tests rely on it."""
    path, log = fake_estate
    got = _run(f"refs/heads/feat/dead {SHA} refs/heads/feat/dead {ZERO}",
               env_extra={guard.NO_AUTOFIX: "1"}, path=path)
    assert got.returncode == 1
    assert "DID IT FOR YOU" not in got.stdout
    assert not [c for c in _calls(log) if c.startswith("push")]


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

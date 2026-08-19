"""The push fence on main.

GitHub will not protect main on this plan -- both protection endpoints answer 403 -- so
`scripts/guard_main_push.py` is the protection, and these tests are what stops it rotting.

Each test names the mutation it kills, because a guard with tests that pass on a broken guard is
worse than no tests: it reports safety it is not providing.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "guard_main_push.py"
HOOK = ROOT / ".githooks" / "pre-push"

spec = importlib.util.spec_from_file_location("guard_main_push", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

ZERO = "0" * 40
SHA_A = "a" * 40
SHA_B = "b" * 40


def line(local_ref: str, local_sha: str, remote_ref: str, remote_sha: str) -> str:
    return f"{local_ref} {local_sha} {remote_ref} {remote_sha}\n"


def run_guard(stdin_text: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """The guard as the hook actually invokes it: a subprocess fed refs on stdin."""
    import os
    env = dict(os.environ)
    env.pop(guard.OVERRIDE, None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(GUARD)], input=stdin_text, capture_output=True,
                          text=True, timeout=30, check=False, env=env)


# --- what it must refuse -------------------------------------------------------------------

def test_refuses_an_ordinary_push_to_main():
    """Kills: the guard doing nothing at all."""
    got = run_guard(line("refs/heads/main", SHA_A, "refs/heads/main", SHA_B))
    assert got.returncode == 1
    assert "main-push guard BLOCKED" in got.stdout


def test_refuses_a_force_push_to_main():
    """A force push arrives with the same remote ref; nothing extra is needed to catch it, and
    this test is what proves that claim rather than assuming it.

    Kills: a fence that only inspects fast-forwards.
    """
    got = run_guard(line("refs/heads/main", SHA_A, "refs/heads/main", SHA_B))
    assert got.returncode == 1


def test_refuses_deleting_main_and_says_so():
    """`git push origin :main` sends an all-zero LOCAL sha.

    Kills: treating a deletion as "no commits, nothing to check" and letting it through -- and
    kills a message that describes a deletion as an ordinary push.
    """
    got = run_guard(line("(delete)", ZERO, "refs/heads/main", SHA_B))
    assert got.returncode == 1
    assert "DELETES main" in got.stdout


@pytest.mark.parametrize("local_ref", ["HEAD", "refs/heads/main", "refs/heads/my-work"])
def test_the_local_ref_name_is_irrelevant(local_ref):
    """`HEAD:main`, `main:main` and `my-work:main` are three spellings of one push. Git resolves
    all of them to the same REMOTE ref before calling the hook, which is the whole design.

    Kills: matching on the local ref, or on the command line, instead of the destination.
    """
    got = run_guard(line(local_ref, SHA_A, "refs/heads/main", SHA_B))
    assert got.returncode == 1


def test_refuses_when_main_is_only_one_ref_among_several():
    """`git push --all` sends many lines. Git's pre-push is all-or-nothing, so one protected ref
    refuses the whole push.

    Kills: checking only the first line.
    """
    stdin = (line("refs/heads/feat-a", SHA_A, "refs/heads/feat-a", ZERO)
             + line("refs/heads/feat-b", SHA_A, "refs/heads/feat-b", ZERO)
             + line("refs/heads/main", SHA_A, "refs/heads/main", SHA_B))
    got = run_guard(stdin)
    assert got.returncode == 1


# --- what it must NOT refuse ---------------------------------------------------------------

def test_allows_an_ordinary_feature_branch():
    """Kills: a fence that blocks every push. The estate would notice, but only after it had
    blocked real work in fifty worktrees."""
    got = run_guard(line("refs/heads/feat/x", SHA_A, "refs/heads/feat/x", ZERO))
    assert got.returncode == 0
    assert got.stdout.strip() == ""


def test_allows_a_branch_whose_name_merely_starts_with_main():
    """`refs/heads/maintenance` is an ordinary branch.

    Kills: `remote_ref.startswith("refs/heads/main")`, which reads as correct and blocks
    maintenance, mainline, main-green-guard and anything else in that family.
    """
    got = run_guard(line("refs/heads/maintenance", SHA_A, "refs/heads/maintenance", SHA_B))
    assert got.returncode == 0


def test_allows_a_tag_called_main():
    """A tag's remote ref is `refs/tags/main`, not `refs/heads/main`.

    Kills: matching on the bare name `main` anywhere in the line.
    """
    got = run_guard(line("refs/tags/main", SHA_A, "refs/tags/main", ZERO))
    assert got.returncode == 0


def test_allows_an_empty_push():
    """Nothing on stdin means nothing is being written.

    Kills: a guard that refuses when it cannot see, which here would block every push git makes
    with an up-to-date remote.
    """
    assert run_guard("").returncode == 0


def test_ignores_a_malformed_line_rather_than_guessing():
    """Kills: an IndexError on a short line, which would make the hook fail with a traceback and
    teach everyone to reach for --no-verify."""
    got = run_guard("garbage\n\nrefs/heads/x " + SHA_A + "\n")
    assert got.returncode == 0


# --- the hatch -----------------------------------------------------------------------------

def test_the_hatch_lets_a_deliberate_push_through():
    """A fence with no hatch gets uninstalled, and an uninstalled fence guards nothing. The one
    real case: main is red, so nothing goes green, so nothing merges, and putting main back needs
    a direct push.

    Kills: removing the override, or misspelling the variable it reads.
    """
    got = run_guard(line("refs/heads/main", SHA_A, "refs/heads/main", SHA_B),
                    {guard.OVERRIDE: "1"})
    assert got.returncode == 0


def test_the_refusal_names_the_hatch():
    """A hatch nobody can find is not a hatch; the next person reaches for `--no-verify`, which
    disables every guard in the hook rather than this one.

    Kills: a refusal message that leaves the reader stuck.
    """
    got = run_guard(line("refs/heads/main", SHA_A, "refs/heads/main", SHA_B))
    assert guard.OVERRIDE in got.stdout
    assert "gh pr create" in got.stdout


# --- the wiring, which is where the bug was --------------------------------------------------

def test_the_hook_actually_calls_the_guard():
    """A guard nothing invokes is a file.

    It asserts the INVOCATION, not the filename. The filename also appears in the staleness check
    above, so `"scripts/guard_main_push.py" in text` still passed with the call deleted -- the
    test reported wiring that was not there.

    Kills: the wiring being dropped in a later edit.
    """
    assert 'printf "%s" "$refs" | python3 scripts/guard_main_push.py' in HOOK.read_text()


def test_the_guard_runs_after_the_staleness_check():
    """The call is unconditional, so it must sit below the block that proves the file exists. Run
    above it, a worktree older than this guard dies on `can't open file` instead of the message
    that tells it to rebase.

    Kills: exactly the ordering mistake made while writing this, which fails closed and so would
    never have shown up as a broken push.
    """
    text = HOOK.read_text()
    staleness = text.index("this tree predates a guard this hook needs")
    call = text.index("python3 scripts/guard_main_push.py")
    assert staleness < call


def test_the_staleness_check_names_this_guard():
    """A tree based between the two guard commits has one file and not the other.

    Kills: a staleness check that only knows about guard_dead_branch_push.py, which would leave
    that tree fenced against dead branch names and unfenced against main.
    """
    assert "guard_main_push.py" in HOOK.read_text().split("# WHERE the push lands")[0]

"""The compute class adapter: does it hand the cutover script the right command?

Every test here builds a THROWAWAY git repository with a fake `deploy/cutover.sh` that records
its arguments and exits 0. That is the only way to prove the argument construction without
moving a real service, and the fake is what makes the rollback direction checkable at all --
the real script's ends-swapped rollback is a claim nobody had tested.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "kit" / "classes" / "compute.sh"


@pytest.fixture
def estate(tmp_path: Path) -> Path:
    """A tiny repo holding the real adapter and a fake cutover that records its argv."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "kit" / "classes").mkdir(parents=True)
    (tmp_path / "deploy").mkdir()
    shutil.copy(SCRIPT, tmp_path / "kit" / "classes" / "compute.sh")
    fake = tmp_path / "deploy" / "cutover.sh"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$(dirname "$0")/../argv.txt"\n')
    fake.chmod(0o755)
    return tmp_path


def call(estate: Path, verb: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run([str(estate / "kit" / "classes" / "compute.sh"), verb],
                          capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(estate), **env})


def argv(estate: Path) -> list[str]:
    return (estate / "argv.txt").read_text().split()


def test_a_move_names_both_ends_in_the_order_it_was_given(estate: Path):
    done = call(estate, "move", RESOURCE="engine", FROM="laptop", TO="fly")
    assert done.returncode == 0, done.stderr
    assert argv(estate) == ["--from", "laptop", "--to", "fly"]


def test_a_rollback_swaps_the_ends(estate: Path):
    """The whole point of the verb. If this passes the ends through unswapped it moves the
    service AGAIN, in the direction that just failed, with the source already stopped."""
    done = call(estate, "rollback", RESOURCE="engine", FROM="laptop", TO="fly")
    assert done.returncode == 0, done.stderr
    assert argv(estate) == ["--from", "fly", "--to", "laptop"]


def test_a_rollback_with_both_ends_the_same_does_nothing(estate: Path):
    done = call(estate, "rollback", RESOURCE="engine", FROM="fly", TO="fly")
    assert done.returncode == 0
    assert not (estate / "argv.txt").exists(), "it called the cutover script anyway"


def test_a_missing_end_is_refused_AND_SAYS_WHICH_ONE(estate: Path):
    """`set -u` already stops an unset end, so the exit code alone proves nothing -- a first
    version of this test passed with the explicit checks deleted. What the checks actually buy
    is the diagnosis: "no FROM -- the runner must name the substrate this resource is on" tells
    the person watching that the PLAN is short a field. `FROM: unbound variable` does not.
    """
    for given, absent in (({"FROM": "laptop"}, "TO"), ({"TO": "fly"}, "FROM")):
        done = call(estate, "move", RESOURCE="engine", **given)
        assert done.returncode != 0
        assert not (estate / "argv.txt").exists(), f"ran the cutover without {absent}"
        assert f"no {absent}" in done.stderr, (
            f"refused without naming {absent}; stderr was {done.stderr!r}")
        assert "unbound variable" not in done.stderr, "the shell caught it, not the check"


def test_an_unknown_verb_exits_78_not_1(estate: Path):
    """78 is EX_CONFIG -- the plan is wrong and the world is untouched. The runner shows that
    differently from a step that tried and failed, and the difference decides whether the
    person watching recompiles or investigates."""
    done = call(estate, "teleport", RESOURCE="engine", FROM="laptop", TO="fly")
    assert done.returncode == 78
    assert not (estate / "argv.txt").exists()


def test_no_verb_at_all_says_which_verbs_exist(estate: Path):
    done = call(estate, "", RESOURCE="engine", FROM="laptop", TO="fly")
    assert done.returncode != 0
    assert "move" in done.stderr and "rollback" in done.stderr


def test_the_dry_run_flag_reaches_the_cutover_script(estate: Path):
    done = call(estate, "move", RESOURCE="engine", FROM="laptop", TO="fly", DRY_RUN="1")
    assert done.returncode == 0, done.stderr
    assert argv(estate) == ["--from", "laptop", "--to", "fly", "--dry-run"]

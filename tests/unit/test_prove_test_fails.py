"""The tool that proves a test can fail must itself be provably unfoolable.

Each test here is one of the ways a mutation check has silently passed in this repo.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "_prove_test_fails", REPO / "scripts" / "prove_test_fails.py")
prove = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prove
spec.loader.exec_module(prove)


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "subject.txt"
    path.write_text("alpha beta alpha\n", encoding="utf-8")
    return path


def _run(target: Path, old: str, new: str, command: list[str]) -> int:
    return prove.main(["--file", str(target), "--replace", old, "--with", new, "--", *command])


def test_a_mutation_the_command_survives_is_a_failure(target):
    assert _run(target, "alpha", "gamma", ["true"]) == 1


def test_a_mutation_the_command_catches_is_a_pass(target):
    assert _run(target, "alpha", "gamma", ["false"]) == 0


def test_a_replacement_that_matches_nothing_is_refused(target):
    """Failure mode 1: the patch did not apply, and the run that followed graded nothing."""
    assert _run(target, "nowhere-in-the-file", "x", ["false"]) == 2


def test_a_replacement_that_leaves_the_original_behind_is_refused(target):
    """Failure mode 2: a partial replacement, so the guarded behaviour is still there."""
    assert _run(target, "alpha", "alpha-ish", ["false"]) == 2


def test_every_occurrence_is_replaced_not_just_the_first(target, tmp_path):
    """The sed-without-g defect, which is what made a real fence look vacuous."""
    seen = tmp_path / "seen.txt"
    script = tmp_path / "peek.py"
    script.write_text(
        f"import pathlib,sys\n"
        f"pathlib.Path({str(seen)!r}).write_text(pathlib.Path({str(target)!r}).read_text())\n"
        f"sys.exit(1)\n", encoding="utf-8")
    assert _run(target, "alpha", "gamma", [sys.executable, str(script)]) == 0
    assert seen.read_text() == "gamma beta gamma\n"


def test_the_file_is_restored_however_it_ends(target):
    before = target.read_text()
    _run(target, "alpha", "gamma", ["false"])
    assert target.read_text() == before
    _run(target, "alpha", "gamma", ["true"])
    assert target.read_text() == before


def test_a_crashing_command_still_restores_the_file(target):
    before = target.read_text()
    with pytest.raises(Exception):
        _run(target, "alpha", "gamma", ["this-command-does-not-exist-anywhere"])
    assert target.read_text() == before


def test_mismatched_argument_counts_are_refused(target):
    assert prove.main(["--file", str(target), "--replace", "alpha", "--replace", "beta",
                       "--with", "gamma", "--", "false"]) == 2


def test_no_command_is_refused(target):
    assert prove.main(["--file", str(target), "--replace", "alpha", "--with", "g"]) == 2

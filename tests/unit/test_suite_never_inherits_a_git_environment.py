"""The test suite must not act on the index of whoever is running it.

THE INCIDENT, 2026-08-20. `scripts/popdd_verify.py --staged` is wired as this repo's pre-commit
gate, so `git commit` runs the whole pytest suite. `git commit` also exports GIT_INDEX_FILE and
GIT_DIR into that hook's environment. An inherited GIT_INDEX_FILE beats `cwd=` and beats
`git -C <dir>`, so `tests/unit/test_worktree_snapshot_touches_nothing.py` — which builds a scratch
repo in tmp_path and runs `git add -A` in it — staged the committer's tree instead of its own.

Measured independently in two worktrees:

    worktree      index before   index after   pytest verdict
    wt-engine100x        1,979             4   10 passed
    prospector-20        2,039             3   10 passed

1,977 files staged as deletions, and the suite reported green both times. The commit was killed
before it landed and `git reset` restored the index from HEAD, so nothing was lost — but only
because someone happened to look at `git diff --cached` while the gate was still running.

WHY THE GUARD IS SHAPED LIKE THIS. Asserting "no GIT_* in os.environ" inside a normal test run is
vacuous: in a normal run there is no GIT_* set, so the assertion passes without exercising
anything (memory `a-guard-that-iterates-an-empty-list-passes.md`). The only honest guard sets the
variable, runs the real suite file that did the damage, and checks the index afterwards. It is
pointed at a COPY of the real index, so this test can never harm the tree it is protecting.

The second test keys on inheritance rather than on damage, and that is deliberate. The peer
session established that the damaging shape is GIT_INDEX_FILE ALONE: with GIT_DIR also set the
fixture cannot build its temp repo and errors out early, destroying nothing (2 passed, 8 errors).
So the two cases differ only in which variables happen to be present, and a guard keyed on
observed damage would call the harmless combination safe.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CULPRIT = ROOT / "tests" / "unit" / "test_worktree_snapshot_touches_nothing.py"
CONFTEST = ROOT / "tests" / "conftest.py"

_loaded = None


def _load_suite_conftest():
    """Load tests/conftest.py BY PATH, and cache it.

    `import conftest` does not work here and fails in a way that looks like the mechanism is
    missing: pytest imports `tests/unit/conftest.py` under the bare name `conftest` first, so a
    plain import returns the wrong file and the assertion below reports "no attribute
    _strip_inherited_git_env" about a file that never had one. Measured while writing this test.
    """
    global _loaded
    if _loaded is None:
        spec = importlib.util.spec_from_file_location("_suite_conftest_under_test", CONFTEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _loaded = module
    return _loaded


def _entries(index: Path) -> int:
    """How many paths the given index file holds."""
    proc = subprocess.run(
        ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, check=True,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
             "GIT_INDEX_FILE": str(index)},
    )
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def test_a_hook_environment_cannot_reach_the_committers_index(tmp_path: Path) -> None:
    """Run the file that caused the incident, with the environment that caused it, on a decoy.

    This is the 2026-08-20 reproduction, kept as a permanent test. If the strip in
    `tests/conftest.py` is removed, the decoy index is emptied and this fails.
    """
    real_index = Path(subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=str(ROOT),
        capture_output=True, text=True, check=True).stdout.strip()) / "index"
    if not real_index.exists():
        pytest.skip(f"no index at {real_index} to copy")

    decoy = tmp_path / "decoy.index"
    shutil.copy(real_index, decoy)
    before = _entries(decoy)
    # Non-vacuity: a decoy with a handful of entries could survive by accident. The real index of
    # this repo carries about two thousand paths; anything under a few hundred means the copy did
    # not work and the test below would prove nothing.
    assert before > 500, f"decoy index holds only {before} entries — copy failed, guard is vacuous"

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_INDEX_FILE"] = str(decoy)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(CULPRIT), "-q", "-p", "no:randomly",
         "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=600,
    )

    after = _entries(decoy)
    assert after == before, (
        f"the suite rewrote an inherited index: {before} entries before, {after} after.\n"
        "A GIT_* variable is reaching git subprocesses inside tests. The strip lives in "
        "tests/conftest.py (_strip_inherited_git_env).\n"
        f"inner pytest said: {proc.stdout.strip()[-400:]}"
    )


def test_the_strip_runs_at_import_and_covers_the_whole_prefix() -> None:
    """The mechanism itself, checked where it lives.

    Keyed on inheritance, not on damage — see the module docstring for why those are different
    questions. Importing conftest is what applies the strip, so this also proves it is reachable
    at import time rather than parked behind a hook that may not be called.
    """
    conftest = _load_suite_conftest()

    assert hasattr(conftest, "_strip_inherited_git_env"), (
        "tests/conftest.py no longer strips the inherited git environment. Removing it lets the "
        "pre-commit gate destroy the committer's index; see this file's docstring."
    )
    assert hasattr(conftest, "STRIPPED_GIT_ENV"), (
        "_strip_inherited_git_env exists but nothing calls it at import time"
    )
    # The strip already ran when conftest was imported for this session, so the environment this
    # test observes must be clean regardless of what the caller exported.
    leaked = sorted(k for k in os.environ if k.startswith("GIT_"))
    assert leaked == [], f"GIT_* survived into a running test: {leaked}"


def test_it_strips_the_prefix_rather_than_a_list_of_known_names() -> None:
    """A list of the three variables that bit us is a list that goes stale.

    GIT_WORK_TREE, GIT_OBJECT_DIRECTORY, GIT_COMMON_DIR and GIT_CONFIG_GLOBAL redirect a git
    subprocess just as effectively as GIT_INDEX_FILE and GIT_DIR do.
    """
    conftest = _load_suite_conftest()

    probes =["GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY",
              "GIT_COMMON_DIR", "GIT_CONFIG_GLOBAL", "GIT_SOMETHING_INVENTED_LATER"]
    for name in probes:
        os.environ[name] = "/nowhere"
    try:
        removed = conftest._strip_inherited_git_env()
    finally:
        for name in probes:
            os.environ.pop(name, None)

    assert sorted(removed) == sorted(probes), (
        f"strip missed {sorted(set(probes) - set(removed))} — it is matching specific names "
        "rather than the GIT_ prefix"
    )

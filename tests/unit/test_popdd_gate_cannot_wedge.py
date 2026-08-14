"""The commit gate must never become the thing that blocks commits.

On 2026-08-14 it did, for 49 minutes, for every session sharing this checkout at once. The
gate runs the whole suite inside `.git/hooks/pre-commit`, so `git commit` holds
`.git/index.lock` for its entire run; a gate that cannot finish is a repo that cannot commit.
Two independent faults produced it, and both are pinned here because neither is visible from
reading the happy path:

  1. `subprocess.run(capture_output=True, timeout=...)` kills only the DIRECT child on
     timeout and then re-enters `communicate()` to drain the pipes. A grandchild that
     inherited the pipe write ends and outlived pytest holds that pipe open, so the drain
     blocks forever and `TimeoutExpired` is never raised. The hang detector hung. Observed:
     popdd_verify at 0.0% CPU for 49 minutes, no pytest process anywhere on the machine, the
     "exceeded 2400s" message never printed. pytest is exactly the process that leaves such
     grandchildren, and a multiprocessing-spawn child does not even carry "pytest" in its
     command line, so `pgrep -f pytest` finds nothing and the tree looks idle and innocent.

  2. Nothing stopped a SECOND session in the same working tree from queueing behind the
     first, which is how a ~50-minute suite becomes a ~100-minute commit cycle and how one
     wedge takes everyone down with it.

Both tests below fail (by hanging, and by passing a second acquisition) against the code as
it stood that morning.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "popdd_verify.py"


def _load_runner():
    """Import scripts/popdd_verify.py by path.

    It is a script, not a package module, and it deliberately defers its LUX import into
    main() so that importing it here needs nothing beyond the stdlib — see its module header.
    """
    spec = importlib.util.spec_from_file_location("popdd_verify_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves annotations via sys.modules[cls.__module__],
    # so a module absent from that table raises AttributeError on the Lane definition rather
    # than anything to do with this test.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pv = _load_runner()


# --- fault 1: the ceiling must actually fire -------------------------------------------


def _spawns_a_grandchild_then_hangs(escape_group: bool) -> list[str]:
    """A step that leaves a grandchild holding the inherited stdout/stderr pipes.

    This is pytest's shape, reduced: the process we can kill by handle is not the only
    process holding the pipe. `escape_group` decides whether the survivor stays in the
    step's process group (so `killpg` reaches it) or detaches into its own session (so it
    does not) — the two halves of the guarantee.
    """
    inner = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c','import time;time.sleep(45)'],"
        f" start_new_session={escape_group})\n"
        "sys.stdout.write('step started\\n'); sys.stdout.flush()\n"
        "time.sleep(600)\n"
    )
    return [sys.executable, "-c", inner]


# The ceiling used by the two hang tests. It must comfortably exceed interpreter startup for
# BOTH the step and its grandchild: measured against a 2s ceiling the kill sometimes landed
# before the grandchild existed, and the test then passed for the wrong reason — nothing was
# holding the pipe, so the drain returned cleanly and the escape was never exercised.
HANG_CEILING_SECONDS = 6


def test_a_timed_out_step_dies_even_though_a_grandchild_holds_the_pipe(tmp_path):
    """The regression. Against `subprocess.run(..., timeout=)` this hangs forever."""
    started = time.monotonic()
    with pytest.raises(pv.StepTimeout) as caught:
        pv._run_step(_spawns_a_grandchild_then_hangs(escape_group=False), tmp_path,
                     timeout=HANG_CEILING_SECONDS)
    elapsed = time.monotonic() - started

    assert elapsed < 60, (
        f"the ceiling took {elapsed:.0f}s to fire — it is being held open by the grandchild's "
        "pipe, which is the deadlock this guards"
    )
    # The group kill reached the survivor, so the drain completed and the output survived.
    assert caught.value.drained is True
    assert "step started" in caught.value.stdout


def test_the_drain_gives_up_when_a_survivor_escapes_the_process_group(tmp_path, monkeypatch):
    """A grandchild in its own session outlives `killpg` and keeps the pipe open.

    Nothing can reclaim that output. The rule is that the gate reports a TIMEOUT with no
    output rather than waiting — a bounded loss of diagnosis instead of an unbounded loss of
    the repo. If this ever hangs, the second `communicate()` has been widened back to
    unbounded.
    """
    monkeypatch.setattr(pv, "DRAIN_TIMEOUT_SECONDS", 4)
    started = time.monotonic()
    with pytest.raises(pv.StepTimeout) as caught:
        pv._run_step(_spawns_a_grandchild_then_hangs(escape_group=True), tmp_path,
                     timeout=HANG_CEILING_SECONDS)
    elapsed = time.monotonic() - started

    assert elapsed < 60, f"the bounded drain did not give up: {elapsed:.0f}s"
    assert caught.value.drained is False
    assert caught.value.stdout == ""


def test_a_normal_step_is_unaffected(tmp_path):
    result = pv._run_step([sys.executable, "-c", "print('ok')"], tmp_path, timeout=30)
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_a_failing_step_still_reports_its_output_and_code(tmp_path):
    result = pv._run_step(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
        tmp_path, timeout=30,
    )
    assert result.returncode == 3
    assert "boom" in result.stderr


def test_the_step_runs_in_its_own_process_group(tmp_path):
    """`start_new_session=True` is load-bearing, not decoration: without it `killpg` would
    signal the gate's own group — including git and the shell that launched it."""
    result = pv._run_step(
        [sys.executable, "-c", "import os; print(os.getpid() == os.getpgrp())"],
        tmp_path, timeout=30,
    )
    assert result.stdout.strip() == "True"


# --- fault 2: one gate per working tree -------------------------------------------------


def test_the_lock_lives_in_this_working_trees_own_git_dir():
    """So two worktrees never collide and two sessions in ONE tree always do.

    In a linked worktree `.git` is a file containing `gitdir:`, so this must ask git rather
    than join a path — the bug tests/unit/test_popdd_gate_lanes.py once shipped.
    """
    path = pv._gate_lock_path()
    assert path.name == "popdd-gate.lock"
    assert path.parent.is_dir(), f"{path.parent} is not a directory — .git treated as a path?"


def test_a_second_gate_in_the_same_tree_is_refused_not_queued(capsys):
    with pv.single_flight() as first:
        assert first is True
        with pv.single_flight() as second:
            assert second is False, (
                "a second gate run in the same checkout was allowed — this is the "
                "~100-minute serialised commit cycle, and the wedge that takes every "
                "session down at once"
            )
        out = capsys.readouterr().out
        assert "setup_worktree.sh" in out, "the refusal must print the fix, not just the fault"


def test_the_lock_is_released_when_the_gate_finishes():
    with pv.single_flight() as acquired:
        assert acquired is True
    assert not pv._gate_lock_path().exists()
    with pv.single_flight() as again:
        assert again is True


def test_the_lock_is_released_even_when_the_gate_raises():
    with pytest.raises(RuntimeError):
        with pv.single_flight() as acquired:
            assert acquired is True
            raise RuntimeError("lane exploded")
    assert not pv._gate_lock_path().exists()


def test_a_dead_holder_does_not_brick_the_repo():
    """A crash or a SIGKILL must not leave a lock that blocks every future commit — that
    would just be a new way to be stuck. PID 2^31-1 does not exist."""
    path = pv._gate_lock_path()
    path.write_text(json.dumps({"pid": 2147483647, "started": time.time(), "tree": "x"}))
    try:
        with pv.single_flight() as acquired:
            assert acquired is True
            assert json.loads(path.read_text())["pid"] == os.getpid()
    finally:
        path.unlink(missing_ok=True)


def test_an_unreadable_lock_is_treated_as_stale():
    path = pv._gate_lock_path()
    path.write_text("{ this is not json")
    try:
        with pv.single_flight() as acquired:
            assert acquired is True
    finally:
        path.unlink(missing_ok=True)


def test_a_wedged_holder_is_named_so_it_can_be_cleared(capsys):
    """Past its own ceiling, the holder is not slow, it is wedged. The operator needs the PID
    and the command, not a suggestion to be patient."""
    path = pv._gate_lock_path()
    ancient = time.time() - (pv.TEST_TIMEOUT_SECONDS + pv.DRAIN_TIMEOUT_SECONDS + 3600)
    path.write_text(json.dumps({"pid": os.getpid(), "started": ancient, "tree": "x"}))
    try:
        with pv.single_flight() as acquired:
            assert acquired is False
        out = capsys.readouterr().out
        assert "wedged" in out.lower()
        assert f"kill {os.getpid()}" in out
    finally:
        path.unlink(missing_ok=True)

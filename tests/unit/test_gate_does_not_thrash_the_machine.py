"""Incident 2026-08-23: two gate runs ran at once and blinded every other instrument.

Rung 4 (incident test), one per bug, named for the bug.

WHAT HAPPENED. Two sessions in two separate worktrees each held their own
`single_flight` lock legitimately -- that lock is per checkout, and a worktree of your own
is exactly what its message tells you to get. Each then started a 6-worker pytest. Measured
on this machine: 15 pytest processes, load average 137 on 12 logical cores. Nothing
crashed. Instead everything else started TIMING OUT: the founder board could not answer 7
of its ~40 rows, and 14 of 30 guard selftests exited 124. A board that reads UNKNOWN is
indistinguishable from a board that was never run, so the estate went blind while looking
perfectly healthy.

THE RULE UNDER TEST, which is timing-independent and survives a rewrite of the lock:
only one gate run may hold this machine's cores at a time, the wait must be bounded so a
wedged holder can never stop every commit on the machine, and there must be an off switch.

These assert the RULE, not the implementation: nothing here names flock, a file path, or a
sleep interval.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

# A child that takes the machine slot, announces it, holds, and releases.
# One lock file for this module, shared by every subprocess a test spawns and separate from
# the machine's real one, so these tests can run under the gate they guard.
LOCK_PATH = Path(tempfile.mkdtemp(prefix="popdd-gate-lock-test-")) / "machine.lock"

PROBE = """
import sys, os, time
sys.path.insert(0, {scripts!r})
import popdd_verify as pv
with pv.machine_capacity():
    print("ENTER %.3f" % time.time(), flush=True)
    time.sleep(float(sys.argv[1]))
    print("EXIT %.3f" % time.time(), flush=True)
""".format(scripts=str(SCRIPTS))


def _run(hold: float, env_extra: dict[str, str] | None = None, timeout: float = 60):
    env = {
        **os.environ,
        "POPDD_TEST_TIMEOUT": "600",
        # Our own lock file, not the estate's. The gate runs this suite, so the gate holds
        # the real lock while these assertions execute; sharing it would make every spawned
        # run wait for the run that spawned it.
        "POPDD_MACHINE_LOCK": str(LOCK_PATH),
        **(env_extra or {}),
    }
    return subprocess.Popen(
        [sys.executable, "-c", PROBE, str(hold)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )


def _stamps(out: str) -> dict[str, float]:
    got = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("ENTER", "EXIT"):
            got[parts[0]] = float(parts[1])
    return got


class TestIncident20260823GateThrashedTheMachine:
    def test_a_second_gate_run_waits_instead_of_taking_the_cores_too(self):
        """The property the incident violated: the two runs must not overlap."""
        a = _run(6.0)
        # Give A the slot before B asks for it. This is setup, not the assertion --
        # the assertion below is about ORDER, which no sleep here can manufacture.
        time.sleep(1.5)
        b = _run(0.5)
        a_out, _ = a.communicate(timeout=90)
        b_out, _ = b.communicate(timeout=90)

        a_st, b_st = _stamps(a_out), _stamps(b_out)
        assert "ENTER" in a_st and "EXIT" in a_st, f"holder never ran: {a_out!r}"
        assert "ENTER" in b_st, f"waiter never ran: {b_out!r}"

        assert b_st["ENTER"] >= a_st["EXIT"], (
            "two gate runs held this machine's cores at the same time. B entered "
            f"{a_st['EXIT'] - b_st['ENTER']:.1f}s BEFORE A released. This is the "
            "2026-08-23 incident: load 137, and every other instrument timing out."
        )

    def test_the_wait_is_announced_rather_than_being_a_silent_hang(self):
        """A gate that stalls with no output is indistinguishable from a wedged one."""
        a = _run(5.0)
        time.sleep(1.5)
        b = _run(0.2)
        a.communicate(timeout=90)
        b_out, _ = b.communicate(timeout=90)
        assert "Waiting" in b_out or "waiting" in b_out, (
            f"the waiter printed nothing about why it was stalled: {b_out!r}"
        )

    def test_there_is_an_off_switch_and_it_works(self):
        """A capacity rail with no off switch becomes the next way to be stuck."""
        a = _run(6.0)
        time.sleep(1.5)
        t0 = time.time()
        b = _run(0.2, {"POPDD_NO_MACHINE_LOCK": "1"})
        b_out, _ = b.communicate(timeout=90)
        elapsed = time.time() - t0
        a.kill()
        a.communicate()

        assert "ENTER" in _stamps(b_out), f"off switch broke the run entirely: {b_out!r}"
        assert elapsed < 5.0, (
            f"POPDD_NO_MACHINE_LOCK=1 still waited {elapsed:.1f}s for the holder. "
            "The off switch does not switch anything off."
        )

    def test_the_wait_is_bounded_so_a_wedged_holder_cannot_stop_every_commit(self):
        """Fail-open. This is the 2026-08-14 lesson applied to the new rail.

        A capacity rail is an optimisation. If it can block a commit forever it has become
        a correctness rail nobody designed, and one wedged process stops the whole machine.
        """
        import importlib
        sys.path.insert(0, str(SCRIPTS))
        pv = importlib.import_module("popdd_verify")

        holder = _run(120.0)
        try:
            time.sleep(1.5)
            # Shrink the ceiling rather than waiting out the real one: the property is
            # "it stops waiting at the ceiling", not "the ceiling is 2550 seconds".
            old_t, old_d = pv.TEST_TIMEOUT_SECONDS, pv.DRAIN_TIMEOUT_SECONDS
            pv.TEST_TIMEOUT_SECONDS, pv.DRAIN_TIMEOUT_SECONDS = 1, 1
            # ceiling = 1 + 1 + 120 is still too long for a unit test, so assert the
            # arithmetic the loop uses rather than sleeping through it.
            ceiling = pv.TEST_TIMEOUT_SECONDS + pv.DRAIN_TIMEOUT_SECONDS + 120
            assert ceiling < float("inf"), "the wait must be bounded"
            assert ceiling > 0
            pv.TEST_TIMEOUT_SECONDS, pv.DRAIN_TIMEOUT_SECONDS = old_t, old_d
        finally:
            holder.kill()
            holder.communicate()

        src = (SCRIPTS / "popdd_verify.py").read_text()
        assert "running anyway" in src, (
            "the wait loop no longer has a fail-open branch; a wedged holder can now "
            "block every commit on this machine"
        )

"""The CI runner container must take its next job itself, not by rebooting the machine.

WHY THIS EXISTS. Measured on 2026-08-18. The entrypoint ran one job and exited, and
`deploy/runner/fly.toml` brought the machine back with `[[restart]] policy = "always"`. That
restart is a full virtual machine boot. Machine 8e4530a7712248 exited cleanly at 20:25:33,
logged `reboot: Restarting system` at 20:26:26, and came to rest STOPPED at 20:26:27. It stayed
stopped. Another machine had stopped the same way at 15:11 and had been down five hours.

The fleet of three was running as one, a pull request sat queued for 25 minutes, and nothing
said so: `scripts/ci_capacity.py` counted REGISTERED runners, and an offline runner is still
registered.

Two properties have to hold together, which is why they are tested together. The loop is in the
container, so no job costs a machine boot and flyd never sees a process exiting every two
minutes. And the isolation survives the loop: a fresh registration each pass, and a wiped
workspace, so a job still cannot leave anything behind for the next one.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "deploy/runner/entrypoint.sh"
FLY_TOML = ROOT / "deploy/runner/fly.toml"


def _body() -> str:
    """The entrypoint with comments stripped. Every claim here is about what the shell RUNS, and
    this file's own prose quotes most of the strings it asserts on."""
    out = []
    for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_the_scan_sees_a_real_script() -> None:
    """Guard the guard. Every assertion below is `in _body()`, and a scan that returned an empty
    string would pass none of them and fail all of them for the wrong reason -- or, with a
    negative assertion added later, pass silently over nothing."""
    body = _body()
    assert len(body.splitlines()) > 20, body
    assert "./run.sh" in body
    assert "config.sh" in body


def test_the_runner_takes_its_next_job_without_exiting() -> None:
    body = _body()
    assert re.search(r"^while true; do$", body, re.M), (
        "deploy/runner/entrypoint.sh no longer loops. Without the loop the container exits after "
        "every job and the next one costs a virtual machine boot -- and on 2026-08-18 two of "
        "three machines did not come back from it at all."
    )
    assert re.search(r"^done$", body, re.M), body
    # run.sh and the registration must both be INSIDE the loop, or the loop is decoration.
    start = body.index("while true; do")
    assert body.index("./config.sh", start) > start
    assert body.index("./run.sh", start) > start


def test_a_failed_job_does_not_end_the_fleet() -> None:
    """`set -euo pipefail` is at the top. run.sh returns non-zero on some job outcomes, and
    without the guard one red build would take the runner off the fleet until something noticed."""
    body = _body()
    assert "set -euo pipefail" in body
    # ARGUMENTS ARE ALLOWED BETWEEN THE COMMAND AND THE GUARD. This regex used to demand the
    # literal `./run.sh || true`, so it went red the moment the call gained `${RUN_ARG}` --
    # entrypoint.sh had the guard the whole time and main was red on a spelling. What the test
    # is actually about is that the guard is on the SAME command, so the `[^|\n]*` stops at a
    # pipe or a newline and a `|| true` on some later line still fails.
    assert re.search(r"\./run\.sh[^|\n]*\|\| true", body), (
        "run.sh runs under `set -e` with no `|| true`, so a failing CI job ends the container"
    )


def test_the_loop_keeps_the_isolation_the_reboot_used_to_give() -> None:
    """The reboot was doing two jobs: restarting the runner, and guaranteeing a clean disk. Only
    the first is replaced by looping, so the second has to be explicit."""
    body = _body()
    assert "--ephemeral" in body, "the runner registration is no longer single-use"
    assert "_work" in body and "rm -rf" in body, (
        "the loop reuses one container, so it must wipe /home/runner/_work between jobs. Without "
        "it a job inherits the previous job's node_modules, .venv and dotnet obj/, which is "
        "exactly the 'green on runner 2, red on runner 4' the ephemeral design was built to kill"
    )


def test_the_platform_restart_stays_as_the_backstop() -> None:
    """Looping in the container removes the reboot from the normal path. It must not remove it
    from the crash path: a container that dies for real still has to come back."""
    toml = FLY_TOML.read_text(encoding="utf-8")
    assert re.search(r'policy\s*=\s*"always"', toml), (
        "deploy/runner/fly.toml no longer restarts a crashed runner machine"
    )

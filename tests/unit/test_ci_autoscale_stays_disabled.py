"""The autoscale verb must stay disabled until it stops killing builds.

WHY THIS EXISTS. 2026-08-19: `deploy/runners.sh autoscale` stopped Fly machines that were
running jobs. The CI runs for PRs #383 #387 #390 #391 #407 #414 #424 #427 #431 died, and every
one of them reported as a failing test rather than as a killed runner, because a machine that
disappears mid-job uploads no log. Nine sessions re-diagnosed the same phantom bug.

Founder directive the same day: autoscaling stays off until spun-up machines are proven
reliable, "and ensure it cant be reenabled by accident". A comment is not a mechanism. This is.

The two defects the refusal names are asserted here as well, so that deleting the refusal
without fixing them still fails: the test for defect 1 fails the moment `busy_names` stops
being read with a fail-open `|| true` AND the refusal is gone, which is exactly the state in
which re-enabling would be safe.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RUNNERS = Path(__file__).resolve().parents[2] / "deploy" / "runners.sh"


@pytest.fixture(scope="module")
def source() -> str:
    return RUNNERS.read_text()


@pytest.fixture(scope="module")
def autoscale_body(source: str) -> str:
    """Everything from `cmd_autoscale() {` to the start of the next top-level function."""
    start = source.index("cmd_autoscale() {")
    rest = source[start + len("cmd_autoscale() {") :]
    end = re.search(r"^\}", rest, re.M)
    assert end, "cmd_autoscale has no closing brace"
    return rest[: end.start()]


@pytest.fixture(scope="module")
def autoscale_code(autoscale_body: str) -> str:
    """The body with comments and heredoc text stripped, so only shell that RUNS is left.

    The refusal deliberately names `fly machine start` as the safe alternative, in prose. A test
    that searches the raw body finds that mention and reads it as a live call. Ordering claims
    have to be made about executable lines only.
    """
    out, in_heredoc = [], False
    for line in autoscale_body.splitlines():
        if in_heredoc:
            if line.strip() == "REFUSED":
                in_heredoc = False
            continue
        if "<<'REFUSED'" in line:
            in_heredoc = True
            continue
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_the_script_is_valid_shell() -> None:
    assert subprocess.run(["bash", "-n", str(RUNNERS)]).returncode == 0


def test_autoscale_refuses_before_it_runs_anything(autoscale_code: str) -> None:
    """The refusal must come first, so no Fly call and no gh call can happen before it."""
    ret = autoscale_code.index("return 1")
    for call in ("fly machine stop", "fly machine start", "fly machines list", "gh api"):
        if call in autoscale_code:
            assert autoscale_code.index(call) > ret, (
                f"`{call}` can run before the disable refuses. The refusal must be the first "
                "thing cmd_autoscale does."
            )


def test_autoscale_returns_non_zero(autoscale_code: str) -> None:
    assert "return 1" in autoscale_code, (
        "The autoscale verb must exit non-zero so a caller that ignores stderr still fails."
    )


def test_the_refusal_says_why_and_what_to_do_instead(autoscale_body: str) -> None:
    lowered = autoscale_body.lower()
    assert "disabled" in lowered
    assert "mid-build" in lowered or "mid-job" in lowered
    assert "runners.sh up" in autoscale_body, (
        "A refusal that does not say how to add capacity gets routed around."
    )


def test_the_busy_read_still_fails_open_so_re_enabling_is_still_unsafe(
    autoscale_body: str,
) -> None:
    """Defect 1, pinned.

    `busy_names` is the ONLY thing standing between the scale-down loop and a machine that is
    mid-job. It is read with `|| true`, so a failed read yields an empty list and every machine
    reads as idle. Reading the runner list needs the `administration` permission, which
    GITHUB_TOKEN cannot be granted, so the read fails routinely rather than rarely.

    While this assertion holds, re-enabling is unsafe. When someone fixes the read, this test
    fails and tells them the disable may now be lifted -- deliberately, not by accident.
    """
    m = re.search(r"busy_names=\"\$\((.*?)\)\"", autoscale_body, re.S)
    assert m, "busy_names is no longer read the way this test understands"
    assert "|| true" in m.group(1), (
        "The busy-runner read no longer fails open. Defect 1 may be fixed. Re-read "
        "tests/unit/test_ci_autoscale_stays_disabled.py and the block at the top of "
        "cmd_autoscale before lifting the disable."
    )


def test_the_ceiling_is_still_below_the_fleet(autoscale_body: str) -> None:
    """Defect 2, pinned: autoscale_max falls back to 3 against a 12-machine fleet."""
    m = re.search(r"_cfg_num autoscale_max (\d+)", autoscale_body)
    assert m, "autoscale_max is no longer read the way this test understands"
    assert int(m.group(1)) < 12, (
        "The autoscale_max fallback now covers the fleet. Defect 2 may be fixed."
    )

"""A macOS CI runner must never be defined in this repo again.

THE FAILURE, 2026-08-19. The DNS drift drill went red on a pull request. Nothing was wrong with
the drill. The job had landed on `mumchimp-mac-4`, where `actions/setup-python@v5` died with
`mkdir: /Users/runner: Permission denied` -- that action writes to the hosted-runner tool cache
path, which does not exist on somebody's laptop.

THE ROOT CAUSE, WHICH IS BIGGER THAN ONE WORKFLOW. Every workflow says
`runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}`, and `CI_RUNS_ON` was `self-hosted`. The mac
runner carried `self-hosted, macOS, X64, light`; the Fly runners carry
`self-hosted, X64, heavy, Linux, container, fly`. Both satisfy `self-hosted`. So EVERY
Linux-assuming job in this repo was a coin flip, and losing it looked like a broken test rather
than a misrouted job. That is why this kept coming back looking like a different bug each time.

WHAT WAS DONE, 2026-08-19, in three layers so no single one has to hold:

1. All four mac runners were removed from the repo registration (`gh api -X DELETE
   repos/.../actions/runners/<id>`), which revokes their credentials. `svc.sh start` can no
   longer bring one back; only a human re-running `config.sh` with a token can.
2. `CI_RUNS_ON`, `CI_LIGHT_RUNS_ON` and `CI_HEAVY_RUNS_ON` were all set to `fly`, a label only
   the Fly Linux fleet carries. Even a re-registered mac cannot take a job.
3. Their launchd agents and their `~/actions-runner*` install directories were parked.

THIS TEST IS THE FOURTH LAYER, and it guards the one thing the other three do not: deleting a
runner does not stop a plist being committed again, and a committed plist is how one gets
installed. So the DEFINITIONS are what this pins.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".git", "node_modules", ".venv", "store", "storage", "graphify-out", ".next"}


def _tracked_paths(pattern: str) -> list[str]:
    return sorted(
        str(p.relative_to(ROOT))
        for p in ROOT.rglob(pattern)
        if not SKIP.intersection(p.relative_to(ROOT).parts)
    )


def test_no_actions_runner_job_is_defined_in_this_repo() -> None:
    offenders = _tracked_paths("actions.runner.*")
    assert offenders == [], (
        "A GitHub Actions runner job definition is in this repo: "
        + ", ".join(offenders)
        + ". CI runs on the Fly Linux fleet (deploy/runner/). A self-hosted mac runner shares "
        "the `self-hosted` label with it, so it silently competes for every job and fails any "
        "that assumes Linux. See this file's docstring for the 2026-08-19 incident."
    )


def test_the_runner_definition_this_repo_does_keep_is_the_linux_one() -> None:
    """The guard above must not pass by there being no runner definition at all.

    A test that asserts an empty list passes just as well when the whole feature has been
    deleted. This pins the thing that SHOULD exist, so the pair can only both pass in the
    state we actually want.
    """
    dockerfile = ROOT / "deploy" / "runner" / "Dockerfile"
    assert dockerfile.is_file(), (
        "deploy/runner/Dockerfile is the CI runner definition and it is missing"
    )
    assert "FROM" in dockerfile.read_text(), "deploy/runner/Dockerfile defines no image"

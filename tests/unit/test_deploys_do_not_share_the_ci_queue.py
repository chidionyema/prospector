"""A deploy must not queue behind our own CI.

On 2026-08-19 a merge to main sat undeployed for twelve hours. Nothing failed. The deploy run
was QUEUED, because every deploy job asked for the same `heavy` self-hosted label as every
feature-branch CI job, and the fleet is three machines. The site kept serving the old build
while every ops screen read green.

The fix was to send deploy jobs to a separate queue. This test is what stops someone putting
them back, which is easy to do by copying a `runs-on:` line from ci.yml.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# The workflows that ship code to production. Named rather than globbed, so deleting one is a
# failure here instead of a test that silently checks nothing.
DEPLOY_WORKFLOWS = ("deploy-web.yml", "deploy-api.yml", "deploy-engine.yml")

# The labels the shared self-hosted fleet answers to. A deploy job asking for any of these is
# back in the queue this test exists to keep it out of.
SHARED_FLEET_VARS = ("CI_RUNS_ON", "CI_HEAVY_RUNS_ON", "CI_LIGHT_RUNS_ON")

RUNS_ON = re.compile(r"^\s*runs-on:\s*(.+)$", re.MULTILINE)


@pytest.mark.parametrize("name", DEPLOY_WORKFLOWS)
def test_deploy_jobs_do_not_ask_for_the_shared_fleet(name: str) -> None:
    path = WORKFLOWS / name
    assert path.exists(), f"{name} is declared here but not on disk"
    lines = RUNS_ON.findall(path.read_text())
    assert lines, f"{name} declares no jobs — the check would pass by looking at nothing"
    for value in lines:
        for var in SHARED_FLEET_VARS:
            assert var not in value, (
                f"{name} runs a deploy job on {var}. That is the CI fleet's queue: a deploy "
                f"then waits behind every feature branch, which is how a merge stayed "
                f"undeployed for twelve hours on 2026-08-19. Use CI_DEPLOY_RUNS_ON."
            )


@pytest.mark.parametrize("name", DEPLOY_WORKFLOWS)
def test_deploy_jobs_still_have_a_runner_if_the_variable_is_unset(name: str) -> None:
    """An unset variable must fall back to a real runner, not to an empty `runs-on`."""
    for value in RUNS_ON.findall((WORKFLOWS / name).read_text()):
        assert "ubuntu-latest" in value, (
            f"{name} has a runs-on with no hosted fallback ({value.strip()}). With "
            f"CI_DEPLOY_RUNS_ON unset the job would never be schedulable."
        )

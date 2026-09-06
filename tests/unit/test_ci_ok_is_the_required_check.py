"""ci-ok is the one required check, so it has to actually aggregate every lane.

Ruleset `strict` (id 20109556) is active on ~DEFAULT_BRANCH with `bypass_actors: []` and requires
guard, python, dotnet, nextjs and ci-ok. That is the platform half, and it is not in this
repository -- read it with `gh api repos/chidionyema/prospector/rulesets/20109556`.

The half a commit CAN break is here: ci-ok is a job in ci.yml, and a required check that does not
depend on a lane is green while that lane is red. That is the same failure the deleted
main-admission-guard.yml existed to catch after the fact, and it is cheaper to refuse it before
the merge than to revert main afterwards.

Written 2026-08-21, when `ci-ok` was added to the ruleset's required contexts and the two revert
robots were deleted. Before that the repository was private, both branch-protection endpoints
answered 403, and nothing refused a merge over a red check -- six PRs went in that way on
2026-08-19 and main was red for over an hour.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

# The contexts named by ruleset `strict`, minus ci-ok itself. Every one of these is a job in
# ci.yml, and ci-ok has to wait for all of them.
REQUIRED_LANES = ("guard", "python", "dotnet", "nextjs")


@pytest.fixture(scope="module")
def jobs() -> dict:
    assert CI.exists(), f"{CI} is gone"
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def test_ci_ok_exists(jobs: dict):
    """If the aggregator is renamed, the ruleset asks for a context nothing ever reports.

    A required check that no job produces does not fail the merge -- it leaves the PR pending
    forever, which reads as a stuck queue rather than as a broken gate.
    """
    assert "ci-ok" in jobs, (
        "ci.yml defines no `ci-ok` job, but ruleset 20109556 requires that context. Either "
        "restore the job or take the context out of the ruleset, in the same change."
    )


@pytest.mark.parametrize("lane", REQUIRED_LANES)
def test_ci_ok_waits_for_every_required_lane(jobs: dict, lane: str):
    """The aggregation is the whole of ci-ok's value; without it the gate passes over a red lane."""
    assert lane in jobs, f"ci.yml has no `{lane}` job, but the ruleset requires that context"
    needs = jobs["ci-ok"].get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    assert lane in needs, (
        f"ci-ok does not `needs: {lane}`, so ci-ok can report green while {lane} is red and the "
        f"merge is allowed. Add it to ci-ok's needs list."
    )


def test_ci_ok_runs_even_when_a_lane_it_needs_was_skipped(jobs: dict):
    """`needs` alone makes ci-ok skip when any lane skips, and a skipped required check never
    resolves. ci.yml skips lanes on purpose -- a docs-only PR runs neither dotnet nor nextjs --
    so ci-ok must run regardless and read the results itself."""
    cond = str(jobs["ci-ok"].get("if", ""))
    assert "always()" in cond, (
        "ci-ok has no `if: always()`, so it is skipped whenever any lane it needs is skipped. "
        f"A skipped required check leaves the pull request pending forever. Found: {cond!r}"
    )


def test_ci_ok_fails_when_a_lane_it_needs_failed(jobs: dict):
    """`if: always()` without a result check is worse than no gate: it is always green."""
    body = yaml.dump(jobs["ci-ok"])
    assert "needs." in body and "result" in body, (
        "ci-ok runs with `if: always()` but never reads `needs.<lane>.result`, so it reports "
        "success no matter what the lanes did. That is a required check that requires nothing."
    )

"""A red main must announce itself, and the announcer must be able to fire.

TWICE ON 2026-08-19 a red main went unannounced and every open pull request inherited it. The
second time, `npm audit --audit-level=high` reached main in #393 on a run whose five heavy jobs
were all CANCELLED, so nothing graded it; main was then red for three hours while agents
re-diagnosed the same failure on their own branches.

`.github/workflows/main-red.yml` is the guard. These tests grade the guard itself, because the
way a `workflow_run` announcer fails is by never running at all: the `workflows:` list matches on
the other workflow's `name:` field, NOT its filename, so one rename makes the announcer silent
and nothing goes red to say so. That is the class in
``a-workflow-that-can-never-run-fails-as-noise``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
ANNOUNCER = WORKFLOWS / "main-red.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # PyYAML parses the bare key `on` as the boolean True. Both spellings are the same trigger
    # block, and a test that reads only one of them silently grades nothing.
    return doc.get("on", doc.get(True)) or {}


def _declared_names() -> set[str]:
    return {_load(p).get("name") for p in WORKFLOWS.glob("*.yml") if _load(p).get("name")}


def test_the_announcer_exists():
    assert ANNOUNCER.exists(), f"{ANNOUNCER} is missing — a red main has nothing to announce it"


def test_it_watches_a_workflow_that_actually_exists():
    """`workflows:` matches on the WATCHED workflow's `name:`, not on its filename."""
    watched = _triggers(_load(ANNOUNCER))["workflow_run"]["workflows"]
    assert watched, "the workflow_run trigger names no workflow, so it can never fire"
    declared = _declared_names()
    assert declared, "no workflow in .github/workflows declares a name — this test stopped grading"
    missing = [w for w in watched if w not in declared]
    assert not missing, (
        f"main-red.yml watches {missing}, and no workflow declares that name. "
        f"Declared names: {sorted(declared)}"
    )


def test_a_name_that_matches_nothing_is_caught():
    """The mutation proof: the check above must FAIL when the watched name is wrong."""
    watched = ["CI that nobody named"]
    assert [w for w in watched if w not in _declared_names()] == watched


def test_it_only_watches_main():
    branches = _triggers(_load(ANNOUNCER))["workflow_run"].get("branches")
    assert branches == ["main"], (
        f"branches={branches!r} — an announcer that fires on every branch turns one red PR "
        "into an issue, which is the alert fatigue this exists to avoid"
    )


def test_it_runs_where_a_broken_fleet_cannot_silence_it():
    """It must not queue on the self-hosted runners it may be reporting the death of."""
    runs_on = _load(ANNOUNCER)["jobs"]["announce"]["runs-on"]
    assert runs_on == "ubuntu-latest", (
        f"runs-on={runs_on!r} — if this waits on `vars.CI_RUNS_ON` then the one failure it can "
        "never report is the fleet being down, which is the failure most worth reporting"
    )


def test_it_both_opens_and_closes():
    script = _load(ANNOUNCER)["jobs"]["announce"]["steps"][0]["run"]
    assert "gh issue create" in script, "nothing opens the issue"
    assert "gh issue close" in script, (
        "nothing closes the issue, so it becomes a permanent red flag nobody trusts"
    )


def test_a_cancelled_run_is_neither_red_nor_green():
    """A cancelled run graded nothing. Closing on it clears a real alarm; opening invents one."""
    script = _load(ANNOUNCER)["jobs"]["announce"]["steps"][0]["run"]
    assert '"$conclusion" != "failure"' in script and '"$conclusion" != "timed_out"' in script, (
        "the script does not restrict the red path to failure/timed_out, so a cancelled run "
        "would be announced as a failure"
    )

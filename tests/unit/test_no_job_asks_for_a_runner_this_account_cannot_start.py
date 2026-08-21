"""No workflow job asks for a GitHub-hosted runner this account cannot start.

WHY THIS EXISTS. `INC-2026-08-20-a-job-that-cannot-start-turned-main-red-hourly` closed the same
class one file at a time. Actions billing on this account refuses every GitHub-hosted job before
its first step -- the check-run annotation reads "The job was not started because recent account
payments have failed or your spending limit needs to be increased" -- so `ci-fleet-keeper.yml` and
`ci-fleet-watch.yml` were each gated on `vars.HOSTED_RUNNERS_AVAILABLE` and each pinned by its own
test. Two tests, two files, and nothing watching the other fifteen.

`merge-when-green.yml` then landed on 2026-08-21 with a bare `runs-on: ubuntu-latest` and no gate.
It failed in three seconds with zero steps on every run it ever had, every ten minutes, and never
merged a pull request. Four were open and CLEAN while it ticked. No test failed, because no test
graded the class.

THE RULE. A job may name a GitHub-hosted runner only when it also carries
`if: vars.HOSTED_RUNNERS_AVAILABLE ...`, which is the switch the founder owns and the one the
incident already chose. Everything else resolves its runner through `vars.CI_*_RUNS_ON`, which is
set to `fly` on the repository and lands on the self-hosted fleet.

A runner expression this file cannot classify FAILS. Passing an unknown value would put the miss
case back exactly where it was.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))

# The label families GitHub bills for. `self-hosted` and this estate's `fly` are free and are not
# refused by billing.
_HOSTED = re.compile(r"^(ubuntu|windows|macos)-", re.IGNORECASE)
_SWITCH = "vars.HOSTED_RUNNERS_AVAILABLE"


def _jobs(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for name, job in (doc.get("jobs") or {}).items():
        if isinstance(job, dict):
            yield name, job


def _labels(runs_on) -> list[str]:
    if isinstance(runs_on, str):
        return [runs_on]
    if isinstance(runs_on, list):
        return [x for x in runs_on if isinstance(x, str)]
    if isinstance(runs_on, dict):          # runs-on: {group: ..., labels: [...]}
        got = runs_on.get("labels") or runs_on.get("group") or ""
        return _labels(got)
    return []


def _asks_for_hosted(runs_on) -> bool:
    """True when this job lands on a GitHub-billed runner no matter what the repo vars say."""
    labels = _labels(runs_on)
    assert labels, f"runs-on {runs_on!r} could not be read as a label"
    for label in labels:
        if "${{" in label:
            # An expression is only safe when it can resolve to a repository variable. A bare
            # `${{ github.something }}` naming a hosted image is not.
            if "vars." in label:
                continue
            pytest.fail(f"runs-on expression names no repository variable: {label!r}")
        if _HOSTED.match(label.strip()):
            return True
    return False


def test_this_file_grades_something():
    assert len(WORKFLOWS) >= 10, f"only {len(WORKFLOWS)} workflows found; the glob is wrong"
    hosted = [
        f"{p.name}:{n}"
        for p in WORKFLOWS
        for n, j in _jobs(p)
        if "runs-on" in j and _asks_for_hosted(j["runs-on"])
    ]
    assert hosted, (
        "no job in the tree asks for a hosted runner, so the assertion below grades nothing. "
        "If that is genuinely true now, delete this file rather than leave it passing vacuously."
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_a_hosted_runner_is_gated_on_the_switch_the_founder_owns(path: Path):
    for name, job in _jobs(path):
        if "runs-on" not in job or not _asks_for_hosted(job["runs-on"]):
            continue
        gate = str(job.get("if") or "")
        assert _SWITCH in gate, (
            f"{path.name} job `{name}` asks for {job['runs-on']!r}, which Actions billing on this "
            f"account refuses before its first step, and carries no `if: {_SWITCH} ...` gate. "
            f"Without the gate the job does not skip, it FAILS, and it fails on every trigger for "
            f"as long as billing is unsettled. Either route it through vars.CI_RUNS_ON like the "
            f"rest of the tree, or gate it. Its `if` is currently {gate!r}."
        )

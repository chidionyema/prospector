"""The fleet probe notices a fleet running an image older than the repository.

THE FAILURE. On 2026-08-19 the hermes-config gate failed at exit 127 in 17ms with no output:
the runner image had no openssh-client and the step redirected stderr to /dev/null, so the
shell's own "command not found" went with it. openssh-client was added to
`deploy/runner/Dockerfile` that hour. The FLEET kept running the old image, and nothing
anywhere said so — Fly showed 18 healthy machines, GitHub showed runners online, and both were
telling the truth. The image was simply not the one the repository describes.

The class is **a deployed artifact that no screen compares against its source**. It is closed
by stamping the image with the commit it was built from (`deploy/runners.sh`) and grading that
stamp here. These tests pin both halves, because a stamp nobody reads and a check for a stamp
nobody writes both pass on their own.

WHAT IS NO LONGER GRADED HERE. `ci-fleet-watch.yml` was deleted on 2026-08-22. It ran the probe
on a schedule from a hosted runner and was gated on `vars.HOSTED_RUNNERS_AVAILABLE`, a switch
that existed because Actions billing refused every hosted job on this account. The repository is
public now and hosted jobs start, so the gate and the workflow both went. The probe survives as
`scripts/ci_fleet_probe.py`, wired to the ops console, and the tests below still grade it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "scripts" / "ci_fleet_probe.py"
RUNNERS_SH = REPO_ROOT / "deploy" / "runners.sh"

EXPECTED = "a" * 40
OTHER = "b" * 40


def _load():
    spec = importlib.util.spec_from_file_location("ci_fleet_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["ci_fleet_probe"] = module
    spec.loader.exec_module(module)
    return module


def _machine(sha: str | None) -> dict:
    env = {"GITHUB_REPO": "chidionyema/prospector"}
    if sha is not None:
        env["RUNNER_IMAGE_SHA"] = sha
    return {"id": "abc", "state": "started", "config": {"env": env}}


def test_a_fleet_on_the_current_image_is_not_a_problem():
    mod = _load()
    machines = [_machine(EXPECTED) for _ in range(18)]
    assert mod.image_staleness(machines, EXPECTED) is None


def test_a_fleet_on_an_older_image_is_reported_with_the_command_that_fixes_it():
    mod = _load()
    problem = mod.image_staleness([_machine(OTHER)], EXPECTED)
    assert problem is not None
    assert OTHER[:12] in problem
    assert EXPECTED[:12] in problem
    assert "deploy/runners.sh up" in problem


def test_an_unstamped_machine_counts_as_stale():
    """The condition this exists to catch, so it must not be skipped as unknown.

    A machine with no stamp was built before `runners.sh` learned to write one, which makes it
    at least that old. Treating an unknown as acceptable is how a staleness check quietly stops
    checking.
    """
    mod = _load()
    problem = mod.image_staleness([_machine(None)], EXPECTED)
    assert problem is not None
    assert "unstamped" in problem


def test_a_mixed_fleet_names_both_populations():
    mod = _load()
    problem = mod.image_staleness([_machine(EXPECTED), _machine(OTHER), _machine(None)], EXPECTED)
    assert problem is not None
    assert OTHER[:12] in problem
    assert "unstamped" in problem


def test_no_expectation_compares_nothing_and_says_so_one_level_up():
    """`git log` can fail — a shallow clone, no origin/main, git not on PATH.

    image_staleness() itself stays quiet: with nothing to compare against it has no finding to
    report, and inventing one here would mean every caller had to special-case it. The alarm
    belongs to the CALLER, and grade() raises it — see the test below. That split matters
    because `actions/checkout` is shallow by default, so a scheduled run with no history would
    otherwise have graded nothing and gone green.
    """
    mod = _load()
    assert mod.image_staleness([_machine(None)], None) is None
    assert mod.image_staleness([], EXPECTED) is None


def test_the_deploy_script_actually_writes_the_stamp_the_probe_reads():
    """The two halves must name the same variable.

    Either half passes its own tests while the pair does nothing: a stamp nobody reads, or a
    check for a stamp nobody writes.
    """
    mod = _load()
    body = RUNNERS_SH.read_text()
    assert f'--env "{mod.STAMP}=' in body, (
        f"deploy/runners.sh must pass {mod.STAMP} to `fly deploy`, or the probe grades a "
        f"stamp that no deploy ever writes"
    )
    assert "log -1 --format=%H -- deploy/runner" in body, (
        "the stamp must be the commit that last touched deploy/runner/, which is what "
        "expected_image_sha() compares it against"
    )


def test_grade_reports_that_it_could_not_work_out_what_to_compare_against():
    """The branch the shallow-checkout case lands in, exercised without a fly or a network.

    Before this, `expected is None` and "every machine current" were the same green. In CI that
    is the difference between a check and a decoration.
    """
    mod = _load()
    mod._json_out = lambda cmd: ([_machine(EXPECTED)], "") if "machine" in cmd else ([], "")
    mod.expected_image_sha = lambda: None
    out = mod.grade(
        {"app": "prospector-ci", "repo": "chidionyema/prospector", "config": "x"},
        fly="/usr/bin/true",
        gh=None,
        image_only=True,
    )
    assert any("cannot tell whether the fleet is current" in p for p in out["problems"]), out

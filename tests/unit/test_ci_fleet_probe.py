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


# ── The check must actually be ASKED, and asked somewhere that can answer ──────────────────
#
# A probe wired to nothing is the defect this whole exercise exists to close: the stale image
# was findable on 2026-08-19 by anyone who thought to look, and nobody thought to look. These
# pin the schedule the same way the test above pins the stamp.

WATCH = REPO_ROOT / ".github" / "workflows" / "ci-fleet-watch.yml"


def _watch() -> dict:
    import yaml

    assert WATCH.exists(), (
        f"{WATCH.name} is gone. The fleet probe then grades nothing on its own: it becomes a "
        f"console button somebody has to think to press, which is how the fleet ran a day-old "
        f"image while every screen read healthy."
    )
    doc = yaml.safe_load(WATCH.read_text())
    # `on:` is the YAML boolean True. Accept either spelling rather than depending on the loader.
    doc["on"] = doc.get("on", doc.get(True))
    return doc


def test_a_schedule_actually_asks_the_question():
    doc = _watch()
    assert "schedule" in (doc["on"] or {}), (
        "ci-fleet-watch must run on a schedule. On workflow_dispatch alone it is a button, and "
        "the fault it catches is one nobody knows to look for."
    )
    scripts = "\n".join(
        step.get("run", "") for job in doc["jobs"].values() for step in job.get("steps", [])
    )
    assert "ci_fleet_probe.py --image-only" in scripts, (
        "the workflow must invoke `scripts/ci_fleet_probe.py --image-only`. Without --image-only "
        "it asks for the repository's runner list, which needs the `administration` permission "
        "GITHUB_TOKEN cannot hold — so it would be red every morning for a credential reason, "
        "and a check that cries wolf daily is a check nobody reads."
    )


def test_the_watch_does_not_run_on_the_fleet_it_grades():
    """The states worth catching are the ones where the fleet cannot run a job."""
    for job_id, job in _watch()["jobs"].items():
        runs_on = str(job.get("runs-on", ""))
        assert "self-hosted" not in runs_on and "CI_RUNS_ON" not in runs_on, (
            f"job `{job_id}` runs on the fleet it is grading ({runs_on!r}). A dead or "
            f"mis-imaged fleet cannot report that it is dead or mis-imaged. Hardcode a hosted "
            f"runner here even though every other workflow in this repo uses vars.CI_RUNS_ON."
        )


def test_the_watch_checks_out_enough_history_to_have_an_expectation():
    """A shallow checkout has no origin/main, and then there is nothing to compare against.

    grade() now reports that rather than passing, so this would go RED rather than silently
    green — but red-for-the-wrong-reason every morning is its own way of killing a check.
    """
    steps = [s for job in _watch()["jobs"].values() for s in job.get("steps", [])]
    checkout = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout, "no checkout step — expected_image_sha() reads this repository's git log"
    assert any(str((s.get("with") or {}).get("fetch-depth")) == "0" for s in checkout), (
        "actions/checkout must set fetch-depth: 0. The default is a shallow single-ref clone "
        "with no origin/main, so `git log origin/main -- deploy/runner` resolves nothing."
    )
    assert any("fetch" in s.get("run", "") and "origin" in s.get("run", "") for s in steps), (
        "fetch origin main explicitly: fetch-depth 0 deepens the checked-out ref, it does not "
        "guarantee a refs/remotes/origin/main to compare against"
    )

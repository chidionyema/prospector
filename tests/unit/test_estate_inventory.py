"""The inventory's own gates.

Every test here is about the JOIN, never about a provider. Discovery shells out to CLIs that
need a live account, so a test that mocks `fly` proves only that the mock was called. What can
be proved offline, and is the part that actually protects the estate, is this: given a resource
that exists, does the tool refuse to call it fine when the repo does not describe it?

The central one is `test_a_resource_of_any_class_with_no_entry_fails`, parametrised over all ten
classes. It is the check the migration spec asks for by name: add a resource of any kind with no
describing file and the run goes red.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.estate_inventory import (
    CLASSES,
    DEFAULT_DECLARATION,
    Found,
    reconcile,
    stale_entries,
    verdict,
)

# A committed-path set standing in for `git ls-tree`. The join only ever asks "is this path on
# the ref", so a set is the whole of what it needs.
COMMITTED = {"deploy/engine/fly.toml", "deploy/secrets.required", "ops/launchd/com.a.json"}


def _cfg(**kw):
    base = {"resources": {}, "admitted_gaps": {}, "admitted_blind_classes": {}}
    base.update(kw)
    return base


# ───────────────────────────── the gate the spec asks for ─────────────────────────────


@pytest.mark.parametrize("cls", CLASSES)
def test_a_resource_of_any_class_with_no_entry_fails(cls):
    """Add anything, anywhere, that the declaration does not mention: the run must go red.

    Parametrised over CLASSES rather than a hand-picked few, so a class added later cannot be
    added without a gate. If someone appends an eleventh class to CLASSES and the discoverer
    finds something undescribed, this test starts failing on that class the same day.
    """
    rows = reconcile([Found(cls, "something-new", "somewhere")], _cfg(), COMMITTED)
    assert rows[0].problem, f"{cls}: an undeclared resource was accepted"
    assert verdict(rows, {}, _cfg()) != 0


def test_a_described_and_restorable_resource_passes():
    """The negative case. Without this, a gate that fails everything would pass the test above."""
    cfg = _cfg(resources={
        "compute:app": {"described_by": "deploy/engine/fly.toml", "restore": "bash deploy/cutover.sh"}
    })
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, COMMITTED)
    assert rows[0].problem is None, rows[0].problem
    assert verdict(rows, {}, cfg) == 0


# ───────────────────────────── a describing file must exist ─────────────────────────────


def test_a_describing_file_that_is_not_on_the_ref_is_not_a_description():
    """A file on someone's branch describes nothing. The estate reads the merged tree."""
    cfg = _cfg(resources={"compute:app": {"described_by": "deploy/not-merged.toml", "restore": "x"}})
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, COMMITTED)
    assert "not on" in rows[0].problem


def test_an_unreadable_ref_fails_rather_than_passing_everything():
    """`committed=None` means the lookup itself failed. Treating that as "no paths confirmed"
    would pass nothing; treating it as "no paths to check" would pass everything. It must be
    the first, because a tool that cannot look must never report clean."""
    cfg = _cfg(resources={"compute:app": {"described_by": "deploy/engine/fly.toml", "restore": "x"}})
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, None)
    assert rows[0].problem and verdict(rows, {}, cfg) != 0


def test_an_entry_with_no_describing_file_is_undescribed():
    cfg = _cfg(resources={"compute:app": {"restore": "bash deploy/cutover.sh"}})
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, COMMITTED)
    assert "names no describing file" in rows[0].problem


# ───────────────────────────── family entries stay per-resource ─────────────────────────────


def test_a_family_entry_still_requires_each_member_to_have_its_own_file():
    """The reason a glob is allowed at all. `ops/launchd/*` covers sixteen jobs in one entry,
    and a seventeenth job with no JSON beside it is still caught."""
    cfg = _cfg(resources={
        "scheduled_job:launchd/*": {"described_by_template": "ops/launchd/{name}.json",
                                    "restore": "x"}
    })
    rows = reconcile(
        [Found("scheduled_job", "launchd/com.a", "launchd"),
         Found("scheduled_job", "launchd/com.new", "launchd")],
        cfg, COMMITTED,
    )
    by = {r.found.name: r for r in rows}
    assert by["launchd/com.a"].problem is None
    assert "not on" in by["launchd/com.new"].problem, "a new member with no file was waved through"


def test_an_exact_entry_beats_a_glob_that_also_matches():
    """Two entries can match one resource. The specific one is the one that meant it."""
    cfg = _cfg(resources={
        "secret:app/*": {"described_by": "deploy/secrets.required", "restore": "x"},
        "secret:app/ODD_ONE": {"described_by": "deploy/engine/fly.toml", "restore": "x"},
    })
    rows = reconcile([Found("secret", "app/ODD_ONE", "fly")], cfg, COMMITTED)
    assert rows[0].described_by == "deploy/engine/fly.toml"


def test_a_glob_that_matched_something_is_not_reported_as_stale():
    """A pattern never equals a discovered key, so a literal comparison called every family
    entry stale. Measured: ten false alarms on the real declaration."""
    cfg = _cfg(resources={"secret:app/*": {"described_by": "deploy/secrets.required", "restore": "x"}})
    rows = reconcile([Found("secret", "app/KEY", "fly")], cfg, COMMITTED)
    assert stale_entries(rows, cfg) == []


def test_a_declared_resource_nothing_found_is_reported():
    cfg = _cfg(resources={"compute:gone": {"described_by": "deploy/engine/fly.toml", "restore": "x"}})
    assert stale_entries([], cfg) == ["compute:gone"]


# ───────────────────────────── the two admissions differ ─────────────────────────────


def test_an_admitted_gap_does_not_fail_the_run():
    cfg = _cfg(admitted_gaps={"compute:app": {"issue": 74, "why": "undecided"}})
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, COMMITTED)
    assert rows[0].admitted and verdict(rows, {}, cfg) == 0


def test_a_restore_gap_excuses_the_restore_and_nothing_else():
    """The distinction this file exists to protect. A blanket admit would also stop grading
    whether the resource is described, which is the check that catches new drift."""
    cfg = _cfg(resources={
        "scheduled_job:launchd/*": {
            "described_by_template": "ops/launchd/{name}.json",
            "restore_gap": {"issue": 82, "why": "no installer for a fresh machine"},
        }
    })
    rows = reconcile(
        [Found("scheduled_job", "launchd/com.a", "launchd"),
         Found("scheduled_job", "launchd/com.new", "launchd")],
        cfg, COMMITTED,
    )
    by = {r.found.name: r for r in rows}
    assert by["launchd/com.a"].problem is None, "a described member should pass"
    assert by["launchd/com.new"].problem, "restore_gap must not excuse a missing describing file"
    assert verdict(rows, {}, cfg) != 0


def test_a_missing_restore_with_no_gap_fails():
    cfg = _cfg(resources={"compute:app": {"described_by": "deploy/engine/fly.toml"}})
    rows = reconcile([Found("compute", "app", "fly/deployed")], cfg, COMMITTED)
    assert rows[0].problem == "no restore command"


def test_not_applicable_needs_a_reason():
    """Otherwise `restore: not_applicable` is a way to silence any resource at all."""
    cfg = _cfg(resources={"log_sink:/x": {"described_by": "deploy/engine/fly.toml",
                                          "restore": "not_applicable"}})
    rows = reconcile([Found("log_sink", "/x", "fly")], cfg, COMMITTED)
    assert rows[0].problem and verdict(rows, {}, cfg) != 0

    cfg["resources"]["log_sink:/x"]["restore_why"] = "output, not state"
    rows = reconcile([Found("log_sink", "/x", "fly")], cfg, COMMITTED)
    assert rows[0].problem is None


# ───────────────────────────── a class nobody could look at ─────────────────────────────


def test_an_unadmitted_blind_class_fails_the_run():
    """A class that could not be probed reports zero resources, which reads exactly like a
    healthy class with nothing in it. A silent hole must cost the same as a loud one."""
    assert verdict([], {"payment_integration": "no key"}, _cfg()) != 0


def test_an_admitted_blind_class_passes():
    cfg = _cfg(admitted_blind_classes={"payment_integration": {"issue": 102, "why": "no key here"}})
    assert verdict([], {"payment_integration": "no key"}, cfg) == 0


# ───────────────────────────── the real declaration ─────────────────────────────


def test_the_shipped_declaration_parses_and_every_admission_names_an_issue():
    """An admission with no ticket is a decision to never fix it, written to look temporary."""
    cfg = yaml.safe_load(DEFAULT_DECLARATION.read_text())
    for key, gap in (cfg.get("admitted_gaps") or {}).items():
        assert gap.get("issue"), f"{key}: admitted with no issue number"
        assert gap.get("why"), f"{key}: admitted with no reason"
    for cls, gap in (cfg.get("admitted_blind_classes") or {}).items():
        assert cls in CLASSES, f"{cls}: admitted blind, but not a class this tool has"
        assert gap.get("issue") and gap.get("why"), f"{cls}: admitted blind with no ticket"
    for key, entry in (cfg.get("resources") or {}).items():
        cls = key.split(":", 1)[0]
        assert cls in CLASSES, f"{key}: names a class this tool does not have"
        if entry.get("restore") == "not_applicable":
            assert entry.get("restore_why"), f"{key}: not_applicable with no reason"


# --- the ratchet itself ----------------------------------------------------------------
#
# A gate nothing runs is a gate that does not exist. These grade the scheduled job that
# runs this tool, so deleting the job fails the suite rather than going quiet.

JOB = Path(__file__).resolve().parents[2] / "ops" / "launchd" / "com.prospector.estate-inventory.json"


def _job() -> dict:
    return json.loads(JOB.read_text())


def test_something_runs_this_tool_on_a_schedule():
    """Delete the job and this fails, which is the whole point of it being a test."""
    assert JOB.exists(), f"no scheduled job runs estate_inventory.py: {JOB} is missing"
    job = _job()
    argv = job["ProgramArguments"]
    assert any(a.endswith("scripts/estate_inventory.py") for a in argv), argv


def test_the_job_names_a_script_that_exists_in_this_repo():
    """The process-audit failure, generalised: the interpreter existed, the script did not.

    launchd_plists.broken_programs only resolves ABSOLUTE arguments, so a relative script
    path would be silently unchecked for the year it took to notice. Ship it absolute.
    """
    argv = _job()["ProgramArguments"]
    script = next(a for a in argv if a.endswith("scripts/estate_inventory.py"))
    assert script.startswith("/"), f"relative script path is not checked by anything: {script}"
    assert (Path(__file__).resolve().parents[2] / "scripts" / "estate_inventory.py").exists()


def test_the_job_writes_a_report_somewhere_a_reader_can_find_it():
    """StandardOutPath is APPENDED to by launchd, so the report needs its own file."""
    argv = _job()["ProgramArguments"]
    assert "--out" in argv, "the run leaves no machine-readable receipt"
    out = argv[argv.index("--out") + 1]
    assert out.endswith(".json"), out
    assert out != _job()["StandardOutPath"], "the report must not share the appended log file"


def test_the_job_signs_a_receipt_so_a_silent_failure_raises():
    """Nine consecutive failed com.prospector.backup runs raised nothing before this wrapper."""
    argv = _job()["ProgramArguments"]
    assert argv[1].endswith("launchd_receipt.py"), argv[:2]
    assert argv[argv.index("--label") + 1] == _job()["Label"]


def test_the_job_does_not_use_a_calendar_slot_the_machine_can_sleep_through():
    """ESTATE_QUIRKS Q2: launchd SKIPS StartCalendarInterval outright if the Mac is asleep."""
    job = _job()
    assert "StartCalendarInterval" not in job
    assert job["StartInterval"] > 0


def test_the_job_can_reach_the_command_line_tools_it_shells_out_to():
    """fly lives in /usr/local/bin, which launchd does NOT put on PATH by default.

    The subject is the PLIST, not the machine running the test. Deriving the expected directory
    from `shutil.which("fly")` made this assert on the runner's filesystem: it passes on the
    founder's Mac and fails on every clone, and it did fail CI on 2026-08-20 with "fly is not
    installed on this machine at all". That is the exact class
    tests/test_suite_is_machine_independent.py exists to stop.
    """
    path = _job()["EnvironmentVariables"]["PATH"].split(":")
    installs = ("/usr/local/bin", "/opt/homebrew/bin")
    assert any(d in path for d in installs), (
        f"none of {installs} is on the job's PATH {path}, so the job cannot find fly on an Intel "
        f"or an Apple-silicon Mac")
    fly = shutil.which("fly")
    if fly:
        assert str(Path(fly).parent) in path, (
            f"fly is installed here at {fly} and is not reachable from the job's PATH: {path}")

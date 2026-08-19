"""The incident report the console renders.

What these tests are FOR. The view exists because the rollup was terminal-only, so the thing most
worth pinning is that it still says what `scripts/incident.py` says. A console that grades
incidents by its own rules would drift from the CI gate, and then the page and the build would
disagree about the same file while both looked green.

They also pin the deep link. A link that lands on the right page and then does nothing is the
failure this estate keeps shipping, so the link value is fed to the docs view that has to serve
it, rather than asserted as a string.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from prospector.ops.docs_view import doc_view
from prospector.ops.incidents_view import TIER_MEANING, incidents_view

REPO = Path(__file__).resolve().parents[2]


def _incident_script():
    spec = importlib.util.spec_from_file_location(
        "_test_incident_script", REPO / "scripts" / "incident.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record(**over) -> dict:
    """A record that validates clean and is proven, so each test can break exactly one thing."""
    rec = {
        "id": "INC-2026-01-01-example",
        "title": "An example incident",
        "opened": "2026-01-01",
        "severity": "high",
        "state": "open",
        "first_order": {"what_broke": "the thing broke", "receipt": "run 1234"},
        "second_order": {"sweep_command": "rg -n thing", "siblings_found": 0},
        "third_order": {"tier": "test", "mechanism": "a test goes red",
                        "landed_on": "2026-01-02"},
        "grade": {"signature": "the thing breaking", "window_days": 14, "verdict": "proven"},
        "cause_chain": ["the thing broke", "CLASS: things break"],
    }
    for key, value in over.items():
        if value is None:
            rec.pop(key, None)
        else:
            rec[key] = value
    return rec


def _tree(tmp_path: Path, records: list[dict], *, malformed: str | None = None) -> Path:
    """A fake checkout: the real scripts/ (so the judgement is the real judgement), fake records."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "docs" / "incidents").mkdir(parents=True)
    (root / "scripts" / "incident.py").write_text(
        (REPO / "scripts" / "incident.py").read_text(encoding="utf-8"), encoding="utf-8")
    for rec in records:
        (root / "docs" / "incidents" / f"{rec['id']}.json").write_text(
            json.dumps(rec), encoding="utf-8")
    if malformed is not None:
        (root / "docs" / "incidents" / "INC-2026-01-09-broken.json").write_text(
            malformed, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _no_cached_script():
    """The view caches the loaded script in sys.modules; each test gets a clean one."""
    sys.modules.pop("_prospector_ops_incident_script", None)
    yield
    sys.modules.pop("_prospector_ops_incident_script", None)


# ---------------------------------------------------------------------------------------------
# Anti-vacuity. A view that returns nothing would pass every assertion below about "no bad rows".
# ---------------------------------------------------------------------------------------------

def test_the_real_repo_has_records_to_report_on():
    view = incidents_view(REPO)
    assert view["headline"]["total"] >= 5, view["headline"]
    assert len(view["incidents"]) == view["headline"]["total"]


def test_every_row_carries_the_fields_the_page_renders():
    """The page indexes these directly. A missing key renders as blank, not as an error."""
    for row in incidents_view(REPO)["incidents"]:
        for field in ("id", "state", "verdict", "blocking", "next", "ok", "doc",
                      "needs_ticket", "tier_means"):
            assert field in row, f"{row.get('id')} has no {field}"
        assert isinstance(row["blocking"], list)
        assert row["next"].strip(), row["id"]


# ---------------------------------------------------------------------------------------------
# The console must not invent judgement.
# ---------------------------------------------------------------------------------------------

def test_the_view_reports_exactly_what_the_gate_reports():
    """Same records, same verdicts. This is the whole reason the view imports the script."""
    incident = _incident_script()
    theirs = incident.rollup(incident.load())
    mine = incidents_view(REPO)

    assert mine["headline"]["total"] == theirs["headline"]["total"]
    assert mine["headline"]["open"] == theirs["headline"]["open"]
    assert mine["headline"]["unguarded"] == theirs["headline"]["unguarded"]
    assert mine["headline"]["overdue_grades"] == theirs["headline"]["overdue_grades"]

    by_id = {r["id"]: r for r in mine["incidents"]}
    for row in theirs["incidents"]:
        assert by_id[row["id"]]["blocking"] == row["blocking"]
        assert by_id[row["id"]]["overdue"] == row["overdue"]
        assert by_id[row["id"]]["verdict"] == row["verdict"]


# ---------------------------------------------------------------------------------------------
# Each state a record can be in, and what the page tells the operator to do about it.
# ---------------------------------------------------------------------------------------------

def test_a_record_with_no_mechanism_is_the_worst_kind_and_says_so(tmp_path):
    root = _tree(tmp_path, [_record(third_order={"tier": "test", "mechanism": "planned"})])
    row = incidents_view(root)["incidents"][0]
    assert row["ok"] is False
    assert "No mechanism has landed" in row["next"]
    assert incidents_view(root)["headline"]["unguarded"] == 1


def test_an_incomplete_record_names_what_is_missing(tmp_path):
    root = _tree(tmp_path, [_record(second_order={"sweep_command": "rg -n thing"})])
    view = incidents_view(root)
    row = view["incidents"][0]
    assert "siblings_found" in " ".join(row["blocking"])
    assert "siblings_found" in row["next"]
    assert view["headline"]["blocked"] == 1


def test_an_overdue_grade_is_reported_with_its_deadline(tmp_path):
    landed = (_dt.date.today() - _dt.timedelta(days=40)).isoformat()
    root = _tree(tmp_path, [_record(
        third_order={"tier": "test", "mechanism": "a test", "landed_on": landed},
        grade={"signature": "sig", "window_days": 14, "verdict": "unproven"})])
    view = incidents_view(root)
    row = view["incidents"][0]
    assert row["overdue"], row
    assert row["next"].startswith("Grade it:")
    assert view["headline"]["overdue_grades"] == 1


def test_a_record_inside_its_window_is_not_chased(tmp_path):
    landed = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    root = _tree(tmp_path, [_record(
        third_order={"tier": "test", "mechanism": "a test", "landed_on": landed},
        grade={"signature": "sig", "window_days": 14, "verdict": "unproven"})])
    row = incidents_view(root)["incidents"][0]
    assert row["overdue"] is None
    assert "window is still open" in row["next"]


def test_a_finished_record_has_nothing_outstanding(tmp_path):
    root = _tree(tmp_path, [_record(state="closed", issue=99)])
    row = incidents_view(root)["incidents"][0]
    assert row["ok"] is True
    assert row["blocking"] == []
    assert "may close" in row["next"]


def test_a_malformed_file_is_a_finding_and_not_a_crash(tmp_path):
    root = _tree(tmp_path, [_record()], malformed="{ this is not json")
    view = incidents_view(root)
    broken = [r for r in view["incidents"] if r["state"] == "malformed"]
    assert len(broken) == 1
    assert "does not parse" in broken[0]["next"]
    assert view["headline"]["total"] == 2


def test_a_checkout_with_no_records_reports_zero_rather_than_failing(tmp_path):
    root = _tree(tmp_path, [])
    view = incidents_view(root)
    assert view["incidents"] == []
    assert view["headline"]["total"] == 0


# ---------------------------------------------------------------------------------------------
# Ordering, tiers and the link.
# ---------------------------------------------------------------------------------------------

def test_the_worst_records_come_first(tmp_path):
    landed = (_dt.date.today() - _dt.timedelta(days=40)).isoformat()
    root = _tree(tmp_path, [
        _record(id="INC-2026-01-05-fine", state="closed"),
        _record(id="INC-2026-01-06-overdue",
                third_order={"tier": "test", "mechanism": "m", "landed_on": landed},
                grade={"signature": "s", "window_days": 14, "verdict": "unproven"}),
        _record(id="INC-2026-01-07-unarmed", third_order={"tier": "test", "mechanism": "m"}),
    ])
    order = [r["id"] for r in incidents_view(root)["incidents"]]
    assert order.index("INC-2026-01-07-unarmed") < order.index("INC-2026-01-06-overdue")
    assert order[-1] == "INC-2026-01-05-fine"


def test_every_tier_the_script_knows_about_has_a_plain_english_meaning():
    """A tier the page cannot explain renders as a bare word, which is what the loop is for."""
    incident = _incident_script()
    assert set(TIER_MEANING) == set(incident.TIERS)
    for meaning in TIER_MEANING.values():
        assert len(meaning) > 20


def test_the_tier_counts_add_up(tmp_path):
    root = _tree(tmp_path, [
        _record(id="INC-2026-01-05-a", third_order={"tier": "heal", "mechanism": "m",
                                                    "landed_on": "2026-01-06"}),
        _record(id="INC-2026-01-06-b", third_order={"tier": "test", "mechanism": "m",
                                                    "landed_on": "2026-01-07"}),
    ])
    head = incidents_view(root)["headline"]
    assert head["by_tier"] == {"heal": 1, "refuse": 0, "test": 1, "memory": 0}
    assert head["no_tier"] == 0


def test_the_link_on_every_row_is_one_the_docs_view_will_actually_serve():
    """The class of defect this kills: a link that lands on the right page and does nothing."""
    for row in incidents_view(REPO)["incidents"]:
        served = doc_view(REPO, row["doc"])
        assert served["name"] == row["doc"]
        assert row["id"] in served["text"]


def test_the_reader_gets_the_class_of_failure_not_just_the_instance(tmp_path):
    root = _tree(tmp_path, [_record()])
    row = incidents_view(root)["incidents"][0]
    assert row["class"] == "CLASS: things break"
    assert row["what_broke"] == "the thing broke"
    assert row["mechanism"] == "a test goes red"


# ---------------------------------------------------------------------------------------------
# The Now page polls this every 30 seconds. It must never be what breaks the front page.
# ---------------------------------------------------------------------------------------------

def test_the_now_page_headline_survives_a_checkout_with_no_incident_script(tmp_path):
    from prospector.ops import console_api

    root = tmp_path / "empty"
    root.mkdir()
    original = console_api._repo_root
    console_api._repo_root = lambda: root  # type: ignore[assignment]
    try:
        head = console_api._incident_headline()
    finally:
        console_api._repo_root = original  # type: ignore[assignment]
    assert "error" in head
    assert head["error_kind"]


def test_the_now_page_headline_is_the_same_numbers_as_the_page():
    from prospector.ops.console_api import _incident_headline

    assert _incident_headline() == incidents_view(REPO)["headline"]


def test_the_view_is_registered_so_the_console_can_ask_for_it():
    from prospector.ops.console_api import READS

    assert "incidents" in READS


# ---------------------------------------------------------------------------------------------
# The parameter that lets one loader serve both callers.
# ---------------------------------------------------------------------------------------------

def test_load_reads_the_directory_it_is_given(tmp_path):
    incident = _incident_script()
    root = _tree(tmp_path, [_record(id="INC-2026-01-08-elsewhere")])
    records = incident.load(root / "docs" / "incidents")
    assert [r["id"] for r in records] == ["INC-2026-01-08-elsewhere"]
    assert incident.load() != records

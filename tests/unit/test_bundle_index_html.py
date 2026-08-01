"""Bundle-level proof that `_create_bundle` now ships index.html alongside the eight
unchanged .md deliverables, without altering them.

Companion to test_bundle_completeness.py (which pins the eight .md files and their
completeness floors); this file pins the NINTH file and proves it doesn't disturb the eight.
"""
from __future__ import annotations

import zipfile

import pytest

from prospector.bridge import BUNDLE_FILES, EngineBridge, _SECTION_TITLES
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class _Cfg:
        entitlements_api_key = ""
        store_payments = {"active_provider": "stripe"}

    return EngineBridge(_Cfg())


def _dossier():
    cand = Candidate(
        candidate_id="c" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    check = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance (SAGB, 2025).",
        citations=[], sources=[], queries=[],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check],
                   created_at="2026-07-31T00:00:00Z")


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    return {k: f"# {k}\n\n{body}" for k in
            ("build_spec", "gtm_plan", "ops_plan", "financial_model")}


def _entries(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


class TestIndexHtmlShipsAlongsideTheEightFiles:
    def test_index_html_is_in_the_zip(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        entries = _entries(path)
        assert "index.html" in entries

    def test_the_eight_md_files_are_still_all_present(self, bridge):
        """index.html is additive — it must never crowd out or replace a promised deliverable."""
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        entries = _entries(path)
        assert set(BUNDLE_FILES) <= set(entries)
        assert len(entries) == len(BUNDLE_FILES) + 1

    def test_index_html_is_not_part_of_the_sellability_contract(self):
        """BUNDLE_FILES is the drift-tested contract with the storefront's PackContents.tsx —
        index.html is a bonus, not a promised file, so it must not be in that tuple."""
        assert "index.html" not in BUNDLE_FILES

    def test_md_file_bytes_are_byte_identical_to_before_the_feature(self, bridge):
        """The feature must not touch the existing deliverables in any way — same bytes with
        or without index.html in the zip."""
        artifacts = _full_artifacts()
        path = bridge._create_bundle(_dossier(), artifacts, [])
        entries = _entries(path)

        # Reference: what bridge.py would write for each file with these exact inputs,
        # reconstructed the same way _create_bundle does (mirrors test_bundle_completeness's
        # own construction, since that file already pins this shape for the .md files alone).
        from prospector.bridge import _held_back_md
        from prospector.dossier import render_markdown
        from prospector.pack_floors import exec_summary_md, first_week_checklist_md

        d = _dossier()
        expected = {
            "01_Blueprint_BuildSpec.md": artifacts.get("build_spec", "") or _held_back_md("Blueprint / build spec"),
            "02_Marketing_Plan_GTM.md": artifacts.get("gtm_plan", "") or _held_back_md("Go-to-market plan"),
            "03_Operations_Plan.md": artifacts.get("ops_plan", "") or _held_back_md("Operations plan"),
            "QA_Report.md": render_markdown(d),
            "00_Executive_Summary.md": exec_summary_md(d.candidate, d.checks),
            "05_First_Week_Checklist.md": first_week_checklist_md(d.candidate),
        }
        for name, text in expected.items():
            assert entries[name] == text.encode(), f"{name} bytes changed"

    def test_index_html_contains_all_section_titles(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()
        for title in (
            "Executive Summary",
            "The Blueprint (Build Spec)",
            "The Go-To-Market Plan",
            "The Operations Plan",
            "The Financial Model",
            "First-Week Checklist",
            "Marketing Assets",
            "The QA Report, with the receipts",
        ):
            assert title in html

    def test_index_html_reads_in_the_bundle_files_order(self, bridge):
        """REGRESSION: the reading order was the WRITE order, and nobody chose it.

        `_create_bundle` writes the cheap artifacts first and the two deterministic floors
        last, because those need `dossier.checks` in hand. While the index accumulated
        alongside those writes, a buyer opening the pack got 01, 02, 03, 04, QA, Marketing,
        00, 05 — landing on the build spec, meeting the Executive Summary seventh of eight,
        and finding the First-Week Checklist, the only file that says what to DO, last.
        Proven on a shipped bundle (publish/bundles/fbd10d6bdfcd5e31/*.zip): "Executive
        Summary" at char 5212, "The Blueprint (Build Spec)" at 4806.

        The test above asserts every title is PRESENT, which was true throughout and is why
        this shipped. Presence was never the property that mattered.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()

        positions = [(html.index(_SECTION_TITLES[name]), name) for name in BUNDLE_FILES]
        assert positions == sorted(positions), (
            "index.html reading order drifted from BUNDLE_FILES: "
            f"{[n for _, n in sorted(positions)]}"
        )
        # The two that motivated the fix, asserted by name so a future reorder has to be
        # deliberate about these specifically.
        assert html.index("Executive Summary") < html.index("The Blueprint (Build Spec)")
        assert html.index("First-Week Checklist") < html.index("The QA Report, with the receipts")

    def test_index_html_carries_the_pack_title_and_id(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()
        assert "Shellfish Classification Aid" in html
        assert "c" * 16 in html

    def test_index_html_does_not_trip_the_structural_audit(self, bridge):
        """audit_bundle only checks BUNDLE_FILES — an extra file must not register as a
        'stub' or otherwise affect the is_listed-deciding audit."""
        from prospector.bridge import audit_bundle
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert audit_bundle(path) == ([], [])

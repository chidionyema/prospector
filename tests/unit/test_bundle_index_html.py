"""Bundle-level proof that index.html IS the pack the buyer opens.

Until 2026-08-15 this file proved the opposite half: that index.html shipped ALONGSIDE eight
unchanged .md deliverables without altering them. It was the ninth file, a bonus, and the
history is kept below because the reason it was a bonus was sound at the time — a new renderer
must not be able to delist a pack whose promised files all arrived.

The renderer is not new now, and the founder's brief ("i dont like md files at all, we are not
selling to developers") removed the eight documents from the archive entirely. They are the
render INPUT (`PACK_DOCUMENTS`), and this file is the reader they are rendered into. So the
assertions are inverted rather than dropped: index.html is in the sellability contract, and
what is proven about the eight documents is that no trace of them reaches the zip.

Companion to test_bundle_completeness.py (the completeness floors) and
test_bundle_declared_entries.py (which owns the exact-archive-set question).
"""
from __future__ import annotations

import zipfile

import pytest

from prospector.bridge import (
    _SECTION_TITLES,
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    BUNDLE_READING_ORDER,
    EngineBridge,
)
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


class TestTheReaderIsThePack:
    """Renamed 2026-08-15 from `TestIndexHtmlShipsAlongsideTheEightFiles`, which named a
    relationship that no longer exists: there are no eight files to ship alongside."""

    def test_index_html_is_in_the_zip(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        entries = _entries(path)
        assert "index.html" in entries

    def test_every_contract_file_is_present_and_nothing_undeclared(self, bridge):
        """Was `test_the_eight_md_files_are_still_all_present`.

        The guarantee is unchanged and is the one that survived every revision of this test:
        nothing promised leaves the bundle, and nothing UNDECLARED enters it. Only the
        membership of "promised" changed.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        entries = _entries(path)
        assert set(BUNDLE_FILES) <= set(entries)
        # Was `len(entries) == len(BUNDLE_FILES) + 1`. That counted the bonus files rather than
        # naming them, so shipping a second one (manifest.jsonld) failed here as though a
        # DELIVERABLE had gone missing — which is the opposite of what this test is for. Naming
        # them keeps the real guarantee (nothing unexpected enters a bundle, and nothing promised
        # leaves it) while letting the bonus set grow deliberately.
        # Read from BUNDLE_BONUS_FILES rather than a literal, for the same reason the literal
        # replaced a count: a third bonus file (Evidence_and_Constraints.md, P4) failed here as
        # though a DELIVERABLE had gone missing. The guarantee kept is the real one — nothing
        # promised leaves the bundle, and nothing UNDECLARED enters it.
        assert set(entries) - set(BUNDLE_FILES) == set(BUNDLE_BONUS_FILES)

    def test_index_html_is_the_sellability_contract(self):
        """Renamed and INVERTED 2026-08-15. It was
        `test_index_html_is_not_part_of_the_sellability_contract`, and the reasoning it carried
        was: BUNDLE_FILES is the drift-tested contract with the storefront's PackContents.tsx,
        and a bonus file's render failure must never be able to block a listing.

        That protected the eight documents from a new renderer. There are no eight documents in
        the archive now — index.html is what the buyer opens, so a bundle without one has
        nothing readable in it, and holding such a pack UNLISTED is the correct outcome rather
        than the hazard. The consequence is deliberate: if the reader fails to render, the pack
        does not list.
        """
        assert "index.html" in BUNDLE_FILES
        assert "index.html" not in BUNDLE_BONUS_FILES

    def test_the_archive_holds_the_declared_entries_and_no_markdown_at_all(self, bridge):
        """Was `test_md_file_bytes_are_byte_identical_to_before_the_feature`.

        That test reconstructed each `.md` exactly as `_create_bundle` composes it and compared
        bytes, to prove index.html was not the thing changing them. The documents no longer
        reach the zip, so there are no bytes of record to compare and the question the test
        asked is gone. What replaces it is the founder's requirement, which is the stronger
        statement anyway: the archive is exactly what the two registries declare, and NO
        markdown survives into it.

        The history is kept because the byte-identity discipline still governs the documents on
        their way into the render — `tests/unit/test_publish_pass.py` pins the publish pass, and
        tests/unit/test_backfill_bundle_html.py pins that a pack already sold gets the same
        text a fresh one does.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        entries = _entries(path)

        assert not [n for n in entries if n.endswith(".md")], (
            f"markdown reached the buyer's zip: {[n for n in entries if n.endswith('.md')]}")
        assert set(entries) == set(BUNDLE_FILES) | set(BUNDLE_BONUS_FILES)

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

    def test_index_html_reads_in_the_reading_order(self, bridge):
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

        Re-pointed 2026-08-15 from `BUNDLE_FILES` to `BUNDLE_READING_ORDER` (renamed with it).
        Those two were the same list when the archive WAS the documents; they are different
        lists now — one is what the pack says, the other is what the archive holds — and the
        order a buyer reads in is the first of the two. `BUNDLE_READING_ORDER` is derived from
        `PACK_DOCUMENTS`, so the ordering assertion still tracks the single place the sequence
        is editable, which is the whole point of the fix.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()

        positions = [(html.index(_SECTION_TITLES[name]), name) for name in BUNDLE_READING_ORDER]
        assert positions == sorted(positions), (
            "index.html reading order drifted from BUNDLE_READING_ORDER: "
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
        """audit_bundle only checks BUNDLE_FILES — the declared bonus (manifest.jsonld) must
        not register as a 'stub' or otherwise affect the is_listed-deciding audit.

        Since 2026-08-15 this also proves the other direction for index.html itself: it is IN
        the contract now, so a clean audit means the reader actually arrived.
        """
        from prospector.bridge import audit_bundle
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert audit_bundle(path) == ([], [])

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


def _rich_dossier():
    """A dossier thick enough that all fourteen reading-order sections actually render.

    `_dossier()` is deliberately thin, and on a thin dossier three of the five narrative
    renderers correctly return "" and are correctly SKIPPED by the reader:

      * `pack_offer.py:118`     — no `hypothesis` and no `structural_form` on the candidate
      * `pack_field.py:284`     — no `incumbency`/`price_comparables` check to read a field from
      * `pack_bear_case.py:256` — nothing refuted, nothing unverifiable, no financial weakness

    `BUNDLE_READING_ORDER` is "the superset, not a contract" (`bridge.py:344`), so an ordering
    assertion driven by the thin dossier can only ever cover the sections that dossier happens
    to produce — and it raises `ValueError` the moment it assumes otherwise. This fixture gives
    each of those three guards the field it asks for, so the order test below covers the whole
    fourteen rather than eleven of them. `test_a_thin_dossier_skips_what_it_cannot_fill` keeps
    the other half of the behaviour pinned.
    """
    cand = Candidate(
        candidate_id="d" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
        hypothesis="Growers will pay for a sampling calendar that tracks classification changes.",
        structural_form="vertical_tool",
    )

    def _check(name, verdict, rationale, sources=()):
        return CheckResult(check_name=name, verdict=verdict, confidence=0.8,
                           rationale=rationale, citations=[], sources=list(sources), queries=[])

    checks = [
        _check("buyer_intent", Verdict.SUPPORTED,
               "Growers search for closure guidance (SAGB, 2025)."),
        _check("incumbency", Verdict.SUPPORTED,
               "Two established consultancies already sell sampling schedules to UK growers.",
               sources=["https://gov.uk/shellfish-classification"]),
        _check("payer_solvency", Verdict.REFUTED,
               "Farm margins reported at under three percent leave little budget for software."),
        _check("distribution", Verdict.UNVERIFIABLE,
               "We could not find a route that reaches these growers at reasonable cost."),
    ]
    return Dossier(candidate=cand, decision=Decision.PASS, checks=checks,
                   created_at="2026-07-31T00:00:00Z")


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    return {k: f"# {k}\n\n{body}" for k in
            ("build_spec", "gtm_plan", "ops_plan", "financial_model")}


# The buyer-visible section titles, in the order a buyer meets them.
#
# Hardcoded rather than read out of `_SECTION_TITLES` on purpose. A test that sources its
# expectations from the thing it is testing cannot fail on a rename, and a rename is exactly
# what happened here: every one of these strings was replaced on 2026-08-15 because the old set
# named the DOCUMENT ("The Financial Model", "The QA Report, with the receipts", "The Blueprint
# (Build Spec)") and two of them printed engine vocabulary at a buyer who has no QA department
# and did not buy a blueprint. Writing them out is what makes a silent slide back to that
# register fail a test. `test_the_title_registry_matches_the_reading_order` pins this literal
# against the registry, so the two cannot drift apart in silence either.
_EXPECTED_TITLES = (
    "Where this starts",
    "What you would be selling",
    "The field: who is already there",
    "The numbers",
    "What would sink this",
    "What you build",
    "How the first customers find you",
    "How it runs once it works",
    "Your first fortnight",
    "The toolkit",
    "Copy you can paste",
    "How to know in 30 days",
    "Everything we read, once",
    "Every check, in full",
)


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

    def test_the_title_registry_matches_the_reading_order(self):
        """`_SECTION_TITLES` read in `BUNDLE_READING_ORDER` IS the buyer's table of contents.

        Added 2026-08-15 with the retitle. It exists so `_EXPECTED_TITLES` can stay a literal
        without going stale unnoticed: adding a section to the reading order, or retitling one,
        fails HERE with a readable diff instead of failing the two bundle-rendering tests below
        with a `ValueError` from a `str.index` that found nothing.
        """
        assert tuple(_SECTION_TITLES[name] for name in BUNDLE_READING_ORDER) == _EXPECTED_TITLES

    def test_index_html_contains_all_section_titles(self, bridge):
        """Re-pointed 2026-08-15. The titles asserted here were the previous nine, verbatim —
        `git show 4983ef0~1:prospector/bridge.py` still carries them — and not one of the
        fourteen strings this branch replaced them with appears anywhere in that file, so this
        test fails against the behaviour it replaces.

        It also moved from `_dossier()` to `_rich_dossier()`. The thin dossier legitimately
        renders eleven of the fourteen sections (see `_rich_dossier`'s docstring for the three
        guards and why "" is right), so it could never have proven the full set present.
        """
        path = bridge._create_bundle(_rich_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()
        missing = [t for t in _EXPECTED_TITLES if t not in html]
        assert not missing, f"sections absent from index.html: {missing}"

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

        Re-pointed AGAIN 2026-08-15, twice over, when the narrative restructure landed:

        1. Every section title changed (see `_EXPECTED_TITLES`), so the two named assertions at
           the bottom named strings that no longer exist anywhere.
        2. `BUNDLE_READING_ORDER` stopped being a derivation and became an explicit fourteen-
           entry tuple that is "the superset, not a contract" (`bridge.py:344`). Five of its
           entries are rendered by guarded modules that return "" on a dossier that cannot fill
           them, and the reader skips those. Indexing every entry unconditionally against the
           thin dossier is what raised `ValueError: substring not found` here — the test was
           asserting a contract the registry had stopped making.

        The fix keeps the assertion at full strength rather than tolerating the gaps: the
        fixture became `_rich_dossier()`, which satisfies all three guards, so the order below
        is still checked across the complete fourteen. The superset behaviour itself is now
        pinned separately by `test_a_thin_dossier_skips_what_it_cannot_fill`.
        """
        path = bridge._create_bundle(_rich_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()

        positions = [(html.index(_SECTION_TITLES[name]), name) for name in BUNDLE_READING_ORDER]
        assert positions == sorted(positions), (
            "index.html reading order drifted from BUNDLE_READING_ORDER: "
            f"{[n for _, n in sorted(positions)]}"
        )
        # The two that motivated the fix, asserted by name so a future reorder has to be
        # deliberate about these specifically. Same two documents as before the retitle: the
        # executive summary ahead of the build spec, the checklist ahead of the QA report.
        assert html.index("Where this starts") < html.index("What you build")
        assert html.index("Your first fortnight") < html.index("Every check, in full")
        # New with the restructure, and the reason the order was rewritten rather than merely
        # corrected: the receipts are an appendix now. They were 52% of the words of the pack
        # the founder read on 2026-08-15, positioned as the payload.
        assert html.index("What you would be selling") < html.index("Everything we read, once")

    def test_a_thin_dossier_skips_what_it_cannot_fill(self, bridge):
        """A section with nothing to say is ABSENT, not an empty heading.

        Added 2026-08-15 to pin the half of `BUNDLE_READING_ORDER` that the ordering test above
        stopped covering when it moved to the rich fixture. `bridge.py:344` calls the tuple "the
        superset, not a contract", and this is what that sentence has to mean in the archive a
        buyer opens: the three renderers that decline on a thin dossier leave no trace in the
        reader — no title, no empty section — and the sections that DO render still arrive in
        the declared order rather than closing ranks in some other one.

        Each of the three declines for a reason that is a claim we would otherwise be inventing:
        `pack_offer.py:118` will not describe a product out of fields the candidate does not
        have, `pack_field.py:284` will not tell a buyer the field is empty on the strength of an
        empty list, and `pack_bear_case.py:256` will not open a case against with no case to
        make.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        html = _entries(path)["index.html"].decode()

        for name in ("The_Offer.md", "The_Field.md", "What_Would_Sink_This.md"):
            assert _SECTION_TITLES[name] not in html, (
                f"{name} rendered a section on a dossier that cannot fill it")
            assert name not in html, f"{name} leaked its filename into the reader"

        present = [(html.index(_SECTION_TITLES[n]), n)
                   for n in BUNDLE_READING_ORDER if _SECTION_TITLES[n] in html]
        assert len(present) == len(BUNDLE_READING_ORDER) - 3
        assert present == sorted(present), (
            "a skipped section reordered the ones around it: "
            f"{[n for _, n in sorted(present)]}")

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

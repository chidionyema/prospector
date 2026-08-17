"""P4: the evidence, stated once, in one file — `Evidence_and_Constraints.md`.

The defect this document answers was measured, not asserted (`pack_reference.py` module
docstring): the same cited source is leaned on by all three plan files in a median of 11 places
per pack, across 62 of 62 live packs. The founder read that as "we sell the same 2,500 words
three times".

What earns this file's keep is not that the document renders — it is the three properties that
make it safe to put on packs somebody has ALREADY paid for:

  * it is deterministic (no model call), so a backfill can add it to a sold pack;
  * it reads BOTH record shapes — a live `Dossier` and the `SimpleNamespace` tree the backfill
    reconstructs from `store/dossiers/<id>.json` — because one of those two is the shape every
    already-listed pack has;
  * it invents nothing. In particular the assumptions register carries no cost column, however
    much the programme doc asks for one: nothing on disk prices a test, and a priced column
    would be a number we made up.
"""
from __future__ import annotations

import re

import pytest

from prospector import pack_bear_case, pack_manifest, pack_reference
from prospector.bridge import (
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    BUNDLE_READING_ORDER,
    PACK_DOCUMENTS,
)
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

_HEX = "1e62e0c381e1c8d3"


def _source(sid: str, url: str) -> Source:
    return Source(source_id=sid, url=url, text="A retrieved passage.",
                  published_at="2026-01-04", query="q", fetched_at="2026-07-31T00:00:00Z")


# One page, cited by two different checks under two different retrieval ids — the exact shape
# that made `lulu.com/create/print-books` appear twice in the pack the founder read.
_SHARED_A = _source(_HEX, "https://example.gov.uk/closures")
_SHARED_B = _source("b" * 16, "https://example.gov.uk/closures")


def _dossier() -> Dossier:
    cand = Candidate(candidate_id="c" * 16, title="Shellfish Classification Aid",
                     one_liner="Scheduling aid for UK oyster farms.", market="uk",
                     who_pays="owner-operated shellfish farms", why_now="new sampling rules")
    supported = CheckResult(
        check_name="legality", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale=f"Closure notices are published weekly [{_HEX}].",
        citations=[_HEX], sources=[_SHARED_A])
    refuted = CheckResult(
        check_name="incumbency", verdict=Verdict.REFUTED, confidence=0.7,
        rationale="Two incumbents already ship this.",
        citations=["b" * 16], sources=[_SHARED_B, _source("d" * 16, "https://reddit.com/r/x")])
    unproven = CheckResult(
        check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE, confidence=0.2,
        rationale="No accounts filed for the segment.",
        queries=["uk shellfish farm accounts", "oyster farm turnover companies house"])
    return Dossier(candidate=cand, decision=Decision.PASS,
                   checks=[supported, refuted, unproven],
                   created_at="2026-07-31T00:00:00Z", provider_chain="claude-cli/default")


@pytest.fixture
def md() -> str:
    return pack_reference.render(_dossier())


@pytest.fixture
def bear() -> str:
    """The other renderer of the same dossier — the one that now owns the register."""
    return pack_bear_case.render(_dossier())


#: The register's heading, in the one module that prints it (`pack_bear_case.py:125`).
_REGISTER = "## What we could not settle, and what it would take"


class TestItSaysTheEvidenceOnce:
    def test_the_settled_checks_are_named_in_the_buyers_words(self, md):
        """Same label map as the QA report (`dossier.check_label`) — two maps is how the same
        check comes to be called two different things in one pack."""
        from prospector.dossier import check_label
        assert f"### {check_label('legality')}" in md
        assert f"### {check_label('incumbency')}" in md
        assert "legality" not in md.replace(check_label("legality"), "")

    def test_a_refuted_check_is_flagged_as_the_one_to_read_first(self, md):
        assert "The evidence goes against this. Read this one before you build." in md

    def test_every_source_is_listed_exactly_once_however_many_checks_fetched_it(self, md):
        block = md.split("## Every source, once")[1]
        assert block.count("https://example.gov.uk/closures") == 1
        assert "2 pages" in block, "the count must be of DISTINCT pages, not retrievals"

    def test_a_forum_post_says_so_rather_than_passing_as_a_record(self, md):
        assert re.search(r"- \[reddit\.com\]\(https://reddit\.com/r/x\) — .+", md)

    def test_an_inline_passage_id_becomes_a_link_not_raw_hex(self, md):
        """`pack_reference` runs with NO prose pass behind it (the backfill renders it straight
        into a zip), so it must do its own linking. 806 raw 16-hex ids shipped in 10 live packs
        because a renderer assumed a downstream pass would clean them."""
        assert _HEX not in md
        assert "(https://example.gov.uk/closures)" in md

    def test_it_does_not_claim_to_have_rewritten_the_plans(self, md):
        """The honest scope: this file makes the evidence readable once; it does not shorten a
        pack somebody already owns. Saying otherwise in the document would be the claim."""
        assert "None of them re-argues the evidence. It is here." in md


class TestTheAssumptionsRegisterHasExactlyOneOwner:
    """Renamed 2026-08-15 from `TestTheAssumptionsRegister`, when the register moved out.

    It used to be rendered HERE under `## What we could not prove` and by
    `pack_bear_case._unproven_block` as well: the same `unverifiable` rows, the same
    `check_label` headings, the same rationales and the same searches, in two sections of one
    pack. That is not a paraphrase needing judgement — it is one list printed twice, and it was
    the largest structural duplicate in the pack the founder read.

    So the property worth pinning is no longer "the register renders". It is that EXACTLY ONE
    module renders it, and which one: the bear case, because an unproven assumption is an
    argument about whether to build (`pack_reference.py:142-154`). Tests that only assert the
    presence of the register in the bear case would pass while this document quietly grew a
    second copy, which is why the absence half is asserted on the rows and not just the heading.
    """

    def test_the_evidence_document_no_longer_carries_the_register(self, md, bear):
        from prospector.dossier import check_label
        assert _REGISTER in bear, "the register has to exist somewhere for absence to mean this"
        assert _REGISTER not in md
        # The rows, not just the title: a duplicate under a different heading is the same
        # duplicate, and renaming the section is the cheapest way to defeat a heading check.
        assert f"### {check_label('payer_solvency')}" not in md
        assert "No accounts filed for the segment." not in md
        assert "uk shellfish farm accounts" not in md

    def test_the_bear_case_gathers_the_unproven_checks_once(self, bear):
        """Where the register went, and the receipt that "moved" was not "deleted"."""
        from prospector.dossier import check_label
        assert _REGISTER in bear, "the register is in neither document"
        block = bear.split(_REGISTER)[1]
        assert block.count(f"### {check_label('payer_solvency')}") == 1
        assert "No accounts filed for the segment." in block
        assert "uk shellfish farm accounts" in block

    def test_the_register_prices_nothing_and_offers_the_searches_instead(self, bear):
        """`source-or-die`: the programme doc asks for a cost-to-confirm column, and nothing on
        disk prices a test. An invented column is the exact failure the catalogue exists to
        avoid, so the register omits it.

        The "and says why" half of this test's old name went with the move and did NOT survive
        as rendered text anywhere: the explanation is now prose in two module docstrings
        (`pack_reference.py:42-47`, `pack_table.py:5-11`) and `Nothing we retrieved tells us
        what a test costs` is in no module at all — asserting it here would have been asserting
        a comment. What IS rendered, and is the honest substitute for a price, is the searches
        the engine actually ran (`pack_bear_case.py:142-147`; the same column is `how_to_settle`
        in `Assumptions.csv`, `pack_table.HEADER`). So: no money, and a real answer to "what
        would it take" in its place.
        """
        block = bear.split(_REGISTER)[1]
        assert not re.search(r"£\s?\d|\$\s?\d|\bcost[s]? about\b", block)
        assert "these are the angles already tried" in block
        assert "- uk shellfish farm accounts" in block

    def test_a_dossier_with_nothing_unproven_omits_the_register_from_both_documents(self):
        """Was `..._omits_the_section_entirely`, and was passing for the wrong reason: after the
        move it looked for `What we could not prove` in `pack_reference.render`, a string that
        module no longer emits under ANY dossier, so it would have passed against "".

        The section is now checked in the module that owns it, and against the populated render
        of the same fixture — the bear case still returns a document here (the refuted check
        keeps it alive), so this pins the omission of the REGISTER rather than the omission of
        the whole file, which is the thing that could actually regress.
        """
        from prospector.dossier import check_label
        d = _dossier()
        d.checks = [c for c in d.checks if c.verdict is not Verdict.UNVERIFIABLE]
        thin = pack_bear_case.render(d)
        assert _REGISTER in pack_bear_case.render(_dossier())
        assert thin.startswith("# What would sink this")
        assert _REGISTER not in thin
        assert f"### {check_label('payer_solvency')}" not in thin
        assert _REGISTER not in pack_reference.render(d)


class TestItReadsBothRecordShapes:
    def test_the_backfill_shape_renders_the_same_document(self):
        """Every already-listed pack reaches this renderer as a `SimpleNamespace` tree whose
        verdicts are plain STRINGS, not `Verdict` members. A `.value` assumption anywhere here
        would render an empty document for exactly the population P4 exists to fix."""
        live = _dossier()
        replayed = pack_manifest.dossier_from_dict(live.to_dict())
        assert pack_reference.render(replayed) == pack_reference.render(live)

    def test_a_dossier_with_no_checks_renders_nothing_at_all(self):
        """An evidence document listing no evidence reads as a pack that was never verified —
        worse than shipping no such file. "" is the caller's signal not to add it."""
        d = _dossier()
        d.checks = []
        assert pack_reference.render(d) == ""


class TestItHasAPlaceInTheRead:
    def test_it_is_a_document_and_belongs_to_neither_archive_list(self):
        """Renamed 2026-08-15 from `test_it_is_a_bonus_file_not_a_promised_deliverable`.

        The reasoning it carried was: BUNDLE_FILES is the drift-tested sellability contract
        with the storefront's PackContents.tsx, so a render failure in a new document must
        never be able to block a listing. That is still why this file cannot be in
        BUNDLE_FILES — and it is no longer a bonus ENTRY either, because it is no longer an
        entry at all. It is a DOCUMENT: composed into `written`, placed in the reading order,
        and delivered through index.html and the PDF like every other section.

        Being in neither list is the load-bearing half. `audit_bundle` iterates BUNDLE_FILES
        asking "did it arrive?" and `undeclared_bundle_entries` iterates the archive asking
        "what is this?" — a name in neither list is invisible to the first and REPORTED by the
        second, so if this document ever leaked back into the zip the shop's file count would
        go wrong loudly instead of quietly.
        """
        assert pack_reference.FILENAME in BUNDLE_READING_ORDER
        assert pack_reference.FILENAME not in BUNDLE_FILES
        assert pack_reference.FILENAME not in BUNDLE_BONUS_FILES

    def test_it_is_read_immediately_before_the_qa_report(self):
        """The two evidence documents belong together: what we found, then how well we found
        it. Anywhere else and the reader meets the QA report's confidence scores before the
        evidence they score."""
        order = list(BUNDLE_READING_ORDER)
        assert order.index(pack_reference.FILENAME) + 1 == order.index("QA_Report.md")

    def test_the_reading_order_is_every_document_plus_this_one(self):
        """Was `test_the_reading_order_still_contains_every_promised_deliverable`, over
        `BUNDLE_FILES`. That arithmetic died on 2026-08-15: the reading order is derived from
        `PACK_DOCUMENTS` now, and BUNDLE_FILES is a different list of a different length, so
        `len(READING_ORDER) == len(BUNDLE_FILES) + 1` was comparing two unrelated counts and
        would have passed or failed by coincidence.

        The property is the same one it always was: the read contains every composed document,
        plus this file, and nothing else — so no document can be composed and then silently
        left out of what the buyer reads.
        """
        assert set(PACK_DOCUMENTS) <= set(BUNDLE_READING_ORDER)
        assert len(BUNDLE_READING_ORDER) == len(PACK_DOCUMENTS) + 1
        assert set(BUNDLE_READING_ORDER) - set(PACK_DOCUMENTS) == {pack_reference.FILENAME}

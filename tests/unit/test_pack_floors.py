"""Claim-safe pack floors — no invented numbers, listing never empty stub."""
from __future__ import annotations

from prospector.models import Candidate, CheckResult, Verdict
from prospector.pack_floors import (
    claim_safe_marketing,
    ensure_marketing_floor,
    exec_summary_md,
    first_week_checklist_md,
)


def test_claim_safe_marketing_uses_only_dossier_fields():
    cand = Candidate(
        title="Shellfish Window",
        one_liner="Lease closure forecast for growers",
        who_pays="Independent shellfish farmers",
    )
    checks = [
        CheckResult("buyer_intent", Verdict.SUPPORTED, 0.9, "Search demand exists"),
        CheckResult("legality", Verdict.UNVERIFIABLE, 0.0, "silence"),
    ]
    m = claim_safe_marketing(cand, checks)
    assert m[0]["type"] == "listing_page"
    copy = m[0]["copy"]
    assert "Shellfish Window" in copy
    assert "Search demand exists" in copy
    assert "TAM" not in copy
    assert "£" not in copy or "£30" not in copy  # no invented price claims
    assert "silence" not in copy  # unverifiable rationale excluded


def test_ensure_marketing_floor_fills_empty():
    cand = Candidate(title="X", one_liner="Y")
    out = ensure_marketing_floor([], cand, [])
    assert any(p.get("type") == "listing_page" and p.get("copy") for p in out)


def test_ensure_marketing_floor_keeps_existing_listing():
    cand = Candidate(title="X", one_liner="Y")
    existing = [{"type": "listing_page", "copy": "Real listing copy from content_gen"}]
    out = ensure_marketing_floor(existing, cand, [])
    assert out[0]["copy"] == "Real listing copy from content_gen"


def test_exec_summary_and_checklist_non_empty():
    cand = Candidate(title="Pack", one_liner="One line", who_pays="SMEs")
    assert "Pack" in exec_summary_md(cand, [])
    assert "First-week" in first_week_checklist_md(cand)
    assert "SMEs" in first_week_checklist_md(cand)


class TestExecSummaryOpensWithSomethingToDo:
    """The first page is now genuinely first (bridge.py reads in BUNDLE_READING_ORDER; that
    constant was called BUNDLE_FILES until 2026-08-15, when the read order and the archive
    became two different lists), so what it opens with is a product decision rather than a
    cosmetic one.

    It opens with a task, not a summary: a £49 download whose first screen is prose gives the
    buyer nothing to do in the five minutes when a refund gets decided. The task is to check
    one of our own citations — the smallest step that ends in the buyer knowing something, and
    the one everything else in the pack depends on.
    """

    def test_the_first_section_is_the_action_not_the_signals(self):
        cand = Candidate(title="Pack", one_liner="One line", who_pays="SMEs")
        md = exec_summary_md(cand, [])
        assert "## Start here" in md
        assert md.index("## Start here") < md.index("## Grounded signals")

    def test_it_points_at_somewhere_that_exists_in_what_the_buyer_downloaded(self):
        """Was `test_it_points_at_a_real_file_in_the_bundle`, and it guards the same thing it
        always did: a first instruction that sends the buyer to something the download does not
        contain is worse than no instruction at all. Only the definition of "exists" changed.

        This one caught a REAL defect on 2026-08-15 rather than going stale. The opening block
        said "1. Open **QA_Report.md**" and "**05_First_Week_Checklist.md** is what to do once
        it checks out" — and the archive stopped containing any `.md` at all that day, so the
        pack's very first page named two files the buyer does not have. `pack_floors.py` now
        interpolates SECTION titles (`QA_SECTION`, `CHECKLIST_SECTION`), which are headings in
        index.html and in the PDF, i.e. places that do exist.

        Those two constants are duplicated in `pack_floors` rather than imported from `bridge`,
        because `bridge` imports `pack_floors` and an import cycle on the money rail is not
        worth the DRY. Duplication is only safe while something holds the two copies equal, so
        that is asserted here first — this test is the reason the duplication is allowed.
        """
        import re

        from prospector import pack_floors
        from prospector.bridge import _SECTION_TITLES

        assert pack_floors.QA_SECTION == _SECTION_TITLES["QA_Report.md"]
        assert pack_floors.CHECKLIST_SECTION == _SECTION_TITLES["05_First_Week_Checklist.md"]

        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        assert re.findall(r"\b[\w/]+\.md\b", md) == [], (
            "the first page named a markdown file; no .md reaches the buyer's zip any more")
        assert pack_floors.QA_SECTION in md
        assert pack_floors.CHECKLIST_SECTION in md

    def test_it_tells_the_buyer_to_refund_us_if_the_source_does_not_check_out(self):
        # The instruction has to survive somebody later deciding it is bad for conversion.
        # It is the reason the block is credible: an opening step that could only ever
        # flatter us would not be a check, it would be an onboarding flow.
        md = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        assert "refund" in md.lower()

    def test_the_payer_line_appears_only_when_the_dossier_has_one(self):
        with_payer = exec_summary_md(
            Candidate(title="Pack", one_liner="One", who_pays="owner-operated oyster farms"), []
        )
        assert "owner-operated oyster farms" in with_payer

        without = exec_summary_md(Candidate(title="Pack", one_liner="One"), [])
        # Absent means absent — no generic "identify your customer" filler standing in for a
        # field the dossier never verified.
        assert "Start here" in without
        assert "4." not in without

    def test_it_still_invents_nothing(self):
        md = exec_summary_md(Candidate(title="Pack", one_liner="One", who_pays="SMEs"), [])
        # Scoped to the block this class is about. The whole-document version of this
        # assertion fails on the existing "What this pack does not claim" section, which
        # contains "TAM" and "guaranteed" precisely because it is DISCLAIMING them — a good
        # reminder that a bare keyword scan cannot tell a claim from its negation.
        block = md[md.index("## Start here"):md.index("## Grounded signals")]
        for invented in ("guaranteed", "TAM", "you will earn", "risk-free", "proven to"):
            assert invented.lower() not in block.lower()

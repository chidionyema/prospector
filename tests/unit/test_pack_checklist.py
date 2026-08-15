"""The pack's action document — `05_First_Week_Checklist.md`.

Measured 2026-08-13 across every bundle on disk: **127 of 127 checklists were the same six
lines**, because `pack_floors.first_week_checklist_md` was wired unconditionally at
`bridge.py:1536`. The buyer of a £320 plan was told to "re-read the QA report kill/pass gates"
and to confirm that "the buyer (`who_pays`)" matched reality — the engine's own audit trail,
addressed to the engine, with a snake_case field name in a code span.

These tests pin the three things that make the replacement worth shipping, and one that keeps
it honest:

  * it is SPECIFIC to the pack — the buyer, the open questions, and headings out of the pack's
    own plan documents;
  * it says nothing the pack did not give it. Every specific comes from a field, a verdict or a
    `##` heading, never from scraped model prose;
  * it never quotes a heading as something it is not. "The buyer, stated precisely" is a
    perfectly good heading and instructing somebody to pick a CHANNEL out of it is worse than
    the generic sentence it replaced;
  * it is deterministic, so the 127 packs already sold can be given the identical document.
"""
from __future__ import annotations

import pytest

from prospector import pack_checklist, pack_manifest
from prospector.dossier import check_label
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict

BUILD_SPEC_MD = """# Build spec

## 1. What this is, in one paragraph

Words.

## 2. The paragraph library — the actual product

Words.
"""

GTM_MD = """# GTM

## What we are selling, in one line a stranger can repeat

Words.

## The buyer, stated precisely

Words.

## Where these families already are

Words.
"""

OPS_MD = """# Ops

## What you are running

Words.

## Intake — the form that does half the work

Words.
"""

DOCS = {
    pack_checklist.BUILD_SPEC: BUILD_SPEC_MD,
    pack_checklist.GTM_PLAN: GTM_MD,
    pack_checklist.OPS_PLAN: OPS_MD,
    pack_checklist.FINANCIAL_MODEL: "## What it earns\n\n- **Month 1:** £320 × 2 = **£640**\n",
}


def _dossier(checks=None, who="Unpaid family carers in England. They pay out of pocket.") -> Dossier:
    cand = Candidate(candidate_id="c" * 16, title="Care Hours Appeal Pack",
                     one_liner="Challenges a cut in council-funded care hours.", market="uk",
                     who_pays=who, why_now="Council budgets were cut in April.")
    return Dossier(candidate=cand, decision=Decision.PASS,
                   checks=checks if checks is not None else _checks(),
                   created_at="2026-07-31T00:00:00Z", provider_chain="claude-cli/default")


def _checks():
    return [
        CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.8,
                    rationale="Carers already pay solicitors."),
        CheckResult(check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE, confidence=0.2,
                    rationale="No passage states what a carer can afford."),
        CheckResult(check_name="distribution", verdict=Verdict.UNVERIFIABLE, confidence=0.1,
                    rationale="No passage states a reachable channel."),
        CheckResult(check_name="incumbency", verdict=Verdict.REFUTED, confidence=0.7,
                    rationale="Two incumbents already ship this."),
    ]


@pytest.fixture
def md() -> str:
    return pack_checklist.render(_dossier(), DOCS)


class TestItIsNotTheTemplateItReplaced:
    def test_the_engines_own_audit_trail_is_not_the_buyers_first_week(self, md):
        assert "QA report" not in md
        assert "SUPPORTED citation" not in md
        assert "claim-check" not in md

    def test_no_field_name_is_printed_at_the_buyer(self, md):
        """`prompts/artifacts.md` forbids this for every other document in the pack; the one
        document that was not model-written was the one breaking the rule."""
        assert "who_pays" not in md
        assert "`" not in md, "a code span in a buyer's plan is the engine talking to itself"

    def test_it_is_specific_to_this_pack_not_to_packs_in_general(self, md):
        assert "Care Hours Appeal Pack" in md
        assert "Unpaid family carers in England." in md


class TestTheBuyerIsTheSpine:
    def test_step_one_is_go_and_find_five_of_them(self, md):
        assert md.index("Find five of them") < md.index("## Week two")

    def test_a_buyer_described_in_one_long_clause_is_still_printed_in_full(self):
        """Measured on disk: 24 of 75 buyer descriptions are a single clause over 200
        characters. A shortening rule that returns "" for those hands a THIRD of the catalogue
        back to the generic template — the rule silently deciding which packs get the good
        document."""
        long_who = ("Owner-operators of the ~350 classified shellfish production businesses in "
                    "England, Wales and Scotland (rope-grown mussel, oyster and clam farms, "
                    "typically 1-10 staff), paying £80-£250 a month per lease; secondary seats "
                    "for the depuration-tank operators who schedule purge capacity")
        out = pack_checklist.render(_dossier(who=long_who), DOCS)
        assert long_who in out

    def test_no_buyer_named_means_no_document_and_the_floor_takes_over(self):
        """A plan whose first step is "find five of blank" is broken in a way the generic
        template is not. Returning "" is what hands the caller back to the floor."""
        assert pack_checklist.render(_dossier(who=""), DOCS) == ""


class TestWhatWeCouldNotSettleBecomesTheirFirstQuestion:
    def test_the_open_question_is_put_to_the_buyer_in_the_buyers_words(self, md):
        assert check_label("payer_solvency") in md
        assert "found nothing that settles it" in md

    def test_the_remaining_open_questions_are_named_beside_it_not_dropped(self, md):
        assert check_label("distribution") in md

    def test_evidence_that_came_back_the_wrong_way_gets_its_own_step_before_building(self, md):
        assert check_label("incumbency") in md
        assert md.index(check_label("incumbency")) < md.index("## Week two")

    def test_a_settled_check_is_not_listed_as_homework(self, md):
        assert check_label("pain_reality") not in md

    def test_a_pack_with_nothing_open_does_not_print_an_empty_step(self):
        settled = [c for c in _checks() if c.verdict == Verdict.SUPPORTED]
        out = pack_checklist.render(_dossier(settled), DOCS)
        assert "found nothing that settles it" not in out
        assert "came back the wrong way" not in out


class TestItQuotesTheDocumentsOwnHeadings:
    def test_the_number_the_document_gave_its_heading_is_not_quoted_back(self, md):
        assert "“The paragraph library — the actual product”" in md
        assert "2. The paragraph library" not in md

    def test_the_section_that_restates_what_the_thing_is_is_skipped(self, md):
        """A buyer standing in week one does not need "What this is, in one paragraph" pointed
        out to them; every plan document opens with one."""
        assert "What this is, in one paragraph" not in md
        assert "What you are running" not in md

    def test_the_channel_step_only_quotes_a_section_that_names_channels(self, md):
        """The regression this pins, seen on a live pack: "The buyer, stated precisely" is the
        first working heading in the GTM plan, and quoting it here told the buyer to pick a
        channel out of a section with no channel in it."""
        assert "Pick ONE channel out of “Where these families already are”" in md
        assert "The buyer, stated precisely" not in md

    def test_with_no_channel_section_it_names_the_document_rather_than_the_wrong_section(self):
        """Re-pointed 2026-08-15: the fallback names the SECTION, not the dict key. Until that
        day this asserted `*02_Marketing_Plan_GTM.md*` — a filename that is no longer in the
        download, so the test was pinning the defect rather than the behaviour. The property is
        untouched: when no heading in the plan names a channel, send the buyer to the whole
        plan rather than to a section that is not about channels."""
        docs = dict(DOCS, **{pack_checklist.GTM_PLAN: "## The buyer, stated precisely\n\nWords.\n"})
        out = pack_checklist.render(_dossier(), docs)
        assert f"Pick ONE channel out of *{pack_checklist.GTM_PLAN_SECTION}*" in out

    def test_a_document_the_pack_does_not_carry_is_never_referred_to(self):
        out = pack_checklist.render(_dossier(), {})
        for absent in (pack_checklist.GTM_PLAN, pack_checklist.GTM_PLAN_SECTION,
                       pack_checklist.FINANCIAL_MODEL, pack_checklist.FINANCIAL_MODEL_SECTION):
            assert absent not in out, absent
        assert "Find five of them" in out, "the plan still stands on the buyer alone"


class TestItSendsTheBuyerSomewhereThatExists:
    """Added 2026-08-15, for a defect of the same class as `pack_floors.exec_summary_md`.

    This module interpolated its own dict KEYS into buyer prose — "It is in
    *04_Financial_Model.md*", "Cut ... in *01_Blueprint_BuildSpec.md*" — and on 2026-08-15 the
    archive stopped carrying any `.md` at all (`PACK_DOCUMENTS`, the render input, split from
    `BUNDLE_FILES`, the archive contract). The one page a buyer pins up was directing them to
    open four files that are not in the download.

    The fix names SECTIONS of the reader instead, which is both what the buyer can find and
    what was always meant — the two cross-references already written by hand on this page, to
    *Evidence and Constraints*, were section titles rather than filenames.

    Those four constants are duplicated in `pack_checklist` rather than imported from `bridge`,
    because `bridge` imports this module and an import cycle on the money rail is not worth the
    DRY. Duplication is only safe while something holds the copies equal, which is this class.
    """

    def test_each_section_constant_is_the_heading_the_reader_actually_prints(self):
        from prospector.bridge import _SECTION_TITLES

        for key, title in (
            (pack_checklist.BUILD_SPEC, pack_checklist.BUILD_SPEC_SECTION),
            (pack_checklist.GTM_PLAN, pack_checklist.GTM_PLAN_SECTION),
            (pack_checklist.OPS_PLAN, pack_checklist.OPS_PLAN_SECTION),
            (pack_checklist.FINANCIAL_MODEL, pack_checklist.FINANCIAL_MODEL_SECTION),
            # The fifth, added 2026-08-15. It was a bare literal, "*Evidence and Constraints*",
            # written by hand in two sentences — and when the reading order was re-titled that
            # day the four above failed here while this one sailed through, still pointing a
            # buyer at a heading the reader had stopped printing. A cross-reference nobody
            # interpolated is not safer than one that is; it is only quieter when it breaks.
            (pack_checklist.EVIDENCE, pack_checklist.EVIDENCE_SECTION),
        ):
            assert title == _SECTION_TITLES[key], key

    def test_no_section_title_is_left_behind_as_a_hand_written_literal(self):
        """The rule the test above can only enforce for constants that exist.

        Every buyer-facing cross-reference on this page must go through a `*_SECTION` constant,
        so this asserts the negative: none of the OLD titles survives anywhere in the source.
        Grepping the module is the only way to catch the reference somebody writes inline
        tomorrow, which is precisely how the evidence one was missed.
        """
        import pathlib

        src = pathlib.Path(pack_checklist.__file__).read_text(encoding="utf-8")
        body = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        for retired in ("Evidence and Constraints", "The Blueprint (Build Spec)",
                        "The Go-To-Market Plan", "The Operations Plan", "The Financial Model"):
            assert retired not in body, f"{retired!r} is a heading the reader no longer prints"

    def test_no_filename_is_printed_at_the_buyer(self, md):
        """The `md` fixture is a pack that RENDERS — `render()` returns "" when the dossier
        names no buyer, and a filename assertion against "" passes vacuously. The first two
        assertions are what stops this test going quiet that way."""
        import re

        assert md, "precondition: this fixture must produce a document, not the empty early-out"
        assert pack_checklist.BUILD_SPEC_SECTION in md or pack_checklist.GTM_PLAN_SECTION in md
        assert re.findall(r"\b[\w/]+\.md\b", md) == [], (
            "the checklist named a file; no .md reaches the buyer's archive any more")


class TestItIsOneNumberedSequence:
    def test_week_two_carries_on_the_numbering_rather_than_restarting_at_one(self, md):
        """Two lists both starting at 1 read as two plans. It is one fortnight."""
        import re
        nums = [int(n) for n in re.findall(r"^(\d+)\. ", md, re.M)]
        assert nums == list(range(1, len(nums) + 1))
        assert int(re.search(r"^(\d+)\. ", md.split("## Week two")[1].lstrip(),
                             re.M).group(1)) > 1


class TestItReadsBothRecordShapes:
    def test_a_replayed_dossier_renders_the_identical_document(self):
        """The backfill rebuilds a `SimpleNamespace` tree from `store/dossiers/<id>.json` whose
        verdicts are plain strings, and that backfill is the only route this document has to
        the packs already sold."""
        live = _dossier()
        replayed = pack_manifest.dossier_from_dict(live.to_dict())
        assert pack_checklist.render(replayed, DOCS) == pack_checklist.render(live, DOCS)

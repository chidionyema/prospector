"""The case against, and the one way it could destroy the text it was moving.

`pack_bear_case` does not generate: it LIFTS claim-checked text out of the dossier and out of
`04_Financial_Model.md`, and the financial model is then rewritten to point at where the text
went. That makes the copy and the delete two halves of one move, and a move whose halves are
decided separately is a move that can drop what it is carrying.

It did. Until 2026-08-15 the copy ran only when `_bullets` parsed a list item out of the
weaknesses block, while the delete ran whenever the HEADING existed — so a weaknesses block
the model wrote as a PARAGRAPH was cut out of the financial model, never written into the bear
case, and left behind a pointer to a section that did not contain it. These pin the invariant
that replaced the two conditions: copied and deleted are the same decision.
"""
from __future__ import annotations

from types import SimpleNamespace

from prospector import pack_bear_case

WEAKNESS = pack_bear_case._FIN_WEAKNESS_HEADING
UNKNOWN = pack_bear_case._FIN_UNKNOWN_HEADING
SOFTEST = "## Where the numbers are softest"

#: A weaknesses block as prose. Nothing about it is malformed — it is what a model writes when
#: it has one thing to say and no reason to make a list of one.
PROSE = ("The revenue line assumes a 3% conversion rate we could not source, and the cost "
         "base excludes payment processing fees entirely.")


def _check(name: str = "pain_reality", verdict: str = "refuted") -> SimpleNamespace:
    """A stored check, in the `SimpleNamespace` shape `pack_manifest.dossier_from_dict` builds:
    verdicts are plain strings, not `Verdict` members."""
    return SimpleNamespace(check_name=name, verdict=verdict, sources=[], citations=[],
                           queries=[], rationale="What we found argues the other way.")


def _dossier(*checks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(checks=list(checks) or [_check()])


def _financial(body: str, heading: str = WEAKNESS) -> str:
    return ("# The numbers\n\n"
            "## What it would cost to run\n\n"
            "Hosting is £40 a month.\n\n"
            f"{heading}\n\n{body}\n")


class TestAProseWeaknessBlockSurvivesInExactlyOnePlace:
    """The defect that shipped: prose satisfied the delete condition and not the copy one."""

    def test_prose_weaknesses_are_copied_into_the_bear_case(self):
        md = pack_bear_case.render(_dossier(), _financial(PROSE))
        assert PROSE in md

    def test_the_financial_model_gives_up_only_what_the_bear_case_took(self):
        fin = _financial(PROSE)
        bear = pack_bear_case.render(_dossier(), fin)
        after = pack_bear_case.financial_md_after_absorbing(fin, pack_bear_case.TITLE)
        # The text is in the pack exactly once — neither duplicated across both documents nor,
        # as it was, deleted from one without ever reaching the other.
        assert (PROSE in bear) + (PROSE in after) == 1
        assert PROSE in bear
        assert pack_bear_case.TITLE in after  # the pointer, and it now points at something

    def test_a_block_the_bear_case_did_not_take_is_not_deleted(self):
        # An empty weaknesses block is copied by nothing, so nothing may remove it. The unknown
        # block below IS taken, which is what makes this a test of the two conditions rather
        # than of the early return.
        fin = ("# The numbers\n\n"
               f"{WEAKNESS}\n\n"
               f"{UNKNOWN}\n\nWe could not work out the churn rate.\n")
        after = pack_bear_case.financial_md_after_absorbing(fin, pack_bear_case.TITLE)
        assert WEAKNESS in after
        assert "We could not work out the churn rate." not in after


class TestTheAbsorbNeverRunsWithNowhereToPutIt:
    """`render()` returning "" means there is no bear case section, so nothing absorbed."""

    def test_a_dossier_with_nothing_against_it_and_no_soft_numbers_renders_no_section(self):
        assert pack_bear_case.render(_dossier(_check(verdict="supported")), "") == ""

    def test_when_no_section_is_rendered_there_was_nothing_to_absorb(self):
        # The invariant behind the caller's rule, pinned here rather than in the caller: a
        # financial model whose weaknesses were NOT lifted still holds them, whatever the
        # caller does. Before the fix an empty render and a deleted block could coexist.
        fin = _financial(PROSE)
        for dossier in (_dossier(_check(verdict="supported")), SimpleNamespace(checks=[])):
            if pack_bear_case.render(dossier, fin) == "":
                assert PROSE in pack_bear_case.financial_md_after_absorbing(
                    fin, pack_bear_case.TITLE)

    def test_a_financial_model_with_neither_heading_is_returned_untouched(self):
        fin = "# The numbers\n\n## What it would cost to run\n\nHosting is £40 a month.\n"
        assert pack_bear_case.financial_md_after_absorbing(fin, pack_bear_case.TITLE) == fin


class TestWhatItDoesWithWhatItTook:
    """Where the absorbed text lands, and in what shape."""

    def test_absorbed_text_appears_verbatim_under_where_the_numbers_are_softest(self):
        md = pack_bear_case.render(_dossier(), _financial(PROSE))
        assert SOFTEST in md
        assert PROSE in md.split(SOFTEST, 1)[1]

    def test_the_unknown_block_lands_under_the_same_heading(self):
        fin = _financial("We could not work out the churn rate.", heading=UNKNOWN)
        md = pack_bear_case.render(_dossier(), fin)
        assert "We could not work out the churn rate." in md.split(SOFTEST, 1)[1]

    def test_list_shapes_the_old_parser_dropped_are_items_now(self):
        # `+ `, an ordered item past 9, and an indented sub-bullet. Each was silently discarded,
        # and a block made only of these parsed as empty — the same loss as the prose case.
        body = "+ Payment fees are excluded.\n10. Churn is a guess.\n  - VAT is assumed out.\n"
        md = pack_bear_case.render(_dossier(), _financial(body))
        for item in ("Payment fees are excluded.", "Churn is a guess.", "VAT is assumed out."):
            assert f"- {item}" in md

    def test_a_multi_item_list_is_not_collapsed_into_one_paragraph(self):
        body = "- First weakness.\n- Second weakness.\n"
        assert pack_bear_case._bullets(body) == ["First weakness.", "Second weakness."]

    def test_two_prose_paragraphs_are_two_items(self):
        assert pack_bear_case._bullets("One thing.\n\nAnother thing.") == [
            "One thing.", "Another thing."]

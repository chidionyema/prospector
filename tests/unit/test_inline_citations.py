"""`link_inline_citations`: the last thing between a model's raw brackets and a paying reader.

Four renderers call it — `pack_field`, `pack_reference`, `pack_bear_case` and the dossier itself
— and none of them runs the prose pass that strips bare hex ids, which is precisely why this
function exists. Both cases below were found by READING the rendered page rather than the code
(pack 13d41ccee9e96e2d on /sample, 2026-08-15); neither had a test.
"""
from __future__ import annotations

from types import SimpleNamespace

from prospector.dossier import link_inline_citations

A = "a" * 16
B = "b" * 16
C = "c" * 16

INDEX = {
    A: SimpleNamespace(url="https://payapps.com/x"),
    B: SimpleNamespace(url="https://pbctoday.co.uk/y"),
    C: SimpleNamespace(url="https://capterra.com/z"),
}


def test_adjacent_brackets_become_one_citation_not_three_parentheses():
    """`[a][b][c]` is three passages backing ONE clause, so it is one parenthesis.

    It rendered as "(payapps.com)(pbctoday.co.uk)(capterra.com)" — three parenthesised hosts
    butted together, which a reader parses as a broken template rather than as corroboration.
    """
    out = link_inline_citations(f"ERP systems [{A}][{B}][{C}], and another product", INDEX)
    assert ")(" not in out, "the three groups were still rendered as separate parentheses"
    assert out == (
        "ERP systems ([payapps.com](https://payapps.com/x), "
        "[pbctoday.co.uk](https://pbctoday.co.uk/y), "
        "[capterra.com](https://capterra.com/z)), and another product")


def test_a_comma_separated_group_still_works():
    # The other shape the brains emit. Unchanged behaviour, pinned because the regex moved.
    out = link_inline_citations(f"claim [{A}, {B}].", INDEX)
    assert out == ("claim ([payapps.com](https://payapps.com/x), "
                   "[pbctoday.co.uk](https://pbctoday.co.uk/y)).")


def test_a_citation_truncated_mid_id_is_dropped_and_the_sentence_closed():
    """The dossier itself is truncated; every renderer printed the stub verbatim.

    `store/dossiers/13d41ccee9e96e2d.pass.json` holds an `incumbency` rationale ending
    `...on its due date in the UK [c33885f45` — nine hex digits, no closing bracket. On the page
    whose whole argument is that every claim is traceable, a half-written citation reads as a
    fabricated one. The clause is real and survives; the stub does not, and the full stop the
    truncation ate is put back.
    """
    out = link_inline_citations(
        "One passage discusses subcontractors chasing retention in the UK [c33885f45", INDEX)
    assert out == "One passage discusses subcontractors chasing retention in the UK."
    assert "c33885f45" not in out
    assert "[" not in out


def test_an_unresolvable_but_complete_id_keeps_its_pointer():
    """The rule this does NOT change.

    A full 16-hex id that is not in the index is still a pointer: someone auditing the run can
    look it up, and `_cited` has always preferred an ugly pointer to a missing one. Only a
    TRUNCATED id is dropped, because there is nothing left to point with.
    """
    missing = "d" * 16
    assert f"`{missing}`" in link_inline_citations(f"claim [{missing}].", INDEX)


def test_a_complete_citation_at_the_very_end_is_not_mistaken_for_a_truncation():
    # The boundary case the tail pattern must not eat: same position, but terminated.
    out = link_inline_citations(f"claim [{A}]", INDEX)
    assert out == "claim ([payapps.com](https://payapps.com/x))"


def test_text_with_no_citations_is_returned_unchanged():
    assert link_inline_citations("Nothing to see [not hex].", INDEX) == "Nothing to see [not hex]."

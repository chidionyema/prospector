"""The offer page: written prose, not interpolated database columns.

`pack_offer.render` is deterministic — it reads dossier fields and writes English, with no model
call — so everything it can get wrong is a template defect, and a template defect ships on every
pack at once. These pin the two that DID ship, found by reading the rendered pack for
13d41ccee9e96e2d on 2026-08-15 rather than by reading the code.
"""
from __future__ import annotations

from prospector import pack_offer
from prospector.models import Candidate


def _render(**fields) -> str:
    base = dict(title="T", one_liner="A one-liner that stands alone.")
    base.update(fields)
    return pack_offer.render(type("D", (), {"candidate": Candidate(**base)})())


class TestTheShapeOfIt:
    """The section that reads two routing keys and has to make a sentence of them.

    Both defects below rendered inside ONE sentence of a paid document::

        This is prosumer tool. The market it was checked against is uk.

    Neither is a data error — `structural_form="prosumer_tool"` and `market="uk"` are exactly
    what the dossier holds and what the engine routes on. They are what happens when a value
    chosen for lookup is printed as prose.
    """

    def test_a_form_outside_the_map_still_gets_an_article(self):
        # `_FORMS` carries the eight forms the generator is meant to emit, each already a full
        # noun phrase. The fallback path is the one that shipped, and it produced "This is
        # prosumer tool." — the raw slug dropped into the sentence with no article.
        md = _render(structural_form="prosumer_tool")
        assert "This is a prosumer tool." in md
        assert "This is prosumer tool." not in md

    def test_the_article_agrees_with_the_slug_it_was_given(self):
        assert "This is an aggregator." in _render(structural_form="aggregator")

    def test_a_mapped_form_keeps_its_own_wording_and_gains_no_second_article(self):
        # The eight mapped values already begin with "a"/"an". Prefixing an article to those
        # would have been the obvious wrong fix: "This is a a service sold as a fixed package".
        md = _render(structural_form="productized_service")
        assert "This is a service sold as a fixed package rather than by the hour." in md

    def test_the_market_is_said_the_way_a_reader_would_say_it(self):
        assert "checked against is the UK." in _render(structural_form="vertical_tool",
                                                       market="uk")
        assert "checked against is the US, Florida." in _render(structural_form="vertical_tool",
                                                                market="us-fl")

    def test_an_unmapped_market_reads_as_a_code_rather_than_an_invented_expansion(self):
        """The fallback upper-cases; it does not guess.

        "US-TX" plainly reads as a code and the reader treats it as one. Expanding it to "the US,
        Texas" from a table that does not contain Texas would be inventing a fact about the
        dossier, which is the one thing this module's docstring forbids. A visibly-unexpanded
        code is also self-reporting: it says "add this slug to `_MARKETS`" every time it renders.
        """
        assert "checked against is US-TX." in _render(structural_form="vertical_tool",
                                                      market="us-tx")

    def test_the_section_is_absent_entirely_when_the_form_is(self):
        # Absent means absent. A "The shape of it" heading over "This is ." is worse than no
        # heading, and the same rule the exec summary follows for its payer line.
        md = _render(market="uk")
        assert "The shape of it" not in md
        assert "checked against" not in md


def test_it_renders_nothing_at_all_without_a_one_liner_or_hypothesis():
    # The whole page is derived; with neither of the two fields it is derived from, the honest
    # output is an empty string that `bridge` can drop, not a title over blank space.
    assert pack_offer.render(
        type("D", (), {"candidate": Candidate(title="T", one_liner="")})()) == ""

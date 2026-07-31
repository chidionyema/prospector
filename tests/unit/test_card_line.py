"""The shelf heading (`card_line`) — length enforced by dropping, never truncating.

The card_line is the first and often only line a browsing buyer reads. Two properties matter
enough to pin: it is never silently shortened (a mid-clause cut is a claim nobody made), and it
goes through the same claim-check gate as the headline.
"""

from prospector.artifacts import CARD_LINE_MAX, _card_line, _listing_check_text, _normalize_listing


class TestCardLine:
    def test_accepts_a_line_within_the_limit(self):
        line = "Refund insurance excess for under-27 gig drivers"
        assert len(line) <= CARD_LINE_MAX
        assert _card_line(line) == line

    def test_accepts_a_line_exactly_at_the_limit(self):
        line = "x" * CARD_LINE_MAX
        assert _card_line(line) == line

    def test_discards_an_over_length_line_rather_than_truncating(self):
        # The load-bearing case. A truncating implementation would return the first 60
        # characters; this asserts the result is empty, not a prefix.
        line = "x" * (CARD_LINE_MAX + 1)
        assert _card_line(line) == ""

    def test_does_not_truncate_a_realistic_over_length_line(self):
        # Cutting at 60 here yields "Not suitable for drivers under 27 who have never held a
        # full" — which reverses the meaning of the sentence. Dropping is the only safe answer.
        line = (
            "Not suitable for drivers under 27 who have never held a full licence for two years"
        )
        assert len(line) > CARD_LINE_MAX
        assert _card_line(line) == ""

    def test_collapses_whitespace_and_strips_a_trailing_period(self):
        # The only tidying allowed, because neither can change a claim.
        assert _card_line("  Track   oyster spat windows.  ") == "Track oyster spat windows"

    def test_empty_and_missing_are_empty(self):
        assert _card_line("") == ""
        assert _card_line("   ") == ""

    def test_whitespace_collapse_can_bring_a_line_under_the_limit(self):
        line = "a" * 30 + "          " + "b" * 25  # 65 raw, 56 collapsed
        assert len(line) > CARD_LINE_MAX
        assert _card_line(line) == "a" * 30 + " " + "b" * 25


class TestNormalizeListingCardLine:
    def test_card_line_survives_normalisation(self):
        piece = _normalize_listing({"card_line": "Chase unclaimed fuel duty rebates for hauliers"})
        assert piece["card_line"] == "Chase unclaimed fuel duty rebates for hauliers"

    def test_over_length_card_line_is_dropped_by_normalisation(self):
        piece = _normalize_listing({"card_line": "y" * 200})
        assert piece["card_line"] == ""

    def test_absent_card_line_is_empty_not_missing(self):
        # The storefront reads this key unconditionally; a missing key is a KeyError waiting
        # to happen in the bridge.
        piece = _normalize_listing({"headline": "Something"})
        assert piece["card_line"] == ""

    def test_a_listing_from_a_bare_string_still_has_the_key(self):
        assert _normalize_listing("just some copy")["card_line"] == ""


class TestCardLineIsClaimChecked:
    def test_card_line_is_included_in_the_claim_check_text(self):
        # The shortest, most-read line on the storefront must not be the one line nobody
        # checked for overstatement.
        piece = _normalize_listing(
            {
                "card_line": "Guaranteed 10x returns for every buyer",
                "headline": "A calmer headline",
            }
        )
        assert "Guaranteed 10x returns for every buyer" in _listing_check_text(piece)

"""The price extractor was reading the wrong 600 characters of the page.

THE DEFECT. `extract_anchors` handed the model `s.text[:600]` — the same head-of-page slice
every other check gets. For every other check that is right. For this one it is wrong: the
head of a pricing page is navigation, a headline and a cookie banner, and the prices sit
below it.

MEASURED 2026-08-16 over the 1,809 stored passages in the last 120 dossiers: 223 carry a
price figure at all, and in 100 of those (45%) the first price falls past character 600.
The model was being asked to transcribe a number it had not been shown, and "no price page
on the open web" was being recorded for pages that stated a price on screen.

THE RULE. Same token budget, different slice: the window opens at the first price figure
when the head has none. The fabrication rail does not move — `_appears_in` still checks the
amount against the FULL passage text, so narrowing what we SHOW can never widen what we
ACCEPT.
"""
from __future__ import annotations

from prospector.price_comparables import PASSAGE_TRUNCATE, _appears_in, price_window

LEAD = "Home About Careers Contact. " * 30          # ~840 chars of navigation
PRICE = "The Pro plan costs £1,299 per seat per year."


def test_a_price_below_the_fold_is_now_inside_the_window():
    text = LEAD + PRICE + " Footer." * 50
    assert "1,299" not in text[:PASSAGE_TRUNCATE], (
        "fixture is wrong: the price must start outside the old head slice")
    assert "£1,299" in price_window(text)


def test_the_window_keeps_what_the_number_is_for():
    """A bare figure is not an anchor — the cadence and the plan name matter."""
    got = price_window(LEAD + PRICE + " Footer." * 50)
    assert "Pro plan" in got and "per seat per year" in got


def test_a_price_in_the_head_leaves_the_slice_alone():
    text = "Pricing: £49 per month. " + ("filler " * 400)
    assert price_window(text) == text[:PASSAGE_TRUNCATE]


def test_a_page_with_no_price_falls_back_to_the_head():
    text = "no numbers here at all. " * 100
    assert price_window(text) == text[:PASSAGE_TRUNCATE]


def test_a_short_passage_is_returned_whole():
    assert price_window("£20 for the kit.") == "£20 for the kit."


def test_the_window_never_exceeds_the_token_budget():
    text = LEAD + PRICE + ("tail " * 500)
    assert len(price_window(text)) <= PASSAGE_TRUNCATE + 1   # +1 for the leading ellipsis


def test_narrowing_the_window_cannot_launder_a_fabricated_price():
    """The auditor reads the full text, not the window. Both directions pinned:
    a real price below the fold still verifies, an invented one still fails."""
    text = LEAD + PRICE + " Footer." * 50
    assert _appears_in(1299, text)
    assert not _appears_in(2499, text)

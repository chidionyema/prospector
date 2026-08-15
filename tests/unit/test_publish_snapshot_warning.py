"""A pack that lists with no lead figure must say so in the run log.

WHAT WENT WRONG. `_financial_snapshot` (bridge.py) pulls the card's headline economics out of the
RENDERED financial model with regexes, and returns `{}` when nothing matches. That is the right
behaviour — inventing a figure would be an unsourced claim, the one thing this engine exists not
to do. The defect was everything downstream of it: the publish path drops empty values from the
catalogue payload, so an unparsed model left no trace at all. The pack listed, the API stored
nothing, and the storefront's fallback printed the pack's cited source count instead — which
looks deliberate. Nothing was logged, nothing went red, and the miss was invisible until someone
counted the live shelf by hand.

Measured against production on 2026-08-14, after the API began projecting the snapshot onto the
catalogue list: 59 live packs, 4 with no snapshot at all and 18 more carrying one with no
`month1Revenue`. So 22 of 59 cards led with the same class of fact, and the pipeline had never
once mentioned it.

The publish must NOT fail on this. The figure's absence is a fact about the model's wording, not
about the idea, and a validated sellable pack must not be blocked by our own parser — the same
principle that bars `price_comparables` from ever killing a candidate. So what is asserted here
is that the condition is detected, that it names WHICH gap it is, and that a pack the card can
lead with stays silent.

`_snapshot_gap` is tested directly rather than through a publish because it was extracted to be
testable without one: the full publish fixture (Stripe provisioner, R2, entitlements, a rendered
financial model) exists in test_publish_facet_warning.py and reproducing it here to exercise a
three-branch pure function would pin the fixture, not the rule.
"""
from __future__ import annotations

from prospector.bridge import _SNAPSHOT_LEAD_KEY, _financial_snapshot, _snapshot_gap


def test_a_snapshot_with_month_one_revenue_is_not_a_gap():
    """The card can lead with a number, so nothing is reported."""
    assert _snapshot_gap({"month1Revenue": "£1,300", "ltvCac": "7.1×"}) is None


def test_nothing_parsed_is_reported_as_nothing_parsed():
    """Distinct from a partial parse: this points at the financial model's SHAPE."""
    for empty in ({}, None):
        gap = _snapshot_gap(empty)
        assert gap, f"{empty!r} must be reported"
        assert "at all" in gap


def test_a_partial_parse_names_what_it_did_find():
    """Points at the money regex, not the model's shape — and the two need different fixes.

    The keys are named in the message on purpose: "ltvCac and paybackMonths matched, money did
    not" is a diagnosis, while a bare "no lead figure" sends the reader to the wrong file.
    """
    gap = _snapshot_gap({"ltvCac": "7.1×", "paybackMonths": "4 months"})
    assert gap
    assert _SNAPSHOT_LEAD_KEY in gap
    assert "ltvCac" in gap and "paybackMonths" in gap


def test_ltv_and_payback_alone_never_rescue_a_card():
    """The founder deleted both figures from the product page on 2026-08-13 as engine language.

    A card cannot lead with a number the site does not print, so their presence must not make
    this function report success — which an `any(snapshot.values())` implementation would.
    """
    assert _snapshot_gap({"ltvCac": "30.7×", "paybackMonths": "4 months"}) is not None


def test_an_empty_string_counts_as_absent():
    """A key present with no value is the same miss as a key that never parsed.

    `.get(key)` rather than `key in snapshot` is what makes this true, and it is the difference
    between a warning and a card that silently falls back.
    """
    assert _snapshot_gap({"month1Revenue": ""}) is not None


def test_the_gap_is_reached_by_a_model_the_regex_cannot_read():
    """End to end over the real extractor: prose with no recognisable money figure.

    This is the actual production failure mode — not a hand-built dict, but a financial model
    whose wording the pattern does not match. Kept deliberately free of any £ figure so the
    test states its own premise.
    """
    unparseable = "# Financial Model\n\nRevenue builds gradually over the first year.\n"
    assert _snapshot_gap(_financial_snapshot(unparseable)) is not None

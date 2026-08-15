"""L2 — price must never run backwards against the one number the buyer can see.

The founder's constraint, 2026-08-15: "a user should be able to intuit why one pack is
priced more or less than another." `sourceCount` is the only quantitative buyer-visible
field on a catalogue row, and on that day the live shelf priced BACKWARDS against it —
£29.99 packs carried a mean of 36.5 sources while £149.99 packs carried 28.6, and 18 of
58 adjacent pairs sorted by depth had the dearer pack citing fewer sources.

So the property under test is not "the price is right" — no test can know that. It is that
`price_for` is a NON-DECREASING function of `source_count`. That is falsifiable, it is the
whole of what "intuitable" means here, and it is the thing a future config edit can break
silently: an extra band edge, a non-monotonic one, or a market offset re-added on the depth
path would each restore the inversion while every rationale string still read fine.

The counts in `LIVE_SOURCE_COUNTS` are not invented. They are the 59 live rows measured on
2026-08-15 (`GET https://api.mumchimp.com/catalog`), pinned here so the suite stays offline
while still exercising the real distribution rather than a tidy synthetic one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector.config import load_config
from prospector.models import Candidate
from prospector.pricing import price_for

# Measured 2026-08-15 from the production catalogue: min 17, median 33, max 51.
LIVE_SOURCE_COUNTS = [
    17, 21, 21, 22, 22, 23, 23, 24, 24, 25, 26, 26, 26, 26, 28, 28, 29, 29, 29, 29,
    30, 31, 31, 31, 31, 32, 32, 33, 33, 33, 34, 34, 34, 34, 34, 35, 36, 39, 39, 39,
    39, 39, 39, 40, 40, 41, 42, 42, 43, 44, 45, 46, 47, 48, 48, 49, 49, 51, 51,
]


@pytest.fixture(scope="module")
def cfg():
    """The REAL config.yaml, not a fixture ladder. A synthetic config would pass while the
    shipped bands were malformed — and a malformed band list falls back to the tier ladder,
    which is exactly the regression this file exists to catch."""
    return load_config()


def _candidate(tier: str = "", market: str = "") -> Candidate:
    return Candidate(
        title="Fuel duty reclaim service for small fleet operators",
        one_liner="Reclaim fuel duty for small fleets",
        ambition_tier=tier,
        market=market,
    )


def test_bands_are_declared_and_well_formed(cfg):
    """The config contract `_usable_bands` enforces at runtime, pinned at rest: exactly
    len(rungs) - 1 strictly-increasing edges. A violation here means the shipped config
    silently degrades every publish to the tier ladder."""
    pricing = (cfg.listing or {}).get("pricing") or {}
    rungs = [int(r) for r in pricing["rungs"]]
    bands = [int(b) for b in pricing["source_count_bands"]]
    assert len(bands) == len(rungs) - 1, (
        f"{len(bands)} band edge(s) cannot split {len(rungs)} rungs")
    assert bands == sorted(set(bands)), f"band edges are not strictly increasing: {bands}"
    assert rungs == sorted(rungs), f"rungs must ascend for bands to mean anything: {rungs}"


@pytest.mark.parametrize("tier,market", [("", ""), ("side_hustle", "uk"),
                                         ("venture", "us"), ("smb", "uk")])
def test_price_is_non_decreasing_in_source_count(cfg, tier, market):
    """The load-bearing property, over a range well past the live one (0..120) so an edge
    at either end cannot hide. Runs across tiers AND markets because the depth path must
    ignore both: if `market_rung_offset` ever reached it, a `us` pack would leapfrog a
    deeper `uk` pack and the shelf would read backwards again."""
    prices = [price_for(_candidate(tier, market), None, cfg,
                        source_count=n).price_pence for n in range(0, 121)]
    for n, (a, b) in enumerate(zip(prices, prices[1:])):
        assert b >= a, (f"price fell from {a}p at {n} sources to {b}p at {n + 1} sources "
                        f"(tier={tier!r}, market={market!r})")


def test_live_catalogue_distribution_has_zero_inversions(cfg):
    """The measured shelf, repriced by the depth ladder: 0 of 58 adjacent pairs invert.
    Before this change the same 59 rows inverted on 18 pairs."""
    priced = [(n, price_for(_candidate(), None, cfg, source_count=n).price_pence)
              for n in LIVE_SOURCE_COUNTS]
    inversions = [(s1, p1, s2, p2) for (s1, p1), (s2, p2) in zip(priced, priced[1:])
                  if s2 >= s1 and p2 < p1]
    assert inversions == [], f"{len(inversions)} inverted pair(s): {inversions[:3]}"


def test_equal_counts_get_equal_prices_whatever_the_tier(cfg):
    """Two packs citing the same number of sources must cost the same, or the buyer's
    comparison fails on the page even though the sequence is technically monotonic."""
    n = 34
    prices = {price_for(_candidate(t, m), None, cfg, source_count=n).price_pence
              for t, m in [("", ""), ("side_hustle", "uk"), ("venture", "us"),
                           ("growth", "uk"), ("smb", "us")]}
    assert len(prices) == 1, f"same depth, {len(prices)} different prices: {sorted(prices)}"


def test_no_source_count_falls_back_to_the_tier_ladder(cfg):
    """`verify._check_question` prices during the moat, before any dossier exists, and must
    keep getting the tier ladder rather than a crash or a band guess."""
    d = price_for(_candidate("side_hustle", "uk"), None, cfg)
    assert d.price_pence == 2999, d.rationale
    assert "rung index" in d.rung and "depth band" not in d.rung
    assert price_for(_candidate("venture", "us"), None, cfg).price_pence == 9999


def test_malformed_bands_degrade_to_the_tier_ladder_and_never_raise(cfg):
    """A bad config edit is a data change on the money rail. It must lose the depth ladder
    loudly (a logged error) and keep publishing at the tier rung — never take the publish
    path down, and never half-apply."""
    import copy

    for broken in ([25, 30], [30, 25, 35, 45], ["a", 30, 35, 45], [25, 25, 35, 45]):
        bad = copy.deepcopy(cfg)
        bad.listing["pricing"]["source_count_bands"] = broken
        d = price_for(_candidate("side_hustle", "uk"), None, bad, source_count=50)
        assert d.price_pence == 2999, f"bands {broken!r} should have been refused: {d.rung}"


def test_depth_rung_is_stated_in_buyer_terms(cfg):
    """The rationale is the audit trail a repricing PATCH quotes as its Reason, and the
    only place the derivation survives. It must name the count and the band."""
    d = price_for(_candidate("venture", "us"), None, cfg, source_count=51)
    assert "51 distinct sources" in d.rationale
    assert d.segment["priced_by"] == "source_count"
    assert d.segment["source_count"] == "51"
    assert d.price_pence == 9999

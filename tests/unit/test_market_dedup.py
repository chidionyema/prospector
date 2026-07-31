"""Dedup is scoped per market (spec D5).

Without this, opening a second market is silently throttled: its candidates collide
with the first market's catalogue and disappear, and nothing in the logs says why.
"""
from __future__ import annotations

from prospector.dedup import dedup, drops_by_market
from prospector.models import Candidate


def _c(title: str, market: str = "") -> Candidate:
    return Candidate(title=title, one_liner="", market=market)


UK_TITLE = "Retiree's Garden-to-Table Harvest Service"
REWORDED = "Retiree Garden Harvest Share"


# ---------------------------------------------------------------------------
# Cross-market: not a duplicate
# ---------------------------------------------------------------------------

def test_same_idea_in_another_market_is_not_a_duplicate():
    unique, dropped = dedup([_c(REWORDED, "us")], [("uk", UK_TITLE)])
    assert [c.title for c in unique] == [REWORDED]
    assert dropped == []


def test_same_idea_in_the_same_market_is_still_a_duplicate():
    unique, dropped = dedup([_c(REWORDED, "uk")], [("uk", UK_TITLE)])
    assert unique == []
    assert len(dropped) == 1


def test_intra_batch_dedup_is_also_market_scoped():
    batch = [_c(UK_TITLE, "uk"), _c(REWORDED, "uk"), _c(REWORDED, "us")]
    unique, dropped = dedup(batch, [])
    kept = {(c.title, c.market) for c in unique}
    assert (UK_TITLE, "uk") in kept
    assert (REWORDED, "us") in kept
    assert (REWORDED, "uk") not in kept
    assert len(dropped) == 1


def test_subdivisions_are_distinct_markets():
    """us-tx and us-ca are different legal terrains; the same idea in each is two
    opportunities, not one."""
    unique, dropped = dedup([_c(REWORDED, "us-ca")], [("us-tx", UK_TITLE)])
    assert len(unique) == 1
    assert dropped == []


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------

def test_legacy_string_catalogue_still_works():
    """Bare strings (no market) keep behaving exactly as before."""
    unique, dropped = dedup([_c(REWORDED)], [UK_TITLE])
    assert unique == []
    assert len(dropped) == 1


def test_unmarked_candidate_matches_legacy_catalogue_via_default_market():
    unique, dropped = dedup([_c(REWORDED)], [("uk", UK_TITLE)], default_market="uk")
    assert unique == []
    assert len(dropped) == 1


def test_unmarked_candidate_is_not_matched_against_a_foreign_market():
    unique, dropped = dedup([_c(REWORDED)], [("us", UK_TITLE)], default_market="uk")
    assert len(unique) == 1
    assert dropped == []


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

def test_drops_are_attributable_to_a_market():
    batch = [_c(UK_TITLE, "uk"), _c(REWORDED, "uk"),
             _c(UK_TITLE, "us"), _c(REWORDED, "us")]
    _, dropped = dedup(batch, [])
    assert drops_by_market(dropped) == {"uk": 1, "us": 1}

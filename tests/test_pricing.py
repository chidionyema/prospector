"""Golden matrix for the L1 price ladder (prospector/pricing.py).

This file is the CONTRACT, and it is deliberately written before the implementation. The rung
values in it are a commercial judgement — the kind of call the manager owns (AGENTS.md) — so
they are pinned here rather than left for whoever writes the function to invent. The
implementation's whole job is to make this pass.

What these tests defend, in order of how badly each would hurt:

1. The DEFAULT is a no-op. An unclassified pack prices at exactly 4999, the price the whole
   catalogue already sells at. Guessing at the price of a pack we know nothing about is
   strictly worse than not moving it, and a ladder that silently re-prices every legacy pack
   the moment it lands is a catalogue-wide incident, not a feature.
2. Every price is a RUNG. Not "close to a rung", not rounded to one — a member of the declared
   ladder. The moment a continuous formula creeps in, prices stop being explicable and stop
   being comparable across packs.
3. The function is TOTAL. Every tier × market combination returns a price, including the
   empty-string defaults that every pre-lane pack carries (models.py Candidate.ambition_tier
   defaults to "") and including values nobody has thought of yet. A KeyError here is a
   publish-time crash on the money path.
4. It is DETERMINISTIC. No clock, no RNG. The same pack priced twice is the same number, or
   the rationale record (D3) is fiction and the price history is unreadable.

The rung NUMBERS are a hypothesis with no willingness-to-pay evidence behind them yet — see
config.yaml listing.pricing and specs/dynamic-pricing-system-2026-08-05.md §8. Changing one is
expected; changing one *by accident* is what this file makes impossible.
"""
from __future__ import annotations

import pytest

from prospector.config import Config
from prospector.models import Candidate, ScoreResult
from prospector.pricing import PriceDecision, price_for

# --- helpers ---------------------------------------------------------------

def _candidate(tier: str = "", market: str = "") -> Candidate:
    return Candidate(title="A test opportunity", ambition_tier=tier, market=market)


def _score(composite: float = 3.5) -> ScoreResult:
    return ScoreResult(scores={}, justification={}, composite=composite)


def _rungs(cfg: Config) -> list[int]:
    return list(cfg.listing["pricing"]["rungs"])


# The golden matrix. Every cell is a deliberate commercial position, not a derived number:
# the tier sets the base rung, and a us-market opportunity earns exactly one rung for
# addressing a larger economy. An unclassified tier ignores market entirely — we know nothing
# about that pack, so market is not evidence either.
GOLDEN: list[tuple[str, str, int]] = [
    # tier          market   expected pence
    ("",            "",      4999),
    ("",            "uk",    4999),
    ("",            "us",    4999),
    ("side_hustle", "",      2999),
    ("side_hustle", "uk",    2999),
    ("side_hustle", "us",    4999),
    ("smb",         "",      4999),
    ("smb",         "uk",    4999),
    ("smb",         "us",    7999),
    ("growth",      "",      7999),
    ("growth",      "uk",    7999),
    ("growth",      "us",    9999),
    # CEILING, not a price cut. The £149.99 and £199.99 rungs were DELETED from
    # `config.yaml listing.pricing.rungs` on 2026-08-15 (founder: "i dont think we should have
    # inventory over 99.99"), leaving a 5-rung ladder whose top is £99.99. `venture` moved to
    # base index 4 with it. The `us` cell is 9999 and not a higher number because the +1 market
    # offset clamps to `last_idx` (= 4): at the top of the ladder there is nothing above to
    # offset into, so all three venture cells land on the ceiling. That collapse is the ceiling
    # working, and this table asserts it rather than the old uncapped ladder.
    ("venture",     "",      9999),
    ("venture",     "uk",    9999),
    ("venture",     "us",    9999),
]


# --- 1. the default must not move ------------------------------------------

def test_unclassified_pack_prices_at_exactly_the_current_catalogue_price(cfg: Config) -> None:
    # Candidate.ambition_tier defaults to "" (models.py) and every pack published before the
    # ambition lanes existed carries it. If this returns anything but 4999, introducing the
    # ladder silently re-prices the back catalogue.
    assert price_for(_candidate(), _score(), cfg).price_pence == 4999


def test_unclassified_pack_ignores_market(cfg: Config) -> None:
    # Market is not a tiebreaker for a pack we cannot classify. Without this the two us-market
    # packs in the live catalogue would move on a segment we have no read on.
    for market in ("", "uk", "us", "de", "us-tx"):
        assert price_for(_candidate(market=market), _score(), cfg).price_pence == 4999


# --- 2. every price is a rung ----------------------------------------------

@pytest.mark.parametrize(("tier", "market", "expected"), GOLDEN)
def test_golden_matrix(cfg: Config, tier: str, market: str, expected: int) -> None:
    assert price_for(_candidate(tier, market), _score(), cfg).price_pence == expected


@pytest.mark.parametrize(("tier", "market", "expected"), GOLDEN)
def test_every_price_is_a_declared_rung(cfg: Config, tier: str, market: str, expected: int) -> None:
    # Guards the failure this ladder exists to prevent: a continuous function that happens to
    # agree with the matrix on these 15 cells and produces £63.41 on the sixteenth.
    decision = price_for(_candidate(tier, market), _score(), cfg)
    assert decision.price_pence in _rungs(cfg)


def test_score_does_not_move_the_price(cfg: Config) -> None:
    # The ladder is SEGMENT-first by design. Letting the composite nudge price is how you get a
    # continuous function wearing a ladder's clothes, and it makes price depend on a number that
    # already has a fail-safe all-zero mode (ScoreResult.score_failed) — a scoring outage would
    # become a pricing outage.
    prices = {price_for(_candidate("growth", "uk"), _score(c), cfg).price_pence
              for c in (0.0, 1.0, 2.5, 3.4, 4.9, 5.0)}
    assert prices == {7999}


# --- 3. totality ------------------------------------------------------------

@pytest.mark.parametrize("tier", ["", "side_hustle", "smb", "growth", "venture", "wildcat", "SMB"])
@pytest.mark.parametrize("market", ["", "uk", "us", "de", "us-tx", "GB"])
def test_is_total_over_every_combination(cfg: Config, tier: str, market: str) -> None:
    # Publishing runs this on the money path. An unrecognised tier or market must degrade to a
    # price, never raise: a new lane added to config.yaml must not take the catalogue down.
    decision = price_for(_candidate(tier, market), _score(), cfg)
    assert isinstance(decision, PriceDecision)
    assert decision.price_pence in _rungs(cfg)


def test_unknown_tier_is_treated_as_unclassified(cfg: Config) -> None:
    # Fail SAFE, not cheap and not expensive: an unrecognised tier is a pack we cannot classify,
    # which is the default case, not the bottom rung.
    assert price_for(_candidate("wildcat", "uk"), _score(), cfg).price_pence == 4999


def test_unknown_market_earns_no_offset(cfg: Config) -> None:
    # A market we have declared no position on must not be guessed at either way.
    assert price_for(_candidate("smb", "de"), _score(), cfg).price_pence == 4999


# --- 4. determinism and provenance -----------------------------------------

def test_is_deterministic(cfg: Config) -> None:
    for tier, market, expected in GOLDEN:
        first = price_for(_candidate(tier, market), _score(), cfg)
        second = price_for(_candidate(tier, market), _score(), cfg)
        assert first.price_pence == second.price_pence == expected
        assert first.rung == second.rung


def test_decision_carries_its_own_justification(cfg: Config) -> None:
    # PATCH /internal/catalog/{id}/price refuses a change with no Reason and no Actor, because a
    # price that moved with no stated cause is indistinguishable from a bug. The decision has to
    # arrive carrying the material for that Reason, or the caller invents one.
    decision = price_for(_candidate("venture", "us"), _score(), cfg)
    assert decision.price_pence == 9999   # the £99.99 ceiling — see GOLDEN above
    assert decision.rung
    assert decision.rationale
    assert decision.segment["ambition_tier"] == "venture"
    assert decision.segment["market"] == "us"


def test_does_not_mutate_its_inputs(cfg: Config) -> None:
    candidate = _candidate("smb", "us")
    before = (candidate.ambition_tier, candidate.market, dict(cfg.listing))
    price_for(candidate, _score(), cfg)
    assert (candidate.ambition_tier, candidate.market, dict(cfg.listing)) == before


# --- 5. the ladder itself ---------------------------------------------------

def test_rungs_are_ascending_and_unique(cfg: Config) -> None:
    rungs = _rungs(cfg)
    assert rungs == sorted(set(rungs)), "a duplicated or out-of-order rung makes an offset meaningless"


def test_default_rung_index_resolves_to_the_current_price(cfg: Config) -> None:
    pricing = cfg.listing["pricing"]
    assert _rungs(cfg)[pricing["default_rung_index"]] == cfg.listing["price_pence"] == 4999


def test_an_out_of_range_rung_index_in_config_degrades_instead_of_crashing(cfg: Config) -> None:
    # The ladder's indices live in config.yaml, so putting one out of range is a DATA edit that
    # never goes near a code review or this suite. It must degrade to the nearest real rung: an
    # IndexError here would be a crash on the publish path caused by a one-character typo.
    import copy

    broken = copy.deepcopy(cfg)
    broken.listing["pricing"]["tier_rung_index"]["smb"] = 99
    decision = price_for(_candidate("smb", "us"), _score(), broken)
    assert decision.price_pence == _rungs(cfg)[-1]
    assert decision.rationale

    broken.listing["pricing"]["tier_rung_index"]["smb"] = -99
    assert price_for(_candidate("smb", ""), _score(), broken).price_pence == _rungs(cfg)[0]


def test_the_dead_price_signal_is_gone() -> None:
    # score.listing_price_signal was a second, unused pricing concept sitting next to the real
    # one (zero callers repo-wide). Leaving it is how the wrong one gets wired up later.
    import prospector.score as score

    assert not hasattr(score, "listing_price_signal")

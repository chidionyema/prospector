"""Price a Candidate against the L1 ladder declared in config.yaml.

Price is a RUNG on a fixed ladder, never an arithmetically derived number. The ladder is
segment-first (ambition_tier × market) and ignores the composite score on purpose: a scoring
outage would otherwise become a pricing outage, and a continuous function wearing a
ladder's clothes is how a £63.41 sneaks onto the money path.

The default (unclassified) rung is the existing catalogue price: a ladder that silently
moves legacy packs the moment it lands is a catalogue-wide incident, not a feature.
"""
from __future__ import annotations

from dataclasses import dataclass

from prospector.config import Config
from prospector.models import Candidate, ScoreResult


@dataclass(frozen=True)
class PriceDecision:
    """The result of pricing one Candidate.

    Carries the rung chosen, the segment inputs that decided it, and a rationale the
    money-path caller can drop into the ``Reason`` field of
    ``PATCH /internal/catalog/{id}/price``, which refuses a price change with no
    stated cause — a price that moved with no Reason is indistinguishable from a bug.
    """
    price_pence: int
    rung: str
    segment: dict[str, str]
    rationale: str


def price_for(candidate: Candidate, score: ScoreResult, cfg: Config) -> PriceDecision:
    """Resolve a Candidate to a rung on the L1 ladder.

    The tier sets the base rung; a ``us``-market opportunity earns exactly one rung of
    offset because it addresses a larger economy. An unclassified tier — empty string or
    one not declared in ``tier_rung_index`` — falls back to ``default_rung_index`` and
    market is ignored, because market is not evidence for a pack we cannot classify. An
    unknown market earns no offset either; guessing at a jurisdiction we have declared no
    position on is a failure mode, not a feature.

    ``score`` is accepted for interface stability and is deliberately NOT consulted: the
    composite has a fail-safe all-zero mode (``ScoreResult.score_failed``), and tying price
    to it would turn a scoring outage into a pricing outage.
    """
    pricing = cfg.listing["pricing"]
    rungs: list[int] = list(pricing["rungs"])
    tier_rung_index: dict[str, int] = dict(pricing["tier_rung_index"])
    market_rung_offset: dict[str, int] = dict(pricing["market_rung_offset"])
    default_idx: int = int(pricing["default_rung_index"])

    tier = candidate.ambition_tier
    market = candidate.market
    segment: dict[str, str] = {"ambition_tier": tier, "market": market}

    last_idx = len(rungs) - 1

    # Unclassified: empty tier, or one the ladder has not been told about. We hold at the
    # default rung rather than guessing, because guessing silently re-prices the back
    # catalogue the moment the ladder lands. Market is not evidence for a pack we cannot
    # classify, so it earns no offset either.
    if tier == "" or tier not in tier_rung_index:
        rung_idx = max(0, min(last_idx, default_idx))
        price_pence = rungs[rung_idx]
        rung = f"default (unclassified) at rung index {rung_idx}"
        rationale = (
            f"Unclassified pack (ambition_tier={tier!r}, market={market!r}) held at the "
            f"default rung of {price_pence}p because the tier is empty or not declared "
            f"on the ladder; market is not evidence for an unclassified pack, so it is "
            f"ignored."
        )
        return PriceDecision(
            price_pence=price_pence,
            rung=rung,
            segment=segment,
            rationale=rationale,
        )

    # Classified: tier sets the base rung, market adds an offset. An unknown market earns
    # zero offset rather than raising — declaring no position is the safe default.
    # base_idx is clamped BEFORE it is used, not just when it is added to. It is read from
    # config, so a typo (`side_hustle: 99`) is a data edit, not a code change — and an
    # unclamped read below when building the rationale would turn that into an IndexError on
    # the publish path. Degrade to the nearest real rung instead of taking the catalogue down.
    base_idx = max(0, min(last_idx, tier_rung_index[tier]))
    offset = market_rung_offset.get(market, 0)
    rung_idx = max(0, min(last_idx, base_idx + offset))
    price_pence = rungs[rung_idx]
    rung = f"{tier} at rung index {rung_idx} (base {base_idx}, offset {offset})"
    rationale = (
        f"Tier {tier!r} sets the base rung at index {base_idx} ({rungs[base_idx]}p); "
        f"market {market!r} adds an offset of {offset} rung(s), landing at index "
        f"{rung_idx} ({price_pence}p)."
    )
    return PriceDecision(
        price_pence=price_pence,
        rung=rung,
        segment=segment,
        rationale=rationale,
    )

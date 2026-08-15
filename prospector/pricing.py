"""Price a Candidate against the L1 ladder declared in config.yaml.

Price is a RUNG on a fixed ladder, never an arithmetically derived number. The ladder is
segment-first (ambition_tier × market) and ignores the composite score on purpose: a scoring
outage would otherwise become a pricing outage, and a continuous function wearing a
ladder's clothes is how a £63.41 sneaks onto the money path.

The default (unclassified) rung is the existing catalogue price: a ladder that silently
moves legacy packs the moment it lands is a catalogue-wide incident, not a feature.

WHICH rung is chosen changed on 2026-08-15. The founder's standing objection to this
module was never the trailing digit — it was "a user should be able to intuit why one
pack is priced more or less than another". Measured that day against the live catalogue
(59 rows, ``GET https://api.mumchimp.com/catalog``), price ran BACKWARDS against the only
quantitative field a buyer can see on a row, ``sourceCount``:

    £29.99 -> 36.5 mean sources    £79.99 -> 40.7
    £49.99 -> 31.0                 £149.99 -> 28.6   <- dearest tier, fewest sources

18 of 58 adjacent pairs sorted by sourceCount had the dearer pack carrying fewer sources.
So the rung is now selected by ``listing.pricing.source_count_bands`` whenever the caller
knows the count, and price is a non-decreasing step function of it BY CONSTRUCTION. The
tier ladder remains, unchanged, as the fallback for every caller that does not know the
count (``verify._check_question`` asks during the moat, before a dossier exists).

``ambition_tier`` was rejected as the primary selector for one reason: it is invisible to
the buyer, so no price it produces can be intuited from the page.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from prospector.config import LISTING_DEFAULTS, Config
from prospector.models import Candidate, PriceAnchor, ScoreResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceDecision:
    """The result of pricing one Candidate.

    Carries the rung chosen, the segment inputs that decided it, and a rationale the
    money-path caller can drop into the ``Reason`` field of
    ``PATCH /internal/catalog/{id}/price``, which refuses a price change with no
    stated cause — a price that moved with no Reason is indistinguishable from a bug.

    ``evidence`` is the C3 anchor summary when retrieved comparables actually moved the
    rung, and ``None`` otherwise. It is the citation trail for a price change: which
    passages, which domains, what median. A price that moved with no ``evidence`` moved on
    the ladder alone, and the rationale says so.
    """
    price_pence: int
    rung: str
    segment: dict[str, str]
    rationale: str
    evidence: Optional[dict[str, Any]] = None


def _anchor_adjustment(rung_idx: int, rungs: list[int],
                       anchors: list[PriceAnchor], cfg: Config
                       ) -> tuple[int, Optional[dict[str, Any]], str]:
    """Move the rung at most ONE step toward retrieved comparables, or not at all.

    Returns ``(new_idx, evidence_or_None, rationale_suffix)``.

    Three deliberate limits, each answering a specific way this could go wrong:

    * **One rung, maximum.** A run of comparables from an adjacent-but-different market
      (enterprise SaaS pages surfacing for a side-hustle pack) would otherwise walk a price
      from £29 to £199 in a single automated act. One rung keeps every move small enough to
      be caught by the next human who reads the price history.
    * **It must clear the neighbouring rung outright.** Not "closer to it" — at or beyond
      it. Rungs exist so crossing one is a decision; a median that merely leans upward is
      not evidence that the ladder is wrong.
    * **Never on an unclassified pack.** Holding the whole back catalogue at 4900 is the
      L1 ladder's central safety property (see ``price_for``); comparables must not become
      the side door that re-prices it.
    """
    from prospector.price_comparables import anchor_evidence

    ev = anchor_evidence(anchors, cfg)
    if ev is None:
        return rung_idx, None, ""
    median = int(ev["median_pence"])
    last_idx = len(rungs) - 1
    if rung_idx < last_idx and median >= rungs[rung_idx + 1]:
        new_idx = rung_idx + 1
        direction = "above"
    elif rung_idx > 0 and median <= rungs[rung_idx - 1]:
        new_idx = rung_idx - 1
        direction = "below"
    else:
        return rung_idx, None, (
            f" Retrieved comparables (median {median}p from {ev['n']} anchor(s) across "
            f"{len(ev['domains'])} domain(s)) did not clear an adjacent rung, so the ladder "
            f"rung stands.")
    suffix = (
        f" Adjusted one rung {'up' if direction == 'above' else 'down'} to index {new_idx} "
        f"({rungs[new_idx]}p): retrieved comparables have a median of {median}p, which is at "
        f"or {direction} the neighbouring rung. Evidence: {ev['n']} cited anchor(s) across "
        f"{len(ev['domains'])} domain(s) ({', '.join(ev['domains'])}).")
    return new_idx, ev, suffix


def _usable_bands(pricing: dict[str, Any], rungs: list[int]) -> Optional[list[int]]:
    """The declared ``source_count_bands``, or None with a LOUD log if they are unusable.

    Silence is the failure mode this guards: a malformed band list that quietly fell back
    to the tier ladder would re-introduce the inversion while every rationale still read
    as though depth had priced the pack. So each rejection says which rule it broke.

    The contract is exactly ``len(rungs) - 1`` strictly-increasing lower edges — edge *i*
    is the smallest source count that reaches rung *i+1*. Fewer or more edges than rungs
    can hold is a config edit that cannot be interpreted, not one to guess at.
    """
    raw = pricing.get("source_count_bands")
    if not raw:
        return None
    try:
        bands = [int(b) for b in raw]
    except (TypeError, ValueError):
        logger.error(
            f"listing.pricing.source_count_bands is not a list of integers ({raw!r}); "
            f"falling back to the tier ladder — packs will NOT be priced by cited depth.")
        return None
    if len(bands) != len(rungs) - 1:
        logger.error(
            f"listing.pricing.source_count_bands has {len(bands)} edge(s) but there are "
            f"{len(rungs)} rung(s); it must have exactly {len(rungs) - 1}. Falling back to "
            f"the tier ladder — packs will NOT be priced by cited depth.")
        return None
    if any(b2 <= b1 for b1, b2 in zip(bands, bands[1:])):
        logger.error(
            f"listing.pricing.source_count_bands is not strictly increasing ({bands!r}), so "
            f"it cannot define a monotonic ladder; falling back to the tier ladder.")
        return None
    return bands


def _band_index(source_count: int, bands: list[int]) -> int:
    """How many band edges this source count has cleared. Non-decreasing in ``source_count``
    by construction — that property is the entire point of this function, and
    ``tests/unit/test_pricing_monotonic.py`` pins it over the full live range."""
    return sum(1 for edge in bands if source_count >= edge)


def price_for(candidate: Candidate, score: Optional[ScoreResult], cfg: Config,
              anchors: Optional[list[PriceAnchor]] = None,
              source_count: Optional[int] = None) -> PriceDecision:
    """Resolve a Candidate to a rung on the L1 ladder.

    The tier sets the base rung; a ``us``-market opportunity earns exactly one rung of
    offset because it addresses a larger economy. An unclassified tier — empty string or
    one not declared in ``tier_rung_index`` — falls back to ``default_rung_index`` and
    market is ignored, because market is not evidence for a pack we cannot classify. An
    unknown market earns no offset either; guessing at a jurisdiction we have declared no
    position on is a failure mode, not a feature.

    ``score`` is accepted for interface stability and is deliberately NOT consulted: the
    composite has a fail-safe all-zero mode (``ScoreResult.score_failed``), and tying price
    to it would turn a scoring outage into a pricing outage. It is typed ``Optional``
    because that unconsultedness has a second caller now: ``verify._check_question`` needs
    the rung DURING the moat, which runs long before ``run.py:465`` scores anything. Passing
    ``None`` is honest; fabricating a zeroed ``ScoreResult`` to satisfy a type would not be.

    ``source_count`` is the number of distinct cited sources behind the pack — the same
    integer ``bridge._trust_fields`` publishes as the row's ``sourceCount``, taken from the
    same helper so the price and the number the buyer reads next to it cannot drift. When
    it is supplied AND ``listing.pricing.source_count_bands`` is declared, it selects the
    rung outright and neither tier nor market is consulted. That exclusivity is not an
    oversight: any second input breaks monotonicity, because two packs with the same count
    would then sit on different rungs and some pair sorted by depth would run backwards
    again. Tier and market stay in the rationale as context, never as arithmetic.

    Bands apply to UNCLASSIFIED packs too, unlike the tier ladder's market offset. A tier
    is a judgement we may not have made; a source count is a fact about the pack in hand.

    ``anchors`` are the C3 ``price_comparables`` results for this candidate. They can move
    the rung by at most one step, and ONLY when config sets
    ``listing.pricing.comparables.rung_adjust_enabled`` — which defaults to false, so
    landing this check changes no price anywhere until someone deliberately turns it on.
    Retrieving evidence and acting on it are two decisions, and conflating them is how a
    catalogue re-prices itself the day a feature merges.
    """
    listing = cfg.listing or {}
    pricing = listing.get("pricing") or {}
    tier = candidate.ambition_tier
    market = candidate.market
    segment: dict[str, str] = {"ambition_tier": tier, "market": market}

    # No ladder declared, or one declared incompletely. Hold at the flat catalogue price
    # rather than raising: this function is on the PUBLISH path (bridge.py mints the
    # provider Price from it), so a config that predates the ladder — or a partial one — must
    # degrade to today's behaviour, not take publishing down. A KeyError here would be a
    # data edit crashing the money rail, which is the exact failure the D1 review caught in
    # the rationale string and the same shape of bug.
    rungs: list[int] = [int(r) for r in (pricing.get("rungs") or [])]
    if not rungs or pricing.get("default_rung_index") is None:
        # The fallback is the DECLARED default, not a second literal: `cfg.listing` normally
        # carries `price_pence` (config.yaml wins, merged in `config.load`), and a cfg built
        # by hand — `tests/unit/test_payer_solvency_price.py` — degrades to that same single
        # source rather than to a number that can silently drift from it (finding #20).
        flat = int(listing.get("price_pence", LISTING_DEFAULTS["price_pence"]))
        return PriceDecision(
            price_pence=flat,
            rung="flat (no ladder declared)",
            segment=segment,
            rationale=(
                f"config listing.pricing declares no usable ladder "
                f"(rungs={pricing.get('rungs')!r}, "
                f"default_rung_index={pricing.get('default_rung_index')!r}); "
                f"holding at the flat catalogue price of {flat}p."
            ),
        )

    tier_rung_index: dict[str, int] = dict(pricing.get("tier_rung_index") or {})
    market_rung_offset: dict[str, int] = dict(pricing.get("market_rung_offset") or {})
    default_idx: int = int(pricing["default_rung_index"])

    last_idx = len(rungs) - 1

    # ---- Depth ladder (2026-08-15). The rung the BUYER can derive from the page. ----
    # This runs before the tier ladder and returns outright, so when a caller knows the
    # source count there is exactly one selector and price is a non-decreasing step
    # function of the one number on the row. `_anchor_adjustment` is deliberately NOT
    # reachable from here: a per-pack nudge of ±1 rung is precisely what re-introduces the
    # inversion this ladder exists to remove — a 30-source pack nudged up would outprice a
    # 45-source one. Anchors keep their evidentiary job (they are retrieved, cited and
    # recorded); they no longer get a vote on the rung.
    bands = _usable_bands(pricing, rungs)
    if source_count is not None and bands is not None:
        rung_idx = max(0, min(last_idx, _band_index(int(source_count), bands)))
        price_pence = rungs[rung_idx]
        lower = ([0] + bands)[rung_idx]
        upper = (bands + [None])[rung_idx]  # type: ignore[list-item]
        span = f"{lower}+" if upper is None else f"{lower}–{upper - 1}"
        if anchors and bool((pricing.get("comparables") or {}).get("rung_adjust_enabled",
                                                                   False)):
            logger.info(
                f"pricing: {len(list(anchors))} anchor(s) present and rung_adjust_enabled is "
                f"on, but this pack was priced by cited depth; anchors do not move a depth "
                f"rung (monotonicity). They remain recorded as evidence.",
                extra={"candidate_id": getattr(candidate, "candidate_id", None)})
        return PriceDecision(
            price_pence=price_pence,
            rung=f"depth band {rung_idx + 1} of {len(rungs)} ({span} sources)",
            segment={**segment, "priced_by": "source_count",
                     "source_count": str(int(source_count))},
            rationale=(
                f"Priced by cited depth: this pack cites {int(source_count)} distinct "
                f"sources, which falls in band {rung_idx + 1} of {len(rungs)} "
                f"({span} sources), so it lists at {price_pence}p. Band edges are "
                f"{bands} sources (config listing.pricing.source_count_bands). Every pack "
                f"citing more sources costs the same or more; tier {tier!r} and market "
                f"{market!r} are recorded but do not move the price, because a buyer "
                f"cannot see either one."
            ),
        )

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
    ladder_idx = rung_idx
    rationale = (
        f"Tier {tier!r} sets the base rung at index {base_idx} ({rungs[base_idx]}p); "
        f"market {market!r} adds an offset of {offset} rung(s), landing at index "
        f"{rung_idx} ({rungs[rung_idx]}p)."
    )

    evidence: Optional[dict[str, Any]] = None
    comparables = (pricing.get("comparables") or {})
    if anchors and bool(comparables.get("rung_adjust_enabled", False)):
        rung_idx, evidence, suffix = _anchor_adjustment(
            ladder_idx, rungs, list(anchors), cfg)
        rationale += suffix

    price_pence = rungs[rung_idx]
    rung = f"{tier} at rung index {rung_idx} (base {base_idx}, offset {offset})"
    return PriceDecision(
        price_pence=price_pence,
        rung=rung,
        segment=segment,
        rationale=rationale,
        evidence=evidence,
    )

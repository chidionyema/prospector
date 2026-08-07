"""Auto-classify a candidate into its natural ambition tier (Part 14 — multi-lane).

The two axes are orthogonal: GENERATION fans out across tiers for coverage; this step
CONFIRMS each idea is vetted by the bar of the tier it actually belongs to. If generation
proposed a "side hustle" that is really a venture (or vice versa), the classifier re-homes it
so the right gates/thresholds apply. One cheap call on the FAST/query model — never the verdict
model. Cross-lane invariant (source-or-die grounding) is untouched: classification only routes
which gate set runs, it never rules on evidence.

Keep-biased like prescreen: on ANY failure (parse error, unknown tier, exception) we KEEP the
tier the candidate was generated under. We never crash and never silently drop a candidate.
"""
from __future__ import annotations

import json

from .config import Config
from .models import Candidate
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency


def _allowed_tiers(cfg: Config) -> list[str]:
    """The tiers the classifier may choose from = the run's active lanes (fallback: the
    single active_lane, else all configured lanes)."""
    if cfg.active_lanes:
        return [str(t) for t in cfg.active_lanes]
    if cfg.active_lane:
        return [cfg.active_lane]
    return [str(t) for t in cfg.lanes.keys()]


@track_latency(name="classify_tier")
def classify_tier(op: Operator, cand: Candidate, cfg: Config) -> str:
    """Return the ambition tier this candidate naturally belongs to (one of the allowed
    tiers). Deterministic fallback to the generated tier (cand.ambition_tier) on any failure
    or an unknown/out-of-set result. Never raises.

    A candidate with NO generated tier gets `""` back on failure, not a tier. Keep-biased means
    keep what the candidate had; one that had nothing has nothing to keep, and the caller — not
    this function — decides what an unresolved classification means.
    """
    allowed = _allowed_tiers(cfg)
    # NOT `cand.ambition_tier or allowed[0]`. That spelling stood here until 2026-08-06 and
    # turned every failure on a tier-less candidate into a confident "side_hustle":
    #
    #   cand = Candidate.from_dict({"title": "legacy pack", "ambition_tier": ""})
    #   classify_tier(BrainThatRaises(), cand, cfg)   -> 'side_hustle'
    #   classify_tier(BrainReturningJunk(), cand, cfg) -> 'side_hustle'
    #   classify_tier(BrainReturningEmpty(), cand, cfg) -> 'side_hustle'
    #
    # ...logging "keeping generated tier 'side_hustle'", which was never true: nothing generated
    # it. `allowed[0]` is not a keep, it is a guess whose value is decided by config ORDER
    # (`active_lanes[0]`). The existing tests never saw it because they all classify a candidate
    # that already has a tier. It matters because 97 of 154 PASS dossiers carry an empty tier,
    # and `config.yaml listing.pricing` maps side_hustle -> rung 1 -> 2900 against the empty
    # tier's default rung 2 -> 4900: a brain being down for the length of a backfill would have
    # re-priced the untiered back catalogue DOWN by a third, on no evidence at all. That is the
    # failure `pricing.py:146` already refuses by hand ("guessing silently re-prices the back
    # catalogue"); the guess must not sneak in one layer up.
    fallback = cand.ambition_tier
    if not allowed:
        return fallback

    try:
        system, user = render("classify",
                              allowed_tiers=", ".join(allowed),
                              candidate_json=json.dumps(cand.to_dict()))
        # temperature=0.0 explicitly. `complete_json` defaults to 0.7 (operator.py:115) — a
        # creative-sampling setting, correct for generation and wrong for a routing decision
        # that is supposed to be a property of the candidate. It is not sufficient for
        # reproducibility (minimax still returned different tiers across repeat runs at 0.0 for
        # 4 of 6 candidates, 2026-08-06) but it removes the one source of variance we control,
        # and it stops the same dossier classifying differently on two consecutive runs of the
        # same brain. Matters because this field feeds the L1 price ladder via
        # `listing.pricing.tier_rung_index`: at 0.7 the rung was partly a dice roll.
        data = op.complete_json(system, user, temperature=0.0)
    except Exception as e:  # noqa: BLE001 — keep-biased: any failure keeps the generated tier
        logger.warning(f"classify_tier failed for {cand.title!r}: {e}; keeping {fallback!r}",
                       extra={"candidate_id": cand.candidate_id, "error": str(e)})
        return fallback

    tier = ""
    if isinstance(data, dict):
        tier = str(data.get("tier", "") or "").strip()

    if tier not in allowed:
        logger.info(f"classify_tier: {tier!r} not in {allowed} for {cand.title!r}; "
                    f"keeping generated tier {fallback!r}",
                    extra={"candidate_id": cand.candidate_id})
        return fallback

    if tier != cand.ambition_tier:
        logger.info(f"classify_tier: re-homed {cand.title!r} {cand.ambition_tier!r} → {tier!r}",
                    extra={"candidate_id": cand.candidate_id})
    return tier

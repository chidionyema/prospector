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
from typing import Optional

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
    """
    allowed = _allowed_tiers(cfg)
    fallback = cand.ambition_tier or (allowed[0] if allowed else "")
    if not allowed:
        return fallback

    try:
        system, user = render("classify",
                              allowed_tiers=", ".join(allowed),
                              candidate_json=json.dumps(cand.to_dict()))
        data = op.complete_json(system, user)
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

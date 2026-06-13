"""Ranking of survivors (Part 4). Score six axes 0-5, composite = Σ(score×weight).
Automatability is a top-weighted axis and drives pricing (Part 6). Pure maths for the
composite (unit-testable, no model); the per-axis scores come from the grounded score
prompt over the verified claims only.
"""
from __future__ import annotations

import json
from typing import Optional

from .config import Config
from .models import SCORE_AXES, Candidate, CheckResult, ScoreResult
from .operator import Operator
from .prompts import render


def composite(scores: dict[str, int], weights: dict[str, float]) -> float:
    """Exact weighted sum. Missing axes count as 0; unknown axes ignored."""
    return round(sum(float(scores.get(ax, 0)) * float(weights.get(ax, 0.0))
                     for ax in weights), 4)


def score_candidate(op: Operator, cfg: Config, cand: Candidate,
                    checks: list[CheckResult]) -> ScoreResult:
    claims = [{"check": c.check_name, "verdict": c.verdict.value,
               "confidence": c.confidence, "rationale": c.rationale,
               "citations": c.citations} for c in checks]
    system, user = render("score", candidate_json=json.dumps(cand.to_dict()),
                          claims_json=json.dumps(claims))
    try:
        data = op.complete_json(system, user, temperature=0.0)
        raw = data.get("scores", {}) or {}
        scores = {ax: int(round(float(raw.get(ax, 0) or 0))) for ax in SCORE_AXES}
        scores = {ax: max(0, min(5, v)) for ax, v in scores.items()}
        justification = {ax: str((data.get("justification", {}) or {}).get(ax, ""))
                         for ax in SCORE_AXES}
    except Exception:
        scores = {ax: 0 for ax in SCORE_AXES}
        justification = {ax: "scoring failed; fail-safe zero" for ax in SCORE_AXES}
    return ScoreResult(scores=scores, justification=justification,
                       composite=composite(scores, cfg.weights))


def passes_composite(score: Optional[ScoreResult], cfg: Config) -> bool:
    return bool(score) and score.composite >= cfg.thresholds.min_composite_to_pass


def listing_price_signal(score: ScoreResult, cfg: Config) -> float:
    """Price tracks composite, automatability weighted hardest (Part 6)."""
    premium = cfg.listing.get("pricing", {}).get("premium_axis", "automatability")
    return round(score.composite + 0.5 * float(score.scores.get(premium, 0)), 4)

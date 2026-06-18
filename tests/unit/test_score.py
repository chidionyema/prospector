"""Unit tests for prospector.score (Part 4 ranking).

Tests the pure-math composite() function and the passes_composite predicate.
No model calls required — composite is pure arithmetic.
"""
from __future__ import annotations

import pytest
from prospector.config import load_config, Config
from prospector.models import SCORE_AXES
from prospector.score import composite, passes_composite, ScoreResult


@pytest.fixture
def cfg() -> Config:
    return load_config()


# ---------------------------------------------------------------------------
# composite() — exact weighted sum
# ---------------------------------------------------------------------------

def test_composite_exact_hand_calculation(cfg):
    """Hand-verify one example using the real weights from config.yaml.

    weights: pain_acuity=0.20, money_provability=0.20, automatability=0.20,
             distribution=0.15, defensibility=0.15, build_feasibility=0.10

    scores: pain_acuity=4, money_provability=3, automatability=5,
            distribution=2, defensibility=3, build_feasibility=4

    Expected = 4*0.20 + 3*0.20 + 5*0.20 + 2*0.15 + 3*0.15 + 4*0.10
             = 0.80 + 0.60 + 1.00 + 0.30 + 0.45 + 0.40
             = 3.55
    """
    scores = {
        "pain_acuity": 4,
        "money_provability": 3,
        "automatability": 5,
        "distribution": 2,
        "defensibility": 3,
        "build_feasibility": 4,
    }
    weights = cfg.weights
    result = composite(scores, weights)
    assert result == pytest.approx(3.55, abs=1e-4)


def test_composite_all_zeros():
    weights = {"pain_acuity": 0.20, "automatability": 0.20}
    scores = {"pain_acuity": 0, "automatability": 0}
    assert composite(scores, weights) == 0.0


def test_composite_all_max():
    """All axes at 5 with weights summing to 1.0 => composite = 5.0."""
    weights = {ax: 1.0 / len(SCORE_AXES) for ax in SCORE_AXES}
    scores = {ax: 5 for ax in SCORE_AXES}
    result = composite(scores, weights)
    assert result == pytest.approx(5.0, abs=1e-3)


def test_composite_missing_axis_counts_as_zero():
    weights = {"pain_acuity": 0.5, "automatability": 0.5}
    scores = {"pain_acuity": 4}  # automatability missing
    result = composite(scores, weights)
    assert result == pytest.approx(4 * 0.5, abs=1e-4)


def test_composite_unknown_axis_ignored():
    weights = {"pain_acuity": 0.5}
    scores = {"pain_acuity": 4, "made_up_axis": 5}
    result = composite(scores, weights)
    # made_up_axis not in weights -> ignored; result = 4 * 0.5
    assert result == pytest.approx(2.0, abs=1e-4)


# ---------------------------------------------------------------------------
# automatability ranks higher (all else equal, weight 0.20)
# ---------------------------------------------------------------------------

def test_higher_automatability_gives_higher_composite(cfg):
    """Two candidates identical except automatability: higher automatability
    must produce a strictly higher composite (automatability weight = 0.20)."""
    base_scores = {
        "pain_acuity": 3,
        "money_provability": 3,
        "distribution": 3,
        "defensibility": 3,
        "build_feasibility": 3,
    }
    low_auto = dict(base_scores, automatability=2)
    high_auto = dict(base_scores, automatability=4)

    result_low = composite(low_auto, cfg.weights)
    result_high = composite(high_auto, cfg.weights)
    assert result_high > result_low


# ---------------------------------------------------------------------------
# passes_composite
# ---------------------------------------------------------------------------

def test_passes_composite_above_threshold(cfg):
    threshold = cfg.thresholds.min_composite_to_pass  # 3.2
    score = ScoreResult(
        scores={ax: 4 for ax in SCORE_AXES},
        justification={ax: "" for ax in SCORE_AXES},
        composite=threshold + 0.5,
    )
    assert passes_composite(score, cfg) is True


def test_passes_composite_below_threshold(cfg):
    threshold = cfg.thresholds.min_composite_to_pass
    score = ScoreResult(
        scores={ax: 1 for ax in SCORE_AXES},
        justification={ax: "" for ax in SCORE_AXES},
        composite=threshold - 0.5,
    )
    assert passes_composite(score, cfg) is False


def test_passes_composite_at_exact_threshold(cfg):
    threshold = cfg.thresholds.min_composite_to_pass
    score = ScoreResult(
        scores={ax: 3 for ax in SCORE_AXES},
        justification={ax: "" for ax in SCORE_AXES},
        composite=threshold,
    )
    assert passes_composite(score, cfg) is True


def test_passes_composite_none_score(cfg):
    assert passes_composite(None, cfg) is False


# ---------------------------------------------------------------------------
# P1-9 — score_failed flag distinguishes a scoring outage from a real 0/5
# ---------------------------------------------------------------------------

def test_score_failed_flag_set_when_scorer_raises(cfg):
    """When the scorer operator errors, the all-zero fail-safe must carry
    score_failed=True so the publish gate can tell it from a genuine low score."""
    from prospector.score import score_candidate
    from prospector.models import Candidate

    class _Boom:
        def complete_json(self, *a, **k):
            raise RuntimeError("scorer down")

    cand = Candidate(title="t", one_liner="o", hypothesis="h", who_pays="x")
    result = score_candidate(_Boom(), cfg, cand, checks=[])
    assert result.score_failed is True
    assert all(v == 0 for v in result.scores.values())


def test_score_failed_flag_false_on_success(cfg):
    """A scorer that returns valid scores yields score_failed=False."""
    from prospector.score import score_candidate
    from prospector.models import Candidate

    class _Ok:
        def complete_json(self, *a, **k):
            return {"scores": {ax: 3 for ax in SCORE_AXES},
                    "justification": {ax: "ok" for ax in SCORE_AXES}}

    cand = Candidate(title="t", one_liner="o", hypothesis="h", who_pays="x")
    result = score_candidate(_Ok(), cfg, cand, checks=[])
    assert result.score_failed is False

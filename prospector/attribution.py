"""Causal attribution for Prospector's self-improvement adaptations.

When the system modifies itself, this module measures whether the change
actually helped or hurt — and by how much. Uses paired comparison of runs
before and after each change to attribute effects with confidence.

Part of the production-grade self-improvement infrastructure (Priority 4).
"""

import math
from pathlib import Path

from .metrics_store import MetricsStore
from .self_modify import SelfModificationLog


def measure_effect(
    change_id: str,
    metrics_store: MetricsStore,
    window_before: int = 20,
    window_after: int = 20,
) -> dict:
    """Measure the effect of a self-modification by comparing runs before vs after.

    Uses Welch's t-test (unequal variance) to determine if the change had a
    statistically significant effect on yield, diversity, and health.

    Args:
        change_id: The change to evaluate.
        metrics_store: MetricsStore with run history.
        window_before: Number of runs before the change to use as baseline.
        window_after: Number of runs after the change to compare against.

    Returns:
        Dict with effect_size, direction, confidence, p_value, and sample_sizes
        for each metric (yield, diversity, health).
    """
    # Get the change timestamp
    mod_log_path = metrics_store.db_path.parent / "self_modifications.db"
    if mod_log_path.is_file():
        mod_log = SelfModificationLog(mod_log_path)
        change = mod_log.get(change_id)
        if not change:
            return _no_data_result(change_id, "Change not found")
        change_ts = change.get("timestamp", "")
    else:
        return _no_data_result(change_id, "No modification log found")

    if not change_ts:
        return _no_data_result(change_id, "Change has no timestamp")

    # Get all runs from metrics store
    trend = metrics_store.trend(window=window_before + window_after + 50)
    if trend["summary"]["total_runs"] < 10:
        return _no_data_result(change_id, "Insufficient run data")

    # Split runs into before/after based on change timestamp
    yields = trend["yield_trend"]
    diversities = trend["diversity_trend"]
    healths = trend["health_trend"]

    before_yield = []
    after_yield = []
    before_div = []
    after_div = []
    before_health = []
    after_health = []

    for ts, y in yields:
        if ts < change_ts:
            before_yield.append(y)
        else:
            after_yield.append(y)

    for ts, d in diversities:
        if ts < change_ts:
            before_div.append(d)
        else:
            after_div.append(d)

    for ts, h in healths:
        if ts < change_ts:
            before_health.append(h)
        else:
            after_health.append(h)

    # Trim to window sizes
    before_yield = before_yield[-window_before:] if before_yield else []
    after_yield = after_yield[:window_after] if after_yield else []
    before_div = before_div[-window_before:] if before_div else []
    after_div = after_div[:window_after] if after_div else []
    before_health = before_health[-window_before:] if before_health else []
    after_health = after_health[:window_after] if after_health else []

    if len(before_yield) < 3 or len(after_yield) < 3:
        return _no_data_result(change_id, "Insufficient samples for comparison")

    # Compute effects
    yield_effect = _compute_effect(before_yield, after_yield, "yield_rate")
    div_effect = _compute_effect(before_div, after_div, "diversity_score")
    health_effect = _compute_effect(before_health, after_health, "health_score")

    # Determine overall direction
    directions = [
        e["direction"]
        for e in [yield_effect, div_effect, health_effect]
        if e["direction"] != "neutral" and e.get("sufficient_samples", True)
    ]
    if not directions:
        overall_direction = "neutral"
    elif directions.count("positive") > directions.count("negative"):
        overall_direction = "positive"
    elif directions.count("negative") > directions.count("positive"):
        overall_direction = "negative"
    else:
        overall_direction = "neutral"

    # Determine if significant (any metric with p < 0.1)
    significant = any(
        e.get("p_value", 1.0) < 0.1 and e.get("sufficient_samples", True)
        for e in [yield_effect, div_effect, health_effect]
    )

    return {
        "change_id": change_id,
        "direction": overall_direction,
        "significant": significant,
        "metrics": {
            "yield": yield_effect,
            "diversity": div_effect,
            "health": health_effect,
        },
        "sample_sizes": {
            "before": len(before_yield),
            "after": len(after_yield),
        },
        "recommendation": _recommendation(overall_direction, significant),
    }


def _compute_effect(
    before: list[float],
    after: list[float],
    metric_name: str,
) -> dict:
    """Compute effect size, direction, and Welch's t-test p-value."""
    n1, n2 = len(before), len(after)
    if n1 < 2 or n2 < 2:
        return {
            "direction": "neutral",
            "effect_size": 0.0,
            "p_value": 1.0,
            "mean_before": 0.0,
            "mean_after": 0.0,
            "sufficient_samples": False,
            "metric": metric_name,
        }

    mean1 = sum(before) / n1
    mean2 = sum(after) / n2

    var1 = sum((x - mean1) ** 2 for x in before) / (n1 - 1) if n1 > 1 else 0.0
    var2 = sum((x - mean2) ** 2 for x in after) / (n2 - 1) if n2 > 1 else 0.0
    # Add tiny epsilon to avoid division by zero when all values are identical
    var1 = max(var1, 1e-10)
    var2 = max(var2, 1e-10)

    # Cohen's d effect size
    pooled_sd = math.sqrt((var1 + var2) / 2) if (var1 + var2) > 0 else 0.001
    effect_size = (mean2 - mean1) / pooled_sd if pooled_sd > 0 else 0.0

    # Welch's t-test
    se = math.sqrt(var1 / n1 + var2 / n2) if n1 > 0 and n2 > 0 else float("inf")
    if se > 0 and se != float("inf"):
        t_stat = (mean2 - mean1) / se
        # Degrees of freedom (Welch-Satterthwaite)
        df_num = (var1 / n1 + var2 / n2) ** 2
        df_den = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        df = df_num / df_den if df_den > 0 else 1
        # Approximate p-value from t-distribution
        p_value = _t_distribution_pvalue(abs(t_stat), df)
    else:
        p_value = 1.0

    direction = "positive" if effect_size > 0.1 else ("negative" if effect_size < -0.1 else "neutral")

    return {
        "direction": direction,
        "effect_size": round(effect_size, 4),
        "p_value": round(p_value, 4),
        "mean_before": round(mean1, 4),
        "mean_after": round(mean2, 4),
        "sufficient_samples": True,
        "metric": metric_name,
    }


def _t_distribution_pvalue(t: float, df: float) -> float:
    """Approximate two-tailed p-value from t-distribution.

    Uses normal approximation for large df, and a simple bound for extreme t.
    """
    if df < 1:
        return 1.0
    # For very large t-statistics, p is effectively 0
    if t > 10:
        return 1e-10
    # For moderate t, use a simple approximation
    # Abramowitz & Stegun 26.7.1: normal approximation for t-distribution
    x = df / (df + t * t)
    # Use regularized incomplete beta via continued fraction
    p_half = 1.0 - _incomplete_beta(df / 2, 0.5, x) if x > 0 else 0.0
    return min(max(p_half * 2, 0.0), 1.0)  # Two-tailed


def _incomplete_beta(a: float, b: float, x: float, steps: int = 100) -> float:
    """Approximate the regularized incomplete beta function using continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use the continued fraction representation (Lentz's method)
    tiny = 1e-30
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d

    for m in range(1, steps):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        # Odd step
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < 1e-10:
            break

    # Multiply by the factor to get regularized incomplete beta
    from math import exp, lgamma
    factor = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return factor * h / a


def _recommendation(direction: str, significant: bool) -> str:
    """Generate a human-readable recommendation."""
    if not significant:
        return "no_action — effect not statistically significant, extend observation window"
    if direction == "positive":
        return "keep — change had significant positive effect"
    if direction == "negative":
        return "rollback — change had significant negative effect, revert recommended"
    return "monitor — effect is neutral, keep but continue monitoring"


def _no_data_result(change_id: str, reason: str) -> dict:
    return {
        "change_id": change_id,
        "direction": "neutral",
        "significant": False,
        "metrics": {},
        "sample_sizes": {"before": 0, "after": 0},
        "recommendation": f"insufficient_data — {reason}",
    }


def attribute_all_active(
    metrics_store: MetricsStore,
    mod_log_path: Path,
) -> list[dict]:
    """Measure effects for all active modifications. Returns list of effect dicts,
    sorted by absolute effect size (most impactful first).
    """
    if not mod_log_path.is_file():
        return []

    mod_log = SelfModificationLog(mod_log_path)
    active = mod_log.list_active()

    results = []
    for change in active:
        effect = measure_effect(change["change_id"], metrics_store)
        results.append(effect)

        # Record the effect back to the modification log
        mod_log.record_effect(
            change["change_id"],
            {
                "direction": effect["direction"],
                "significant": effect["significant"],
                "yield_effect": effect["metrics"].get("yield", {}).get("effect_size", 0),
                "recommendation": effect["recommendation"],
            },
        )

    # Sort by absolute effect size
    def _abs_effect(e):
        yield_eff = e["metrics"].get("yield", {}).get("effect_size", 0)
        return abs(yield_eff)

    results.sort(key=_abs_effect, reverse=True)
    return results

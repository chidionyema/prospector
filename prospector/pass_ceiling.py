"""Honest soft early-exit: stop when a PASS is already mathematically impossible.

Hard-gate kill-fast (cited disconfirming evidence) is unchanged — see kill_filter /
verify. This module only short-circuits when remaining checks cannot possibly clear
the PASS-side floors that build_dossier already enforces:

  - min_supported_to_pass (source_or_die)
  - moat_critical_checks grounded-supported (moat_ungrounded)
  - min_composite_to_pass when even every score axis at 5 cannot clear the bar

Same final decision (KILL with the same gate family); less wall-clock on dead ideas.

Why min_composite usually pays full price
----------------------------------------
Live composite comes from the score step (LLM rubric over axes), which runs only
after every check + adversarial when no gate fired. Check verdicts do not map 1:1
onto axis scores, so an honest early-exit cannot know the real composite mid-vet.
The only safe composite short-circuit is when the *theoretical* max (every weight
axis at 5) is already below `min_composite_to_pass` — a misconfigured / unreachable
bar. Normal catalogue bars (e.g. 2.5) sit below that ceiling, so min_composite kills
still run the full suite + score; the throughput win is source_or_die /
moat_ungrounded (and skipping adversarial once those floors are already impossible).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from .models import SCORE_AXES, CheckResult
from .score import composite

# PASS-side floors soft-exit may return. Not hard gates (cited refuted kills).
SOFT_EXIT_GATES = frozenset({"source_or_die", "moat_ungrounded", "min_composite"})


def _support_floor(cfg) -> float:
    floor = getattr(cfg.thresholds, "min_supported_confidence", None)
    if floor is None:
        floor = cfg.thresholds.confidence_floor
    return float(floor or 0.0)


def _is_grounded_supported(check: CheckResult, floor: float) -> bool:
    return (
        getattr(check.verdict, "value", None) == "supported"
        and float(getattr(check, "confidence", 0.0) or 0.0) >= floor
    )


def max_possible_composite(cfg) -> float:
    """Upper bound on composite: every configured weight axis at 5."""
    weights = getattr(cfg, "weights", None) or {}
    if not weights:
        weights = {ax: 0.0 for ax in SCORE_AXES}
    scores = {ax: 5 for ax in weights}
    return composite(scores, weights)


def pass_impossible_reason(
    checks: Sequence[CheckResult],
    remaining: Iterable[str],
    cfg,
) -> Optional[str]:
    """Return the PASS-side gate that must fire, or None if a PASS is still possible.

    `remaining` is the set of check names not yet run (including soft score_checks).
    Does not consider hard-gate kills — callers still run is_hard_fail first.
    Does not consider infrastructure failure — callers must refuse soft-exit when
    any check has retrieval_failed (DEFER must win over a PASS-floor kill).
    """
    remaining_names = {str(n) for n in remaining if n}
    floor = _support_floor(cfg)
    min_supported = int(getattr(cfg.thresholds, "min_supported_to_pass", 1) or 1)
    moat_checks = tuple(
        getattr(cfg.thresholds, "moat_critical_checks",
                ("value_durability", "incumbency"))
        or ()
    )

    n_supported = sum(1 for c in checks if _is_grounded_supported(c, floor))
    if n_supported + len(remaining_names) < min_supported:
        return "source_or_die"

    moat_remaining = [c for c in moat_checks if c in remaining_names]
    moat_grounded = sum(
        1 for c in checks
        if c.check_name in moat_checks and _is_grounded_supported(c, floor)
    )
    if moat_checks and moat_grounded < 1 and not moat_remaining:
        return "moat_ungrounded"

    bar = float(getattr(cfg.thresholds, "min_composite_to_pass", 0.0) or 0.0)
    if max_possible_composite(cfg) < bar:
        return "min_composite"

    return None

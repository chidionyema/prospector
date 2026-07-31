"""Soft early-exit: PASS impossible → same gate family, fewer checks."""
from __future__ import annotations

from prospector.config import Config, Thresholds
from prospector.models import CheckResult, Verdict
from prospector.pass_ceiling import (
    SOFT_EXIT_GATES,
    max_possible_composite,
    pass_impossible_reason,
)


def _cfg(**thresh) -> Config:
    c = Config()
    c.thresholds = Thresholds(
        confidence_floor=0.0,
        min_supported_confidence=0.3,
        min_supported_to_pass=thresh.get("min_supported_to_pass", 2),
        min_composite_to_pass=thresh.get("min_composite_to_pass", 2.5),
        moat_critical_checks=thresh.get("moat_critical_checks", ["buyer_intent"]),
    )
    c.weights = {
        "pain_acuity": 0.20,
        "money_provability": 0.20,
        "automatability": 0.15,
        "distribution": 0.15,
        "defensibility": 0.25,
        "build_feasibility": 0.05,
    }
    return c


def _check(name: str, verdict: Verdict, conf: float = 0.9,
           retrieval_failed: bool = False) -> CheckResult:
    return CheckResult(
        name, verdict, conf, f"{name} {verdict.value}",
        retrieval_failed=retrieval_failed,
    )


def test_source_or_die_when_remaining_cannot_meet_min_supported():
    cfg = _cfg(min_supported_to_pass=2)
    checks = [_check("buyer_intent", Verdict.UNVERIFIABLE)]
    # One remaining check → at most 1 supported total < 2
    assert pass_impossible_reason(checks, ["pain_reality"], cfg) == "source_or_die"


def test_still_possible_when_remaining_can_meet_min_supported():
    cfg = _cfg(min_supported_to_pass=2)
    checks = [_check("buyer_intent", Verdict.SUPPORTED, 0.9)]
    assert pass_impossible_reason(checks, ["pain_reality", "currency"], cfg) is None


def test_moat_ungrounded_when_critical_checks_exhausted():
    cfg = _cfg(moat_critical_checks=["buyer_intent"])
    checks = [
        _check("buyer_intent", Verdict.UNVERIFIABLE),
        _check("pain_reality", Verdict.SUPPORTED, 0.9),
        _check("currency", Verdict.SUPPORTED, 0.9),
    ]
    # moat check done, not grounded; no moat left in remaining
    assert pass_impossible_reason(checks, ["distribution"], cfg) == "moat_ungrounded"


def test_moat_still_possible_if_critical_check_remaining():
    cfg = _cfg(moat_critical_checks=["buyer_intent"], min_supported_to_pass=1)
    checks = [_check("pain_reality", Verdict.SUPPORTED, 0.9)]
    assert pass_impossible_reason(checks, ["buyer_intent"], cfg) is None


def test_min_composite_when_theoretical_max_below_bar():
    cfg = _cfg(min_composite_to_pass=99.0, min_supported_to_pass=1,
               moat_critical_checks=["buyer_intent"])
    checks = [_check("buyer_intent", Verdict.SUPPORTED, 0.9)]
    assert max_possible_composite(cfg) < 99.0
    assert pass_impossible_reason(checks, [], cfg) == "min_composite"


def test_normal_composite_bar_does_not_soft_exit_on_theory():
    """Catalogue bars sit below theoretical max — min_composite pays full price."""
    cfg = _cfg(min_composite_to_pass=2.5, min_supported_to_pass=1,
               moat_critical_checks=["buyer_intent"])
    checks = [_check("buyer_intent", Verdict.SUPPORTED, 0.9)]
    assert max_possible_composite(cfg) >= 2.5
    assert pass_impossible_reason(checks, [], cfg) is None


def test_weak_supported_does_not_count_toward_floor():
    cfg = _cfg(min_supported_to_pass=2)
    # conf 0.2 < min_supported_confidence 0.3
    checks = [_check("buyer_intent", Verdict.SUPPORTED, 0.2)]
    assert pass_impossible_reason(checks, ["pain_reality"], cfg) == "source_or_die"


def test_refuted_does_not_count_as_supported():
    cfg = _cfg(min_supported_to_pass=2)
    checks = [_check("buyer_intent", Verdict.REFUTED, 0.9)]
    assert pass_impossible_reason(checks, ["pain_reality"], cfg) == "source_or_die"


def test_soft_exit_gates_are_pass_floors_not_hard_gates():
    assert SOFT_EXIT_GATES == frozenset(
        {"source_or_die", "moat_ungrounded", "min_composite"})


def test_empty_remaining_moat_ungrounded_after_critical_silence():
    cfg = _cfg(moat_critical_checks=["buyer_intent"], min_supported_to_pass=1)
    checks = [
        _check("buyer_intent", Verdict.UNVERIFIABLE),
        _check("pain_reality", Verdict.SUPPORTED, 0.9),  # meets min_supported
    ]
    assert pass_impossible_reason(checks, [], cfg) == "moat_ungrounded"

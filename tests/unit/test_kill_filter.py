"""Unit tests for prospector.kill_filter (Part 4 hard gates).

Tests that each hard gate fires KILL for its killing verdict, and that a
clean set of checks passes all gates.
"""
from __future__ import annotations

import pytest
from prospector.config import load_config, Config
from prospector.kill_filter import apply_gates, is_hard_fail
from prospector.models import CheckResult, Verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_check(name: str, verdict: Verdict, confidence: float = 0.9,
               rationale: str = "rationale") -> CheckResult:
    return CheckResult(
        check_name=name,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        citations=["abc123"] if verdict != Verdict.UNVERIFIABLE else [],
    )


def _all_passing_checks() -> list[CheckResult]:
    """A clean set: all required checks with supported/refuted verdicts that pass."""
    return [
        # value_durability: kills on refuted only — supported passes
        make_check("value_durability", Verdict.SUPPORTED),
        # incumbency: kills on supported — must be refuted (no incumbent)
        make_check("incumbency", Verdict.REFUTED),
        # payer_solvency: kills on refuted only — supported passes
        make_check("payer_solvency", Verdict.SUPPORTED),
        # distribution: kills on refuted only — supported passes
        make_check("distribution", Verdict.SUPPORTED),
        # legality: kills on SUPPORTED (margin depends on breaking law) — a lawful
        # idea is REFUTED ("no, it doesn't require illegality"), which passes.
        make_check("legality", Verdict.REFUTED),
        # pain_reality: kills on refuted only — supported passes
        make_check("pain_reality", Verdict.SUPPORTED),
    ]


@pytest.fixture
def cfg() -> Config:
    return load_config()


# ---------------------------------------------------------------------------
# Hard gate — each killing verdict fires KILL
# ---------------------------------------------------------------------------

class TestValueDurabilityGate:
    def test_unverifiable_does_not_kill(self, cfg):
        """Silence is not evidence: unverifiable must NOT trip the gate."""
        checks = [make_check("value_durability", Verdict.UNVERIFIABLE)]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None

    def test_refuted_kills(self, cfg):
        checks = [make_check("value_durability", Verdict.REFUTED)]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "value_durability"

    def test_supported_passes(self, cfg):
        checks = _all_passing_checks()
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestIncumbencyGate:
    def test_supported_kills(self, cfg):
        """incumbency=supported means a strong incumbent exists — kill."""
        checks = [
            # value_durability must pass first (supported), then incumbency kills
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
        ]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "incumbency"

    def test_refuted_passes(self, cfg):
        """incumbency=refuted means no dominant incumbent — gate passes."""
        checks = _all_passing_checks()
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestPayerSolvencyGate:
    def test_refuted_kills(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.REFUTED),
        ]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "payer_solvency"

    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.UNVERIFIABLE),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestDistributionGate:
    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.UNVERIFIABLE),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None

    def test_refuted_kills(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.REFUTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "distribution"


class TestLegalityGate:
    def test_supported_kills(self, cfg):
        """legality kills on SUPPORTED — the margin genuinely depends on breaking
        law/terms or falsifying a measurement. A lawful idea is REFUTED and survives."""
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.SUPPORTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "legality"

    def test_refuted_does_not_kill(self, cfg):
        """legality=refuted ("lawful — does not require breaking law", incl. a creative
        but lawful workaround) must NOT kill. This is the false-negative that the inverted
        [refuted] gate used to produce on good ideas."""
        checks = _all_passing_checks()   # legality is REFUTED here
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None

    def test_unverifiable_does_not_kill(self, cfg):
        """legality=unverifiable does NOT kill (silence is not evidence of illegality)."""
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.UNVERIFIABLE),
            make_check("pain_reality", Verdict.SUPPORTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestPainRealityGate:
    def test_refuted_kills(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.REFUTED),
            make_check("pain_reality", Verdict.REFUTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "pain_reality"

    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.REFUTED),
            make_check("pain_reality", Verdict.UNVERIFIABLE),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


# ---------------------------------------------------------------------------
# Clean set — all gates pass
# ---------------------------------------------------------------------------

def test_clean_set_passes_all_gates(cfg):
    """A fully supported set (incumbency refuted) should pass every gate."""
    checks = _all_passing_checks()
    killed, gate, reason = apply_gates(checks, cfg)
    assert killed is False
    assert gate is None
    assert "passed" in reason.lower()


# ---------------------------------------------------------------------------
# adversarial_decisive=True fires KILL
# ---------------------------------------------------------------------------

def test_adversarial_decisive_kills(cfg):
    checks = _all_passing_checks()  # gates themselves pass
    killed, gate, reason = apply_gates(checks, cfg, adversarial_decisive=True)
    assert killed is True
    assert gate == "adversarial_decisive"
    assert "adversarial" in reason.lower()


def test_adversarial_decisive_false_does_not_kill(cfg):
    checks = _all_passing_checks()
    killed, gate, _ = apply_gates(checks, cfg, adversarial_decisive=False)
    assert killed is False
    assert gate is None


# ---------------------------------------------------------------------------
# Confidence floor: required check supported but confidence below floor
# ---------------------------------------------------------------------------

def test_low_confidence_supported_does_not_fail_non_killing_gate(cfg):
    """value_durability kills only on 'refuted'. A low-confidence 'supported'
    is not a killing verdict, so it must NOT trip the gate — low confidence
    alone never kills (a KILL must be grounded in cited disconfirming evidence)."""
    floor = cfg.thresholds.confidence_floor  # 0.6
    low_conf = floor - 0.1  # 0.5

    cr = CheckResult(
        check_name="value_durability",
        verdict=Verdict.SUPPORTED,
        confidence=low_conf,
        rationale="barely supported",
        citations=["x"],
    )
    assert is_hard_fail("value_durability", cr, cfg) is False


def test_confidence_above_floor_not_a_fail(cfg):
    floor = cfg.thresholds.confidence_floor
    high_conf = floor + 0.1

    cr = CheckResult(
        check_name="value_durability",
        verdict=Verdict.SUPPORTED,
        confidence=high_conf,
        rationale="firmly supported",
        citations=["x"],
    )
    assert is_hard_fail("value_durability", cr, cfg) is False


def test_incumbency_low_confidence_supported_still_kills(cfg):
    """incumbency: killing verdict is 'supported', so low confidence supported
    is caught by the first branch (verdict in killing set) directly."""
    floor = cfg.thresholds.confidence_floor
    low_conf = floor - 0.1

    cr = CheckResult(
        check_name="incumbency",
        verdict=Verdict.SUPPORTED,
        confidence=low_conf,
        rationale="supported with low confidence",
        citations=["x"],
    )
    # 'supported' is in the killing set for incumbency -> is_hard_fail True regardless
    assert is_hard_fail("incumbency", cr, cfg) is True

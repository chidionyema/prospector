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
    """A clean set: all required checks with supported verdicts that pass."""
    return [
        # All checks now follow positive polarity (supported = GOOD)
        make_check("value_durability", Verdict.SUPPORTED),
        make_check("incumbency", Verdict.SUPPORTED),
        make_check("payer_solvency", Verdict.SUPPORTED),
        make_check("distribution", Verdict.SUPPORTED),
        make_check("legality", Verdict.SUPPORTED),
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
    def test_refuted_kills(self, cfg):
        """incumbency=refuted means a strong incumbent exists — kill."""
        checks = [
            # value_durability must pass first (supported), then incumbency kills
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.REFUTED),
        ]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "incumbency"

    def test_supported_passes(self, cfg):
        """incumbency=supported means no dominant incumbent — gate passes."""
        checks = _all_passing_checks()
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestPayerSolvencyGate:
    def test_refuted_kills(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.REFUTED),
        ]
        killed, gate, reason = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "payer_solvency"

    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.UNVERIFIABLE),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None


class TestDistributionGate:
    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.UNVERIFIABLE),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None

    def test_refuted_kills(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.REFUTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "distribution"


class TestLegalityGate:
    def test_refuted_kills(self, cfg):
        """legality kills on REFUTED — the margin genuinely depends on breaking
        law/terms or falsifying a measurement."""
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.REFUTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "legality"

    def test_supported_passes(self, cfg):
        """legality=supported ("lawful — does not require breaking law") must NOT kill."""
        checks = _all_passing_checks()   # legality is SUPPORTED here
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is False
        assert gate is None

    def test_unverifiable_does_not_kill(self, cfg):
        """legality=unverifiable does NOT kill (silence is not evidence of illegality)."""
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
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
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.SUPPORTED),
            make_check("pain_reality", Verdict.REFUTED),
        ]
        killed, gate, _ = apply_gates(checks, cfg)
        assert killed is True
        assert gate == "pain_reality"

    def test_unverifiable_does_not_kill(self, cfg):
        checks = [
            make_check("value_durability", Verdict.SUPPORTED),
            make_check("incumbency", Verdict.SUPPORTED),
            make_check("payer_solvency", Verdict.SUPPORTED),
            make_check("distribution", Verdict.SUPPORTED),
            make_check("legality", Verdict.SUPPORTED),
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

def _with_floor(cfg, floor):
    """Return a cfg whose thresholds.confidence_floor is set to `floor`, without
    mutating the shared fixture."""
    from dataclasses import replace
    return replace(cfg, thresholds=replace(cfg.thresholds, confidence_floor=floor))


def test_supported_is_not_a_killing_verdict_for_value_durability(cfg):
    """value_durability kills only on 'refuted'. A 'supported' is not a killing
    verdict, so it must NOT trip the gate regardless of confidence."""
    cr = CheckResult(
        check_name="value_durability", verdict=Verdict.SUPPORTED,
        confidence=0.5, rationale="supported", citations=["x"])
    assert is_hard_fail("value_durability", cr, cfg) is False


def test_default_floor_zero_lets_grounded_kill_fire(cfg):
    """With the shipped default floor (0.0, inert), any grounded refuted kills —
    golden-set / current-catalogue behaviour is preserved."""
    assert cfg.thresholds.confidence_floor == 0.0
    cr = CheckResult(
        check_name="incumbency", verdict=Verdict.REFUTED,
        confidence=0.40, rationale="grounded refutation", citations=["x"])
    assert is_hard_fail("incumbency", cr, cfg) is True


def test_floor_suppresses_below_floor_kill(cfg):
    """The lever: when the floor is raised, a killing verdict whose grounding
    confidence is BELOW the floor no longer hard-kills — it falls through to
    scoring (closes the value_durability over-restriction wall)."""
    cfg_floor = _with_floor(cfg, 0.6)
    weak = CheckResult(
        check_name="value_durability", verdict=Verdict.REFUTED,
        confidence=0.25, rationale="weakly-grounded refutation", citations=["x"])
    assert is_hard_fail("value_durability", weak, cfg_floor) is False


def test_floor_still_kills_at_or_above_floor(cfg):
    """Above the floor, a grounded killing verdict still hard-kills."""
    cfg_floor = _with_floor(cfg, 0.6)
    strong = CheckResult(
        check_name="value_durability", verdict=Verdict.REFUTED,
        confidence=0.82, rationale="strongly-grounded refutation", citations=["x"])
    assert is_hard_fail("value_durability", strong, cfg_floor) is True

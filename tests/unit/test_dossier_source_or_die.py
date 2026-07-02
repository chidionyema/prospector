"""Source-or-die at the PASS boundary (regression for the 2026-06-16 ungrounded-pass class).

Clearing the composite is necessary but NOT sufficient to PASS: the scorer rules on the candidate
narrative and will score an ungrounded idea highly. A PASS must rest on >=1 grounded-SUPPORTED
check, else we would be publishing on silence. This is the exact defect that minted 9 ungrounded
"pass" dossiers (every check unverifiable, conf 0.0, 0 sources, yet composite 2.95 -> PASS) and put
an ungrounded "Probate Locker" pack briefly live.
"""
from __future__ import annotations

from prospector.config import load_config
from prospector.dossier import build_dossier
from prospector.models import Candidate, CheckResult, Decision, ScoreResult, Verdict


def _cfg():
    cfg = load_config()
    return cfg


def _score_passing(cfg):
    comp = cfg.thresholds.min_composite_to_pass + 1.0
    return ScoreResult(scores={ax: 5 for ax in cfg.weights}, justification={},
                       composite=comp, score_failed=False)


def _check(name, verdict, conf):
    return CheckResult(check_name=name, verdict=verdict, confidence=conf, rationale="r")


def test_ungrounded_high_composite_does_not_pass():
    """All checks unverifiable but composite clears the bar -> KILL source_or_die, never PASS."""
    cfg = _cfg()
    checks = [_check(g, Verdict.UNVERIFIABLE, 0.0) for g in ("pain_reality", "payer_solvency")]
    d = build_dossier(Candidate(title="Ungrounded idea"), checks, None, None,
                      _score_passing(cfg), cfg, "test")
    assert d.decision == Decision.KILL
    assert d.gate_fired in ("source_or_die", "moat_ungrounded")


def test_one_grounded_supported_check_allows_pass():
    """A single grounded-supported moat check + 2 total grounded -> PASS."""
    cfg = _cfg()
    floor = cfg.thresholds.confidence_floor
    checks = [_check("value_durability", Verdict.SUPPORTED, max(0.5, floor + 0.1)),
              _check("payer_solvency", Verdict.SUPPORTED, max(0.5, floor + 0.1)),
              _check("pain_reality", Verdict.UNVERIFIABLE, 0.0)]
    d = build_dossier(Candidate(title="Grounded idea"), checks, None, None,
                      _score_passing(cfg), cfg, "test")
    assert d.decision == Decision.PASS
    assert d.gate_fired is None


def test_low_confidence_supported_does_not_ground_pass():
    """PASS-SIDE floor (min_supported_confidence): a SUPPORTED check below the pass-side
    floor does NOT count as grounded, so a coin-flip 'supported' (e.g. conf 0.15) cannot
    mint a PASS. This is the 2026-06-25 laxness fix. Decoupled from confidence_floor
    (kill-side) — proven here by leaving confidence_floor at 0.0 (inert) while the
    pass-side floor alone rejects the weak support."""
    from dataclasses import replace
    base = _cfg()
    cfg = replace(base, thresholds=replace(base.thresholds,
                  confidence_floor=0.0, min_supported_confidence=0.3))
    # All supported, but every confidence is below the pass-side floor -> none grounded.
    checks = [_check("value_durability", Verdict.SUPPORTED, 0.15),
              _check("incumbency", Verdict.SUPPORTED, 0.20),
              _check("payer_solvency", Verdict.SUPPORTED, 0.15)]
    d = build_dossier(Candidate(title="Coin-flip supported"), checks, None, None,
                      _score_passing(cfg), cfg, "test")
    assert d.decision == Decision.KILL
    assert d.gate_fired in ("moat_ungrounded", "source_or_die")


def test_supported_at_pass_floor_grounds_pass():
    """The same checks at confidence AT/above the pass-side floor DO ground a PASS —
    confirms the floor admits genuine grounded support (no over-restriction)."""
    from dataclasses import replace
    base = _cfg()
    cfg = replace(base, thresholds=replace(base.thresholds,
                  confidence_floor=0.0, min_supported_confidence=0.3))
    checks = [_check("value_durability", Verdict.SUPPORTED, 0.45),
              _check("payer_solvency", Verdict.SUPPORTED, 0.45),
              _check("pain_reality", Verdict.UNVERIFIABLE, 0.0)]
    d = build_dossier(Candidate(title="Grounded idea"), checks, None, None,
                      _score_passing(cfg), cfg, "test")
    assert d.decision == Decision.PASS
    assert d.gate_fired is None


def test_retrieval_outage_still_defers_not_source_or_die():
    """An upstream DEFER (retrieval outage) is parked for re-vet, NOT reclassified as a kill."""
    cfg = _cfg()
    from prospector.models import DEFER_GATE
    checks = [_check("pain_reality", Verdict.UNVERIFIABLE, 0.0)]
    checks[0].retrieval_failed = True
    d = build_dossier(Candidate(title="Outage idea"), checks, None, DEFER_GATE,
                      None, cfg, "test")
    assert d.decision == Decision.DEFER

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
    assert d.gate_fired == "source_or_die"


def test_one_grounded_supported_check_allows_pass():
    """A single grounded-supported check (conf >= floor) + passing composite -> PASS."""
    cfg = _cfg()
    floor = cfg.thresholds.confidence_floor
    checks = [_check("pain_reality", Verdict.SUPPORTED, max(0.5, floor + 0.1)),
              _check("payer_solvency", Verdict.UNVERIFIABLE, 0.0)]
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

"""Test for Shadow Moat infrastructure (run.py)."""
from __future__ import annotations

import pytest
import logging
from prospector.run import vet_candidate
from prospector.operator import MockOperator
from prospector.config import load_config
from prospector.models import Candidate
from prospector.retrieval import FixtureProvider

def test_vet_candidate_logs_shadow_moat_drift(caplog):
    caplog.set_level(logging.INFO)
    
    # Primary op: says PASS
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported", "confidence": 1.0, "rationale": "ok", "citations": []
    })
    
    # Experimental op: says KILL (refuted)
    exp_op = MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0, "rationale": "bad", "citations": []
    })
    
    cand = Candidate(title="Test Idea", one_liner="x", hypothesis="y", who_pays="z")
    cfg = load_config()
    
    # Provide enough fixtures for all checks
    fixtures = {
        "": [{"url": "http://x", "text": "evidence"}]
    }
    search = FixtureProvider(fixtures=fixtures)
    
    # Run vet
    dossier = vet_candidate(cand, op, search, cfg, experimental_op=exp_op)
    
    # 1. Primary should pass all hard gates (might fail on min_composite scoring)
    assert dossier.gate_fired in (None, "min_composite")
    
    # 2. Shadow Moat should have been called and drift logged
    assert "SHADOW MOAT: Running experimental vet" in caplog.text
    assert "SHADOW MOAT DRIFT" in caplog.text
    assert "Primary=None vs Experimental=value_durability" in caplog.text

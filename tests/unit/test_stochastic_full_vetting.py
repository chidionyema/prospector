"""Test for Stochastic Full-Vetting (verify.py)."""
from __future__ import annotations

from typing import Any
import pytest
from prospector.config import load_config
from prospector.models import Candidate, Verdict, Source
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify

@pytest.fixture
def cfg():
    return load_config()

@pytest.fixture
def cand():
    return Candidate(title="Test", one_liner="x", hypothesis="y", who_pays="z")

def test_verify_short_circuits_normally(cfg, cand):
    """Normally, verify stops at the first hard fail."""
    # Mock search that returns one passage for value_durability
    # The template query for value_durability contains "obsolete" and "commoditised".
    fixtures = {
        "obsolete commoditised": [{"url": "http://x", "text": "dead"}]
    }
    search = FixtureProvider(fixtures=fixtures)
    
    # Mock operator that refutes everything
    op = MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0, 
        "rationale": "dead", "citations": []
    })
    
    checks, adv, gate = verify(op, search, cfg, cand, skip_adversarial=True)
    
    # Should only have 1 check (value_durability) if it's the first in run_order
    assert len(checks) == 1
    assert gate == "value_durability"

def test_verify_runs_all_with_full_vet(cfg, cand):
    """With full_vet=True, verify runs ALL checks even if some fail."""
    # Use catch-all fixture ("") so every check gets evidence.
    fixtures = {
        "": [{"url": "http://x", "text": "evidence"}]
    }
    search = FixtureProvider(fixtures=fixtures)
    
    op = MockOperator(router=lambda s, u: {
        "verdict": "refuted", "confidence": 1.0, 
        "rationale": "dead", "citations": []
    })
    
    checks, adv, gate = verify(op, search, cfg, cand, skip_adversarial=True, full_vet=True)
    
    # Should run all checks (usually 6)
    assert len(checks) > 1
    assert gate is not None # Still records the FIRST failing gate

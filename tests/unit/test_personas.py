"""Test for Persona system (config.py, verify.py, run.py)."""
from __future__ import annotations

import pytest
import json
from prospector.config import load_config
from prospector.models import Candidate, Verdict
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verdict_for, adversarial

@pytest.fixture
def cfg():
    c = load_config()
    # Add a test persona
    c.personas["test_persona"] = {
        "generation_bias": "gen-bias",
        "verdict_bias": "verdict-bias",
        "adversarial_bias": "adv-bias",
        "thresholds": {"min_composite_to_pass": 4.5}
    }
    return c

def test_config_for_persona(cfg):
    p_cfg = cfg.for_persona("test_persona")
    assert p_cfg.active_persona == "test_persona"
    assert p_cfg.thresholds.min_composite_to_pass == 4.5

def test_verdict_for_uses_persona_bias(cfg):
    p_cfg = cfg.for_persona("test_persona")
    cand = Candidate(title="X", one_liner="y", hypothesis="z", who_pays="w")
    sources = [] # Empty sources will short-circuit, but let's mock render
    
    # We need to capture what's passed to render
    captured_kwargs = {}
    import prospector.verify as verify_mod
    orig_render = verify_mod.render
    def mock_render(name, **kwargs):
        captured_kwargs.update(kwargs)
        return "sys", "user"
    
    import prospector.verify
    verify_mod.render = mock_render
    try:
        # Pass sources to avoid early return
        from prospector.models import Source
        sources = [Source(source_id="s1", url="http://x", text="text")]
        # Mock op to return valid JSON
        op = MockOperator(router=lambda s, u: {"verdict": "supported", "citations": ["s1"]})
        
        verdict_for(op, cand, "value_durability", sources, p_cfg)
        assert captured_kwargs["verdict_bias"] == "verdict-bias"
    finally:
        verify_mod.render = orig_render

def test_adversarial_uses_persona_bias(cfg):
    p_cfg = cfg.for_persona("test_persona")
    cand = Candidate(title="X", one_liner="y", hypothesis="z", who_pays="w")
    
    captured_kwargs = {}
    import prospector.verify as verify_mod
    orig_render = verify_mod.render
    def mock_render(name, **kwargs):
        captured_kwargs.update(kwargs)
        return "sys", "user"
    
    verify_mod.render = mock_render
    try:
        op = MockOperator(router=lambda s, u: {"kill_case": "dead", "decisive": True})
        adversarial(op, p_cfg, cand, [])
        assert captured_kwargs["adversarial_bias"] == "adv-bias"
    finally:
        verify_mod.render = orig_render

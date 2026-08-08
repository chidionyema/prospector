"""Test for Persona-Aware Adaptive Intelligence (adaptive.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospector.adaptive import calculate_exploration_level, calculate_persona_drift
from prospector.config import load_config


class MockStore:
    def __init__(self, rows, dossiers=None):
        self.rows = rows
        self.dossiers = dossiers or {}
        self._root = Path("store") # dummy

    def all(self, decision=None):
        if decision:
            return [r for r in self.rows if r.get("decision") == decision]
        return self.rows
    
    def get(self, cid):
        return self.dossiers.get(cid)

@pytest.fixture
def cfg():
    c = load_config()
    c.personas["shark"] = {"thresholds": {"min_composite_to_pass": 4.5}}
    c.personas["soft"] = {"thresholds": {"min_composite_to_pass": 2.0}}
    return c

def test_calculate_exploration_level_normalizes_for_shark(cfg):
    # 1. Shark has 95% kill rate. Normal for Shark (threshold 4.5).
    # expected_baseline = 0.7 + (4.5 - 3.2)*0.5 = 0.7 + 0.65 = 1.35 (capped at 0.98)
    rows = [{"decision": "kill", "persona": "shark", "created_at": "2026-01-01"}] * 95 + \
           [{"decision": "pass", "persona": "shark", "created_at": "2026-01-01"}] * 5
    store = MockStore(rows)
    
    cfg.active_persona = "shark"
    expl = calculate_exploration_level(store, cfg=cfg)
    
    # Kill rate 0.95 vs baseline 0.98 -> negative deviation -> low exploration (0.2 or 0.5)
    assert expl <= 0.5

def test_calculate_exploration_level_spikes_for_soft_persona(cfg):
    # 2. Soft persona has 95% kill rate. BAD (expected baseline for 2.0 is 0.7).
    rows = [{"decision": "kill", "persona": "soft", "created_at": "2026-01-01"}] * 95 + \
           [{"decision": "pass", "persona": "soft", "created_at": "2026-01-01"}] * 5
    store = MockStore(rows)
    
    cfg.active_persona = "soft"
    expl = calculate_exploration_level(store, cfg=cfg)
    
    # Kill rate 0.95 vs baseline 0.7 -> +25% deviation -> MAX exploration (1.0)
    assert expl == 1.0

def test_calculate_persona_drift(tmp_path):
    # Mock audit log
    log_path = tmp_path / "prospector.jsonl"
    events = [
        {"message": "ADVISORY BOARD 'shark' agrees with primary"},
        {"message": "ADVISORY BOARD 'minimalist' differs from primary", "shadow_persona": "minimalist"},
        {"message": "ADVISORY BOARD 'shark' agrees with primary"},
        {"message": "ADVISORY BOARD 'minimalist' differs from primary", "shadow_persona": "minimalist"}
    ]
    with open(log_path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
            
    class StoreWithRoot:
        def __init__(self, root): self._root = root
    
    store = StoreWithRoot(tmp_path)
    drift = calculate_persona_drift(store)

    # 2 differences out of 4 board vets = 50% drift for minimalist
    assert drift["minimalist"] == 0.5
    assert "shark" not in drift or drift["shark"] == 0.0


def test_all_configured_audiences_have_descriptions():
    """Every operator/buyer persona listed in config.yaml under
    `audience_forms` must have a non-trivial description in
    _AUDIENCE_DESCRIPTIONS, otherwise the prompt falls back to the raw slug
    and the model receives no persona guidance. Read the dict from the module
    (not config.yaml) so the test is independent of the config file layout."""
    from prospector.generate import _AUDIENCE_DESCRIPTIONS

    keys = ["startup_operator", "software_developer", "agency_owner",
            "ops_manager", "ecommerce_seller"]
    for k in keys:
        assert k in _AUDIENCE_DESCRIPTIONS, f"missing audience description: {k}"
        desc = _AUDIENCE_DESCRIPTIONS[k]
        assert isinstance(desc, str) and len(desc.strip()) >= 40, (
            f"audience {k!r} description is too short or not a string: {desc!r}"
        )

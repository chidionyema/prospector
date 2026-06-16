"""Test for Generative Alpha tracking (diagnostics.py)."""
from __future__ import annotations

import pytest
from prospector.diagnostics import calculate_generative_alpha, calculate_yield
from prospector.models import Decision

class MockStore:
    def __init__(self, rows, dossiers=None, tmp_path=None):
        self.rows = rows
        self.dossiers = dossiers or {}
        from pathlib import Path
        self._dossier_dir = Path(tmp_path) if tmp_path else Path("/tmp/dossiers")
        if tmp_path:
            self._dossier_dir.mkdir(parents=True, exist_ok=True)
        self._root = self._dossier_dir.parent

    def all(self, decision=None):
        if decision:
            return [r for r in self.rows if r.get("decision") == decision]
        return self.rows
    
    def get(self, cid):
        return self.dossiers.get(cid)

def test_calculate_generative_alpha():
    # 1. Store with high-scoring passes
    rows = [
        {"candidate_id": "c1", "decision": "pass", "composite": 4.5, "created_at": "2026-01-02"},
        {"candidate_id": "c2", "decision": "pass", "composite": 4.0, "created_at": "2026-01-01"}
    ]
    dossiers = {
        "c1": {"score": {"scores": {"pain_acuity": 5, "automatability": 4}}},
        "c2": {"score": {"scores": {"pain_acuity": 4, "automatability": 5}}}
    }
    store = MockStore(rows, dossiers)
    
    alpha = calculate_generative_alpha(store)
    
    assert alpha["rolling_avg"] == 4.25
    assert alpha["axis_averages"]["pain_acuity"] == 4.5
    assert alpha["axis_averages"]["automatability"] == 4.5

def test_calculate_yield():
    # Store with high survival rate
    rows = [{"decision": "pass"}] * 8 + [{"decision": "kill"}] * 2
    store = MockStore(rows)
    
    y = calculate_yield(store)
    assert y == 0.8

def test_quality_decay_alarm(tmp_path):
    # Store with low-scoring passes
    rows = [{"candidate_id": f"c{i}", "decision": "pass", "composite": 2.5, "created_at": "2026-01-01"} for i in range(5)]
    store = MockStore(rows, tmp_path=tmp_path / "dossiers")
    
    from prospector.diagnostics import calibration_alarms
    from prospector.config import load_config
    
    cfg = load_config()
    alarms = calibration_alarms(store, cfg)
    
    # Should trigger quality_decay
    assert any(a["code"] == "quality_decay" for a in alarms)

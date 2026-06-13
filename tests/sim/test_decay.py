"""Clock time-travel simulation for Task E: Decay loop (Part 7, 16).
"""
from __future__ import annotations

import datetime
import re
from typing import Any

import pytest
from prospector.config import load_config
from prospector.decay import run_decay_loop
from prospector.models import Candidate, Decision, Dossier, Verdict, CheckResult, ScoreResult
from prospector.operator import MockOperator
from prospector.store import Store


@pytest.fixture
def setup_store(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    store = Store(cfg)
    
    cand = Candidate(title="Decay Test", one_liner="Stale biz")
    score = ScoreResult(
        scores={ax: 4 for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        justification={ax: "good" for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        composite=4.0
    )
    
    now = datetime.datetime.now(datetime.timezone.utc)
    created_at = (now - datetime.timedelta(days=40)).isoformat()
    due_at = (now - datetime.timedelta(days=10)).isoformat()
    
    dossier = Dossier(
        candidate=cand,
        decision=Decision.PASS,
        score=score,
        model_version="test-model",
        created_at=created_at,
        reverify_due_at=due_at,
        checks=[CheckResult("pain_reality", Verdict.SUPPORTED, 0.9, "OK")]
    )
    store.save(dossier)
    return cfg, store, dossier


def test_decay_loop_refreshes_valid_dossier(setup_store):
    cfg, store, d = setup_store
    
    def router(system, user):
        if "Write 1-3 queries" in user:
            return ["query"]
        if "analyst" in system:
            m = re.search(r"\[([a-f0-9]{16})\]", user)
            cid = [m.group(1)] if m else []
            v = "refuted" if "incumbency" in user else "supported"
            return {"verdict": v, "confidence": 0.9, "rationale": "ok", "citations": cid}
        if "Score a vetted opportunity" in system:
            return {
                "scores": {ax: 4 for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
                "justification": {ax: "good" for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]}
            }
        if "generate a grounded business artifact" in system:
            return {"content": "ok"}
        if "write listing and marketing copy" in system:
            return {"copy": "ok"}
        if "check marketing/listing copy" in system:
            return {"pass": True}
        return {}


    op = MockOperator(router=router)
    from prospector.retrieval import FixtureProvider
    # "" key matches every query (templated disconfirming queries for the
    # template_checks don't contain "query"); router still routes verdicts by check name.
    search = FixtureProvider(fixtures={"": [{"url": "http://ok.com", "text": "OK"}]})
    
    res = run_decay_loop(store, op, search, cfg)
    assert res["refreshed"] == 1
    updated = store.get(d.candidate.candidate_id)
    assert updated["decision"] == "pass"
    assert datetime.datetime.fromisoformat(updated["reverify_due_at"]) > datetime.datetime.now(datetime.timezone.utc)


def test_decay_loop_delists_failed_dossier(setup_store):
    cfg, store, d = setup_store
    
    def router(system, user):
        if "Write 1-3 queries" in user:
            return ["query"]
        if "analyst" in system:
            m = re.search(r"\[([a-f0-9]{16})\]", user)
            cid = [m.group(1)] if m else []
            if "value_durability" in user:
                return {"verdict": "refuted", "confidence": 0.9, "rationale": "dead", "citations": cid}
            v = "refuted" if "incumbency" in user else "supported"
            return {"verdict": v, "confidence": 0.9, "rationale": "ok", "citations": cid}
        if "Score a vetted opportunity" in system:
            return {
                "scores": {ax: 4 for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
                "justification": {ax: "good" for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]}
            }
        return {"content": "ok", "copy": "ok", "pass": True}


    op = MockOperator(router=router)
    from prospector.retrieval import FixtureProvider
    # "" key matches every query, incl. templated value_durability disconfirming query.
    search = FixtureProvider(fixtures={"": [{"url": "http://dead.com", "text": "dead"}]})
    cfg.hard_gates = [{"value_durability": ["refuted"]}]

    res = run_decay_loop(store, op, search, cfg)
    assert res["delisted"] == 1
    updated = store.get(d.candidate.candidate_id)
    assert updated["decision"] == "kill"
    assert updated["gate_fired"] == "value_durability"

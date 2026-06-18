"""Integration tests for Task D: Headless read/commerce API (Part 15C).

Proofs:
1. Public listings are accessible without auth.
2. Dossiers are gated (entitlement required).
3. test-token grants access (positive gating).
4. Missing or bad token denies access (negative gating).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prospector.api import app
from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier, Verdict, CheckResult, ScoreResult
from prospector.store import Store
# compose_packs was deleted — orphaned 3-tier pricing (never called in production).
# The live commerce path uses one £30 (3000 pence) pack. The listing JSON below
# pushes that static shape.
from publish.publish import _write_listing

client = TestClient(app)


@pytest.fixture
def setup_store(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    store = Store(cfg)
    
    # Create a passing dossier and publish it
    cand = Candidate(title="API Biz", one_liner="A biz for the API test")
    score = ScoreResult(
        scores={ax: 4 for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        justification={ax: "good" for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        composite=4.0
    )
    dossier = Dossier(
        candidate=cand,
        decision=Decision.PASS,
        score=score,
        model_version="test-model",
        created_at="2026-06-13T12:00:00Z",
        checks=[CheckResult("pain_reality", Verdict.SUPPORTED, 0.9, "OK")]
    )
    store.save(dossier)

    # /v1/listings serves the local listing JSON (store_dir/listings/{id}.json).
    # publish() now routes through EngineBridge (Store API catalog + R2) and writes
    # no local listing when those are unconfigured, so write the listing the endpoint
    # reads directly. This keeps the API-contract test independent of money-rail infra.
    listing = {
        "candidate_id": cand.candidate_id,
        "verified_at": dossier.created_at,
        "reverify_due_at": dossier.created_at,
        "source_count": len(dossier.all_sources),
        "packs": {
            # Static £30 pack (3000 pence) — live commerce path is the single source of truth.
            "scout": {
                "name": "Scout",
                "price_pence": 3000,
                "contents": {
                    "thesis": cand.hypothesis,
                    "evidence": [s.to_dict() for s in dossier.all_sources],
                    "score": score.to_dict()
                }
            },
            "operator": {
                "name": "Operator",
                "price_pence": 3000,
                "contents": {
                    "scout": "included"
                }
            },
            "founder_investor": {
                "name": "Founder / Investor",
                "price_pence": 3000,
                "contents": {
                    "operator": "included"
                }
            }
        },
    }
    _write_listing(cand.candidate_id, listing, cfg)

    return cfg, dossier



def test_public_listings_no_auth(setup_store):
    cfg, dossier = setup_store
    
    # We need to make sure the app uses the test config's store_dir
    # For simplicity in this test, we'll patch the app's cfg/store if needed,
    # but since it's a singleton in api.py, it's easier to just ensure 
    # REPO_ROOT/store is where it looks or similar.
    # Actually, api.py loads config at module level.
    
    # To make this test robust, let's override the app's dependency or config
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    response = client.get("/v1/listings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["id"] == dossier.candidate.candidate_id


def test_dossier_gating_negative(setup_store):
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    cid = dossier.candidate.candidate_id
    
    # No auth
    response = client.get(f"/v1/dossiers/{cid}")
    assert response.status_code == 403
    
    # Bad token
    response = client.get(f"/v1/dossiers/{cid}", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 403


def test_dossier_gating_positive(setup_store):
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    cid = dossier.candidate.candidate_id
    
    # Valid token
    response = client.get(f"/v1/dossiers/{cid}", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["candidate"]["candidate_id"] == cid


def test_health_check():
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint(setup_store):
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    response = client.get("/v1/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["engine"]["total_vetted"] >= 1
    assert "pass_count" in data["engine"]
    assert "gates" in data

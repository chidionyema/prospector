"""Integration tests for Task D: Headless read/commerce API (Part 15C).

Proofs:
1. Public listings are accessible without auth.
2. Dossiers are gated (entitlement required).
3. test-token grants access (positive gating).
4. Missing or bad token denies access (negative gating).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from prospector.api import app
from prospector.config import load_config
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict
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
    #
    # The first six keys are what publish.publish writes for every real pack, and what
    # publish.validate_listing now enforces on the write path (Q4b.3). They were absent
    # here, so this fixture was building a receipt shape production has never produced —
    # exactly how the two mock fixtures got into the operator's store/listings/.
    #
    # The rest (reverify_due_at, source_count, packs) are what /v1/listings reads at
    # prospector/api.py:98-104, and they are the reason this fixture had to invent a
    # shape at all: 73 of 73 live receipts carry NONE of them, and api.py:105's bare
    # `except Exception: continue` swallows the resulting KeyError, so the endpoint
    # returns [] for every real listing. Keeping them here preserves what this test
    # asserts; the endpoint/writer divergence is recorded in the readiness register and
    # is not fixed by widening a fixture.
    listing = {
        "candidate_id": cand.candidate_id,
        "title": cand.title,
        "market": getattr(cand, "market", "") or "",
        "published_via": "EngineBridge",
        "catalog": True,
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


def test_public_listings_serves_the_receipt_production_actually_writes(setup_store):
    """Regression for §28.10 — /v1/listings answered 200 `[]` for the whole live catalogue.

    The endpoint read `reverify_due_at`, `source_count` and `packs["scout"]`: keys no
    writer in this repo has ever produced. 73 of 73 live receipts lacked all three, and
    `api.py`'s bare `except Exception: continue` turned every KeyError into a silent
    skip, so a total schema divergence was indistinguishable from an empty catalogue.

    It survived the suite because `setup_store` above writes a receipt carrying those
    keys — a shape invented to exercise the endpoint, which production has never
    written. So this test deliberately does NOT use that fixture's listing. It writes
    the SIX keys `publish.publish` really passes to `_write_listing` and nothing else.

    If this test ever fails, the fix is the endpoint. Adding keys to the receipt below
    would restore exactly the blindness it was written to remove.
    """
    cfg, dossier = setup_store
    thin_id = "1111222233334444"
    _write_listing(thin_id, {
        "candidate_id": thin_id,
        "title": "PanelPack — the fixed-fee pack that gets a care package restored",
        "market": "uk",
        "verified_at": dossier.created_at,
        "published_via": "EngineBridge",
        "catalog": True,
    }, cfg)

    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    response = client.get("/v1/listings")
    assert response.status_code == 200
    data = response.json()

    row = next((r for r in data if r["id"] == thin_id), None)
    assert row is not None, (
        f"the production receipt shape was dropped by /v1/listings; served {data!r}")
    assert row["title"].startswith("PanelPack")
    assert row["market"] == "uk"
    assert row["verified_at"] == dossier.created_at
    # The deleted 3-tier pricing stays deleted: `compose_packs` is gone (see the note at
    # the top of this file), so reviving `packs` here would resurrect an abandoned model.
    assert "packs" not in row
    assert "scout" not in row


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


def test_dev_all_access_token_inert_by_default(setup_store, monkeypatch):
    """P2 — the dev all-access token must be a no-op unless the env var enables it,
    so `Bearer test-token` is NOT a production backdoor."""
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    monkeypatch.delenv("PROSPECTOR_DEV_ALL_ACCESS_TOKEN", raising=False)
    cid = dossier.candidate.candidate_id
    response = client.get(f"/v1/dossiers/{cid}", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 403


def test_dossier_gating_positive(setup_store, monkeypatch):
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    # The all-access token is inert unless the dev env var explicitly enables it
    # (no hardcoded backdoor). Opt in for this positive-gating test.
    monkeypatch.setenv("PROSPECTOR_DEV_ALL_ACCESS_TOKEN", "test-token")

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


def test_metrics_endpoint(setup_store, monkeypatch):
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    monkeypatch.setenv("PROSPECTOR_ADMIN_API_KEY", "test-admin-key")
    response = client.get("/v1/metrics", headers={"X-Admin-Key": "test-admin-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["engine"]["total_vetted"] >= 1
    assert "pass_count" in data["engine"]
    assert "gates" in data


def test_metrics_requires_admin_key(setup_store, monkeypatch):
    """Operational metrics fail closed when unconfigured and reject a wrong key."""
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    monkeypatch.delenv("PROSPECTOR_ADMIN_API_KEY", raising=False)
    assert client.get("/v1/metrics").status_code == 503

    monkeypatch.setenv("PROSPECTOR_ADMIN_API_KEY", "test-admin-key")
    assert client.get("/v1/metrics").status_code == 401
    assert client.get("/v1/metrics", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_listing_id_rejects_path_traversal(setup_store):
    """A traversal id never reaches the filesystem (400 before any read)."""
    cfg, dossier = setup_store
    from prospector import api
    api.cfg = cfg
    api.store = Store(cfg)

    assert client.get("/v1/listings/../../etc/passwd").status_code in (400, 404)
    assert client.get("/v1/listings/not-a-hex-id").status_code == 400

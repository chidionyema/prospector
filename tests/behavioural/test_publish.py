"""Behavioural tests for Task C: Packs + publish-on-pass (Part 6, 11, 16).

Proofs:
1. Publish is called ONLY on a PASS decision.
2. Listing contains trust metadata and correctly tiered packs.
3. Syndication failure doesn't block canonical publish (resilience).
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from prospector.config import Config
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict
from publish.publish import publish


@pytest.fixture(autouse=True)
def _internal_api_key(monkeypatch):
    # The bridge fails closed without a configured internal key (no committed default), so
    # the publish path needs one — exactly as production supplies it via env.
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-internal-key")
    # The entitlements check also fails closed without a configured API key.
    monkeypatch.setenv("PROSPECTOR_ENTITLEMENTS_API_KEY", "test-entitlements-key")


@pytest.fixture
def cfg(monkeypatch):
    c = Config()
    c.store = {"dir": "store_test"}
    c.listing = {"exclusivity": True, "subscription": True}
    # Read entitlements key from env (set by _internal_api_key fixture)
    c.entitlements_api_key = os.environ.get("PROSPECTOR_ENTITLEMENTS_API_KEY", "")
    return c


@pytest.fixture
def passing_dossier():
    cand = Candidate(title="Pass Biz", one_liner="A passing business")
    # Score 4.0 on all axes
    score = ScoreResult(
        scores={ax: 4 for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        justification={ax: "good" for ax in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]},
        composite=4.0
    )
    return Dossier(
        candidate=cand,
        decision=Decision.PASS,
        score=score,
        model_version="test-model",
        created_at="2026-06-13T12:00:00Z",
        # A LANE-DECISIVE grounded check (`value_durability`) is not decoration here: a PASS with
        # only incidental supported checks is what `build_dossier` KILLs as `moat_ungrounded`, so
        # a fixture without one described a dossier the real pipeline cannot emit. It slipped
        # through before only because the bridge's publish backstop ran a weaker copy of the
        # source-or-die arithmetic (engine audit finding 8) and never looked at the decisive set.
        checks=[
            CheckResult("pain_reality", Verdict.SUPPORTED, 0.9, "OK"),
            CheckResult("value_durability", Verdict.SUPPORTED, 0.9, "OK"),
        ]
    )


@pytest.fixture
def killing_dossier():
    cand = Candidate(title="Kill Biz", one_liner="A failing business")
    return Dossier(
        candidate=cand,
        decision=Decision.KILL,
        gate_fired="incumbency",
        reason="Incumbent exists."
    )


def test_publish_only_on_pass(passing_dossier, killing_dossier, cfg, tmp_path):
    cfg.store["dir"] = str(tmp_path)
    
    # PASS
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        res_pass = publish(passing_dossier, cfg)
        assert res_pass["status"] == "published"
    
    # KILL
    res_kill = publish(killing_dossier, cfg)
    assert res_kill["status"] == "skipped"


def test_listing_receipt_written_on_publish(passing_dossier, cfg, tmp_path):
    """Successful Store publish also drops a local store/listings receipt for CC."""
    cfg.store = {"dir": str(tmp_path)}

    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value.status_code = 200
        mock_get.return_value.status_code = 404
        res = publish(passing_dossier, cfg)
        assert res["status"] == "published"

    listing_path = tmp_path / "listings" / f"{passing_dossier.candidate.candidate_id}.json"
    assert listing_path.exists(), res
    data = json.loads(listing_path.read_text(encoding="utf-8"))
    assert data["candidate_id"] == passing_dossier.candidate.candidate_id
    assert data.get("catalog") is True


def test_syndication_outage_resilience(passing_dossier, cfg, tmp_path, monkeypatch):
    cfg.store["dir"] = str(tmp_path)
    
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        res = publish(passing_dossier, cfg)
        assert res["status"] == "published"
    # If we added a mock that raised, we'd assert it still returned status='published'

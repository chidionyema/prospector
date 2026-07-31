"""A pack registered with no sector must say so in the run log.

Not guessing a sector is correct and stays correct — the vocabulary is closed, the storefront
routes buyers on it, and an invented category is an unsourced claim. But silence is a separate
failure: four of the twenty-six packs live on 2026-07-31 (CureSafe Strip, SpatWindow,
StrikeShield, SailCert) carried no facets at all, and nothing had ever announced it, so they sat
on the shelf reachable only by search until someone read the catalogue by hand.

The publish must not fail on this — an untagged pack is still a real, sellable pack — so what is
asserted here is that it is LOUD and that it still lists.
"""
from __future__ import annotations

import logging

import pytest

from prospector.bridge import EngineBridge
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


class _FakeProvisioner:
    def create_product(self, name, description, metadata):
        return "prod_real_123"

    def create_price(self, product_id, amount_pence, currency="gbp"):
        return "price_real_123"


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-internal-key")

    class _Thresholds:
        confidence_floor = 0.0

    class _Cfg:
        entitlements_api_key = "test-entitlements-key"
        store_payments = {"active_provider": "stripe"}
        thresholds = _Thresholds()
        listing = {"price_pence": 4900}

    b = EngineBridge(_Cfg())
    b.entitlements_check = lambda candidate_id: True
    b.stripe = _FakeProvisioner()
    b.r2.upload = lambda path, key: True

    calls: list[dict] = []
    b._update_catalog = lambda **kwargs: (calls.append(kwargs), True)[1]
    b.catalog_calls = calls
    return b


def _dossier(facets):
    """A publishable PASS whose listing carries `facets` (or omits the block entirely)."""
    body = "## Section\n\nGrounded prose about the opportunity. " * 20
    listing = {
        "type": "listing_page",
        "copy": "# SpatWindow\n\nA per-lease closure forecast for owner-operated UK oyster and "
                "mussel farms: storm-overflow telemetry, rainfall and tide fused into a harvest "
                "window, so stock is moved before a downgrade lands rather than after.",
    }
    if facets is not None:
        listing["facets"] = facets
    cand = Candidate(
        candidate_id="c" * 16,
        title="SpatWindow",
        one_liner="Per-lease closure forecast for UK shellfish farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    cand.tags = {
        "artifacts": {k: f"# {k}\n\n{body}" for k in
                      ("build_spec", "gtm_plan", "ops_plan", "financial_model")},
        "marketing": [listing],
    }
    return Dossier(
        candidate=cand,
        decision=Decision.PASS,
        checks=[CheckResult(check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
                            rationale="Growers search for closure guidance.",
                            citations=[], sources=[], queries=[])],
        created_at="2026-07-31T00:00:00Z",
    )


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


class TestSectorlessPublishIsAnnounced:
    def test_a_missing_facets_block_warns(self, bridge, caplog):
        with caplog.at_level(logging.WARNING, logger="prospector.bridge"):
            bridge.publish_pass(_dossier(None))
        warned = [m for m in _warnings(caplog) if "NO sector" in m]
        assert warned, f"no sector-less warning; warnings were {_warnings(caplog)}"
        # The message has to be actionable on its own: which pack, and where to fix it.
        assert "c" * 16 in warned[0]
        assert "facets-backfill.json" in warned[0]

    def test_the_warning_names_every_absent_facet(self, bridge, caplog):
        """A pack with only `effort` is still mostly untagged — the log must say so."""
        with caplog.at_level(logging.WARNING, logger="prospector.bridge"):
            bridge.publish_pass(_dossier({"effort": "automatable"}))
        warned = [m for m in _warnings(caplog) if "NO sector" in m]
        assert warned
        # Matched on the rendered list, not on substrings of the whole message: the message
        # also echoes the facets block it was given, so a bare `"effort" not in message`
        # would pass or fail for the wrong reason.
        assert (
            "Absent facets: ['advantages', 'commitment', 'mechanism', 'payer', 'sector']"
            in warned[0]
        ), warned[0]

    def test_a_sector_less_pack_is_still_listed(self, bridge, caplog):
        # Deliberate: not tagging is not a reason to withhold a real pack from sale. If this
        # ever becomes a hard gate it should be a decision, not a side effect of adding a log.
        with caplog.at_level(logging.WARNING, logger="prospector.bridge"):
            bridge.publish_pass(_dossier(None))
        assert bridge.catalog_calls[-1]["is_listed"] is True

    def test_a_tagged_pack_says_nothing(self, bridge, caplog):
        with caplog.at_level(logging.WARNING, logger="prospector.bridge"):
            bridge.publish_pass(_dossier({
                "sector": "other", "payer": "b2b", "effort": "automatable",
                "mechanism": "vertical_tool", "advantages": ["ops"],
            }))
        assert not [m for m in _warnings(caplog) if "NO sector" in m]
        call = bridge.catalog_calls[-1]
        assert call["metadata"]["sector"] == "other"
        assert call["metadata"]["payer"] == "b2b"

    def test_an_invented_sector_warns_rather_than_shipping(self, bridge, caplog):
        """`normalize` drops a value outside the vocabulary — the pack must then read as
        untagged, not as quietly tagged with something the storefront cannot render."""
        with caplog.at_level(logging.WARNING, logger="prospector.bridge"):
            bridge.publish_pass(_dossier({"sector": "aquaculture"}))
        assert [m for m in _warnings(caplog) if "NO sector" in m]
        assert "sector" not in bridge.catalog_calls[-1]["metadata"]

"""A pack that cannot list must not mint a money rail.

THE DEFECT THIS CLOSES. `publish_pass` minted the Stripe Product (bridge.py), minted the
Price, uploaded the bundle to R2, and only THEN ran the Q2 lint. Every operand of the lint —
completeness, the bundle audit, the content lint — is a pure function of a pack already built,
so none of them could ever be changed by provisioning. The ordering bought nothing and cost a
leak: on 2026-08-08 four freshly-passed packs each failed the lint on a single dead citation
URL, and each left behind a Stripe Product and Price that no buyer could ever reach, once per
republish attempt.

The three properties below are the fix, and each fails differently if it regresses:

  * an unlistable pack mints NOTHING (the leak itself);
  * a sellable pack still mints (the fix must not have simply disabled provisioning);
  * a REPUBLISH still resolves its live money rail even when the new content fails the lint
    (the guard is on the MINT, not on `_resolve_money_rail` — that function only reads, and
    skipping it would write stub ids over a live pack's real ones and unlist it).

The third is the one worth the most: it is the difference between a fix and an incident.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from test_bridge_pricing import _dossier  # the same PASS dossier the ladder tests publish

from prospector.bridge import EngineBridge, ExistingPrice
from prospector.config import Config

LIVE_PRODUCT = "prod_live_abc"
LIVE_PRICE = "price_live_abc"


@pytest.fixture
def bridge(cfg: Config, monkeypatch):
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-internal-key")
    b = EngineBridge(cfg)
    b.store_api_url = "http://localhost:5050"
    b.entitlements_check = MagicMock(return_value=True)
    return b


def _unsellable(candidate_id: str):
    """A PASS dossier whose pack is a stub: fails completeness, the bundle audit and the lint."""
    d = _dossier(candidate_id)
    d.candidate.tags = {
        "artifacts": {
            "build_spec": "Test build spec content",
            "gtm_plan": "Test GTM plan content",
            "ops_plan": "Test ops plan content",
            "financial_model": "Test financial model content",
        },
        "marketing": [{"type": "listing_page", "copy": "# FuelClaim\n\nListing copy."}],
    }
    return d


def _publish(b: EngineBridge, dossier, *, prov, existing: dict | None = None):
    """Publish once; return (ok, catalogue_payload)."""
    with patch.object(EngineBridge, "provisioner", property(lambda self: prov)), \
            patch("requests.post") as mock_post, \
            patch("requests.get") as mock_get:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"
        if existing is None:
            mock_get.return_value.status_code = 404
        else:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = existing
        ok = b.publish_pass(dossier)

        payload = None
        for call in mock_post.call_args_list:
            body = call.kwargs.get("json") or {}
            if isinstance(body, dict) and "title" in body:
                payload = body
    return ok, payload


def _fresh_provisioner() -> MagicMock:
    prov = MagicMock()
    prov.create_product.return_value = "prod_test"
    prov.create_price.return_value = "price_test"
    return prov


def test_an_unlistable_pack_mints_no_provider_objects(bridge):
    """The leak. A stub pack fails every content gate, so provisioning it can only ever
    produce an orphan — a Product and a Price no catalogue row will ever point at."""
    prov = _fresh_provisioner()
    ok, payload = _publish(bridge, _unsellable("gate-stub"), prov=prov)

    assert ok is True, "the pack must still REGISTER (unlisted), so the operator can see it"
    prov.create_product.assert_not_called()
    prov.create_price.assert_not_called()
    assert payload is not None
    assert payload["isListed"] is False


def test_an_unlistable_pack_is_registered_with_stub_ids_not_real_ones(bridge):
    """Skipping the mint must leave the pack visibly unprovisioned rather than half-provisioned."""
    _, payload = _publish(bridge, _unsellable("gate-stub2"), prov=_fresh_provisioner())

    assert payload["providerPriceId"].startswith("price_stub_")
    assert payload["providerProductId"].startswith("prov_stub_")


def test_a_sellable_pack_still_mints_its_money_rail(bridge):
    """The control. If the gate were simply blocking provisioning outright, the leak would be
    'fixed' by making the shelf unable to grow at all — which is the bug, not the fix."""
    prov = _fresh_provisioner()
    ok, payload = _publish(bridge, _dossier("gate-ok"), prov=prov)

    assert ok is True
    prov.create_product.assert_called_once()
    prov.create_price.assert_called_once()
    assert payload["isListed"] is True


def test_a_republish_keeps_its_live_rail_even_when_the_new_content_fails_the_lint(bridge):
    """The money-rail safety property, and the reason the guard sits on the MINT branch alone.

    `_resolve_money_rail` only READS (describe_price). Gating it on content_ok would leave a
    live, already-sold pack carrying `price_stub_*` ids into `_update_catalog`, overwriting a
    real money rail with stubs. The pack must go unlisted on bad content — and keep the exact
    provider objects it is already sold with.
    """
    prov = _fresh_provisioner()
    prov.describe_price.return_value = ExistingPrice(LIVE_PRODUCT, 4900, "gbp")
    existing = {"id": "gate-live", "providerPriceId": LIVE_PRICE,
                "providerProductId": LIVE_PRODUCT, "pricePence": 4900, "isListed": True}

    ok, payload = _publish(bridge, _unsellable("gate-live"), prov=prov, existing=existing)

    assert ok is True
    prov.describe_price.assert_called_once_with(LIVE_PRICE)
    prov.create_product.assert_not_called()
    prov.create_price.assert_not_called()
    assert payload["providerPriceId"] == LIVE_PRICE, "a live rail must never be stubbed over"
    assert payload["providerProductId"] == LIVE_PRODUCT
    assert payload["isListed"] is False, "bad content still unlists it"

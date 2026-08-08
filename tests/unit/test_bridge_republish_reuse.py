"""A republish must not mint a second money rail for a pack that already has one.

The defect, found 2026-08-08 while preparing to regenerate 42 published packs whose artifact
prose leaked engine field names: `publish_pass` called `create_product` and `create_price`
unconditionally on EVERY publish (bridge.py, step 3), and the only thing standing between
that and a duplicate was the provider's idempotency key. Stripe's idempotency keys expire
after 24 HOURS. Every one of those 42 packs was published days-to-weeks ago, so the key was
long dead and each republish would have minted a genuinely new Product and Price.

That alone would only litter Stripe. What makes it a fulfilment bug is the other half, on
the Store side:

  * the catalogue upsert assigns ProviderPriceId unconditionally on the UPDATE path
    (Store.Api/Program.cs:490), so the new price becomes the one checkout bills against;
  * that same update path never reassigns PricePence (Program.cs:477-482 sets only
    Title/OneLine/DossierRef), so the fulfilment floor keeps the ORIGINAL number;
  * FulfilmentService.cs:88 refuses delivery when `item.AmountPence < pack.PricePence`.

So any republish that lands on a lower rung charges the buyer the new amount and then
refuses to deliver. The Store already treats a published price as immutable; these tests pin
the engine honouring the same invariant instead of silently contradicting it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from test_bridge_pricing import _dossier  # the same PASS dossier the ladder tests publish

from prospector.bridge import EngineBridge, ExistingPrice, StripeProvisioner
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


def _publish(b: EngineBridge, dossier, *, existing: dict | None, prov):
    """Publish once against a given catalogue row. Returns (result, provisioner, payload).

    Only the provisioner and the HTTP edges are stubbed, so the decision under test is made
    by the real `publish_pass`, not by the harness.
    """
    prov_ctx = patch.object(EngineBridge, "provisioner", property(lambda self: prov))
    with prov_ctx, patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"
        if existing is None:
            mock_get.return_value.status_code = 404
        else:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = existing
        result = b.publish_pass(dossier)

        payload = None
        for call in mock_post.call_args_list:
            body = call.kwargs.get("json") or {}
            if isinstance(body, dict) and "title" in body:
                payload = body
    return result, payload


def _live_row(price_id: str = LIVE_PRICE, price_pence: int = 4900) -> dict:
    """A catalogue row as GET /catalog/{id} really projects it (Program.cs:330-336).

    Note what is NOT here: providerProductId. The public projection does not expose it, which
    is exactly why the product id has to be resolved from the price at the provider.
    """
    return {"id": "c2-reuse", "title": "Pack", "pricePence": price_pence,
            "paymentProvider": "stripe", "providerPriceId": price_id,
            "contentVersion": 3}


def _provisioner(found: ExistingPrice | None) -> MagicMock:
    prov = MagicMock()
    prov.create_product.return_value = "prod_NEW_should_not_exist"
    prov.create_price.return_value = "price_NEW_should_not_exist"
    prov.describe_price.return_value = found
    return prov


# --------------------------------------------------------------------------------------
# The core property
# --------------------------------------------------------------------------------------

def test_republishing_a_live_pack_mints_nothing_and_keeps_its_price(bridge):
    """The bug in one assertion: a republish must reuse, not re-mint."""
    prov = _provisioner(ExistingPrice(LIVE_PRODUCT, 4900, "gbp"))
    ok, payload = _publish(bridge, _dossier("c2-reuse", "venture", "us"),
                           existing=_live_row(), prov=prov)

    assert ok is True
    prov.create_product.assert_not_called()
    prov.create_price.assert_not_called()
    assert payload["providerPriceId"] == LIVE_PRICE
    assert payload["providerProductId"] == LIVE_PRODUCT


def test_a_moved_rung_never_repoints_a_pack_that_is_already_on_sale(bridge):
    """The charged-but-undelivered case, and the reason reuse is not merely tidiness.

    The ladder decides a rung on every publish. If the config, tier or market moved since the
    first publish it can decide a DIFFERENT one. Repointing checkout at that new price while
    the Store keeps the old floor is what bills a buyer and then refuses them the download.
    """
    dossier = _dossier("c2-reuse", "venture", "us")
    prov = _provisioner(ExistingPrice(LIVE_PRODUCT, 2900, "gbp"))
    ok, payload = _publish(bridge, dossier, existing=_live_row(price_pence=2900), prov=prov)

    assert ok is True
    prov.create_price.assert_not_called()
    # The catalogue number must equal what the live price object actually charges, never the
    # rung we would have chosen today.
    assert payload["pricePence"] == 2900
    assert payload["providerPriceId"] == LIVE_PRICE

    decision = dossier.candidate.tags["price_decision"]
    assert decision["applied"] is False, "an unapplied rung must not read as the live price"
    assert decision["live_price_pence"] == 2900


def test_the_catalogue_number_always_equals_what_the_price_object_charges(bridge):
    """The invariant behind both tests above, stated once: no drift, in either direction."""
    for live_amount in (1900, 4900, 12900):
        prov = _provisioner(ExistingPrice(LIVE_PRODUCT, live_amount, "gbp"))
        _, payload = _publish(bridge, _dossier("c2-reuse", "venture", "us"),
                              existing=_live_row(price_pence=live_amount), prov=prov)
        assert payload["pricePence"] == live_amount


# --------------------------------------------------------------------------------------
# First publish is untouched — reuse must not become "never provision"
# --------------------------------------------------------------------------------------

def test_a_first_publish_still_mints_its_money_rail(bridge):
    prov = _provisioner(None)
    ok, payload = _publish(bridge, _dossier("c2-new", "venture", "us"),
                           existing=None, prov=prov)

    assert ok is True
    prov.create_product.assert_called_once()
    prov.create_price.assert_called_once()
    prov.describe_price.assert_not_called(), "nothing to look up on a first publish"
    assert payload["providerPriceId"] == "price_NEW_should_not_exist"


def test_a_stub_price_id_is_not_a_money_rail_and_is_replaced(bridge):
    """A pack that was published without keys carries `price_stub_*`, which cannot bill.

    Reusing that would pin the pack permanently unlistable, so a stub is treated as no rail
    at all — the one case where a republish SHOULD mint.
    """
    prov = _provisioner(None)
    ok, payload = _publish(bridge, _dossier("c2-stub", "venture", "us"),
                           existing=_live_row(price_id="price_stub_c2stub"), prov=prov)

    assert ok is True
    prov.create_price.assert_called_once()
    assert payload["providerPriceId"] == "price_NEW_should_not_exist"


# --------------------------------------------------------------------------------------
# Fail closed: when the live rail cannot be established, publish nothing
# --------------------------------------------------------------------------------------

def test_a_price_the_provider_cannot_confirm_refuses_the_republish(bridge):
    """Unverifiable is not permission to mint. Both alternatives here are worse than stopping:
    minting repoints checkout, and writing the id unverified asserts something we cannot see.
    """
    prov = _provisioner(None)  # describe_price -> None
    ok, payload = _publish(bridge, _dossier("c2-reuse", "venture", "us"),
                           existing=_live_row(), prov=prov)

    assert ok is False
    prov.create_product.assert_not_called()
    prov.create_price.assert_not_called()
    assert payload is None, "a refused republish must not write a catalogue row"


def test_a_keyless_run_never_clobbers_a_live_pack_with_a_stub(bridge):
    """Before the fix this was the loudest damage available: a publish run with no provider
    key overwrote a LIVE pack's real ids with `prov_stub_*`/`price_stub_*` and unlisted it,
    because the upsert assigns both ids unconditionally (Program.cs:489-490).
    """
    ok, payload = _publish(bridge, _dossier("c2-reuse", "venture", "us"),
                           existing=_live_row(), prov=None)

    assert ok is False
    assert payload is None


# --------------------------------------------------------------------------------------
# The provider-side lookup that makes all of the above possible
# --------------------------------------------------------------------------------------

def _stripe_provisioner(retrieve):
    """A StripeProvisioner around a fake SDK, so these run with no stripe package or key."""
    p = object.__new__(StripeProvisioner)
    fake = MagicMock()
    fake.Price.retrieve = retrieve
    fake.error.StripeError = _StripeError
    p._stripe = fake
    return p


class _StripeError(Exception):
    pass


def test_describe_price_resolves_product_amount_and_currency():
    p = _stripe_provisioner(lambda pid: {"product": LIVE_PRODUCT, "unit_amount": 4900,
                                         "currency": "gbp"})
    assert p.describe_price(LIVE_PRICE) == ExistingPrice(LIVE_PRODUCT, 4900, "gbp")


def test_describe_price_handles_an_expanded_product_object():
    """`Price.retrieve` returns the product as an id, or as the object when expanded."""
    p = _stripe_provisioner(lambda pid: {"product": {"id": LIVE_PRODUCT, "name": "Pack"},
                                         "unit_amount": 4900, "currency": "gbp"})
    assert p.describe_price(LIVE_PRICE).product_id == LIVE_PRODUCT


def test_describe_price_returns_none_when_stripe_errors():
    """A failed lookup must not raise into the publish path; the caller fails closed on None."""
    def boom(pid):
        raise _StripeError("no such price")

    assert _stripe_provisioner(boom).describe_price(LIVE_PRICE) is None


def test_describe_price_returns_none_on_an_incomplete_price():
    p = _stripe_provisioner(lambda pid: {"product": None, "unit_amount": None})
    assert p.describe_price(LIVE_PRICE) is None

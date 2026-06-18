import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the prospector directory to the path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from prospector.models import Candidate, Dossier, Decision, ScoreResult
from prospector.bridge import EngineBridge, ProductProvisioner, StripeProvisioner, PaddleClient, ProvisioningError

class TestEngineBridge(unittest.TestCase):
    def setUp(self):
        # The bridge now fails closed without an internal key (no committed default), so the
        # publish path must be given one explicitly — exactly as production does via env.
        os.environ["STORE_INTERNAL_API_KEY"] = "test-internal-key"
        self.cfg = MagicMock()
        self.bridge = EngineBridge(self.cfg)
        # Point to the local test server
        self.bridge.store_api_url = "http://localhost:5050"

    @patch("requests.post")
    def test_publish_pass(self, mock_post):
        # Mock the entitlements check to pass (separate from the catalog API call)
        self.bridge.entitlements_check = MagicMock(return_value=True)

        # Mock successful response for the catalog API call
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"

        # 1. Create a mock dossier
        candidate = Candidate(
            title="AI Fuel Duty Automation",
            one_liner="SaaS to reclaim fuel duty for fleets",
            why_now="2024 HMRC rule change"
        )
        candidate.candidate_id = "test-cand-123"
        candidate.tags = {
            "artifacts": {
                "build_spec": "Test build spec content",
                "gtm_plan": "Test GTM plan content",
                "ops_plan": "Test ops plan content",
                "financial_model": "Test financial model content"
            },
            "marketing": [
                {"type": "listing_page", "copy": "This is the listing page copy."}
            ]
        }
        
        dossier = MagicMock(spec=Dossier)
        dossier.decision = Decision.PASS
        dossier.candidate = candidate
        dossier.score = MagicMock(spec=ScoreResult)
        dossier.score.composite = 4.2
        dossier.score.scores = {axis: 4 for axis in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]}
        dossier.score.justification = {axis: "Test justification" for axis in ["pain_acuity", "money_provability", "automatability", "distribution", "defensibility", "build_feasibility"]}
        dossier.checks = []
        dossier.adversarial = None
        dossier.gate_fired = None
        dossier.reason = "Survived all gates; composite 4.2."
        dossier.provider_chain = "test-chain"
        dossier.model_version = "test-model"
        dossier.created_at = "2026-06-15T00:00:00Z"
        dossier.reverify_due_at = "2026-07-15T00:00:00Z"
        dossier.provisional = False

        # 2. Call the bridge
        success = self.bridge.publish_pass(dossier)
        
        # 3. Assertions
        self.assertTrue(success, "Bridge should successfully publish a non-provisional PASS dossier")

        # Check if zip exists
        zip_path = Path("publish/bundles/test-cand-123/prospector_pack_test-can.zip")
        self.assertTrue(zip_path.exists(), f"Bundle zip should be created at {zip_path}")

    @patch("requests.post")
    def test_refuse_provisional_pass(self, mock_post):
        """A PASS dossier stamped provisional=true must be refused publication."""
        candidate = Candidate(
            title="Provisional Biz",
            one_liner="Provisional ruling candidate"
        )
        candidate.candidate_id = "test-provisional-cand"

        dossier = MagicMock(spec=Dossier)
        dossier.decision = Decision.PASS
        dossier.candidate = candidate
        dossier.score = None
        dossier.checks = []
        dossier.adversarial = None
        dossier.gate_fired = None
        dossier.reason = "Provisional PASS — fallback brain ruled."
        dossier.model_version = "test-model"
        dossier.created_at = "2026-06-15T00:00:00Z"
        dossier.provisional = True

        # Call the bridge — should refuse to publish
        success = self.bridge.publish_pass(dossier)

        self.assertFalse(success, "Bridge must refuse to publish a provisional PASS dossier")
        # Ensure _update_catalog was NEVER called
        mock_post.assert_not_called()


class TestProductProvisionerProtocol(unittest.TestCase):
    """ProductProvisioner is the seam for provider-agnostic product creation
    (P3 — replaces the hardcoded Paddle-only path).
    """

    def test_protocol_has_required_methods(self):
        # Protocol declares the contract; duck-typed classes must implement it.
        for method in ("create_product", "create_price"):
            self.assertTrue(
                hasattr(ProductProvisioner, method),
                f"ProductProvisioner must declare {method!r}"
            )

    def test_paddleclient_satisfies_protocol(self):
        # PaddleClient is the legacy provider — must still satisfy the seam.
        self.assertTrue(hasattr(PaddleClient, "create_product"))
        self.assertTrue(hasattr(PaddleClient, "create_price"))
        # Both accept (name/description) / (product_id/amount_pence)
        import inspect
        ps = inspect.signature(PaddleClient.create_product).parameters
        self.assertIn("name", ps)
        self.assertIn("description", ps)
        ps = inspect.signature(PaddleClient.create_price).parameters
        self.assertIn("product_id", ps)
        self.assertIn("amount_pence", ps)

    def test_stripeprovisioner_satisfies_protocol(self):
        self.assertTrue(hasattr(StripeProvisioner, "create_product"))
        self.assertTrue(hasattr(StripeProvisioner, "create_price"))
        import inspect
        ps = inspect.signature(StripeProvisioner.create_product).parameters
        self.assertIn("name", ps)
        self.assertIn("description", ps)
        ps = inspect.signature(StripeProvisioner.create_price).parameters
        self.assertIn("product_id", ps)
        self.assertIn("amount_pence", ps)


class TestProviderSelection(unittest.TestCase):
    """EngineBridge.provisioner must select by active_provider config."""

    def _make_bridge(self, active_provider="paddle",
                     paddle_key="paddle-test", stripe_key=None):
        cfg = MagicMock()
        cfg.store_payments = {"active_provider": active_provider}
        with patch.dict(os.environ, {"PADDLE_API_KEY": paddle_key}, clear=False):
            if stripe_key:
                with patch.dict(os.environ, {"STRIPE_API_KEY": stripe_key}):
                    return EngineBridge(cfg)
            return EngineBridge(cfg)

    def test_default_provider_is_paddle(self):
        b = self._make_bridge()
        self.assertEqual(b.active_provider, "paddle")
        self.assertIs(b.provisioner, b.paddle)

    def test_stripe_provider_selected_via_config(self):
        b = self._make_bridge(active_provider="stripe", stripe_key="sk_test_abc")
        self.assertEqual(b.active_provider, "stripe")
        self.assertIs(b.provisioner, b.stripe)

    def test_paddle_provider_selected_via_config(self):
        b = self._make_bridge(active_provider="paddle")
        self.assertEqual(b.active_provider, "paddle")
        self.assertIs(b.provisioner, b.paddle)

    def test_no_api_key_yields_none_provisioner(self):
        # No keys set at all — provisioner must be None (no crash, no fake).
        cfg = MagicMock()
        cfg.store_payments = {"active_provider": "paddle"}
        with patch.dict(os.environ, {}, clear=True):
            # Patched env with no PADDLE_API_KEY / STRIPE_API_KEY
            b = EngineBridge(cfg)
            # Paddle is None because no key
            self.assertIsNone(b.paddle)
            self.assertIsNone(b.provisioner)


class TestStripeProvisionerHardening(unittest.TestCase):
    """The former known gaps are now closed: create_product/create_price pass an
    idempotency_key (retry-safe — a publish retry reuses the Stripe-side object instead of
    duplicating it), and Stripe SDK errors are translated to a domain ProvisioningError.
    These tests verify the behaviour against a mocked Stripe client.
    """

    def _provisioner(self):
        # Build without __init__ (which would import stripe and set a real api_key), then
        # inject a mock client. The real stripe.error hierarchy is kept so the except
        # clauses in StripeProvisioner actually match.
        import stripe
        p = StripeProvisioner.__new__(StripeProvisioner)
        p._stripe = MagicMock()
        p._stripe.error = stripe.error
        return p

    def test_create_product_passes_idempotency_key(self):
        p = self._provisioner()
        p._stripe.Product.create.return_value = MagicMock(id="prod_123")
        pid = p.create_product("Name", "Desc", {"pack_id": "cand-9"})
        self.assertEqual(pid, "prod_123")
        self.assertEqual(
            p._stripe.Product.create.call_args.kwargs["idempotency_key"],
            "prospector-product-cand-9",
        )

    def test_create_price_passes_idempotency_key(self):
        p = self._provisioner()
        p._stripe.Price.create.return_value = MagicMock(id="price_123")
        rid = p.create_price("prod_123", 3000, "gbp")
        self.assertEqual(rid, "price_123")
        self.assertIn("idempotency_key", p._stripe.Price.create.call_args.kwargs)

    def test_stripe_error_becomes_provisioning_error(self):
        import stripe
        p = self._provisioner()
        p._stripe.Product.create.side_effect = stripe.error.APIConnectionError("boom")
        with self.assertRaises(ProvisioningError):
            p.create_product("Name", "Desc", {"pack_id": "cand-9"})


if __name__ == "__main__":
    unittest.main()

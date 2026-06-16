import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the prospector directory to the path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from prospector.models import Candidate, Dossier, Decision, ScoreResult
from prospector.bridge import EngineBridge, ProductProvisioner, StripeProvisioner, PaddleClient

class TestEngineBridge(unittest.TestCase):
    def setUp(self):
        self.cfg = MagicMock()
        self.bridge = EngineBridge(self.cfg)
        # Point to the local test server
        self.bridge.store_api_url = "http://localhost:5050"

    @patch("requests.post")
    def test_publish_pass(self, mock_post):
        # Mock successful response
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
        
        # 2. Call the bridge
        success = self.bridge.publish_pass(dossier)
        
        # 3. Assertions
        self.assertTrue(success, "Bridge should successfully publish a PASS dossier")

        # Check if zip exists
        zip_path = Path("publish/bundles/test-cand-123/prospector_pack_test-can.zip")
        self.assertTrue(zip_path.exists(), f"Bundle zip should be created at {zip_path}")


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


class TestStripeProvisionerKnownGaps(unittest.TestCase):
    """Document the known gaps in StripeProvisioner so they're explicit
    (and discoverable), not silently lurking. These are not failing tests;
    they're TODOs that the next sprint should close.
    """

    def test_idempotency_key_NOT_set_on_create_product(self):
        """KNOWN GAP: StripeProvisioner.create_product does not pass an
        idempotency_key. A retry of publish_pass after a network error
        creates a duplicate Stripe product.

        Track: needs `idempotency_key=f"prospector-pack-{candidate_id}"` in
        the stripe.Product.create call. PaddleClient has the same gap.
        """
        import inspect
        source = inspect.getsource(StripeProvisioner.create_product)
        # The fix is to add `idempotency_key=...` to the .create() call.
        # Today it's not there — that is the bug.
        self.assertNotIn("idempotency_key", source,
            "REMINDER: this test exists to track the idempotency gap. "
            "If idempotency_key is now in the source, the gap is closed — "
            "delete this test.")

    def test_stripe_error_handling_NOT_present(self):
        """KNOWN GAP: StripeProvisioner does not catch stripe.error.StripeError
        and re-raise as a domain-specific exception. A Stripe API failure
        currently propagates as a raw stripe library error to the caller.

        Track: wrap the .create() calls in try/except stripe.error.StripeError,
        re-raise as ProvisioningError with the Stripe request_id for the
        audit trail.
        """
        import inspect
        source = inspect.getsource(StripeProvisioner.create_product)
        self.assertNotIn("stripe.error.StripeError", source,
            "REMINDER: this test exists to track the error-handling gap. "
            "If StripeError is now caught, the gap is closed.")


if __name__ == "__main__":
    unittest.main()

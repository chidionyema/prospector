"""The engine bridge, end to end: a PriceDecision must mint the provider Price and the
catalogue row together, because a drift between them charges the buyer and then fails the
fulfilment fence.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the prospector directory to the path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from prospector.bridge import (
    EngineBridge,
    ProductProvisioner,
    ProvisioningError,
    StripeProvisioner,
)
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict


class TestEngineBridge(unittest.TestCase):
    def setUp(self):
        # The bridge now fails closed without an internal key (no committed default), so the
        # publish path must be given one explicitly — exactly as production does via env.
        os.environ["STORE_INTERNAL_API_KEY"] = "test-internal-key"
        self.cfg = MagicMock()
        # Real numeric thresholds so the source-or-die guard runs real comparisons rather than
        # MagicMock ones. These mirror the REAL Config dataclass defaults (config.py:145, :155);
        # a mock that omits them let the bridge's guard silently diverge from the decision layer.
        self.cfg.thresholds.confidence_floor = 0.0
        self.cfg.thresholds.min_supported_confidence = 0.0
        self.cfg.thresholds.min_supported_to_pass = 1
        self.cfg.thresholds.moat_critical_checks = ["value_durability", "incumbency"]
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
        # A real PASS rests on grounded evidence (source-or-die): >=1 supported check AND at
        # least one of the LANE'S DECISIVE checks grounded. `pain_reality` alone is not decisive
        # for the venture lane, and a dossier carrying only that is exactly what
        # dossier.build_dossier KILLs as `moat_ungrounded` — the bridge published it anyway
        # until the two were made to share one function (ENGINE_AUDIT MEDIUM-HIGH #1).
        dossier.checks = [
            CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED,
                        confidence=0.8, rationale="grounded"),
            CheckResult(check_name="value_durability", verdict=Verdict.SUPPORTED,
                        confidence=0.8, rationale="grounded on the decisive dimension"),
        ]
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

    @patch("requests.post")
    def test_refuse_ungrounded_pass(self, mock_post):
        """Source-or-die backstop: a PASS with 0 grounded-supported checks must NOT publish.

        This is the exact stale class that put an ungrounded 'Probate Locker' pack live —
        decision=PASS, every check unverifiable, 0 sources. The bridge is the last fence.
        """
        self.bridge.entitlements_check = MagicMock(return_value=True)
        candidate = Candidate(title="Ungrounded Biz", one_liner="No evidence behind it")
        candidate.candidate_id = "test-ungrounded-cand"

        dossier = MagicMock(spec=Dossier)
        dossier.decision = Decision.PASS
        dossier.candidate = candidate
        dossier.score = None
        # Composite-passed but every check is unverifiable -> no grounding to stand on.
        dossier.checks = [
            CheckResult(check_name="pain_reality", verdict=Verdict.UNVERIFIABLE,
                        confidence=0.0, rationale="no passage"),
        ]
        dossier.adversarial = None
        dossier.gate_fired = None
        dossier.reason = "Survived all gates; composite 2.95."
        dossier.model_version = "test-model"
        dossier.created_at = "2026-06-15T00:00:00Z"
        dossier.provisional = False

        success = self.bridge.publish_pass(dossier)

        self.assertFalse(success, "Bridge must refuse to publish an ungrounded PASS dossier")
        mock_post.assert_not_called()


class TestProductProvisionerProtocol(unittest.TestCase):
    """ProductProvisioner is the seam for provider-agnostic product creation
    (P3 — replaces the hardcoded single-provider path).
    """

    def test_protocol_has_required_methods(self):
        # Protocol declares the contract; duck-typed classes must implement it.
        for method in ("create_product", "create_price"):
            self.assertTrue(
                hasattr(ProductProvisioner, method),
                f"ProductProvisioner must declare {method!r}"
            )

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

    def _make_bridge(self, active_provider=None, stripe_key=None):
        cfg = MagicMock()
        if active_provider is None:
            del cfg.store_payments  # no config key at all -> the env/default path
        else:
            cfg.store_payments = {"active_provider": active_provider}
        env = {"STRIPE_API_KEY": stripe_key} if stripe_key else {}
        with patch.dict(os.environ, env, clear=not stripe_key):
            return EngineBridge(cfg)

    def test_default_provider_is_stripe(self):
        # The default must match the Store's own default (MoneyRailConfigGate). If the two
        # ends of the money rail disagree about who is billing, a pack lists with ids the
        # Store cannot charge.
        b = self._make_bridge()
        self.assertEqual(b.active_provider, "stripe")

    def test_stripe_provider_selected_via_config(self):
        b = self._make_bridge(active_provider="stripe", stripe_key="sk_test_abc")
        self.assertEqual(b.active_provider, "stripe")
        self.assertIs(b.provisioner, b.stripe)

    def test_unknown_provider_yields_none_provisioner(self):
        # A provider we hold no key for must mint nothing. None makes the pack publish
        # UNLISTED; anything else would list it against a price id nobody can bill.
        b = self._make_bridge(active_provider="paddle", stripe_key="sk_test_abc")
        self.assertIsNone(b.provisioner)

    def test_no_api_key_yields_none_provisioner(self):
        # No keys set at all — provisioner must be None (no crash, no fake).
        b = self._make_bridge(active_provider="stripe")
        self.assertIsNone(b.stripe)
        self.assertIsNone(b.provisioner)


class TestStripeKeySelection(unittest.TestCase):
    """The publisher must mint prices in the account the deployed Store bills through.

    On 2026-07-31 it did not: STRIPE_API_KEY was a sandbox test key while the Store billed
    live, so 10 packs listed with well-formed price ids that account could not charge and
    every buy button returned HTTP 500. Shape checks cannot catch that — a test price id looks
    exactly like a live one — so the rule is enforced on key MODE against the target.
    """

    def _bridge(self, env):
        cfg = MagicMock()
        cfg.store_payments = {"active_provider": "stripe"}
        with patch.dict(os.environ, env, clear=True):
            return EngineBridge(cfg)

    def test_remote_catalog_refuses_a_test_key(self):
        # The exact production failure. No provisioner => the `priced` guard publishes the
        # pack UNLISTED, which is the safe end of the trade: invisible beats unbuyable.
        b = self._bridge({
            "STORE_API_URL": "https://api.mumchimp.com",
            "STRIPE_API_KEY": "sk_test_abc",
        })
        self.assertIsNone(b.stripe_api_key)
        self.assertIsNone(b.stripe)
        self.assertIsNone(b.provisioner)
        self.assertIn("without a live key", b.stripe_key_reason)

    def test_remote_catalog_prefers_the_live_key_even_when_both_are_set(self):
        # Both vars set is the normal developer state; the live catalogue must not get the
        # test one just because STRIPE_API_KEY is the older, more familiar name.
        b = self._bridge({
            "STORE_API_URL": "https://api.mumchimp.com",
            "STRIPE_API_KEY": "sk_test_abc",
            "STRIPE_LIVE_API_KEY": "sk_live_xyz",
        })
        self.assertEqual(b.stripe_api_key, "sk_live_xyz")
        self.assertIsNotNone(b.provisioner)

    def test_remote_catalog_accepts_a_live_key_under_the_legacy_name(self):
        b = self._bridge({
            "STORE_API_URL": "https://api.mumchimp.com",
            "STRIPE_API_KEY": "sk_live_only",
        })
        self.assertEqual(b.stripe_api_key, "sk_live_only")

    def test_local_store_still_takes_a_test_key(self):
        # Developing against localhost with a sandbox key is the normal case, not a fault;
        # the guard must not make local work impossible.
        b = self._bridge({
            "STORE_API_URL": "http://localhost:5291",
            "STRIPE_API_KEY": "sk_test_abc",
        })
        self.assertEqual(b.stripe_api_key, "sk_test_abc")
        self.assertIsNotNone(b.provisioner)


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
        """The key is keyed on the pack AND the request parameters.

        This test used to pin the literal "prospector-product-cand-9". That literal WAS the
        defect: a Stripe idempotency key is remembered for 24h and replaying it with
        different parameters is a hard error, not a no-op, and this product's `name` and
        `description` are the pack's own copy. Measured 2026-08-08, packs 13795bea31feee47
        and 2abc23c3c0d05bab both failed with "Keys for idempotent requests can only be used
        with the same parameters they were first used with" after a copy fix, leaving two
        packs that could never list. So assert the PROPERTY the key exists for, not the
        string: a pack-scoped prefix, and the same key for the same request.
        """
        p = self._provisioner()
        p._stripe.Product.create.return_value = MagicMock(id="prod_123")
        pid = p.create_product("Name", "Desc", {"pack_id": "cand-9"})
        self.assertEqual(pid, "prod_123")
        key = p._stripe.Product.create.call_args.kwargs["idempotency_key"]
        self.assertTrue(key.startswith("prospector-product-cand-9-"), key)

        # Retry-safety, the property the key is FOR: an identical request never mints twice.
        p.create_product("Name", "Desc", {"pack_id": "cand-9"})
        self.assertEqual(p._stripe.Product.create.call_args.kwargs["idempotency_key"], key)

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

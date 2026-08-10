"""The gate-only rehearsal must answer "would this sell?" without touching the money rail.

Why these tests exist. Before 2026-08-09 the deterministic verdict on a pack — the
`validate_pack` + `audit_bundle` + `lint_pack` triple that decides `is_listed` — was only
ever produced as a SIDE EFFECT of a real publish. So "why is this pack not selling?" was a
question you could only answer by minting a Stripe object. Measured that day: of the 17
republishable PASS dossiers whose stored artifacts already clear `validate_pack`, 9 had no
`store/dossiers/<id>.lint.json` at all and their blocker was simply unknown.

`dry_run=True` closes that gap, and the whole value of it rests on one property: it can only
ever do LESS than a publish. These tests pin that property at the seam where it could
regress — an edit that moves the early return one line later would put `price_for` (the
first step of the money rail) inside a rehearsal, and this repo has already paid for orphan
Stripe products once (967457f).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector.bridge import EngineBridge
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict


def _dossier(candidate_id: str, *, financial_model: str = "Test financial model content"):
    candidate = Candidate(
        title="AI Fuel Duty Automation",
        one_liner="SaaS to reclaim fuel duty for fleets",
        why_now="2024 HMRC rule change",
    )
    candidate.candidate_id = candidate_id
    candidate.market = "uk"
    candidate.tags = {
        "artifacts": {
            "build_spec": "Test build spec content",
            "gtm_plan": "Test GTM plan content",
            "ops_plan": "Test ops plan content",
            "financial_model": financial_model,
        },
        "marketing": [
            {"type": "listing_page", "copy": "This is the listing page copy."}
        ],
    }
    axes = ["pain_acuity", "money_provability", "automatability",
            "distribution", "defensibility", "build_feasibility"]
    dossier = MagicMock(spec=Dossier)
    dossier.decision = Decision.PASS
    dossier.candidate = candidate
    dossier.score = MagicMock(spec=ScoreResult)
    dossier.score.composite = 4.2
    dossier.score.scores = {a: 4 for a in axes}
    dossier.score.justification = {a: "Test justification" for a in axes}
    # A PASS needs the LANE'S decisive check grounded, not merely one supported check:
    # dossier.py:167 mints Decision.PASS only when `moat_grounded >= 1` and KILLs
    # `moat_ungrounded` otherwise. This candidate carries ambition_tier="" — the default lane,
    # moat_critical_checks=[value_durability, incumbency] — so a lone non-decisive check
    # described a dossier the engine cannot produce.
    dossier.checks = [
        CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED,
                    confidence=0.8, rationale="grounded"),
        CheckResult(check_name="value_durability", verdict=Verdict.SUPPORTED,
                    confidence=0.8, rationale="grounded"),
    ]
    dossier.adversarial = None
    dossier.gate_fired = None
    dossier.reason = "Survived all gates; composite 4.2."
    dossier.provider_chain = "test-chain"
    dossier.model_version = "test-model"
    dossier.created_at = "2026-06-15T00:00:00Z"
    dossier.reverify_due_at = "2026-07-15T00:00:00Z"
    dossier.provisional = False
    return dossier


class TestDryRunMintsNothing(unittest.TestCase):
    def setUp(self):
        os.environ["STORE_INTERNAL_API_KEY"] = "test-internal-key"
        self._tmp = tempfile.TemporaryDirectory()
        self.store_dir = Path(self._tmp.name)
        self.cfg = MagicMock()
        self.cfg.thresholds.confidence_floor = 0.0
        # Real values, not MagicMocks: `store_dir` gates the lint-receipt write behind an
        # isinstance check, and `listing` is read as a dict. A MagicMock for either makes the
        # receipt assertion below vacuous rather than failing — the expensive kind of green.
        self.cfg.store_dir = str(self.store_dir)
        self.cfg.listing = {}
        self.bridge = EngineBridge(self.cfg)
        self.bridge.store_api_url = "http://localhost:5050"
        self.bridge.entitlements_check = MagicMock(return_value=True)
        # Both provisioners and the object store, so the assertion does not depend on which
        # provider happens to be active in this environment.
        self.bridge.stripe = MagicMock()
        self.bridge.paddle = MagicMock()
        self.bridge.r2 = MagicMock()

    def tearDown(self):
        self._tmp.cleanup()

    @patch("requests.get")
    @patch("requests.post")
    def test_a_dry_run_mints_no_price_uploads_nothing_and_writes_no_catalogue_row(
            self, mock_post, mock_get):
        """The property the whole flag rests on: strictly fewer side effects than a publish."""
        with patch("prospector.bridge.price_for") as mock_price_for:
            self.bridge.publish_pass(_dossier("dry-cand-001"), dry_run=True)

        # price_for is the FIRST step of the money rail. The gate-only exit is placed above
        # it precisely so a rehearsal cannot reach it; if this fails, the early return has
        # drifted below the line it was put above.
        mock_price_for.assert_not_called()
        self.bridge.stripe.assert_not_called()
        self.bridge.paddle.assert_not_called()
        self.bridge.r2.upload.assert_not_called()
        # entitlements_check is mocked out, so any surviving POST would be the catalogue push.
        mock_post.assert_not_called()
        mock_get.assert_not_called()

    def test_a_dry_run_still_writes_the_lint_receipt(self):
        """The receipt is the entire deliverable — a silent rehearsal would be worthless."""
        self.bridge.publish_pass(_dossier("dry-cand-002"), dry_run=True)

        receipt = self.store_dir / "dossiers" / "dry-cand-002.lint.json"
        self.assertTrue(receipt.exists(), f"no lint receipt written at {receipt}")
        report = json.loads(receipt.read_text(encoding="utf-8"))
        for key in ("ok", "problems", "pack_complete", "bundle_missing", "bundle_stubs"):
            self.assertIn(key, report, f"lint receipt missing {key!r}")

    def test_a_dry_run_reports_the_currency_defect_rather_than_hiding_it(self):
        """A rehearsal that returned True for an unsellable pack would be worse than none.

        `$` amounts in a `uk` pack are a lint ERROR (`check_currency`), which is one of the
        two blockers actually holding the 2026-08-09 backlog off the shelf. The dry run must
        return False for it and name it in the receipt.
        """
        bad = _dossier(
            "dry-cand-003",
            financial_model="Revenue: $4,900 per month. Costs: $1,200 per month.",
        )
        content_ok = self.bridge.publish_pass(bad, dry_run=True)

        self.assertFalse(content_ok, "a pack with a currency error must not read as sellable")
        report = json.loads(
            (self.store_dir / "dossiers" / "dry-cand-003.lint.json").read_text(encoding="utf-8"))
        errors = " ".join(p["detail"] for p in report["problems"]
                          if p["severity"] == "error")
        self.assertIn("$", errors, f"currency defect not named in the receipt: {errors!r}")

    @patch("requests.get")
    @patch("requests.post")
    def test_the_real_path_is_unchanged_when_the_flag_is_absent(self, mock_post, mock_get):
        """dry_run defaults to False, so every existing caller keeps its behaviour.

        Reaching `price_for` is the proof that the early return did not leak into the
        default path — the failure mode of adding a gate is silently gating everything.
        """
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"
        with patch("prospector.bridge.price_for") as mock_price_for:
            mock_price_for.return_value = MagicMock(
                price_pence=4900, rationale="test", rung="r1",
                segment="s", evidence={}, currency="gbp")
            self.bridge.publish_pass(_dossier("dry-cand-004"))

        mock_price_for.assert_called_once()


class TestPublishWrapperDryRun(unittest.TestCase):
    """`publish()` must not leave the traces that mean "this pack went live"."""

    def setUp(self):
        os.environ["STORE_INTERNAL_API_KEY"] = "test-internal-key"
        self._tmp = tempfile.TemporaryDirectory()
        self.store_dir = Path(self._tmp.name)
        self.cfg = MagicMock()
        self.cfg.thresholds.confidence_floor = 0.0
        self.cfg.store_dir = str(self.store_dir)
        self.cfg.listing = {}

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_writes_no_listing_receipt_and_no_inflight_marker(self):
        """store/listings/ is read as authority by three consumers.

        `tools/backfill_missing_listings.sh` decides a pack is DONE purely from a file being
        present there, and `decay._queue_unlist` decides a killed pack was ever live the same
        way. A receipt minted by a rehearsal would make both of them wrong about a pack that
        was never published.
        """
        from publish.publish import publish

        with patch("publish.publish.EngineBridge") as MockBridge:
            MockBridge.return_value.publish_pass.return_value = True
            res = publish(_dossier("dry-cand-005"), self.cfg, dry_run=True)

        MockBridge.return_value.publish_pass.assert_called_once()
        self.assertTrue(
            MockBridge.return_value.publish_pass.call_args.kwargs.get("dry_run"),
            "the wrapper must forward dry_run to the bridge, not just skip its own writes")
        self.assertEqual(res["status"], "dry_run")
        self.assertTrue(res["content_ok"])
        self.assertFalse((self.store_dir / "listings" / "dry-cand-005.json").exists(),
                         "a rehearsal wrote a listing receipt")
        self.assertFalse((self.store_dir / "listings" / ".inflight").exists(),
                         "a rehearsal wrote an in-flight marker")


if __name__ == "__main__":
    unittest.main()

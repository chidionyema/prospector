"""`card_line` must survive the whole way to the Store API's catalog metadata.

The producer (`artifacts._normalize_listing`) and the consumer (the storefront's `Pack.cardLine`)
are each covered by their own tests, which is exactly why this one exists: a key-name typo in
`bridge.py` between them passes both suites and silently ships a storefront that never sees a
card line. This asserts against the real POST body the bridge sends.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from prospector.artifacts import _normalize_listing
from prospector.bridge import EngineBridge
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict

AXES = [
    "pain_acuity",
    "money_provability",
    "automatability",
    "distribution",
    "defensibility",
    "build_feasibility",
]


def _dossier(listing: dict, candidate_id: str) -> Dossier:
    candidate = Candidate(
        title="FuelClaim — reclaim fuel duty for small fleets",
        one_liner="SaaS to reclaim fuel duty for fleets",
        why_now="2024 HMRC rule change",
    )
    candidate.candidate_id = candidate_id
    candidate.tags = {
        "artifacts": {
            "build_spec": "Test build spec content",
            "gtm_plan": "Test GTM plan content",
            "ops_plan": "Test ops plan content",
            "financial_model": "Test financial model content",
        },
        # Through the real normaliser, so this test cannot pass on a shape the engine
        # never actually produces.
        "marketing": [_normalize_listing(listing)],
    }

    dossier = MagicMock(spec=Dossier)
    dossier.decision = Decision.PASS
    dossier.candidate = candidate
    dossier.score = MagicMock(spec=ScoreResult)
    dossier.score.composite = 4.2
    dossier.score.scores = {axis: 4 for axis in AXES}
    dossier.score.justification = {axis: "Test justification" for axis in AXES}
    dossier.checks = [
        CheckResult(
            check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.8, rationale="grounded"
        ),
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


class TestBridgeCardLine(unittest.TestCase):
    def setUp(self):
        os.environ["STORE_INTERNAL_API_KEY"] = "test-internal-key"
        cfg = MagicMock()
        cfg.thresholds.confidence_floor = 0.0
        self.bridge = EngineBridge(cfg)
        self.bridge.store_api_url = "http://localhost:5050"
        self.bridge.entitlements_check = MagicMock(return_value=True)

    def _published_metadata(self, listing: dict, candidate_id: str) -> dict:
        """The catalog registration payload the bridge actually POSTs.

        Per-pack metadata is FLATTENED onto the top-level payload by `_update_catalog`
        (`payload.setdefault(k, v)`), so the assertion is against the wire body itself rather
        than a nested object that does not exist.
        """
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = "OK"
            self.assertTrue(self.bridge.publish_pass(_dossier(listing, candidate_id)))

            for call in mock_post.call_args_list:
                payload = call.kwargs.get("json") or {}
                if isinstance(payload, dict) and "title" in payload:
                    return payload
        self.fail("no catalog registration POST was made")

    def test_card_line_reaches_the_store_api(self):
        meta = self._published_metadata(
            {"card_line": "Reclaim fuel duty for small haulage fleets", "copy": "Listing copy."},
            "test-cardline-ok",
        )
        self.assertEqual(meta.get("cardLine"), "Reclaim fuel duty for small haulage fleets")

    def test_an_over_length_card_line_is_omitted_not_truncated(self):
        # The load-bearing assertion: NO prefix of the rejected line reaches the wire. A
        # truncating implementation would send the first 60 characters here.
        meta = self._published_metadata(
            {"card_line": "z" * 200, "copy": "Listing copy."},
            "test-cardline-long",
        )
        self.assertNotIn("cardLine", meta)
        self.assertNotIn("zzz", str(meta))

    def test_an_absent_card_line_is_omitted_from_the_wire_entirely(self):
        # Not sent as "" — omitted. `bridge.py:433` strips empty values so a republish never
        # blanks a field the Store already holds (the same rule that stops a facet-light
        # republish untagging a pack the backfill tagged). The storefront types `cardLine`
        # optional and `cardHeading` falls back to the title, so absent is a handled state.
        meta = self._published_metadata({"copy": "Listing copy."}, "test-cardline-absent")
        self.assertNotIn("cardLine", meta)


if __name__ == "__main__":
    unittest.main()

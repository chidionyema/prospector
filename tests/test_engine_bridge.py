import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the prospector directory to the path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from prospector.models import Candidate, Dossier, Decision, ScoreResult
from prospector.bridge import EngineBridge

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

if __name__ == "__main__":
    unittest.main()

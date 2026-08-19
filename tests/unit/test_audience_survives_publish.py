"""The audience persona must survive BOTH boundaries: the SQLite index and the catalogue row.

Generation stamps `candidate.tags["audience"]` (generate.py:552) and, until this landed, both
downstream boundaries dropped it — the index had no column and `bridge._update_catalog` never
put it on the wire. Nothing could learn per-persona because the persona did not survive publish.

The two seams are tested together on purpose. They read the SAME normaliser
(`Candidate.audience`), and the failure this guards against is not either one being broken
outright but the two disagreeing: if the index stored `"SMB_Owner"` and the catalogue row
`"smb_owner"`, every join between engine yield and storefront conversion would silently split
one persona into two cohorts, and each suite would still be green on its own.
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
from prospector.store import Store

AXES = [
    "pain_acuity",
    "money_provability",
    "automatability",
    "distribution",
    "defensibility",
    "build_feasibility",
]


def _candidate(audience, candidate_id="test-audience"):
    """A candidate carrying `audience` in tags, exactly as generation writes it.

    `audience` is passed through untouched (including None and odd casing) so the tests can
    assert on the normaliser rather than on a pre-cleaned fixture.
    """
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
        "marketing": [_normalize_listing({"copy": "Listing copy."})],
    }
    if audience is not None:
        candidate.tags["audience"] = audience
    return candidate


def _dossier(candidate) -> Dossier:
    dossier = MagicMock(spec=Dossier)
    dossier.decision = Decision.PASS
    dossier.candidate = candidate
    dossier.score = MagicMock(spec=ScoreResult)
    dossier.score.composite = 4.2
    dossier.score.scores = {axis: 4 for axis in AXES}
    dossier.score.justification = {axis: "Test justification" for axis in AXES}
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
    dossier.dense_reward = 0.0
    dossier.persona = ""
    return dossier


class TestAudienceNormaliser(unittest.TestCase):
    """`Candidate.audience` is the single reader both boundaries share."""

    def test_it_is_case_and_whitespace_normalised(self):
        self.assertEqual(_candidate("  SMB_Owner ").audience, "smb_owner")

    def test_an_unstamped_candidate_reports_empty_not_a_guess(self):
        # 26 of the 1436 dossiers on disk are in this state. Empty means "generation did not
        # stamp one" — inventing a default would create a cohort nobody generated for.
        self.assertEqual(_candidate(None).audience, "")

    def test_a_value_outside_the_configured_list_is_kept(self):
        # Deliberately unvalidated: `generation.audience_forms` is operator-editable, and
        # rejecting unknown members would blank the field on every publish after a rename.
        self.assertEqual(_candidate("newly_added_persona").audience, "newly_added_persona")

    def test_it_does_not_duplicate_itself_into_the_dossier_json(self):
        # A property, not a field. If it became a field, every dossier on disk would grow a
        # second copy of a value it already carries under `tags`, free to drift from it.
        self.assertNotIn("audience", _candidate("smb_owner").to_dict())


class TestAudienceReachesTheCatalogueRow(unittest.TestCase):
    def setUp(self):
        # `patch.dict` and not a raw `os.environ[...] =`: a raw assignment in setUp survives
        # the test and every test after it in the same xdist worker, and the test that then
        # fails is somebody else's. On 2026-08-19 a process-wide PROSPECTOR_STORE_DIR left
        # behind by `ops/automations/log_rotation.py` failed eight tests in three unrelated
        # files, on CI only. `tests/conftest.py` now fails the leaking test by name, which is
        # how this one was found.
        env = patch.dict(os.environ, {"STORE_INTERNAL_API_KEY": "test-internal-key"})
        env.start()
        self.addCleanup(env.stop)
        cfg = MagicMock()
        cfg.thresholds.confidence_floor = 0.0
        self.bridge = EngineBridge(cfg)
        self.bridge.store_api_url = "http://localhost:5050"
        self.bridge.entitlements_check = MagicMock(return_value=True)

    def _published_payload(self, audience, candidate_id) -> dict:
        """The catalog registration body the bridge actually POSTs.

        Metadata is flattened onto the top-level payload by `_update_catalog`
        (`payload.setdefault(k, v)`), so this asserts against the wire body itself.
        """
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = "OK"
            self.assertTrue(
                self.bridge.publish_pass(_dossier(_candidate(audience, candidate_id)))
            )
            for call in mock_post.call_args_list:
                payload = call.kwargs.get("json") or {}
                if isinstance(payload, dict) and "title" in payload:
                    return payload
        self.fail("no catalog registration POST was made")

    def test_the_persona_reaches_the_store_api(self):
        payload = self._published_payload("primary_carer", "test-audience-ok")
        self.assertEqual(payload.get("audience"), "primary_carer")

    def test_it_is_normalised_on_the_wire(self):
        # The Store stores this verbatim; normalising here is what keeps the catalogue's
        # spelling identical to the index's, so the two can be joined.
        payload = self._published_payload("  Primary_Carer  ", "test-audience-case")
        self.assertEqual(payload.get("audience"), "primary_carer")

    def test_an_absent_persona_is_omitted_from_the_wire_entirely(self):
        # Omitted, NOT sent as "". The Store's apply block only overwrites what it was sent
        # (`if (request.Audience is not null)`), so "" would blank a stored persona on a
        # metadata-light republish, while absent leaves it alone.
        payload = self._published_payload(None, "test-audience-absent")
        self.assertNotIn("audience", payload)


def _real_dossier(candidate) -> Dossier:
    """A genuine Dossier, not a MagicMock.

    `Store.save` writes `dossier.to_json()` to disk before it touches the index, so the index
    tests have to use the real serialiser — a mock would make the on-disk half of `save` a
    no-op and the test would stop covering the path it names.
    """
    return Dossier(
        candidate=candidate,
        decision=Decision.PASS,
        reason="Survived all gates.",
        created_at="2026-06-15T00:00:00Z",
        reverify_due_at="2026-07-15T00:00:00Z",
    )


class TestAudienceReachesTheIndex(unittest.TestCase):
    def _store(self) -> Store:
        import tempfile

        cfg = MagicMock()
        # A tempdir, never the live store: tests writing into store/ is how the production
        # audit log got polluted before.
        self._tmp = tempfile.TemporaryDirectory()
        cfg.store_dir = Path(self._tmp.name)
        return Store(cfg)

    def _saved_row(self, audience, candidate_id):
        store = self._store()
        store.save(_real_dossier(_candidate(audience, candidate_id)))
        with store._connect() as conn:
            return conn.execute(
                "SELECT audience FROM dossiers WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()

    def test_the_persona_is_indexed(self):
        self.assertEqual(self._saved_row("gen_z_worker", "idx-ok")["audience"], "gen_z_worker")

    def test_it_is_normalised_identically_to_the_wire(self):
        self.assertEqual(self._saved_row("  Gen_Z_Worker ", "idx-case")["audience"],
                         "gen_z_worker")

    def test_an_unstamped_dossier_indexes_empty_string_not_null(self):
        # Empty string, never NULL, matching `market` and `persona`. A column holding both ''
        # and NULL for the same meaning splits every GROUP BY into two buckets, and the
        # per-persona question this column exists to answer is a GROUP BY.
        self.assertEqual(self._saved_row(None, "idx-absent")["audience"], "")

    def test_the_column_is_indexed_for_grouping(self):
        store = self._store()
        with store._connect() as conn:
            names = {r["name"] for r in conn.execute("PRAGMA index_list(dossiers)")}
        self.assertIn("idx_audience", names)


if __name__ == "__main__":
    unittest.main()

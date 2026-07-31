"""A published bundle must be structurally complete — every file present and non-stub.

Two proven failure modes this pins:

1. `_add_to_zip` writes nothing when content is empty, so a tier that silently returned ""
   produced a zip with the file ABSENT. Real example: publish/bundles/af1647af*/*.zip had no
   01/02/03; seven 2026-06-18 bundles had 5 of 8 files.
2. The Marketing_Assets loop appended a `##` heading per marketing piece even when `copy` was
   empty, so an all-empty list produced exactly `"# Marketing Assets\n\n"` — 20 bytes. Seen as
   late as 2026-07-30 22:21 (publish/bundles/a03a2ba0*).
"""
from __future__ import annotations

import zipfile

import pytest

from prospector.bridge import BUNDLE_FILES, EngineBridge, _MIN_BUNDLE_ENTRY_BYTES
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """_create_bundle writes to a relative publish/bundles path — keep it out of the repo."""
    monkeypatch.chdir(tmp_path)

    class _Cfg:
        entitlements_api_key = ""
        store_payments = {"active_provider": "stripe"}

    return EngineBridge(_Cfg())


def _dossier():
    cand = Candidate(
        candidate_id="b" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    check = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance (SAGB, 2025).",
        citations=[], sources=[], queries=[],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check],
                   created_at="2026-07-31T00:00:00Z")


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    return {k: f"# {k}\n\n{body}" for k in
            ("build_spec", "gtm_plan", "ops_plan", "financial_model")}


def _entries(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {i.filename: i.file_size for i in zf.infolist()}


class TestCompleteBundle:
    def test_all_eight_files_present(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert path is not None
        assert set(_entries(path)) == set(BUNDLE_FILES)

    def test_no_entry_is_a_stub(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        for name, size in _entries(path).items():
            assert size >= _MIN_BUNDLE_ENTRY_BYTES, f"{name} is {size}b"


class TestMissingArtifactsStillProduceAllEightFiles:
    """REGRESSION: empty prose used to make the file vanish from the zip entirely."""

    @pytest.mark.parametrize("dropped", ["build_spec", "gtm_plan", "ops_plan"])
    def test_empty_artifact_becomes_an_honest_placeholder(self, bridge, dropped):
        artifacts = _full_artifacts()
        artifacts[dropped] = ""
        path = bridge._create_bundle(_dossier(), artifacts, [])
        entries = _entries(path)
        assert set(entries) == set(BUNDLE_FILES), f"dropping {dropped} lost a file"
        assert all(s >= _MIN_BUNDLE_ENTRY_BYTES for s in entries.values())

    def test_placeholder_invents_nothing(self, bridge):
        artifacts = _full_artifacts()
        artifacts["ops_plan"] = ""
        path = bridge._create_bundle(_dossier(), artifacts, [])
        with zipfile.ZipFile(path) as zf:
            text = zf.read("03_Operations_Plan.md").decode()
        assert "not generated" in text.lower()
        assert "held back from sale" in text.lower()

    def test_every_artifact_missing_still_yields_eight_files(self, bridge):
        path = bridge._create_bundle(_dossier(), {}, [])
        assert set(_entries(path)) == set(BUNDLE_FILES)


class TestMarketingAssetsNeverAStub:
    def test_empty_marketing_list_is_filled_by_the_floor(self, bridge):
        """REGRESSION: this is the exact input that produced the 20-byte file."""
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        size = _entries(path)["Marketing_Assets.md"]
        assert size > 20, "20 bytes is the bare '# Marketing Assets' header"
        assert size >= _MIN_BUNDLE_ENTRY_BYTES

    def test_pieces_with_empty_copy_do_not_emit_headings(self, bridge):
        marketing = [
            {"type": "social_post", "copy": ""},
            {"type": "launch_email", "copy": "   "},
        ]
        path = bridge._create_bundle(_dossier(), _full_artifacts(), marketing)
        with zipfile.ZipFile(path) as zf:
            text = zf.read("Marketing_Assets.md").decode()
        assert "## Social Post" not in text
        assert "## Launch Email" not in text
        # the floor still supplied a real listing page
        assert len(text) >= _MIN_BUNDLE_ENTRY_BYTES

    def test_real_pieces_are_kept(self, bridge):
        marketing = [{"type": "launch_email", "copy": "Real email body with substance."}]
        path = bridge._create_bundle(_dossier(), _full_artifacts(), marketing)
        with zipfile.ZipFile(path) as zf:
            text = zf.read("Marketing_Assets.md").decode()
        assert "## Launch Email" in text
        assert "Real email body with substance." in text

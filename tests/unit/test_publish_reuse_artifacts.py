"""`--reuse-artifacts` must re-bundle without calling a model.

Dossiers persist their generated prose under candidate.tags["artifacts"], but publish_passes
regenerated unconditionally (tools/publish_passes.py:132), so repairing a pack whose only
defect was a deterministic floor — a missing 00_Executive_Summary.md, a 20-byte
Marketing_Assets.md — cost a full LLM generation. Measured 2026-07-31: 17 of the 28 pending
packs have stored artifacts that already clear validate_pack, so this path repairs them free.
"""
from __future__ import annotations

import json

import pytest

import tools.publish_passes as pp


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """publish_passes with every model call and network call replaced by a counter."""
    calls = {"artifacts": 0, "marketing": 0, "published": []}

    def _fake_generate_artifacts(*a, **k):
        calls["artifacts"] += 1
        body = "## Section\n\nGenerated prose. " * 40
        return {k_: f"# {k_}\n\n{body}" for k_ in
                ("build_spec", "gtm_plan", "ops_plan", "financial_model")}

    def _fake_generate_marketing(*a, **k):
        calls["marketing"] += 1
        return [{"type": "listing_page", "copy": "Freshly generated listing copy. " * 5}]

    def _fake_publish(dossier, cfg):
        calls["published"].append(dossier.candidate.candidate_id)
        return {"status": "published", "candidate_id": dossier.candidate.candidate_id}

    class _Cfg:
        entitlements_api_key = "test-key"
        operator = ["mock"]
        artifact_operator = ["mock"]

    monkeypatch.setattr(pp, "generate_artifacts", _fake_generate_artifacts)
    monkeypatch.setattr(pp, "generate_marketing_content", _fake_generate_marketing)
    monkeypatch.setattr(pp, "publish", _fake_publish)
    monkeypatch.setattr(pp, "load_config", lambda *a, **k: _Cfg())
    monkeypatch.setattr(pp, "_load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(pp, "make_operator", lambda *a, **k: object())
    monkeypatch.setattr(pp, "_build_artifact_op", lambda *a, **k: object())
    monkeypatch.chdir(tmp_path)
    return calls


def _write_dossier(tmp_path, *, artifacts: dict | None) -> str:
    body = "## Section\n\nStored, moat-verified prose. " * 40
    arts = artifacts if artifacts is not None else {
        k: f"# {k}\n\n{body}" for k in
        ("build_spec", "gtm_plan", "ops_plan", "financial_model")
    }
    d = {
        "decision": "pass",
        "created_at": "2026-07-31T00:00:00Z",
        "candidate": {
            "candidate_id": "c" * 16,
            "title": "Stored Pack",
            "one_liner": "A pack whose prose is already on disk.",
            "market": "uk",
            "who_pays": "operators",
            "why_now": "rule change",
            "tags": {"artifacts": arts, "marketing": []},
        },
        "checks": [],
    }
    p = tmp_path / "dossier.pass.json"
    p.write_text(json.dumps(d))
    return str(p)


class TestReuseArtifacts:
    def test_no_model_call_when_stored_artifacts_are_complete(self, harness, tmp_path):
        path = _write_dossier(tmp_path, artifacts=None)
        rc = pp.main(["--reuse-artifacts", path])
        assert rc == 0
        assert harness["artifacts"] == 0, "regenerated despite complete stored artifacts"
        assert harness["marketing"] == 0
        assert harness["published"] == ["c" * 16]

    def test_falls_back_to_generation_when_stored_artifacts_are_incomplete(
        self, harness, tmp_path
    ):
        """Reuse must never publish a pack the completeness gate would reject."""
        path = _write_dossier(tmp_path, artifacts={"build_spec": "too short"})
        rc = pp.main(["--reuse-artifacts", path])
        assert rc == 0
        assert harness["artifacts"] == 1, "should have regenerated the incomplete pack"
        assert harness["published"] == ["c" * 16]

    def test_default_path_still_regenerates(self, harness, tmp_path):
        path = _write_dossier(tmp_path, artifacts=None)
        rc = pp.main([path])
        assert rc == 0
        assert harness["artifacts"] == 1, "reuse must be opt-in, not the default"

    def test_flag_is_not_treated_as_a_dossier_path(self, harness, tmp_path):
        path = _write_dossier(tmp_path, artifacts=None)
        pp.main(["--reuse-artifacts", path])
        assert harness["published"] == ["c" * 16]

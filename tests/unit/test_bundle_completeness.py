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
from pathlib import Path

import pytest

from prospector.bridge import (
    BUNDLE_FILES,
    EngineBridge,
    _MIN_BUNDLE_ENTRY_BYTES,
    audit_bundle,
)
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


# The financial model is never free prose in production: _validate_artifact_shape forces a
# dict and artifacts.py:258 renders it through _render_financial_model, so every real pack
# carries these sections and Python-computed (arithmetically exact) figures. The fixture
# mirrors that shape because the publish gate now lints it (pack_linter); a prose blob here
# would assert that a pack the pipeline cannot produce is sellable.
RENDERED_FINANCIAL_MODEL = """## Financial Model

### Revenue
- **Month 1:** £50 × 10 customers = **£500**
- **Month 12:** £50 × 120 customers = **£6,000**
- **Growth (M1→M12):** 12.0×

### Gross Margin: **88%** (COGS: 12% of revenue)
- **Per customer/month:** £44.00

### Payback Period
- **~2.3 months** (CAC £100 / gross margin £44.00/month)

### Customer Lifetime Value (CLV)
- ~**£1,000** (ARPU £50 / 5.0% monthly churn)

### LTV:CAC Ratio
- 10.0

### Month 1 P&L
- Revenue £500, COGS £60, gross profit £440.
"""


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    out = {k: f"# {k}\n\n{body}" for k in
           ("build_spec", "gtm_plan", "ops_plan", "financial_model")}
    out["financial_model"] = RENDERED_FINANCIAL_MODEL
    return out


def _entries(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {i.filename: i.file_size for i in zf.infolist()}


class TestCompleteBundle:
    def test_all_eight_files_present(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert path is not None
        # `<=` not `==`: the bundle also ships index.html (pack_html.py), a bonus reading
        # view that is deliberately NOT part of the BUNDLE_FILES sellability contract — see
        # test_bundle_index_html.py for that file's own coverage.
        assert set(BUNDLE_FILES) <= set(_entries(path))

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
        assert set(BUNDLE_FILES) <= set(entries), f"dropping {dropped} lost a file"
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
        assert set(BUNDLE_FILES) <= set(_entries(path))


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


class TestAuditBundle:
    """The audit the LISTING decision is made on.

    `validate_pack` reads the in-memory artifacts, so it cannot see a file that never reached
    the zip. That is not hypothetical: a03a2ba029b408a7 shipped 3 of 8 files with a 20-byte
    Marketing_Assets.md and was listed for sale anyway. `audit_bundle` reads the written
    artefact instead, and `publish_pass` ANDs it into `is_listed`.
    """

    def test_complete_bundle_audits_clean(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        assert audit_bundle(path) == ([], [])

    def test_missing_file_is_reported(self, tmp_path):
        path = tmp_path / "pack.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name in BUNDLE_FILES:
                if name == "05_First_Week_Checklist.md":
                    continue
                zf.writestr(name, "x" * (_MIN_BUNDLE_ENTRY_BYTES + 1))
        missing, stubs = audit_bundle(str(path))
        assert missing == ["05_First_Week_Checklist.md"]
        assert stubs == []

    def test_stub_entry_is_reported(self, tmp_path):
        """The exact a03a2ba0 shape: the file is present, and 20 bytes of it."""
        path = tmp_path / "pack.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name in BUNDLE_FILES:
                body = "# Marketing Assets\n\n" if name == "Marketing_Assets.md" else "x" * 500
                zf.writestr(name, body)
        missing, stubs = audit_bundle(str(path))
        assert missing == []
        assert stubs == ["Marketing_Assets.md=20b"]

    def test_absent_zip_counts_as_wholly_missing_rather_than_raising(self, tmp_path):
        # The caller uses this to decide listing; an audit that throws would take down the
        # register-unlisted retry path it exists to protect.
        missing, stubs = audit_bundle(str(tmp_path / "does-not-exist.zip"))
        assert missing == list(BUNDLE_FILES)
        assert stubs == []

    def test_corrupt_zip_counts_as_wholly_missing(self, tmp_path):
        path = tmp_path / "corrupt.zip"
        path.write_bytes(b"not a zip file at all")
        assert audit_bundle(str(path)) == (list(BUNDLE_FILES), [])


class _FakeProvisioner:
    def create_product(self, name, description, metadata):
        return "prod_real_123"

    def create_price(self, product_id, amount_pence, currency="gbp"):
        return "price_real_123"


@pytest.fixture
def publishing_bridge(monkeypatch, tmp_path):
    """A bridge with every gate but the bundle audit already satisfied.

    Entitlements, provisioning and upload are stubbed to SUCCEED deliberately: the point of
    these tests is that the bundle audit alone decides listing, so every other input has to be
    green or a False `is_listed` would prove nothing.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-internal-key")

    class _Thresholds:
        confidence_floor = 0.0

    class _Cfg:
        entitlements_api_key = "test-entitlements-key"
        store_payments = {"active_provider": "stripe"}
        thresholds = _Thresholds()
        listing = {"price_pence": 4900}

    b = EngineBridge(_Cfg())
    b.entitlements_check = lambda candidate_id: True
    b.stripe = _FakeProvisioner()
    b.r2.upload = lambda path, key: True

    calls: list[dict] = []

    def _capture(**kwargs):
        calls.append(kwargs)
        return True

    b._update_catalog = _capture
    b.catalog_calls = calls
    return b


def _pass_dossier_with_artifacts():
    d = _dossier()
    d.candidate.tags = {
        "artifacts": _full_artifacts(),
        "marketing": [{
            "type": "listing_page",
            "copy": "# Shellfish Classification Aid\n\nA scheduling aid for UK oyster farms "
                    "facing new sampling rules, sold as a one-off pack.",
        }],
    }
    return d


class TestIncompleteBundleCannotBeListed:
    """The listing gate, end to end.

    `validate_pack` reads the in-memory artifacts and passes in every test here — that is the
    hole. What decides listing is a re-read of the zip that was actually written.
    """

    def test_a_complete_bundle_is_listed(self, publishing_bridge):
        assert publishing_bridge.publish_pass(_pass_dossier_with_artifacts()) is True
        call = publishing_bridge.catalog_calls[-1]
        assert call["is_listed"] is True
        assert call["content_key"] and call["content_hash"]

    def test_a_bundle_missing_a_file_is_registered_unlisted(self, publishing_bridge, monkeypatch):
        def _deficient(self, dossier, artifacts, marketing):
            path = Path("publish/bundles/deficient.zip")
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "w") as zf:
                for name in BUNDLE_FILES:
                    if name == "05_First_Week_Checklist.md":
                        continue
                    zf.writestr(name, "x" * 500)
            return path

        monkeypatch.setattr(EngineBridge, "_create_bundle", _deficient)
        publishing_bridge.publish_pass(_pass_dossier_with_artifacts())

        call = publishing_bridge.catalog_calls[-1]
        # Registered (so the operator can retry) but NOT for sale, and with no content
        # pointer — a buyer must never be handed a key to a bundle we know is short.
        assert call["is_listed"] is False
        assert call["content_key"] is None
        assert call["content_hash"] is None

    def test_the_a03a2ba0_shape_is_registered_unlisted(self, publishing_bridge, monkeypatch):
        """The live defect: 3 of 8 files, one of them a 20-byte header, listed for sale."""
        def _stubbed(self, dossier, artifacts, marketing):
            path = Path("publish/bundles/stubbed.zip")
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("04_Financial_Model.md", "x" * 500)
                zf.writestr("Marketing_Assets.md", "# Marketing Assets\n\n")
                zf.writestr("QA_Report.md", "x" * 500)
            return path

        monkeypatch.setattr(EngineBridge, "_create_bundle", _stubbed)
        publishing_bridge.publish_pass(_pass_dossier_with_artifacts())
        assert publishing_bridge.catalog_calls[-1]["is_listed"] is False

    def test_validate_pack_alone_would_have_listed_it(self):
        """Proves the gap the audit closes rather than assuming it.

        If `validate_pack` failed on this input, the tests above would pass for the wrong
        reason and the audit could be deleted without anything going red.
        """
        from prospector.pack_validation import validate_pack

        d = _pass_dossier_with_artifacts()
        ok, problems = validate_pack(d.candidate.tags["artifacts"], d.candidate.tags["marketing"])
        assert ok, problems

"""A published bundle must be structurally complete — every file present and non-stub.

Two proven failure modes this pins:

1. `_add_to_zip` writes nothing when content is empty, so a tier that silently returned ""
   produced a zip with the file ABSENT. Real example: publish/bundles/af1647af*/*.zip had no
   01/02/03; seven 2026-06-18 bundles had 5 of 8 files.
2. The Marketing_Assets loop appended a `##` heading per marketing piece even when `copy` was
   empty, so an all-empty list produced exactly `"# Marketing Assets\n\n"` — 20 bytes. Seen as
   late as 2026-07-30 22:21 (publish/bundles/a03a2ba0*).

Both incidents happened when the archive WAS the eight markdown documents. Since 2026-08-15 the
documents are the render input and the archive holds the rendered pack (`BUNDLE_FILES` =
index.html, Complete_Pack.pdf, First_Fortnight.html, Assumptions.csv, Marketing_Assets.txt), so
the same two failure modes are asserted where they now land: an absent artifact reaches the
buyer as an honest placeholder INSIDE the reader, and the marketing floor is measured on
`Marketing_Assets.txt`, the one document that still ships as editable text.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from prospector.bridge import (
    _MIN_BUNDLE_ENTRY_BYTES,
    BUNDLE_FILES,
    EngineBridge,
    audit_bundle,
)
from prospector.marketing_assets import heading_for
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


class _Cfg:
    entitlements_api_key = ""
    store_payments = {"active_provider": "stripe"}


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """_create_bundle writes to a relative publish/bundles path — keep it out of the repo."""
    monkeypatch.chdir(tmp_path)
    return EngineBridge(_Cfg())


@pytest.fixture(scope="module")
def complete_bundle(tmp_path_factory) -> Path:
    """ONE bundle, built once, for every test whose input is the unmodified happy path.

    Four tests called `_create_bundle(_dossier(), _full_artifacts(), [])` with byte-identical
    arguments — `_dossier()` and `_full_artifacts()` take no parameters and are pure — and each
    call re-rendered the whole pack: `pack_html.render_pack_html` (bridge.py:1822) and
    `pack_pdf.render_pack_pdf` (bridge.py:1835). That is the same PDF produced four times to
    ask four different questions about it, and this file was 92.7s of the suite's slowest 30.

    Module scope is safe here for a checkable reason, not a hopeful one: every consumer only
    READS the zip (`_entries`, `audit_bundle`). Any future test that mutates the archive must
    take the function-scoped `bridge` fixture and build its own — sharing a mutable artefact
    across tests is how a suite starts depending on its own order, which this repo has already
    paid for once (see `tests/test_drain_moat_preflight.py`).

    `os.chdir` rather than `monkeypatch.chdir` because monkeypatch is function-scoped and would
    tear down under a module-scoped fixture. The path is resolved to an ABSOLUTE one before the
    cwd is restored — `_create_bundle` returns a path relative to the directory it ran in, so
    yielding it unresolved would hand every test a path that no longer points anywhere.
    """
    root = tmp_path_factory.mktemp("complete-bundle")
    cwd = Path.cwd()
    os.chdir(root)
    try:
        built = EngineBridge(_Cfg())._create_bundle(_dossier(), _full_artifacts(), [])
        assert built is not None, "the happy path produced no bundle at all"
        return Path(built).resolve()
    finally:
        os.chdir(cwd)


def _dossier():
    cand = Candidate(
        candidate_id="b" * 16,
        # Names a buyer, because since 2026-08-14 `check_title`'s actuator defaults ON and a
        # title that names none publishes UNLISTED. The old fixture title, "Shellfish
        # Classification Aid", predated that rule and made THIS file's listing assertion fail
        # for a reason that has nothing to do with bundles — which is the point of fixing the
        # fixture rather than the gate: a bundle test must not be able to pass on a pack the
        # engine would refuse to list.
        title="Classification scheduling for UK oyster farms",
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
    # A PASS needs the LANE'S decisive check grounded, not merely one supported check:
    # dossier.py:167 mints Decision.PASS only when `moat_grounded >= 1` and KILLs
    # `moat_ungrounded` otherwise. This candidate carries ambition_tier="" — the default lane,
    # moat_critical_checks=[value_durability, incumbency] — so a lone non-decisive check
    # described a dossier the engine cannot produce.
    durability = CheckResult(
        check_name="value_durability", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Sampling rules are re-issued each season, so the aid stays needed.",
        citations=[], sources=[], queries=[],
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check, durability],
                   created_at="2026-07-31T00:00:00Z")


# The financial model is never free prose in production: _validate_artifact_shape forces a
# dict and artifacts.py:258 renders it through _render_financial_model, so every real pack
# carries these sections and Python-computed (arithmetically exact) figures. The fixture
# mirrors that shape because the publish gate now lints it (pack_linter); a prose blob here
# would assert that a pack the pipeline cannot produce is sellable.
from prospector.artifacts import _render_financial_model

# Generated by the renderer under test, never transcribed. Three copies of this fixture
# had been hand-typed across the suite, so a heading change went red in 22 tests while the
# thing they were guarding — that publish, lint and the renderer agree — was never checked.
_FIN_INPUTS = {
    "revenue_model": "subscription",
    "monthly_price": 50, "target_customers_month_1": 10,
    "target_customers_month_12": 120, "estimated_cac_gbp": 100,
    "estimated_monthly_churn_pct": 5.0, "cost_of_goods_pct": 12,
    "overhead_month_1_gbp": 200,
}
RENDERED_FINANCIAL_MODEL = _render_financial_model(_FIN_INPUTS, [], "£")


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
    def test_every_contract_file_is_present(self, complete_bundle):
        """Renamed 2026-08-15 from `test_all_eight_files_present`: the contract is no longer
        eight markdown documents, it is the five rendered artefacts of `BUNDLE_FILES`. The name
        stated a count that had become false, which is worse than no name at all.
        """
        path = complete_bundle
        # `path is not None` used to be asserted here; it now lives in the fixture, which is
        # where the build happens. Losing it entirely would have let a None bundle fail as a
        # confusing TypeError inside `_entries` instead of as "no bundle was produced".
        # `<=` not `==`: the bundle also ships manifest.jsonld, a declared bonus that is
        # deliberately NOT part of the BUNDLE_FILES sellability contract. The exact-set
        # assertion lives in test_bundle_declared_entries.py, which owns that question.
        assert set(BUNDLE_FILES) <= set(_entries(path))

    def test_no_entry_is_a_stub(self, complete_bundle):
        path = complete_bundle
        for name, size in _entries(path).items():
            assert size >= _MIN_BUNDLE_ENTRY_BYTES, f"{name} is {size}b"


class TestMissingArtifactsStillProduceEveryContractFile:
    """REGRESSION: empty prose used to make the file vanish from the zip entirely.

    Renamed 2026-08-15 (was `...ProduceAllEightFiles`). The eight documents are no longer zip
    entries, so the property is stated against the contract rather than against a count.
    """

    @pytest.mark.parametrize("dropped", ["build_spec", "gtm_plan", "ops_plan"])
    def test_empty_artifact_becomes_an_honest_placeholder(self, bridge, dropped):
        artifacts = _full_artifacts()
        artifacts[dropped] = ""
        path = bridge._create_bundle(_dossier(), artifacts, [])
        entries = _entries(path)
        assert set(BUNDLE_FILES) <= set(entries), f"dropping {dropped} lost a file"
        assert all(s >= _MIN_BUNDLE_ENTRY_BYTES for s in entries.values())

    def test_placeholder_invents_nothing(self, bridge):
        """Read from the READER since 2026-08-15, not from `03_Operations_Plan.md`.

        The placeholder is unchanged (`bridge._held_back_md`) and so is the property being
        pinned — a missing artifact must state its own absence rather than be papered over
        with invented content. What changed is where a buyer meets it: the documents are the
        render input now, so the honest placeholder has to survive INTO index.html, which is
        the file the buyer actually opens. Asserting it on a .md that no longer ships would
        have proved nothing about what was delivered.
        """
        artifacts = _full_artifacts()
        artifacts["ops_plan"] = ""
        path = bridge._create_bundle(_dossier(), artifacts, [])
        with zipfile.ZipFile(path) as zf:
            text = zf.read("index.html").decode()
        assert "not generated" in text.lower()
        assert "held back from sale" in text.lower()

    def test_every_artifact_missing_still_yields_every_contract_file(self, bridge):
        path = bridge._create_bundle(_dossier(), {}, [])
        assert set(BUNDLE_FILES) <= set(_entries(path))


class TestMarketingAssetsNeverAStub:
    """Measured on `Marketing_Assets.txt` since 2026-08-15.

    The 20-byte incident happened to `Marketing_Assets.md`, which is no longer a zip entry —
    it is the render input for `Marketing_Assets.txt`, the one document the pack still ships in
    an editable form because a buyer PASTES it rather than reads it. The stub floor therefore
    has to hold on the .txt: that is the file the buyer receives, and a header-only .txt is the
    same short delivery the .md was. The assertions below are the originals, re-pointed — the
    markdown `## ` prefix is gone from plain text, so an emitted heading is caught by its LABEL
    (`marketing_assets.heading_for`), which is strictly the thing that must not appear.
    """

    def test_empty_marketing_list_is_filled_by_the_floor(self, complete_bundle):
        """REGRESSION: this is the exact input that produced the 20-byte file.

        The empty marketing list IS the regression input, and `complete_bundle` is built with
        exactly `[]` — so sharing it keeps the input this test exists for, rather than
        approximating it.
        """
        size = _entries(complete_bundle)["Marketing_Assets.txt"]
        assert size > 20, "20 bytes is the bare '# Marketing Assets' header"
        assert size >= _MIN_BUNDLE_ENTRY_BYTES

    def test_pieces_with_empty_copy_do_not_emit_headings(self, bridge):
        marketing = [
            {"type": "social_post", "copy": ""},
            {"type": "launch_email", "copy": "   "},
        ]
        path = bridge._create_bundle(_dossier(), _full_artifacts(), marketing)
        with zipfile.ZipFile(path) as zf:
            text = zf.read("Marketing_Assets.txt").decode()
        assert heading_for("social_post")[0] not in text
        assert heading_for("launch_email")[0] not in text
        # the floor still supplied a real listing page
        assert len(text) >= _MIN_BUNDLE_ENTRY_BYTES

    def test_real_pieces_are_kept(self, bridge):
        marketing = [{"type": "launch_email", "copy": "Real email body with substance."}]
        path = bridge._create_bundle(_dossier(), _full_artifacts(), marketing)
        with zipfile.ZipFile(path) as zf:
            text = zf.read("Marketing_Assets.txt").decode()
        # Read from `marketing_assets.heading_for`, not a literal. The heading used to be
        # `type.replace("_", " ").title()`, which shipped "Seo Preview" — our internal enum,
        # title-cased, in a £49.99 product (P6). Pinning the literal here made this test fail
        # for the FIX rather than for a regression, which is the opposite of its job: what it
        # guards is that a real piece survives into the file, whatever the heading says.
        assert heading_for("launch_email")[0] in text
        assert "Real email body with substance." in text


class TestAuditBundle:
    """The audit the LISTING decision is made on.

    `validate_pack` reads the in-memory artifacts, so it cannot see a file that never reached
    the zip. That is not hypothetical: a03a2ba029b408a7 shipped 3 of 8 files with a 20-byte
    Marketing_Assets.md and was listed for sale anyway. `audit_bundle` reads the written
    artefact instead, and `publish_pass` ANDs it into `is_listed`.
    """

    def test_complete_bundle_audits_clean(self, complete_bundle):
        assert audit_bundle(complete_bundle) == ([], [])

    def test_missing_file_is_reported(self, tmp_path):
        """The dropped file is `Complete_Pack.pdf` since 2026-08-15 (was
        `05_First_Week_Checklist.md`, which is no longer an archive entry).

        It is the deliberate consequence of the new contract, stated as a test: the typeset
        edition is a promised deliverable now, so a pack whose PDF failed to render is SHORT
        and must not list. Before the change the renderers sat in BUNDLE_BONUS_FILES and a
        pack missing one listed anyway, silently incomplete.
        """
        path = tmp_path / "pack.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name in BUNDLE_FILES:
                if name == "Complete_Pack.pdf":
                    continue
                zf.writestr(name, "x" * (_MIN_BUNDLE_ENTRY_BYTES + 1))
        missing, stubs = audit_bundle(str(path))
        assert missing == ["Complete_Pack.pdf"]
        assert stubs == []

    def test_stub_entry_is_reported(self, tmp_path):
        """The a03a2ba0 shape: the file is present, and a header's worth of it.

        The 2026-07-30 incident was a 20-byte `Marketing_Assets.md`. The marketing copy now
        ships as `Marketing_Assets.txt` — same document, same failure mode, one heading and
        nothing under it — so the stub floor is asserted where the buyer would meet it.
        """
        path = tmp_path / "pack.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for name in BUNDLE_FILES:
                body = "Marketing Assets\n\n" if name == "Marketing_Assets.txt" else "x" * 500
                zf.writestr(name, body)
        missing, stubs = audit_bundle(str(path))
        assert missing == []
        assert stubs == ["Marketing_Assets.txt=18b"]

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

    # See the identical fake in test_publish_facet_warning.py: `usd_cents` joined the
    # ProductProvisioner protocol on 2026-08-14, and a fake missing it fails as a publish that
    # quietly went UNLISTED rather than as a signature error.
    def create_price(self, product_id, amount_pence, currency="gbp", usd_cents=None):
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
            "copy": "# Classification scheduling for UK oyster farms\n\nA scheduling aid for "
                    "UK oyster farms "
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
        # `sections_out` is the out-param the real `_create_bundle` fills with the assembled
        # read so the caller can lint it (bridge.py, 2026-08-15). A stub that composes no
        # sections leaves it untouched, which is the documented "the bundle failed to build"
        # case and exactly what this test is staging.
        def _deficient(self, dossier, artifacts, marketing, sections_out=None):
            path = Path("publish/bundles/deficient.zip")
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "w") as zf:
                for name in BUNDLE_FILES:
                    # Since 2026-08-15 the file dropped here is the typeset edition: it is a
                    # promised deliverable now, so its absence is exactly what must reach the
                    # catalogue as `is_listed=False`.
                    if name == "Complete_Pack.pdf":
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
        """The live defect: 3 of 8 files, one of them a 20-byte header, listed for sale.

        The fixture still writes the 2026-07 markdown shape on purpose. Since 2026-08-15 that
        archive is short of every file in `BUNDLE_FILES` rather than five of eight, which is a
        stronger version of the same verdict: a bundle in the old shape is not sellable either.
        """
        def _stubbed(self, dossier, artifacts, marketing, sections_out=None):
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

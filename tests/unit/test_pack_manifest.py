"""Proof that every bundle ships `manifest.jsonld`, and that it says what it claims to say.

Companion to test_bundle_index_html.py (the HTML reader); this pins the machine-readable half.
The promised deliverables are pinned by test_bundle_completeness.py and are not re-asserted here
beyond proving the manifest does not disturb them.

Since 2026-08-15 the manifest is rendered from the ARCHIVE contents and `_FILE_TITLES`, not from
the composed documents and `_SECTION_TITLES`. Those are two different maps for two different
jobs: `_SECTION_TITLES` names the sections INSIDE the reader, `_FILE_TITLES` names the things the
zip actually holds. Handing the manifest the documents would make it assert a sha256 for eight
files the zip does not contain — the single failure mode this file exists to make impossible.

The assertion that earns this file's keep is `test_the_manifest_carries_no_price`. `bridge.py` is
the money rail: one PriceDecision mints the provider Price object AND writes the catalogue row so
the two cannot drift, and a price copied into a zip on a buyer's disk is a third copy the engine can
never correct. That is a regression a reviewer would not notice in a 250-line JSON document, so it
is tested rather than commented.
"""
from __future__ import annotations

import dataclasses
import json
import zipfile

import pytest

from prospector import dossier as dossier_mod
from prospector import pack_manifest
from prospector.bridge import (
    _FILE_TITLES,
    BUNDLE_BONUS_FILES,
    BUNDLE_FILES,
    EngineBridge,
)
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict
from prospector.verify import VERDICT_PASSAGE_TRUNCATE


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class _Cfg:
        entitlements_api_key = ""
        store_payments = {"active_provider": "stripe"}

    return EngineBridge(_Cfg())


def _source(sid: str, url: str, text: str) -> Source:
    return Source(
        source_id=sid, url=url, text=text,
        published_at="2026-01-04", query="oyster closure guidance",
        fetched_at="2026-07-31T00:00:00Z",
    )


# One source cited by BOTH checks, so de-duplication is exercised rather than asserted.
_SHARED = _source("s-shared", "https://example.gov.uk/closures", "Closure notices are issued weekly.")


def _dossier() -> Dossier:
    cand = Candidate(
        candidate_id="c" * 16,
        title="Shellfish Classification Aid",
        one_liner="Scheduling aid for UK oyster farms.",
        market="uk",
        who_pays="owner-operated shellfish farms",
        why_now="new sampling rules",
    )
    supported = CheckResult(
        check_name="buyer_intent", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Growers search for closure guidance.",
        citations=["s-shared"], sources=[_SHARED],
        provider="claude-cli/default",
    )
    # A long passage, a second citation of the shared source, and every honesty flag set, so the
    # truncation and the flags are covered by a real render rather than by a unit call.
    degraded = CheckResult(
        check_name="payer_solvency", verdict=Verdict.UNVERIFIABLE, confidence=0.2,
        rationale="No accounts filed for the segment.",
        citations=["s-long", "s-shared"],
        sources=[_source("s-long", "https://example.com/accounts", "x" * (VERDICT_PASSAGE_TRUNCATE + 500)),
                 _SHARED],
        degraded=True, retrieval_failed=True, provisional=True,
        provider="minimax/MiniMax-M3",
    )
    return Dossier(
        candidate=cand, decision=Decision.PASS, checks=[supported, degraded],
        created_at="2026-07-31T00:00:00Z", provider_chain="claude-cli/default",
    )


def _full_artifacts():
    body = ("## Section\n\nGrounded prose about the opportunity. " * 20)
    return {k: f"# {k}\n\n{body}" for k in
            ("build_spec", "gtm_plan", "ops_plan", "financial_model")}


def _manifest_from_zip(zip_path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read(pack_manifest.MANIFEST_FILENAME).decode("utf-8"))


def _nodes(doc: dict, node_type: str) -> list[dict]:
    return [n for n in doc["@graph"] if n.get("@type") == node_type]


class TestTheManifestShipsInTheBundle:
    def test_manifest_is_in_the_zip_and_is_valid_json(self, bridge):
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        assert doc["@context"][0] == "https://schema.org"
        assert doc["@context"][1]["prospector"] == pack_manifest.PROSPECTOR_NS
        assert doc["prospector:manifestVersion"] == pack_manifest.MANIFEST_VERSION

    def test_the_promised_deliverables_are_untouched(self, bridge):
        """The manifest is additive. Adding it must not alter what is sold.

        Renamed 2026-08-15 (was `test_the_eight_deliverables_are_untouched`): the count in the
        name became false when the contract became five rendered files.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        assert set(BUNDLE_FILES) <= names
        assert pack_manifest.MANIFEST_FILENAME in names


class TestTheManifestDescribesWhatShipped:
    def test_every_promised_file_is_listed_in_READING_order_with_a_true_digest(self, bridge):
        """Reading order, not zip write order.

        The zip is written 01, 02, 03, 04, QA, Marketing, 00, 05 (see the note in
        `_create_bundle`). A manifest built from the write sequence would tell an agent the
        Executive Summary is the seventh document, which is the exact defect index.html shipped
        with for weeks. `BUNDLE_FILES` is the contract and the manifest takes its order from it.

        The titles come from `_FILE_TITLES` since 2026-08-15, not `_SECTION_TITLES`. The
        manifest describes the ARCHIVE, and the archive's first entry is index.html, which has
        no entry in the section map at all — reading the old map here would have raised a
        KeyError rather than quietly mislabelling, which is the only reason it was caught.
        """
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        doc = _manifest_from_zip(path)
        with zipfile.ZipFile(path) as zf:
            raw = {n: zf.read(n) for n in zf.namelist()}

        promised = [n for n in _nodes(doc, "DigitalDocument")
                    if n.get("prospector:promisedDeliverable") is not False]
        assert [n["contentUrl"] for n in promised] == list(BUNDLE_FILES)
        assert [n["position"] for n in promised] == list(range(1, len(BUNDLE_FILES) + 1))
        assert promised[0]["name"] == _FILE_TITLES[BUNDLE_FILES[0]]

        import hashlib
        for node in promised:
            body = raw[node["contentUrl"]]
            assert node["prospector:sha256"] == hashlib.sha256(body).hexdigest()
            assert node["contentSize"] == str(len(body))

    def test_the_manifest_never_describes_itself(self, bridge):
        """A file cannot carry the digest of its own final bytes, so it must not try."""
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        urls = [n["contentUrl"] for n in _nodes(doc, "DigitalDocument")]
        assert pack_manifest.MANIFEST_FILENAME not in urls

    def test_a_file_that_did_not_ship_is_omitted_not_asserted(self):
        """A partially-built bundle is held UNLISTED; the manifest must still be truthful."""
        # The archive contents, not the composed documents — `BUNDLE_FILES[0]` is index.html
        # since 2026-08-15, so the stand-in content is a rendered page rather than markdown.
        written = {BUNDLE_FILES[0]: "<h1>Exec</h1><p>body</p>"}
        doc = json.loads(pack_manifest.render_manifest(
            _dossier(), written, BUNDLE_FILES, _FILE_TITLES, "c" * 16))
        assert [n["contentUrl"] for n in _nodes(doc, "DigitalDocument")] == [BUNDLE_FILES[0]]

    def test_a_bonus_file_is_listed_and_flagged_as_not_promised(self, bridge):
        """A bonus file is in the zip, so an agent enumerating entries must find it accounted
        for, and must be able to tell it apart from a sold deliverable.

        Asserted against BUNDLE_BONUS_FILES, not a literal: the manifest is the machine-readable
        account of what shipped, so every declared bonus must appear in it. The manifest itself is
        the one exception — a file cannot carry the digest of its own final bytes
        (`test_the_manifest_never_describes_itself`).
        """
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        bonus = [n for n in _nodes(doc, "DigitalDocument")
                 if n.get("prospector:promisedDeliverable") is False]
        assert (set(n["contentUrl"] for n in bonus)
                == set(BUNDLE_BONUS_FILES) - {pack_manifest.MANIFEST_FILENAME})


class TestTheManifestCarriesTheEvidence:
    def test_each_check_is_a_ClaimReview_with_its_verdict_and_confidence(self, bridge):
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        reviews = {n["claimReviewed"]: n for n in _nodes(doc, "ClaimReview")}
        assert set(reviews) == {"buyer_intent", "payer_solvency"}

        ok = reviews["buyer_intent"]
        assert ok["prospector:verdict"] == "supported"
        assert ok["reviewRating"]["ratingValue"] == 0.8
        assert (ok["reviewRating"]["worstRating"], ok["reviewRating"]["bestRating"]) == (0, 1)
        # The verdict word is NOT recoverable from the number: `unverifiable` at high confidence
        # and `supported` at low confidence are different facts, so both must survive.
        assert ok["reviewRating"]["alternateName"] == "supported"

    def test_every_citation_resolves_to_a_source_node_in_the_same_graph(self, bridge):
        """A dangling @id is worse than no citation: it reads as evidence and resolves to nothing."""
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        ids = {n["@id"] for n in doc["@graph"]}
        for review in _nodes(doc, "ClaimReview"):
            for cite in review["citation"]:
                assert cite["@id"] in ids

    def test_a_source_cited_twice_appears_once(self, bridge):
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        urls = [n["url"] for n in _nodes(doc, "WebPage")]
        assert sorted(urls) == ["https://example.com/accounts", "https://example.gov.uk/closures"]

    def test_the_passage_ships_truncated_to_exactly_what_the_verdict_saw(self, bridge):
        """Not a display truncation. Shipping MORE would let an agent 're-verify' against evidence
        the ruling never saw and conclude we were wrong on a paragraph we were never shown."""
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        long = next(n for n in _nodes(doc, "WebPage") if n["url"].endswith("/accounts"))
        assert len(long["prospector:passage"]) == VERDICT_PASSAGE_TRUNCATE
        assert long["prospector:passageTruncatedAt"] == VERDICT_PASSAGE_TRUNCATE
        assert long["prospector:fetchedAt"] == "2026-07-31T00:00:00Z"

    def test_a_degraded_or_provisional_ruling_is_flagged(self, bridge):
        """An agent that could not tell a degraded verdict from a clean one would quote it as
        settled. The flags are emitted only when true, so their presence is the signal."""
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        reviews = {n["claimReviewed"]: n for n in _nodes(doc, "ClaimReview")}
        bad = reviews["payer_solvency"]
        assert bad["prospector:degraded"] is True
        assert bad["prospector:retrievalFailed"] is True
        clean = reviews["buyer_intent"]
        assert "prospector:degraded" not in clean
        assert "prospector:retrievalFailed" not in clean

    def test_the_buyer_is_never_told_which_model_ruled(self, bridge):
        """`prospector:ruledBy` was the model name, per check, in the zip the buyer downloads,
        and `prospector:provisional` was our trust tier for it. Founder, 2026-08-15, on a pack
        pulled off the live storefront: it had "even ai judge info".

        The two flags left above stay, and the difference is the whole rule: `degraded` and
        `retrievalFailed` are facts about the EVIDENCE, which is what was sold. Which model
        ruled is a fact about our supply chain, and the buyer can do nothing with it."""
        doc = _manifest_from_zip(bridge._create_bundle(_dossier(), _full_artifacts(), []))
        blob = json.dumps(doc)
        assert "ruledBy" not in blob
        assert "minimax" not in blob.lower()
        for node in _nodes(doc, "ClaimReview"):
            assert "prospector:provisional" not in node, node["claimReviewed"]

    def test_the_verdict_scale_is_stated_in_the_document(self):
        """`unverifiable` is a real third outcome, not a missing value, and an agent has no way to
        know that from the word alone."""
        doc = json.loads(pack_manifest.render_manifest(
            _dossier(), {}, BUNDLE_FILES, _FILE_TITLES, "c" * 16))
        assert set(doc["prospector:verdictScale"]) == {"supported", "refuted", "unverifiable"}


_MONEY_WORDS = ("price", "offer", "amount", "gbp", "pence", "currency", "cost")


def _keys(node, out=None):
    """Every key name anywhere in the document."""
    out = set() if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _keys(v, out)
    return out


class TestTheMoneyRail:
    """THE MONEY-RAIL GUARD.

    One PriceDecision mints the provider Price object AND writes the catalogue row precisely so the
    two cannot drift; a drift charges the buyer and then fails the fulfilment fence. A price in the
    zip is a third copy, on a buyer's disk permanently, that the engine can never correct after a
    re-price — and no reader needs it, because fulfilment reads the catalogue row.

    THE GUARD IS ON KEYS AND TYPES, NOT ON THE RENDERED TEXT. The first version of this test
    searched the whole document for the substring "price"/"£". It passed here and would have failed
    on the first real pack: rendered against a shipped bundle
    (publish/bundles/08b22037fc2afc07/…), the manifest matched "price", "offer", "currency" and "£"
    — all of them inside RETRIEVED EVIDENCE (a passage reading "£78 Billion Settlement Announced…")
    and inside a rationale about buyers already paying professionals. Same run: zero money-shaped
    KEYS. Those words are the product's substance — `price_comparables` is a check whose entire job
    is cited price anchors from the open web — so a text search would have driven exactly the wrong
    fix, stripping evidence to satisfy a guard about the till.

    What the rail actually forbids is a FIELD asserting what this pack costs. A price can only enter
    as a key, or as schema.org's own money vocabulary, so both are what is pinned.
    """

    def test_no_money_shaped_key_exists_anywhere_in_the_document(self, bridge):
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        with zipfile.ZipFile(path) as zf:
            doc = json.loads(zf.read(pack_manifest.MANIFEST_FILENAME))
        leaked = sorted(k for k in _keys(doc)
                        if any(w in k.lower() for w in _MONEY_WORDS))
        assert leaked == [], f"manifest.jsonld grew a money field: {leaked}"

    def test_no_schema_org_money_node_exists(self, bridge):
        """`Offer` / `PriceSpecification` / `MonetaryAmount` are how a price would arrive if someone
        made the manifest 'more complete' as a product listing. It is not a product listing."""
        path = bridge._create_bundle(_dossier(), _full_artifacts(), [])
        with zipfile.ZipFile(path) as zf:
            doc = json.loads(zf.read(pack_manifest.MANIFEST_FILENAME))
        types = {n.get("@type") for n in doc["@graph"]}
        assert not types & {"Offer", "AggregateOffer", "PriceSpecification", "MonetaryAmount"}, types


class TestTheBackfillPathRendersFromAStoredDossier:
    """`dossier_from_dict` is how already-listed packs get a manifest without regenerating them.

    It rebuilds the record as nested SimpleNamespaces, which is a DIFFERENT input shape from the
    dataclasses every other test in this file uses. That difference shipped a crash: `score.scores`
    is a dict on the live path and a namespace here, and `dict()` on a namespace raises. It was
    caught by rendering a real stored dossier, not by these tests, so the round trip is pinned now.
    """

    def test_a_dossier_round_tripped_through_json_renders_identically(self):
        from prospector.models import ScoreResult
        d = _dossier()
        d.score = ScoreResult(scores={"pain_reality": 4, "distribution": 2},
                              justification={"pain_reality": "growers say so"}, composite=3.4)
        live = pack_manifest.render_manifest(d, {}, BUNDLE_FILES, _FILE_TITLES, "c" * 16)
        stored = pack_manifest.render_manifest(
            pack_manifest.dossier_from_dict(json.loads(json.dumps(d.to_dict()))),
            {}, BUNDLE_FILES, _FILE_TITLES, "c" * 16)
        assert json.loads(stored) == json.loads(live)

    def test_our_grade_of_the_idea_never_reaches_the_buyer(self):
        """`prospector:scores` and `prospector:compositeScore` were in every manifest until
        2026-08-15. They are our internal ranking, which exists to decide what to PUBLISH — a
        decision already made by the time anyone can download this — and printing the grade
        beside the thing graded invites a comparison the pack cannot support, between two
        composites scored months apart against different evidence.

        Asserted on the SUBSTRING as well as the key, because the number also reached the
        buyer through `pack_data`'s scorecard.json and would have to be removed twice."""
        from prospector.models import ScoreResult
        d = _dossier()
        d.score = ScoreResult(scores={"pain_reality": 4}, justification={}, composite=3.4)
        doc = json.loads(pack_manifest.render_manifest(
            pack_manifest.dossier_from_dict(d.to_dict()), {}, BUNDLE_FILES, _FILE_TITLES, "c" * 16))
        pack = next(n for n in doc["@graph"] if n.get("@type") == "Report")
        assert "prospector:scores" not in pack
        assert "prospector:compositeScore" not in pack
        assert "prospector:providerChain" not in pack
        assert "3.4" not in json.dumps(pack)

    def test_the_namespace_conversion_guard_is_still_exercised(self):
        """`_plain_mapping` lost its caller when the scores came out of the manifest, and its
        lesson is worth more than the call site was: `dossier_from_dict` rebuilds a stored
        dossier as nested SimpleNamespaces, so a plain Dict[str, float] on the live path
        arrives as a NAMESPACE on the backfill path and `dict()` raises TypeError. Every unit
        test built from the real dataclasses missed it; the first real stored dossier found
        it. Pinned directly so the next caller inherits a tested helper."""
        from types import SimpleNamespace
        assert pack_manifest._plain_mapping({"pain_reality": 4}) == {"pain_reality": 4}
        assert pack_manifest._plain_mapping(SimpleNamespace(pain_reality=4)) == {"pain_reality": 4}


class TestARecordThatPredatesAFieldStillRenders:
    """A dossier is written once and read for years, so the reader must tolerate an old row.

    It did not. `dossier_from_dict` built a namespace from the keys a stored record HAPPENS to
    have, and `render_markdown` reads `dossier.persona` unguarded (dossier.py:776) — a field
    every stored PASS predates. Measured: 84 stored PASS records, 0 rendered, 84 raised
    `AttributeError: 'types.SimpleNamespace' object has no attribute 'persona'`, which put the
    packs already sold out of reach of the re-render that corrects their QA report.

    The tests above were green throughout, because they round-trip a dossier built by TODAY's
    dataclass — which by construction has every field today's reader asks for, and so can never
    reproduce the one thing that was broken. These drop the fields instead. The per-field sweep
    is the gate that matters: it is written against `dataclasses.fields(Dossier)` rather than a
    list of names, so a field added tomorrow is covered the day it is added, which is the only
    form of this test that stays true.

    The real store cannot be the gate here — store/dossiers/ is gitignored, so a test reading it
    asserts on one laptop (tests/test_suite_is_machine_independent.py:36). That sweep lives in
    scripts/store_audit.py, which runs where the data is.
    """

    @staticmethod
    def _stored_without(*absent: str) -> dict:
        """A stored record as written by a build that did not have these fields yet."""
        from prospector.models import ScoreResult
        d = _dossier()
        d.score = ScoreResult(scores={"pain_reality": 4}, justification={"pain_reality": "why"},
                              composite=3.4)
        record = json.loads(json.dumps(d.to_dict()))
        for key in absent:
            record.pop(key, None)
        return record

    def test_a_record_written_before_persona_existed_renders(self):
        """The exact measured failure: the three fields no stored PASS record carries."""
        record = self._stored_without("persona", "publish_status", "publish_error")
        text = dossier_mod.render_markdown(pack_manifest.dossier_from_dict(record))
        assert "Shellfish Classification Aid" in text
        assert "Persona" not in text, "an absent persona must render as no line, not as blank"

    def test_the_manifest_renders_from_that_record_too(self):
        record = self._stored_without("persona", "publish_status", "publish_error")
        doc = json.loads(pack_manifest.render_manifest(
            pack_manifest.dossier_from_dict(record), {}, BUNDLE_FILES, _FILE_TITLES, "c" * 16))
        assert _nodes(doc, "Report"), doc.keys()

    @pytest.mark.parametrize("field_name", sorted(
        f.name for f in dataclasses.fields(Dossier)
        if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING))
    def test_dropping_any_defaulted_field_still_renders(self, field_name):
        """Every field that carries a default is a field some stored row predates.

        Fields WITHOUT a default (`candidate`, `decision`) are excluded deliberately: they have
        existed since the first record, so no row on disk is missing them, and inventing a
        substitute for a required field would be a silent blank in a published QA report rather
        than a fix.
        """
        record = self._stored_without(field_name)
        assert field_name not in record
        text = dossier_mod.render_markdown(pack_manifest.dossier_from_dict(record))
        assert text.startswith("# Shellfish Classification Aid")

    def test_a_misspelt_field_is_still_an_error(self):
        """The fix fills the fields the DATACLASS declares, and nothing else.

        A `__getattr__`-returns-None namespace would also have made these renders pass, and
        would have turned `dossier.persoan` into a blank line in a document a buyer pays for.
        """
        ns = pack_manifest.dossier_from_dict(self._stored_without("persona"))
        assert ns.persona == ""
        with pytest.raises(AttributeError):
            ns.persoan

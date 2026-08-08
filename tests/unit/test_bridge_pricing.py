"""C2 — the ladder, not a flat constant, decides what the bridge publishes.

Two numbers leave `publish_pack`: the amount the provider `Price` object is minted at, and
the `pricePence` written to the catalogue row. Before C2 they agreed only because both read
the same `config.listing.price_pence` constant. Now a `PriceDecision` decides, and the
load-bearing property is that ONE decision feeds BOTH.

Why that property and not merely "the price is right": the fulfilment fence compares what
the buyer actually paid against the catalogue's floor
(`FulfilmentService.cs` → `pack.EffectiveFloorPence`). A Stripe Price minted at one number
and a catalogue row written at another produces a pack that charges the buyer correctly and
then refuses to deliver — the exact failure L0 exists to prevent, reintroduced one layer up.
A test that only checked each number against config would pass while they diverged.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sellable_pack import sellable_tags

from prospector.bridge import EngineBridge
from prospector.config import Config
from prospector.models import Candidate, CheckResult, Decision, Dossier, ScoreResult, Verdict
from prospector.price_rationale import read_rationale
from prospector.pricing import price_for

AXES = ["pain_acuity", "money_provability", "automatability", "distribution",
        "defensibility", "build_feasibility"]


def _dossier(candidate_id: str, tier: str = "", market: str = "",
             tags_extra: dict | None = None) -> Dossier:
    candidate = Candidate(
        title="FuelClaim — reclaim fuel duty for small fleets",
        one_liner="SaaS to reclaim fuel duty for fleets",
        ambition_tier=tier,
        market=market,
    )
    candidate.candidate_id = candidate_id
    # A pack that genuinely clears the content gates. `publish_pass` decides completeness,
    # the bundle audit and the Q2 lint BEFORE it mints, and skips provisioning entirely for a
    # pack that cannot list — so a stub fixture here would exercise the no-mint path while
    # claiming to test the minted price. See tests/unit/sellable_pack.py.
    candidate.tags = sellable_tags()
    if tags_extra:
        candidate.tags.update(tags_extra)

    d = MagicMock(spec=Dossier)
    d.decision = Decision.PASS
    d.candidate = candidate
    d.score = ScoreResult(scores={a: 4 for a in AXES},
                          justification={a: "ok" for a in AXES}, composite=4.2)
    d.checks = [CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED,
                            confidence=0.8, rationale="grounded")]
    d.adversarial = None
    d.gate_fired = None
    d.reason = "Survived all gates."
    d.provider_chain = "test-chain"
    d.model_version = "test-model"
    d.created_at = "2026-08-05T00:00:00Z"
    d.reverify_due_at = "2026-09-05T00:00:00Z"
    d.provisional = False
    return d


@pytest.fixture
def bridge(cfg: Config, monkeypatch):
    """A bridge on the REAL config.yaml, so the ladder under test is the shipped one."""
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-internal-key")
    b = EngineBridge(cfg)
    b.store_api_url = "http://localhost:5050"
    b.entitlements_check = MagicMock(return_value=True)
    return b


def _publish_and_capture(b: EngineBridge, dossier) -> tuple[int, int]:
    """Publish once; return (minted_price_pence, catalogue_price_pence).

    The provisioner is stubbed rather than the whole publish path, so the number captured
    is the one the real code hands to the real `create_price` argument.
    """
    prov = MagicMock()
    prov.create_product.return_value = "prod_test"
    prov.create_price.return_value = "price_test"
    with patch.object(EngineBridge, "provisioner", property(lambda self: prov)), \
            patch("requests.post") as mock_post, \
            patch("requests.get") as mock_get:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"
        mock_get.return_value.status_code = 404
        assert b.publish_pass(dossier) is True

        catalogue = None
        for call in mock_post.call_args_list:
            payload = call.kwargs.get("json") or {}
            if isinstance(payload, dict) and "title" in payload:
                catalogue = payload
        assert catalogue is not None, "no catalogue registration POST was made"

    minted = prov.create_price.call_args.kwargs["amount_pence"]
    return int(minted), int(catalogue["pricePence"])


def test_the_minted_price_and_the_catalogue_row_are_the_same_number(bridge, cfg):
    """The drift guard. If these two ever disagree, the pack charges and refuses delivery."""
    minted, catalogued = _publish_and_capture(bridge, _dossier("c2-drift", "venture", "us"))
    assert minted == catalogued


def test_an_unclassified_pack_still_publishes_at_the_flat_catalogue_price(bridge, cfg):
    """C2 is a NO-OP on today's catalogue. Every live pack carries `ambition_tier=""`, so
    repointing the money rail onto the ladder must change nothing until lanes start tagging
    candidates. A repoint that silently re-priced 61 live packs on merge is the incident
    this asserts against."""
    minted, catalogued = _publish_and_capture(bridge, _dossier("c2-flat"))
    assert minted == catalogued == 4900


def test_a_classified_pack_publishes_at_its_ladder_rung_not_the_constant(bridge, cfg):
    """...and the constant really is gone: a tiered pack must NOT come out at 4900."""
    dossier = _dossier("c2-ladder", "venture", "us")
    expected = price_for(dossier.candidate, dossier.score, cfg).price_pence
    minted, catalogued = _publish_and_capture(bridge, dossier)
    assert minted == catalogued == expected
    assert expected != 4900, "sanity: the ladder must actually move a venture/us pack"


def test_the_price_decision_is_recorded_on_the_candidate(bridge, cfg):
    """A price with no stated cause is indistinguishable from a bug — the same reason
    `PATCH /internal/catalog/{id}/price` refuses a change with no `Reason`."""
    dossier = _dossier("c2-record", "growth", "uk")
    _publish_and_capture(bridge, dossier)
    rec = dossier.candidate.tags.get("price_decision")
    assert rec and rec["price_pence"] == 7900
    assert "growth" in rec["rationale"]
    assert rec["segment"] == {"ambition_tier": "growth", "market": "uk"}


def test_publishing_writes_a_rationale_record_and_the_ref_resolves(bridge, cfg):
    """D3 on the publish path. `PricePatchRequest.RationaleRef` is the auditor's pointer,
    but a re-priced pack is not the only price decision the system takes — the first one is
    taken here, at publish. Without this, the publish path would be the single money-moving
    act with no derivation record behind it.

    The ref is resolved and parsed, not merely asserted non-empty: a ref that points at
    nothing reads exactly like provenance until someone follows it."""
    dossier = _dossier("c2-rationale", "growth", "uk")
    minted, catalogued = _publish_and_capture(bridge, dossier)

    ref = dossier.candidate.tags.get("price_rationale_ref")
    assert ref, "publish took a price decision and left no rationale record"

    record = read_rationale(ref)          # resolves via PROSPECTOR_RATIONALE_ROOT (conftest)
    assert record["pack_id"] == "c2-rationale"
    assert record["source"] == "prospector/bridge.py"
    # The record must document the price that was actually minted and catalogued, not a
    # re-derivation: a rationale describing a different number is worse than none.
    assert record["decision"]["price_pence"] == minted == catalogued
    assert record["ladder"]["rungs"] == list(cfg.listing["pricing"]["rungs"])


def test_update_catalog_has_no_default_price(bridge):
    """`price_pence` must be a required parameter. A default would be a second source of
    truth for the price, quietly disagreeing with the Price object the caller minted."""
    import inspect
    sig = inspect.signature(EngineBridge._update_catalog)
    assert sig.parameters["price_pence"].default is inspect.Parameter.empty


def test_a_config_with_no_ladder_holds_the_flat_price_instead_of_crashing(cfg: Config):
    """`price_for` is on the publish path now, so a config that predates the ladder — or one
    with a half-written `pricing` block — must degrade to today's behaviour rather than
    raising. A KeyError here is a data edit taking the money rail down."""
    c = copy.deepcopy(cfg)
    c.listing = {"price_pence": 4900}
    d = price_for(Candidate(title="x", ambition_tier="venture", market="us"),
                  ScoreResult(scores={}, justification={}), c)
    assert d.price_pence == 4900
    assert "no ladder declared" in d.rung

    c2 = copy.deepcopy(cfg)
    c2.listing["pricing"] = {"rungs": [1900, 4900]}   # default_rung_index missing
    d2 = price_for(Candidate(title="x"), ScoreResult(scores={}, justification={}), c2)
    assert d2.price_pence == 4900

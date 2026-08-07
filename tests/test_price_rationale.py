"""D3 acceptance — the rationale record behind a price (prospector/price_rationale.py).

The build plan's acceptance for D3 is two claims, and this file is written to make both
falsifiable:

1. **Round trip.** Write a decision, read it back, and every field survives. A derivation
   record that loses the evidence or the segment on the way to disk is not provenance.
2. **The ref matches the PATCH.** The `rationaleRef` the money-rail PATCH carries is
   exactly the path the record was written at. A ref that points at nothing is
   indistinguishable from no ref, and it is worse, because it reads like an audit trail.

Everything writes under `tmp_path`. A test that wrote into `store/pricing/rationale/`
would file fiction next to the real price history — the same class of mistake as
`verify_pipeline.py` writing into the live gap store.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from prospector.config import Config
from prospector.models import Candidate, ScoreResult
from prospector.price_rationale import (
    RATIONALE_DIR,
    SCHEMA_VERSION,
    build_record,
    ladder_snapshot,
    read_rationale,
    record_ref,
    write_rationale,
)
from prospector.pricing import PriceDecision, price_for

AT = datetime(2026, 8, 6, 9, 15, 30, tzinfo=timezone.utc)


def _decision(cfg: Config, tier: str = "growth", market: str = "us") -> PriceDecision:
    return price_for(Candidate(title="A test opportunity", ambition_tier=tier,
                               market=market),
                     ScoreResult(scores={}, justification={}), cfg)


# --- 1. round trip ----------------------------------------------------------

def test_every_field_survives_a_write_and_a_read(cfg: Config, tmp_path: Path) -> None:
    d = _decision(cfg)
    ref = write_rationale("pack_abc123", d, cfg, actor="claude:test",
                          source="tests", reason="because", at=AT, repo_root=tmp_path)
    got = read_rationale(ref, repo_root=tmp_path)

    assert got["schema_version"] == SCHEMA_VERSION
    assert got["pack_id"] == "pack_abc123"
    assert got["created_at"] == "2026-08-06T09:15:30Z"
    assert got["actor"] == "claude:test"
    assert got["source"] == "tests"
    assert got["reason"] == "because"
    assert got["decision"]["price_pence"] == d.price_pence
    assert got["decision"]["rung"] == d.rung
    assert got["decision"]["segment"] == d.segment
    assert got["decision"]["rationale"] == d.rationale
    assert got["decision"]["evidence"] == d.evidence


def test_the_evidence_block_survives_when_comparables_moved_the_rung(
        cfg: Config, tmp_path: Path) -> None:
    """`evidence` is the citation trail for a price that moved on retrieved comparables
    rather than on the ladder alone. It is a nested dict, which is exactly the shape a
    lossy serialiser flattens or drops."""
    ev = {"median_pence": 9900, "n": 3, "domains": ["a.com", "b.co.uk"],
          "anchors": [{"price_pence": 9900, "url": "https://a.com/pricing"}]}
    d = PriceDecision(price_pence=9900, rung="growth at rung index 4",
                      segment={"ambition_tier": "growth", "market": "us"},
                      rationale="moved one rung on comparables", evidence=ev)
    ref = write_rationale("pack_ev", d, cfg, actor="a", source="s", at=AT,
                          repo_root=tmp_path)
    assert read_rationale(ref, repo_root=tmp_path)["decision"]["evidence"] == ev


def test_the_record_is_valid_json_on_disk_at_the_ref(cfg: Config,
                                                     tmp_path: Path) -> None:
    """Proven by reading the file directly, not through `read_rationale` — a reader that
    is the only thing able to parse its own writer proves nothing about the artifact an
    auditor will actually open."""
    ref = write_rationale("pack_json", _decision(cfg), cfg, actor="a", source="s",
                          at=AT, repo_root=tmp_path)
    path = tmp_path / ref
    assert path.is_file(), f"nothing written at {ref}"
    assert ref.startswith(RATIONALE_DIR + "/")
    assert json.loads(path.read_text())["pack_id"] == "pack_json"


# --- 2. the ladder is snapshotted, not named --------------------------------

def test_the_record_carries_the_rung_numbers_that_were_in_force(cfg: Config) -> None:
    """A record naming only a ladder VERSION would be reinterpreted against whatever
    config.yaml says on the day it is read. The numbers themselves must be in the file."""
    snap = build_record("p", _decision(cfg), cfg, actor="a", source="s",
                        at=AT)["ladder"]
    assert snap["rungs"] == list(cfg.listing["pricing"]["rungs"])
    assert snap["default_rung_index"] == cfg.listing["pricing"]["default_rung_index"]
    assert snap["tier_rung_index"] == dict(cfg.listing["pricing"]["tier_rung_index"])
    assert snap["version"] == cfg.listing["pricing"].get("ladder_version")


def test_editing_a_rung_changes_the_ladder_fingerprint(cfg: Config) -> None:
    """The fingerprint is the claim that the label cannot make: it changes when the
    numbers change, whether or not anybody remembered to bump `ladder_version`."""
    before = ladder_snapshot(cfg)["fingerprint"]
    cfg.listing["pricing"]["rungs"] = [1900, 2900, 4900, 7900, 9900, 14900, 24900]
    after = ladder_snapshot(cfg)["fingerprint"]
    assert before != after

    # ...and the label alone does not move it, which is the whole reason it exists.
    cfg.listing["pricing"]["ladder_version"] = "renamed-and-nothing-else"
    assert ladder_snapshot(cfg)["fingerprint"] == after


def test_a_config_with_no_ladder_still_produces_a_record(tmp_path: Path) -> None:
    """`price_for` degrades to the flat price rather than raising on a config that
    predates the ladder (pricing.py:121). The record writer sits on the same publish path
    and must degrade the same way — an audit writer that crashed where the money path
    survived would take publishing down to protect a log."""
    empty = Config(listing={})
    d = PriceDecision(price_pence=4900, rung="flat (no ladder declared)",
                      segment={"ambition_tier": "", "market": ""},
                      rationale="no ladder")
    ref = write_rationale("pack_noladder", d, empty, actor="a", source="s", at=AT,
                          repo_root=tmp_path)
    got = read_rationale(ref, repo_root=tmp_path)
    assert got["ladder"]["rungs"] == []
    assert got["ladder"]["default_rung_index"] is None
    assert got["decision"]["price_pence"] == 4900


# --- 3. the ref is derived, deterministic, and tamper-evident ---------------

def test_the_same_decision_writes_to_the_same_ref_twice(cfg: Config,
                                                        tmp_path: Path) -> None:
    """Determinism, so a re-run of a backfill overwrites its own record instead of
    littering near-identical ones next to the price history."""
    d = _decision(cfg)
    a = write_rationale("pack_same", d, cfg, actor="a", source="s", at=AT,
                        repo_root=tmp_path)
    b = write_rationale("pack_same", d, cfg, actor="a", source="s", at=AT,
                        repo_root=tmp_path)
    assert a == b
    assert len(list((tmp_path / RATIONALE_DIR / "pack_same").iterdir())) == 1


def test_a_different_price_lands_at_a_different_ref(cfg: Config) -> None:
    base = _decision(cfg, "growth", "us")
    other = PriceDecision(price_pence=base.price_pence + 5000, rung=base.rung,
                          segment=base.segment, rationale=base.rationale)
    mk = lambda d: record_ref(build_record("pack_x", d, cfg, actor="a", source="s",  # noqa: E731
                                          at=AT))
    assert mk(base) != mk(other)


def test_an_edited_record_is_refused_rather_than_returned(cfg: Config,
                                                          tmp_path: Path) -> None:
    """The one behaviour that would make this file worse than useless: handing back an
    altered derivation as if it were the one the buyer was charged under."""
    ref = write_rationale("pack_tamper", _decision(cfg), cfg, actor="a", source="s",
                          at=AT, repo_root=tmp_path)
    path = tmp_path / ref
    doc = json.loads(path.read_text())
    doc["decision"]["price_pence"] = 100
    path.write_text(json.dumps(doc))

    with pytest.raises(ValueError, match="does not match its own digest"):
        read_rationale(ref, repo_root=tmp_path)


def test_a_pack_id_cannot_escape_the_rationale_directory(cfg: Config,
                                                         tmp_path: Path) -> None:
    """`pack_id` arrives from a catalogue row and becomes a path segment."""
    ref = write_rationale("../../etc/passwd", _decision(cfg), cfg, actor="a",
                          source="s", at=AT, repo_root=tmp_path)
    assert ref.startswith(RATIONALE_DIR + "/")
    assert ".." not in ref
    assert (tmp_path / ref).resolve().is_relative_to(
        (tmp_path / RATIONALE_DIR).resolve())


# --- 4. the ref the PATCH carries is the record that was written ------------

def test_the_patch_request_carries_the_ref_the_record_was_written_at(
        cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The acceptance claim that spans D3 and the C1 money rail: what
    `PricePatchRequest.RationaleRef` points at must be a record that exists and parses.

    Built through the script's own `build_patch_payload`, so this fails if the payload is
    ever rewired to a hand-written string (it previously carried a spec anchor,
    `specs/pricing-build-plan-2026-08-05.md#C1`, which no record backed).
    """
    import scripts.backfill_ladder_prices as backfill

    monkeypatch.setattr(backfill, "cfg", lambda: cfg)
    d = _decision(cfg, "side_hustle", "uk")
    m = {"id": "pack_patch", "tier": "side_hustle", "market": "uk",
         "new_pence": d.price_pence, "rung": d.rung, "rationale": d.rationale,
         "decision": d}

    ref = write_rationale(m["id"], d, cfg, actor=backfill.ACTOR, source=backfill.SOURCE,
                          reason=backfill.patch_reason(m), at=AT, repo_root=tmp_path)
    payload = backfill.build_patch_payload(m, "price_live_123", ref)

    assert payload["rationaleRef"] == ref
    assert (tmp_path / payload["rationaleRef"]).is_file()

    record = read_rationale(payload["rationaleRef"], repo_root=tmp_path)
    # The record and the PATCH must agree on the number, or the audit trail documents a
    # price that was never charged.
    assert record["decision"]["price_pence"] == payload["pricePence"]
    assert record["reason"] == payload["reason"]
    assert record["actor"] == payload["actor"]

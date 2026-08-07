"""Q4b.3 — `store/listings/` must refuse a receipt that isn't one.

The directory is read as authority by three consumers that never re-derive what they find
there: the Control Center Pub badge, `tools/backfill_missing_listings.sh` (a file present
means DONE) and `decay._queue_unlist` (a file present means "this kill was live, unlist
it"). The writer accepted any dict, so two mock fixtures landed in the directory and were
counted as published packs by all three.

The property under test is not "validate_listing rejects nonsense" — it is that the
rejection happens on the WRITE PATH and leaves no file and no `.tmp` behind. A fence that
validates and then writes anyway is the bug it was meant to stop.
"""
from __future__ import annotations

import json

import pytest

from publish.publish import _write_listing, validate_listing


def _receipt(**over):
    r = {
        "candidate_id": "abc123",
        "title": "A pack about something",
        "market": "uk",
        "verified_at": "2026-08-07T00:00:00",
        "published_via": "EngineBridge",
        "catalog": True,
    }
    r.update(over)
    return r


# --- the happy path still works ------------------------------------------------------------

def test_a_real_receipt_is_written(tmp_path):
    cfg = {"store_dir": str(tmp_path)}
    p = _write_listing("abc123", _receipt(), cfg)
    assert p.exists()
    assert json.loads(p.read_text())["candidate_id"] == "abc123"


def test_extra_keys_are_allowed(tmp_path):
    """Adding a field to the receipt must not require editing the fence."""
    cfg = {"store_dir": str(tmp_path)}
    p = _write_listing("abc123", _receipt(price_pence=4900), cfg)
    assert json.loads(p.read_text())["price_pence"] == 4900


# --- the fence -----------------------------------------------------------------------------

@pytest.mark.parametrize("missing", [
    "candidate_id", "title", "market", "verified_at", "published_via", "catalog",
])
def test_every_required_field_is_load_bearing(missing):
    r = _receipt()
    del r[missing]
    with pytest.raises(ValueError, match=missing):
        validate_listing("abc123", r)


def test_the_two_mock_fixtures_shape_is_rejected():
    """What actually got in: a dossier-ish blob with none of the receipt's fields."""
    with pytest.raises(ValueError, match="missing required field"):
        validate_listing("7bdca0e0cb4e0f68", {"id": "7bdca0e0cb4e0f68", "mock": True})


def test_an_empty_dict_is_rejected():
    with pytest.raises(ValueError, match="missing required field"):
        validate_listing("abc123", {})


def test_a_non_dict_is_rejected():
    with pytest.raises(ValueError, match="must be a dict"):
        validate_listing("abc123", ["candidate_id", "abc123"])  # type: ignore[arg-type]


@pytest.mark.parametrize("field,bad", [
    ("title", 42),
    ("market", None),
    ("catalog", "true"),      # the string "true" is not the boolean the CC reads
    ("verified_at", 1754500000),
])
def test_wrong_types_are_rejected(field, bad):
    with pytest.raises(ValueError, match=field):
        validate_listing("abc123", _receipt(**{field: bad}))


def test_a_receipt_filed_under_the_wrong_id_is_rejected():
    """The mismatch that makes the backfill skip one pack forever and re-publish another."""
    with pytest.raises(ValueError, match="does not match the file"):
        validate_listing("abc123", _receipt(candidate_id="deadbeef"))


def test_an_empty_candidate_id_is_rejected():
    with pytest.raises(ValueError, match="non-empty candidate_id"):
        validate_listing("", _receipt(candidate_id=""))


# --- the property that matters: rejection leaves NOTHING on disk ---------------------------

def test_a_rejected_write_leaves_no_file_and_no_tmp(tmp_path):
    cfg = {"store_dir": str(tmp_path)}
    with pytest.raises(ValueError):
        _write_listing("abc123", {"mock": True}, cfg)
    listings = tmp_path / "listings"
    assert not (listings / "abc123.json").exists()
    assert list(listings.glob(".*.tmp")) == [], "a rejected receipt left a temp file behind"


# The regression floor over the operator's real receipts — "every live listing in
# store/listings/ satisfies the rule we now enforce" — is NOT here. It was, and
# tests/test_suite_is_machine_independent.py rejected it: store/ is gitignored, so the
# assertion holds on one machine and skips into vacuity on every clone. It now lives in
# scripts/store_audit.py as the LISTINGS check, which is run where that data exists.

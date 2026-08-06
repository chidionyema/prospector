"""`tools/price_history.py` — the reader that joins a price change to its derivation record.

Two artifacts survive a price move: the `PackPriceHistory` row (who, when, one line of why)
and the D3 rationale record under `store/pricing/rationale/` (which segment, which rung,
which ladder). The row points at the record by path, and until this tool nothing followed
the pointer — so "the derivation is recorded" and "the derivation is retrievable" were
different claims, and only the first was true.

What these tests pin is the part that would otherwise rot silently: the tool must tell the
three outcomes apart. A record that is absent, a record that has been edited since it was
written, and no record at all are three different facts, and only the middle one means the
price cannot be justified. Collapsing them — or reporting a fault as "could not check" —
turns the probe into decoration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from prospector.price_rationale import write_rationale
from prospector.pricing import PriceDecision
from tools import price_history


# --------------------------------------------------------------------------- fakes
class _Response:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _payload(rows, *, continuous=True, current=7900, origin=4900):
    return {
        "packId": "pk-1",
        "currentPricePence": current,
        "currentMinBillablePence": current,
        "publishedAt": "2026-07-01T00:00:00Z",
        "originPricePence": origin,
        "changeCount": len(rows),
        "continuous": continuous,
        "truncated": False,
        "asOf": None,
        "history": rows,
    }


def _row(ref, *, to=7900, frm=4900):
    return {
        "id": 1, "fromPence": frm, "toPence": to, "minBillablePence": frm,
        "providerPriceId": "price_x", "reason": "L1 ladder", "actor": "price-engine",
        "rationaleRef": ref, "createdAt": "2026-07-15T10:00:00Z",
    }


@pytest.fixture
def api(monkeypatch):
    """Serve one canned payload, and record what the tool asked for."""
    state = {"payload": _payload([]), "status": 200, "params": None, "raise": None}

    def _get(url, headers=None, params=None, timeout=None):
        state["params"] = params
        if state["raise"]:
            raise state["raise"]
        return _Response(state["payload"], state["status"])

    monkeypatch.setattr(price_history.requests, "get", _get)
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "k")
    return state


def _write_record(pack_id="pk-1") -> str:
    """A real D3 record via the real writer, under the per-test rationale root."""
    decision = PriceDecision(price_pence=7900, rung="growth-uk",
                             segment={"tier": "growth", "market": "uk"},
                             rationale="ladder")
    cfg = type("C", (), {"listing": {"pricing": {"rungs": [1900, 4900, 7900],
                                                 "ladder_version": "L1-test"}}})()
    return write_rationale(pack_id, decision, cfg, actor="price-engine", source="test")


# --------------------------------------------------------------------------- the three outcomes
def test_a_change_with_a_readable_record_is_coherent(api, capsys):
    ref = _write_record()
    api["payload"] = _payload([_row(ref)])

    assert price_history.main(["pk-1"]) == 0

    out = capsys.readouterr().out
    assert "rationale: OK" in out
    # The derivation itself, not just its filename — the point of following the pointer.
    assert "tier=growth" in out and "L1-test" in out


def test_an_edited_record_is_a_fault_not_a_footnote(api, capsys):
    ref = _write_record()
    path = Path(os.environ["PROSPECTOR_RATIONALE_ROOT"]) / ref
    record = json.loads(path.read_text())
    record["decision"]["price_pence"] = 1900          # someone "corrected" the receipt
    path.write_text(json.dumps(record))

    api["payload"] = _payload([_row(ref)])

    # 1, not 0 and not 3: the record was checked and it is not provenance for anything.
    # Returning 0 here would let a tampered price audit pass a green probe.
    assert price_history.main(["pk-1"]) == 1
    assert "TAMPERED" in capsys.readouterr().out


def test_a_record_the_row_names_but_disk_does_not_have_is_a_fault(api, capsys):
    api["payload"] = _payload([_row("store/pricing/rationale/pk-1/nope-000000000000.json")])

    assert price_history.main(["pk-1"]) == 1
    assert "MISSING" in capsys.readouterr().out


def test_no_rationale_at_all_is_not_a_fault(api, capsys):
    # RationaleRef is optional by contract: a founder-applied change legitimately has none,
    # and flagging that would train the reader to ignore the flag that matters.
    api["payload"] = _payload([_row(None)])

    assert price_history.main(["pk-1"]) == 0
    assert "(none recorded)" in capsys.readouterr().out


# --------------------------------------------------------------------------- the chain
def test_a_discontinuous_chain_fails_even_when_every_record_reads(api, capsys):
    ref = _write_record()
    api["payload"] = _payload([_row(ref)], continuous=False)

    # Every record present and valid, and the answer is still FAIL: a price was applied
    # without a history row, so the record does not account for every price the pack had.
    assert price_history.main(["pk-1"]) == 1
    assert "discontinuous" in capsys.readouterr().err


def test_a_pack_never_repriced_reads_clean(api, capsys):
    api["payload"] = _payload([], current=4900, origin=4900)

    assert price_history.main(["pk-1"]) == 0
    assert "no recorded price changes" in capsys.readouterr().out


# --------------------------------------------------------------------------- broken vs unproven
def test_a_missing_key_is_unproven_not_pass_and_not_fail(monkeypatch, capsys):
    monkeypatch.delenv("STORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.setattr(price_history, "_load_dotenv", lambda: None)

    # 3, the verify_store.sh convention. 0 would report an unchecked pack as audited; 1
    # would send someone to fix a price that was never looked at.
    assert price_history.main(["pk-1"]) == 3
    assert "UNPROVEN" in capsys.readouterr().err


def test_an_unreachable_api_is_unproven(api, capsys):
    api["raise"] = price_history.requests.RequestException("connection refused")

    assert price_history.main(["pk-1"]) == 3
    assert "UNPROVEN" in capsys.readouterr().err


def test_a_wrong_key_is_unproven_and_says_which_key(api, capsys):
    api["status"] = 401

    assert price_history.main(["pk-1"]) == 3
    assert "STORE_INTERNAL_API_KEY" in capsys.readouterr().err


def test_html_from_the_storefront_host_is_unproven_not_a_crash(api, capsys):
    # mumchimp.com serves the storefront and 404s on /catalog; pointing --api-url there
    # returns HTML. A traceback would read as a bug in the tool rather than a wrong host.
    api["payload"] = None

    assert price_history.main(["pk-1"]) == 3
    assert "storefront" in capsys.readouterr().err


# --------------------------------------------------------------------------- passthrough
def test_as_of_reaches_the_endpoint(api):
    api["payload"] = _payload([])
    price_history.main(["pk-1", "--as-of", "2026-07-01T12:00:00Z"])

    # The point-in-time answer is the endpoint's job, not this tool's: recomputing it here
    # would be a second implementation free to disagree with the one the API serves.
    assert api["params"]["asOf"] == "2026-07-01T12:00:00Z"

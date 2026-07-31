"""The reconcile exception ledger is the ONE sanctioned way to make a money probe go green.

reconcile_orders.py answers "did every paying buyer get what they paid for?" with an exit code.
The exception ledger can flip that answer, which makes it the highest-leverage file in the money
rail: a mistake here doesn't produce a wrong number, it produces a green light over a real
customer who was charged and got nothing.

So these tests guard the ledger's refusals, not its happy path. Every one of them asserts that
some plausible-looking input is REJECTED rather than quietly treated as "no exceptions".
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "store_platform" / "scripts" / "reconcile_orders.py"


def _load_module():
    """Import the script by path — store_platform/scripts is not an importable package."""
    spec = importlib.util.spec_from_file_location("reconcile_orders", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rec():
    return _load_module()


def _write(tmp_path: Path, payload) -> Path:
    p = tmp_path / "exceptions.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return p


def test_absent_ledger_means_no_excuses(rec, tmp_path):
    """A missing file must mean 'excuse nothing', so a deleted ledger turns the probe RED.

    The fail-safe direction matters: over-reporting a failure is recoverable, under-reporting it
    means a real paid-without-delivery goes unnoticed.
    """
    assert rec.load_exceptions(tmp_path / "does-not-exist.json") == {}


def test_valid_entry_is_returned(rec, tmp_path):
    p = _write(tmp_path, {"exceptions": {"cs_live_abc": {"reason": "internal test order"}}})
    assert rec.load_exceptions(p)["cs_live_abc"]["reason"] == "internal test order"


def test_blank_reason_is_rejected(rec, tmp_path):
    """Whitespace is not a justification. Without this, the ledger becomes a silencer."""
    p = _write(tmp_path, {"exceptions": {"cs_live_abc": {"reason": "   "}}})
    with pytest.raises(RuntimeError, match="no reason"):
        rec.load_exceptions(p)


def test_missing_reason_key_is_rejected(rec, tmp_path):
    p = _write(tmp_path, {"exceptions": {"cs_live_abc": {"added": "2026-07-31"}}})
    with pytest.raises(RuntimeError, match="no reason"):
        rec.load_exceptions(p)


def test_malformed_json_is_rejected_not_ignored(rec, tmp_path):
    """A typo must not silently degrade to 'no exceptions' — that would flip the verdict."""
    p = _write(tmp_path, "{ not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        rec.load_exceptions(p)


def test_exceptions_must_be_an_object(rec, tmp_path):
    """A list would make `sid in excused` silently false for every session."""
    p = _write(tmp_path, {"exceptions": ["cs_live_abc"]})
    with pytest.raises(RuntimeError, match="must be an object"):
        rec.load_exceptions(p)


def test_null_entry_is_rejected(rec, tmp_path):
    p = _write(tmp_path, {"exceptions": {"cs_live_abc": None}})
    with pytest.raises(RuntimeError, match="no reason"):
        rec.load_exceptions(p)


def test_shipped_ledger_is_valid_and_every_entry_justified(rec):
    """The real checked-in ledger must always load, or production reconcile exits 2."""
    entries = rec.load_exceptions(rec.EXCEPTIONS_PATH)
    for sid, meta in entries.items():
        assert sid.startswith("cs_"), f"{sid} is not a Stripe checkout session id"
        # A reason has to actually explain something; a word or two cannot.
        assert len(meta["reason"]) > 40, f"{sid}: reason is too thin to audit"

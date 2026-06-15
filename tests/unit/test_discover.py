"""Unit tests for the signal-discovery extension (beyond original spec).

Discovery self-sources a diverse portfolio of signals so generation can range
broadly. It judges nothing; the grounded moat downstream still vets every
candidate. These tests cover the two pure pieces — model-response normalisation
and the signals/ audit-trail writer — without touching the live brain.
"""
from __future__ import annotations

import os

import pytest

from prospector.config import load_config
from prospector.discover import discover_signals
from prospector.run import _save_discovered_signals


class _StubOp:
    """Operator stub returning a canned signal payload (no network)."""

    model_version = "stub"

    def __init__(self, payload):
        self._payload = payload

    def complete_json(self, system, user, temperature=0.0):
        return self._payload


@pytest.fixture
def cfg():
    return load_config()


def test_discover_normalises_bare_list_and_drops_empty(cfg):
    op = _StubOp([
        {"title": "Heat-pump installer skills gap",
         "signal_text": "UK grant surge outpaces certified installers.",
         "sector": "energy"},
        {"title": "Vet fee transparency rule",
         "signal_text": "CMA review forces price disclosure for vets.",
         "sector": "healthcare"},
        {"title": "junk", "signal_text": "", "sector": "x"},  # empty text → dropped
    ])
    sigs = discover_signals(op, cfg, n=3)
    assert len(sigs) == 2
    assert {s["sector"] for s in sigs} == {"energy", "healthcare"}
    assert all(s["signal_text"] for s in sigs)


def test_discover_unwraps_dict_payload(cfg):
    # The model sometimes wraps the list under a key; discover must unwrap it.
    op = _StubOp({"signals": [
        {"title": "A", "signal_text": "real change one", "sector": "logistics"},
    ]})
    sigs = discover_signals(op, cfg, n=1)
    assert len(sigs) == 1
    assert sigs[0]["sector"] == "logistics"


def test_discover_returns_empty_on_bad_model_response(cfg):
    # A non-list/non-dict response must yield [] (never raise) so the caller decides.
    op = _StubOp("not json-shaped")
    assert discover_signals(op, cfg, n=2) == []


def test_discover_never_raises_on_operator_error(cfg):
    class _Boom:
        model_version = "boom"

        def complete_json(self, *a, **k):
            raise RuntimeError("model exploded")

    assert discover_signals(_Boom(), cfg, n=2) == []


def test_save_discovered_signals_writes_audit_trail(tmp_path, monkeypatch):
    # Run inside a tmp cwd so the writer's relative signals/ dir is isolated.
    monkeypatch.chdir(tmp_path)
    sigs = [
        {"title": "Heat-pump installer skills gap!!!",
         "signal_text": "  grant surge outpaces installers  ",
         "sector": "energy"},
    ]
    paths = _save_discovered_signals(sigs)
    assert len(paths) == 1
    p = paths[0]
    assert os.path.exists(p)
    assert p.startswith("signals/discovered_")
    # slug is sanitised (no punctuation/spaces) and content is stripped + newline.
    assert "heat_pump_installer_skills_gap" in p
    assert open(p, encoding="utf-8").read() == "grant surge outpaces installers\n"

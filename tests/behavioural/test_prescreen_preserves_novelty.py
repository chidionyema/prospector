"""Prescreen bias-toward-keep tests (Part 3 / Part 16 creativity proof).

Critical invariant: uncertainty defaults to keep=True so that novel,
unconventional opportunities are never silently dropped.
  - Router returns None -> MockOperator returns "{}" -> prescreen keeps.
  - Router returns ambiguous dict (no 'keep' key) -> keeps.
  - Explicit {"keep": false, "reason": "illegal"} -> drops.
  - Exception in op.complete_json -> keeps on uncertainty.
"""
from __future__ import annotations

import pytest
from prospector.config import load_config
from prospector.models import Candidate
from prospector.operator import MockOperator, ParseError
from prospector.prescreen import prescreen


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Novel fintech approach for micro-farmers",
        one_liner="Mobile ledger for informal credit",
        hypothesis="Underbanked smallholders need portable credit history",
        who_pays="NGOs and agri-lenders",
    )


# ---------------------------------------------------------------------------
# Ambiguity / uncertainty -> keep=True
# ---------------------------------------------------------------------------

def test_router_returns_none_keeps_candidate(cfg, cand):
    """Router returning None -> MockOperator falls through to '{}' -> kept.

    prescreen checks data.get('keep') which will be None -> keep=True.
    """
    op = MockOperator(router=lambda s, u: None)
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert score == 0.5


def test_empty_dict_response_keeps_candidate(cfg, cand):
    """Router returning {} (no 'keep' key) -> ambiguous -> kept on uncertainty."""
    op = MockOperator(router=lambda s, u: {})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert score == 0.5


def test_dict_without_keep_key_keeps_candidate(cfg, cand):
    """Response with 'reason' but no 'keep' -> treated as ambiguous, kept."""
    op = MockOperator(router=lambda s, u: {"reason": "Interesting idea"})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert score == 0.5


def test_keep_true_explicit_keeps_candidate(cfg, cand):
    """Explicit keep=True (boolean) -> kept."""
    op = MockOperator(router=lambda s, u: {"keep": True, "score": 0.9, "reason": "Looks promising"})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert score == 0.9
    assert reason == "Looks promising"


def test_keep_string_true_keeps_candidate(cfg, cand):
    """keep='true' (string) -> also kept (only 'false' string triggers rejection)."""
    op = MockOperator(router=lambda s, u: {"keep": "true", "reason": "ok"})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True


# ---------------------------------------------------------------------------
# Explicit rejection
# ---------------------------------------------------------------------------

def test_explicit_keep_false_drops_candidate(cfg, cand):
    """Explicit keep=False (boolean) -> rejected with reason."""
    op = MockOperator(router=lambda s, u: {"keep": False, "reason": "illegal"})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is False
    assert reason == "illegal"


def test_explicit_keep_string_false_drops_candidate(cfg, cand):
    """keep='false' (string, case-insensitive) -> rejected."""
    op = MockOperator(router=lambda s, u: {"keep": "false", "reason": "illegal activity"})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is False
    assert "illegal" in reason


def test_explicit_false_no_reason_uses_default(cfg, cand):
    """keep=False with no reason -> rejected with default reason string."""
    op = MockOperator(router=lambda s, u: {"keep": False})
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is False
    assert reason  # non-empty default


# ---------------------------------------------------------------------------
# Exception in operator -> kept on uncertainty
# ---------------------------------------------------------------------------

def test_operator_exception_keeps_candidate(cfg, cand):
    """Any exception in op.complete_json -> (True, 'kept on uncertainty')."""
    class _BoomOperator(MockOperator):
        def _raw(self, system, user, temperature):
            raise RuntimeError("network error")

    op = _BoomOperator()
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert "uncertainty" in reason.lower()
    assert score == 0.5


# ---------------------------------------------------------------------------
# Non-dict response -> kept on uncertainty
# ---------------------------------------------------------------------------

def test_list_response_keeps_candidate(cfg, cand):
    """A list response (non-dict) is treated as ambiguous -> keep=True."""
    op = MockOperator(router=lambda s, u: ["keep", "yes"])
    keep, score, reason, features = prescreen(op, cfg, cand)
    assert keep is True
    assert score == 0.5

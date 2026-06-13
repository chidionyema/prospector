"""Source-or-die tests (Part 4 / Part 16).

Proves that verdict_for enforces strict grounding:
  1. Empty sources -> verdict forced to unverifiable (degraded=True).
  2. Model returns 'supported' with no citations -> downgraded to unverifiable.
  3. Model returns 'supported' citing an unknown source_id -> downgraded to unverifiable.
  4. Model returns 'refuted' with no citations -> allowed (refuted doesn't need citation).
"""
from __future__ import annotations

import pytest
from prospector.config import load_config
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import verdict_for


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Test Opportunity",
        one_liner="A test",
        hypothesis="Some hypothesis",
        who_pays="SMEs",
    )


REAL_SOURCE = Source.make(url="https://real.example.com", text="Real evidence of market pain.")


# ---------------------------------------------------------------------------
# Empty sources -> unverifiable (graceful degradation)
# ---------------------------------------------------------------------------

def test_empty_sources_returns_unverifiable(cand):
    """When no passages are retrieved, verdict must be unverifiable + degraded."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported", "confidence": 0.9,
        "rationale": "It is supported", "citations": ["anything"],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[])
    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.degraded is True
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# supported + no citations -> downgraded to unverifiable
# ---------------------------------------------------------------------------

def test_supported_with_no_citations_downgraded(cand):
    """Model returns 'supported' but citations=[] -> downgraded to unverifiable."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported",
        "confidence": 0.85,
        "rationale": "Pain is real",
        "citations": [],  # no citations provided
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])
    assert result.verdict == Verdict.UNVERIFIABLE


def test_supported_with_unknown_source_id_downgraded(cand):
    """Model returns 'supported' citing an ID not in the retrieved sources
    -> filtered out -> no valid citations -> downgraded to unverifiable."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported",
        "confidence": 0.85,
        "rationale": "Pain is real",
        "citations": ["deadbeefdeadbeef"],  # ID not in retrieved sources
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])
    assert result.verdict == Verdict.UNVERIFIABLE


# ---------------------------------------------------------------------------
# supported + valid citation -> NOT downgraded
# ---------------------------------------------------------------------------

def test_supported_with_valid_citation_not_downgraded(cand):
    """Model returns 'supported' and cites the real source_id -> verdict kept."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported",
        "confidence": 0.85,
        "rationale": "Pain confirmed by data.",
        "citations": [REAL_SOURCE.source_id],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])
    assert result.verdict == Verdict.SUPPORTED
    assert REAL_SOURCE.source_id in result.citations


# ---------------------------------------------------------------------------
# refuted + no citations -> still refuted (no source-or-die for refuted)
# ---------------------------------------------------------------------------

def test_refuted_without_citations_stays_refuted(cand):
    """Source-or-die only applies to 'supported'. 'refuted' with no valid
    citations is still a refuted verdict — the guard doesn't touch it."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "refuted",
        "confidence": 0.80,
        "rationale": "No evidence of pain.",
        "citations": [],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])
    assert result.verdict == Verdict.REFUTED


# ---------------------------------------------------------------------------
# unverifiable -> stays unverifiable (degraded flag NOT set when operator succeeds)
# ---------------------------------------------------------------------------

def test_unverifiable_stays_unverifiable(cand):
    """Model explicitly returns 'unverifiable' -> kept as-is (not upgraded or crashed)."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "unverifiable",
        "confidence": 0.4,
        "rationale": "Inconclusive evidence.",
        "citations": [],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])
    assert result.verdict == Verdict.UNVERIFIABLE
    # degraded is False here — the operator succeeded, it's just unverifiable
    assert result.degraded is False

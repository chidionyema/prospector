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
from prospector.models import Candidate, CheckResult, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import adversarial, verdict_for


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


# ---------------------------------------------------------------------------
# P1-5: synthesized:// sources are stripped before the verdict (moat rules on
# RETRIEVED pages, never a cheap model's self-synthesis dressed as a source).
# ---------------------------------------------------------------------------

SYNTH_SOURCE = Source.make(url="synthesized://deepseek/knowledge",
                           text="DeepSeek thinks the market is huge.")


def test_synthesized_only_sources_are_not_grounding(cand):
    """If the only 'source' is a synthesized:// self-summary, it is stripped and the
    verdict degrades to unverifiable — never a synthesis-grounded supported."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported", "confidence": 0.9,
        "rationale": "supported", "citations": [SYNTH_SOURCE.source_id],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[SYNTH_SOURCE])
    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.degraded is True


def test_synthesized_source_cannot_be_cited(cand):
    """A real source + a synthesized one: a 'supported' that cites ONLY the
    synthesized id is downgraded (synth is stripped from the valid-citation set)."""
    op = MockOperator(router=lambda s, u: {
        "verdict": "supported", "confidence": 0.9,
        "rationale": "supported", "citations": [SYNTH_SOURCE.source_id],
    })
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE, SYNTH_SOURCE])
    assert result.verdict == Verdict.UNVERIFIABLE


# ---------------------------------------------------------------------------
# P1-6: an adversarial DECISIVE kill must cite evidence (source-or-die).
# ---------------------------------------------------------------------------

def test_adversarial_decisive_without_citations_downgraded(cand):
    """decisive=True with no citations is the model's opinion, not grounded
    disconfirmation -> downgraded to non-decisive so it can't fire the gate."""
    cfg = load_config()
    op = MockOperator(router=lambda s, u: {
        "kill_case": "I just think it's dead", "decisive": True, "citations": [],
    })
    result = adversarial(op, cfg, cand, checks=[])
    assert result.decisive is False


def _check_holding(*sources: Source) -> CheckResult:
    """A minimal CheckResult that actually HOLDS the given passages.

    The adversarial pass is shown `[c.to_dict() for c in checks]`, and CheckResult.to_dict
    ships each source_id — so this is exactly the id set the model can legitimately cite.
    """
    return CheckResult(check_name="pain_reality", verdict=Verdict.UNVERIFIABLE,
                       confidence=0.0, rationale="", sources=list(sources))


def test_adversarial_decisive_with_citations_kept(cand):
    """decisive=True citing a passage we HOLD is grounded -> stays decisive.

    The check must be supplied: previously this passed `checks=[]`, so the cited id
    resolved to nothing and the test proved only that the list was non-empty.
    """
    cfg = load_config()
    op = MockOperator(router=lambda s, u: {
        "critical_regulatory_blocker": True, "impossible_unit_economics": False, "incumbent_monopoly": False, "risk_summary": "Statute X bans it",
        "citations": [REAL_SOURCE.source_id],
    })
    result = adversarial(op, cfg, cand, checks=[_check_holding(REAL_SOURCE)])
    assert result.decisive is True
    assert result.citations == [REAL_SOURCE.source_id]


def test_adversarial_decisive_with_dangling_citation_downgraded(cand):
    """Register §27.2 item 1: an id that RESOLVES TO NOTHING is not evidence.

    Measured on the live corpus before this fence existed: 8 of 142 adversarial_decisive
    kills cited only ids pointing at no retrieved passage (two of them at our own repo
    files). The old guard passed them because the citations LIST was non-empty.
    """
    cfg = load_config()
    op = MockOperator(router=lambda s, u: {
        "critical_regulatory_blocker": True, "impossible_unit_economics": False,
        "incumbent_monopoly": False, "risk_summary": "Statute X bans it",
        "citations": ["src_that_was_never_retrieved"],
    })
    result = adversarial(op, cfg, cand, checks=[_check_holding(REAL_SOURCE)])
    assert result.citations == []
    assert result.decisive is False


def test_adversarial_keeps_only_the_resolving_citations(cand):
    """A mix keeps the real id, drops the invented one, and stays decisive.

    `partial` was 0 in the measured corpus, so this case is not known to occur live — it is
    pinned anyway, because the filter must not be all-or-nothing if it ever does.
    """
    cfg = load_config()
    op = MockOperator(router=lambda s, u: {
        "critical_regulatory_blocker": True, "impossible_unit_economics": False,
        "incumbent_monopoly": False, "risk_summary": "Statute X bans it",
        "citations": [REAL_SOURCE.source_id, "src_invented"],
    })
    result = adversarial(op, cfg, cand, checks=[_check_holding(REAL_SOURCE)])
    assert result.citations == [REAL_SOURCE.source_id]
    assert result.decisive is True

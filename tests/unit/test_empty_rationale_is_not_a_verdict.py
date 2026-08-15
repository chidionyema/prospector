"""A ruling with no reason is not evidence — it is an unevaluated check.

THE DEFECT. `prompts/verdict.md:73-74` requires a rationale grounded in the cited
passages, but nothing enforced it. A reply that parsed cleanly, carried a verdict and a
confidence, and left `rationale` empty flowed into scoring and the kill gates exactly
like a considered finding. That is the `store/dossiers/2102bacc6dd75cf9.kill.json` defect
wearing a different coat: the dossier reads as fully reasoned while the argument field is
blank. `verify.py`'s existing `except Exception` fail-safe cannot catch it, because
nothing raised.

MEASURED (2026-08-15, golden set, fixture-pinned retrieval, the same nine cases):
claude_cli ruled 0 of 27 checks with an empty rationale; minimax ruled 5 of 33 — one of
them a dental `payer_solvency` `unverifiable` whose own reply argued the payer could pay.
The trusted brain's rate is zero, so this guard cannot regress it.

THE RULE. Treat it as a failed verdict CALL, not as a demotion: reuse `degraded` +
`retrieval_failed` so the existing DEFER gate fires unchanged. An unjustified answer is
an unevaluated check, and the honest verdict on an unevaluated check is "come back to
it", never "this idea is dead".
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.kill_filter import is_hard_fail
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import verdict_for


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(title="Test Opportunity", one_liner="A test product",
                     hypothesis="People suffer from X", who_pays="SMEs")


def _sources() -> list[Source]:
    """Real passages, so the check reaches the parse path rather than the
    no-passages graceful-degradation branch at the top of verdict_for."""
    return [Source(source_id="S1", url="https://example.com/a",
                   text="Incumbent vendors already serve this segment at scale.",
                   published_at="2024-01-01")]


def _op(payload: dict) -> MockOperator:
    return MockOperator(router=lambda system, user: payload)


@pytest.mark.parametrize("rationale", ["", "   ", "\n\t "])
@pytest.mark.parametrize("verdict_word", ["unverifiable", "refuted", "supported"])
def test_blank_rationale_is_a_failed_call_not_a_finding(cfg, cand, rationale,
                                                       verdict_word):
    """Every verdict word, not just `unverifiable`. A REFUTED with no reason is the
    worse case: it is a KILL the operator cannot see the evidence for."""
    res = verdict_for(_op({"verdict": verdict_word, "confidence": 0.9,
                           "rationale": rationale, "citations": ["S1"]}),
                      cand, "incumbency", _sources(), cfg)

    assert res.retrieval_failed is True, "must fire the DEFER gate, not rule"
    assert res.degraded is True
    assert res.verdict == Verdict.UNVERIFIABLE
    assert res.confidence == 0.0
    assert res.rationale.strip(), "the fail-safe must say WHY it is a fail-safe"
    # Same protection the outage path gets: a retrieval_failed check may never hard-fail.
    assert is_hard_fail("incumbency", res, cfg) is False


def test_a_missing_rationale_key_is_treated_the_same(cfg, cand):
    """Absent is not weaker than blank — both mean the brain gave no reason."""
    res = verdict_for(_op({"verdict": "refuted", "confidence": 0.8,
                           "citations": ["S1"]}),
                      cand, "incumbency", _sources(), cfg)
    assert res.retrieval_failed is True
    assert res.verdict == Verdict.UNVERIFIABLE


def test_a_reasoned_verdict_is_untouched(cfg, cand):
    """The contrast case that stops this guard becoming a blanket DEFER: a verdict WITH
    a rationale rules normally and is not marked degraded."""
    res = verdict_for(_op({"verdict": "refuted", "confidence": 0.8,
                           "rationale": "Salesforce and HubSpot already serve this "
                                        "segment [S1], so the space is occupied.",
                           "citations": ["S1"]}),
                      cand, "incumbency", _sources(), cfg)

    assert res.retrieval_failed is False, "a reasoned verdict must not DEFER"
    assert res.degraded is False
    assert "Salesforce" in res.rationale
    assert res.verdict == Verdict.REFUTED

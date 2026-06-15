"""Retrieval failure must DEFER, never KILL (moat-integrity).

The defect this guards against: a transient web-search outage produced an empty
passage set, which collapsed to `unverifiable`, which is a hard-fail for
value_durability — so an infrastructure failure masqueraded as a grounded kill.

The fix distinguishes:
  - search RAISED (outage)             -> retrieval_failed=True -> Decision.DEFER
  - search returned [] (looked, empty) -> unverifiable          -> no silence-kill

Silence (unverifiable) is NOT evidence: it can neither defer (it's not an outage)
nor kill (a KILL must be grounded in cited disconfirming evidence). Both paths are
asserted here so the distinction can't silently regress.
"""
from __future__ import annotations

import pytest
from prospector.config import load_config
from prospector.kill_filter import is_hard_fail
from prospector.models import Candidate, Decision, DEFER_GATE, Verdict
from prospector.operator import MockOperator
from prospector.retrieval import SearchProvider
from prospector.run import vet_candidate
from prospector.verify import verify


class FailingProvider(SearchProvider):
    """Every search raises — simulates a CLI/transport outage."""
    def search(self, query: str, k: int = 4, max_chars: int = 1500):
        raise RuntimeError("simulated gemini CLI outage")


class EmptyProvider(SearchProvider):
    """Every search succeeds but finds nothing — a legitimate empty result."""
    def search(self, query: str, k: int = 4, max_chars: int = 1500):
        return []


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.fast_queries = 1
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(title="Test Opportunity", one_liner="A test product",
                     hypothesis="People suffer from X", who_pays="SMEs")


def test_failed_search_marks_retrieval_failed_and_never_hard_fails(cfg, cand):
    op = MockOperator()
    checks, adv, gate = verify(op, FailingProvider(), cfg, cand)

    # verify() defers — the gate is the defer sentinel, NOT value_durability.
    assert gate == DEFER_GATE, f"expected defer sentinel, got {gate!r}"
    assert adv is None

    first = checks[0]
    assert first.retrieval_failed is True
    assert first.verdict == Verdict.UNVERIFIABLE
    # The kill filter must REFUSE to fail a retrieval-failed check, even though
    # value_durability normally kills on 'unverifiable'.
    assert is_hard_fail(first.check_name, first, cfg) is False


def test_vet_candidate_defers_on_outage_not_kill(cfg, cand):
    op = MockOperator()
    d = vet_candidate(cand, op, FailingProvider(), cfg)
    assert d.decision == Decision.DEFER, f"outage must DEFER, got {d.decision}"
    assert d.gate_fired is None          # no real gate fired
    assert d.score is None               # not scored
    assert "retriev" in d.reason.lower()


def test_grounding_provider_propagates_transport_failure(monkeypatch):
    """Regression for the real-provider gap: the unit DEFER path only fires if search()
    RAISES, but the live GeminiCliGroundingProvider used to swallow transport errors and
    return [] — making an outage indistinguishable from 'found nothing' and wrongly KILL.
    A transport failure (run_gemini_cli gave up after retries) MUST propagate."""
    from prospector import gemini_cli
    from prospector.gemini_cli import GeminiCliGroundingProvider

    def boom(*a, **k):
        raise RuntimeError("gemini cli failed after 3 attempts: QUOTA_EXHAUSTED")
    monkeypatch.setattr(gemini_cli, "run_gemini_cli", boom)
    with pytest.raises(RuntimeError):
        GeminiCliGroundingProvider().search("anything")


def test_grounding_provider_empty_on_ran_but_no_results(monkeypatch):
    """Contrast: the search RAN but produced no parseable/usable JSON — that is a
    legitimate empty result, NOT an outage, so it returns [] (caller may KILL)."""
    from prospector import gemini_cli
    from prospector.gemini_cli import GeminiCliGroundingProvider
    monkeypatch.setattr(gemini_cli, "run_gemini_cli", lambda *a, **k: "no json here")
    assert GeminiCliGroundingProvider().search("anything") == []


def test_legit_empty_result_does_not_silence_kill_nor_defer(cfg, cand):
    """Contrast case: a search that genuinely finds nothing is NOT an outage, so it
    must not DEFER. But silence is not evidence either, so NO hard gate may fire —
    unverifiable checks fall through to scoring, where a low composite stops it
    publishing. The kill (if any) is a score-stage rejection, never a silence-kill."""
    op = MockOperator()
    d = vet_candidate(cand, op, EmptyProvider(), cfg)
    # Not deferred: a genuine empty result is not a retrieval outage.
    assert d.decision != Decision.DEFER
    # No HARD gate fired on an all-unverifiable candidate (silence is not evidence).
    # It may still be killed downstream at scoring (gate_fired == "min_composite").
    hard_gates = set(cfg.gate_map().keys())
    assert d.gate_fired not in hard_gates
    # And it is NOT mislabelled as a retrieval failure.
    vd = next(c for c in d.checks if c.check_name == "value_durability")
    assert vd.retrieval_failed is False

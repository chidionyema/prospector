"""Graceful degradation tests (Part 9).

Proves that the engine fails safely and never crashes when:
  1. FixtureProvider returns [] for all queries -> verdict forced to unverifiable;
     verify() runs every check and fires NO gate (silence is not evidence) but does
     NOT raise.
  2. MockOperator router raises inside a verdict call -> verdict_for returns
     unverifiable (degraded=True), no crash propagated.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import DEFER_GATE, run_check, verdict_for, verify

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.results_per_query = 1
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Graceful Degradation Test Candidate",
        one_liner="Test",
        hypothesis="Testing fault tolerance",
        who_pays="Nobody",
    )


# ---------------------------------------------------------------------------
# Empty FixtureProvider (all queries return []) -> graceful unverifiable
# ---------------------------------------------------------------------------

class _EmptyProvider(FixtureProvider):
    """Always returns empty list for any query."""
    def __init__(self):
        super().__init__(fixtures={})

    def search(self, query, k=4, max_chars=1500):
        return []


def _query_router(system: str, user: str):
    """Returns valid query lists so gen_queries never crashes."""
    if "queries most likely" in system or "Write 1-3 queries" in user:
        return ["test query"]
    return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}


def test_empty_provider_yields_unverifiable_not_crash(cfg, cand):
    """run_check with an empty provider should return Verdict.UNVERIFIABLE degraded=True,
    not raise an exception."""
    op = MockOperator(router=_query_router)
    provider = _EmptyProvider()

    result = run_check(op, provider, cfg, cand, "pain_reality")

    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.degraded is True
    assert result.check_name == "pain_reality"


def test_verify_with_empty_provider_does_not_kill_or_raise(cfg, cand):
    """verify() with an empty provider should terminate cleanly, never raise.

    Silence is not cited disconfirming evidence — no HARD gate (refuted kill) may
    fire. Soft PASS-floor early-exit (moat_ungrounded / source_or_die) is allowed:
    same final KILL as finishing the suite then failing those floors in
    build_dossier, without paying for adversarial/score on a dead idea.
    """
    from prospector.pass_ceiling import SOFT_EXIT_GATES

    op = MockOperator(router=_query_router)
    provider = _EmptyProvider()

    # Must not raise
    checks, adv, gate = verify(op, provider, cfg, cand)

    assert len(checks) >= 1

    # Hard gates must not fire on silence; soft PASS-floor exit is OK.
    hard = set(cfg.gate_map())
    assert gate is None or gate in SOFT_EXIT_GATES, (
        f"Silence must not fire a hard gate, got {gate!r}")
    assert gate not in hard

    # All returned checks should be degraded (no passages retrieved)
    for check in checks:
        assert check.degraded is True


def test_run_check_empty_provider_multiple_checks_no_crash(cfg, cand):
    """Run multiple run_check calls with empty provider — none should raise."""
    op = MockOperator(router=_query_router)
    provider = _EmptyProvider()

    for check_name in ["pain_reality", "value_durability", "incumbency"]:
        result = run_check(op, provider, cfg, cand, check_name)
        assert result.verdict == Verdict.UNVERIFIABLE
        assert result.degraded is True


# ---------------------------------------------------------------------------
# Operator router raises inside verdict call -> fail-safe unverifiable
# ---------------------------------------------------------------------------

REAL_SOURCE = Source.make(
    url="https://evidence.example.com",
    text="Some real evidence text for testing."
)


def test_verdict_for_operator_raises_returns_unverifiable(cand):
    """If the operator raises during a verdict call, verdict_for must return
    Verdict.UNVERIFIABLE degraded=True without propagating the exception."""
    class _BoomOnVerdictOperator(MockOperator):
        def _raw(self, system: str, user: str, temperature: float) -> str:
            # Raise on any actual verdict call (which includes 'Passages:' in user)
            if "Passages:" in user:
                raise ConnectionError("simulated network failure in verdict call")
            # For query_gen calls, return a valid response
            return '["test query"]'

    op = _BoomOnVerdictOperator()
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])

    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.degraded is True


def test_verdict_for_operator_raises_for_all_retries_no_crash(cand):
    """When operator keeps raising (exhausts retries), verdict_for returns
    unverifiable fail-safe rather than surfacing ParseError."""
    class _AlwaysRaisesOperator(MockOperator):
        def _raw(self, system: str, user: str, temperature: float) -> str:
            raise RuntimeError("permanent failure")

    op = _AlwaysRaisesOperator()
    # Must not raise — verdict_for catches Exception from complete_json
    result = verdict_for(op, cand, "pain_reality", sources=[REAL_SOURCE])

    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.degraded is True


def test_verify_with_crashing_operator_does_not_raise(cfg, cand):
    """verify() with an operator that crashes on verdict calls should not
    surface the exception — it kills gracefully."""
    class _BoomOperator(MockOperator):
        def _raw(self, system: str, user: str, temperature: float) -> str:
            if "Passages:" in user:
                raise RuntimeError("verdict call exploded")
            return '["query"]'

    search = FixtureProvider(fixtures={
        "pain": [{"url": "https://x.com", "text": "some pain evidence"}],
        "value": [{"url": "https://y.com", "text": "some value evidence"}],
        "incumbent": [{"url": "https://z.com", "text": "no incumbents"}],
        "payer": [{"url": "https://p.com", "text": "payer solvent"}],
        "distribution": [{"url": "https://d.com", "text": "channel exists"}],
        "legal": [{"url": "https://l.com", "text": "fully legal"}],
    })

    op = _BoomOperator()

    # Must not raise
    checks, adv, gate = verify(op, search, cfg, cand)

    # All checks that ran should be degraded (operator crashed on verdict)
    for check in checks:
        assert check.degraded is True
        assert check.verdict == Verdict.UNVERIFIABLE


def test_crashed_verdict_call_defers_never_kills(cfg, cand):
    """A verdict call that CRASHED must defer the candidate, never kill it.

    Regression for 2026-08-06. `verdict_for`'s generic-exception path returned a plain
    `unverifiable` CheckResult with no `retrieval_failed` flag, so an outage flowed into
    scoring and the kill gates as though it were a finding about the idea. Proof it bit:
    store/dossiers/2102bacc6dd75cf9.kill.json is a KILL on gate `min_composite` whose
    SEVEN checks all read `unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — a
    candidate killed by our own infrastructure, in a dossier that reads as fully reasoned.

    An exception is not evidence. The gate that fires must be the DEFER gate.

    Mutation test: drop `retrieval_failed=True` from that CheckResult in verify.py and
    this fails — the gate comes back as a kill gate instead of DEFER_GATE.
    """
    class _BoomOperator(MockOperator):
        def _raw(self, system: str, user: str, temperature: float) -> str:
            if "Passages:" in user:
                raise RuntimeError("verdict call exploded")
            return '["query"]'

    # Catch-all key: EVERY query retrieves a passage, so every check reaches verdict_for and
    # crashes there. Keyed fixtures would let an unmatched query short-circuit on "no passages"
    # instead — a different code path (retrieval_failed stays False by design, because silence
    # from the web is a fact about the web) which would not exercise the bug under test.
    search = FixtureProvider(fixtures={
        "": [{"url": "https://evidence.example.com", "text": "some retrieved evidence"}],
    })

    checks, _adv, gate = verify(_BoomOperator(), search, cfg, cand)

    assert checks, "expected at least one check to have run"
    for check in checks:
        assert check.retrieval_failed is True, (
            f"{check.check_name} recorded a crashed verdict call as evidence")
    assert gate == DEFER_GATE, (
        f"a crashed verdict call fired {gate!r} instead of deferring — this is the shape "
        "that killed candidate 2102bacc6dd75cf9")

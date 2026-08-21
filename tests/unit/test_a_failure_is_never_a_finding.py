"""A component's own FAILURE must never be written as a FINDING about the idea.

This repo already fixed this class once, at the verdict stage: `verify.run_check` sets
`retrieval_failed=True` so a raised call DEFERS instead of contributing an `unverifiable`
to the kill gates. `store/dossiers/2102bacc6dd75cf9.kill.json` is the dossier that bought
that fix — a KILL on `min_composite` whose seven checks all read "Verdict call failed;
fail-safe", in a document that reads as fully reasoned.

A specialist review on 2026-08-21 found the same class alive at the two stages AFTER it,
and each escapes in the opposite direction:

  adversarial() raised  -> AdversarialResult(decisive=False) -> reads as "no decisive case
                           against it" -> PASS -> published. An UNVERIFIED candidate in
                           front of a paying buyer.
  score_candidate() raised -> all-zero scores -> composite 0.0 -> KILL on `min_composite`,
                           with a buyer-facing reason quoting a bar the idea never met
                           because nothing ever scored it.

Both are guarded here, each with a control arm: the same pipeline with nothing broken must
NOT defer, otherwise these tests would pass on an engine that defers everything.

The third test guards the estimator those decisions rest on. `_calc_confidence` counted
repeated citations of ONE source as independent evidence.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.models import DEFER_REASONS, Candidate, Decision, Source
from prospector.operator import MockOperator
from prospector.retrieval import SearchProvider
from prospector.run import vet_candidate
from prospector.verify import _calc_confidence

#: Markers that identify a stage by its system prompt. MockOperator routes on substrings.
VERDICT_MARKER = "ruthless, evidence-bound analyst"
ADVERSARIAL_MARKER = "risk auditor"
SCORE_MARKER = "Score a vetted opportunity"

_SUPPORTED = {"verdict": "supported", "confidence": 0.9,
              "rationale": "The passage states councils charge landlords an annual fee.",
              "citations": ["s1"]}
_SCORES = {"scores": {"defensibility": 4, "pain_acuity": 4, "money_provability": 4,
                      "automatability": 4, "distribution": 4, "build_feasibility": 4},
           "justification": {k: "grounded in s1" for k in
                             ("defensibility", "pain_acuity", "money_provability",
                              "automatability", "distribution", "build_feasibility")}}
_NO_CASE = {"kill_case": "No decisive objection survives the evidence.",
            "decisive": False, "confidence": 0.1, "citations": ["s1"], "objections": []}


class _OneSource(SearchProvider):
    def search(self, query: str, k: int = 4, max_chars: int = 1500):
        return [Source(source_id="s1", url="https://x.gov.uk/a",
                       text="councils charge landlords an annual compliance fee")]


def _router(break_at: str | None):
    """Answer every stage properly, except `break_at`, which raises like a dead adapter."""
    def route(system: str, user: str):
        if break_at and break_at in system:
            raise RuntimeError(f"simulated adapter crash at {break_at!r}")
        if VERDICT_MARKER in system:
            return _SUPPORTED
        if ADVERSARIAL_MARKER in system:
            return _NO_CASE
        if SCORE_MARKER in system:
            return _SCORES
        return None
    return route


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
    return Candidate(title="Landlord Compliance Fee Recovery", one_liner="A test product",
                     hypothesis="Landlords overpay compliance fees", who_pays="Landlords")


def _vet(cfg, cand, break_at):
    return vet_candidate(cand, MockOperator(router=_router(break_at)), _OneSource(), cfg)


def test_control_arm_nothing_broken_does_not_defer(cfg, cand):
    """Without this, both tests below would pass on an engine that defers everything."""
    d = _vet(cfg, cand, break_at=None)
    assert d.decision is not Decision.DEFER, (
        f"the control arm deferred ({d.gate_fired!r}: {d.reason}) — the two tests below "
        f"would then prove nothing")


def test_a_crashed_adversarial_pass_defers_instead_of_publishing(cfg, cand):
    d = _vet(cfg, cand, break_at=ADVERSARIAL_MARKER)
    assert d.decision is Decision.DEFER, (
        f"the final gate never ran, so the candidate is UNCHALLENGED, not cleared. "
        f"Got {d.decision} ({d.gate_fired!r}) — a PASS here publishes it.")
    assert d.gate_fired is None, "a defer records no gate; nothing was decided"
    assert "adversarial" in d.reason.lower()
    # The reason must not read as a clean bill of health.
    assert "unchallenged" in d.reason.lower() or "never" in d.reason.lower()


def test_a_crashed_scorer_defers_instead_of_killing_on_min_composite(cfg, cand):
    d = _vet(cfg, cand, break_at=SCORE_MARKER)
    assert d.decision is Decision.DEFER, (
        f"nothing scored the idea, so 0.0 is a fail-safe and not a low score. "
        f"Got {d.decision} ({d.gate_fired!r}): {d.reason}")
    assert d.gate_fired is None
    assert "min_composite" not in (d.reason or ""), (
        "the buyer-facing reason must not quote a bar the idea was never measured against")


def test_both_new_reasons_are_declared_defers_not_kills():
    """The strings verify.py and dossier.py emit must be IN DEFER_REASONS. If either is
    ever renamed on one side only, it silently becomes a KILL gate again."""
    assert "adversarial_unrun" in DEFER_REASONS
    assert "score_failed" in DEFER_REASONS


def test_one_source_cited_three_times_is_still_one_source():
    """`citations` is filtered to valid ids but was not deduplicated, so `cited/total` was
    not a fraction and `min(1, cited/3)` counted the same passage repeatedly. Confidence
    feeds confidence_floor, min_supported_confidence and dense_reward's KILL branch."""
    s = Source(source_id="s1", url="https://x.gov.uk/a",
               text="landlords pay fees for compliance checks every year")
    q = "Do landlords pay for compliance checks?"
    once = _calc_confidence([s], ["s1"], q)
    assert _calc_confidence([s], ["s1", "s1", "s1"], q) == once
    assert _calc_confidence([s], ["s1"] * 10, q) == once
    # Two DISTINCT sources must still beat one source cited twice — otherwise the fix
    # has flattened the diversity term along with the duplicate.
    s2 = Source(source_id="s2", url="https://other.gov.uk/b",
                text="landlords pay fees for compliance checks every year")
    assert _calc_confidence([s, s2], ["s1", "s2"], q) > _calc_confidence([s, s2], ["s1", "s1"], q)

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
from prospector.models import DEFER_GATE, Candidate, Decision, Verdict
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


def test_a_genuinely_empty_search_says_so_in_json_and_does_not_defer(monkeypatch):
    """An empty result must be EXPRESSED, not inferred from our failure to read the reply.

    This replaces `test_grounding_provider_empty_on_ran_but_no_results`, which asserted the
    opposite and whose docstring stated the reasoning being retired here: "the search RAN
    but produced no parseable/usable JSON — that is a legitimate empty result, NOT an
    outage, so it returns [] (caller may KILL)."

    That conflates the search running with the ANSWER being read. We get bytes back and
    cannot parse them; that is a fact about our parser, and on 2026-08-15 it was literally
    that — `_extract_json` parsed JSON in strict mode and scanned `[`…`]` before `{`…`}`, so
    ONE literal newline inside a model's rationale made it return the wrong array. Under the
    old rule our own parser defect arrived downstream wearing the costume of "the web has
    nothing on this", and a candidate could be KILLed on it with a dossier that read as
    fully reasoned.

    The asymmetry that settles it: a model with nothing to report CAN say so parseably —
    `[]` is valid JSON and the prompt asks for a JSON array — so an unreadable reply is a
    protocol violation, not a null result. Treating it as empty feeds a fabricated finding
    into the kill gates and is unrecoverable. Treating it as a failure costs a failover, and
    only a whole dead chain becomes a DEFER, which `vet --resume` finalises later. "The
    honest verdict on an unevaluated check is 'come back to it', never 'this idea is dead'."
    """
    from prospector import gemini_cli
    from prospector.gemini_cli import GeminiCliGroundingProvider
    monkeypatch.setattr(gemini_cli, "run_gemini_cli", lambda *a, **k: "[]")
    assert GeminiCliGroundingProvider().search("anything") == [], (
        "a search that genuinely found nothing must still return [] and must NOT raise — "
        "otherwise every empty result becomes a DEFER and the line stops")


def test_an_unreadable_reply_is_a_failure_not_an_empty_result(monkeypatch):
    """The other half of the distinction, and the one that was missing.

    `[]` and 'we could not read the answer' must not be the same bytes. If they are, the
    chain books a breaker SUCCESS, clears the provider's dead mark and short-circuits
    (`FallbackSearchProvider.search`, retrieval.py:1860-1895) — so a broken provider stays
    in rotation AND its silence counts as evidence.
    """
    from prospector import gemini_cli
    from prospector.gemini_cli import GeminiCliGroundingProvider
    from prospector.operator import ParseError

    monkeypatch.setattr(gemini_cli, "run_gemini_cli", lambda *a, **k: "no json here")
    with pytest.raises(ParseError):
        GeminiCliGroundingProvider().search("anything")


def test_the_same_rule_holds_for_the_claude_grounding_adapter(monkeypatch):
    """claude_cli is the always-available backstop at the END of the retrieval chain
    (`config.yaml retrieval.provider: [ddg, exa, claude_cli]`), so it is the provider whose
    silence is most likely to be read as the web's. Pinned on both adapters because fixing
    one and leaving the other is how this class survives a fix."""
    from prospector import claude_cli
    from prospector.claude_cli import ClaudeCliGroundingProvider
    from prospector.operator import ParseError

    monkeypatch.setattr(claude_cli, "run_claude_cli", lambda *a, **k: "I could not search.")
    with pytest.raises(ParseError):
        ClaudeCliGroundingProvider().search("anything")

    monkeypatch.setattr(claude_cli, "run_claude_cli", lambda *a, **k: "[]")
    assert ClaudeCliGroundingProvider().search("anything") == []


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

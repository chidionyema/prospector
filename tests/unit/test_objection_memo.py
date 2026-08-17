"""The case against an idea was one paragraph. Now it is a memo, and every line cites.

THE DEFECT. `verify.adversarial` returned a single `risk_summary` blob, and the dossier
printed it under "The case against". A reader got our conclusion and no way to work with
it: no separate objections, no order of severity, and no statement of what would have to be
true for an objection not to bite. That is the shape of a verdict, not of diligence.

THE RULE, pinned below. The pass now also returns 2-4 objections, and each one:
  - carries at least one source_id that RESOLVES to a passage the brain was actually shown.
    An objection citing nothing is an opinion. Opinions do not ship in this engine, and the
    same rail already guards the pass's top-level citations (`verify.py`, the `_dangling`
    filter) and its `decisive` flag;
  - states what would have to be true for it not to bite, so the reader knows what to check;
  - is capped at four. A list of twelve buries the strongest objection among makeweights.
"""
from __future__ import annotations

import pytest

from prospector.config import load_config
from prospector.dossier import render_markdown
from prospector.models import AdversarialResult, Candidate, CheckResult, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import MAX_OBJECTIONS, adversarial


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


def _checks() -> list[CheckResult]:
    """One check whose sources are the only citable ids in the run."""
    return [CheckResult(
        check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.8,
        rationale="Practitioners describe the problem directly.",
        citations=["S1"],
        sources=[Source(source_id="S1", url="https://example.com/a",
                        text="Buyers in this segment report the problem weekly.",
                        published_at="2026-01-01"),
                 Source(source_id="S2", url="https://example.com/b",
                        text="One vendor holds most of the channel.")])]


def _run(cfg, cand, payload: dict) -> AdversarialResult:
    return adversarial(MockOperator(router=lambda system, user: payload), cfg, cand,
                       _checks())


BASE = {"critical_regulatory_blocker": False, "impossible_unit_economics": False,
        "incumbent_monopoly": False, "risk_summary": "Nothing decisive.",
        "citations": ["S1"]}


def test_a_grounded_objection_survives_with_its_answer(cfg, cand):
    res = _run(cfg, cand, BASE | {"objections": [
        {"objection": "The channel is controlled by one vendor.",
         "what_would_have_to_be_true": "A second route to the buyer exists.",
         "severity": "high", "citations": ["S2"]}]})
    assert len(res.objections) == 1
    ob = res.objections[0]
    assert ob["objection"] == "The channel is controlled by one vendor."
    assert ob["what_would_have_to_be_true"] == "A second route to the buyer exists."
    assert ob["severity"] == "high"
    assert ob["citations"] == ["S2"]


def test_an_uncited_objection_is_dropped(cfg, cand):
    res = _run(cfg, cand, BASE | {"objections": [
        {"objection": "It feels crowded.", "severity": "high", "citations": []}]})
    assert res.objections == []


def test_an_objection_citing_a_passage_we_never_retrieved_is_dropped(cfg, cand):
    """The id must RESOLVE. A plausible-looking hash is not a receipt."""
    res = _run(cfg, cand, BASE | {"objections": [
        {"objection": "Regulators are circling.", "severity": "high",
         "citations": ["deadbeefdeadbeef"]}]})
    assert res.objections == []


def test_the_memo_is_capped(cfg, cand):
    many = [{"objection": f"Objection {i}", "what_would_have_to_be_true": "x",
             "severity": "low", "citations": ["S1"]} for i in range(12)]
    assert len(_run(cfg, cand, BASE | {"objections": many}).objections) == MAX_OBJECTIONS


def test_an_invented_severity_becomes_unknown_rather_than_printing(cfg, cand):
    res = _run(cfg, cand, BASE | {"objections": [
        {"objection": "Costs may rise.", "severity": "catastrophic",
         "citations": ["S1"]}]})
    assert res.objections[0]["severity"] == "unknown"


def test_a_pass_with_no_objections_still_returns_a_result(cfg, cand):
    """The memo is additive. Nothing about the existing pass may depend on it."""
    res = _run(cfg, cand, BASE)
    assert res.objections == []
    assert res.kill_case == "Nothing decisive."
    assert res.decisive is False


class _Dossier:
    """The renderer reads its input with getattr, so a stub is the honest fixture."""
    def __init__(self, adv):
        self.candidate = Candidate(title="T", one_liner="o", hypothesis="h", who_pays="w")
        self.checks = _checks()
        self.adversarial = adv
        self.decision = None
        self.score = None
        self.sources = self.checks[0].sources


def test_the_memo_reaches_the_page():
    adv = AdversarialResult(
        kill_case="Nothing decisive.", decisive=False, citations=["S1"],
        objections=[{"objection": "The channel is controlled by one vendor.",
                     "what_would_have_to_be_true": "A second route to the buyer exists.",
                     "severity": "high", "citations": ["S2"]}])
    md = render_markdown(_Dossier(adv))
    assert "The channel is controlled by one vendor." in md
    assert "What would have to be true for this not to bite: A second route" in md
    assert "High risk" in md

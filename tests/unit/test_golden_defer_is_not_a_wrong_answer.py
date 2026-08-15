"""A deferred golden case is NO answer, and must never be scored as a WRONG one.

THE DEFECT, measured 2026-08-15. `claude_cli` hit its usage limit partway through a
promotion run (18 `usage limit` / 14 HTTP 429 lines in the run log). The last three cases
DEFERRED — the engine behaving correctly, per "an exception is never evidence; a failed
call DEFERS" (verify.py). The harness that judges brains had no counterpart to that rule:
it compared `defer` to the expected `kill`/`pass`, found a mismatch, and printed
`discrimination=0.67 (6/9) → FAIL`. That number is a measurement of OUR outage published
as a verdict on the brain — the same misattribution that, earlier the same night, blamed
minimax for a fixture it could not have passed.

THE RULE, asserted here:
  1. A deferred case is excluded from the DENOMINATOR (not counted correct or incorrect).
  2. Any defer makes the whole RUN inconclusive, because a score over six cases is not
     comparable with one over nine — so it may neither promote a challenger nor fail one.
  3. The per-case guards that blame the FIXTURE FILE ("NO EVIDENCE") must stay silent on a
     deferred case: it short-circuits before its checks ever attach passages, so firing
     there accuses the fixtures of an outage. Both deferred cases in that run did exactly
     this.
"""
from __future__ import annotations

import json

import pytest

from prospector.config import load_config
from prospector.golden import run_golden_set
from prospector.models import Candidate, CheckResult, Decision, Source, Verdict


def _FakeCheck() -> CheckResult:
    """One check that actually saw a passage — what a RULED case looks like.

    A real CheckResult, not a stub: run_golden_set's audit record reads verdict,
    confidence, citations, degraded and retrieval_failed off it, and a stub that
    grows attributes only as the assertions demand them tests the stub."""
    return CheckResult(
        check_name="value_durability", verdict=Verdict.REFUTED, confidence=0.9,
        rationale="the passage says so", citations=["a" * 16],
        sources=[Source(source_id="a" * 16, url="https://example.com/x",
                        text="evidence", retrieved_by="fixture")])


class _FakeDossier:
    def __init__(self, decision: Decision, gate=None, reason="", ruled=True):
        self.decision = decision
        self.gate_fired = gate
        self.reason = reason
        # A ruled case reaches retrieval and attaches passages; a DEFERRED case
        # short-circuits before that. Modelling both is the point of this file: the
        # zero-passage state is what made the NO EVIDENCE guard misfire on defers.
        self.checks = [_FakeCheck()] if ruled else []


@pytest.fixture
def golden_file(tmp_path):
    """Three cases: two the brain rules on, one it defers."""
    p = tmp_path / "golden.json"
    p.write_text(json.dumps([
        {"idea": "Ruled Right", "expected": "kill"},
        {"idea": "Ruled Wrong", "expected": "kill"},
        {"idea": "Never Ruled", "expected": "kill"},
    ]), encoding="utf-8")
    return str(p)


def _vet_fn(cand: Candidate, *a, **k) -> _FakeDossier:
    if cand.title == "Ruled Right":
        return _FakeDossier(Decision.KILL, "value_durability")
    if cand.title == "Ruled Wrong":
        return _FakeDossier(Decision.PASS)
    return _FakeDossier(Decision.DEFER, None, "moat exhausted: usage limit reached",
                        ruled=False)


def test_defer_leaves_the_denominator_not_the_numerator(golden_file, capsys):
    cfg = load_config()
    disc, results = run_golden_set(None, None, cfg, golden_file, verbose=True,
                                   _vet_fn=_vet_fn)

    # 1 correct of the 2 actually RULED — not 1 of 3. Scoring the defer as a miss would
    # give 0.33 and read as a materially worse brain.
    assert disc == pytest.approx(0.5), (
        f"expected 1/2 over the ruled cases, got {disc}")

    by_idea = {r["idea"]: r for r in results}
    assert by_idea["Never Ruled"]["deferred"] is True
    assert by_idea["Never Ruled"]["passed"] is False, (
        "a defer is not a pass either — it is simply not scored")
    assert by_idea["Ruled Right"]["deferred"] is False
    assert by_idea["Ruled Wrong"]["deferred"] is False


def test_the_run_says_inconclusive_and_does_not_blame_the_fixtures(golden_file, capsys):
    cfg = load_config()
    run_golden_set(None, None, cfg, golden_file, verbose=True, _vet_fn=_vet_fn)
    out = capsys.readouterr().out

    assert "INCONCLUSIVE" in out, "a run containing a defer must say so, loudly"
    assert "usage limit" in out, "and must surface WHY the brain never ruled"
    # The fixture-hole guard must not fire on a case that never got as far as retrieval.
    assert "NO EVIDENCE" not in out, (
        "a deferred case has no passages because it short-circuited, not because the "
        "fixture file is missing a key — printing this accuses the fixtures of an outage")


def test_a_clean_run_is_unaffected(golden_file, capsys):
    """The contrast case: with no defers the metric and the wording are unchanged, so
    this guard cannot quietly soften a real failure into 'inconclusive'."""
    def _all_ruled(cand: Candidate, *a, **k):
        return _FakeDossier(Decision.KILL, "value_durability")

    cfg = load_config()
    disc, results = run_golden_set(None, None, cfg, golden_file, verbose=True,
                                   _vet_fn=_all_ruled)
    out = capsys.readouterr().out

    assert disc == pytest.approx(1.0)
    assert "INCONCLUSIVE" not in out
    assert all(r["deferred"] is False for r in results)

"""The golden score measures DECISION separation only — and must say so out loud.

THE DEFECT, found 2026-08-15 while reading a claude_cli run that scored 1.00.
`run_golden_set`'s docstring promised `correct = decision_match AND gate_match AND
surfaced`, while the code has always been `passed = decision_match` (HEAD's
golden.py:143).  On that very run four of nine cases KILLed on a check other than the
one the golden set labels — `Generic E-commerce Platform for SMBs` was labelled
`incumbency` and died on `value_durability`, `Illegal LinkedIn Scraping Hub` was
labelled `legality` and died on `distribution` — and all four still counted correct.

So a promotion decision could be taken on "the challenger matches the incumbent at
1.00" while the two brains were killing the same ideas for entirely different reasons.
The number is not wrong; the sentence attached to it was.  This file pins both halves:
the metric stays decision-only (changing it would silently re-score every historical
run), and every run prints the gate accuracy it is NOT counting.
"""
from __future__ import annotations

import json

import pytest

from prospector.config import load_config
from prospector.golden import run_golden_set
from prospector.models import Candidate, CheckResult, Decision, Source, Verdict


def _check(name: str) -> CheckResult:
    return CheckResult(
        check_name=name, verdict=Verdict.REFUTED, confidence=0.9,
        rationale="the passage says so", citations=["a" * 16],
        sources=[Source(source_id="a" * 16, url="https://example.com/x",
                        text="evidence", retrieved_by="fixture")])


class _Dossier:
    def __init__(self, decision: Decision, gate: str | None):
        self.decision = decision
        self.gate_fired = gate
        self.reason = "because the passage says so"
        self.checks = [_check(gate or "value_durability")]


@pytest.fixture
def golden_file(tmp_path):
    """Two KILL cases, each labelled with the gate we expect to fire."""
    p = tmp_path / "golden.json"
    p.write_text(json.dumps([
        {"idea": "Right Gate", "expected": "kill", "gate": "legality"},
        {"idea": "Wrong Gate", "expected": "kill", "gate": "incumbency"},
    ]), encoding="utf-8")
    return str(p)


def _vet_fn(cand: Candidate, *a, **k) -> _Dossier:
    # Both KILL — the decision is right both times. The second dies on the wrong check.
    if cand.title == "Right Gate":
        return _Dossier(Decision.KILL, "legality")
    return _Dossier(Decision.KILL, "value_durability")


def test_a_kill_on_the_wrong_gate_still_scores_correct(golden_file):
    """The metric is decision separation. Asserted, not assumed: if someone tightens it
    to include gate_match, every historical discrimination figure in
    store/golden_runs/ silently changes meaning, and the promotion bar
    (`--min-discrimination 0.78`, an incumbent's measured score) stops being comparable
    to the thing it was measured against."""
    cfg = load_config()
    disc, results = run_golden_set(None, None, cfg, golden_file, verbose=False,
                                   _vet_fn=_vet_fn)

    assert disc == pytest.approx(1.0), (
        f"both decisions were KILL as expected, so the score is 2/2; got {disc}")
    by_idea = {r["idea"]: r for r in results}
    assert by_idea["Wrong Gate"]["passed"] is True
    assert by_idea["Wrong Gate"]["gate_match"] is False, (
        "and the per-case record must still record that the gate was wrong")
    assert by_idea["Right Gate"]["gate_match"] is True


def test_the_run_prints_the_gate_accuracy_it_is_not_counting(golden_file, capsys):
    """The compensating control. A 100% score printed beside 50% gate accuracy cannot be
    mistaken for a brain that reasoned correctly twice."""
    cfg = load_config()
    run_golden_set(None, None, cfg, golden_file, verbose=True, _vet_fn=_vet_fn)
    out = capsys.readouterr().out

    assert "Gate accuracy: 1/2" in out, out
    assert "NOT part of the score" in out, (
        "the disclaimer is the point — without it the line reads as a second score")

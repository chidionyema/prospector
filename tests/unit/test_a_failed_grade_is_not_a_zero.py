"""The generative golden set must not average an outage in as a score of zero.

MEASURED 2026-08-15. `golden_gen.run_generative_golden` graded each case inside a bare
`except Exception` that set `alpha = 0.0`, then divided `total_alpha` by `len(cases)`. 0.0 is
also the lowest grade the Professor can legitimately award, so a grader that crashed and a
generator that produced nothing of value reduced to the identical number — in the one harness
whose entire job is deciding whether a second brain can be trusted. That is how the promotion
gate came to record that a model "answers without reasons" when its answers had been thrown
away upstream.

These tests pin the DISTINCTION, not the happy path: a run with one broken grade must not be
reportable as the same thing as a run with one zero grade.
"""
from __future__ import annotations

import json

import pytest

from prospector.errors import ProviderExhaustedError
from prospector.golden_gen import run_generative_golden


class _FakeCandidate:
    def __init__(self, title: str) -> None:
        self.title = title

    def to_dict(self) -> dict:
        return {"title": self.title}


class _Prof:
    """Professor that grades the first case and fails on every one after it."""

    def __init__(self, fail_with: Exception) -> None:
        self.fail_with = fail_with
        self.calls = 0

    def complete_json(self, system, user, temperature=0.0):
        self.calls += 1
        if self.calls == 1:
            return {"alpha_score": 4.0, "rationale": "found the wedge"}
        raise self.fail_with


@pytest.fixture()
def two_case_golden(tmp_path, monkeypatch):
    path = tmp_path / "generative_golden.json"
    path.write_text(json.dumps([
        {"signal": "signal one", "targets": ["t1"]},
        {"signal": "signal two", "targets": ["t2"]},
    ]), encoding="utf-8")
    monkeypatch.setattr("prospector.golden_gen.generate",
                        lambda op, cfg, signal_text, k: [_FakeCandidate("idea")])
    return str(path)


def test_a_broken_grade_is_excluded_from_the_mean_not_scored_zero(two_case_golden):
    prof = _Prof(RuntimeError("professor adapter blew up"))

    report = run_generative_golden(None, prof, None, golden_path=two_case_golden, k=1)

    # The old code reported (4.0 + 0.0) / 2 = 2.0 and nothing said a case had failed.
    assert report["overall_alpha"] != 2.0
    assert report["overall_alpha"] == 4.0        # the mean of what was ACTUALLY graded
    assert report["graded_n"] == 1
    assert report["failed_n"] == 1
    assert report["degraded"] is True

    graded, failed = report["cases"]
    assert graded["graded"] is True and graded["alpha_score"] == 4.0
    assert failed["graded"] is False
    assert failed["alpha_score"] is None          # never 0.0 — 0.0 is a real verdict
    assert "professor adapter blew up" in failed["rationale"]


def test_a_real_zero_grade_still_counts_as_a_zero(two_case_golden, monkeypatch):
    """The other side of the distinction: a genuine 0.0 must still lower the score."""
    class _ZeroProf:
        def complete_json(self, system, user, temperature=0.0):
            return {"alpha_score": 0.0, "rationale": "nothing of value here"}

    report = run_generative_golden(None, _ZeroProf(), None,
                                   golden_path=two_case_golden, k=1)

    assert report["overall_alpha"] == 0.0
    assert report["graded_n"] == 2
    assert report["failed_n"] == 0
    assert report["degraded"] is False
    assert all(c["graded"] is True for c in report["cases"])


def test_no_grade_at_all_reports_none_not_a_floor_score(two_case_golden):
    class _DeadProf:
        def complete_json(self, system, user, temperature=0.0):
            raise ValueError("unparseable grade")

    report = run_generative_golden(None, _DeadProf(), None,
                                   golden_path=two_case_golden, k=1)

    assert report["overall_alpha"] is None       # not 0.0: nothing was measured
    assert report["graded_n"] == 0
    assert report["degraded"] is True


def test_an_exhausted_professor_aborts_instead_of_reporting_a_number(two_case_golden):
    """A benched brain is not a grade. It must reach the caller as the failover signal."""
    prof = _Prof(ProviderExhaustedError("out of quota", provider="minimax"))

    with pytest.raises(ProviderExhaustedError):
        run_generative_golden(None, prof, None, golden_path=two_case_golden, k=1)

"""E6B's answer must be a property of the data, not of the grid or of a default.

E6 was carried as "blocked on live daemon ticks". It was not: the bar is ">=20% of
prescreen calls removed at no PASS loss", which is a statement about eventual
OUTCOME, and outcomes for 1,789 candidates are already on disk. E6B replays the
shipped scorer over them.

Two ways that replay can produce a confident wrong answer, both pinned here:

* **The grid decides the answer.** The first version swept thresholds in 0.02 steps.
  Scores pile up at 0.0 when passes are rare, so the smoke run dropped 89.50% at the
  very first rung — the resolution, not the data, chose the number. The sweep is now
  exact over the observed scores.
* **"Nothing is safe" reads as "safe but useless".** `best_safe` returns None, not
  0.0, when no threshold is safe. A caller that coerced that to a rate would report a
  0% drop for a prefilter that is unsafe at EVERY threshold — a very different fact.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
E6B_PATH = REPO / "tools" / "experiments" / "e6b_prefilter_pass_safety.py"


@pytest.fixture(scope="module")
def e6b():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("e6b_uut", E6B_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(score, decision):
    return {"score": score, "decision": decision}


# --------------------------------------------------------------------------- #
# the sweep must not be a grid
# --------------------------------------------------------------------------- #

def test_thresholds_are_the_observed_scores(e6b):
    scored = [_row(0.0, "kill"), _row(0.5, "pass"), _row(0.0, "kill"), _row(0.25, "defer")]
    ts = e6b.candidate_thresholds(scored)
    assert ts[:3] == [0.0, 0.25, 0.5]          # deduped and sorted
    assert ts[-1] > 0.5                        # one rung above the max, so "drop all" is reachable


def test_thresholds_ignore_abstentions(e6b):
    """An abstaining scorer returns None. None is not a threshold and must never be
    compared against one."""
    assert e6b.candidate_thresholds([_row(None, "pass"), _row(0.4, "kill")])[:1] == [0.4]


def test_no_scores_yields_no_thresholds(e6b):
    assert e6b.candidate_thresholds([_row(None, "pass")]) == []
    assert e6b.candidate_thresholds([]) == []


def test_every_threshold_is_reachable_including_full_drop(e6b):
    """Without the sentinel above the max, the highest observed score can never be
    dropped and the top of the curve is unreachable."""
    scored = [_row(0.1, "kill"), _row(0.9, "kill")]
    curve = e6b.sweep(scored)
    assert max(c["n_dropped"] for c in curve) == 2


# --------------------------------------------------------------------------- #
# the sweep's arithmetic
# --------------------------------------------------------------------------- #

def test_sweep_counts_drops_pass_loss_and_defer_loss(e6b):
    scored = [_row(0.1, "kill"), _row(0.2, "pass"), _row(0.3, "defer"), _row(0.4, "kill")]
    at = {round(c["threshold"], 4): c for c in e6b.sweep(scored)}
    assert at[0.1]["n_dropped"] == 0                       # strict <, so nothing drops at the min
    assert at[0.3]["n_dropped"] == 2
    assert at[0.3]["pass_dropped"] == 1
    assert at[0.3]["defer_dropped"] == 0
    assert at[0.3]["drop_rate"] == pytest.approx(0.5)
    assert at[0.3]["pass_loss_rate"] == pytest.approx(1.0)  # 1 of the 1 pass
    assert at[0.4]["defer_dropped"] == 1


def test_an_abstention_is_never_dropped(e6b):
    """Abstaining means the prefilter declined to rule. Counting it as a drop would
    credit the prefilter with a saving it never made."""
    scored = [_row(None, "pass"), _row(0.1, "kill")]
    curve = e6b.sweep(scored)
    assert all(c["n_dropped"] <= 1 for c in curve)
    assert all(c["pass_dropped"] == 0 for c in curve)


def test_drop_rate_is_over_the_whole_population(e6b):
    """The bar is a share of prescreen CALLS, so abstentions belong in the
    denominator — they still cost a call."""
    scored = [_row(None, "kill")] * 3 + [_row(0.1, "kill")]
    top = max(e6b.sweep(scored), key=lambda c: c["drop_rate"])
    assert top["drop_rate"] == pytest.approx(0.25)


# --------------------------------------------------------------------------- #
# "nothing is safe" is an answer, not a zero
# --------------------------------------------------------------------------- #

def test_best_safe_is_none_when_every_threshold_loses_a_pass(e6b):
    curve = [{"threshold": 0.1, "drop_rate": 0.5, "pass_dropped": 1, "defer_dropped": 0},
             {"threshold": 0.2, "drop_rate": 0.9, "pass_dropped": 3, "defer_dropped": 1}]
    assert e6b.best_safe(curve, allow_defer_loss=True) is None
    assert e6b.best_safe(curve, allow_defer_loss=False) is None


def test_best_safe_takes_the_largest_safe_drop(e6b):
    curve = [{"threshold": 0.1, "drop_rate": 0.10, "pass_dropped": 0, "defer_dropped": 0},
             {"threshold": 0.2, "drop_rate": 0.30, "pass_dropped": 0, "defer_dropped": 0},
             {"threshold": 0.3, "drop_rate": 0.90, "pass_dropped": 1, "defer_dropped": 0}]
    assert e6b.best_safe(curve, allow_defer_loss=False)["drop_rate"] == pytest.approx(0.30)


def test_defer_loss_is_a_separate_question(e6b):
    """A dropped defer is an unruled candidate, not a lost pass. The two bars must be
    reportable independently."""
    curve = [{"threshold": 0.2, "drop_rate": 0.4, "pass_dropped": 0, "defer_dropped": 2}]
    assert e6b.best_safe(curve, allow_defer_loss=True)["drop_rate"] == pytest.approx(0.4)
    assert e6b.best_safe(curve, allow_defer_loss=False) is None


def test_empty_curve_is_none(e6b):
    assert e6b.best_safe([], allow_defer_loss=True) is None

"""E18 must be able to tell a real effect from a confounded one.

The filed claim was that leading a query with our packaging vocabulary ("solo",
"fixed-fee", "done-for-you") costs us retrieval. The naive between-candidate contrast
says so emphatically — 2.37 sources vs 3.79, unverifiable 80.51% vs 61.27%, in the
same direction on every check. Acting on that would have been a blind edit: the
vocabulary is a property of the CANDIDATE, not of the query, so the two arms are two
populations of idea rather than two ways of searching.

An experiment that cannot distinguish those two worlds is worse than none, because it
launders a confound into a licence to change the query builder. So the tests below
build both worlds explicitly:

* a CONFOUNDED corpus, where each candidate sits wholly in one arm and the arms differ
  because the ideas differ — E18 must refuse to act; and
* a REAL-EFFECT corpus, where every candidate contributes to both arms and the
  wrapper-led checks genuinely retrieve worse — E18 must act.

If the harness returns the same verdict for both, it is measuring nothing. That is the
same trap E1's docstring names: an experiment whose null result and whose broken
result are the same output is not an experiment.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
E18_PATH = REPO / "tools" / "experiments" / "e18_query_vocabulary_confound.py"


@pytest.fixture(scope="module")
def e18():
    sys.path.insert(0, str(REPO / "tools" / "experiments"))
    spec = importlib.util.spec_from_file_location("e18_uut", E18_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(cid, check, wrapper, sources, unv):
    return {"candidate_id": cid, "check": check, "wrapper": wrapper,
            "n_sources": sources, "unverifiable": unv, "n_queries": 1}


# --------------------------------------------------------------------------- #
# what counts as the treatment
# --------------------------------------------------------------------------- #

def test_wrapper_detection_is_first_token_only(e18):
    """'leads with' is the behaviour under test. A domain-led query that merely
    mentions the vocabulary later is NOT in the treatment arm."""
    assert e18.leads_with_wrapper("solo operator dispute resolution") is True
    assert e18.leads_with_wrapper("Fixed-Fee conveyancing pricing") is True
    assert e18.leads_with_wrapper("conveyancing fixed-fee pricing") is False
    assert e18.leads_with_wrapper("dental practice solo") is False


def test_blank_queries_are_not_treatment(e18):
    assert e18.leads_with_wrapper("") is False
    assert e18.leads_with_wrapper("   ") is False
    assert e18.leads_with_wrapper(None) is False


# --------------------------------------------------------------------------- #
# the design diagnostic — the thing that made the naive number uninterpretable
# --------------------------------------------------------------------------- #

def test_design_detects_treatment_assigned_at_candidate_level(e18):
    """Each candidate wholly in one arm => nothing is paired, and the between-candidate
    contrast is comparing ideas."""
    rows = ([_row("a", "legality", 1, 1, 1), _row("a", "distribution", 1, 1, 1)]
            + [_row("b", "legality", 0, 5, 0), _row("b", "distribution", 0, 5, 0)])
    d = e18.design_diagnostic(rows)
    assert d["n_candidates"] == 2
    assert d["candidates_in_both_arms"] == 0
    assert d["share_in_both_arms"] == pytest.approx(0.0)


def test_design_detects_a_within_candidate_design(e18):
    rows = [_row("a", "legality", 1, 1, 1), _row("a", "distribution", 0, 5, 0)]
    d = e18.design_diagnostic(rows)
    assert d["candidates_in_both_arms"] == 1
    assert d["share_in_both_arms"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# the two worlds the harness must separate
# --------------------------------------------------------------------------- #

def _confounded_corpus():
    """Arms differ ONLY because the candidates differ. Every candidate is single-arm,
    so a correct paired estimate has nothing to pair and must not claim an effect."""
    rows = []
    for i in range(40):                       # hard ideas, all wrapper-led
        rows += [_row(f"hard{i}", "legality", 1, 1, 1),
                 _row(f"hard{i}", "distribution", 1, 1, 1)]
    for i in range(40):                       # easy ideas, all domain-led
        rows += [_row(f"easy{i}", "legality", 0, 6, 0),
                 _row(f"easy{i}", "distribution", 0, 6, 0)]
    return rows


def _real_effect_corpus(helpful: bool = False):
    """A genuine, IDENTIFIABLE within-candidate effect.

    Identifiable is the operative word. If the wrapper arm always fell on the same
    check, residualising on check_name would absorb the whole effect and report zero —
    correctly, because vocabulary and check would be perfectly collinear and nothing
    could tell them apart. So the arm ROTATES across checks: on half the candidates
    `legality` is wrapper-led, on the other half `distribution` is. The noise terms
    exist because a constant difference has zero variance, and a zero standard error
    yields no interval.
    """
    good, bad = (1, 0) if helpful else (0, 1)
    rows = []
    for i in range(40):
        w_check, d_check = (("legality", "distribution") if i % 2 == 0
                            else ("distribution", "legality"))
        w_src, d_src = ((6 + i % 2, 1 + i % 3) if helpful else (1 + i % 3, 6 + i % 2))
        rows += [_row(f"c{i}", w_check, 1, w_src, bad if i % 5 else good),
                 _row(f"c{i}", d_check, 0, d_src, good if i % 5 else bad)]
    return rows


def test_a_pure_confound_does_not_produce_an_act_verdict(e18):
    rows = _confounded_corpus()
    naive = e18.naive_contrast(rows)
    # the naive contrast is enormous and entirely spurious
    assert naive["mean_sources"]["wrapper"] == pytest.approx(1.0)
    assert naive["mean_sources"]["domain"] == pytest.approx(6.0)
    assert naive["unverifiable_rate"]["wrapper"] == pytest.approx(1.0)

    adjusted = e18.paired_adjusted(rows)
    assert adjusted["d_sources"]["n"] == 0          # nothing is pairable
    call, _ = e18.verdict(adjusted)
    assert call == "INSUFFICIENT"                   # never ACT


def test_a_real_within_candidate_effect_is_detected(e18):
    """The complement: the harness must not be a machine that always says no."""
    adjusted = e18.paired_adjusted(_real_effect_corpus())
    assert adjusted["d_sources"]["n"] == 40
    call, why = e18.verdict(adjusted)
    assert call == "ACT"
    assert "fewer sources" in why or "more unverifiable" in why


def test_the_two_worlds_do_not_produce_the_same_verdict(e18):
    """States the contract directly: an experiment whose broken and null outputs match
    is not an experiment."""
    confounded, _ = e18.verdict(e18.paired_adjusted(_confounded_corpus()))
    real, _ = e18.verdict(e18.paired_adjusted(_real_effect_corpus()))
    assert confounded != real


# --------------------------------------------------------------------------- #
# the adjustment itself
# --------------------------------------------------------------------------- #

def test_check_residualisation_removes_a_check_imbalance(e18):
    """Checks differ in base retrievability and the arms are not balanced across them.
    If the wrapper arm is simply over-represented on a hard check, the UNadjusted
    difference is that imbalance, not an effect."""
    # Every observation sits exactly at its own check's base level, so the true
    # within-candidate effect is zero. But the wrapper arm is drawn ONLY from the hard
    # check while the domain arm spans both, so the UNadjusted difference is a pure
    # artefact of that imbalance (-4), and only the residualisation removes it.
    rows = [
        _row("a", "hard", 1, 1, 1), _row("a", "hard", 0, 1, 1), _row("a", "easy", 0, 9, 0),
        _row("b", "hard", 1, 1, 1), _row("b", "hard", 0, 1, 1), _row("b", "easy", 0, 9, 0),
    ]
    adjusted = e18.paired_adjusted(rows)
    assert adjusted["d_sources"]["n"] == 2
    assert adjusted["d_sources"]["mean"] == pytest.approx(0.0, abs=1e-9)

    # the artefact the adjustment is removing is real and large
    unadjusted = [1 - (1 + 9) / 2, 1 - (1 + 9) / 2]
    assert sum(unadjusted) / len(unadjusted) == pytest.approx(-4.0)


def test_a_single_pair_yields_no_interval(e18):
    """One pair has no variance. Emitting a CI there would invent precision."""
    rows = [_row("a", "legality", 1, 1, 1), _row("a", "distribution", 0, 5, 0)]
    s = e18.paired_adjusted(rows)["d_sources"]
    assert s["n"] == 1
    assert s["ci95"] is None
    assert e18.verdict(e18.paired_adjusted(rows))[0] == "INSUFFICIENT"


def test_a_helpful_effect_is_not_reported_as_harm(e18):
    """The bar is directional: wrapper vocabulary retrieving BETTER is not a reason to
    edit the query builder in the harmful direction."""
    call, _ = e18.verdict(e18.paired_adjusted(_real_effect_corpus(helpful=True)))
    assert call == "DO_NOT_ACT"


def test_naive_prevalence_is_over_checks_that_issued_queries(e18):
    rows = [_row("a", "x", 1, 1, 1), _row("a", "y", 0, 1, 1),
            _row("b", "x", 0, 1, 1), _row("b", "y", 0, 1, 1)]
    assert e18.naive_contrast(rows)["wrapper_prevalence"] == pytest.approx(0.25)

"""The prose repair told the model not to make the change it was asking for.

Measured 2026-08-21 over the 273 model-written prose artifacts (`build_spec`, `gtm_plan`,
`ops_plan`) in dossiers written on or after 2026-08-16, the day `prose_target.json` landed
and `listing.human_register_repair` went on. Compared against the same target's own
pre-repair `ours_mean`, with `prose_measure.document_measures`, the instrument that built it:

    measure                n     pre    post   change   human p5-p95
    punct_hyphen_per_1k  273   31.84   16.45     -48%   0.69 - 7.05
    punct_comma_per_1k   273   61.30   48.87     -20%   13.27 - 49.11
    hedges_per_1k        273    3.51    3.69      +5%   5.67 - 23.05
    mattr                272    0.77    0.76      -2%   0.63 - 0.71

The two measures that are pure surface moved. The two that need the sentence to claim
something different did not. `repair_feedback` said why, in its own preamble: "this is about
how the sentences are built, never about what they say." Adding "appears" to a sentence IS
changing what it says, so a model obeying the preamble could never satisfy the hedge rule.

The hyphen rule had a second, independent defect. It named compound stacking --
"Front-Door Key-Safe Re-Siting" -- as the class. Over the 6,301 hyphenated tokens in that
same prose, Title-Case compounds are 47 of them, 0.7%. 83.4% are ordinary lowercase
compounds (`one-off`, `fixed-fee`, `self-employed`, `part-time`), and "write the words out"
turns those into spelling errors. There is no lookup-table fix either: 3,016 distinct tokens,
and the top 50 cover 19.3% of occurrences.

These tests fail if either instruction comes back.
"""
import pytest

from prospector import prose_target


def _feedback(measure, side, value, p5, p95):
    return prose_target.repair_feedback(
        [{"measure": measure, "side": side, "value": value, "p5": p5, "p95": p95}])


HEDGE_FINDING = ("hedges_per_1k", "below", 3.69, 5.6711, 23.0516)
HYPHEN_FINDING = ("punct_hyphen_per_1k", "above", 16.45, 0.694, 7.0547)


def test_the_preamble_no_longer_forbids_changing_what_the_draft_says():
    """The clause that made the hedge rule unsatisfiable is gone."""
    text = _feedback(*HEDGE_FINDING)
    assert "never about what they say" not in text


def test_a_hedge_finding_is_told_that_marking_uncertainty_is_permitted():
    """The rule asks for hedging, so the preamble must license it explicitly."""
    text = _feedback(*HEDGE_FINDING).lower()
    assert "marking uncertainty is not changing what the draft says" in text


def test_the_evidence_ban_survives():
    """Loosening the preamble must not license inventing or cutting evidence."""
    text = _feedback(*HEDGE_FINDING).lower()
    for phrase in ("figure", "date", "source", "named entity", "do not cut evidence"):
        assert phrase in text, phrase


@pytest.mark.parametrize("compound", ["one-off", "self-employed", "follow-up", "part-time"])
def test_the_hyphen_rule_protects_fixed_compounds(compound):
    """Splitting these is a spelling error, and the rule used to ask for it."""
    assert compound in prose_target.PROMPT_RULE["punct_hyphen_per_1k"]["above"]


def test_the_hyphen_rule_does_not_ask_for_the_words_to_be_written_out():
    """0.7% of our hyphens are the class that instruction was aimed at."""
    rule = prose_target.PROMPT_RULE["punct_hyphen_per_1k"]["above"]
    assert "Write compounds out as words" not in rule
    assert "Front-Door Key-Safe Re-Siting" not in rule


def test_the_hyphen_rule_names_the_class_that_was_actually_measured():
    """83.4% are lowercase compounds stacked in front of a noun."""
    rule = prose_target.PROMPT_RULE["punct_hyphen_per_1k"]["above"].lower()
    assert "in front of a noun" in rule


def test_both_rules_still_reach_a_draft_that_breaches_both():
    """The wiring, not the wording: a two-measure draft gets both rules."""
    text = prose_target.repair_feedback([
        dict(zip(("measure", "side", "value", "p5", "p95"), HEDGE_FINDING)),
        dict(zip(("measure", "side", "value", "p5", "p95"), HYPHEN_FINDING)),
    ])
    assert "unsure about" in text
    assert "in front of a noun" in text
    assert text.count("\n  - ") == 2


def test_the_human_facing_advice_names_the_same_class_as_the_model_rule():
    """`ADVICE` is what a person reads in the console. It carried the same 0.7% error."""
    advice = prose_target.ADVICE["punct_hyphen_per_1k"]["above"]
    assert "Front-Door Key-Safe Re-Siting" not in advice
    assert "Write the words out" not in advice
    assert "in front of nouns" in advice
    assert "one-off" in advice

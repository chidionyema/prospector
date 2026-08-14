"""Guards for the post-verdict figure trace (programme doc §33).

Two jobs. First, pin the matcher's semantics — leniency in the right direction, digit boundaries that
cannot launder a fabricated number, and the off-ladder price case that is a real defect rather than a
self-reference. Second, pin this module to `tools/experiments/q4c_claim_level_tracing.py`'s
independent implementation, which is the instrument that MEASURES whether the fix works. The
duplication is deliberate (a probe importing the code under test agrees with its bugs); this test is
what stops the two drifting apart while staying independent at measurement time.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from prospector.figure_check import (
    DEFAULT_TRUNCATE,
    contains,
    figures,
    price_rung_forms,
    trace_figures,
)
from prospector.models import CheckResult, Verdict

REPO = pathlib.Path(__file__).resolve().parents[2]


class _Src:
    """Minimal Source-like: trace_figures only reads `.source_id` and `.text`."""

    def __init__(self, source_id: str, text: str) -> None:
        self.source_id = source_id
        self.text = text


# ---------------------------------------------------------------------------
# figures(): a figure is a number carrying a CLAIM
# ---------------------------------------------------------------------------

def test_figures_extracts_units_and_magnitudes():
    got = figures("£1,299 up front, 42% margin, 3.5x return, 12 million users")
    assert got == ["1299", "42", "3.5", "12"]


def test_figures_skips_years_and_prose_counting():
    # 2024 is a date; "3 suppliers" is prose. Neither is evidence, and counting them would bury the
    # real signal in noise — the reason the probe's bare-number branch has a floor at all.
    assert figures("In 2024 we spoke to 3 suppliers about 7 options") == []


def test_figures_keeps_large_bare_numbers():
    # No unit, but nobody writes 53601 casually. This is the shape of the worst live row found:
    # `08dbe23f7be7af97 legality/supported figures=['53601']`.
    assert figures("Regulation 53601 applies") == ["53601"]


# ---------------------------------------------------------------------------
# contains(): digit boundaries are the anti-laundering rail
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("haystack,num,expected", [
    ("the fee is 149 pounds", "49", False),      # 49 must not match inside 149
    ("the fee is 1.49", "49", False),            # nor as the fraction of another number
    ("the fee is 49 pounds", "49", True),
    ("the fee is 49.99", "49", True),            # LENIENT on purpose — see the test below
    ("margin was 92.0%", "92", True),            # trailing zeros are the same number
    ("priced at 4.50", "4.5", True),
    ("revenue of 1,299,000", "1299000", True),   # commas in the haystack ignored
])
def test_contains_digit_boundaries(haystack, num, expected):
    assert contains(haystack, num) is expected


def test_leniency_runs_OPPOSITE_to_appears_in_and_that_is_correct():
    """`contains` and `price_comparables._appears_in` disagree on "49" in "49.99" BY DESIGN.

    They answer different questions and both are conservative in their own direction:

    - `_appears_in` decides whether to ACCEPT a price anchor as evidence. Strict, because a
      near-miss would launder a fabricated number into a "cited" one — worse than no anchor.
    - `contains` decides whether to ACCUSE our own output of inventing a number. Lenient, because
      every untraceable count must be a LOWER bound. A passage reading 49.99 plausibly grounds a
      rationale saying 49; calling that fabrication would inflate the accusation.

    Encoded as a test because the two look like the same function and are not, and "unify them"
    is the obvious wrong refactor.
    """
    from prospector.price_comparables import _appears_in
    assert _appears_in(49, "the fee is 49.99") is False
    assert contains("the fee is 49.99", "49") is True


# ---------------------------------------------------------------------------
# trace_figures(): the four buckets
# ---------------------------------------------------------------------------

def test_traceable_when_the_figure_is_in_a_cited_passage():
    srcs = [_Src("a", "The average annual fee is 42% of turnover.")]
    t = trace_figures("Buyers already pay 42% of turnover.", srcs, ["a"])
    assert t.traceable == ["42"] and t.untraceable == [] and t.clean


def test_other_passage_when_the_number_is_grounded_but_miscited():
    # A hygiene defect, NOT a grounding defect: the number was retrieved, the citation is wrong.
    # Conflating the two would overstate the accusation.
    srcs = [_Src("a", "nothing numeric here"), _Src("b", "the levy is 42%")]
    t = trace_figures("The levy is 42%.", srcs, ["a"])
    assert t.other_passage == ["42"] and t.untraceable == [] and t.clean


def test_untraceable_when_no_passage_contains_it():
    # Shaped after the real live row `08b22037fc2afc07 payer_solvency/refuted figures=['320']`.
    srcs = [_Src("a", "Carers report significant unmet need.")]
    t = trace_figures("Around £320 per carer per year qualifies.", srcs, ["a"])
    assert t.untraceable == ["320"] and not t.clean


def test_candidate_self_reference_is_not_an_accusation():
    srcs = [_Src("a", "no numbers")]
    t = trace_figures("Our 12% uplift.", srcs, ["a"], self_text="a 12% uplift target")
    assert t.self_ref == ["12"] and t.untraceable == []


def test_a_bare_number_under_the_floor_is_invisible_to_the_trace():
    """The bare-number floor is a real blind spot, recorded so nobody reads 0 as "clean".

    Without a unit, only numbers >= 1000 count, so an invented "320 carers" or "12 months" is NOT
    flagged while "£320" and "12%" are. That is the lenient direction again — bare small integers
    are overwhelmingly prose ("3 suppliers", "two of the passages") and flagging them would drown
    the signal. The consequence to remember: every untraceable count is a LOWER BOUND, twice over.
    """
    srcs = [_Src("a", "no numbers here")]
    assert trace_figures("Around 320 carers qualify.", srcs, ["a"]).untraceable == []
    assert trace_figures("Around £320 qualifies.", srcs, ["a"]).untraceable == ["320"]


# ---------------------------------------------------------------------------
# The off-ladder price: the measured live defect, and the one that must NOT be excused
# ---------------------------------------------------------------------------

def test_declared_rung_is_self_reference_in_pounds_and_pence():
    rungs = price_rung_forms([1999, 2999, 4999])
    srcs = [_Src("a", "no numbers")]
    for asserted in ("a £49.99 pack", "a 4999 pence pack", "a £19.99 pack"):
        t = trace_figures(asserted, srcs, ["a"], price_rungs=rungs)
        assert t.untraceable == [], asserted
        assert t.self_ref, asserted


def test_off_ladder_price_stays_untraceable():
    """£49 is NOT a rung — £49.99 is. `payer_solvency` asserted "£49" on four live packs.

    A check reasoning about a price we do not charge is a real defect. Laundering it into
    `self_ref` because it merely LOOKS like our pricing is how that bug would have stayed invisible.
    """
    rungs = price_rung_forms([1999, 2999, 4999])
    srcs = [_Src("a", "no numbers")]
    t = trace_figures("so a £49 audit is safely within budget", srcs, ["a"], price_rungs=rungs)
    assert t.untraceable == ["49"] and t.self_ref == []


# ---------------------------------------------------------------------------
# Truncation: trace against what the model SAW, not what we stored
# ---------------------------------------------------------------------------

def test_figure_beyond_the_prompt_budget_is_untraceable():
    """`verify.py` builds the prompt as `s.text[:VERDICT_PASSAGE_TRUNCATE]`.

    Crediting the model with evidence past that cut would let a fabricated number pass because the
    stored passage happens to contain it further down. The probe measured `truncated = 0.0%`, which
    is only a meaningful validity check if this boundary is enforced.
    """
    tail = "x" * DEFAULT_TRUNCATE + " the figure is 42%"
    srcs = [_Src("a", tail)]
    assert trace_figures("It is 42%.", srcs, ["a"]).untraceable == ["42"]
    assert trace_figures("It is 42%.", srcs, ["a"], truncate=len(tail)).traceable == ["42"]


# ---------------------------------------------------------------------------
# Doctrine: the flag is observability. It must reach the dossier and change nothing else.
# ---------------------------------------------------------------------------

def test_checkresult_defaults_to_None_not_empty_and_serialises_for_the_audit_trail():
    """`None` (nobody looked) and `[]` (the trace ran and found nothing) are different claims.

    Defaulting to `[]` would make every dossier written before the trace existed read as
    figure-clean — see `human_review.is_traced` and `models.py:270`.
    """
    r = CheckResult(check_name="legality", verdict=Verdict.SUPPORTED, confidence=0.7,
                    rationale="ok")
    assert r.untraceable_figures is None
    r2 = CheckResult(check_name="legality", verdict=Verdict.SUPPORTED, confidence=0.7,
                     rationale="ok", untraceable_figures=["53601"])
    # Must land in the dossier JSON, or the listing fence and the audit tool have nothing to read.
    assert r2.to_dict()["untraceable_figures"] == ["53601"]
    # And it must not have touched the ruling: an absent number is OUR bug, not evidence.
    assert r2.verdict is Verdict.SUPPORTED and r2.confidence == 0.7


# ---------------------------------------------------------------------------
# Equivalence with the independent probe
# ---------------------------------------------------------------------------

def _load_probe():
    path = REPO / "tools" / "experiments" / "q4c_claim_level_tracing.py"
    if not path.exists():
        pytest.skip("probe not present in this checkout")
    spec = importlib.util.spec_from_file_location("_q4c_probe", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_q4c_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


_CORPUS = [
    "Buyers already pay £1,299 a year, a 42% premium on the 3.5x baseline.",
    "In 2024, 3 suppliers quoted 12 million units at 49.99 each.",
    "Regulation 53601 applies; penalties reach 10127.1 dollars.",
    "so a £49 audit is safely within budget for a 320 carer caseload",
    "Growth of 1.99 per cent against a 21,400 unit market.",
    "no numbers at all in this sentence",
]


def test_verdict_for_records_untraceable_figures_without_touching_the_ruling():
    """The wiring, not the matcher — a green module test says nothing about whether verify.py calls it.

    Also pins the doctrine in the place it can regress: the flag is recorded and the SUPPORTED
    ruling survives untouched. If a later change demotes here, this test fails and the reason is in
    `CheckResult.untraceable_figures` — our own extraction bug must not kill a sound idea.
    """
    from prospector.models import Candidate, Source
    from prospector.operator import MockOperator
    from prospector.verify import verdict_for

    src = Source(source_id="s1", url="https://example.org/carers",
                 text="Carers report significant unmet need for respite provision.")
    # A second, independent publisher — no digits, so it cannot change what the figure trace
    # finds. Required since 2026-08-14: the corroboration floor demotes a `supported` ruling
    # cited entirely to one registrable domain (`admissibility.corroboration_reason`), and
    # this test is about the FIGURE trace, which must be exercised on a surviving ruling.
    src2 = Source(source_id="s2", url="https://carerstrust.example.net/respite",
                  text="Local authorities fund respite placements for unpaid carers.")
    cand = Candidate(title="Respite matcher", one_liner="Match carers to respite",
                     hypothesis="Carers cannot find respite", who_pays="Local authorities")
    op = MockOperator(router=lambda system, user: {
        "verdict": "supported", "confidence": 0.9,
        "rationale": "Around £320 per carer per year is available, and unmet need is significant.",
        "citations": ["s1", "s2"]})

    r = verdict_for(op, cand, "payer_solvency", [src, src2])

    assert r.untraceable_figures == ["320"], "the trace block in verdict_for did not fire"
    assert r.verdict is Verdict.SUPPORTED, "an untraceable figure must NOT demote the ruling"
    assert r.confidence > 0.0, "nor zero the confidence"


def test_matcher_matches_the_independent_probe():
    """The probe is the instrument; this module is the fix. They must agree, or one is wrong.

    They are separate implementations ON PURPOSE — a probe that imported the code under test would
    ratify its bugs. This test is the substitute for that coupling.
    """
    probe = _load_probe()
    for text in _CORPUS:
        assert figures(text) == probe.figures(text), text
    for text in _CORPUS:
        for num in figures(text):
            assert contains(text, num) == probe.contains(text, num), (text, num)
    # And the boundary cases the buckets turn on.
    for haystack, num in [("149", "49"), ("49.99", "49"), ("92.0%", "92"), ("1,299,000", "1299000")]:
        assert contains(haystack, num) == probe.contains(haystack, num), (haystack, num)

"""The engine-grade strip, pinned to the renderer it has to agree with.

`render_markdown(..., include_our_grade=False)` keeps our scoresheet out of every pack
generated from 2026-08-15 onward. It cannot reach the 61 packs already on the shelf: their
`index.html` and `Complete_Pack.pdf` are RENDERED, so nothing can be edited in place, and
they are re-rendered from their own pre-conversion `.md` — markdown written before the fix
existed. `strip_our_grade_markdown` is that same removal expressed on the shipped document.

Two functions doing one job is a drift risk, so the load-bearing test here is the PAIRING
test: strip the `include_our_grade=True` render and you must get the `include_our_grade=False`
render, character for character. Measured 2026-08-16 over all 75 stored PASS dossiers: 75
matched, 0 mismatched, 0 no-ops.
"""
import pytest

from prospector.models import (
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    ScoreResult,
    Source,
    Verdict,
)
from prospector.dossier import render_markdown, strip_our_grade_markdown

SCORED = """\
# Every check, in full

Some prose about the market.

---
## How it scored

**Overall: 3.6500** (each line is rated out of 5, then weighted)

| What we rated | Score | Why |
|---------------|------:|-----|
| How badly it hurts | 4/5 | Councils are already paying for this by hand. |
| How provable the money is | 3/5 | Two cited invoices. |

---
## Why this passed

Survived all gates; composite 3.6500; 5 grounded-supported check(s) (moat grounded: 1).

---
## Every source we used

- <https://example.gov.uk/a>
"""


def test_the_scoresheet_and_the_composite_both_go():
    out = strip_our_grade_markdown(SCORED)
    assert out is not None
    assert "How it scored" not in out
    assert "3.6500" not in out
    assert "composite" not in out.lower()
    # and the sections either side are untouched
    assert "## Why this passed" in out
    assert "Survived all gates; 5 grounded-supported check(s) (moat grounded: 1)." in out
    assert "## Every source we used" in out
    assert "https://example.gov.uk/a" in out


def test_a_clean_report_comes_back_none():
    """The None contract `patched_md` relies on, and the idempotency it buys: running the
    backfill twice must not rewrite a pack it already corrected."""
    once = strip_our_grade_markdown(SCORED)
    assert strip_our_grade_markdown(once) is None
    assert strip_our_grade_markdown("# A report with no grade in it\n\nProse.\n") is None


def test_the_signage_pack_keeps_its_spec():
    """`_COMPOSITE_CLAUSE` is `\\bcomposite\\s+\\d`, which a pack about signage matches in
    good faith. The scrub is scoped to the pass-reason line for exactly this reason: a
    backfill that silently edits a buyer's spec sheet is a worse defect than the leak it
    was sent to fix. This string is the shape that produced the false positives when the
    engine-leak token list was first drafted (`check_engine_leak`, 2026-08-15)."""
    doc = SCORED.replace("Some prose about the market.",
                         "Panels are 3mm aluminium composite 3050 x 1500, cut to size.")
    out = strip_our_grade_markdown(doc)
    assert out is not None
    assert "aluminium composite 3050 x 1500" in out


def test_a_report_with_only_the_composite_clause_is_still_stripped():
    """A KILL-shaped or hand-edited report may carry the reason line without the table.
    Anchoring the strip on the table would leave the figure the founder actually quoted."""
    doc = "## Why this passed\n\nSurvived all gates; composite 2.9500; 8 checks.\n"
    out = strip_our_grade_markdown(doc)
    assert out == "## Why this passed\n\nSurvived all gates; 8 checks.\n"


# ---------------------------------------------------------------------------
# The pairing test — the one that stops the two implementations drifting
# ---------------------------------------------------------------------------

#: The shapes the pairing has to hold over, built here rather than read off this disk.
#:
#: This test globbed the operator's own PASS dossiers until 2026-08-16, and CI refused it:
#: `tests/test_suite_is_machine_independent.py::test_no_test_reads_the_operators_own_store`
#: forbids reading a gitignored path — 1,153 dossiers on the author's Mac, none in any
#: clone. Its `pytest.skip` on an empty store did not save it, because that guard is static:
#: it reads the source line, so the test would have SKIPPED in CI forever and pinned nothing
#: anyway. Built dossiers cost the property nothing and are the only version that runs where
#: it matters.
#:
#: One case per SHAPE the strip has to handle, each drawn from a real stored reason line:
#: the number mid-sentence, the number opening the sentence, and the record with no score at
#: all — the third being the no-op case, where the two renders are already identical.
_PAIRING_CASES = {
    "composite mid-sentence": dict(
        decision=Decision.PASS,
        reason="Survived all gates; composite 3.6500; 5 grounded-supported check(s) "
               "(moat grounded: 2).",
        composite=3.6500),
    "composite opens the sentence": dict(
        decision=Decision.KILL,
        reason="Composite 2.9500 cleared the bar but adversarial review refused it.",
        composite=2.9500),
    "no score at all": dict(
        decision=Decision.PASS,
        reason="Survived all gates; 8 grounded-supported check(s).",
        composite=None),
}


def _dossier(*, decision, reason, composite):
    checks = [CheckResult(
        check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.7,
        rationale="Fleets file the reclaim by hand.", citations=["s1"],
        sources=[Source(source_id="s1", url="https://www.gov.uk/x", text="p")],
    )]
    score = None if composite is None else ScoreResult(
        scores={"pain_acuity": 4, "value_durability": 3},
        justification={"pain_acuity": "It hurts weekly."},
        composite=composite)
    return Dossier(
        candidate=Candidate(title="A thing", one_liner="It does a thing."),
        checks=checks, decision=decision, reason=reason, score=score,
        created_at="2026-08-01T00:00:00+00:00",
    )


@pytest.mark.parametrize("name", sorted(_PAIRING_CASES))
def test_strip_matches_what_the_renderer_omits(name):
    """Strip the graded render and you must get the ungraded one, character for character.

    Two functions do one job — the renderer omits our scoresheet on everything generated
    from 2026-08-15, and `strip_our_grade_markdown` removes it from the 61 packs already
    rendered — so the only thing stopping them drifting is this equality."""
    d = _dossier(**_PAIRING_CASES[name])
    with_grade = render_markdown(d, include_our_grade=True)
    without = render_markdown(d, include_our_grade=False)
    # None is the documented "nothing to strip", not a failure: it is what tells `patched_md`
    # an already-clean pack must not be rewritten twice. The claim is about the RESULT, so a
    # no-op has to be read as the document unchanged.
    assert (strip_our_grade_markdown(with_grade) or with_grade) == without


def test_at_least_one_case_actually_has_something_to_strip():
    """The pairing above passes trivially where the two renders are already identical. A
    suite of only no-ops is green and pins nothing, so one case must do real work."""
    stripped = [n for n in _PAIRING_CASES
                if render_markdown(_dossier(**_PAIRING_CASES[n]), include_our_grade=True)
                != render_markdown(_dossier(**_PAIRING_CASES[n]), include_our_grade=False)]
    assert stripped, "every pairing case is a no-op; the equality proves nothing"

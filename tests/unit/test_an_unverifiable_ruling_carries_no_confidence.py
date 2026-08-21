"""`confidence` measures GROUNDING, so an unverifiable ruling scores 0.0.

`verify._calc_confidence` is `citation_score + diversity_score + relevance_score`
(`verify.py:91-199`). It has no verdict term, so it measures how much evidence RETRIEVAL
returned rather than how well the claim was established. For `supported` and `refuted` those
two track together. For `unverifiable` they invert: a check that fetched four diverse,
on-topic passages and established nothing outscored one that fetched two and proved its claim.

MEASURED over 14,006 checks in 2,806 dossiers (`tools/experiments/e19_confidence_gap.py`):

    verdict            n   mean conf   median
    unverifiable   9,965      0.5627    0.700
    supported      3,079      0.5695    0.600
    refuted          662      0.5418    0.580

7,304 of the 9,965 unverifiable checks (73.3%) scored >= 0.5, and the MEDIAN unverifiable
check was more confident than the median supported one. The field did not separate ruled from
unruled at all (gap +0.0019) while `kill_filter.py:5` documents it as "grounding confidence"
and gates a hard kill on it. W0.2's standing receipt measured the same inversion at -0.0405
over a narrower window and nothing in the engine changed.

The file's two other unverifiable exits (`verify.py:857`, `:898`) already wrote 0.0, so before
this guard the retrieval-failure paths and the ruled path disagreed about what an unverifiable
check is worth.
"""
from __future__ import annotations

from prospector.config import Admissibility, Config
from prospector.models import Candidate, Source, Verdict
from prospector.operator import MockOperator
from prospector.verify import verdict_for

# A government URL: admissibility's low tiers and the corroboration floor both exempt it, so
# nothing but the property under test can move the confidence.
GOOD_URL = "https://www.legislation.gov.uk/ukpga/2010/15"


def _ruling(verdict: str, citations=("s1",)):
    cfg = Config(admissibility=Admissibility(policy="P1_check_aware"))
    cand = Candidate(title="X", one_liner="y", hypothesis="z", who_pays="w")
    sources = [
        Source(source_id="s1", url=GOOD_URL,
               text="The Equality Act 2010 legally protects people from discrimination."),
        Source(source_id="s2", url="https://www.gov.uk/guidance/equality-act",
               text="Guidance on the Equality Act 2010 and what it requires of employers."),
    ]
    op = MockOperator(router=lambda s, u: {
        "verdict": verdict, "citations": list(citations),
        "rationale": "None of the passages establish the rate for this segment."})
    return verdict_for(op, cand, "legality", sources, cfg)


def test_an_unverifiable_ruling_scores_zero_confidence():
    """The guard. Fails before it: this ruling cites a real, diverse, on-topic source, so
    `_calc_confidence` scored it exactly as if the claim had been established."""
    res = _ruling("unverifiable", citations=("s1", "s2"))
    assert res.verdict == Verdict.UNVERIFIABLE
    assert res.confidence == 0.0


def test_non_vacuity_the_same_evidence_still_scores_when_the_claim_is_established():
    """Without this the test above passes on a harness that produces 0.0 for every verdict."""
    res = _ruling("supported", citations=("s1", "s2"))
    assert res.verdict == Verdict.SUPPORTED
    assert res.confidence > 0.0, "the identical sources and citations must still score"


def test_the_source_or_die_downgrade_lands_at_zero_too():
    """`supported` with no citation is downgraded to unverifiable at `verify.py:614-617`,
    BEFORE `_calc_confidence` runs — so it kept the diversity and relevance terms and shipped
    a demoted ruling wearing a grounded score."""
    res = _ruling("supported", citations=())
    assert res.verdict == Verdict.UNVERIFIABLE
    assert res.confidence == 0.0


def test_an_unverifiable_ruling_is_a_finding_not_an_outage():
    """`retrieval_failed=True` would turn this into a DEFER (`verify.py:693`). The evidence
    was fetched and judged; scoring it 0.0 is a statement about grounding, not about uptime."""
    res = _ruling("unverifiable", citations=("s1", "s2"))
    assert getattr(res, "retrieval_failed", False) is False
    assert getattr(res, "degraded", False) is False


def test_a_refuted_ruling_keeps_its_confidence_because_it_gates_the_hard_kill():
    """`kill_filter.py:51` hard-kills only when confidence clears `confidence_floor`. Zeroing
    a killing verdict would silently disarm that gate."""
    res = _ruling("refuted", citations=("s1", "s2"))
    assert res.verdict == Verdict.REFUTED
    assert res.confidence > 0.0

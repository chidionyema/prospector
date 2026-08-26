"""E-105's classifier decides whether a check needed a brain at all.

Every test here pins a way the rule could claim a saving it has not earned. The expensive
mistake is a FALSE POSITIVE: a rule that fires on a check the brain could have ruled turns a
cost saving into a wrong verdict, and it would show up as a quality regression nobody traced
back to a cost change.
"""

from __future__ import annotations

from tools.experiments.e105_unverifiable_prefilter import classify


def _check(sources, queries):
    return {"sources": sources, "queries": queries, "citations": []}


def test_no_source_at_all_is_catchable():
    assert classify(_check([], ["what does a UK dentist pay for scheduling software"]), {}) == (
        "no_source_retrieved"
    )


def test_sources_present_but_textless_is_catchable():
    check = _check([{"url": "https://example.com"}], ["dentist scheduling software price"])
    assert classify(check, {}) == "sources_carry_no_text"


def test_zero_overlap_is_catchable():
    check = _check(
        [{"url": "https://example.com", "text": "Volcanic activity in Iceland during winter."}],
        ["dentist scheduling software pricing"],
    )
    assert classify(check, {}) == "zero_overlap"


def test_topical_overlap_is_NOT_catchable():
    """The rule must keep its hands off anything a brain could plausibly rule on.

    This is the false-positive guard. The passage does not answer the query, but it is about
    the same subject, so only a brain can say whether it supports the claim.
    """
    check = _check(
        [
            {
                "url": "https://e.com",
                "text": "Dentist practices increasingly adopt scheduling tools.",
            }
        ],
        ["dentist scheduling software pricing"],
    )
    assert classify(check, {}) == "not_decidable"


def test_a_shared_number_alone_blocks_the_rule():
    """Numbers carry meaning that the stopword-stripped token set throws away."""
    check = _check(
        [{"url": "https://e.com", "text": "The figure reached 4,568 last year."}],
        ["how many 4,568"],
    )
    assert classify(check, {}) == "not_decidable"


def test_stopwords_alone_are_not_overlap():
    """A rule that counted 'the' as evidence would never fire, and would report a real zero."""
    check = _check(
        [{"url": "https://e.com", "text": "The and of for to in on is are was."}],
        ["the dentist and the software"],
    )
    assert classify(check, {}) == "zero_overlap"


def test_a_check_with_no_queries_is_never_claimed_as_a_saving():
    """Without queries there is no statement of what was sought, so the rule cannot judge.

    It must abstain rather than guess, otherwise a missing field reads as a free saving.
    """
    check = _check([{"url": "https://e.com", "text": "Some retrieved text about dentists."}], [])
    assert classify(check, {}) == "not_decidable_no_queries"

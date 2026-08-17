"""The pain check must search for a SIZE, and the query must actually be issued.

The pack page prints "how big it is" (founder, 2026-08-16, marked mandatory), and
`prompts/content_gen.md` may only put a figure there if a verified claim already states one.
Nothing in the engine ever searched for a size, so the field would ship empty on almost every
pack: measured over 245 live/deferred dossiers, an explicit market-size phrase appeared in 6,
any countable population figure in 21.

The trap this file exists to catch is not the wording. It is that `_templated_queries` emits
`disconfirm[0]` and `confirm[0]` and nothing else, so adding a size query as a SECOND confirm
template is inert -- it looks like a fix, ships, and never runs a search. These tests fail if
the size query is ever demoted out of slot 0.
"""
from __future__ import annotations

from prospector.models import Candidate
from prospector.verify import _CONFIRM_TEMPLATES, _templated_queries


def _cand() -> Candidate:
    return Candidate(
        candidate_id="t0",
        title="Compliance workbook for independent care homes",
        one_liner="A workbook that gets a small care home through its CQC inspection.",
        market="uk",
    )


def test_the_pain_check_asks_how_many_are_affected() -> None:
    assert _CONFIRM_TEMPLATES["pain_reality"] == ["{q} how many affected statistics survey evidence"]


def test_the_size_query_is_in_the_slot_that_is_actually_searched() -> None:
    # Slot 0 is the only confirm slot `_templated_queries` reads. A size query anywhere else
    # is never issued, so this assertion is the whole point of the change.
    assert "how many affected" in _CONFIRM_TEMPLATES["pain_reality"][0]


def test_a_pain_reality_run_issues_the_size_query() -> None:
    queries = _templated_queries(_cand(), "pain_reality", n=2)
    assert any("how many affected" in q for q in queries), queries


def test_the_pain_check_still_looks_for_the_disconfirming_evidence_first() -> None:
    # Kill-fast is unchanged: the negative query still leads, so a candidate with no real
    # problem still dies on the cheapest gate before anything is spent on sizing it.
    queries = _templated_queries(_cand(), "pain_reality", n=2)
    assert "not a real problem" in queries[0], queries

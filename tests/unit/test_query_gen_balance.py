"""Test that query_gen prompt produces balanced queries (spec: balanced-query-gen.md).

The old prompt generated ONLY disconfirming queries, creating a structural bias 
toward unverifiable (92.9% in production). The fix generates 1 confirmation + 
1 refutation query per check so the verdict model has evidence for both outcomes.
"""
from __future__ import annotations

from prospector.prompts import render


def test_query_gen_prompt_is_balanced_not_disconfirming_only():
    """The query_gen prompt must instruct for BOTH confirming AND refuting queries.
    
    OLD (fails this): "EXPOSE a business idea as dead ... DISCONFIRMING evidence"
    NEW (passes this): "confirmation query ... refutation query"
    """
    system, user = render(
        "query_gen",
        candidate_json='{"title":"Test","hypothesis":"test"}',
        check_name="pain_reality",
        check_question="Real, acute problem?",
    )
    combined = (system + " " + user).lower()

    # Reject: prompt that ONLY asks for disconfirming/dead-exposing queries
    # (the old prompt's signature phrases)
    assert "expose" not in system.lower(), (
        "Prompt still says 'EXPOSE a business idea as dead' — "
        "must use balanced language"
    )
    assert "disconfirming" not in system.lower(), (
        "Prompt still says 'DISCONFIRMING evidence' — "
        "must instruct for both confirmation and refutation"
    )

    # Require: prompt instructs for confirmation/supporting queries too
    has_confirm = any(w in combined for w in ("confirmation", "confirming", "supporting"))
    # At minimum, the prompt must not be disconfirming-only (already checked above).
    # It should instruct for confirmation or evidence-for queries.
    assert has_confirm, (
        "Prompt must instruct to search for confirming/supporting evidence, "
        "not only disconfirming. Combined text: " + combined[:300]
    )


def test_query_gen_prompt_asks_for_both_kinds_of_query():
    """The prompt should explicitly ask for 2 queries: one to confirm, one to refute."""
    system, user = render(
        "query_gen",
        candidate_json='{"title":"Test","hypothesis":"test"}',
        check_name="value_durability",
        check_question="Is the value real and durable?",
    )
    combined = (system + " " + user).lower()

    # The prompt should mention both directions explicitly
    assert "confirm" in combined or "support" in combined or "true" in combined, (
        "Prompt must instruct to search for confirming/true evidence"
    )
    assert "refut" in combined or "false" in combined or "against" in combined, (
        "Prompt must instruct to search for refuting/false evidence"
    )

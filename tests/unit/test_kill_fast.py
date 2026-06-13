"""Kill-fast short-circuit test (Part 4).

Proves that verify() stops after the second check (value_durability) when it
fires a hard fail, rather than running all six checks.

CHECKS dict order (models.py): pain_reality, value_durability, incumbency, ...
  - Check 1: pain_reality — must PASS (supported + valid citation)
  - Check 2: value_durability — fires KILL (refuted + valid citation)

Because is_hard_fail() is called inside verify() after each run_check(), and
value_durability=refuted is in its killing set, verify() should return with
len(checks)==2 and gate=="value_durability".

Citation mechanics:
  - verdict_for downgrades 'supported' with no valid citation to 'unverifiable'.
  - 'refuted' with no valid citation is still 'refuted' (no source-or-die penalty).
  - The router receives user text that contains "[source_id]" tags for each passage.
    We parse the first [id] from the user text and cite it so 'supported' verdicts
    survive the citation check.
"""
from __future__ import annotations

import re
from typing import Any

import pytest
from prospector.config import load_config
from prospector.models import Candidate, Source
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.results_per_query = 1
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Test Opportunity",
        one_liner="A test product",
        hypothesis="People suffer from X",
        who_pays="SMEs",
    )


# ---------------------------------------------------------------------------
# Build the known Source objects so we can cite their source_ids
# ---------------------------------------------------------------------------

PAIN_SOURCE = Source.make(url="https://pain.example.com", text="acute pain confirmed by survey data")
VALUE_SOURCE = Source.make(url="https://value.example.com", text="value is evaporating rapidly due to commoditisation")


def _make_fixture_provider() -> FixtureProvider:
    """FixtureProvider matches by substring: 'pain' matches pain_reality queries,
    'value' matches value_durability queries."""
    return FixtureProvider(fixtures={
        # pain_reality queries contain "pain_reality" which contains "pain"
        "pain": [
            {"url": PAIN_SOURCE.url, "text": PAIN_SOURCE.text},
        ],
        # value_durability is a template_check: its disconfirming query contains
        # "commoditised" (see _DISCONFIRM_TEMPLATES), so key the fixture on that.
        "commoditised": [
            {"url": VALUE_SOURCE.url, "text": VALUE_SOURCE.text},
        ],
        # LLM-path fallback (if value_durability is removed from template_checks).
        "value": [
            {"url": VALUE_SOURCE.url, "text": VALUE_SOURCE.text},
        ],
        # Fallback for any other check (should not be reached in kill-fast test)
        "incumbent": [
            {"url": "https://inc.example.com", "text": "no dominant incumbent found"},
        ],
        "payer": [
            {"url": "https://pay.example.com", "text": "SMEs have budget for this"},
        ],
        "distribution": [
            {"url": "https://dist.example.com", "text": "self-serve channel available"},
        ],
        "legal": [
            {"url": "https://legal.example.com", "text": "fully compliant"},
        ],
    })


# ---------------------------------------------------------------------------
# Router: parses first [source_id] from user text, then routes by check name
# ---------------------------------------------------------------------------

def _make_router(call_counter: list):
    """Return a router function that:
    - Counts every call that looks like a verdict call (contains 'Passages:').
    - Returns 'supported' + valid citation for pain_reality.
    - Returns 'refuted' + valid citation for value_durability.
    - Returns a query list for query_gen calls (contains 'queries most likely').
    """
    def router(system: str, user: str) -> Any:
        # query_gen calls: return a simple list
        if "queries most likely" in system or "Write 1-3 queries" in user:
            # Extract check name from user to give a useful query key
            if "pain_reality" in user:
                return ["pain reality check"]
            if "value_durability" in user:
                return ["value durability check"]
            return ["generic query"]

        # verdict calls — the user text contains the passages with [source_id] tags
        if "Passages:" not in user:
            # score / adversarial / other calls — return a safe default
            return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}

        call_counter.append(1)

        # Extract the first [source_id] from the user text
        m = re.search(r"\[([a-f0-9]{16})\]", user)
        first_id = m.group(1) if m else ""

        if "pain_reality" in user:
            # pain_reality must PASS — return supported + cite the passage
            return {
                "verdict": "supported",
                "confidence": 0.85,
                "rationale": "Survey data confirms acute pain.",
                "citations": [first_id],
            }

        if "value_durability" in user:
            # value_durability must KILL — return refuted + cite the passage
            return {
                "verdict": "refuted",
                "confidence": 0.88,
                "rationale": "Value is evaporating; commoditised.",
                "citations": [first_id],
            }

        # Should not be reached in a kill-fast run
        return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": [first_id]}

    return router


# ---------------------------------------------------------------------------
# The kill-fast test
# ---------------------------------------------------------------------------

def test_verify_short_circuits_at_value_durability(cfg, cand):
    """verify() short-circuits at the FIRST hard fail. Kill-fast order is driven by
    config (cfg.hard_gates), where value_durability is the first gate — so a refuted
    value_durability stops the run after exactly 1 check, never reaching the other five.
    """
    call_counter: list = []
    op = MockOperator(router=_make_router(call_counter))
    search = _make_fixture_provider()

    checks, adv, gate = verify(op, search, cfg, cand)

    # Gate must have fired on value_durability (the first config gate)
    assert gate == "value_durability", f"Expected gate='value_durability', got {gate!r}"

    # Exactly 1 check run — kill-fast stopped at the first decisive gate
    assert len(checks) == 1, (
        f"Expected 1 check (kill-fast at first gate), but {len(checks)} were run: "
        f"{[c.check_name for c in checks]}"
    )

    # No adversarial pass (short-circuited before it)
    assert adv is None

    value_check = checks[0]
    assert value_check.check_name == "value_durability"
    assert value_check.verdict.value == "refuted"

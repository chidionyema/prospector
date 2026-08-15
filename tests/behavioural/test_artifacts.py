"""Behavioural tests for Task B: Secondary artifacts + claim-check (Part 5, 16).

Proofs:
1. Planted fantasy number in artifacts gets labelled 'assumption — unverified'.
2. Marketing copy with an unsupported claim fails the claim-check.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from prospector.artifacts import generate_artifacts, generate_marketing_content, verify_claims
from prospector.models import Candidate, CheckResult, Verdict
from prospector.operator import MockOperator


@pytest.fixture
def cand() -> Candidate:
    return Candidate(title="Test Biz", one_liner="A test biz")


@pytest.fixture
def checks() -> list[CheckResult]:
    return [
        CheckResult(
            check_name="pain_reality", 
            verdict=Verdict.SUPPORTED, 
            confidence=0.9, 
            rationale="Verified pain exists for 100k users."
        )
    ]


def test_artifact_grounding_labels_unverified(cand, checks):
    """Proof: planted fantasy number gets labelled 'assumption — unverified'.

    FIX #3: financial_model now returns structured JSON assumptions (not prose content).
    The LLM outputs {monthly_price, assumptions:[...], weaknesses:[...], ...} and Python
    renders the arithmetic.  The 'assumption — unverified' label is carried through
    by the model in the 'assumptions' list.  This test verifies the grounding contract
    is preserved: the LLM still marks unverified figures as assumptions.
    """

    def router(system: str, user: str) -> Any:
        if "generate a grounded business artifact" in system:
            # FIX #3: model outputs structured JSON — LLM marks the TAM as an assumption.
            return {
                "monthly_price": 49,
                "target_customers_month_1": 20,
                "target_customers_month_12": 200,
                "estimated_cac_gbp": 300,
                "estimated_clv_gbp": 1200,
                "estimated_monthly_churn_pct": 5,
                "cost_of_goods_pct": 20,
                "overhead_month_1_gbp": 2000,
                "sales_cycle_months": 1,
                "payback_months": 6,
                "assumptions": [
                    # The LLM correctly labels the TAM as unverified.
                    "TAM: £1B — assumption — unverified (no verified market size claim in evidence)",
                    "Target customer base: 100k users — assumption — unverified"
                ],
                "weaknesses": [
                    "TAM is unverified; market sizing relies on published third-party estimate "
                    "without direct grounding in evidence."
                ]
            }
        return {}

    op = MockOperator(router=router)
    artifacts = generate_artifacts(op, cand, checks)

    content = artifacts.get("financial_model", "")
    # FIX #3: the 'assumption — unverified' label is now in the assumptions list rendered
    # into the model output.  The test verifies this grounding contract is preserved.
    assert "assumption — unverified" in content
    assert "TAM" in content
    # Python arithmetic renders correctly (price × customers → month 1 revenue).
    assert "£980" in content or "980" in content


def test_claim_check_rejects_unsupported_statement(cand, checks):
    """Proof: copy with an unsupported claim => claim_check pass=false."""
    
    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    copy = "This business is guaranteed to make £1M in a week." # Hallucination
    
    def router(system: str, user: str) -> Any:
        if "check marketing/listing copy" in system:
            # Identify the violation
            if "£1M" in user:
                return {
                    "pass": False,
                    "violations": [{"text": "£1M in a week", "issue": "unsupported claim"}]
                }
            return {"pass": True, "violations": []}
        return {}

    op = MockOperator(router=router)
    passed = verify_claims(op, copy, claims)
    assert passed is False


def test_marketing_content_regeneration_on_fail(cand, checks):
    """Proof: the repair turn belongs to listing_page, and ONLY to listing_page.

    `_gen_one_content` sets ``attempts = 3 if t == "listing_page" else 1``: the copy a
    buyer reads before paying gets its rewrite, the three optional pieces are dropped on
    the first claim-check failure (measured 2026-08-15 — the ancillary repair turn rescued
    ~26% of drafts and burned ~1,200 model calls doing it).

    The old version of this test asserted the pre-2026-08-15 contract, where every type
    was regenerated. It also keyed its router on the GLOBAL call ordinal, so which piece
    received the planted hallucination depended on which of the four threads got there
    first — the assertion passed or failed on a thread race. The router below keys on the
    piece TYPE (`Type: {type}` in the content_gen user prompt, prompts/content_gen.md:40),
    so every piece gets the same treatment and the counts are exact, not `>=`.
    """
    from prospector.marketing_assets import ASSET_TYPES

    lock = threading.Lock()
    per_type_gen: dict[str, int] = {}
    call_counts = {"content_gen": 0, "claim_check": 0}

    def router(system: str, user: str) -> Any:
        if "write listing and marketing copy" in system:
            t = next((a for a in ASSET_TYPES if f"Type: {a}" in user), "unknown")
            with lock:
                call_counts["content_gen"] += 1
                per_type_gen[t] = per_type_gen.get(t, 0) + 1
                n = per_type_gen[t]
            # Every type hallucinates on its FIRST draft and is clean thereafter, so the
            # only thing that varies between pieces is whether a second draft is asked for.
            if n == 1:
                return {"type": t, "copy": "Hallucinated claim."}
            return {"type": t, "copy": "Grounded claim: 100k users."}

        if "check marketing/listing copy" in system:
            with lock:
                call_counts["claim_check"] += 1
            if "Hallucinated" in user:
                return {"pass": False, "violations": [{"text": "Hallucinated", "issue": "bad"}]}
            return {"pass": True, "violations": []}
        return {}

    op = MockOperator(router=router)
    content = generate_marketing_content(op, cand, checks)

    ancillary = [t for t in ASSET_TYPES if t != "listing_page"]
    # listing_page: draft 1 fails, draft 2 clears -> 2 calls. Each ancillary piece: one
    # draft, one check, dropped. Exact, because the router no longer depends on ordering.
    assert per_type_gen["listing_page"] == 2, per_type_gen
    for t in ancillary:
        assert per_type_gen[t] == 1, per_type_gen
    assert call_counts["content_gen"] == len(ancillary) + 2
    assert call_counts["claim_check"] == len(ancillary) + 2

    # The rewritten listing_page is what ships...
    listing = next(c for c in content if c["type"] == "listing_page")
    assert "Grounded" in str(listing)
    assert "Hallucinated" not in str(listing)
    # ...and a piece that failed its only claim-check is DROPPED, never shipped unverified.
    assert {c["type"] for c in content}.isdisjoint(ancillary), content

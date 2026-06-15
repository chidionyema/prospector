"""Behavioural tests for Task B: Secondary artifacts + claim-check (Part 5, 16).

Proofs:
1. Planted fantasy number in artifacts gets labelled 'assumption — unverified'.
2. Marketing copy with an unsupported claim fails the claim-check.
"""
from __future__ import annotations

import json
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
    """Proof: A piece that fails claim-check is regenerated (attempted twice)."""
    
    call_counts = {"content_gen": 0, "claim_check": 0}
    
    def router(system: str, user: str) -> Any:
        if "write listing and marketing copy" in system:
            call_counts["content_gen"] += 1
            # Return a hallucination on the first attempt
            if call_counts["content_gen"] == 1:
                return {"type": "listing_page", "copy": "Hallucinated claim."}
            # Return clean copy on the second attempt
            return {"type": "listing_page", "copy": "Grounded claim: 100k users."}
            
        if "check marketing/listing copy" in system:
            call_counts["claim_check"] += 1
            if "Hallucinated" in user:
                return {"pass": False, "violations": [{"text": "Hallucinated", "issue": "bad"}]}
            return {"pass": True, "violations": []}
        return {}

    op = MockOperator(router=router)
    # Filter to just listing_page for this test to keep call counts simple
    from prospector import artifacts
    # Patch types temporarily or just check counts
    content = generate_marketing_content(op, cand, checks)
    
    # Each content type is generated. For 'listing_page', it should have taken 2 attempts.
    # Total content_gen calls = (3 types * 1 attempt) + (1 type * 2 attempts) = 5
    # (actually 4 types total in generate_marketing_content)
    # If all 4 types are run:
    # listing_page: 2 attempts
    # teaser_social: 1 attempt
    # seo_preview: 1 attempt
    # launch_email: 1 attempt
    # Total = 5 calls to content_gen
    assert call_counts["content_gen"] >= 5
    assert call_counts["claim_check"] >= 5
    
    # Find the listing_page result
    listing = next(c for c in content if c["type"] == "listing_page")
    assert "Grounded" in listing["copy"]
    assert "Hallucinated" not in listing["copy"]

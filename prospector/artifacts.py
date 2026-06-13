"""Secondary artifacts + claim-check (Part 5).
On PASS, generate build_spec, GTM, ops_plan, financial_model (grounded),
plus claim-checked marketing/listing content.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .models import Candidate, CheckResult, Verdict
from .operator import Operator
from .prompts import render


def generate_artifacts(
    op: Operator, 
    cand: Candidate, 
    checks: List[CheckResult]
) -> Dict[str, str]:
    """Generate grounded build_spec, gtm_plan, ops_plan, and financial_model."""
    # We only use SUPPORTED checks as 'verified claims'
    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["build_spec", "gtm_plan", "ops_plan", "financial_model"]
    results = {}

    for t in types:
        system, user = render("artifacts", candidate_json=cand_json,
                              claims_json=claims_json, type=t)
        # Using temperature 0.3 for grounding consistency
        data = op.complete_json(system, user, temperature=0.3)
        results[t] = str(data.get("content", ""))

    return results


def verify_claims(op: Operator, copy: str, claims: List[Dict[str, Any]]) -> bool:
    """Check marketing/listing copy for claim-consistency (Part 5)."""
    system, user = render("claim_check", copy=copy, claims_json=json.dumps(claims))
    try:
        data = op.complete_json(system, user, temperature=0.0)
        return bool(data.get("pass", False))
    except Exception:
        # Fail-safe: if the check fails, we assume it's NOT verified
        return False


def generate_marketing_content(
    op: Operator, 
    cand: Candidate, 
    checks: List[CheckResult]
) -> List[Dict[str, str]]:
    """Generate and claim-check listing_page, teaser_social, seo_preview, and launch_email."""
    # We only use SUPPORTED checks as 'verified claims'
    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["listing_page", "teaser_social", "seo_preview", "launch_email"]
    out = []

    for t in types:
        copy = ""
        passed = False
        # Part 5: "A piece that fails [claim-check] is regenerated"
        for attempt in range(2):
            system, user = render("content_gen", candidate_json=cand_json,
                                  claims_json=claims_json, type=t)
            data = op.complete_json(system, user, temperature=0.7)
            copy = str(data.get("copy", ""))
            
            if verify_claims(op, copy, claims):
                passed = True
                break
            # If it fails, next attempt will try again (temperature 0.7 adds variance)
            
        if passed:
            out.append({"type": t, "copy": copy})
        else:
            from .telemetry import logger
            logger.warning(f"Dropping unverified marketing piece: {t}", extra={"candidate_id": cand.candidate_id})

    return out

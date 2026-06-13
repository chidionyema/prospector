"""Packs and pricing (Part 6).
Composes the Scout, Operator, and Founder-Investor packs from the artifact graph.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from .models import Dossier, Decision, ScoreResult
from .score import listing_price_signal

def compose_packs(dossier: Dossier, cfg: Any) -> Dict[str, Any]:
    """Compose tiered packs from the dossier's artifacts and scores."""
    if dossier.decision != Decision.PASS:
        return {}

    score = dossier.score
    if not score:
        return {}

    # Base price signal from score.py
    price_signal = listing_price_signal(score, cfg)
    
    # Tiers and their contents (Part 6 table)
    # Scout: validated thesis + evidence table + score
    # Operator: Scout + build spec + grounded GTM + ops plan
    # Founder/Investor: Operator + competitive teardown + financial model + risk register + market memo
    
    # Map artifacts
    # Note: 'competitive teardown', 'risk register', 'market memo' are currently stubs
    # or part of other artifacts. We'll group them into the main 4 for now.
    
    # Pricing multipliers (cents)
    # Scout: ~$20-50, Operator: ~$100-200, Founder: ~$500-1000
    # If price_signal is ~4-6:
    scout_price = int(price_signal * 1000) # 4.5 -> 4500 ($45)
    operator_price = int(price_signal * 3000) # 4.5 -> 13500 ($135)
    founder_price = int(price_signal * 10000) # 4.5 -> 45000 ($450)

    packs = {
        "scout": {
            "name": "Scout",
            "price_cents": scout_price,
            "contents": {
                "thesis": dossier.candidate.hypothesis,
                "evidence": [s.to_dict() for s in dossier.all_sources],
                "score": score.to_dict()
            }
        },
        "operator": {
            "name": "Operator",
            "price_cents": operator_price,
            "contents": {
                "scout": "included",
                "build_spec": dossier.candidate.tags.get("artifacts", {}).get("build_spec"),
                "gtm_plan": dossier.candidate.tags.get("artifacts", {}).get("gtm_plan"),
                "ops_plan": dossier.candidate.tags.get("artifacts", {}).get("ops_plan")
            }
        },
        "founder_investor": {
            "name": "Founder / Investor",
            "price_cents": founder_price,
            "contents": {
                "operator": "included",
                "financial_model": dossier.candidate.tags.get("artifacts", {}).get("financial_model"),
                "risk_register": "included in financial_model", # per current artifacts prompt
                "market_memo": "included in gtm_plan"
            }
        }
    }
    
    return packs

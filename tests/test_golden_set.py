"""Golden-set acceptance test (Part 14 step 4, Part 16).

Verifies that the Golden Set harness correctly discriminates between PASS/KILL
cases using a deterministic mock operator and fixture provider.

This proves:
1. The harness (prospector/golden.py) is correct.
2. The engine's verification pipeline (verify, kill_filter, score) correctly
   handles various kill gates and pass conditions.
3. The discrimination metric is calculated correctly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from prospector.config import load_config
from prospector.golden import run_golden_set
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider

# ---------------------------------------------------------------------------
# Data mapping for the Golden Mock
# ---------------------------------------------------------------------------

GOLDEN_EXPECTATIONS = {
    "Haulage HMRC fuel-duty": {
        "kill_gate": "value_durability", 
        "kill_verdict": "refuted",
        "rationale": "2022 red-diesel reform removed off-road entitlement for haulage"
    },
    "Construction retention": {
        "kill_gate": "value_durability", 
        "kill_verdict": "refuted",
        "rationale": "retentions being banned; loss is insolvency-driven"
    },
    "AI subscription spend-audit": {
        "kill_gate": "incumbency", 
        "kill_verdict": "supported", 
        "rationale": "funded incumbents already ship SaaS-spend management"
    },
    "Care-home council fee": {
        "kill_gate": "payer_solvency", 
        "kill_verdict": "refuted",
        "rationale": "councils chronically under-funded; payer can't pay"
    },
    "Token/credit resale": {
        "kill_gate": "legality",
        "kill_verdict": "supported",   # margin DEPENDS ON breaking provider terms -> kill
        "rationale": "resale/account-sharing violates provider terms"
    },
    "Generic AI meal-planner": {
        "kill_gate": "pain_reality", 
        "kill_verdict": "refuted",
        "rationale": "saturated consumer category, no acute pain (non-reg test)"
    },
    "Unified-API niche bridge": {
        "kill_gate": None, 
        "rationale": "proven pattern; moat = un-shortcuttable integration work"
    },
    "Construction smash-and-grab": {
        "kill_gate": None, 
        "rationale": "solvent payer + statutory adjudication forcing mechanism"
    },
}

def _make_golden_router():
    def router(system: str, user: str) -> Any:
        # 1. Query generation
        if "queries most likely" in system or "Write 1-3 queries" in user:
            for idea in GOLDEN_EXPECTATIONS:
                if idea.lower() in user.lower():
                    return [idea]
            return ["generic query"]

        # 3. Verdicts
        if "Passages:" in user:
            m = re.search(r"\[([a-f0-9]{16})\]", user)
            first_id = m.group(1) if m else ""
            
            # Find which idea we are talking about
            active_idea = None
            for idea in GOLDEN_EXPECTATIONS:
                if idea.lower() in user.lower():
                    active_idea = idea
                    break
            
            if not active_idea:
                return {"verdict": "unverifiable", "confidence": 0.5, "rationale": "unknown idea", "citations": []}
            
            exp = GOLDEN_EXPECTATIONS[active_idea]
            kill_gate = exp["kill_gate"]
            
            # Identify current check from user text
            current_check = None
            for check_name in ["pain_reality", "value_durability", "incumbency", "payer_solvency", "distribution", "legality"]:
                if check_name in user:
                    current_check = check_name
                    break
            
            if kill_gate and current_check == kill_gate:
                return {
                    "verdict": exp["kill_verdict"],
                    "confidence": 0.95,
                    "rationale": exp["rationale"],
                    "citations": [first_id]
                }
            
            # PASS logic — depends on each check's QUESTION FRAMING:
            #   incumbency ("someone already solves this?")  -> PASS = refuted (no incumbent)
            #   legality   ("margin depends on breaking law?") -> PASS = refuted (lawful)
            #   others (positively framed)                    -> PASS = supported
            v = "refuted" if current_check in ("incumbency", "legality") else "supported"
            
            # Surface the rationale in pain_reality for PASS cases
            rat = exp["rationale"] if (not kill_gate and current_check == "pain_reality") else "No evidence to the contrary."
            
            return {
                "verdict": v,
                "confidence": 0.9,
                "rationale": rat,
                "citations": [first_id]
            }

        # 4. Scoring
        if "Score a vetted opportunity" in system or '"scores":' in user:
            scores = {
                "pain_acuity": 4,
                "money_provability": 4,
                "automatability": 4,
                "distribution": 4,
                "defensibility": 4,
                "build_feasibility": 4
            }
            return {
                "scores": scores,
                "justification": {k: "looks good" for k in scores}
            }


        # Safe default
        return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}

    return router


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_golden_set_discrimination_is_perfect_with_mock_data():
    """Run the 8-case golden set with our specialized router and fixtures.
    Should achieve 100% discrimination.
    """
    cfg = load_config()
    cfg.retrieval.provider = "fixture"
    cfg.retrieval.cache = False
    
    op = MockOperator(router=_make_golden_router())
    
    # Load fixtures
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "golden_fixtures.json"
    with open(fixtures_path, "r", encoding="utf-8") as f:
        fixtures = json.load(f)
    search = FixtureProvider(fixtures=fixtures)
    
    golden_set_path = Path(__file__).parent.parent / "fixtures" / "golden_set.json"
    
    discrimination, results = run_golden_set(op, search, cfg, str(golden_set_path), verbose=True)
    
    assert discrimination == 1.0, f"Expected 100% discrimination, got {discrimination:.1%}"
    assert len(results) == 8
    for r in results:
        assert r["passed"], f"Case {r['idea']!r} failed to meet expectations"

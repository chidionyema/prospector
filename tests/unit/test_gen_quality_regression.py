"""Automated regression guard for generation quality optimizations.

Captures DPP diversity, positive trait extraction, grid priorities, and
exemplar robustness as baseline measurements. Any future technique change
that regresses these numbers without an intentional re-baseline fails CI.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from prospector.adaptive import get_pass_traits, calculate_grid_priorities, get_exemplars
from prospector.config import Config, Thresholds
from prospector.models import Candidate
from prospector.novelty import select_diverse_candidates, _text_similarity

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
BASELINE_PATH = FIXTURES / "gen_quality_baseline.json"


def _load_baseline():
    return json.loads(BASELINE_PATH.read_text())


# ---------------------------------------------------------------------------
# Helper: no-embedding operator (simulates all non-Gemini operators)
# ---------------------------------------------------------------------------

class _NoEmbedOp:
    model_version = "stub"
    name = "stub"

    def embed(self, text: str) -> list[float]:
        return []

    def complete_json(self, system, user, temperature=0.7):
        return {}


# ---------------------------------------------------------------------------
# 1. DPP diversity regression
# ---------------------------------------------------------------------------

def test_dpp_diversity_meets_baseline():
    """DPP with no embeddings must select at most N AI-cluster ideas and produce
    average pairwise similarity below the baseline threshold."""
    baseline = _load_baseline()["dpp_diversity"]["baseline"]

    candidates = [
        (Candidate(title="AI Invoice Processing for SMEs",
                   one_liner="Automated invoice processing for small businesses"), 0.90, ""),
        (Candidate(title="AI Expense Tracking Tool",
                   one_liner="Automated expense management for business owners"), 0.88, ""),
        (Candidate(title="AI Tax Filing Assistant",
                   one_liner="Automated tax preparation and filing for freelancers"), 0.86, ""),
        (Candidate(title="AI Payroll Automation",
                   one_liner="Payroll processing for UK small businesses"), 0.84, ""),
        (Candidate(title="AI Inventory Management",
                   one_liner="Stock management and reordering for SMEs"), 0.82, ""),
        # Diverse cluster
        (Candidate(title="Construction Adjudication Arbitrage",
                   one_liner="Recover unpaid invoices via statutory adjudication under Housing Grants Act"), 0.70, ""),
        (Candidate(title="Probate Property Clear-Out Service",
                   one_liner="Clear, value and sell estate properties for fixed fee on behalf of executors"), 0.68, ""),
        (Candidate(title="Garden Office Power Broker",
                   one_liner="Source, negotiate and project-manage pre-fab garden office installations"), 0.66, ""),
        (Candidate(title="Tradie Time-Capture Agent",
                   one_liner="Done-for-you automated time tracking for sole-trading tradespeople"), 0.64, ""),
        (Candidate(title="Solo Breeder Litter Deposit Recovery Kit",
                   one_liner="Template legal kit for recovering pet breeding litter deposits"), 0.62, ""),
    ]

    result = select_diverse_candidates(_NoEmbedOp(), candidates, k=baseline["k"])
    titles = [c.title for c in result]
    ai_count = sum(1 for t in titles if t.startswith("AI "))

    # Average pairwise trigram similarity
    total_sim = 0.0
    pairs = 0
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            total_sim += _text_similarity(titles[i], titles[j])
            pairs += 1
    avg_sim = total_sim / pairs if pairs else 0.0

    diverse_count = sum(1 for t in titles if not t.startswith("AI "))

    assert ai_count <= baseline["max_ai_cluster_selected"], \
        f"DPP selected {ai_count} AI-cluster ideas (baseline max: {baseline['max_ai_cluster_selected']})"
    assert avg_sim <= baseline["max_avg_pairwise_similarity"], \
        f"avg pairwise similarity {avg_sim:.3f} exceeds baseline {baseline['max_avg_pairwise_similarity']}"
    assert diverse_count >= baseline["min_diverse_selected"], \
        f"only {diverse_count} diverse candidates (baseline min: {baseline['min_diverse_selected']})"

    # If we're within baseline, record actual numbers for debugging
    print(f"  DPP regression check: ai_count={ai_count}/{baseline['max_ai_cluster_selected']} "
          f"avg_sim={avg_sim:.3f}/{baseline['max_avg_pairwise_similarity']} "
          f"diverse={diverse_count}/{baseline['min_diverse_selected']} — PASS")


# ---------------------------------------------------------------------------
# 2. Positive trait extraction regression
# ---------------------------------------------------------------------------

def test_pass_traits_format_meets_baseline():
    """get_pass_traits output must contain baseline-required fields."""
    baseline = _load_baseline()["pass_traits"]["baseline"]

    # Test 1: empty store → empty string
    class _EmptyStore:
        def all(self, decision=None):
            return []

    assert get_pass_traits(_EmptyStore()) == baseline["empty_store_returns"], \
        "Empty store should return empty string"

    # Test 2: store with PASSes → must contain required fields
    class _MockStore:
        def all(self, decision=None):
            return [
                {"candidate_id": "abc", "structural_form": "local_service",
                 "ambition_tier": "side_hustle"},
            ]

        def get(self, cid):
            return {
                "candidate": {
                    "title": "Test Pass",
                    "one_liner": "A passing test idea",
                    "tags": {"sector": "construction", "audience": "retiree_cohort"},
                    "hypothesis": "Uses regulatory wedge",
                    "durable_wedge_type": "regulatory_license",
                },
            }

    traits = get_pass_traits(_MockStore())
    for field in baseline["required_fields_when_passes_exist"]:
        assert field in traits, \
            f"get_pass_traits output missing required field '{field}'"

    print(f"  Pass traits format check: {len(baseline['required_fields_when_passes_exist'])} fields present — PASS")


# ---------------------------------------------------------------------------
# 3. Grid priority boosting regression
# ---------------------------------------------------------------------------

def test_grid_priorities_boosting_meets_baseline():
    """Fertile forms must be boosted at baseline multipliers."""
    baseline = _load_baseline()["grid_priorities"]["baseline"]

    cfg = Config(
        active_lanes=["test_lane"],
        lanes={
            "test_lane": {
                "generation": {
                    "structural_forms": ["form_a", "form_b", "form_c"],
                },
            },
        },
        thresholds=Thresholds(confidence_floor=0.6, min_composite_to_pass=2.0),
    )

    class MockStore:
        def all(self, decision=None):
            rows = []
            for i in range(5):
                rows.append({"candidate_id": f"a{i}", "ambition_tier": "test_lane",
                             "structural_form": "form_a"})
            for i in range(2):
                rows.append({"candidate_id": f"b{i}", "ambition_tier": "test_lane",
                             "structural_form": "form_b"})
            return rows

    priorities = calculate_grid_priorities(MockStore(), cfg)
    prio_list = priorities.get("test_lane", [])

    # Fertile form_a must be boosted 3x
    assert prio_list.count("form_a") == baseline["fertile_form_multiplier_top"], \
        f"form_a count {prio_list.count('form_a')} != baseline {baseline['fertile_form_multiplier_top']}"

    # form_b must be boosted 2x
    assert prio_list.count("form_b") == baseline["fertile_form_multiplier_second"], \
        f"form_b count {prio_list.count('form_b')} != baseline {baseline['fertile_form_multiplier_second']}"

    # Zero-count form must be included
    assert baseline["zero_count_forms_always_included"]
    assert "form_c" in prio_list, "zero-count form_c missing from priorities"

    print(f"  Grid priorities: form_a×{prio_list.count('form_a')} "
          f"form_b×{prio_list.count('form_b')} form_c present — PASS")


# ---------------------------------------------------------------------------
# 4. Exemplar robustness regression
# ---------------------------------------------------------------------------

def test_exemplars_handle_edge_cases():
    """get_exemplars must never crash on missing/incomplete dossiers."""
    baseline = _load_baseline()["exemplars"]["baseline"]

    class MockStore:
        def all(self, decision=None):
            if decision == "pass":
                return [
                    {"candidate_id": "abc", "composite": 3.5, "title": "Test"},
                ]
            return [
                {"candidate_id": "def", "title": "Kill Test",
                 "gate_fired": "value_durability", "adversarial_confidence": 0.9},
            ]

        def get(self, cid):
            # Simulate missing dossier JSON
            return None

    result = get_exemplars(MockStore())
    # Should not crash — output may be empty or partial
    assert isinstance(result, str)
    # Even with missing dossiers, should not raise
    assert True  # survived

    print(f"  Exemplar robustness: survived missing dossier — PASS")


# ---------------------------------------------------------------------------
# 5. Thin-candidate skip regression
# ---------------------------------------------------------------------------

def test_thin_candidates_skip_refinement():
    """The _refine_wave filter in generate.py must not send thin candidates to LLM.
    Proof: with 2 structural forms, thin candidate survives in its own form slot."""
    from prospector.generate import generate
    from prospector.config import Config as Cfg

    refinement_calls = []

    class _ThinOp:
        model_version = "stub"
        name = "stub"

        def embed(self, t):
            return []

        def complete_json(self, system, user, temperature=0.7):
            combined = (system + " " + user).lower()
            if "critique" in combined or "refine" in combined:
                refinement_calls.append(True)
                return [{"title": "Refined Substantive Idea",
                         "one_liner": "This idea has been refined with more detail and edge",
                         "why_now": "2024 regulatory change plus API",
                         "tags": {"sector": "construction"},
                         "automatability": 0.8, "weak_monetisation": False}]
            # Generation call — return candidates matching each form
            return [
                {"title": "Thin", "one_liner": "x", "why_now": "now", "tags": {},
                 "automatability": 0.5, "weak_monetisation": False},
                {"title": "A Substantive Business Idea With Detail",
                 "one_liner": "This idea has enough text detail to be worth refining",
                 "why_now": "2024 regulatory change", "tags": {"sector": "construction"},
                 "automatability": 0.7, "weak_monetisation": False},
            ]

    cfg = Cfg(
        generation={
            "candidates_per_signal": 2,
            "max_per_call": 2,
            "max_rounds": 1,
            "refinement_enabled": True,
            "structural_forms": ["local_service", "micro_ecommerce"],
            "audience_forms": ["retiree_cohort"],
            "operator_archetype": "",
            "archetypes": {},
        },
        thresholds=Thresholds(confidence_floor=0.6, min_composite_to_pass=2.0),
    )

    op = _ThinOp()
    result = generate(op, cfg, signal_text="test", k=2)

    # The thin candidate must survive
    thin = [c for c in result if c.title == "Thin"]
    assert len(thin) >= 1, f"Thin candidate was dropped — should be preserved, got {[c.title for c in result]}"

    # Refinement was called (since substantive existed)
    assert len(refinement_calls) >= 1, "Refinement LLM was never called"

    print(f"  Thin-candidate skip: thin survived, refinement called {len(refinement_calls)}x — PASS")

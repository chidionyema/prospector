"""Moat-discipline generation contract (gen-side fix for the value_durability wall).

Diagnosis (2026-06-14): 54/68 KILLs (79%) fired on value_durability — all correctly
cited. Root cause was a GENERATION wrapper-reflex (insurance pool / concierge /
marketplace / brokerage on a transparent market whose value is already free or a
predictable expense), not verification mis-calibration. The fix lives in generation:
each idea must declare a durable wedge from a closed taxonomy and pass a commodity
pre-mortem. These tests lock that contract in (gates stay untouched — constraint still
lives in verification).
"""
from __future__ import annotations

from prospector import adaptive
from prospector.generate import _parse_candidates
from prospector.models import Candidate
from prospector.prompts import render


def test_wedge_and_premortem_fold_into_tags_and_serialise():
    c = Candidate.from_dict({
        "title": "Test Co", "one_liner": "x",
        "durable_wedge_type": "regulatory_license",
        "commodity_premortem": {
            "strongest_free_or_commodity_alternative": "HMRC free filing",
            "why_that_incumbent_cannot_capture_this_value": "needs FCA licence"},
        "tags": {"sector": "fintech"},
    })
    assert c.tags["durable_wedge_type"] == "regulatory_license"
    assert c.tags["commodity_premortem"][
        "why_that_incumbent_cannot_capture_this_value"] == "needs FCA licence"
    assert c.tags["sector"] == "fintech"            # existing tags preserved
    assert "durable_wedge_type" in c.to_dict()["tags"]   # persists to dossier JSON


def test_parse_candidates_carries_wedge_field():
    parsed = _parse_candidates([{"title": "A", "durable_wedge_type": "network_effect"}])
    assert parsed[0].tags["durable_wedge_type"] == "network_effect"


def test_generate_prompt_renders_moat_taxonomy_and_premortem():
    # FIX #5: the taxonomy (moat wedge, commodity pre-mortem, structural traps) moved
    # from the user section to generate_system.md (static, model-cached).  The user
    # section now carries only dynamic variables.  Both sections must be present.
    system, user = render("generate", signal_text="s", sector="", strategy_lens="invert",
                           exploration_level=0.7, target_qualities="q",
                           recent_failure_modes="f", k=5, avoid="none", seed="1.1")
    # Static taxonomy lives in the system section (generate_system.md).
    for needle in ("DURABLE VALUE-CAPTURE IS MANDATORY", "COMMODITY PRE-MORTEM",
                   "proprietary_data", "regulatory_license", "network_effect",
                   "switching_cost", "exclusive_channel", "technical_ip",
                   "durable_wedge_type", "commodity_premortem"):
        assert needle in system, f"generate system prompt missing: {needle}"
    # Dynamic user-side variables render correctly.
    assert "Exploration level 0-1: 0.7" in user
    assert "STRUCTURAL FORM for THIS batch" in user


class _FakeStore:
    """Catalogue where value_durability dominates the recent kills."""
    def all(self, decision=None):
        return [{"candidate_id": f"id{i}", "gate_fired": "value_durability",
                 "created_at": f"2026-06-1{i}"} for i in range(5)]

    def get(self, cid):
        return {"reason": "value_durability=refuted (conf 0.8): value already free via HMRC",
                "sources": [{"url": "https://gov.uk/x"}]}


def test_dominant_gate_surfaces_abstract_structural_rule():
    fm = adaptive.get_recent_failure_modes(_FakeStore())
    assert "DOMINANT FAILURE — value_durability" in fm
    assert "middleman wrapper" in fm        # the SHAPE, not just instances
    # still keeps the per-instance evidence the generator can also use
    assert "Recent kill-gates:" in fm

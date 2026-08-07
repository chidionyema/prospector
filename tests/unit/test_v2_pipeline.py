"""Tests for Prospector v2.0 domain primitives, pipeline, and middleware."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from prospector.domain.primitives import CandidateJourney, CandidateSpec
from prospector.pipeline.middleware import TribunalMiddleware
from prospector.pipeline.moat_contract import (
    MoatVerificationContract,
)

# ── CandidateSpec ───────────────────────────────────────────────────────


class TestCandidateSpec:
    def test_frozen_instance_prevents_mutation(self):
        spec = CandidateSpec(
            generation_batch_id="b1",
            structural_form="vertical_tool",
            target_audience="smb_owner",
            core_concept_prose="An AI bookkeeper for tradespeople.",
        )
        with pytest.raises(Exception):  # FrozenInstanceError or similar
            spec.target_audience = "new_audience"  # type: ignore[misc]

    def test_deterministic_id_same_payload_same_id(self):
        # Same created_at needed for deterministic ID — use a fixed timestamp.
        ts = 1000.0
        a2 = CandidateSpec("b1", "form_a", "aud_x", "concept", created_at=ts)
        b2 = CandidateSpec("b1", "form_a", "aud_x", "concept", created_at=ts)
        assert a2.id == b2.id

    def test_different_payload_different_id(self):
        a = CandidateSpec("b1", "form_a", "aud_x", "concept_a")
        b = CandidateSpec("b1", "form_a", "aud_x", "concept_b")
        assert a.id != b.id

    def test_id_is_16_chars_hex(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        assert len(spec.id) == 16
        assert all(c in "0123456789abcdef" for c in spec.id)


# ── CandidateJourney ────────────────────────────────────────────────────


class TestCandidateJourney:
    def test_default_status_is_prescreened(self):
        j = CandidateJourney(spec_id="abc123")
        assert j.status == "PRESCREENED"

    def test_append_event_adds_timestamped_record(self):
        j = CandidateJourney(spec_id="abc123")
        j.append_event("VETTING_STARTED", {"gate": "legality"})
        assert len(j.audit_log) == 1
        assert j.audit_log[0]["stage"] == "VETTING_STARTED"
        assert j.audit_log[0]["gate"] == "legality"
        assert "ts" in j.audit_log[0]

    def test_pivot_count_starts_zero(self):
        j = CandidateJourney(spec_id="abc123")
        assert j.pivot_count == 0


# ── MoatVerificationContract ────────────────────────────────────────────


class TestMoatContract:
    def test_valid_minimal_contract_parses(self):
        raw = _make_minimal_contract_json(status="KILL", law="LAW: Test rule")
        contract = MoatVerificationContract.model_validate_json(raw)
        assert contract.verdict_declaration.status == "KILL"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            MoatVerificationContract.model_validate_json("not json")

    def test_missing_required_field_raises(self):
        raw = json.dumps({"ledger_audit": {"violates_known_laws": False}})
        with pytest.raises(Exception):
            MoatVerificationContract.model_validate_json(raw)

    def test_invalid_status_raises(self):
        raw = _make_minimal_contract_json(status="INVALID_STATUS", law="LAW: x")
        with pytest.raises(Exception):
            MoatVerificationContract.model_validate_json(raw)

    def test_proceed_status_parses(self):
        raw = _make_minimal_contract_json(status="PROCEED", competitors=["Acme Corp", "Beta Inc"])
        contract = MoatVerificationContract.model_validate_json(raw)
        assert contract.verdict_declaration.status == "PROCEED"

    def test_pivot_status_with_payload_parses(self):
        raw = _make_minimal_contract_json(
            status="PIVOT",
            axis="TARGET_AUDIENCE",
            generator_prompt="Retarget to enterprise instead of SMB.",
        )
        contract = MoatVerificationContract.model_validate_json(raw)
        assert contract.verdict_declaration.status == "PIVOT"
        assert contract.verdict_declaration.pivot_payload is not None
        assert contract.verdict_declaration.pivot_payload.axis == "TARGET_AUDIENCE"


# ── TribunalMiddleware ──────────────────────────────────────────────────


class TestTribunalMiddleware:
    def test_schema_trap_rejects_invalid_json(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        with pytest.raises(ValueError, match="MALFORMED_SCHEMA"):
            tribunal.audit_payload("not json", journey)

    def test_empty_proof_trap_rejects_short_differentiation(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        raw = _make_minimal_contract_json(
            status="PROCEED",
            competitors=["Acme Corp", "Beta Inc"],
            differentiation_proof="short",  # < 40 chars
        )
        with pytest.raises(ValueError, match="LAZY_TOKEN_GENERATION"):
            tribunal.audit_payload(raw, journey)

    def test_empty_proof_trap_rejects_no_competitors(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        raw = _make_minimal_contract_json(
            status="PROCEED",
            competitors=["NONE"],
            differentiation_proof="A" * 50,
        )
        with pytest.raises(ValueError, match="UNCITED_INCUMBENCY"):
            tribunal.audit_payload(raw, journey)

    def test_empty_proof_trap_rejects_empty_competitor_list(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        raw = _make_minimal_contract_json(
            status="PROCEED",
            competitors=[],
            differentiation_proof="A" * 50,
        )
        with pytest.raises(ValueError, match="UNCITED_INCUMBENCY"):
            tribunal.audit_payload(raw, journey)

    def test_pivot_limiter_force_kills_after_2_pivots(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123", pivot_count=2)
        raw = _make_minimal_contract_json(
            status="PIVOT",
            axis="CORE_FEATURE",
            generator_prompt="Change the core feature.",
        )
        contract = tribunal.audit_payload(raw, journey)
        # Should have been force-mutated to KILL.
        assert contract.verdict_declaration.status == "KILL"
        assert contract.verdict_declaration.new_ledger_law is not None
        assert "LAW:" in contract.verdict_declaration.new_ledger_law

    def test_pivot_limiter_rejects_defective_pivot(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        raw = _make_minimal_contract_json(
            status="PIVOT",
            axis="CORE_FEATURE",
            generator_prompt="",  # empty — defective
        )
        with pytest.raises(ValueError, match="DEFECTIVE_PIVOT"):
            tribunal.audit_payload(raw, journey)

    def test_pivot_limiter_allows_first_pivot(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123", pivot_count=0)
        raw = _make_minimal_contract_json(
            status="PIVOT",
            axis="PRICING_MODEL",
            generator_prompt="Switch to subscription model.",
        )
        contract = tribunal.audit_payload(raw, journey)
        assert contract.verdict_declaration.status == "PIVOT"

    def test_disk_commit_writes_law_to_ledger(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            ledger_path = f.name
        try:
            tribunal = TribunalMiddleware(ledger_path=ledger_path)
            journey = CandidateJourney(spec_id="abc123")
            raw = _make_minimal_contract_json(
                status="KILL",
                law="LAW: Do not build middleman wrappers on transparent markets.",
            )
            tribunal.audit_payload(raw, journey)
            content = Path(ledger_path).read_text()
            assert "LAW: Do not build middleman wrappers" in content
        finally:
            os.unlink(ledger_path)

    def test_disk_commit_sanitizes_special_chars(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            ledger_path = f.name
        try:
            tribunal = TribunalMiddleware(ledger_path=ledger_path)
            journey = CandidateJourney(spec_id="abc123")
            raw = _make_minimal_contract_json(
                status="KILL",
                law="LAW: No @#$%^ special ! chars!",
            )
            tribunal.audit_payload(raw, journey)
            content = Path(ledger_path).read_text()
            # Special chars should be stripped.
            assert "@" not in content.split("*")[-1]
            assert "LAW: No  special  chars" in content or "LAW: No special chars" in content
        finally:
            os.unlink(ledger_path)

    def test_proceed_with_valid_evidence_passes(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc123")
        raw = _make_minimal_contract_json(
            status="PROCEED",
            competitors=["Stripe", "Adyen"],
            differentiation_proof="Proprietary risk-scoring model trained on 10 years of "
            "transaction data that no competitor can replicate without the same data.",
        )
        contract = tribunal.audit_payload(raw, journey)
        assert contract.verdict_declaration.status == "PROCEED"


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_minimal_contract_json(
    status: str = "KILL",
    law: str | None = None,
    competitors: list[str] | None = None,
    differentiation_proof: str = "SHORT_CIRCUITED",
    axis: str = "CORE_FEATURE",
    generator_prompt: str = "",
) -> str:
    """Build a minimal valid MoatVerificationContract JSON string."""
    if competitors is None:
        competitors = ["SHORT_CIRCUITED"]

    pivot = None
    if status == "PIVOT":
        pivot = {
            "axis": axis,
            "generator_prompt": generator_prompt,
        }

    contract = {
        "ledger_audit": {
            "violates_known_laws": False,
            "cited_law_number": None,
        },
        "gate_evaluations": {
            "gate_1_legality": {
                "regulatory_body": "NONE",
                "fatal_flaw": False,
            },
            "gate_2_payer_solvency": {
                "existing_line_item_budget": "QuickBooks",
                "fatal_flaw": False,
            },
            "gate_3_distribution": {
                "unpaid_acquisition_wedge": "Trade show XYZ",
                "fatal_flaw": False,
            },
            "gate_4_incumbency": {
                "named_competitors": competitors,
                "differentiation_proof": differentiation_proof,
                "fatal_flaw": False,
            },
            "gate_5_value_durability": {
                "why_not_a_vitamin": "This solves a critical compliance problem.",
                "fatal_flaw": False,
            },
        },
        "adversarial_attack": "This business dies because incumbents will bundle the feature. "
        "The CAC is too high for solo operators.",
        "verdict_declaration": {
            "status": status,
            "pivot_payload": pivot,
            "new_ledger_law": law,
        },
    }
    return json.dumps(contract)

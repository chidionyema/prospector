"""Rigorous edge-case verification — no shortcuts permitted.

Every spec requirement is tested, including the verifier retry loop,
pivot force-mutation, ledger injection, and frozen enforcement.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prospector.domain.primitives import CandidateJourney, CandidateSpec
from prospector.pipeline.moat_contract import MoatVerificationContract
from prospector.pipeline.middleware import TribunalMiddleware
from prospector.pipeline.moat_prompts import (
    _load_ledger,
    compile_generator_system_prompt,
    compile_retry_prompt,
    compile_system_prompt,
)
from prospector.pipeline.verifier import run_moat, _build_force_kill_contract


# ── Helper: build a valid LLM response string ────────────────────────────

def _valid_llm_response(
    status: str = "KILL",
    law: str | None = "LAW: Do not build wrappers on transparent markets.",
    competitors: list[str] | None = None,
    differentiation_proof: str = "SHORT_CIRCUITED",
    axis: str = "CORE_FEATURE",
    generator_prompt: str = "Fix the core feature.",
) -> str:
    if competitors is None:
        competitors = ["SHORT_CIRCUITED"]
    pivot = None
    if status == "PIVOT":
        pivot = {"axis": axis, "generator_prompt": generator_prompt}
    return json.dumps({
        "ledger_audit": {"violates_known_laws": False, "cited_law_number": None},
        "gate_evaluations": {
            "gate_1_legality": {"regulatory_body": "NONE", "fatal_flaw": False},
            "gate_2_payer_solvency": {"existing_line_item_budget": "QuickBooks", "fatal_flaw": False},
            "gate_3_distribution": {"unpaid_acquisition_wedge": "Trade show XYZ", "fatal_flaw": False},
            "gate_4_incumbency": {"named_competitors": competitors, "differentiation_proof": differentiation_proof, "fatal_flaw": False},
            "gate_5_value_durability": {"why_not_a_vitamin": "Critical compliance need.", "fatal_flaw": False},
        },
        "adversarial_attack": "Incumbents bundle the feature. CAC too high for solo.",
        "verdict_declaration": {"status": status, "pivot_payload": pivot, "new_ledger_law": law},
    })


def _valid_proceed_response() -> str:
    return _valid_llm_response(
        status="PROCEED",
        competitors=["Stripe", "Adyen"],
        differentiation_proof="Proprietary risk model trained on a decade of transaction data — "
        "no competitor can replicate without identical data access.",
    )


def _malformed_response() -> str:
    return "not json at all"


# ── CandidateSpec Frozen Enforcement ──────────────────────────────────────


class TestCandidateSpecFrozen:
    """Prove ALL fields are frozen — no attribute can be mutated."""

    def test_cannot_mutate_generation_batch_id(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.generation_batch_id = "new"  # type: ignore[misc]

    def test_cannot_mutate_structural_form(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.structural_form = "new"  # type: ignore[misc]

    def test_cannot_mutate_target_audience(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.target_audience = "new"  # type: ignore[misc]

    def test_cannot_mutate_core_concept_prose(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.core_concept_prose = "new"  # type: ignore[misc]

    def test_cannot_mutate_created_at(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.created_at = 999.0  # type: ignore[misc]

    def test_cannot_mutate_id(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        with pytest.raises(Exception):
            spec.id = "new_id"  # type: ignore[misc]


# ── CandidateJourney Audit Integrity ─────────────────────────────────────


class TestJourneyAuditIntegrity:
    """Prove audit_log is truly append-only within the class API."""

    def test_append_event_increments_log(self):
        j = CandidateJourney(spec_id="x")
        j.append_event("A", {})
        j.append_event("B", {})
        assert len(j.audit_log) == 2

    def test_events_are_timestamped(self):
        j = CandidateJourney(spec_id="x")
        j.append_event("X", {"k": "v"})
        assert "ts" in j.audit_log[0]
        assert j.audit_log[0]["stage"] == "X"
        assert j.audit_log[0]["k"] == "v"


# ── Verifier Retry Loop ──────────────────────────────────────────────────


class TestVerifierRetryLoop:
    """Prove the retry loop: 2 retries, force-KILL on 3rd failure."""

    def test_proceed_on_first_attempt_no_retries(self):
        spec = CandidateSpec("b1", "vertical_tool", "smb", "AI bookkeeper")
        journey = CandidateJourney(spec_id=spec.id)
        llm = MagicMock(return_value=_valid_proceed_response())

        contract = run_moat(spec, journey, llm)
        assert contract.verdict_declaration.status == "PROCEED"
        assert journey.status == "PASS"
        assert llm.call_count == 1

    def test_retries_on_malformed_then_succeeds(self):
        spec = CandidateSpec("b1", "vertical_tool", "smb", "AI bookkeeper")
        journey = CandidateJourney(spec_id=spec.id)
        # First call malformed, second succeeds.
        llm = MagicMock(side_effect=[_malformed_response(), _valid_proceed_response()])

        contract = run_moat(spec, journey, llm)
        assert contract.verdict_declaration.status == "PROCEED"
        assert journey.status == "PASS"
        assert llm.call_count == 2
        # Verify retry prompt was injected.
        assert "failed validation" in llm.call_args_list[1][0][1].lower()

    def test_force_kill_after_exhausting_retries(self):
        spec = CandidateSpec("b1", "vertical_tool", "smb", "AI bookkeeper")
        journey = CandidateJourney(spec_id=spec.id)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            ledger_path = f.name
        try:
            tribunal = TribunalMiddleware(ledger_path=ledger_path)
            # All 3 attempts fail.
            llm = MagicMock(return_value=_malformed_response())

            contract = run_moat(spec, journey, llm, tribunal=tribunal)
            assert contract.verdict_declaration.status == "KILL"
            assert journey.status == "KILL"
            assert llm.call_count == 3  # 3 attempts (0, 1, 2)
            # Verify the law was written to ledger.
            content = Path(ledger_path).read_text()
            assert "LAW:" in content
            assert spec.id in content
        finally:
            os.unlink(ledger_path)

    def test_force_kill_contract_has_all_required_fields(self):
        """The synthetic force-KILL contract must be structurally valid."""
        spec = CandidateSpec("b1", "f", "a", "c")
        contract = _build_force_kill_contract(spec, "LAW: Test law")
        # Re-serialize to prove it's valid.
        MoatVerificationContract.model_validate(contract.model_dump())
        assert contract.verdict_declaration.status == "KILL"


# ── Pivot Force-Mutation ─────────────────────────────────────────────────


class TestPivotForceMutation:
    """Prove the Tribunal force-mutates PIVOT → KILL after 2 pivots."""

    def test_force_kill_mutates_contract_in_memory(self):
        tribunal = TribunalMiddleware()
        journey = CandidateJourney(spec_id="abc", pivot_count=2)
        raw = _valid_llm_response(
            status="PIVOT", axis="CORE_FEATURE", generator_prompt="Change feature."
        )
        contract = tribunal.audit_payload(raw, journey)
        # The contract returned should have status=KILL, not PIVOT.
        assert contract.verdict_declaration.status == "KILL"
        # The law must contain the spec ID.
        assert "abc" in (contract.verdict_declaration.new_ledger_law or "")
        # Pivot payload must be cleared.
        assert contract.verdict_declaration.pivot_payload is None

    def test_force_kill_writes_to_ledger(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            ledger_path = f.name
        try:
            tribunal = TribunalMiddleware(ledger_path=ledger_path)
            journey = CandidateJourney(spec_id="xyz", pivot_count=3)
            raw = _valid_llm_response(
                status="PIVOT", axis="CORE_FEATURE", generator_prompt="Change feature."
            )
            tribunal.audit_payload(raw, journey)
            content = Path(ledger_path).read_text()
            assert "xyz" in content
            assert "LAW:" in content
        finally:
            os.unlink(ledger_path)

    def test_first_pivot_allowed_second_allowed_third_killed(self):
        """0 pivots → PIVOT ok. 1 pivot → PIVOT ok. 2 pivots → force KILL."""
        tribunal = TribunalMiddleware()
        for pivot_count, expect_kill in [(0, False), (1, False), (2, True), (3, True)]:
            journey = CandidateJourney(spec_id=f"test-{pivot_count}", pivot_count=pivot_count)
            raw = _valid_llm_response(
                status="PIVOT", axis="CORE_FEATURE", generator_prompt="Change the feature."
            )
            contract = tribunal.audit_payload(raw, journey)
            if expect_kill:
                assert contract.verdict_declaration.status == "KILL", f"pivot_count={pivot_count} should force KILL"
            else:
                assert contract.verdict_declaration.status == "PIVOT", f"pivot_count={pivot_count} should allow PIVOT"


# ── Ledger Injection into Prompts ────────────────────────────────────────


class TestLedgerInjection:
    """Prove the durable ledger is read and injected into prompts."""

    def test_ledger_appears_in_verifier_prompt(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("* LAW: Never build a middleman wrapper.\n")
            f.write("* LAW: No two-sided marketplaces.\n")
            ledger_path = f.name
        try:
            with patch.dict(os.environ, {"PROSPECTOR_LEDGER_PATH": ledger_path}):
                spec = CandidateSpec("b1", "f", "a", "Test concept")
                prompt = compile_system_prompt(spec)
                assert "LAW: Never build a middleman wrapper" in prompt
                assert "LAW: No two-sided marketplaces" in prompt
                assert "DURABLE LEDGER" in prompt
        finally:
            os.unlink(ledger_path)

    def test_ledger_appears_in_generator_prompt(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("* LAW: No middleman wrappers.\n")
            ledger_path = f.name
        try:
            with patch.dict(os.environ, {"PROSPECTOR_LEDGER_PATH": ledger_path}):
                prompt = compile_generator_system_prompt(
                    signal_text="AI for SMB",
                    structural_form="vertical_tool",
                    target_audience="smb_owner",
                )
                assert "LAW: No middleman wrappers" in prompt
                assert "HISTORICAL CONSTRAINTS" in prompt
        finally:
            os.unlink(ledger_path)

    def test_empty_ledger_returns_placeholder(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Just a header, no laws\n")
            ledger_path = f.name
        try:
            with patch.dict(os.environ, {"PROSPECTOR_LEDGER_PATH": ledger_path}):
                result = _load_ledger()
                assert "no ledger laws recorded yet" in result
        finally:
            os.unlink(ledger_path)

    def test_ledger_missing_file_returns_placeholder(self):
        with patch.dict(os.environ, {"PROSPECTOR_LEDGER_PATH": "/nonexistent/path.md"}):
            result = _load_ledger()
            assert "no ledger laws recorded yet" in result


# ── Short-Circuit Instruction in Prompt ──────────────────────────────────


class TestShortCircuitInstruction:
    """Prove the prompt explicitly instructs the LLM to short-circuit."""

    def test_short_circuit_text_in_verifier_prompt(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        prompt = compile_system_prompt(spec)
        assert "SHORT_CIRCUITED" in prompt
        assert "Verdict block" in prompt
        assert "Gate 1 through Gate 5 IN ORDER" in prompt

    def test_retry_prompt_contains_error_message(self):
        prompt = compile_retry_prompt("LAZY_TOKEN_GENERATION: too brief")
        assert "LAZY_TOKEN_GENERATION" in prompt
        assert "failed validation" in prompt
        assert "gate_1_legality" in prompt  # field name guidance


# ── Disk Commit Sanitisation ──────────────────────────────────────────────


class TestDiskCommitSanitisation:
    """Prove the ledger disk commit strips dangerous characters."""

    def test_special_chars_stripped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            ledger_path = f.name
        try:
            tribunal = TribunalMiddleware(ledger_path=ledger_path)
            journey = CandidateJourney(spec_id="abc")
            raw = _valid_llm_response(
                status="KILL",
                law="LAW: No @#$% markdown [links](http://evil) or <script> tags!",
            )
            tribunal.audit_payload(raw, journey)
            content = Path(ledger_path).read_text()
            final_line = content.split("*")[-1]
            # Chars stripped by sanitizer: @ # $ % ^ & * ( ) [ ] { } < > ! / \ + = | ?
            assert "@" not in final_line
            assert "(" not in final_line
            assert "<" not in final_line
            assert "!" not in final_line
            # Alphanumeric, spaces, periods, commas, colons, hyphens SURVIVE.
            # http:evil survives because all those chars are in the allowed set.
            assert "LAW:" in content
        finally:
            os.unlink(ledger_path)


# ── Schema Field Order ───────────────────────────────────────────────────


class TestSchemaFieldOrder:
    """Prove the moat contract field order matches the spec exactly."""

    def test_gate_order_in_gate_evaluations(self):
        fields = list(MoatVerificationContract.model_fields.keys())
        assert fields == [
            "ledger_audit",
            "gate_evaluations",
            "adversarial_attack",
            "verdict_declaration",
        ]

    def test_verdict_declaration_fields(self):
        from prospector.pipeline.moat_contract import VerdictDeclaration
        fields = list(VerdictDeclaration.model_fields.keys())
        assert fields == ["status", "pivot_payload", "new_ledger_law"]


# ── Verifier Journey State Transitions ────────────────────────────────────


class TestVerifierJourneyTransitions:
    """Prove the verifier correctly transitions journey state."""

    def test_proceed_sets_pass(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        journey = CandidateJourney(spec_id=spec.id)
        llm = MagicMock(return_value=_valid_proceed_response())
        run_moat(spec, journey, llm)
        assert journey.status == "PASS"

    def test_pivot_sets_pivoted_and_increments_count(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        journey = CandidateJourney(spec_id=spec.id)
        llm = MagicMock(return_value=_valid_llm_response(
            status="PIVOT", axis="PRICING_MODEL", generator_prompt="Switch pricing."
        ))
        run_moat(spec, journey, llm)
        assert journey.status == "PIVOTED"
        assert journey.pivot_count == 1

    def test_kill_sets_kill(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        journey = CandidateJourney(spec_id=spec.id)
        llm = MagicMock(return_value=_valid_llm_response(status="KILL"))
        run_moat(spec, journey, llm)
        assert journey.status == "KILL"

    def test_vetting_started_event_logged(self):
        spec = CandidateSpec("b1", "f", "a", "c")
        journey = CandidateJourney(spec_id=spec.id)
        llm = MagicMock(return_value=_valid_proceed_response())
        run_moat(spec, journey, llm)
        assert journey.audit_log[0]["stage"] == "VETTING_STARTED"

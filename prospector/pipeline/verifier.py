"""Sequential Short-Circuiting Moat Verifier (Stage 6).

The v2 Moat evaluates gates 1→5 in order.  The moment a gate flips
fatal_flaw=true, the LLM is instructed to short-circuit: fill downstream
gates with "SHORT_CIRCUITED" and jump to the verdict block.

The Tribunal middleware validates every response.  On schema failure,
retry up to 2 times with the error message injected.  On third failure,
force KILL and write a law.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from prospector.domain.primitives import CandidateJourney, CandidateSpec
from prospector.pipeline.middleware import TribunalMiddleware
from prospector.pipeline.moat_contract import MoatVerificationContract
from prospector.pipeline.moat_prompts import (
    compile_retry_prompt,
    compile_system_prompt,
)

logger = logging.getLogger(__name__)

# Max retries before force-KILL.
_MAX_RETRIES = 2


def run_moat(
    spec: CandidateSpec,
    journey: CandidateJourney,
    llm_call: Callable[[str, str], str],
    tribunal: Optional[TribunalMiddleware] = None,
) -> MoatVerificationContract:
    """Run the sequential short-circuiting moat for one spec.

    Args:
        spec: The frozen candidate spec.
        journey: The mutable journey (status updated in-place).
        llm_call: Function (system_prompt, user_prompt) -> raw LLM response string.
        tribunal: TribunalMiddleware instance (created if None).

    Returns:
        The validated MoatVerificationContract.

    On persistent schema failure after max retries, force-KILLs the journey
    and writes a synthetic law to the ledger.
    """
    if tribunal is None:
        tribunal = TribunalMiddleware()

    system = compile_system_prompt(spec)
    user = ""  # v2 puts everything in the system prompt.

    journey.append_event("VETTING_STARTED", {"spec_id": spec.id})
    journey.status = "VETTING"

    for attempt in range(_MAX_RETRIES + 1):
        try:
            raw = llm_call(system, user)
            contract = tribunal.audit_payload(raw, journey)
            verdict = contract.verdict_declaration

            # Apply the verdict to the journey.
            if verdict.status == "PROCEED":
                journey.status = "PASS"
                journey.append_event("VERDICT_PASS", {
                    "attempt": attempt + 1,
                })
            elif verdict.status == "PIVOT":
                journey.pivot_count += 1
                journey.status = "PIVOTED"
                journey.append_event("VERDICT_PIVOT", {
                    "attempt": attempt + 1,
                    "pivot_count": journey.pivot_count,
                    "axis": verdict.pivot_payload.axis if verdict.pivot_payload else None,
                })
            elif verdict.status == "KILL":
                journey.status = "KILL"
                journey.append_event("VERDICT_KILL", {
                    "attempt": attempt + 1,
                    "law": verdict.new_ledger_law,
                })

            return contract

        except ValueError as e:
            error_msg = str(e)
            logger.warning(
                "[TRIBUNAL BREAKER] Moat attempt %d/%d failed for Spec %s: %s",
                attempt + 1, _MAX_RETRIES + 1, spec.id, error_msg)
            journey.append_event("TRIBUNAL_REJECT", {
                "attempt": attempt + 1,
                "error": error_msg,
            })

            if attempt < _MAX_RETRIES:
                # Retry: inject the error into a new user prompt.
                user = compile_retry_prompt(error_msg)
            else:
                # Exhausted retries — force KILL.
                logger.error(
                    "[TRIBUNAL BREAKER] Moat exhausted %d retries for Spec %s — force KILL",
                    _MAX_RETRIES + 1, spec.id)
                journey.status = "KILL"
                law = (f"LAW: Do not generate concepts related to [{spec.id}] "
                       f"— failed moat schema validation {_MAX_RETRIES + 1} times.")
                journey.append_event("FORCE_KILL", {
                    "reason": f"Schema validation failed {_MAX_RETRIES + 1} times",
                    "last_error": error_msg,
                    "law": law,
                })
                # Commit the synthetic law.
                tribunal._commit_law(law, spec.id)
                # Build a minimal contract carrying the force-KILL.
                return _build_force_kill_contract(spec, law)


def _build_force_kill_contract(
    spec: CandidateSpec,
    law: str,
) -> MoatVerificationContract:
    """Build a minimal MoatVerificationContract for a force-KILL after retry exhaustion."""
    from prospector.pipeline.moat_contract import (
        GateDistribution,
        GateEvaluations,
        GateIncumbency,
        GateLegality,
        GatePayerSolvency,
        GateValueDurability,
        LedgerAudit,
        VerdictDeclaration,
    )
    return MoatVerificationContract(
        ledger_audit=LedgerAudit(violates_known_laws=False),
        gate_evaluations=GateEvaluations(
            gate_1_legality=GateLegality(regulatory_body="NONE", fatal_flaw=False),
            gate_2_payer_solvency=GatePayerSolvency(
                existing_line_item_budget="SHORT_CIRCUITED", fatal_flaw=False,
            ),
            gate_3_distribution=GateDistribution(
                unpaid_acquisition_wedge="SHORT_CIRCUITED", fatal_flaw=False,
            ),
            gate_4_incumbency=GateIncumbency(
                named_competitors=["SHORT_CIRCUITED"],
                differentiation_proof="SHORT_CIRCUITED",
                fatal_flaw=False,
            ),
            gate_5_value_durability=GateValueDurability(
                why_not_a_vitamin="SHORT_CIRCUITED", fatal_flaw=False,
            ),
        ),
        adversarial_attack=f"Failed moat schema validation: {spec.id}",
        verdict_declaration=VerdictDeclaration(
            status="KILL",
            new_ledger_law=law,
        ),
    )

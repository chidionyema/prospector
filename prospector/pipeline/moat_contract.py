"""Hostage Output Schema — Pydantic v2 structured-output contracts.

The LLM MUST return JSON matching MoatVerificationContract.  The field ORDER
is a security feature: the model is forced to evaluate gates sequentially,
and the Tribunal validates structural integrity before any ruling is trusted.

Every gate carries a `fatal_flaw: bool`.  The moment a gate flips to True,
the LLM is instructed (via the prompt in moat_prompts.py) to fill downstream
gate fields with the sentinel "SHORT_CIRCUITED" and jump to the verdict block.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Ledger audit (runs BEFORE the gates — pre-existing kill reasons) ───────


class LedgerAudit(BaseModel):
    model_config = ConfigDict(strict=True)
    violates_known_laws: bool
    cited_law_number: Optional[str] = Field(
        None,
        description="Must cite exact Ledger rule if violated, else null",
    )


# ── Gate 1–5 (kill-fast order) ────────────────────────────────────────────


class GateLegality(BaseModel):
    model_config = ConfigDict(strict=True)
    regulatory_body: str = Field(
        description="Name specific regulatory body (e.g. FINRA, FDA, OSHA) or 'NONE'",
    )
    fatal_flaw: bool


class GatePayerSolvency(BaseModel):
    model_config = ConfigDict(strict=True)
    existing_line_item_budget: str = Field(
        description="Name specific software/tool this demographic currently pays for",
    )
    fatal_flaw: bool


class GateDistribution(BaseModel):
    model_config = ConfigDict(strict=True)
    unpaid_acquisition_wedge: str = Field(
        description="Specific non-ads wedge (e.g., specific trade show, directory to scrape)",
    )
    fatal_flaw: bool


class GateIncumbency(BaseModel):
    model_config = ConfigDict(strict=True)
    named_competitors: List[str] = Field(
        description="Verbatim names of top 2 competitors, or ['NONE']",
    )
    differentiation_proof: str = Field(
        description="Why the incumbent cannot copy this in a weekend",
    )
    fatal_flaw: bool


class GateValueDurability(BaseModel):
    model_config = ConfigDict(strict=True)
    why_not_a_vitamin: str = Field(
        description="Why this is an existential pain, not a nice-to-have",
    )
    fatal_flaw: bool


# ── Gate bundle (ordered Gate 1 → Gate 5) ──────────────────────────────────


class GateEvaluations(BaseModel):
    model_config = ConfigDict(strict=True)
    gate_1_legality: GateLegality
    gate_2_payer_solvency: GatePayerSolvency
    gate_3_distribution: GateDistribution
    gate_4_incumbency: GateIncumbency
    gate_5_value_durability: GateValueDurability


# ── PIVOT payload (actionable instructions for the generator) ──────────────


class PivotPayload(BaseModel):
    model_config = ConfigDict(strict=True)
    axis: Literal["TARGET_AUDIENCE", "PRICING_MODEL", "CORE_FEATURE"]
    generator_prompt: str = Field(
        description="Actionable prompt to fix the fatal flaw in the next generation loop",
    )


# ── Verdict (the final ruling) ─────────────────────────────────────────────


class VerdictDeclaration(BaseModel):
    model_config = ConfigDict(strict=True)
    status: Literal["PROCEED", "PIVOT", "KILL"]
    pivot_payload: Optional[PivotPayload] = Field(
        None,
        description="Required if status == PIVOT",
    )
    new_ledger_law: Optional[str] = Field(
        None,
        description="If KILL, write a generalized 'LAW: Do not...' rule",
    )


# ── MASTER SCHEMA ──────────────────────────────────────────────────────────


class MoatVerificationContract(BaseModel):
    """THE MASTER SCHEMA: Pass MoatVerificationContract.model_json_schema() to
    the LLM SDK as the structured-output contract."""
    model_config = ConfigDict(strict=True)
    ledger_audit: LedgerAudit
    gate_evaluations: GateEvaluations
    adversarial_attack: str = Field(
        description="Mandatory 2-sentence explanation of how this business dies.",
    )
    verdict_declaration: VerdictDeclaration

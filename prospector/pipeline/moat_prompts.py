"""Deterministic prompt compilers for the v2 Moat.

Every prompt is built from the CandidateSpec + the durable ledger — no
randomness, no LLM query-gen for the gates.  The gates use templated
disconfirming queries; the only LLM work is ruling on the fetched passages.
"""
from __future__ import annotations

import json
from typing import Optional

from prospector.domain.primitives import CandidateSpec
from prospector.pipeline.middleware import default_ledger_path
from prospector.pipeline.moat_contract import MoatVerificationContract


def _load_ledger(max_lines: int = 15) -> str:
    """Read the last `max_lines` non-empty bullet points from the ledger.

    Resolves the path per call via middleware.default_ledger_path() — one definition
    shared with the writer, so a redirected ledger is read AND written in the same place.
    """
    ledger = default_ledger_path()
    if not ledger.exists():
        return "(no ledger laws recorded yet)"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    bullets = [ln.strip() for ln in lines if ln.strip().startswith("*")]
    recent = bullets[-max_lines:] if len(bullets) > max_lines else bullets
    if not recent:
        return "(no ledger laws recorded yet)"
    return "\n".join(recent)


def compile_system_prompt(spec: CandidateSpec) -> str:
    """Build the system prompt for the v2 Moat verifier.

    Injects the CandidateSpec fields, the durable ledger, and the
    sequential short-circuiting instruction.
    """
    ledger = _load_ledger()
    # Compact field reference — the full model_json_schema() is too verbose for the prompt.
    schema_ref = """{
  "ledger_audit": {
    "violates_known_laws": <bool>,
    "cited_law_number": <string or null>
  },
  "gate_evaluations": {
    "gate_1_legality": {
      "regulatory_body": <string, e.g. "FINRA" or "NONE">,
      "fatal_flaw": <bool>
    },
    "gate_2_payer_solvency": {
      "existing_line_item_budget": <string>,
      "fatal_flaw": <bool>
    },
    "gate_3_distribution": {
      "unpaid_acquisition_wedge": <string>,
      "fatal_flaw": <bool>
    },
    "gate_4_incumbency": {
      "named_competitors": [<string>, <string>],
      "differentiation_proof": <string, 40+ chars if PROCEED>,
      "fatal_flaw": <bool>
    },
    "gate_5_value_durability": {
      "why_not_a_vitamin": <string>,
      "fatal_flaw": <bool>
    }
  },
  "adversarial_attack": <string, exactly 2 sentences>,
  "verdict_declaration": {
    "status": "PROCEED" | "PIVOT" | "KILL",
    "pivot_payload": {
      "axis": "TARGET_AUDIENCE" | "PRICING_MODEL" | "CORE_FEATURE",
      "generator_prompt": <string>
    } or null,
    "new_ledger_law": <string starting with "LAW:"> or null
  }
}"""

    return f"""You are the Prospector v2.0 Verification Moat — a stateful evolutionary engine.

Your task: evaluate ONE candidate idea through 5 sequential gates.  You must
evaluate Gate 1 through Gate 5 IN ORDER.  The moment a Gate results in
`fatal_flaw: true`, you are instructed to fill the remaining downstream gate
assessment strings with the exact placeholder text 'SHORT_CIRCUITED' and jump
instantly to the Verdict block.  Never evaluate a gate that has been short-
circuited by an earlier fatal flaw.

────────────────────────────────────────────────────────────
CANDIDATE UNDER REVIEW
────────────────────────────────────────────────────────────
Title / Core Concept: {spec.core_concept_prose}
Structural Form:      {spec.structural_form}
Target Audience:      {spec.target_audience}
Spec ID:              {spec.id}
────────────────────────────────────────────────────────────

────────────────────────────────────────────────────────────
DURABLE LEDGER (Pre-existing kill laws)
────────────────────────────────────────────────────────────
{ledger}
────────────────────────────────────────────────────────────

────────────────────────────────────────────────────────────
REQUIRED JSON OUTPUT — use EXACTLY these field names:
────────────────────────────────────────────────────────────
{schema_ref}

LEDGER AUDIT (run FIRST, before any gate):
- Does this candidate violate any law in the ledger above?
- If yes, set violates_known_laws=true and cite the exact law.

GATE 1 — LEGALITY:
- Is this concept regulated by a specific body (FINRA, FDA, OSHA, FCA, etc.)?
- If yes, does the concept require a licence, accreditation, or regulatory
  approval that a solo founder cannot reasonably obtain?
- If it requires breaking any law or platform ToS, it is dead.

GATE 2 — PAYER SOLVENCY:
- Name a specific software/tool/service this target demographic CURRENTLY pays
  for that proves they have budget for this category.
- If no existing line-item budget exists, they won't pay for this.

GATE 3 — DISTRIBUTION:
- Identify a SPECIFIC unpaid acquisition wedge (not "SEO" or "content marketing").
  Name an actual trade show, directory, community, or platform where these buyers
  already congregate.
- If no such wedge exists, distribution is fatal.

GATE 4 — INCUMBENCY:
- Name the top 2 competitors verbatim.  If none exist, write ["NONE"].
- Explain in 40+ characters why an incumbent cannot copy this in a weekend
  (switching cost, proprietary data, network effect, captive channel, licence).

GATE 5 — VALUE DURABILITY:
- Is this an existential pain (the buyer MUST solve it) or a vitamin
  (nice-to-have)?
- If it's a vitamin, it's dead.  Painkillers survive.

ADVERSARIAL ATTACK (mandatory, always run):
- In exactly 2 sentences, explain how this business dies.  Be ruthlessly honest.
  What is the single most likely failure mode?

VERDICT:
- PROCEED: all 5 gates pass with fatal_flaw=false AND differentiation is provable.
- PIVOT: one gate has a fatal flaw that is FIXABLE by changing the target
  audience, pricing model, or core feature.  Provide an actionable pivot prompt.
- KILL: fatal and unfixable — write a LAW: rule for the ledger.
"""


def compile_retry_prompt(error_message: str) -> str:
    """Build the retry message when the Tribunal rejects a response."""
    return (
        f"Your previous attempt failed validation with error: {error_message}. "
        "Correct the output and resubmit. Critical: use the EXACT field names from "
        "the schema — gate_1_legality (not 'gate1'), named_competitors (not "
        "'competitors'), existing_line_item_budget (not 'existing_budget_item'), "
        "unpaid_acquisition_wedge (not 'acquisition_wedge'), why_not_a_vitamin "
        "(not 'is_painkiller'), differentiation_proof (not 'why_not_copyable'). "
        "adversarial_attack must be a STRING, not an object. "
        "verdict_declaration.status is the field, not 'verdict'."
    )


def compile_generator_system_prompt(
    signal_text: str,
    structural_form: str,
    target_audience: str,
) -> str:
    """Build the generator system prompt with ledger amnesia cure.

    Injects the last 15 ledger laws so the generator never proposes a concept
    that has already been mathematically proven to fail.
    """
    ledger = _load_ledger()

    return f"""You are the Prospector v2.0 Divergent Alpha Ideation Engine.

Generate ONE specific, concrete business idea matching the constraints below.

────────────────────────────────────────────────────────────
SIGNAL / OPPORTUNITY SPACE
────────────────────────────────────────────────────────────
{signal_text}
────────────────────────────────────────────────────────────

────────────────────────────────────────────────────────────
STRUCTURAL FORM
────────────────────────────────────────────────────────────
{structural_form}
────────────────────────────────────────────────────────────

────────────────────────────────────────────────────────────
TARGET AUDIENCE
────────────────────────────────────────────────────────────
{target_audience}
────────────────────────────────────────────────────────────

────────────────────────────────────────────────────────────
HISTORICAL CONSTRAINTS (THE LEDGER)
────────────────────────────────────────────────────────────
The following concepts have been mathematically proven to fail our investment
thesis. You are strictly forbidden from generating any Candidate concepts that
violate these laws:
{ledger}
────────────────────────────────────────────────────────────

Return ONLY valid JSON. No prose, no code fences.
"""

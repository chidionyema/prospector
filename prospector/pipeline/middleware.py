"""Defensive Middleware — the Python "Tribunal".

Every LLM response passes through TribunalMiddleware.audit_payload() before
it becomes a ruling.  Four hard checks enforce structural integrity:

  1. SCHEMA TRAP     — invalid JSON / schema mismatch → ValueError
  2. EMPTY PROOF     — PROCEED without real evidence → ValueError
  3. PIVOT LIMITER   — max 2 pivots; defective payload → ValueError / force-KILL
  4. DISK COMMIT     — KILL with a LAW: rule → append to durable ledger
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from prospector.domain.primitives import CandidateJourney
from prospector.pipeline.moat_contract import MoatVerificationContract

logger = logging.getLogger(__name__)

# Ledger path relative to repo root. NOT read directly — go through
# default_ledger_path() so the override below can bite.
_REPO_LEDGER = Path(__file__).resolve().parents[2] / "storage" / "durable_ledger.md"

# Env override, honoured at CALL time.
_LEDGER_ENV = "PROSPECTOR_LEDGER_PATH"


def default_ledger_path() -> Path:
    """Resolve the durable-ledger path, honouring $PROSPECTOR_LEDGER_PATH.

    Deliberately a function, not a module constant. A constant binds at IMPORT, which is
    before any pytest fixture can redirect it, so `monkeypatch.setenv` would be a silent
    no-op — the exact defect that let the test suite append 1196 fixture `LAW:` lines to
    the production `storage/durable_ledger.md` and get them committed. Those laws are fed
    back into every generator and verifier prompt (moat_prompts._load_ledger), so the
    pollution does not just sit in a log: it constrains what the engine is allowed to
    propose. Same family as audit.py's `_AUDIT_DIR`; resolved here at call time so the
    env var is sufficient on its own.
    """
    override = os.environ.get(_LEDGER_ENV)
    return Path(override) if override else _REPO_LEDGER

# Sentinel values the LLM uses when short-circuiting.
_SHORT_CIRCUITED_SENTINEL = "SHORT_CIRCUITED"


class TribunalMiddleware:
    """Validates LLM responses and enforces pipeline invariants."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else default_ledger_path()

    # ── public entry point ─────────────────────────────────────────────

    def audit_payload(
        self,
        raw_llm_json_str: str,
        journey: CandidateJourney,
    ) -> MoatVerificationContract:
        """Run all 4 Tribunal checks.  Returns the validated contract on success.
        Raises ValueError on any breach (caller retries or force-KILLs)."""
        spec_id = journey.spec_id

        # ── CHECK 1: Schema Trap ──────────────────────────────────────
        try:
            contract = MoatVerificationContract.model_validate_json(raw_llm_json_str)
        except Exception as e:
            logger.warning(
                "[TRIBUNAL BREAKER] MALFORMED_SCHEMA on Spec %s: %s", spec_id, e)
            raise ValueError(f"MALFORMED_SCHEMA: {e}") from e

        verdict = contract.verdict_declaration

        # ── CHECK 2: Empty Proof Trap (PROCEED requires evidence) ─────
        if verdict.status == "PROCEED":
            self._enforce_proceed_evidence(contract, spec_id)

        # ── CHECK 3: Pivot Limiter ─────────────────────────────────────
        if verdict.status == "PIVOT":
            self._enforce_pivot_limits(contract, journey, spec_id)

        # ── CHECK 4: Disk Commit (KILL with LAW:) ──────────────────────
        if verdict.status == "KILL" and verdict.new_ledger_law:
            if verdict.new_ledger_law.startswith("LAW:"):
                self._commit_law(verdict.new_ledger_law, spec_id)

        return contract

    # ── private enforcement methods ────────────────────────────────────

    def _enforce_proceed_evidence(
        self, contract: MoatVerificationContract, spec_id: str,
    ) -> None:
        """PROCEED must name real competitors with a substantive differentiation proof."""
        incumbency = contract.gate_evaluations.gate_4_incumbency

        # Differentiation proof must be substantive.
        proof = incumbency.differentiation_proof.strip()
        if len(proof) < 40:
            logger.warning(
                "[TRIBUNAL BREAKER] LAZY_TOKEN_GENERATION on Spec %s: "
                "differentiation_proof too brief (%d chars)", spec_id, len(proof))
            raise ValueError(
                "LAZY_TOKEN_GENERATION: Differentiation proof too brief.")

        # Must name real competitors.
        competitors = incumbency.named_competitors
        if (not competitors
                or competitors == ["NONE"]
                or competitors == ["none"]):
            logger.warning(
                "[TRIBUNAL BREAKER] UNCITED_INCUMBENCY on Spec %s: "
                "declared PROCEED without naming real competitors", spec_id)
            raise ValueError(
                "UNCITED_INCUMBENCY: Declared PROCEED without naming real competitors.")

    def _enforce_pivot_limits(
        self,
        contract: MoatVerificationContract,
        journey: CandidateJourney,
        spec_id: str,
    ) -> None:
        """Cap pivots at 2.  On third attempt, force KILL and write a law."""
        verdict = contract.verdict_declaration

        if journey.pivot_count >= 2:
            # Force-mutate the verdict in memory.
            verdict.status = "KILL"
            law = (f"LAW: Do not generate concepts related to [{spec_id}] "
                   f"after multiple failed wedge pivots.")
            verdict.new_ledger_law = law
            verdict.pivot_payload = None
            logger.warning(
                "[TRIBUNAL BREAKER] PIVOT_EXHAUSTED on Spec %s: "
                "%d pivots already attempted → force-KILL", spec_id, journey.pivot_count)
            # Commit the synthetic law immediately.
            self._commit_law(law, spec_id)
            return

        # Pivot must carry an actionable prompt.
        payload = verdict.pivot_payload
        if payload is None or not payload.generator_prompt.strip():
            logger.warning(
                "[TRIBUNAL BREAKER] DEFECTIVE_PIVOT on Spec %s: "
                "missing actionable generator_prompt", spec_id)
            raise ValueError(
                "DEFECTIVE_PIVOT: Missing actionable prompt.")

    def _commit_law(self, raw_law: str, spec_id: str) -> None:
        """Sanitize and append a LAW: rule to the durable ledger."""
        # Keep alphanumeric, spaces, periods, commas, colons, hyphens.
        sanitized = re.sub(r"[^a-zA-Z0-9 .,:\-]", "", raw_law)
        if not sanitized.strip():
            return
        line = f"\n* {sanitized.strip()}"
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(line)
            logger.info(
                "[TRIBUNAL] Committed law to ledger for Spec %s: %s",
                spec_id, sanitized[:80])
        except OSError as e:
            logger.error(
                "[TRIBUNAL BREAKER] Failed to write law to ledger for Spec %s: %s",
                spec_id, e)

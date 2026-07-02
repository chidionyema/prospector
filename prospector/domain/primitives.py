"""Domain Primitives: CandidateSpec (frozen) + CandidateJourney (mutable).

The God Object is dead.  A CandidateSpec is an immutable snapshot of what the
generator proposed.  A CandidateJourney carries mutable state (status, pivot
count, audit log) that evolves as the spec moves through the pipeline.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal

# ── CandidateSpec (FROZEN — never mutates after creation) ──────────────────


@dataclass(frozen=True)
class CandidateSpec:
    """Immutable record of a generated idea.  `id` is a deterministic SHA-256
    digest of the payload, truncated to 16 hex chars — identical payloads
    ALWAYS produce the same id, so duplicate generation is discoverable."""
    generation_batch_id: str
    structural_form: str
    target_audience: str
    core_concept_prose: str
    created_at: float = field(default_factory=lambda: time.time())

    # Set by __post_init__ — not a constructor argument.
    id: str = field(init=False)

    def __post_init__(self) -> None:
        payload = (
            f"{self.generation_batch_id}|{self.structural_form}|"
            f"{self.target_audience}|{self.core_concept_prose}|"
            f"{self.created_at}"
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        # Frozen dataclass requires object.__setattr__ to set init=False fields.
        object.__setattr__(self, "id", digest)


# ── CandidateJourney (MUTABLE — evolves through the pipeline) ──────────────


@dataclass
class CandidateJourney:
    """Mutable state machine tracking a CandidateSpec through the pipeline.

    `status` moves forward: PRESCREENED → VETTING → PIVOTED | KILL | PASS.
    `pivot_count` caps at 2 (Tribunal forces KILL on third pivot attempt).
    `audit_log` is an append-only list of timestamped stage events.
    """
    spec_id: str
    status: Literal["PRESCREENED", "VETTING", "PIVOTED", "KILL", "PASS"] = "PRESCREENED"
    pivot_count: int = 0
    audit_log: List[Dict[str, Any]] = field(default_factory=list)

    def append_event(self, stage_name: str, payload: Dict[str, Any]) -> None:
        """Append a timestamped record to the audit log."""
        self.audit_log.append({
            "ts": time.time(),
            "stage": stage_name,
            **payload,
        })

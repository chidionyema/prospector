"""Data contracts for Prospector.

These dataclasses ARE the future API resources (Part 15C): Dossier, Claim/Source,
Pack, etc. Keep them serialisable (to_dict / from_dict) so the same shapes flow from
the engine -> store -> (later) the read/commerce API with no translation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import hashlib
import json


class Verdict(str, Enum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNVERIFIABLE = "unverifiable"


class Decision(str, Enum):
    PASS = "pass"
    KILL = "kill"
    DEFER = "defer"   # could not be ruled on (retrieval/infra failure) — re-vet later, NOT a kill


# Sentinel "gate" used by verify() to signal a deferral (a decisive check could not be
# retrieved). build_dossier() maps it to Decision.DEFER — it is NOT a real kill gate.
DEFER_GATE = "retrieval_unavailable"


# The six universal kill-checks (Part 4). Order is the kill-fast evaluation order:
# cheapest/most-decisive gates first, stop at first hard fail.
CHECKS: dict[str, str] = {
    "pain_reality": "Real, acute problem/desire — people suffering or paying to solve it?",
    "value_durability": "Is the value real and durable — not fabricated, already commoditised, or evaporating?",
    "incumbency": "Does someone already solve this well (funded incumbent or dominant cheap option)?",
    "payer_solvency": "Does the payer have budget and motive (not a broke body, not a segment that won't pay)?",
    "distribution": "A low-friction route to the buyer (self-serve / forcing mechanism / existing channel)?",
    "legality": "Does the margin depend on breaking terms/law or falsifying a measurement?",
}

SCORE_AXES = ("pain_acuity", "money_provability", "automatability",
              "distribution", "defensibility", "build_feasibility")


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


@dataclass
class Source:
    """A retrieved, citable passage. The atom of grounding (source-or-die)."""
    source_id: str
    url: str
    text: str
    published_at: Optional[str] = None
    query: Optional[str] = None          # the query that surfaced it (audit)
    fetched_at: Optional[str] = None

    @staticmethod
    def make(url: str, text: str, published_at: Optional[str] = None,
             query: Optional[str] = None, fetched_at: Optional[str] = None) -> "Source":
        return Source(source_id=_id(url, text[:120]), url=url, text=text,
                      published_at=published_at, query=query, fetched_at=fetched_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    """A generated opportunity. Nothing is judged at generation (Part 3)."""
    title: str
    one_liner: str = ""
    hypothesis: str = ""
    who_pays: str = ""
    why_now: str = ""
    tags: dict[str, Any] = field(default_factory=dict)
    automatability: Any = None
    weak_monetisation: bool = False
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id:
            self.candidate_id = _id(self.title, self.one_liner)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Candidate":
        return Candidate(
            title=d.get("title", ""), one_liner=d.get("one_liner", ""),
            hypothesis=d.get("hypothesis", ""), who_pays=d.get("who_pays", ""),
            why_now=d.get("why_now", ""), tags=d.get("tags", {}) or {},
            automatability=d.get("automatability"),
            weak_monetisation=bool(d.get("weak_monetisation", False)),
            candidate_id=d.get("candidate_id", ""))


@dataclass
class CheckResult:
    """Verdict for one of the six checks, grounded in fetched passages."""
    check_name: str
    verdict: Verdict
    confidence: float
    rationale: str
    citations: list[str] = field(default_factory=list)   # source_ids
    sources: list[Source] = field(default_factory=list)  # the passages used
    queries: list[str] = field(default_factory=list)
    degraded: bool = False   # search/fetch failed -> forced unverifiable (Part 9)
    retrieval_failed: bool = False  # ALL searches for this check errored (infra/outage),
                                    # distinct from "searched and found nothing" — must
                                    # NEVER trip a kill gate; the candidate defers instead.

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


@dataclass
class AdversarialResult:
    kill_case: str
    decisive: bool
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    scores: dict[str, int]
    justification: dict[str, str]
    composite: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Dossier:
    """The full audit record for one candidate — PASS or KILL, both first-class.

    Carries everything needed to reproduce and dispute the decision (Part 8/9):
    prompts, model version, sources, verdicts.
    """
    candidate: Candidate
    decision: Decision
    gate_fired: Optional[str] = None        # which gate killed it (KILL only)
    reason: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    adversarial: Optional[AdversarialResult] = None
    score: Optional[ScoreResult] = None
    model_version: str = ""
    created_at: str = ""
    reverify_due_at: Optional[str] = None

    @property
    def all_sources(self) -> list[Source]:
        seen: dict[str, Source] = {}
        for c in self.checks:
            for s in c.sources:
                seen[s.source_id] = s
        return list(seen.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "decision": self.decision.value,
            "gate_fired": self.gate_fired,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
            "adversarial": self.adversarial.to_dict() if self.adversarial else None,
            "score": self.score.to_dict() if self.score else None,
            "model_version": self.model_version,
            "created_at": self.created_at,
            "reverify_due_at": self.reverify_due_at,
            "sources": [s.to_dict() for s in self.all_sources],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

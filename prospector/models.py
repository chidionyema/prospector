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


# The check VOCABULARY (questions). A check's role — hard-kill / score-only / off — and
# its bar are set per ambition LANE (config.lanes), not here: a durable-moat check is right
# for a unicorn candidate and wrong for a £30 side-hustle. The first six are the universal
# moat checks (the default/`venture` run set, DEFAULT_CHECKS below, in kill-fast order). The
# last four are the Stage-1 "pack-intent" checks the cheaper lanes (side_hustle/smb) judge
# on — demand and deliverability rather than moat. All are positively framed (a NO = the bad
# case → they kill on `refuted` when a lane makes them a hard gate).
CHECKS: dict[str, str] = {
    "pain_reality": "Real, acute problem/desire — people suffering or paying to solve it?",
    "value_durability": "Is the value real and durable — not fabricated, already commoditised, or evaporating?",
    "incumbency": "Is the space underserved (no dominant incumbent or funded rival already solving this well)?",
    "payer_solvency": "Does the payer have budget and motive (not a broke body, not a segment that won't pay)?",
    "distribution": "A low-friction route to the buyer (self-serve / forcing mechanism / existing channel)?",
    "legality": ("Is the margin lawful — achievable without breaking law/terms or "
                 "falsifying a measurement? A creative but lawful workaround — exploiting a "
                 "legitimate statutory mechanism or a permitted loophole — is NOT a fail; only "
                 "a margin that cannot exist without genuine illegality/breach counts."),
    # ---- Stage-1 pack-intent checks (cheaper lanes) ----
    "buyer_intent": ("Is there demonstrable buyer intent — are people actively searching for, "
                     "or already paying to solve, this RIGHT NOW (search demand, existing paid "
                     "alternatives, communities asking)? Commoditised demand is a YES, not a fail."),
    "route_to_market": ("Is there a real, beginner-followable route to reach paying buyers — a "
                        "channel a novice can actually execute (an open ad channel, a marketplace, "
                        "an existing audience) — not one requiring scarce expertise or blocked by a ban?"),
    "currency": ("Is this opportunity live and current right NOW — an active trend/regulation/need — "
                 "rather than a stale or already-peaked leftover from a previous year?"),
    "claims_verifiable": ("Can the core factual claims be checked against retrievable public sources "
                          "rather than merely asserted — and do the sources confirm rather than "
                          "contradict them?"),
}

# The default run set when no ambition lane is active (the original universal moat checks,
# in kill-fast order). Lanes declare their own run set via hard_gates + `score_checks`.
DEFAULT_CHECKS: tuple[str, ...] = ("pain_reality", "value_durability", "incumbency",
                                   "payer_solvency", "distribution", "legality")

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
    structural_form: str = ""   # the business FORM this idea was generated in (categorical)
    # Ambition TIER this idea is judged by (side_hustle / smb / growth / venture). Orthogonal
    # to packaging: the tier sets the vetting BAR; the £30 pack is downstream selling format.
    # Default "" = no lane engaged (today's single-default behaviour, back-compat).
    ambition_tier: str = ""
    # Optional audit trail of how the raw brainstormed idea was sharpened during the
    # refinement pass (list of {"before": {...}} snapshots). Purely additive observability
    # — never read by any gate; rendered in the dossier's "Generation Refinement" section.
    refinement_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.candidate_id:
            self.candidate_id = _id(self.title, self.one_liner)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Candidate":
        raw_tags = d.get("tags", {})
        if isinstance(raw_tags, list):
            tags = {str(t): True for t in raw_tags}
        else:
            tags = dict(raw_tags or {})
        # The generator's mandated durable-wedge declaration + commodity pre-mortem
        # (see prompts/generate.md). Carried in the free-form tags dict so they persist
        # into the dossier for observability without widening the Candidate contract.
        for k in ("durable_wedge_type", "commodity_premortem"):
            if d.get(k) is not None and k not in tags:
                tags[k] = d[k]
        # structural_form is a first-class categorical field. Back-compat: old dossiers
        # encoded it as a boolean tag key "form:<name>" — recover it if the field is absent.
        sform = str(d.get("structural_form", "") or "")
        if not sform:
            sform = next((str(k).split("form:", 1)[1] for k in tags
                          if str(k).startswith("form:")), "")
        return Candidate(
            title=d.get("title", ""), one_liner=d.get("one_liner", ""),
            hypothesis=d.get("hypothesis", ""), who_pays=d.get("who_pays", ""),
            why_now=d.get("why_now", ""), tags=tags,
            automatability=d.get("automatability"),
            weak_monetisation=bool(d.get("weak_monetisation", False)),
            candidate_id=d.get("candidate_id", ""),
            structural_form=sform,
            ambition_tier=str(d.get("ambition_tier", "") or ""),
            refinement_history=list(d.get("refinement_history") or []))


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
    # Which operator actually ran this check (e.g. "gemini/2.5-flash-lite" or
    # "minimax/MiniMax-M3").  Records the concrete model version used so the audit
    # trail shows exactly which brain ruled, not just the class name.
    provider: str = ""
    # True when this check was ruled by the cheap emergency fallback tail (deepseek/
    # minimax) because the trusted moat (Claude+Gemini) was exhausted. A provisional
    # ruling keeps throughput up but is NOT trusted as final: it never publishes on PASS
    # and is auto re-vetted by the moat on the next `vet --resume`.
    provisional: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["sources"] = [s.to_dict() for s in self.sources]
        return d


@dataclass
class AdversarialResult:
    kill_case: str
    decisive: bool
    confidence: float = 0.0  # Continuous decisiveness score [0..1]
    citations: list[str] = field(default_factory=list)
    # Which operator ran the adversarial pass (e.g. "claude/claude-opus-4-8").
    provider: str = ""
    # True when the adversarial pass was ruled by the cheap emergency fallback tail
    # (moat exhausted). Same semantics as CheckResult.provisional.
    provisional: bool = False

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
    # The concrete operator chain that ran the moat for this dossier.
    # Format: "claude/claude-opus → gemini/2.5-flash" or "minimax/MiniMax-M3".
    # Persisted so the audit trail shows exactly which brains were used, including
    # any failover steps when the primary moat was exhausted mid-run.
    provider_chain: str = ""
    created_at: str = ""
    reverify_due_at: Optional[str] = None
    # True when ANY decisive ruling in this dossier (the gate that fired, or — for a
    # survivor — any check / the adversarial pass) was served by the cheap emergency
    # fallback tail because the trusted moat was exhausted. A provisional dossier is a
    # real-but-untrusted decision: it never publishes on PASS and is auto re-vetted by
    # the moat on the next `vet --resume`.
    provisional: bool = False

    @property
    def dense_reward(self) -> float:
        """The Stage 1 continuous training signal: a single [0..1] float 
        representing the candidate's quality, even for kills.
        
        Formula: 
          - PASS: 0.8 + (0.2 * composite_score/6.0)
          - KILL: (sum(gate_confidences) / n_gates) * 0.5 
          - Penalty for early kills or adversarial decisive.
        """
        if self.decision == Decision.PASS:
            comp = self.score.composite if self.score else 3.0
            return round(0.8 + (0.2 * comp / 6.0), 3)
        
        if not self.checks:
            return 0.0
            
        # For kills, we average the confidences of the checks that ran.
        # This gives a 'partial credit' signal for ideas that cleared some gates.
        avg_conf = sum(c.confidence for c in self.checks) / len(self.checks)
        
        # Adversarial kill penalty: if it was killed by the critic, it's lower value.
        adv_penalty = 0.8 if self.adversarial and self.adversarial.decisive else 1.0
        
        return round(avg_conf * 0.5 * adv_penalty, 3)

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
            # Surface the tier at the top level too (not just nested in candidate) so the
            # catalogue / storefront can filter listings by ambition class without digging.
            "ambition_tier": self.candidate.ambition_tier,
            "decision": self.decision.value,
            "gate_fired": self.gate_fired,
            "reason": self.reason,
            "checks": [c.to_dict() for c in self.checks],
            "adversarial": self.adversarial.to_dict() if self.adversarial else None,
            "score": self.score.to_dict() if self.score else None,
            "model_version": self.model_version,
            "provider_chain": self.provider_chain,
            "created_at": self.created_at,
            "reverify_due_at": self.reverify_due_at,
            "provisional": self.provisional,
            "dense_reward": self.dense_reward,
            "sources": [s.to_dict() for s in self.all_sources],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

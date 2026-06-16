"""Typed config loader. The gates/weights/thresholds are DATA (Part 4/13A) so the
golden set can tune them without code changes."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Retrieval:
    # str (single provider) or list[str] (ordered failover chain, Part 9).
    provider: "str | list[str]" = "fixture"
    queries_per_check: int = 2
    results_per_query: int = 4
    max_passage_chars: int = 1500
    cache: bool = True
    # Checks that skip the LLM query-gen call and use deterministic disconfirming
    # templates instead (cheap decisive gates that kill most candidates).
    template_checks: list[str] = field(default_factory=list)
    fast_queries: int = 1  # query count used for template_checks
    # Model for the web-SEARCH/grounding step (distinct from the verdict `model`).
    # flash-lite returns 0 sources for many queries (poor grounding recall); the
    # mid-tier `gemini-2.5-flash` recalls far better and is still fast. Empty =>
    # fall back to model_fast/model. Verdict ruling still uses `model` (can stay -lite).
    search_model: str = ""
    # Web-grounding fail-fast budget. The free gemini web-search tool throttles after a
    # burst and then internally backs off for ~hours, which presents as a 240s hang. A
    # short timeout + few retries makes a throttled search GIVE UP quickly so the candidate
    # DEFERS (re-vet later) instead of blocking the whole run. Verdict calls (no web) are
    # unaffected — they use run_gemini_cli's normal timeout.
    search_timeout: int = 75            # base seconds per grounding web-search call (attempt 0)
    search_timeout_max: int = 150       # adaptive ceiling: timeout escalates per retry up to this
    search_timeout_escalation: float = 1.5  # multiply the timeout each retry (slow≠dead: give it room)
    search_retries: int = 1             # in-place retries before failing over to the next provider
    claude_min_timeout: int = 120       # claude grounding floor (its search is slower than gemini's)
    # Bounded work queue: a grounding call waits at most this long for a free provider
    # slot before giving up and failing over. Without this the semaphore wait was
    # UNBOUNDED and sat OUTSIDE the timeout, so a saturated provider could block a vet
    # indefinitely. Caps total latency at queue_timeout + search_timeout.
    queue_timeout: int = 45             # seconds to wait for a concurrency slot before failover
    # Physical load governors (decouple logical candidate concurrency from heavy CLI
    # subprocess load). Config is the single source of truth; PROSPECTOR_{GEMINI,CLAUDE}_
    # CONCURRENCY / PROSPECTOR_VET_WORKERS env vars still override for ops.
    gemini_concurrency: int = 2         # max concurrent gemini CLI subprocesses
    claude_concurrency: int = 2         # max concurrent claude CLI subprocesses
    vet_workers: int = 3                # candidates vetted in parallel; align to grounding slots
    # Circuit breaker (failover resilience). A provider is retired only after this many
    # CONSECUTIVE transient failures (or immediately on a quota wall), and recovers via a
    # half-open probe after the cooldown — never permanently dead-listed for the run.
    breaker_failure_threshold: int = 3  # consecutive transient fails before opening
    breaker_cooldown_s: float = 60.0    # seconds open before a half-open recovery probe


@dataclass
class Thresholds:
    confidence_floor: float = 0.6
    min_composite_to_pass: float = 3.2


@dataclass
class Spend:
    daily_cap_usd: float = 20.0
    warn_at_usd: float = 15.0


@dataclass
class Config:
    # str (single brain) or list[str] (ordered failover chain, Part 9).
    operator: "str | list[str]" = "mock"
    model: str = ""
    # Optional lighter model for mechanical calls (query-gen, prescreen). Empty
    # => reuse `model` (the CLI already auto-routes utility calls to flash).
    model_fast: str = ""
    model_version_tag: str = ""
    retrieval: Retrieval = field(default_factory=Retrieval)
    thresholds: Thresholds = field(default_factory=Thresholds)
    # hard_gates: list of single-key dicts, preserves kill-fast order
    hard_gates: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    # Ambition lanes (Part 14): the engine caters to the FULL spectrum — from £30
    # side-hustles to unicorn-potential ventures — by judging each candidate against the
    # bar appropriate to its OWN ambition class, not one universal filter. A lane overrides
    # hard_gates / thresholds / weights; the top-level fields above are the implicit default
    # (the `venture` moat behaviour). `active_lane` empty => default => byte-for-byte today.
    lanes: dict[str, Any] = field(default_factory=dict)
    active_lane: str = ""
    # Multi-lane-by-default: ONE run spans these tiers, each idea judged by its own bar
    # (a mixed-ambition catalogue, not a single tier). `active_lane` (singular) still pins
    # a single lane and OVERRIDES this. Empty active_lanes => single-default behaviour.
    active_lanes: list[str] = field(default_factory=list)
    # Candidates generated per tier per multi-lane run (fan-out for coverage).
    lane_quota: dict[str, int] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    # Generation PROFILES (Part 16 — targeted steering): a named, reusable bundle of
    # `generation` overrides (restricted structural_forms + a free-text `focus` directive)
    # that biases WHAT KIND of ideas are generated, without touching gates/thresholds. A
    # profile composes over any lane (it is re-applied after `for_lane` so its forms/focus
    # WIN over the lane's generation framing). `active_profile` empty => unchanged (today).
    profiles: dict[str, Any] = field(default_factory=dict)
    active_profile: str = ""
    listing: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    spend: Spend = field(default_factory=Spend)
    store: dict[str, Any] = field(default_factory=lambda: {"dir": "store"})

    @property
    def store_dir(self) -> Path:
        d = Path(self.store.get("dir", "store"))
        return d if d.is_absolute() else REPO_ROOT / d

    def gate_map(self) -> dict[str, list[str]]:
        """Flatten hard_gates to {gate_name: [killing_verdicts]} (excludes adversarial flag)."""
        out: dict[str, list[str]] = {}
        for g in self.hard_gates:
            for k, v in g.items():
                if k != "adversarial_decisive":
                    out[k] = list(v)
        return out

    @property
    def adversarial_decisive_kills(self) -> bool:
        for g in self.hard_gates:
            if "adversarial_decisive" in g:
                return bool(g["adversarial_decisive"])
        return True

    def for_lane(self, name: str | None) -> "Config":
        """Return a Config resolved to ambition lane `name`. A lane may override
        `hard_gates` (replaces, preserving kill-fast order), partially override
        `thresholds`, `weights` and `generation` (merged over the defaults). Unknown/empty
        name => unchanged (the default lane). The same shared machinery — retrieval,
        grounding, kill-fast, scoring — runs underneath; only the gate roles, bars, and
        (for cheaper lanes) the generation framing swap. The `generation` merge lets a lane
        reframe idea generation (e.g. side_hustle generates £30-pack niches, not venture
        moats) with no separate code path; an empty override leaves generation untouched."""
        if not name or name not in self.lanes:
            return self
        lane = self.lanes.get(name) or {}
        new_thresholds = self.thresholds
        if lane.get("thresholds"):
            new_thresholds = replace(self.thresholds, **lane["thresholds"])
        new_weights = {**self.weights, **(lane.get("weights") or {})}
        new_hard_gates = lane.get("hard_gates") or self.hard_gates
        new_generation = {**self.generation, **(lane.get("generation") or {})}
        resolved = replace(self, hard_gates=new_hard_gates, thresholds=new_thresholds,
                           weights=new_weights, generation=new_generation, active_lane=name)
        # A profile composes OVER the lane: re-apply it so its restricted forms / focus
        # directive win over the lane's generation framing. No-op when no profile active.
        if self.active_profile:
            resolved = resolved.for_profile(self.active_profile)
        return resolved

    def for_profile(self, name: str | None) -> "Config":
        """Return a Config with generation PROFILE `name` merged over `generation`.

        A profile is generation-only: it merges its `generation` override (e.g. a restricted
        `structural_forms` list + a free-text `focus` directive) on top of the current
        generation config and records `active_profile`. Gates, thresholds and weights are
        untouched — a profile steers what is GENERATED, never how strictly it is judged.
        Unknown/empty name => unchanged. Composes with lanes via `for_lane` (profile wins)."""
        if not name or name not in self.profiles:
            return self
        prof = self.profiles.get(name) or {}
        new_generation = {**self.generation, **(prof.get("generation") or {})}
        return replace(self, generation=new_generation, active_profile=name)


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else REPO_ROOT / "config.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    cfg = Config(
        operator=raw.get("operator", "mock"),
        model=raw.get("model", ""),
        model_fast=raw.get("model_fast", ""),
        model_version_tag=raw.get("model_version_tag", ""),
        retrieval=Retrieval(**(raw.get("retrieval") or {})),
        thresholds=Thresholds(**(raw.get("thresholds") or {})),
        hard_gates=raw.get("hard_gates") or [],
        weights=raw.get("weights") or {},
        lanes=raw.get("lanes") or {},
        active_lane=raw.get("active_lane") or "",
        active_lanes=raw.get("active_lanes") or [],
        lane_quota=raw.get("lane_quota") or {},
        generation=raw.get("generation") or {},
        profiles=raw.get("profiles") or {},
        active_profile=raw.get("active_profile") or "",
        listing=raw.get("listing") or {},
        schedule=raw.get("schedule") or {},
        spend=Spend(**(raw.get("spend") or {})),
        store=raw.get("store") or {"dir": "store"},
    )
    # Resolve the configured active lane (if any) into the operative gate/threshold/weight
    # fields. Empty active_lane => the top-level defaults stand unchanged (today's behaviour).
    # A config-pinned active_profile (if any) is applied too; for_lane re-applies it so it
    # composes correctly. Empty active_profile => generation untouched.
    if cfg.active_lane:
        return cfg.for_lane(cfg.active_lane)
    if cfg.active_profile:
        return cfg.for_profile(cfg.active_profile)
    return cfg

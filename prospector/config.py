"""Typed config loader. The gates/weights/thresholds are DATA (Part 4/13A) so the
golden set can tune them without code changes."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import os
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
    # confidence_floor: a killing verdict (refuted, or supported-for-incumbency) only
    # HARD-kills when its deterministic grounding confidence clears this floor; below it,
    # the candidate falls through to scoring instead of being killed at the gate. This is
    # the tunable lever for the value_durability over-restriction wall (war-room
    # 2026-06-15). DEFAULT 0.0 = inert (every grounded kill fires, golden-set safe). The
    # real launch value must be calibrated by re-running the 6 known good/bad controls
    # live under supervision (store/runs/control_experiment_*.log) — do NOT raise this
    # above 0 from a guess; the mock/fixture confidence scale (~0.4 flat) is not the live
    # scale. See docs/PIPELINE_REVIEW_2026-06-18.md (P0-2).
    confidence_floor: float = 0.0
    min_composite_to_pass: float = 3.2


@dataclass
class Spend:
    daily_cap_usd: float = 20.0
    warn_at_usd: float = 15.0


@dataclass
class ModelDefaults:
    """Per-provider default model identifiers. These are the *fallbacks* used
    when a provider is selected but `cfg.model` is empty. Setting
    `cfg.model = "..."` overrides these on a per-call basis (see
    `operator._build_operator`).

    Why this dataclass exists: model identifiers used to be hardcoded in
    each operator's `_DEFAULT_MODEL` strings. That coupled code to a moving
    target (provider rollouts, deprecations) and forced a code change +
    release for every model migration. Now they're config-driven — the
    `deepseek-chat` 2026-07-24 deprecation is a 1-line `config.yaml` change.

    The defaults below are the *historical* values (what the hardcoded
    strings used to be). If `config.yaml` is missing the `model_defaults`
    block, these defaults are used. `config.yaml`'s `model_defaults` block
    takes precedence.
    """
    # Operator defaults (one per provider kind, plus a `_fast` split for the
    # cheap/structured variant where it exists).
    gemini: str = "gemini-2.0-flash"
    claude: str = "claude-opus-4-8"
    deepseek: str = "deepseek-chat"
    minimax: str = "MiniMax-M3"        # full reasoning model
    minimax_fast: str = "MiniMax-M2.7"  # cheap/structured
    ollama: str = "qwen2.5-coder:7b"
    # Search provider defaults (the LLM that decomposes queries for the
    # function-calling search providers). One per search provider.
    search: dict[str, str] = field(default_factory=lambda: {
        "deepseek": "deepseek-chat",
        "minimax":  "MiniMax-M3",
    })


@dataclass
class PriceTier:
    """Per-token USD price for a provider."""
    input: float = 0.0
    output: float = 0.0


@dataclass
class Pricing:
    """Per-provider token pricing (USD per 1M tokens).

    Used by telemetry to estimate spend. Missing-provider lookups return
    PriceTier(0, 0) (free / unknown / not-priced-yet) with a warning log so
    spend is never silently wrong. The historical values from
    `telemetry.PRICING` are the defaults; `config.yaml`'s `pricing` block
    overrides them.
    """
    gemini: PriceTier = field(default_factory=lambda: PriceTier(0.10, 0.40))
    claude: PriceTier = field(default_factory=lambda: PriceTier(3.00, 15.00))
    deepseek: PriceTier = field(default_factory=lambda: PriceTier(0.27, 1.10))
    minimax: PriceTier = field(default_factory=lambda: PriceTier(0.30, 0.30))
    ollama: PriceTier = field(default_factory=lambda: PriceTier(0.00, 0.00))
    mock: PriceTier = field(default_factory=lambda: PriceTier(0.00, 0.00))


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
    # Personas (Part 16 principal refactor): Analytical multi-tenancy.
    # A persona provides analytical bias/voice for generation, verdict, and adversarial.
    personas: dict[str, Any] = field(default_factory=dict)
    active_persona: str = ""
    listing: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    spend: Spend = field(default_factory=Spend)
    store: dict[str, Any] = field(default_factory=lambda: {"dir": "store"})
    # Entitlements API key for the /entitlements check. Read from the
    # PROSPECTOR_ENTITLEMENTS_API_KEY env var at config load time. No default
    # — if unset, the entitlements check will fail clearly (fail-closed).
    entitlements_api_key: str = ""
    # Per-provider default model identifiers (see ModelDefaults docstring).
    # This is the canonical home for "what model does provider X use by default".
    # Operators / search providers consume this; the historical `_DEFAULT_MODEL`
    # strings in operator.py are GONE.
    model_defaults: ModelDefaults = field(default_factory=ModelDefaults)
    # Per-provider token pricing (USD per 1M tokens). Consumed by
    # `telemetry.get_price(provider)`; replaces the hardcoded `PRICING` dict.
    pricing: Pricing = field(default_factory=Pricing)

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
        # A persona also composes OVER the lane.
        if self.active_persona:
            resolved = resolved.for_persona(self.active_persona)
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
        resolved = replace(self, generation=new_generation, active_profile=name)
        # If we have an active persona, re-apply it so its generation_bias win.
        if self.active_persona:
            resolved = resolved.for_persona(self.active_persona)
        return resolved

    def for_persona(self, name: str | None) -> "Config":
        """Return a Config with persona `name` analytical bias applied.

        A persona can provide:
        - `generation_bias`: Injected into the generation system prompt.
        - `verdict_bias`: Injected into the verdict system prompt.
        - `adversarial_bias`: Injected into the adversarial system prompt.
        - `thresholds`: Persona-specific threshold tweaks.
        """
        if not name or name not in self.personas:
            return self
        persona = self.personas.get(name) or {}
        # Apply threshold overrides if any
        new_thresholds = self.thresholds
        if persona.get("thresholds"):
            new_thresholds = replace(self.thresholds, **persona["thresholds"])
        
        return replace(self, thresholds=new_thresholds, active_persona=name)


def _parse_model_defaults(raw_md: dict | None) -> ModelDefaults:
    """Parse the `model_defaults` block from config.yaml.

    The block is optional; if absent, the dataclass defaults are used (which
    match the historical hardcoded values for backwards compatibility).
    """
    if not raw_md:
        return ModelDefaults()
    # Split the operator defaults (top-level) from the search-provider defaults
    # (nested under `search:`). The shape mirrors ModelDefaults exactly.
    search = raw_md.get("search") or {}
    return ModelDefaults(
        gemini=raw_md.get("gemini", "gemini-2.0-flash"),
        claude=raw_md.get("claude", "claude-opus-4-8"),
        deepseek=raw_md.get("deepseek", "deepseek-chat"),
        minimax=raw_md.get("minimax", "MiniMax-M3"),
        minimax_fast=raw_md.get("minimax_fast", "MiniMax-M2.7"),
        ollama=raw_md.get("ollama", "qwen2.5-coder:7b"),
        search=search,
    )


def _parse_pricing(raw_pr: dict | None) -> Pricing:
    """Parse the `pricing` block from config.yaml. Per-provider
    {input: usd_per_1M_input, output: usd_per_1M_output}. Missing providers
    use the historical default (free / $0.00) — see Pricing docstring.
    """
    if not raw_pr:
        return Pricing()
    def _tier(d: dict | None, default: PriceTier) -> PriceTier:
        if not d:
            return default
        return PriceTier(
            input=float(d.get("input", default.input)),
            output=float(d.get("output", default.output)),
        )
    return Pricing(
        gemini=_tier(raw_pr.get("gemini"), Pricing().gemini),
        claude=_tier(raw_pr.get("claude"), Pricing().claude),
        deepseek=_tier(raw_pr.get("deepseek"), Pricing().deepseek),
        minimax=_tier(raw_pr.get("minimax"), Pricing().minimax),
        ollama=_tier(raw_pr.get("ollama"), Pricing().ollama),
        mock=_tier(raw_pr.get("mock"), Pricing().mock),
    )


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
        personas=raw.get("personas") or {},
        active_persona=raw.get("active_persona") or "",
        listing=raw.get("listing") or {},
        schedule=raw.get("schedule") or {},
        spend=Spend(**(raw.get("spend") or {})),
        store=raw.get("store") or {"dir": "store"},
        model_defaults=_parse_model_defaults(raw.get("model_defaults")),
        pricing=_parse_pricing(raw.get("pricing")),
        # Read entitlements_api_key from env var; config.yaml value takes precedence
        # over the env var when both are set (for testing/override).
        entitlements_api_key=(
            raw.get("entitlements_api_key")
            or os.environ.get("PROSPECTOR_ENTITLEMENTS_API_KEY", "")
        ),
    )
    # Resolve the configured active lane (if any) into the operative gate/threshold/weight
    # fields. Empty active_lane => the top-level defaults stand unchanged (today's behaviour).
    # A config-pinned active_profile (if any) is applied too; for_lane re-applies it so it
    # composes correctly. Empty active_profile => generation untouched.
    if cfg.active_lane:
        cfg = cfg.for_lane(cfg.active_lane)
    if cfg.active_profile:
        cfg = cfg.for_profile(cfg.active_profile)
    if cfg.active_persona:
        cfg = cfg.for_persona(cfg.active_persona)
    return cfg

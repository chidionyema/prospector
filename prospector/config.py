"""Typed config loader. The gates/weights/thresholds are DATA (Part 4/13A) so the
golden set can tune them without code changes."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Keys a market block may NEVER contain. A market configures the EVIDENCE TERRAIN
# (where to look, in what language, under whose authority) and the FRAMING — never the
# BAR. Only an ambition LANE moves the bar. Allowing a market to set these would make
# "open a low-evidence market by lowering its threshold" a one-line config edit, which
# is exactly the failure the two-loops rule forbids: demand never overrides truth.
MARKET_FORBIDDEN_KEYS = ("hard_gates", "thresholds", "weights")

_MARKET_STATUSES = ("open", "probing", "closed")


class MarketConfigError(ValueError):
    """The `markets:` block is malformed or attempts to move the bar."""


class UnknownMarketError(ValueError):
    """A market code was requested that is not defined in config.

    Deliberately louder than the unknown-LANE behaviour (`for_lane` returns self):
    silently running "us" as the UK default would stamp dossiers with a market whose
    evidence chain never ran — fabricated provenance. Fail closed instead.
    """


class UnknownArchetypeError(ValueError):
    """`operator_archetype` names a binding that is not defined under generation.archetypes."""


@dataclass
class Retrieval:
    # str (single provider) or list[str] (ordered failover chain, Part 9).
    provider: "str | list[str]" = "fixture"
    queries_per_check: int = 2
    results_per_query: int = 4
    max_passage_chars: int = 1500
    cache: bool = True
    # FETCH THE PAGE, don't rule on the search snippet (2026-08-13).
    # MEASURED over 11,857 grounding passages since 2026-08-08: mean 222 chars, median 217,
    # p90 281, and 94.7% under 300 — because `_resolve()` sends a HEAD and every provider
    # stores the search engine's ~220-char RESULT SNIPPET as the passage. `max_passage_chars`
    # (1500) has therefore never once bound. The verdict prompt already budgets 600 chars per
    # passage (`verify.VERDICT_PASSAGE_TRUNCATE`), so we were filling 37% of a budget that was
    # already there. 67.5% of checks ruled `unverifiable`, and grounding failures
    # (moat_ungrounded + source_or_die) became 54.6% of all kills.
    # Default OFF so fixtures, golden-set runs and any directly-constructed Retrieval() keep
    # their current byte-for-byte behaviour; config.yaml turns it on for the live engine.
    fetch_pages: bool = False
    fetch_timeout_s: float = 8.0        # per page; a slow page must not extend a vet
    fetch_max_workers: int = 8          # pages are fetched concurrently, like _resolve
    # Only REPLACE a snippet when the page yields materially more than we already had.
    # Without this a bot-walled page returning a 200 + "enable JavaScript" shim would
    # overwrite a genuinely informative snippet with less than it replaced.
    fetch_min_gain_chars: int = 400
    fetch_max_bytes: int = 400_000      # stop reading; some pages are tens of MB
    # RANK WHAT SEARCH RETURNED (2026-08-14). Every provider asks for exactly
    # `results_per_query` results and keeps the search engine's own first k, so relevance
    # was measured at the verdict (as `unverifiable`) and never enforced at the source.
    # MEASURED over the 450 passages written since the page-fetch fix: `supported` sources
    # contain 42.8% of their own query's content words, `unverifiable` sources 25.1%.
    # Re-running ten of the offending queries at max_results=10, the first 3 average 25.9%
    # coverage and the best 3 average 36.8%. `k * relevance_overfetch` results are fetched
    # (capped at the 10 every provider already caps at) and the best k kept.
    # Default 1 = OFF, a byte-for-byte no-op, so fixtures, the golden set and any directly
    # constructed Retrieval() keep their behaviour; config.yaml turns it on for the engine.
    relevance_overfetch: int = 1
    # DiskCache freshness: cached grounding passages older than this are treated as a
    # miss and re-fetched, so a verdict never rules on stale evidence. 0 disables expiry
    # (cache forever). Default 14 days — long enough to amortise repeat vets in a batch,
    # short enough that a re-vet weeks later re-grounds against the live page.
    cache_ttl_s: int = 1_209_600
    # Checks that skip the LLM query-gen call and use deterministic disconfirming
    # templates instead (cheap decisive gates that kill most candidates).
    template_checks: list[str] = field(default_factory=list)
    fast_queries: int = 1  # query count used for template_checks
    # BATCHED LLM query-gen (fast/non-critical tier). When True, verify() makes ONE
    # query_op call per candidate that decomposes the idea into real-world domain
    # queries for ALL checks at once (prompts/query_gen_batched.md), overriding the
    # deterministic templates. Proven necessary: deterministic _keywords restates the
    # product pitch ("productized transforms tenant answers adversarial") so search
    # returns off-topic junk (dictionary entries, whatsapp.com, diy.com) → ~93%
    # unverifiable at batch scale. Query-gen is non-critical (a search string, not a
    # verdict) so it runs on the deepseek→minimax fast chain — the moat verdict brain is
    # untouched. Graceful: if the batch call fails or omits a check, that check falls
    # back to the deterministic template (no hard-fail when the fast chain is down).
    llm_query_gen: bool = False
    # E1 hybrid arm (default OFF = control). Checks listed here use deterministic ENTITY
    # templates slot-filled from candidate fields (who_pays, tags.audience) as the PRIMARY
    # query source; the existing LLM/template chain fills in only when the entity fields are
    # blank. The bet (docs/COMMERCIAL_READINESS_PROGRAM.md §3 E1): queries that NAME the
    # concrete payer/channel entity ground payer_solvency/distribution, where product-shaped
    # queries starve. Never touches the verdict brain.
    hybrid_entity_checks: list[str] = field(default_factory=list)
    # Model for the web-SEARCH/grounding step (distinct from the verdict `model`).
    # flash-lite returns 0 sources for many queries (poor grounding recall); the
    # mid-tier model recalls far better and is still fast. Empty =>
    # fall back to model_fast/model. Verdict ruling still uses `model` (can stay -lite).
    search_model: str = ""
    # Web-grounding fail-fast budget. The free web-search tiers throttle after a
    # burst and then internally backs off for ~hours, which presents as a 240s hang. A
    # short timeout + few retries makes a throttled search GIVE UP quickly so the candidate
    # DEFERS (re-vet later) instead of blocking the whole run. Verdict calls (no web) are
    # unaffected — they use the CLI's normal timeout.
    search_timeout: int = 75            # base seconds per grounding web-search call (attempt 0)
    search_timeout_max: int = 150       # adaptive ceiling: timeout escalates per retry up to this
    search_timeout_escalation: float = 1.5  # multiply the timeout each retry (slow≠dead: give it room)
    search_retries: int = 1             # in-place retries before failing over to the next provider
    claude_min_timeout: int = 120       # claude grounding floor
    # Bounded work queue: a grounding call waits at most this long for a free provider
    # slot before giving up and failing over. Without this the semaphore wait was
    # UNBOUNDED and sat OUTSIDE the timeout, so a saturated provider could block a vet
    # indefinitely. Caps total latency at queue_timeout + search_timeout.
    queue_timeout: int = 45             # seconds to wait for a concurrency slot before failover
    # Physical load governors (decouple logical candidate concurrency from heavy CLI
    # subprocess load). Config is the single source of truth; env overrides for ops:
    #   PROSPECTOR_CLAUDE_CONCURRENCY, PROSPECTOR_VET_WORKERS.
    # Keep vet_workers <= claude_concurrency so parallel vets do not self-induce
    # queue_timeout / CLI hangs. `cursor_concurrency` was removed 2026-08-06 with the
    # cursor_cli adapter; claude_concurrency is now the only CLI ceiling.
    claude_concurrency: int = 2         # max concurrent claude CLI subprocesses
    vet_workers: int = 3                # candidates vetted in parallel; align to grounding slots
    # Completion-brain CLI budgets (the non-web Claude CLI). Distinct from
    # search_timeout (web-grounding). query_gen_* is the tight cap for non-critical
    # query-gen so one hung agent call cannot burn 6+ minutes per check.
    cli_timeout: int = 120              # verdict / adversarial completion (attempt 0)
    cli_timeout_max: int = 180          # completion ceiling across retries
    cli_retries: int = 1                # in-place retries for completion brains
    query_gen_timeout: int = 90         # batched/per-check query-gen (attempt 0)
    query_gen_timeout_max: int = 90     # no escalation — fail over / template fast
    query_gen_retries: int = 0          # template fallback is the retry
    # Circuit breaker (failover resilience). A provider is retired only after this many
    # CONSECUTIVE transient failures (or immediately on a quota wall), and recovers via a
    # half-open probe after the cooldown — never permanently dead-listed for the run.
    breaker_failure_threshold: int = 3  # consecutive transient fails before opening
    breaker_cooldown_s: float = 60.0    # seconds open before a half-open recovery probe
    # Batch-level kill-fast on INFRASTRUCTURE. The breaker above retires a single provider;
    # this one stops a whole vetting batch once the pipeline is demonstrably unable to rule.
    # Streak, not total — a healthy batch may legitimately defer one or two candidates, so
    # only CONSECUTIVE infra-gated defers mean "the subsystem is down, not the ideas".
    # 0 disables. Never a verdict knob: it can stop work, never change a ruling.
    infra_defer_abort_streak: int = 3


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
    # min_supported_confidence: PASS-SIDE floor (dossier source-or-die only). A SUPPORTED
    # check counts as grounded toward a PASS only when its confidence clears this floor.
    # Decoupled from confidence_floor (kill-side) so tightening passes never loosens kills.
    # Calibrated 2026-06-25 to 0.3 against the live supported-confidence distribution
    # (median 0.43); 0.0 default keeps it inert for callers that don't set it.
    min_supported_confidence: float = 0.0
    min_composite_to_pass: float = 3.2
    min_supported_to_pass: int = 1  # source-or-die: min grounded-supported checks for PASS
    # Lane-aware publish gate (source-or-die at the PASS boundary). The check(s) whose grounded
    # SUPPORTED verdict is REQUIRED before a candidate may publish in this lane; at least one
    # listed check must be grounded-supported. Default = the venture moat
    # (value_durability/incumbency). Lanes that DELIBERATELY disable the moat checks
    # (side_hustle, smb — see config.yaml lane notes) MUST override this to their own headline
    # evidence (e.g. payer_solvency), otherwise the gate demands checks the lane never runs and
    # NO candidate can ever PASS. PROVEN 2026-06-28: Martyn's Law cleared composite (2.95) but
    # was KILLed on `moat_ungrounded` because the smb lane runs neither value_durability nor
    # incumbency — making the entire smb/side_hustle PASS path structurally unreachable.
    moat_critical_checks: list[str] = field(
        default_factory=lambda: ["value_durability", "incumbency"])


@dataclass
class Spend:
    daily_cap_usd: float = 20.0
    warn_at_usd: float = 15.0
    # Ceiling on SUBSCRIPTION-equivalent burn — the Claude Code CLI's own `total_cost_usd`,
    # which `daily_cap_usd` cannot see (see scheduler/guard.py for the full measurement).
    # 0 = disabled, which is the historical behaviour and the default: this is not billed
    # money, so capping it is a decision about the Max plan's usage allowance, not about
    # liability, and arming it silently would halt a daemon that is currently legal.
    daily_subscription_cap_usd: float = 0.0
    # The ARMABLE half of the ceiling above. `daily_subscription_cap_usd` refuses the whole
    # tick via `guard.evaluate()`, and `run_scheduled.run_tick` returns on `not can_run` BEFORE
    # the drain — so arming it freezes the backlog, which is the 0efe40e defect arriving
    # through the money rail instead of through PAUSE. This one only suppresses GENERATION and
    # leaves the drain running, so the backlog falls while it is engaged and it releases itself
    # at the day roll-over. 0 = disabled (default, for the same reason as the hard cap).
    daily_subscription_soft_cap_usd: float = 0.0


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
    claude: str = "claude-opus-4-8"
    deepseek: str = "deepseek-chat"
    minimax: str = "MiniMax-M3"        # full reasoning model
    minimax_fast: str = "MiniMax-M3"  # also M3 per standing order
    ollama: str = "qwen2.5-coder:7b"
    standardcompute: str = "standardcompute"
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
    claude: PriceTier = field(default_factory=lambda: PriceTier(3.00, 15.00))
    deepseek: PriceTier = field(default_factory=lambda: PriceTier(0.27, 1.10))
    minimax: PriceTier = field(default_factory=lambda: PriceTier(0.30, 0.30))
    ollama: PriceTier = field(default_factory=lambda: PriceTier(0.00, 0.00))
    mock: PriceTier = field(default_factory=lambda: PriceTier(0.00, 0.00))

    # Deliberately `None`, not PriceTier(0, 0). StandardCompute publishes no
    # machine-readable rates: /v1/pricing, /v1/usage, /v1/billing and
    # /v1/models/standardcompute all 404 (probed 2026-08-08), and /v1/models
    # returns only {"id": "StandardCompute"}. A 0/0 default would satisfy
    # `getattr(cfg.pricing, provider)` in telemetry.get_price and SILENCE the
    # "not in cfg.pricing; returning $0" warning — converting a loud unknown
    # into a confident zero, which is exactly how spend.daily_cap_usd ends up
    # governing a fiction. None keeps the warning firing until real rates are
    # entered under a top-level `pricing:` block in config.yaml.
    standardcompute: PriceTier | None = None


@dataclass
class Admissibility:
    """Citation admissibility at RULING time (programme doc §20, the Q4 lever).

    `policy` is one of `prospector.admissibility.POLICIES`. Default `P1_check_aware`:
    measured to demote 12 ruled verdicts across two months (0.47%), one on the current moat,
    while removing the 18.8% low-tier exposure. `P0_global` is available but was measured at
    4.3x P1's cost and is NOT recommended — it destroys user-generated evidence precisely in
    the channel checks where that evidence was the right shape for the question.

    Set `policy: off` to restore pre-§20 behaviour exactly.
    """
    policy: str = "P1_check_aware"


def _validate_admissibility(raw: Any) -> "Admissibility":
    """Fail LOUDLY on an unknown policy rather than silently disabling the gate.

    Same rule as `_build_operator` raising for the removed `cursor_cli`: a typo in
    `config.yaml` must stop the process at startup, because the alternative is a gate that
    quietly does nothing while the config file says it is on. `inadmissible_tiers` returns an
    empty set for an unknown policy by design (it must never crash mid-verdict), which is
    exactly why the typo has to be caught HERE instead.
    """
    from .admissibility import POLICIES
    if not raw:
        return Admissibility()
    if not isinstance(raw, dict):
        raise ValueError(f"config `admissibility` must be a mapping, got {type(raw).__name__}")
    unknown = set(raw) - {"policy"}
    if unknown:
        raise ValueError(f"config `admissibility` has unknown key(s): {sorted(unknown)}")
    policy = str(raw.get("policy") or "P1_check_aware")
    if policy not in POLICIES:
        raise ValueError(
            f"config `admissibility.policy` = {policy!r} is not one of {list(POLICIES)}")
    return Admissibility(policy=policy)


def _validate_retrieval(raw: Any) -> "Retrieval":
    """Build Retrieval, rejecting a `hybrid_entity_checks` entry that has no template.

    The defect this closes: `_entity_queries` returns [] for a check with no entity
    template (deliberately — a missing template must not crash a verdict mid-run, and
    tests/unit/test_e1_hybrid_queries.py asserts that contract). The caller then falls
    through to the ordinary LLM/template chain. So listing `incumbency` in
    `hybrid_entity_checks` when no `incumbency` template existed did not enable the E1
    arm for that check — it did NOTHING, while config.yaml read as though the arm was on.
    The experiment would then report a null result for a condition it never ran.

    Same rule as `_validate_admissibility` and `_build_operator`'s removed `cursor_cli`:
    a config that cannot mean what it says must stop the process at startup.
    """
    from .entity_templates import checks_with_entity_templates

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"config `retrieval` must be a mapping, got {type(raw).__name__}")

    requested = raw.get("hybrid_entity_checks") or []
    if isinstance(requested, str) or not isinstance(requested, (list, tuple)):
        raise ValueError(
            "config `retrieval.hybrid_entity_checks` must be a list of check names, "
            f"got {type(requested).__name__}"
        )
    known = checks_with_entity_templates()
    unbacked = [c for c in requested if c not in known]
    if unbacked:
        raise ValueError(
            f"config `retrieval.hybrid_entity_checks` names check(s) with no entity "
            f"template: {sorted(unbacked)}. Known: {sorted(known)}. Listing a check here "
            f"without a template in prospector/entity_templates.py silently disables the "
            f"E1 arm for it instead of enabling it — add the template, or remove the name."
        )
    return Retrieval(**raw)


_PRESCREEN_PREFILTER_KEYS = frozenset({
    "shadow_mode", "backend", "threshold", "neighbours",
    "min_similarity", "min_exemplars", "max_exemplars", "log_dir",
})


def _validate_prescreen_prefilter(raw: Any) -> dict[str, Any]:
    """Fail LOUDLY on an unknown key (same rule as `_validate_admissibility`).

    A typo in this block must stop the process at startup. The alternative —
    `shadow_mod: true` silently doing nothing — is exactly the failure this repo
    already paid for with a gate that read as configured-on while inert.
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"config `prescreen_prefilter` must be a mapping, got {type(raw).__name__}")
    unknown = set(raw) - _PRESCREEN_PREFILTER_KEYS
    if unknown:
        raise ValueError(
            f"config `prescreen_prefilter` has unknown key(s): {sorted(unknown)}; "
            f"known keys are {sorted(_PRESCREEN_PREFILTER_KEYS)}")
    return dict(raw)


# Strict key allowlists for the blocks added by the commercial-readiness programme.
# Same rule as `_validate_admissibility` and `_validate_prescreen_prefilter`: a typo must
# stop the process at startup, because the alternative — `shadow_mod: true` silently doing
# nothing — is a failure this repo has already paid for more than once.
_BLOCK_KEYS: dict[str, frozenset[str]] = {
    # §25.6 — deterministic numeric-citation check. SHADOW ONLY by founder decision.
    "numeric_citation": frozenset({
        "enabled", "shadow_mode", "min_digits", "ignore_years", "tolerance", "log_dir",
    }),
    # V2 — under-coverage sampler over the four axes that actually exist as columns.
    "coverage_sampler": frozenset({
        "enabled", "axes", "method", "unknown_policy", "recent_window",
        "min_coverage", "seed",
        # G7 illumination. Both are steering-only: at quality_weight 0.0 the sampler is
        # V2 byte-for-byte, so a config that omits them is not a config that lost a feature.
        "quality_weight", "quality_stat",
    }),
    # V4 — nightly meta-shape monitor: "78 niches, one shape" becomes a measured number.
    "meta_shape_monitor": frozenset({
        "enabled", "embed_model", "ollama_host", "clusters",
        "alert_top_cluster_share", "min_rows", "log_dir",
    }),
    # R2 — per-candidate claim lock so a drain and a manual resume cannot both pay for
    # the same re-vet. A correctness rail, so unlike the others it defaults ON.
    "claim_lock": frozenset({"enabled", "dir", "stale_after_s"}),
    # F1-F4 — deterministic buyer-facing data artifacts (scorecard, financials,
    # comparables, radar SVG, XLSX, PDF). Zero LLM calls.
    "pack_data": frozenset({"enabled", "formats", "chrome_path"}),
}


def _validate_block(name: str, raw: Any) -> dict[str, Any]:
    """Validate one of the `_BLOCK_KEYS` config blocks, failing loudly on a typo."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"config `{name}` must be a mapping, got {type(raw).__name__}")
    known = _BLOCK_KEYS[name]
    unknown = set(raw) - known
    if unknown:
        raise ValueError(
            f"config `{name}` has unknown key(s): {sorted(unknown)}; "
            f"known keys are {sorted(known)}")
    return dict(raw)


# Defaults for the raw `listing:` block. config.yaml WINS for every key it declares; these
# only fill what it omits, so the flat catalogue price is declared in exactly ONE place in
# Python instead of as a literal on the money path (audit finding #20 — `pricing.py`'s
# `int(listing.get("price_pence", 4999))`). Two hardcoded fallbacks for one field is the
# defect shape of finding #17, and a price is the field where that drift charges a buyer.
LISTING_DEFAULTS: dict[str, Any] = {
    "price_pence": 4999,
    # §33 / item 33-G. When true, `bridge.listing_gate` refuses to list a pack whose figures were
    # never traced, or whose flagged figures have no human decision (`human_review.SELLABLE`).
    # DEFAULT FALSE, and the default is a decision: 15 of the 50 packs on sale carry an untraceable
    # figure, so switching it on is a ~30% delisting. The honest copy shipped regardless of the
    # flag, so nothing here is load-bearing for a promise.
    "require_figure_verification": False,
}


@dataclass
class Config:
    # str (single brain) or list[str] (ordered failover chain, Part 9).
    operator: "str | list[str]" = "mock"
    model: str = ""
    # Optional lighter model for mechanical calls (query-gen, prescreen). Empty
    # => reuse `model` (the CLI already auto-routes utility calls to flash).
    model_fast: str = ""
    model_version_tag: str = ""
    # Quality chain for the customer-facing £49 deliverable (prose artifacts + listing_page).
    # CLI-based, in-subscription operators (AGY CLI primary -> Claude CLI failover) so the
    # product's own copy isn't generated by the cheap non-critical tail. Empty => the moat op.
    artifact_operator: "str | list[str]" = field(default_factory=lambda: ["claude_cli"])
    # Shelf/marketing copy, split off the deliverable chain 2026-08-14 (founder: "isplit it but
    # we needd strong guardrails to keep minimax. in check"). Cheap chain first; the guardrail
    # is in run.py::_generate_pack_content, which grades the copy against the shelf bar and
    # ESCALATES a breach to artifact_operator rather than shipping the pack UNLISTED.
    marketing_operator: "str | list[str]" = field(
        default_factory=lambda: ["minimax", "claude_cli"])
    # The cheap chain: generation, prescreen, scoring. Never rules a verdict — anything of its
    # that reaches a ruling is stamped `provisional` by `is_provisional_provider`
    # (operator.py:1071). It was a module constant in `run.py`, which meant the one knob whose
    # whole purpose is "what does the ancillary work cost" could only be moved by editing
    # source and re-execing the daemon, while every throughput knob beside it was a config
    # line. Empty => the historical default below, byte for byte.
    # claude_cli removed 2026-08-14 (founder: "claude should never be used for non-critical").
    # Must stay equal to run.py::_NONCRITICAL_ORDER — test_noncritical_operator_config.py pins
    # the two together, and caught this default drifting when the constant moved.
    noncritical_operator: "str | list[str]" = field(
        default_factory=lambda: ["minimax", "standardcompute"])
    retrieval: Retrieval = field(default_factory=Retrieval)
    thresholds: Thresholds = field(default_factory=Thresholds)
    admissibility: Admissibility = field(default_factory=Admissibility)
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
    # Markets (Epic D): the JURISDICTION an opportunity lives in. Orthogonal to both the
    # ambition lane (which sets the bar) and the buyer's locale (packs sell in GBP
    # regardless). A market supplies the evidence terrain — authority domains, search
    # region, legality corpus — and the prompt framing. It may not touch the bar; see
    # MARKET_FORBIDDEN_KEYS. `active_market` empty => markets["default"] => byte-for-byte
    # today's behaviour.
    markets: dict[str, Any] = field(default_factory=dict)
    active_market: str = ""
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
    # Run-level archetype pin (`--archetype`). Empty => each lane's generation.operator_archetype
    # (or the top-level default). When set, re-applied after for_lane so it wins over lane defaults.
    active_archetype: str = ""
    listing: dict[str, Any] = field(default_factory=dict)
    # Near-duplicate similarity ratio (Part 3 dedup). At or above this, two candidates
    # are treated as duplicates and the later one is dropped. Lifted out of dedup.py so
    # the freshness bar is tunable without a code change.
    dedup_threshold: float = 0.85
    # Content-word overlap (Jaccard) threshold for the SECOND dedup signal. Char ratio is
    # blind to the same idea reworded; this catches it. At or above this, two candidates
    # are duplicates even if the char ratio is low. None disables the token signal.
    dedup_token_threshold: float = 0.34
    # E6 (programme doc §3) — local-embedding prescreen prefilter, SHADOW MODE ONLY.
    # `shadow_mode: false` by default: the block is inert until explicitly enabled, and
    # even when enabled it only LOGS what it would have dropped alongside what the LLM
    # prescreen actually decided (`prescreen_prefilter.record_shadow`). No key in this
    # block can change a prescreen decision — acting on the prefilter is a separate,
    # unbuilt change that E6 must earn with measured agreement first.
    prescreen_prefilter: dict[str, Any] = field(default_factory=dict)
    # §25.6 — deterministic numeric-citation check. Q4c measured that ~1 figure in 10 in a
    # dossier rationale appears in NO retrieved passage: the model invented it. This check
    # extracts the figures and confirms each one appears in the passage its own rationale
    # cites. Founder decision: SHADOW MODE FIRST — it logs, it never demotes a verdict.
    numeric_citation: dict[str, Any] = field(default_factory=dict)
    # V2 — under-coverage sampler. Built on the four axes that are real COLUMNS in
    # `dossiers` (ambition_tier, structural_form, audience, market), not on `sector`,
    # which exists only as prompt text and is therefore unmeasurable. Default OFF.
    coverage_sampler: dict[str, Any] = field(default_factory=dict)
    # V4 — meta-shape monitor: embeds catalogue one-liners locally and alerts when one
    # cluster exceeds a share. Makes "78 niches, one shape" a number instead of a worry.
    meta_shape_monitor: dict[str, Any] = field(default_factory=dict)
    # R2 — per-candidate claim lock for drain/decay/resume. Without it a concurrent drain
    # and a manual `vet --resume` can both claim the same candidate and pay twice for the
    # same re-vet. Defaults ON: this is a correctness rail, not an experiment.
    claim_lock: dict[str, Any] = field(default_factory=dict)
    # F1-F4 — deterministic buyer-facing data artifacts. The comparables in particular are
    # already fetched today and then DISCARDED; the buyer never sees the price evidence.
    pack_data: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    spend: Spend = field(default_factory=Spend)
    store: dict[str, Any] = field(default_factory=lambda: {"dir": "store"})
    # Entitlements API key for the /entitlements check. Read from the
    # PROSPECTOR_ENTITLEMENTS_API_KEY env var at config load time. No default
    # — if unset, the entitlements check will fail clearly (fail-closed).
    entitlements_api_key: str = ""
    # Storefront payment rail. `active_provider` selects which ProductProvisioner
    # EngineBridge uses at publish time (bridge.py `provisioner`). This MUST match the
    # provider the Store API's checkout endpoint bills through: checkout builds a Stripe
    # Checkout Session from `pack.ProviderPriceId`, so a pack provisioned under any other
    # provider lists with a `price_stub_*` id and its checkout 500s. Config-driven (not
    # env-only) so the value is version-controlled and identical across environments.
    store_payments: dict[str, Any] = field(
        default_factory=lambda: {"active_provider": "stripe"})
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
        # PROSPECTOR_STORE_DIR redirects every store read/write, including those made
        # by a CLI subprocess that loads its own Config. Without it a subprocess-driven
        # test has no way to avoid the operator's real store/: on 2026-07-30 the market
        # CLI tests both read and DELETED the live store/markets/us/READINESS.json while
        # an actual `markets probe us` run was writing it, which made
        # test_opening_without_a_probe_is_refused fail non-deterministically against a
        # tree whose tests pass in isolation. Absent the var, behaviour is unchanged.
        override = os.environ.get("PROSPECTOR_STORE_DIR", "").strip()
        d = Path(override) if override else Path(self.store.get("dir", "store"))
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
        # A run-level --archetype pin wins over the lane's default operator_archetype.
        if self.active_archetype:
            resolved = resolved.for_archetype(self.active_archetype)
        return resolved

    def for_archetype(self, name: str | None) -> "Config":
        """Pin `generation.operator_archetype` for this run (generation-only; never a gate).

        The named binding must exist under `generation.archetypes` (binding + forbid text
        injected into the generate prompt). Empty/None => unchanged. Unknown name raises.
        """
        if not name:
            return self
        archetypes = (self.generation or {}).get("archetypes") or {}
        if name not in archetypes:
            raise UnknownArchetypeError(
                f"unknown archetype {name!r}; defined: {sorted(archetypes)}")
        new_generation = {**self.generation, "operator_archetype": name}
        return replace(self, generation=new_generation, active_archetype=name)

    # ------------------------------------------------------------------
    # Markets (Epic D)
    # ------------------------------------------------------------------

    @property
    def default_market(self) -> str:
        """The market a candidate belongs to when none is declared."""
        return str((self.markets or {}).get("default", "") or "")

    def resolve_market(self, name: str | None) -> str:
        """Resolve a possibly-empty market name to a concrete code.

        Empty => the configured default. Raises UnknownMarketError for a name that has
        no definition (directly or via a parent, e.g. "us-tx" resolves through "us").
        """
        code = str(name or "").strip().lower() or self.default_market
        if not code:
            return ""
        if not self._market_chain(code):
            raise UnknownMarketError(
                f"unknown market {code!r}; defined: "
                f"{sorted(k for k in (self.markets or {}) if k != 'default')}")
        return code

    def _market_chain(self, code: str) -> list[str]:
        """Ancestry of `code`, nearest-first: 'us-tx' -> ['us-tx', 'us'].

        Only codes that are actually defined appear. Empty list => undefined market.
        A subdivision inherits everything its parent declares (spec DD4), so opening
        "us-tx" needs no config beyond "us" unless it genuinely differs.
        """
        markets = self.markets or {}
        parts = code.split("-")
        chain = []
        for i in range(len(parts), 0, -1):
            candidate = "-".join(parts[:i])
            if isinstance(markets.get(candidate), dict):
                chain.append(candidate)
        return chain

    def market_config(self, name: str | None = None) -> dict[str, Any]:
        """The resolved market block, with parent values inherited by a subdivision.

        Nearest ancestor wins per key. Returns {} when no markets are configured at all
        (a config predating Epic D), so every caller degrades to today's behaviour.
        """
        if not self.markets:
            return {}
        code = self.resolve_market(name if name is not None else self.active_market)
        if not code:
            return {}
        resolved: dict[str, Any] = {}
        for ancestor in reversed(self._market_chain(code)):  # furthest first
            resolved.update(self.markets.get(ancestor) or {})
        resolved["code"] = code
        return resolved

    def market_status(self, name: str | None = None) -> str:
        """'open' | 'probing' | 'closed'. Unconfigured markets read as 'open' so a
        pre-Epic-D config keeps working unchanged."""
        mc = self.market_config(name)
        return str(mc.get("status", "open") or "open") if mc else "open"

    def for_market(self, name: str | None) -> "Config":
        """Return a Config resolved to market `name`.

        Merges ONLY `retrieval` and `generation` overrides from the market block and
        records `active_market`. Gates, thresholds and weights are structurally
        untouchable (MARKET_FORBIDDEN_KEYS, enforced at load): a market changes where
        the engine LOOKS, never how strictly it JUDGES.

        Unknown name raises (UnknownMarketError) — see that class for why this diverges
        from for_lane's silent no-op.
        """
        if not self.markets:
            return self
        code = self.resolve_market(name)
        if not code:
            return self
        block = self.market_config(code)
        new_retrieval = self.retrieval
        if block.get("retrieval"):
            new_retrieval = replace(self.retrieval, **block["retrieval"])
        new_generation = {**self.generation, **(block.get("generation") or {})}
        return replace(self, retrieval=new_retrieval, generation=new_generation,
                       active_market=code)

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
        claude=raw_md.get("claude", "claude-opus-4-8"),
        deepseek=raw_md.get("deepseek", "deepseek-chat"),
        minimax=raw_md.get("minimax", "MiniMax-M3"),
        minimax_fast=raw_md.get("minimax_fast", ModelDefaults.minimax_fast),
        ollama=raw_md.get("ollama", "qwen2.5-coder:7b"),
        standardcompute=raw_md.get("standardcompute", "standardcompute"),
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
        claude=_tier(raw_pr.get("claude"), Pricing().claude),
        deepseek=_tier(raw_pr.get("deepseek"), Pricing().deepseek),
        minimax=_tier(raw_pr.get("minimax"), Pricing().minimax),
        ollama=_tier(raw_pr.get("ollama"), Pricing().ollama),
        mock=_tier(raw_pr.get("mock"), Pricing().mock),
        # `None` when unset, NOT a 0/0 tier — see the Pricing.standardcompute comment.
        # A 0/0 default here would satisfy the getattr in telemetry.get_price and mute
        # the unpriced-provider warning, which is the only thing currently telling the
        # operator that standardcompute spend is missing from the daily cap.
        standardcompute=(_tier(raw_pr.get("standardcompute"), PriceTier(0.0, 0.0))
                         if raw_pr.get("standardcompute") else None),
    )


def _validate_generation(raw_generation: dict | None) -> dict:
    """Fail closed when operator_archetype names a missing binding.

    Archetypes are prompt fragments only — they never touch gates/thresholds. Validation
    catches a typo that would silently drop the binding (empty operator_constraints).
    """
    if not raw_generation:
        return {}
    if not isinstance(raw_generation, dict):
        raise ValueError("`generation` must be a mapping")
    archetypes = raw_generation.get("archetypes") or {}
    if archetypes and not isinstance(archetypes, dict):
        raise ValueError("`generation.archetypes` must be a mapping")
    for code, block in archetypes.items():
        if not isinstance(block, dict):
            raise ValueError(f"generation.archetypes.{code!r} must be a mapping")
        if not str(block.get("binding", "")).strip():
            raise ValueError(
                f"generation.archetypes.{code!r} needs a non-empty `binding` string")
    pin = str(raw_generation.get("operator_archetype", "") or "").strip()
    if pin and pin not in archetypes:
        raise UnknownArchetypeError(
            f"generation.operator_archetype is {pin!r} but no such entry under "
            f"generation.archetypes (defined: {sorted(archetypes)})")
    return raw_generation


def _validate_markets(raw_markets: dict | None) -> dict:
    """Fail closed on a malformed `markets:` block.

    The load-time refusal of MARKET_FORBIDDEN_KEYS is the structural guarantee behind
    "the bar never moves per market" — it makes the tempting shortcut in a low-evidence
    market impossible rather than merely discouraged.
    """
    if not raw_markets:
        return {}
    if not isinstance(raw_markets, dict):
        raise MarketConfigError("`markets` must be a mapping")

    default = raw_markets.get("default")
    if not default:
        raise MarketConfigError("`markets.default` is required when `markets` is set")

    defined = {k: v for k, v in raw_markets.items() if k != "default"}
    if default not in defined:
        raise MarketConfigError(
            f"`markets.default` is {default!r} but no such market is defined "
            f"(defined: {sorted(defined)})")

    for code, block in defined.items():
        if not isinstance(block, dict):
            raise MarketConfigError(f"market {code!r} must be a mapping")
        offending = [k for k in MARKET_FORBIDDEN_KEYS if k in block]
        if offending:
            raise MarketConfigError(
                f"market {code!r} may not set {offending} — a market configures the "
                f"evidence terrain, never the bar. Move it to a lane if the BAR must "
                f"change; see MARKET_FORBIDDEN_KEYS.")
        if not str(block.get("label", "")).strip():
            raise MarketConfigError(f"market {code!r} needs a `label`")
        status = str(block.get("status", "open") or "open")
        if status not in _MARKET_STATUSES:
            raise MarketConfigError(
                f"market {code!r} has status {status!r}; expected one of "
                f"{list(_MARKET_STATUSES)}")
    return raw_markets


def _validate_weights(raw_weights: dict | None) -> dict[str, float]:
    """Fail LOUDLY on a malformed `weights:` block.

    score.composite() iterates this dict as `scores[ax] * weights[ax]`; a typo'd axis
    silently contributes 0 to every candidate's score (the unknown key is just skipped),
    and a block that does not sum to 1.0 silently rescaled the rubric. Both are
    founder-fatal config errors that must stop the process at startup — a load-time
    typo that quietly zeroes an axis cannot be detected from a single candidate's
    score, only from the shape of the rubric across many runs.
    """
    if not raw_weights:
        return {}
    if not isinstance(raw_weights, dict):
        raise ValueError(
            f"config `weights` must be a mapping, got {type(raw_weights).__name__}")
    # score.py imports config.py at module scope, so the reverse import must be lazy
    # (function-local) to avoid a circular import on package init.
    from .score import SCORE_AXES
    valid = set(SCORE_AXES)
    for k in raw_weights:
        if k not in valid:
            raise ValueError(
                f"config `weights` has unknown axis {k!r}; valid axes are {sorted(valid)}")
        try:
            v = float(raw_weights[k])
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"config `weights[{k!r}]` must coerce to float, got "
                f"{raw_weights[k]!r} ({type(raw_weights[k]).__name__})") from e
        if v < 0:
            raise ValueError(
                f"config `weights[{k!r}]` must be >= 0, got {v}")
    total = sum(float(v) for v in raw_weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            f"config `weights` must sum to 1.0 within 1e-6, got {total}")
    return {k: float(v) for k, v in raw_weights.items()}


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else REPO_ROOT / "config.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    cfg = Config(
        operator=raw.get("operator", "mock"),
        model=raw.get("model", ""),
        model_fast=raw.get("model_fast", ""),
        model_version_tag=raw.get("model_version_tag", ""),
        artifact_operator=raw.get("artifact_operator") or ["claude_cli"],
        marketing_operator=raw.get("marketing_operator") or ["minimax", "claude_cli"],
        # Fourth and last place this chain is declared (dataclass default, run.py's
        # _NONCRITICAL_ORDER, config.yaml, here). claude_cli removed 2026-08-14 — a default
        # is a decision, and this one silently outvoted the config every time the key was absent.
        noncritical_operator=(raw.get("noncritical_operator")
                              or ["minimax", "standardcompute"]),
        retrieval=_validate_retrieval(raw.get("retrieval")),
        thresholds=Thresholds(**(raw.get("thresholds") or {})),
        admissibility=_validate_admissibility(raw.get("admissibility")),
        hard_gates=raw.get("hard_gates") or [],
        weights=_validate_weights(raw.get("weights")),
        lanes=raw.get("lanes") or {},
        active_lane=raw.get("active_lane") or "",
        active_lanes=raw.get("active_lanes") or [],
        lane_quota=raw.get("lane_quota") or {},
        markets=_validate_markets(raw.get("markets")),
        active_market=raw.get("active_market") or "",
        generation=_validate_generation(raw.get("generation")),
        profiles=raw.get("profiles") or {},
        active_profile=raw.get("active_profile") or "",
        personas=raw.get("personas") or {},
        active_persona=raw.get("active_persona") or "",
        # Defaults first, config.yaml second: a declared key always wins, an omitted one
        # falls back to LISTING_DEFAULTS rather than to a literal buried in pricing.py.
        listing={**LISTING_DEFAULTS, **(raw.get("listing") or {})},
        dedup_threshold=float(raw.get("dedup_threshold", 0.85)),
        dedup_token_threshold=(
            None if raw.get("dedup_token_threshold", 0.34) is None
            else float(raw.get("dedup_token_threshold", 0.34))
        ),
        prescreen_prefilter=_validate_prescreen_prefilter(raw.get("prescreen_prefilter")),
        numeric_citation=_validate_block("numeric_citation", raw.get("numeric_citation")),
        coverage_sampler=_validate_block("coverage_sampler", raw.get("coverage_sampler")),
        meta_shape_monitor=_validate_block(
            "meta_shape_monitor", raw.get("meta_shape_monitor")),
        claim_lock=_validate_block("claim_lock", raw.get("claim_lock")),
        pack_data=_validate_block("pack_data", raw.get("pack_data")),
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
        # Payment rail: config.yaml wins, then PAYMENTS_ACTIVE_PROVIDER, then the
        # dataclass default (stripe). Never silently falls back to a provider we hold
        # no key for — that is what shipped six unbuyable packs.
        store_payments={
            "active_provider": (
                (raw.get("store_payments") or {}).get("active_provider")
                or os.environ.get("PAYMENTS_ACTIVE_PROVIDER")
                or "stripe"
            ),
            **{k: v for k, v in (raw.get("store_payments") or {}).items()
               if k != "active_provider"},
        },
    )
    # Lane-level operator_archetype pins must resolve against the shared archetypes map.
    archetypes = (cfg.generation or {}).get("archetypes") or {}
    for lane_name, lane in (cfg.lanes or {}).items():
        if not isinstance(lane, dict):
            continue
        pin = str((lane.get("generation") or {}).get("operator_archetype", "") or "").strip()
        if pin and pin not in archetypes:
            raise UnknownArchetypeError(
                f"lanes.{lane_name}.generation.operator_archetype is {pin!r} but no such "
                f"entry under generation.archetypes (defined: {sorted(archetypes)})")

    # Market resolves FIRST: it is the outermost context (which evidence terrain the run
    # searches), and the lane/profile/persona resolvers below use dataclasses.replace, so
    # active_market and the market-merged retrieval survive them untouched.
    if cfg.active_market:
        cfg = cfg.for_market(cfg.active_market)
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

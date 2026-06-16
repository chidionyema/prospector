"""CLI orchestrator (Part 3/4/8). The runtime entrypoint.

Usage examples:
  python -m prospector.run vet --title "Fuel duty rebate automation" \\
      --one-liner "SaaS to reclaim fuel duty for fleets" --why-now "2024 HMRC rule change"

  python -m prospector.run signal --text "Rising energy costs for SME manufacturers"

  python -m prospector.run signal --file signals/fuel_duty.txt \\
      --fixtures fixtures/fuel_duty_passages.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Max candidates vetted in parallel. Each vet drives slow CLI subprocesses, so the
# real throughput ceiling is the grounding concurrency; this caps how many candidate
# vets are in flight at once. Sourced from config (retrieval.vet_workers, aligned to
# grounding slots) so 5 workers no longer oversubscribe 2+2 slots and self-induce
# timeouts; PROSPECTOR_VET_WORKERS still overrides for ops. Not a verdict knob.
def _vet_workers(cfg) -> int:
    env = os.environ.get("PROSPECTOR_VET_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, int(getattr(cfg.retrieval, "vet_workers", 3)))


def _resolve_lanes(cfg, args) -> Optional[list]:
    """Which ambition lanes this run spans (Part 14 — multi-lane-by-default).

    --lane X            => single pinned tier [X] (classify skipped; tier is the user's word).
    else active_lane    => single config-pinned tier (today's single-lane behaviour).
    else active_lanes   => the multi-lane set (a mixed-ambition catalogue).
    else                => None (no lane engaged → byte-for-byte today's single default).
    """
    lane = getattr(args, "lane", None)
    if lane:
        return [lane]
    if getattr(cfg, "active_lane", ""):
        return [cfg.active_lane]
    if getattr(cfg, "active_lanes", None):
        return list(cfg.active_lanes)
    return None


def _lane_counts(cfg, lanes: list, k: Optional[int]) -> dict:
    """How many candidates to generate per lane. With no explicit total (`k` None) use the
    per-lane `lane_quota` (default 3). With an explicit `--candidates k`, distribute k across
    the lanes PROPORTIONAL to the quota weights (every lane keeps >=1) so the flag scales the
    whole fan-out rather than any single tier. All values are config-sourced — no hardcoding."""
    if not lanes:
        return {}
    quota = {t: max(1, int((cfg.lane_quota or {}).get(t, 3))) for t in lanes}
    if k is None:
        return quota
    total_w = sum(quota.values()) or len(lanes)
    counts = {t: max(1, round(k * quota[t] / total_w)) for t in lanes}
    # Nudge the rounded counts toward the requested total k (never below 1 per lane).
    order = sorted(lanes, key=lambda t: quota[t], reverse=True)
    i = 0
    while sum(counts.values()) != k and i < 10_000:
        t = order[i % len(order)]
        diff = k - sum(counts.values())
        if diff > 0:
            counts[t] += 1
        elif counts[t] > 1:
            counts[t] -= 1
        i += 1
    return counts


# ---------------------------------------------------------------------------
# Pending signal persistence (generation resilience)
# When the generation chain (DeepSeek → MiniMax → Gemini) is exhausted, the signal
# text is saved here so the operator can re-run generation with `generate --resume`
# when the chain recovers.  Each pending signal is one JSON file keyed by a hash of
# the signal text so re-runs don't create duplicates.
# ---------------------------------------------------------------------------
_PENDING_DIR = Path(__file__).resolve().parent.parent / "signals" / "pending"


def _save_pending_signal(signal_text: str, cfg: Config) -> Path:
    """Save a failed signal so `generate --resume` can retry it later."""
    import hashlib
    key = hashlib.sha1(signal_text.encode()).hexdigest()[:16]
    path = _PENDING_DIR / f"{key}.json"
    try:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"signal_text": signal_text, "key": key}), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not save pending signal: {e}")
    return path


def _load_pending_signals() -> list[tuple[Path, str]]:
    """Return all pending signals as (path, text) pairs."""
    if not _PENDING_DIR.exists():
        return []
    results = []
    for p in sorted(_PENDING_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append((p, data.get("signal_text", "")))
        except Exception:
            pass
    return results

from .config import Config, load_config
from .dedup import dedup
from .dossier import build_dossier, render_markdown
from .errors import ProviderExhaustedError
from .generate import generate
from .models import Candidate, Decision, Dossier
from .operator import Operator
from .prescreen import prescreen
from .retrieval import SearchProvider
from .score import score_candidate
from .store import Store
from .telemetry import logger, set_context, track_latency

# verify is imported lazily inside vet_candidate to avoid a pre-existing
# dead-import error in verify.py (gate_check listed but not defined in
# kill_filter.py).  Lazy import keeps the module-level import of run.py clean
# while still providing full runtime access.
def _get_verify():
    from .verify import verify as _verify
    return _verify


# ---------------------------------------------------------------------------
# Core vetting unit
# ---------------------------------------------------------------------------

@track_latency(name="vet_candidate")
def vet_candidate(
    cand: Candidate,
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    store: Optional[Store] = None,
    query_op: Optional[Operator] = None,
    publish: bool = False,
    show_checks: bool = False,
    label: Optional[str] = None,
    skip_adversarial: bool = False,
    full_vet: bool = False,
    experimental_op: Optional[Operator] = None,
    board_personas: Optional[list[str]] = None,
) -> Dossier:
    """Run the full verification pipeline for a single candidate.

    Steps:
      1. Run the six kill-checks (kill-fast).
      2. Score only if no gate fired.
      3. Assemble Dossier with UTC timestamps.
      4. Persist via store if provided.

    Secondary artifacts + marketing content (~12 model calls) and syndication are
    deferred behind ``publish``: a plain vet produces only the grounded verdict +
    score (cheap). Pass publish=True to generate listing content and publish on
    PASS. ``query_op`` is an optional lighter model for the mechanical query-gen
    step (model tiering); falls back to ``op``.

    Args:
        full_vet: When True, bypasses kill-fast and runs ALL checks (Stochastic Full-Vetting).
        experimental_op: Optional operator to run verification against in parallel
            (Shadow Moat). Findings are logged but do not change the dossier decision.
        board_personas: Optional list of persona names to run as 'Advisory Board'. 
            Each persona runs verification in parallel and findings are logged.
    """
    set_context(candidate_id=cand.candidate_id, phase="vetting")
    logger.info(f"Vetting candidate: {cand.title!r} (full_vet={full_vet}, persona={cfg.active_persona})")

    from . import progress

    def _check_line(res, prefix: str = "") -> str:
        v = res.verdict.value
        mark = "✗" if v in ("refuted", "unverifiable") else "✓"
        return f"{prefix}{mark} {res.check_name} → {v} (conf {res.confidence:.2f})"

    on_check = None
    if label:
        # Concurrent signal pool: tag EVERY line with the candidate so interleaved
        # output from parallel vets stays attributable, and emit a line the moment
        # the vet starts so the user gets immediate feedback (not a 60s silence).
        progress.note(f"{label} ▸ vetting started" + (" [FULL-VET]" if full_vet else ""))
        def on_check(res) -> None:
            progress.note(_check_line(res, prefix=f"{label} "))
    elif show_checks:
        # Single-vet: no interleaving, so no candidate prefix needed.
        if full_vet:
            progress.note("Full-vet mode: short-circuit disabled.")
        def on_check(res) -> None:
            progress.note(_check_line(res))

    verify = _get_verify()
    # Build the moat operator chain string for the audit trail (e.g. "claude/claude-opus-4-8 →
    # gemini/2.5-flash-lite").  FallbackOperator.name is already in that format.
    _provider_chain = getattr(op, "name", "") or getattr(op, "model_version", "") or str(op)
    
    # Shadow Moat: Run experimental verification in parallel if requested.
    # We do this first (or concurrently) to ensure it doesn't wait for the primary.
    exp_res = None
    if experimental_op:
        logger.info(f"SHADOW MOAT: Running experimental vet for {cand.title!r}")
        try:
            # Run a silent verification (no progress updates)
            exp_res = verify(experimental_op, search, cfg, cand, 
                            skip_adversarial=skip_adversarial, full_vet=full_vet)
        except Exception as e:
            logger.warning(f"Shadow Moat failed for {cand.candidate_id}: {e}")

    # ADVISORY BOARD (Part 16 principal upgrade): Run shadow personas in parallel.
    board_results = {}
    if board_personas:
        for p_name in board_personas:
            if p_name == cfg.active_persona: continue
            logger.info(f"ADVISORY BOARD: persona {p_name!r} analyzing {cand.title!r}")
            try:
                p_cfg = cfg.for_persona(p_name)
                # Run silent verification with shadow persona
                p_res = verify(op, search, p_cfg, cand, 
                               skip_adversarial=skip_adversarial, full_vet=full_vet)
                board_results[p_name] = p_res
            except Exception as e:
                logger.warning(f"Advisory Board failed for persona {p_name!r}: {e}")

    try:
        checks, adversarial, gate = verify(op, search, cfg, cand,
                                           on_check=on_check, query_op=query_op,
                                           skip_adversarial=skip_adversarial,
                                           full_vet=full_vet)
    except ProviderExhaustedError as e:
        # Both Claude AND Gemini are exhausted — the moat is down.  This is NOT a
        # candidate quality failure; defer the candidate for re-vet when the moat
        # recovers.  Log a moat-outage telemetry event so the audit trail is complete.
        logger.warning(f"Moat exhausted for {cand.title!r}: {e}; deferring "
                       f"(re-vet when moat recovers via `vet --resume`)",
                       extra={"candidate_id": cand.candidate_id,
                              "provider_exhausted": str(e)[:200],
                              "event": "moat_outage"})
        from .telemetry import record_usage
        record_usage(input_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0, web=False,
                     message=f"MOAT OUTAGE: {cand.candidate_id} deferred — {str(e)[:100]}")
        checks, adversarial = [], None
        gate = "moat_exhausted"

    # Log Shadow Moat drift
    if exp_res:
        exp_checks, exp_adv, exp_gate = exp_res
        if exp_gate != gate:
            logger.warning(f"SHADOW MOAT DRIFT for {cand.candidate_id}: "
                           f"Primary={gate} vs Experimental={exp_gate}",
                           extra={"primary": gate, "experimental": exp_gate, 
                                  "candidate": cand.title})
    
    # Log Advisory Board findings
    for p_name, (p_checks, p_adv, p_gate) in board_results.items():
        if p_gate != gate:
            logger.info(f"ADVISORY BOARD ({p_name!r}) differs for {cand.candidate_id}: "
                        f"Primary={gate} vs {p_name}={p_gate}",
                        extra={"primary_persona": cfg.active_persona, "shadow_persona": p_name,
                               "primary_gate": gate, "shadow_gate": p_gate})
        else:
            logger.info(f"ADVISORY BOARD ({p_name!r}) agrees with primary decision ({gate})")

    score = None
    if gate is None:
        logger.info("Candidate survived all gates. Scoring...")
        # FIX #12: score is a rubric classification — route to flash-lite via query_op.
        score = score_candidate(op, cfg, cand, checks, scorer_op=query_op)

        if publish:
            # --- Task B: Secondary artifacts + claim-check (publish-time only) ---
            # FIX #12: route artifact/marketing generation to flash-lite (query_op/fast_op).
            # FIX #13: generate_artifacts and generate_marketing_content are now
            # parallelized internally (ThreadPoolExecutor) — 4 threads instead of
            # sequential, cutting PASS-survivor latency by ~50%.
            logger.info("Generating publish-time artifacts + marketing content...")
            from .artifacts import generate_artifacts, generate_marketing_content
            cand.tags["artifacts"] = generate_artifacts(op, cand, checks, fast_op=query_op)
            cand.tags["marketing"] = generate_marketing_content(op, cand, checks, fast_op=query_op)

    now = datetime.datetime.now(datetime.timezone.utc)

    created_at = now.isoformat()
    reverify_due_at = (now + datetime.timedelta(days=30)).isoformat()

    dossier = build_dossier(
        cand=cand,
        checks=checks,
        adversarial=adversarial,
        gate_fired=gate,
        score=score,
        cfg=cfg,
        op_model_version=op.model_version,
        provider_chain=_provider_chain,
        created_at=created_at,
        reverify_due_at=reverify_due_at,
    )

    if store is not None:
        store.save(dossier)

    if publish and dossier.decision == Decision.PASS and not dossier.provisional:
        try:
            from publish.publish import publish as _publish
            _publish(dossier, cfg)
        except Exception as e:
            logger.error(f"Publication failed for {cand.candidate_id}", extra={"error": str(e)})
    elif publish and dossier.decision == Decision.PASS and dossier.provisional:
        # Provisional PASS: the moat was exhausted and the cheap fallback tail ruled.
        # Real-but-untrusted — never publish. It will auto re-vet on `vet --resume`.
        logger.warning(
            f"Provisional PASS held back from publication for {cand.candidate_id} "
            f"(ruled by emergency fallback; awaiting moat re-vet via `vet --resume`).",
            extra={"candidate_id": cand.candidate_id, "provider_chain": _provider_chain})

    logger.info(f"Vetting complete: {dossier.decision.value.upper()}", 
                extra={"decision": dossier.decision.value, "gate": gate})
    return dossier



# ---------------------------------------------------------------------------
# Signal pipeline
# ---------------------------------------------------------------------------

@track_latency(name="run_signal")
def run_signal(
    signal_text: str,
    cfg: Optional[Config] = None,
    op: Optional[Operator] = None,
    search: Optional[SearchProvider] = None,
    store: Optional[Store] = None,
    k: Optional[int] = None,
    publish: bool = False,
    exploration: Optional[float] = None,
    lanes: Optional[list] = None,
    focus: Optional[str] = None,
    board_personas: Optional[list[str]] = None,
) -> list[Dossier]:
    """Generate candidates from a signal, dedup, prescreen, vet each, return dossiers.

    Any of cfg/op/search/store may be None — defaults are loaded automatically.
    Plain runs are cheap (verdict + score only); pass publish=True to also
    generate listing artifacts and publish PASSes. ``signal_text=""`` runs
    blue-sky generation. ``exploration`` overrides the adaptive exploration level
    when provided (e.g. the ``generate`` CLI's ``--exploration``).

    ``lanes`` (Part 14 — multi-lane-by-default): the ambition tiers this run spans.
      - None         => no lane engaged; byte-for-byte today's single-default behaviour.
      - [X]          => single pinned tier (generate + vet in tier X; classify skipped).
      - [X, Y, ...]  => MIXED catalogue: fan generation out per tier, auto-classify each idea
                        into its natural tier, then vet EACH against its OWN tier's bar.
    """
    from .telemetry import get_usage_summary, reset_usage
    from . import progress
    set_context(phase="signal_pipeline")
    logger.info("Starting signal pipeline")
    reset_usage()  # fresh token ledger for this run
    progress.banner("Signal pipeline starting")

    # --- Load defaults ---
    if cfg is None:
        cfg = load_config()

    if op is None:
        from .operator import make_operator
        op = make_operator(cfg)

    # Tiered non-critical chain (fast_op): cheapest operators first, last-resort
    # fallback to Gemini-flash.  Claude is deliberately EXCLUDED — it is too expensive
    # for mechanical JSON work (prescreen, scoring, content).  The moat chain (Claude→
    # Gemini) is only used for kill-check verdicts and adversarial analysis.
    #
    # Tier 1: DeepSeek-chat  $0.27/M in  (best for structured JSON output)
    # Tier 2: MiniMax-M2.7   $0.30/M in  (secondary; robust fallback)
    # Tier 3: Gemini-flash   $0.075/M in (last resort; cheaper per-token than Claude)
    #
    # Each tier is guarded by an independent circuit breaker.  A quota exhaustion on
    # DeepSeek skips it and tries MiniMax; MiniMax exhausted skips to Gemini-flash;
    # Gemini-flash exhausted → all three skipped → ProviderExhaustedError → DEFER.
    # A tier's health mark does NOT pollute the moat health file (moat stays clean).
    from .operator import _build_operator, FallbackOperator
    from .errors import ProviderExhaustedError
    from .telemetry import record_usage

    def _build_operator_chain(order: tuple[str, ...], fast: bool) -> Operator:
        """Build a FallbackOperator from the given tier order. Raises if none available."""
        tiers = []
        for kind in order:
            try:
                tiers.append((kind, _build_operator(kind, cfg, fast=fast)))
            except RuntimeError:
                pass  # tier not configured or missing API key
        if len(tiers) == 0:
            raise ProviderExhaustedError(
                f"All operators in {order} unavailable — check API keys and credentials.")
        if len(tiers) == 1:
            logger.info(f"Single operator: {tiers[0][0]}")
            return tiers[0][1]
        r = cfg.retrieval
        chain = FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                                cooldown_s=r.breaker_cooldown_s)
        logger.info(f"Chain: {' → '.join(n for n, _ in tiers)}")
        return chain

    # gen_op: gemini API first (~1s per call, paid quota), deepseek fallback.
    gen_op = _build_operator_chain(
        ("gemini", "deepseek", "gemini_cli"),
        fast=True
    )

    # fast_op: same order.
    fast_op = _build_operator_chain(
        ("gemini", "deepseek", "gemini_cli"),
        fast=True
    )

    # Shadow Moat (Part 16 principal upgrade): optionally load an experimental 
    # operator to run in parallel. Findings are logged for drift analysis.
    experimental_op = None
    exp_name = getattr(cfg, "experimental_operator", None)
    if exp_name:
        try:
            experimental_op = _build_operator(exp_name, cfg)
            logger.info(f"SHADOW MOAT ENABLED: using experimental operator {exp_name!r}")
        except Exception as e:
            logger.warning(f"Could not initialize shadow moat operator {exp_name!r}: {e}")

    if search is None:
        from .retrieval import make_provider
        search = make_provider(cfg)

    if store is None:
        store = Store(cfg)

    # --- Adaptive creativity (Part 3) ---
    from .adaptive import (calculate_exploration_level, get_recent_failure_modes,
                           select_lenses, blue_sky_failure_steer, get_exemplars,
                           calculate_grid_priorities)
    expl = exploration if exploration is not None else calculate_exploration_level(store, cfg=cfg)
    fails = get_recent_failure_modes(store, cfg=cfg)
    # Blue-sky (no signal): the kill log is domain-specific and, fed raw, drags
    # generation back into the saturated domain. Reframe it as a no-go zone +
    # cross-sector mandate so blue-sky actually ranges (Part 15B breadth KPI).
    if not signal_text.strip():
        fails = blue_sky_failure_steer(fails)
    
    # ML Improvement: Exemplar injection (Stage 2)
    exemplars = get_exemplars(store, op)
    if exemplars:
        fails = (fails or "") + "\n\n" + exemplars

    # ML Improvement: Grid Scheduler (Stage 3)
    grid_priorities = calculate_grid_priorities(store, cfg)

    lenses = select_lenses(cfg, expl, k=k or 5)
    logger.info(f"Adaptive Controller: expl={expl:.1f}", extra={"exploration_level": expl, "fails": fails, "lenses": lenses, "grid_priorities": grid_priorities})

    # --- Spend guard (Part 9) ---
    from .spend import SpendGuard
    guard = SpendGuard(daily_cap_usd=cfg.spend.daily_cap_usd,
                       warn_at_usd=cfg.spend.warn_at_usd)

    # --- Generate ---
    # Positive learning: extract PASS survivor patterns for injection into generation.
    from .adaptive import get_pass_traits
    patterns = get_pass_traits(store)

    # FIX: MiniMax generation — gen_op (MiniMax) for generation; op (Claude/Gemini) stays
    # for verification.  gen_op falls back to op if MINIMAX_API_KEY is not configured.
    if lanes and len(lanes) > 1:
        # MULTI-LANE (Part 14): fan generation out across tiers.
        # Tier is set inside generate_multilane() directly from the lane loop variable —
        # no LLM call needed to re-confirm what generation already assigned.  The lane
        # config (cfg.for_lane(tier)) shaped the idea at generation time; the tier tag
        # is the authoritative routing key for the downstream vetting bar.
        from .generate import generate_multilane
        counts = _lane_counts(cfg, lanes, k)
        progress.step(f"multi-lane generation across {len(lanes)} tier(s): {counts}")
        candidates = generate_multilane(
            op, cfg, lanes=lanes, lane_counts=counts, signal_text=signal_text,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            gen_op=gen_op, grid_priorities=grid_priorities, focus=focus,
            pass_patterns=patterns)
        # ambition_tier already set inside generate_multilane (c.ambition_tier = tier).
    elif lanes:
        # SINGLE pinned tier (--lane X or config active_lane): generate in that tier, tag it,
        # skip classify (the tier is fixed by the operator's choice).
        tier = lanes[0]
        # ML Improvement: Grid Scheduler (Stage 3)
        priorities = (grid_priorities or {}).get(tier)
        candidates = generate(
            op, cfg.for_lane(tier), signal_text=signal_text, k=k,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=patterns)
        for c in candidates:
            c.ambition_tier = tier
    else:
        # DEFAULT (no lane engaged): byte-for-byte today's single-default behaviour.
        # Use 'venture' (default) prioritized forms
        priorities = (grid_priorities or {}).get("venture")
        candidates = generate(
            op, cfg, signal_text=signal_text, k=k,
            strategy_lens=lenses, exploration_level=expl, recent_failure_modes=fails,
            gen_op=gen_op, grid_priorities=priorities, focus=focus,
            pass_patterns=patterns,
        )
    if not candidates:
        # Generation chain exhausted — save the signal text so the operator can
        # re-run it later with `generate --resume`.  Never lose a signal.
        _save_pending_signal(signal_text, cfg)
        logger.warning(f"Generation chain exhausted (deepseek/minimax/gemini all unavailable or "
                       f"quota depleted). Signal saved for retry. Run `generate --resume` "
                       f"when generation chain recovers.")
        progress.step(f"generation chain exhausted — signal saved, re-run with generate --resume")
        return []
    logger.info(f"Generated {len(candidates)} candidates")
    progress.step(f"generated {len(candidates)} candidates")

    # --- Dedup against catalogue ---
    catalogue = store.catalogue_titles()
    unique, dropped = dedup(candidates, catalogue)
    if dropped:
        logger.info(f"Dedup dropped {len(dropped)} near-duplicate pair(s)")
    if dropped:
        progress.note(f"dedup dropped {len(dropped)} near-duplicate(s)")

    # --- Rejection fast-path (Part 8) ---
    # If an exact near-duplicate was KILLED within the SLA window, return that dossier immediately.
    final_candidates = []
    rejection_dossiers = []

    # Load recent KILLS
    all_kills = store.all(decision=Decision.KILL.value)
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    for cand in unique:
        found_recent_kill = False
        for k_row in all_kills:
            # Check SLA (e.g. 30 days)
            due_str = k_row.get("reverify_due_at")
            if due_str and now_dt < datetime.datetime.fromisoformat(due_str):
                from .dedup import is_near_duplicate
                if is_near_duplicate(cand.title, k_row["title"]):
                    logger.info(f"REJECTION FAST-PATH: reusing kill record for {cand.title!r}", 
                                extra={"candidate_id": cand.candidate_id, "original_id": k_row["candidate_id"]})
                    k_dossier_dict = store.get(k_row["candidate_id"])
                    if k_dossier_dict:
                        found_recent_kill = True
                        break

        if not found_recent_kill:
            final_candidates.append(cand)

    # --- Prescreen (parallel) ---
    # prescreen() is a pure, no-web per-candidate call that NEVER raises (keep-biased
    # on any error). Running candidates concurrently overlaps the calls without changing
    # any keep/reject decision — physical load is still bounded by the CLI semaphores.
    # Results are collected in submission order so kept[] stays in generation order.
    from concurrent.futures import ThreadPoolExecutor
    prescreened_data: list[tuple[Candidate, float, str]] = []
    pre_workers = _vet_workers(cfg)
    with ThreadPoolExecutor(max_workers=pre_workers) as pre_ex:
        pre = [(cand, pre_ex.submit(prescreen, fast_op, cfg, cand))
               for cand in final_candidates]
        for cand, fut in pre:
            keep, score, reason, features = fut.result()
            if keep:
                prescreened_data.append((cand, score, features))
            else:
                logger.info(f"PRESCREENED OUT: {cand.title!r}", extra={"reason": reason})
                progress.note(f"prescreened out: {cand.title!r}")

    if not prescreened_data:
        logger.warning("No candidates survived prescreen")
        progress.step("0 candidates survived prescreen")
        return []

    # --- ML Improvement: DPP Novelty Selection ---
    # Instead of vetting ALL prescreened candidates, we select the most diverse 
    # and high-quality subset. This prevents spending moat tokens on near-duplicates.
    from .novelty import select_diverse_candidates
    target_k = k or getattr(cfg.generation, "candidates_per_signal", 5)
    kept = select_diverse_candidates(op, prescreened_data, k=target_k)

    workers = _vet_workers(cfg)
    progress.step(f"vetting {len(kept)} candidate(s) diverse subset live (max {workers} in parallel)…")

    # --- Vet each candidate (Bounded Concurrency Task E) ---
    from concurrent.futures import ThreadPoolExecutor, as_completed
    dossiers: list[Dossier] = []

    def _label(idx: int, total: int, title: str) -> str:
        short = (title[:34] + "…") if len(title) > 35 else title
        return f"[{idx}/{total} {short}]"

    with ThreadPoolExecutor(max_workers=workers) as executor:
        fut_meta: dict = {}  # future -> stable candidate index (1-based, survives reorder)
        for idx, cand in enumerate(kept, start=1):
            # Check spend guard (rough check before submitting)
            if guard.tripped():
                logger.error(f"ABORTING: Spend guard tripped (${guard.total():.2f})")
                break
            
            # Stochastic Full-Vetting (Part 16 principal upgrade): 1-in-10 candidates 
            # bypass kill-fast to gather a complete failure surface for the 
            # Adaptive Controller.
            should_full_vet = (idx % 10 == 0)
            
            # Each candidate carries a stable [idx/N title] tag so its live per-check
            # lines stay attributable even though parallel vets interleave on stderr.
            # Per-tier vetting (Part 14): resolve config to THIS candidate's ambition tier so
            # the gates/thresholds/weights/adversarial framing match the idea's own bar. For an
            # untagged candidate (today's default) for_lane("") returns cfg unchanged.
            vet_cfg = cfg.for_lane(cand.ambition_tier)
            fut = executor.submit(
                vet_candidate, cand, op, search, vet_cfg,
                store=store, query_op=fast_op, publish=publish,
                label=_label(idx, len(kept), cand.title),
                full_vet=should_full_vet,
                experimental_op=experimental_op,
                board_personas=board_personas)
            fut_meta[fut] = idx
            # Rough cost estimate increment
            guard.add(0.01)

        total_submitted = len(fut_meta)
        # Stream each verdict the MOMENT its vet finishes (completion order), not in
        # submission order — a fast KILL no longer waits behind a slow candidate.
        for future in as_completed(fut_meta):
            idx = fut_meta[future]
            try:
                d = future.result()
                gate_str = f" [gate={d.gate_fired}]" if d.gate_fired else ""
                logger.info(f"Result: {d.candidate.title!r} → {d.decision.value.upper()}{gate_str}",
                            extra={"candidate_id": d.candidate.candidate_id, "decision": d.decision.value, "score": d.score.composite if d.score else None})
                progress.result(idx, total_submitted, d.decision.value, d.candidate.title,
                                gate=d.gate_fired,
                                composite=(d.score.composite if d.score else None))
                dossiers.append(d)
            except Exception as e:
                logger.error(f"ERROR vetting candidate: {e}", extra={"error": str(e)})
                progress.note(f"[{idx}/{total_submitted}] ⚠ error: {e}")

    # --- Summary ---
    n_pass = sum(1 for d in dossiers if d.decision == Decision.PASS)
    n_defer = sum(1 for d in dossiers if d.decision == Decision.DEFER)
    n_kill = len(dossiers) - n_pass - n_defer
    ruled = n_pass + n_kill
    survival = n_pass / ruled if ruled else 0.0  # deferrals excluded — not real kills
    usage = get_usage_summary()
    logger.info("Signal pipeline complete", extra={
        "total_vetted": len(dossiers),
        "pass_count": n_pass,
        "kill_count": n_kill,
        "defer_count": n_defer,
        "survival_rate": survival,
        "usage": usage,
    })
    progress.summary(n_pass, n_kill, usage, n_defer=n_defer)

    # Production self-watch (free, no model calls): flag calibration pathologies
    # — zero-yield, single-gate dominance, dead gates — the moment they appear, so a
    # mis-calibrated filter (e.g. a gate killing on silence) is surfaced, not silent.
    from .diagnostics import calibration_alarms
    for a in calibration_alarms(store, cfg):
        progress.note(("🚨 " if a["level"] == "alarm" else "⚠️  ") + f"[{a['code']}] {a['message']}")

    return dossiers



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_config_and_overrides(args: argparse.Namespace) -> Config:
    """Load config and apply CLI overrides (operator, retrieval provider)."""
    cfg = load_config(args.config if args.config else None)

    if hasattr(args, "operator") and args.operator:
        cfg.operator = args.operator

    # If fixtures provided, switch retrieval provider to fixture mode
    if hasattr(args, "fixtures") and args.fixtures:
        cfg.retrieval.provider = "fixture"

    # Ambition-lane override (config-pinned): judge against THIS lane's gates/thresholds
    # instead of the default. Applied last (returns a resolved copy). Empty => unchanged.
    if getattr(args, "lane", None):
        cfg = cfg.for_lane(args.lane)

    # Generation-profile override (Part 16): a targeted steering bundle (restricted forms +
    # focus directive). Applied after the lane so it composes over it (profile wins). Empty
    # => unchanged. for_lane re-applies it internally for per-tier multilane generation.
    if getattr(args, "profile", None):
        cfg = cfg.for_profile(args.profile)

    # Persona override (Part 16 principal upgrade): analytical multi-tenancy.
    # Applied after the profile so its biases (generation/verdict/adversarial) win.
    if getattr(args, "persona", None):
        cfg = cfg.for_persona(args.persona)

    return cfg


def _make_search(cfg: Config, args: argparse.Namespace) -> SearchProvider:
    """Build the SearchProvider, injecting fixtures when --fixtures is passed."""
    from .retrieval import make_provider

    fixtures = None
    if hasattr(args, "fixtures") and args.fixtures:
        with open(args.fixtures, encoding="utf-8") as fh:
            fixtures = json.load(fh)

    return make_provider(cfg, fixtures=fixtures)


def _resolve_board(args: argparse.Namespace) -> Optional[list[str]]:
    if getattr(args, "board", False):
        return ["shark", "minimalist", "academic"]
    return None


def _cmd_vet(args: argparse.Namespace, log_path: Path) -> None:
    """Vet a single candidate or re-vet all moat-deferred candidates."""
    cfg = _build_config_and_overrides(args)

    from .operator import make_operator
    from .telemetry import get_usage_summary, reset_usage
    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    search = _make_search(cfg, args)
    store = Store(cfg)

    if getattr(args, "resume", False):
        _cmd_resume(args, cfg, op, fast_op, search, store)
        return

    cand = Candidate(
        title=args.title,
        one_liner=getattr(args, "one_liner", "") or "",
        why_now=getattr(args, "why_now", "") or "",
    )

    from . import progress
    progress.banner(f"Vetting: {cand.title!r}")
    progress.step("running kill-checks (kill-fast)…")

    d = vet_candidate(cand, op, search, cfg, store=store,
                      query_op=fast_op, publish=getattr(args, "publish", False),
                      show_checks=True,
                      board_personas=_resolve_board(args))
    progress.summary(
        n_pass=1 if d.decision == Decision.PASS else 0,
        n_kill=1 if d.decision == Decision.KILL else 0,
        n_defer=1 if d.decision == Decision.DEFER else 0)
    print(render_markdown(d))
    usage = get_usage_summary()
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_resume(args: argparse.Namespace, cfg: Config, op: Operator,
                fast_op: Operator, search: SearchProvider, store: Store) -> None:
    """Re-vet all moat-deferred candidates.

    Called when `vet --resume` is used or when the moat comes back online after an outage.
    Loads each deferred candidate, re-runs the full verification pipeline (not partial —
    the moat is now available, so we run everything), and overwrites the DEFER decision
    with the fresh verdict.  Candidates that were deferred due to a real retrieval
    outage (not moat exhaustion) are also retried.
    """
    # Two populations need the moat to revisit them:
    #   1. DEFER  — the moat was unavailable, so no verdict was reached at all.
    #   2. provisional — a real verdict WAS reached, but by the cheap emergency fallback
    #      tail (moat exhausted). Re-vet so the trusted moat overwrites the cheap ruling.
    # De-dup by candidate_id (a dossier can't be both, but guard against overlap).
    deferred = store.all(decision="defer")
    provisional = store.provisional()
    seen_ids = {r.get("candidate_id", "") for r in deferred}
    pending = list(deferred) + [r for r in provisional
                                if r.get("candidate_id", "") not in seen_ids]
    if not pending:
        print("No deferred or provisional candidates to resume. Moat is healthy.")
        return

    n_prov = len(pending) - len(deferred)
    print(f"Found {len(deferred)} deferred + {n_prov} provisional candidate(s). "
          f"Re-vetting with moat...")
    from .models import Candidate
    from .telemetry import get_usage_summary, reset_usage
    from . import progress

    n_pass = n_kill = n_defer = 0
    resumed_dossiers = []
    for row in pending:
        cid = row.get("candidate_id", "")
        # Load the full dossier JSON to reconstruct the candidate fields.
        full = store.get(cid)
        if not full:
            print(f"  ⚠ {cid}: dossier JSON missing, skipping")
            continue
        cand_dict = full.get("candidate", {})
        cand = Candidate.from_dict(cand_dict)
        # Also restore ambition_tier and structural_form from the stored data.
        cand.ambition_tier = str(cand_dict.get("ambition_tier", "") or "")
        cand.structural_form = str(cand_dict.get("structural_form", "") or "")
        was_provisional = bool(row.get("provisional", 0))
        prior = ("provisional " + str(full.get("decision", "")).upper()
                 if was_provisional else "deferred")
        original_reason = full.get("reason", "")[:80]
        progress.banner(f"[resume] {cand.title!r} (was {prior}: {original_reason})")

        try:
            d = vet_candidate(cand, op, search, cfg, store=store,
                              query_op=fast_op,
                              publish=getattr(args, "publish", False),
                              show_checks=True,
                              board_personas=_resolve_board(args))
        except ProviderExhaustedError as e:
            # Moat still exhausted — stop here. Remaining candidates keep their prior
            # state (deferred, or provisional verdict); re-run --resume when moat recovers.
            progress.note(f"Moat still exhausted ({e}). Remaining candidates keep their "
                         f"prior state. Re-run `vet --resume` when moat recovers.")
            break

        if d.decision == Decision.PASS:
            n_pass += 1
        elif d.decision == Decision.KILL:
            n_kill += 1
        else:
            n_defer += 1
        resumed_dossiers.append(d)

    # Summary.
    print(f"\n{'='*60}")
    print(f"Resume complete: {len(resumed_dossiers)}/{len(pending)} re-vetted  "
          f"✅{n_pass}  🛑{n_kill}  ⏸️{n_defer}")
    if n_defer > 0:
        print(f"  {n_defer} still deferred — moat may still be recovering.")
    if n_pass > 0:
        print(f"  ✅ {n_pass} candidate(s) PASSED — see store/dossiers/")
    usage = get_usage_summary()
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_signal(args: argparse.Namespace, log_path: Path) -> None:
    """Run the full signal pipeline from text or file."""
    cfg = _build_config_and_overrides(args)

    if args.text is not None:  # "" is a valid blue-sky signal, not "missing"
        signal_text = args.text
    elif args.file:
        with open(args.file, encoding="utf-8") as fh:
            signal_text = fh.read()
    else:
        print("Error: --text or --file is required for the signal command.", file=sys.stderr)
        sys.exit(1)

    from .operator import make_operator
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    dossiers = run_signal(signal_text, cfg=cfg, op=op, search=search, store=store,
                          k=getattr(args, "count", None),
                          publish=getattr(args, "publish", False),
                          lanes=_resolve_lanes(cfg, args),
                          focus=getattr(args, "focus", None),
                          board_personas=_resolve_board(args))

    # Durable, human-readable result on stdout (stderr carried the live progress).
    from .telemetry import get_usage_summary
    print(f"\n=== Signal result: {len(dossiers)} candidate(s) vetted ===")
    for d in dossiers:
        glyph = {Decision.PASS: "PASS", Decision.KILL: "KILL",
                 Decision.DEFER: "DEFER"}.get(d.decision, d.decision.value.upper())
        if d.decision == Decision.DEFER:
            detail = "retrieval failed — re-vet (NOT a kill)"
        elif d.gate_fired:
            detail = f"gate={d.gate_fired}"
        else:
            detail = f"composite={d.score.composite:.2f}" if d.score else ""
        print(f"  [{glyph}] {d.candidate.title}  {detail}")
        print(f"         id={d.candidate.candidate_id}  (full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_generate(args: argparse.Namespace, log_path: Path) -> None:
    """Blue-sky run: generate + vet candidates with NO signal (signal_text="").
    With --resume: re-run the full pipeline for all pending signals that failed due
    to generation chain exhaustion."""
    cfg = _build_config_and_overrides(args)

    # --- Handle --resume: re-run pipeline for pending signals ---
    if getattr(args, "resume", False):
        _cmd_generate_resume(args, cfg, log_path)
        return

    from .operator import make_operator
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    dossiers = run_signal("", cfg=cfg, op=op, search=search, store=store,
                          k=getattr(args, "candidates", None),
                          exploration=getattr(args, "exploration", None),
                          publish=getattr(args, "publish", False),
                          lanes=_resolve_lanes(cfg, args),
                          focus=getattr(args, "focus", None),
                          board_personas=_resolve_board(args))

    from .telemetry import get_usage_summary
    print(f"\n=== Blue-sky result: {len(dossiers)} candidate(s) vetted ===")
    for d in dossiers:
        glyph = {Decision.PASS: "PASS", Decision.KILL: "KILL",
                 Decision.DEFER: "DEFER"}.get(d.decision, d.decision.value.upper())
        if d.decision == Decision.DEFER:
            detail = "retrieval failed — re-vet (NOT a kill)"
        elif d.gate_fired:
            detail = f"gate={d.gate_fired}"
        else:
            detail = f"composite={d.score.composite:.2f}" if d.score else ""
        print(f"  [{glyph}] {d.candidate.title}  {detail}")
        print(f"         id={d.candidate.candidate_id}  (full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_generate_resume(args: argparse.Namespace, cfg: Config, log_path: Path) -> None:
    """Re-run the pipeline for all pending signals.

    Reads signals from signals/pending/ and re-runs the full signal pipeline
    (generate + vet) for each.  On success, removes the pending file.  On
    failure, leaves it so it can be retried again.
    Safe to re-run when the non-critical generation chain (DeepSeek/MiniMax/
    Gemini) recovers from quota depletion.
    """
    pending = _load_pending_signals()
    if not pending:
        print("No pending signals to resume. signals/pending/ is empty.")
        return

    from .operator import make_operator
    from .retrieval import make_provider
    from .telemetry import reset_usage, get_usage_summary
    from . import progress

    reset_usage()
    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    print(f"Found {len(pending)} pending signal(s). Re-running pipeline...")
    total_pass = total_kill = total_defer = 0
    for path, signal_text in pending:
        signal_key = path.stem
        progress.banner(f"[resume] {signal_key}: {signal_text[:60]!r}")
        dossiers = run_signal(signal_text, cfg=cfg, op=op, search=search, store=store,
                              k=getattr(args, "count", None),
                              publish=getattr(args, "publish", False),
                              lanes=_resolve_lanes(cfg, args))
        n_pass = sum(1 for d in dossiers if d.decision == Decision.PASS)
        n_kill = sum(1 for d in dossiers if d.decision == Decision.KILL)
        n_defer = sum(1 for d in dossiers if d.decision == Decision.DEFER)
        total_pass += n_pass
        total_kill += n_kill
        total_defer += n_defer

        if dossiers:
            # Generation succeeded — remove the pending file.
            path.unlink(missing_ok=True)
            print(f"  [{n_pass} pass / {n_kill} kill / {n_defer} defer] → pending file removed")
        else:
            # Generation still failing — leave the pending file for retry.
            print(f"  Generation still failing — pending file retained")

    print(f"\n=== Resume complete: {total_pass} pass / {total_kill} kill / {total_defer} defer ===")
    if total_defer > 0:
        print(f"  {total_defer} DEFERred — run `vet --resume` when moat recovers.")
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


def _cmd_report(args, cfg, log_path) -> None:
    """Render the catalogue / metrics / costs / generation quality / trend.
    Reads on-disk state only; no model calls."""
    from .report import (catalogue_report, metrics_report, costs_report,
                           generation_quality_report, trend_report, full_report)
    from .diagnostics import calibration_alarms, render_alarms
    from .store import Store
    store = Store(cfg)
    if args.full:
        print(full_report(store, log_path))
        print("\n" + "═" * 72)
        print("CALIBRATION SELF-WATCH")
        print("═" * 72)
        print(render_alarms(calibration_alarms(store, cfg)))
    elif args.metrics:
        print(metrics_report(store))
        print("\n  calibration self-watch:")
        print(render_alarms(calibration_alarms(store, cfg)))
    elif args.generation_quality:
        print(generation_quality_report(store))
    elif args.trend:
        windows = getattr(args, 'windows', (7, 30, 90))
        print(trend_report(store, windows=windows))
    elif args.costs:
        print(costs_report(log_path))
    else:  # default: catalogue
        print(catalogue_report(store, decision=args.decision))


def _cmd_diagnose(args, cfg, log_path) -> None:
    """Calibration self-diagnostics. Free catalogue alarms always; --deep also runs
    the golden set through the production brain chain against fixed evidence."""
    from .diagnostics import (calibration_alarms, render_alarms,
                              run_calibration, render_calibration)
    from .store import Store
    store = Store(cfg)
    print("═" * 72)
    print("CALIBRATION SELF-WATCH (catalogue, no model calls)")
    print("═" * 72)
    print(render_alarms(calibration_alarms(store, cfg)))
    if getattr(args, "deep", False):
        print()
        report = run_calibration(cfg, floor=args.floor)
        print(render_calibration(report))
        if not report["ok"]:
            sys.exit(2)  # regression → non-zero so CI / scripts can gate on it


def _cmd_operators(args) -> None:
    """Probe every operator: latency, health, circuit breakers, chain state.

    Run this first whenever something feels wrong — it shows exactly which operators
    are alive, how fast they respond, and what the persisted health marks say.
    """
    import time
    from .config import load_config
    from .health import get_health
    from .operator import _build_operator, make_operator, FallbackOperator

    SIMPLE_PROMPT = ("You are a helpful assistant. "
                      "Reply to the following with exactly three words: Hello, how are you?")

    print("=" * 72)
    print("OPERATOR DIAGNOSTICS")
    print("=" * 72)

    # ── 1. Persisted health (cross-run exhaustion marks) ───────────────────
    print("\n▸ Persisted health (store/provider_health.json)")
    try:
        health = get_health()
        pdata = health._load()
        if pdata:
            now = time.time()
            for name, entry in pdata.items():
                until = float(entry.get("dead_until", 0))
                remaining = max(0, until - now)
                print(f"  ✗ {name:55s}  dead for {int(remaining):>5}s more")
        else:
            print("  (clean — no exhausted operators)")
    except Exception as e:
        print(f"  (could not read: {e})")

    # ── 2. Individual operator probes ───────────────────────────────────────
    print("\n▸ Individual operator probes")
    available_ops = []  # list of (kind, op, elapsed_or_None)
    cfg = load_config(args.config if args.config else None)

    for kind in ("deepseek", "minimax", "gemini",
                 "gemini_cli", "claude_cli"):
        print(f"\n  {kind:15s}", end="", flush=True)
        try:
            op = _build_operator(kind, cfg, fast=True)
            print(f"  [{op.name}]", end="")

            t0 = time.monotonic()
            result = op._raw(SIMPLE_PROMPT, "", 0.1)
            elapsed = time.monotonic() - t0
            short = (result or "(empty)")[:60].replace("\n", " ")
            print(f"  ✓ {elapsed:6.1f}s  → {short!r}")
            available_ops.append((kind, op, elapsed))
        except RuntimeError as e:
            print(f"  ✗ unavailable: {e}")
            available_ops.append((kind, None, None))
        except Exception as e:
            print(f"  ✗ FAILED: {type(e).__name__}: {e}")
            available_ops.append((kind, None, None))

    # ── 3. Non-critical chain ordering (same logic as run_signal) ────────
    print("\n▸ Non-critical chain ordering")
    # These match the order in run_signal's _build_operator_chain calls.
    # gen_op: generation (creative, ~7000-char prompts)
    # fast_op: scoring + prescreen (0-5 axis, simple prompts)
    # Run `python -m prospector.run operators --gen` to measure and update these.
    try:
        from .errors import ProviderExhaustedError
        r = cfg.retrieval

        def build_chain(order, fast_label):
            tiers = []
            for kind in order:
                try:
                    op = _build_operator(kind, cfg, fast=False)  # gen_op uses fast=False for reasoning
                    if fast_label:
                        # fast_op uses fast=True for scoring/prescreen
                        op = _build_operator(kind, cfg, fast=True)
                    tiers.append((kind, op))
                except RuntimeError:
                    pass
            if not tiers:
                return f"{fast_label or 'chain'}: (none available)"
            if len(tiers) == 1:
                return f"{fast_label}: {tiers[0][0]} (single)"
            fb = FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                                 cooldown_s=r.breaker_cooldown_s)
            return f"{fast_label}: {' → '.join(n for n, _ in tiers)}"

        print(f"  {build_chain(('deepseek', 'minimax', 'gemini_cli'), 'gen_op')}")
        print(f"  {build_chain(('deepseek', 'minimax', 'gemini_cli'), 'fast_op')}")
    except Exception as e:
        print(f"  ✗ could not build chains: {e}")

    # ── 4. Generation prompt probe (optional) ─────────────────────────────
    if getattr(args, "gen", False):
        print("\n▸ Generation prompt probe (~7000 chars)")
        from .prompts import render
        sys_p, usr_p = render("generate",
                               signal_text="AI tools for UK small businesses",
                               sector="", strategy_lens="broaden",
                               exploration_level=0.5)
        print(f"  Prompt size: {len(sys_p) + len(usr_p)} chars")
        # Probe the non-critical chain operators only
        gen_ops = [(k, o, b) for k, o, b in available_ops
                   if o is not None and k in ("deepseek", "minimax", "gemini_cli")]
        for kind, op, baseline in gen_ops:
            print(f"\n  {kind:15s} (baseline {baseline:.1f}s)...", end="", flush=True)
            t0 = time.monotonic()
            try:
                result = op._raw(sys_p, usr_p, 0.7)
                elapsed = time.monotonic() - t0
                short = str(result)[:80].replace("\n", " ")
                print(f"  {elapsed:6.1f}s  → {short!r}")
            except Exception as e:
                elapsed = time.monotonic() - t0
                print(f"  ✗ {elapsed:.1f}s: {type(e).__name__}: {e}")

    # ── 5. Summary ─────────────────────────────────────────────────────────
    print("\n▸ Summary")
    working = [(n, t) for n, _, t in available_ops if t is not None]
    slow = [(n, t) for n, _, t in available_ops if t is not None and t > 15]
    dead = [n for n, _, t in available_ops if t is None]

    if working:
        by_speed = sorted(working, key=lambda x: x[1])
        print(f"  Fastest : {by_speed[0][0]}({by_speed[0][1]:.1f}s)")
        print(f"  All     : " + ", ".join(f"{n}({t:.1f}s)" for n, t in by_speed))
    if slow:
        print(f"  Slow    : " + ", ".join(f"{n}({t:.1f}s)" for n, t in slow))
    if dead:
        print(f"  Dead    : " + ", ".join(dead))
    if not working and not dead:
        print("  (no operators probed — check network and API keys)")

    print("\n" + "=" * 72)



def _manage_lanes(action: str, lane_name: str | None, config_path: Path) -> None:
    """Manage ambition lanes in config.yaml via line-based editing.

    Actions:
      list   — print defined lanes + active_lane / active_lanes (no mutation)
      nix    — remove lane_name from active_lanes
      natch  — add lane_name to active_lanes
      set    — set active_lane to lane_name (single-lane pin; "" => unset)
      unset  — clear active_lane to "" (multi-lane mode)

    Uses regex-based line replacement to preserve YAML comments and structure.
    """
    import re

    text = config_path.read_text()

    # ------------------------------------------------------------------ list
    if action == "list":
        cfg = load_config(config_path)
        defined = list(cfg.lanes.keys()) if cfg.lanes else []
        print(f"Defined lanes: {', '.join(defined) if defined else '(none defined)'}")
        al = cfg.active_lane or ""
        als = cfg.active_lanes or []
        mode = "(single-lane mode)" if al else "(multi-lane mode)"
        print(f"active_lane: {al!r}  {mode}")
        print(f"active_lanes: [{', '.join(als)}]")
        return

    # ------------------------------------------------------------------ nix
    if action == "nix":
        # Parse the active_lanes line
        m = re.search(r"^active_lanes:\s*\[(.*?)\]\s*$", text, re.MULTILINE)
        if not m:
            print("error: active_lanes line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        current = [s.strip() for s in m.group(1).split(",") if s.strip()]
        if lane_name not in current:
            print(f"note: '{lane_name}' is not in active_lanes (no change).")
            print(f"active_lanes: [{', '.join(current)}]")
            return
        current.remove(lane_name)
        new_line = f"active_lanes: [{', '.join(current)}]"
        text = re.sub(r"^active_lanes:\s*\[.*?\]\s*$", new_line, text, flags=re.MULTILINE)
        config_path.write_text(text)
        print(f"nixed '{lane_name}' — active_lanes: [{', '.join(current)}]")
        return

    # ------------------------------------------------------------------ natch
    if action == "natch":
        m = re.search(r"^active_lanes:\s*\[(.*?)\]\s*$", text, re.MULTILINE)
        if not m:
            print("error: active_lanes line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        current = [s.strip() for s in m.group(1).split(",") if s.strip()]
        if lane_name in current:
            print(f"note: '{lane_name}' is already in active_lanes (no change).")
            print(f"active_lanes: [{', '.join(current)}]")
            return
        current.append(lane_name)
        new_line = f"active_lanes: [{', '.join(current)}]"
        text = re.sub(r"^active_lanes:\s*\[.*?\]\s*$", new_line, text, flags=re.MULTILINE)
        config_path.write_text(text)
        print(f"natched '{lane_name}' — active_lanes: [{', '.join(current)}]")
        return

    # ------------------------------------------------------------------ set
    if action == "set":
        lane_val = lane_name or ""
        new_active = f'active_lane: "{lane_val}"'
        if re.search(r"^active_lane:", text, re.MULTILINE):
            text = re.sub(r"^active_lane:\s*\".*?\"\s*$", new_active, text, flags=re.MULTILINE)
        else:
            print("error: active_lane line not found in config.yaml", file=sys.stderr)
            sys.exit(1)
        config_path.write_text(text)
        if lane_val:
            print(f"active_lane set to '{lane_val}' (single-lane mode)")
        else:
            print("active_lane unset (multi-lane mode)")
        return

    # ------------------------------------------------------------------ unset
    if action == "unset":
        text = re.sub(r"^active_lane:\s*\".*?\"\s*$", 'active_lane: ""', text, flags=re.MULTILINE)
        config_path.write_text(text)
        print("active_lane unset (multi-lane mode)")
        return

    print(f"error: unknown lanes action '{action}'", file=sys.stderr)
    sys.exit(1)


def _cmd_lanes(args: argparse.Namespace, log_path: Path) -> None:
    """Dispatch to _manage_lanes with args from the CLI."""
    from .config import REPO_ROOT
    action = getattr(args, "lanes_action", "list")
    lane_name = getattr(args, "lane", None)
    config_path = args.config if getattr(args, "config", None) else REPO_ROOT / "config.yaml"
    path = Path(config_path) if not isinstance(config_path, Path) else config_path
    if not path.exists():
        print(f"error: config file not found at {path}", file=sys.stderr)
        sys.exit(1)
    _manage_lanes(action, lane_name, path)


def _save_discovered_signals(signals: list[dict]) -> list[str]:
    """Persist discovered signals to signals/ as a re-runnable audit trail.

    Mirrors the spec's operator-pasted-signal convention (signals/, one per file):
    a discovered signal becomes a normal signal file the operator can re-vet or edit.
    """
    import re

    out_dir = "signals"
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    paths: list[str] = []
    for s in signals:
        slug = re.sub(r"[^a-z0-9]+", "_", s.get("title", "").lower()).strip("_")[:50] or "signal"
        path = os.path.join(out_dir, f"discovered_{stamp}_{slug}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(s["signal_text"].strip() + "\n")
        paths.append(path)
    return paths


def _cmd_discover(args: argparse.Namespace, log_path: Path) -> None:
    """Surface N diverse signals, then run the full pipeline on each (a sweep).

    NOTE: signal *discovery* is a deliberate extension BEYOND the original spec —
    the spec's model is operator-pasted signal files. This command lets the engine
    self-source a diverse, sector-spread portfolio of signals so generation ranges
    broadly instead of producing variations on one hand-written theme. It judges
    nothing; the same grounded moat downstream still vets and kills every candidate.
    """
    cfg = _build_config_and_overrides(args)

    from .operator import make_operator
    from .discover import discover_signals
    from . import progress

    op = make_operator(cfg)
    search = _make_search(cfg, args)
    store = Store(cfg)

    progress.banner(f"Signal discovery (spec extension): surfacing {args.signals} signal(s)")
    signals = discover_signals(op, cfg, n=args.signals,
                               sectors=getattr(args, "sectors", "") or "")
    if not signals:
        print("No signals discovered (model returned nothing usable).", file=sys.stderr)
        sys.exit(1)

    sectors = sorted({s.get("sector", "") for s in signals if s.get("sector")})
    progress.step(f"discovered {len(signals)} signal(s) across {len(sectors)} sector(s)")
    for s in signals:
        print(f"  • [{s.get('sector', '?')}] {s['title']}")

    if not getattr(args, "no_save", False):
        saved = _save_discovered_signals(signals)
        progress.note(f"saved {len(saved)} signal file(s) to signals/ (re-runnable audit trail)")

    if getattr(args, "dry_run", False):
        print("\n(dry-run) discovery only — no candidates generated or vetted.")
        return

    # --- Sweep: run the full grounded pipeline on each discovered signal ---
    all_dossiers: list[Dossier] = []
    board = _resolve_board(args)
    for i, s in enumerate(signals, start=1):
        progress.banner(f"[{i}/{len(signals)}] {s.get('sector', '?')}: {s['title']}")
        ds = run_signal(s["signal_text"], cfg=cfg, op=op, search=search, store=store,
                        k=getattr(args, "count", None),
                        publish=getattr(args, "publish", False),
                        lanes=_resolve_lanes(cfg, args),
                        board_personas=board)
        all_dossiers.extend(ds)

    # --- Cross-sweep summary ---
    n_pass = sum(1 for d in all_dossiers if d.decision == Decision.PASS)
    n_defer = sum(1 for d in all_dossiers if d.decision == Decision.DEFER)
    n_kill = len(all_dossiers) - n_pass - n_defer
    print(f"\n=== Discovery sweep complete: {len(signals)} signal(s) → "
          f"{len(all_dossiers)} candidate(s) vetted ===")
    print(f"    PASS={n_pass}  KILL={n_kill}  DEFER={n_defer}")
    for d in all_dossiers:
        if d.decision == Decision.PASS:
            comp = f"  composite={d.score.composite:.2f}" if d.score else ""
            print(f"  [PASS] {d.candidate.title}{comp}")
            print(f"         id={d.candidate.candidate_id}  "
                  f"(full dossier: store/dossiers/{d.candidate.candidate_id}.json)")
    if n_pass == 0:
        print("  (no PASS this sweep — per-signal verdicts in the catalogue / store/prospector.jsonl)")


def _load_dotenv() -> None:
    """Populate os.environ from env files, without adding a dependency (python-dotenv
    is not installed). Existing env vars ALWAYS WIN — a real shell (which sources
    ~/.config/llm/secrets.sh via ~/.zshrc) is authoritative; these files only fill gaps
    for non-shell launches (IDE run config, cron, a bare subprocess).

    Reads, in order (later files never override earlier or the live env):
      1. the gitignored repo-root .env        (project-specific overrides)
      2. ~/.config/llm/secrets.sh             (the canonical cross-tool key store)

    Both are simple KEY=VALUE; a leading `export ` is tolerated (so the SAME file can be
    sourced by zsh and parsed here — single source of truth). Blanks and #-comments are
    skipped; surrounding quotes stripped. Missing/malformed files are silently ignored."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(repo_root, ".env"),
        os.path.expanduser("~/.config/llm/secrets.sh"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="python -m prospector.run",
        description="Prospector opportunity vetting engine",
    )
    parser.add_argument("--config", metavar="PATH", help="Path to config.yaml")

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- vet subcommand ----
    vet_p = sub.add_parser("vet", help="Vet a single candidate")
    vet_p.add_argument("--title", required=True, help="Opportunity title")
    vet_p.add_argument("--one-liner", dest="one_liner", default="",
                       help="One-liner description")
    vet_p.add_argument("--why-now", dest="why_now", default="",
                       help="Why this opportunity exists now")
    vet_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    vet_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane to judge against (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    vet_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    vet_p.add_argument("--board", action="store_true",
                       help="Enable 'Advisory Board' mode: run multiple shadow personas (shark, minimalist, academic) "
                            "in parallel for deep critique.")
    vet_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    vet_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish on PASS (extra model calls)")
    vet_p.add_argument("--resume", action="store_true",
                       help="Re-vet all moat-deferred candidates (decision=defer).  "
                            "Uses the same operator/lane as the original run.  "
                            "Safe to re-run when the moat (Claude/Gemini) comes back online.")

    # ---- signal subcommand ----
    sig_p = sub.add_parser("signal", help="Run the full signal pipeline")
    sig_src = sig_p.add_mutually_exclusive_group(required=True)
    sig_src.add_argument("--text", metavar="TEXT", help="Signal text inline")
    sig_src.add_argument("--file", metavar="PATH", help="Path to signal text file")
    sig_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    sig_p.add_argument("--count", type=int, default=None, metavar="N",
                       help="Number of candidates to generate (default: config candidates_per_signal)")
    sig_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    sig_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")
    sig_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane for generation + vetting (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    sig_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    sig_p.add_argument("--board", action="store_true",
                       help="Enable 'Advisory Board' mode: run multiple shadow personas (shark, minimalist, academic) "
                            "in parallel for deep critique.")
    sig_p.add_argument("--profile", metavar="NAME",
                       help="Generation profile: a reusable steering bundle (restricted forms + "
                            "focus directive) from config 'profiles' (e.g. online_autonomous_predator).")
    sig_p.add_argument("--focus", metavar="TEXT",
                       help="Free-text targeting constraint applied to THIS run's generation "
                            "(e.g. 'online only, fully automated, acute pain, makes money directly "
                            "online'). Overrides a profile's focus. Generation-only; never a gate.")

    # ---- generate subcommand (blue-sky: no signal) ----
    gen_p = sub.add_parser("generate", help="Blue-sky run: generate + vet candidates with no signal")
    gen_p.add_argument("--candidates", type=int, default=None, metavar="N",
                       help="Number of candidates to generate (default: config candidates_per_signal)")
    gen_p.add_argument("--exploration", type=float, default=None, metavar="X",
                       help="Override exploration level 0-1 (default: adaptive)")
    gen_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    gen_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    gen_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")
    gen_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane for generation + vetting (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    gen_p.add_argument("--persona", metavar="NAME",
                       help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                            "Default: config active_persona.")
    gen_p.add_argument("--profile", metavar="NAME",
                       help="Generation profile: a reusable steering bundle (restricted forms + "
                            "focus directive) from config 'profiles' (e.g. online_autonomous_predator).")
    gen_p.add_argument("--focus", metavar="TEXT",
                       help="Free-text targeting constraint applied to THIS run's generation "
                            "(e.g. 'online only, fully automated, acute pain, makes money directly "
                            "online'). Overrides a profile's focus. Generation-only; never a gate.")
    gen_p.add_argument("--resume", action="store_true",
                       help="Re-run generation for all pending signals that failed due to "
                            "generation chain exhaustion.  Reads signals from "
                            "signals/pending/ and re-runs the full pipeline (generate + vet). "
                            "Safe to re-run when the non-critical chain (DeepSeek/MiniMax/ "
                            "Gemini) recovers.")

    # ---- discover subcommand (spec EXTENSION: self-sourced signals) ----
    disc_p = sub.add_parser("discover",
                            help="Self-source N diverse signals, then sweep the pipeline over each (beyond original spec)")
    disc_p.add_argument("--signals", type=int, default=10, metavar="N",
                        help="Number of diverse signals to surface (default 10)")
    disc_p.add_argument("--sectors", metavar="LIST",
                        help="Comma-separated sectors to spread across (default: built-in broad set)")
    disc_p.add_argument("--count", type=int, default=None, metavar="N",
                        help="Candidates to generate per signal (default: config candidates_per_signal)")
    disc_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Only surface + save signals; do not generate or vet")
    disc_p.add_argument("--no-save", dest="no_save", action="store_true",
                        help="Do not write discovered signals to signals/")
    disc_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "minimax", "deepseek", "mock"],
                        help="Override operator from config")
    disc_p.add_argument("--lane", metavar="NAME",
                        help="Pin the sweep to a single ambition lane (default: multi-lane "
                             "across config active_lanes).")
    disc_p.add_argument("--persona", metavar="NAME",
                        help="Analytical persona to 'tint' the run (e.g. shark, minimalist, academic). "
                             "Default: config active_persona.")
    disc_p.add_argument("--fixtures", metavar="PATH",
                        help="Path to fixtures JSON (uses FixtureProvider)")
    disc_p.add_argument("--publish", action="store_true",
                        help="Generate listing artifacts + publish PASSes (extra model calls)")

    # ---- report subcommand ----
    rep_p = sub.add_parser("report", help="Read the catalogue, metrics, costs, generation quality, and trend (no model calls)")
    rep_view = rep_p.add_mutually_exclusive_group()
    rep_view.add_argument("--catalogue", action="store_true",
                          help="List vetted ideas grouped by decision + lane (default)")
    rep_view.add_argument("--metrics", action="store_true",
                          help="Truth-loop health: kill rate, per-lane breakdown, gate distribution")
    rep_view.add_argument("--costs", action="store_true",
                          help="Lifetime spend, tokens, slowest ops (errors excluded)")
    rep_view.add_argument("--generation-quality", dest="generation_quality", action="store_true",
                          help="Generation quality: form diversity, audience spread, prescreen rate")
    rep_view.add_argument("--trend", action="store_true",
                          help="Rolling 7/30/90d cohort trend: kill rate over time")
    rep_view.add_argument("--full", action="store_true",
                          help="All five views: catalogue + metrics + quality + trend + costs")
    rep_p.add_argument("--decision", choices=["pass", "kill", "defer"],
                       help="Filter the catalogue to one decision")

    # ---- diagnose subcommand ----
    diag_p = sub.add_parser("diagnose",
                            help="Calibration self-diagnostics (alarms; --deep runs the golden set)")
    diag_p.add_argument("--deep", action="store_true",
                        help="Run the golden set through the production brain chain (model calls)")
    diag_p.add_argument("--floor", type=float, default=0.75,
                        help="Min golden discrimination to count as OK (default 0.75)")

    # ---- operators subcommand ----
    op_p = sub.add_parser("operators",
                          help="Probe every operator: latency, health, circuit breakers, chain state")
    op_p.add_argument("--timeout", type=float, default=60.0,
                     help="Per-operator probe timeout in seconds (default: 60)")
    op_p.add_argument("--gen", action="store_true",
                     help="Also run a generation-prompt probe (tests full prompt size)")

    # ---- lanes subcommand ----
    lanes_p = sub.add_parser("lanes", help="Manage ambition lanes (list, nix, natch, set, unset)")
    lanes_act = lanes_p.add_subparsers(dest="lanes_action", required=True)

    lanes_act.add_parser("list", help="Show all defined lanes and active configuration")

    nix_p = lanes_act.add_parser("nix", help="Remove a lane from active_lanes")
    nix_p.add_argument("lane", help="Lane name to remove")

    natch_p = lanes_act.add_parser("natch", help="Add a lane to active_lanes")
    natch_p.add_argument("lane", help="Lane name to add")

    set_p = lanes_act.add_parser("set", help="Set active_lane (single-lane pin; empty = unset / multi-lane)")
    set_p.add_argument("lane", nargs="?", default="", help="Lane name (omit or empty to unset)")

    lanes_act.add_parser("unset", help="Clear active_lane (return to multi-lane mode)")

    args = parser.parse_args()

    # Keep the verbose JSON audit log out of the way (it goes to a tail-able file);
    # the console shows the human progress stream. PROSPECTOR_JSON_LOG=stderr opts out.
    cfg_for_log = load_config(args.config if args.config else None)
    from .telemetry import route_logs_to_file
    log_path = cfg_for_log.store_dir / "prospector.jsonl"
    route_logs_to_file(str(log_path))
    from . import progress
    progress.note(f"audit log → {log_path}")

    if args.command == "vet":
        _cmd_vet(args, log_path)
    elif args.command == "signal":
        _cmd_signal(args, log_path)
    elif args.command == "generate":
        _cmd_generate(args, log_path)
    elif args.command == "discover":
        _cmd_discover(args, log_path)
    elif args.command == "report":
        _cmd_report(args, cfg_for_log, log_path)
    elif args.command == "diagnose":
        _cmd_diagnose(args, cfg_for_log, log_path)
    elif args.command == "operators":
        _cmd_operators(args)
    elif args.command == "lanes":
        _cmd_lanes(args, log_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

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
from typing import NamedTuple, Optional

# Max candidates vetted in parallel. Each vet drives slow CLI subprocesses, so the
# real throughput ceiling is retrieval.claude_concurrency; this caps how many candidate
# vets are in flight at once. Sourced from config (retrieval.vet_workers).
# Keep it <= retrieval.claude_concurrency so workers do not self-induce queue_timeout —
# oversubscribing the CLI is what produced the ~3s HTTP-429 failures that flapped the moat
# on 2026-08-06. PROSPECTOR_VET_WORKERS overrides for ops. Not a verdict knob.
def _vet_workers(cfg) -> int:
    env = os.environ.get("PROSPECTOR_VET_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, int(getattr(cfg.retrieval, "vet_workers", 3)))


# Kill-fast is a rule about IDEAS: stop paying for a candidate the moment one gate is decisive.
# This is that rule applied to INFRASTRUCTURE, and it had no implementation until 2026-08-06.
# That day's 10:00 UTC batch vetted 14 candidates end-to-end and deferred all 14. The
# non-critical chain that generates each check's search queries had been benched by a monthly
# spend limit, so 52 of 98 checks never produced a query — and a check with no query has no
# passages, which verify.py reports as retrieval_failed -> DEFER_GATE. Retrieval was healthy
# throughout (200/200 ddg searches `ok`, every completed search 5-42 passages), which is why a
# preflight probe would NOT have caught this: the subsystem that died is not the one we probe.
# Nothing counted defers ACROSS candidates, so candidates 3..14 each re-learned the same
# outage at full price, and all 14 landed in a backlog the drain must pay for a SECOND time.
#
# Deliberately cause-agnostic. Three different subsystems (query-gen, retrieval, the moat)
# produce an identical batch-level signature, and on 2026-08-06 two confident diagnoses of
# which one it was were both wrong. Counting the signature is reliable; inferring the cause
# from inside the batch is not.
#
# A STREAK, not a total: a healthy batch may legitimately defer one or two candidates, so only
# CONSECUTIVE infra-gated defers mean the subsystem is down rather than the ideas being
# awkward. 0 disables. Not a verdict knob — it can only stop work, never change a ruling.
def _infra_abort_streak(cfg) -> int:
    env = os.environ.get("PROSPECTOR_INFRA_ABORT_STREAK")
    if env:
        return max(0, int(env))
    return max(0, int(getattr(cfg.retrieval, "infra_defer_abort_streak", 3)))


def _infra_abort_check(dossier, streak: int, threshold: int, pending) -> tuple:
    """Advance the consecutive-infra-defer streak; cancel un-started vets if it trips.

    Returns ``(new_streak, cancelled_or_None)``. ``cancelled_or_None`` is ``None`` while the
    batch should keep going, otherwise the number of vets cancelled before they started.

    Only ``Future.cancel()`` is used, which by contract refuses a vet that is already running.
    So an abort can never discard a verdict we have paid for — it declines to buy more.
    """
    streak = streak + 1 if dossier.gate_fired in _INFRA_GATES else 0
    if not threshold or streak < threshold:
        return streak, None
    return streak, sum(1 for f in pending if f.cancel())


def _sync_cli_concurrency(cfg) -> None:
    """Apply retrieval.*_concurrency to CLI governors (env vars still win when set)."""
    r = getattr(cfg, "retrieval", None)
    if r is None:
        return
    try:
        from .claude_cli import configure_concurrency as _claude_conc
        _claude_conc(int(getattr(r, "claude_concurrency", 2) or 2))
    except Exception:
        pass


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


def _save_pending_signal(signal_text: str, cfg: Config) -> Optional[Path]:
    """Persist a failed signal so `generate --resume` can retry it later.

    Returns the path on a CONFIRMED write, or None if the signal could not be
    durably saved. A write failure here means the signal would be silently lost,
    so it is logged at ERROR (not warning) and surfaced to the caller — never
    swallowed as if the deferral succeeded.
    """
    import hashlib
    key = hashlib.sha1(signal_text.encode()).hexdigest()[:16]
    path = _PENDING_DIR / f"{key}.json"
    try:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"signal_text": signal_text, "key": key}), encoding="utf-8")
        tmp.replace(path)  # atomic publish — a half-written file is never resumed
        if not path.exists():
            raise OSError(f"pending signal not present after write: {path}")
        return path
    except Exception as e:
        logger.error(
            f"FAILED to persist pending signal {key} — it will NOT be resumable: {e}",
            extra={"signal_key": key, "pending_dir": str(_PENDING_DIR)},
        )
        return None


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
from . import drain_state
from .dedup import dedup, drops_by_market
from .dossier import build_dossier, render_markdown
from .errors import GroundingInfrastructureError, ProviderExhaustedError
from .generate import generate
from .models import DEFER_GATE, Candidate, Decision, Dossier

#: Gates meaning "the pipeline could not rule", as opposed to "this idea failed". Both are set
#: by verify.py when a check never got an answer — never by a grounded verdict. Defined here
#: rather than beside `_infra_abort_check` above, because this module's early helper block
#: precedes its import block: a module-level tuple there evaluates DEFER_GATE too soon.
_INFRA_GATES = (DEFER_GATE, "moat_exhausted")
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


# Non-critical chain order: claude_cli (subscription) → minimax emergency tail.
# Founder directive 2026-08-06: "we need to use claude code and minimax".
#
# This was `(deepseek, cursor_cli, minimax)`. Both leading tiers were measured DEAD on
# 2026-08-06 — one JSON call to each configured brain:
#
#     deepseek    RuntimeError: DeepSeek call failed: HTTP Error 402: Payment Required
#     cursor_cli  ProviderExhaustedError: cursor cli exit 1: ActionRequiredError:
#                 You've hit your usage limit
#     minimax     OK
#     claude_cli  OK
#
# So EVERY generation, prescreen and score call was being served by minimax — the guardrailed
# emergency tail — after paying two guaranteed failures first. Nothing raised and nothing was
# logged above INFO, so from the outside the chain looked healthy: that is the failure mode of a
# fallback that works. The tail is not a neutral place to land, either: minimax was measured
# NON-DETERMINISTIC on the classify call at temperature 0.0 (4 of 6 candidates returned a
# different tier across 3 repeat runs), while claude_cli returned the identical answer 18/18.
#
# claude_cli is in MOAT_PRIMARY (operator.py:875), so this does put a moat brain on the
# non-critical chain. That is a deliberate, founder-directed change to the rule in CLAUDE.md,
# and it is not unprecedented: `_build_artifact_op` below has always generated the customer-
# facing pack prose on the CLI operators. The rule that still binds absolutely is the one about
# VERDICTS: DeepSeek/MiniMax never rule as trusted-final — is_provisional_provider enforces it.
# PROCESS RISK, stated as such: claude_cli work is slot-governed (cli_governor), so a large
# non-critical burst can now queue behind — or ahead of — the daemon's verdict calls. It costs
# throughput, not correctness. Restoring deepseek/cursor_cli is a one-line change when billing
# and usage limits recover; their breakers already half-open on their own.
#
# Ollama REJECTED 2026-07-01 (markdown, not JSON). Module-level so run_signal, `operators`, and
# the proof tools all reference the SAME chain.
_NONCRITICAL_ORDER = ("claude_cli", "minimax")


# ---------------------------------------------------------------------------
# Core vetting unit
# ---------------------------------------------------------------------------

@track_latency(name="vet_candidate")
def _build_artifact_op(cfg: Config, fallback_op: Operator) -> Operator:
    """Build the quality chain for the customer-facing £49 deliverable.

    The pack's prose (build_spec / gtm_plan / ops_plan / listing_page) IS the product, so it
    is generated by the CLI-based, in-subscription operators in ``cfg.artifact_operator``
    (Gemini CLI primary -> Claude CLI failover) rather than the cheap non-critical tail. Each
    tier is circuit-broken against the NON-CRITICAL health file (a CLI hiccup here must never
    blind the Claude->Gemini moat verdict path). Falls back to ``fallback_op`` (the moat) when
    none of the configured CLI operators are available, so generation never hard-fails on this.
    """
    from .operator import _build_operator, FallbackOperator
    from .health import get_noncritical_health

    order = cfg.artifact_operator
    if isinstance(order, str):
        order = [order]
    tiers = []
    for kind in (order or []):
        try:
            tiers.append((kind, _build_operator(kind, cfg, fast=False)))
        except RuntimeError:
            pass  # CLI not on PATH / not configured — skip this tier
    if not tiers:
        logger.warning("Artifact quality chain %s unavailable; using moat op for the deliverable",
                       order)
        return fallback_op
    if len(tiers) == 1:
        logger.info("Artifact deliverable operator: %s", tiers[0][0])
        return tiers[0][1]
    r = cfg.retrieval
    logger.info("Artifact deliverable chain: %s", " → ".join(n for n, _ in tiers))
    return FallbackOperator(tiers, failure_threshold=r.breaker_failure_threshold,
                            cooldown_s=r.breaker_cooldown_s, health=get_noncritical_health())


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
    # claude-cli/default").  FallbackOperator.name is already in that format.
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
            # The £49 deliverable's prose runs on the quality CLI chain (Gemini CLI -> Claude
            # CLI), not flash-lite. The financial model (Python-computed) and ancillary
            # marketing stay on fast_op; claim-check runs on the moat `op` (a verification gate
            # must never be judged by the cheap model that wrote the copy).
            quality_op = _build_artifact_op(cfg, op)
            cand.tags["artifacts"] = generate_artifacts(
                op, cand, checks, fast_op=query_op, quality_op=quality_op, cfg=cfg)
            cand.tags["marketing"] = generate_marketing_content(
                op, cand, checks, fast_op=query_op, quality_op=quality_op, check_op=op)

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
    _sync_cli_concurrency(cfg)

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
    from .errors import GroundingInfrastructureError, ProviderExhaustedError
    from .telemetry import record_usage
    from .health import get_noncritical_health

    # Founder-fence: the non-critical chain records exhaustion to its OWN health file,
    # never the moat's. A dead DeepSeek/MiniMax/Gemini-flash here must not blind the
    # Claude→Gemini moat (and vice versa).
    _noncritical_health = get_noncritical_health()

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
                                cooldown_s=r.breaker_cooldown_s,
                                health=_noncritical_health)
        logger.info(f"Chain: {' → '.join(n for n, _ in tiers)}")
        return chain

    # gen_op: divergent candidate generation (non-critical).
    gen_op = _build_operator_chain(_NONCRITICAL_ORDER, fast=True)

    # fast_op: prescreen / scoring / mechanical JSON (non-critical), same order.
    fast_op = _build_operator_chain(_NONCRITICAL_ORDER, fast=True)

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

    # CROSS-RUN ANTI-DUPLICATION MEMORY. The blue-sky daemon re-runs generation every cycle;
    # without telling the model what it has ALREADY produced (PASS and KILL alike), it keeps
    # regenerating the same idea families (the live near-duplicate probate packs). Seed the
    # generator's `avoid` list from the freshest dossier titles so it explores NEW ground.
    prior_titles = store.recent_titles(limit=200)

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
            prior_titles=prior_titles,
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
            pass_patterns=patterns, prior_titles=prior_titles)
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
            pass_patterns=patterns, prior_titles=prior_titles,
        )
    if not candidates:
        # Generation chain exhausted — save the signal text so the operator can
        # re-run it later with `generate --resume`.  Never lose a signal.
        _save_pending_signal(signal_text, cfg)
        logger.warning(f"Generation chain exhausted ({'/'.join(_NONCRITICAL_ORDER)} all "
                       f"unavailable or quota depleted). Signal saved for retry. Run "
                       f"`generate --resume` when generation chain recovers.")
        progress.step(f"generation chain exhausted — signal saved, re-run with generate --resume")
        return []
    logger.info(f"Generated {len(candidates)} candidates")
    progress.step(f"generated {len(candidates)} candidates")

    # --- Dedup against catalogue (per market: the same idea elsewhere is not a dupe) ---
    catalogue = store.catalogue_titles()
    unique, dropped = dedup(candidates, catalogue, threshold=cfg.dedup_threshold,
                            token_threshold=cfg.dedup_token_threshold,
                            default_market=_default_market(cfg))
    if dropped:
        by_market = drops_by_market(dropped)
        logger.info(f"Dedup dropped {len(dropped)} near-duplicate pair(s)",
                    extra={"dropped_by_market": by_market})
        detail = " ".join(f"{m or 'unset'}:{n}" for m, n in sorted(by_market.items()))
        progress.note(f"dedup dropped {len(dropped)} near-duplicate(s) [{detail}]")

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
    from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
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
        infra_abort = _infra_abort_streak(cfg)
        infra_streak = 0
        infra_aborted = False
        n_cancelled = 0
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

                # Kill-fast on INFRASTRUCTURE (see _infra_abort_streak). Counted AFTER the
                # dossier is kept: work already paid for is banked, never discarded. Only
                # UN-STARTED vets are cancelled, so this can lose no evidence — it can only
                # decline to buy more of it while the pipeline is unable to rule.
                infra_streak, cancelled = _infra_abort_check(
                    d, infra_streak, 0 if infra_aborted else infra_abort, fut_meta)
                if cancelled is not None:
                    infra_aborted = True
                    n_cancelled = cancelled
                    msg = (f"INFRA ABORT: {infra_streak} consecutive candidates deferred on "
                           f"gate={d.gate_fired!r} — the pipeline cannot rule, so this is an "
                           f"outage, not a verdict. Cancelled {n_cancelled} un-started vet(s) "
                           f"of {total_submitted}; {len(dossiers)} kept.")
                    # CRITICAL: the daemon's launchd log drops info/warning, so a quieter
                    # level here would make the abort invisible exactly where it matters.
                    logger.critical(msg, extra={"infra_gate": d.gate_fired,
                                                "cancelled": n_cancelled,
                                                "submitted": total_submitted})
                    print(f"⏸ {msg}", file=sys.stderr, flush=True)
                    progress.note(f"⏸ {msg}")
            except CancelledError:
                # A vet this loop cancelled above — expected, not an error. It must be caught
                # HERE: since 3.8 CancelledError derives from BaseException, so the generic
                # `except Exception` below cannot see it and it would escape and kill the batch.
                continue
            except GroundingInfrastructureError:
                raise  # circuit breaker — halt daemon, don't burn credits
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

    # Per-batch funnel diagnostics — emitted on EVERY generation run (founder
    # requirement 2026-06-22: every generation ships WITH diagnostics). Purely
    # additive instrumentation: derived from this batch's own dossiers + the
    # top-of-funnel counts already in scope. Wrapped so a diagnostics failure can
    # never break a run. Written to store/scheduler/{DIAGNOSTICS_LATEST.txt,
    # batch_diagnostics.jsonl}.
    try:
        from .diagnostics import diagnose_batch, persist_batch_diagnostics, render_batch_diagnostics
        stage_counts = {
            "generated": len(candidates),
            "dedup_dropped": len(dropped),
            "rejection_fastpath": len(unique) - len(final_candidates),
            "prescreen_in": len(final_candidates),
            "prescreened_out": len(final_candidates) - len(prescreened_data),
            "novelty_selected": len(kept),
            "vetted": len(dossiers),
        }
        _bd = diagnose_batch(dossiers, stage_counts=stage_counts, usage=usage, cfg=cfg)
        persist_batch_diagnostics(_bd, store)
        progress.note("📊 batch diagnostics → store/scheduler/DIAGNOSTICS_LATEST.txt")
        logger.info("batch diagnostics written", extra={"funnel": stage_counts,
                    "unverifiable_pct": _bd.get("unverifiable_pct"),
                    "decisions": _bd.get("decisions")})
    except Exception as _diag_exc:  # never let diagnostics break a run
        logger.warning(f"batch diagnostics failed (non-fatal): {_diag_exc}")

    return dossiers



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_market(cfg: Config) -> str:
    """The market unmarked candidates and legacy catalogue rows belong to."""
    try:
        return cfg.active_market or cfg.default_market
    except AttributeError:  # Config predating Epic D
        return ""


def _guard_market_open(cfg: Config, args: argparse.Namespace) -> None:
    """Refuse to run against a market that has not passed its readiness probe.

    A market is CLOSED until a calibration probe demonstrates the engine can actually
    see it (specs/multi-market-dimension.md §4). Generating into an unproven market
    would mint dossiers whose grounding nobody has measured — the exact thing the gate
    exists to prevent. `--probe` is the one sanctioned way past this, and it is what
    `markets probe` uses to run the calibration itself.
    """
    if getattr(args, "probe", False):
        return
    status = cfg.market_status(cfg.active_market)
    if status != "open":
        code = cfg.active_market
        ref = cfg.market_config(code).get("readiness_ref") or f"store/markets/{code}/READINESS.json"
        print(f"error: market {code!r} is {status}, not open.\n"
              f"  Run the readiness probe first:\n"
              f"    python -m prospector.run markets probe --market {code} "
              f"--set markets/calibration/{code.split('-')[0]}.jsonl\n"
              f"  Then, if it passes: markets open {code}  (reads {ref})",
              file=sys.stderr)
        sys.exit(2)


def _build_config_and_overrides(args: argparse.Namespace) -> Config:
    """Load config and apply CLI overrides (operator, retrieval provider)."""
    cfg = load_config(args.config if args.config else None)

    if hasattr(args, "operator") and args.operator:
        cfg.operator = args.operator

    # If fixtures provided, switch retrieval provider to fixture mode
    if hasattr(args, "fixtures") and args.fixtures:
        cfg.retrieval.provider = "fixture"

    # Market override (Epic D): which JURISDICTION this run generates/vets for. Applied
    # BEFORE the lane because it is the outer context (the evidence terrain), and because
    # for_lane/for_profile/for_persona preserve active_market through dataclasses.replace.
    if getattr(args, "market", None):
        cfg = cfg.for_market(args.market)
    # Guard the EFFECTIVE market, not just an explicit --market. A closed market can
    # also arrive via `active_market:`/`markets.default:` in config.yaml, and that
    # route must not be the one way to mint dossiers into an unproven jurisdiction.
    # hasattr, not truthiness: only the market-aware commands own this dimension.
    if hasattr(args, "market"):
        _guard_market_open(cfg, args)

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

    # Founder-archetype override (generation-only). Applied last so it wins over lane
    # defaults; for_lane re-applies active_archetype for multi-lane fan-out.
    if getattr(args, "archetype", None):
        from .config import UnknownArchetypeError
        try:
            cfg = cfg.for_archetype(args.archetype)
        except UnknownArchetypeError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)

    return cfg


def _make_search(cfg: Config, args: argparse.Namespace) -> SearchProvider:
    """Build the SearchProvider, injecting fixtures when --fixtures is passed."""
    from .retrieval import make_provider

    fixtures = None
    if hasattr(args, "fixtures") and args.fixtures:
        with open(args.fixtures, encoding="utf-8") as fh:
            fixtures = json.load(fh)

    return make_provider(cfg, fixtures=fixtures)


def _add_market_args(p: argparse.ArgumentParser) -> None:
    """Attach the market flags shared by vet/signal/generate/discover."""
    p.add_argument("--market", metavar="CODE",
                   help="Jurisdiction to generate/vet for (e.g. uk, us, us-tx). "
                        "Default: config active_market, else markets.default. "
                        "A market that has not passed its readiness probe is refused.")
    p.add_argument("--probe", action="store_true",
                   help="Calibration run: permit a non-open market. Used by "
                        "`markets probe`; results never publish.")


def _add_archetype_arg(p: argparse.ArgumentParser) -> None:
    """Attach --archetype (generation-only founder-capacity pin)."""
    p.add_argument("--archetype", metavar="NAME",
                   help="Founder archetype for generation (solo_agent, small_team, "
                        "startup). Overrides the lane default. Generation-only — "
                        "never moves gates or thresholds.")


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
        _cmd_resume(args, cfg, op, fast_op, search, store, log_path)
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


def _cmd_replicate(args: argparse.Namespace, log_path: Path) -> None:
    """Re-vet proven PASSes from one market as candidates in another.

    The cheapest high-quality generation channel available: an idea that already cleared
    the bar somewhere is a better-than-random hypothesis elsewhere. What does NOT carry
    over is the evidence — every verdict, source and score is re-earned from scratch
    against the target market's own chain. A replicated PASS is a new PASS, or it is a
    KILL with its own cited reason.
    """
    from .operator import make_operator
    from .telemetry import get_usage_summary, reset_usage
    from . import progress

    source_market = args.source_market.lower()
    cfg = _build_config_and_overrides(args)  # --market is the TARGET (gate-checked)
    target_market = cfg.active_market or _default_market(cfg)
    if source_market == target_market:
        print(f"error: --from and --market are both {target_market!r}; nothing to replicate.",
              file=sys.stderr)
        sys.exit(2)

    store = Store(cfg)
    # The index carries `market`, so filter there rather than opening 1,000+ JSON files.
    rows = [r for r in store.all(decision=Decision.PASS.value)
            if (r.get("market") or "").lower() == source_market]
    min_composite = getattr(args, "min_composite", None)
    if min_composite is not None:
        rows = [r for r in rows
                if float(r.get("composite") or 0.0) >= min_composite]
    rows = sorted(rows, key=lambda r: float(r.get("composite") or 0.0), reverse=True)
    rows = rows[: (args.n or len(rows))]

    if not rows:
        print(f"No PASS dossiers in market {source_market!r} to replicate.")
        return

    print(f"Replicating {len(rows)} PASS candidate(s): {source_market} → {target_market}")
    clones: list[Candidate] = []
    for row in rows:
        full = store.get(row.get("candidate_id", "")) or {}
        if not full:
            continue
        src = Candidate.from_dict(full.get("candidate", {}))
        clone = Candidate(
            title=src.title, one_liner=src.one_liner, hypothesis=src.hypothesis,
            who_pays=src.who_pays, why_now=src.why_now,
            tags={**dict(src.tags or {}), "replicated_from": src.candidate_id,
                  "replicated_from_market": source_market},
            automatability=src.automatability,
            structural_form=src.structural_form, ambition_tier=src.ambition_tier,
            market=target_market)  # candidate_id left blank => re-derived WITH the market
        if clone.candidate_id == src.candidate_id:
            # Cannot happen once market participates in the hash, but if it ever did the
            # save would overwrite the source dossier — refuse rather than destroy it.
            print(f"error: clone of {src.candidate_id} collides with its source; aborting.",
                  file=sys.stderr)
            sys.exit(3)
        clones.append(clone)

    if getattr(args, "dry_run", False):
        for c in clones:
            print(f"  {c.candidate_id}  {c.title[:60]}")
        print("\nDRY RUN — nothing vetted. Drop --dry-run to run the full vet.")
        return

    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    search = _make_search(cfg, args)

    n_pass = n_kill = n_defer = 0
    for clone in clones:
        progress.banner(f"Replicating into {target_market}: {clone.title!r}")
        d = vet_candidate(clone, op, search, cfg, store=store, query_op=fast_op,
                          publish=getattr(args, "publish", False), show_checks=False)
        n_pass += d.decision == Decision.PASS
        n_kill += d.decision == Decision.KILL
        n_defer += d.decision == Decision.DEFER
        print(f"  {d.decision.value.upper():5s}  {clone.title[:56]}"
              f"{'  gate=' + d.gate_fired if d.gate_fired else ''}")

    progress.summary(n_pass=n_pass, n_kill=n_kill, n_defer=n_defer)
    from .report import costs_report
    print(f"\n{costs_report(log_path or '')}")


#: Populations `vet --resume --only` can restrict the drain to. "all" is the default and the
#: historical behaviour; the daemon never passes this flag, so its per-tick drain is unchanged.
RESUME_SELECTORS = ("all", "defer", "provisional", "provisional-pass", "provisional-kill")


def _resume_selects(row: dict, only: str) -> bool:
    """Does this backlog row belong to the `--only` population?

    WHY THIS EXISTS. The drain sorts DEFER and provisional rows together, oldest first
    (see the comment at the `sorted(...)` call below), which is right for fairness and wrong
    for targeting. Measured on the live index 2026-08-06: of the OLDEST 100 drainable rows,
    51 were provisional KILLs, 47 were DEFERs, 1 was a provisional DEFER — and exactly
    **1** was a provisional PASS. The 72 provisional PASSes (the only population that can
    become sellable inventory, because a re-vet that confirms them clears
    `run.py:422`'s `not dossier.provisional` publish gate) are spread from 2026-06-21 to
    2026-08-06, so oldest-first buries them. Draining them via `--limit` alone would need
    the whole ~351-row backlog, which at the live batch's ~5.5 min/candidate is ~32 hours.

    A row's `decision` and `provisional` both come from `SELECT *` (`store.provisional()`
    and `store.all()`), so both keys are present on every row.
    """
    decision = str(row.get("decision", "") or "").lower()
    provisional = bool(row.get("provisional", 0))
    if only == "defer":
        return decision == "defer"
    if only == "provisional":
        return provisional
    if only == "provisional-pass":
        return provisional and decision == "pass"
    if only == "provisional-kill":
        return provisional and decision == "kill"
    return True


#: Drain priority. The bound is spent from rank 0 down, so this is the ONLY thing that decides
#: what a tick's money buys.
_RANK_PROVISIONAL_PASS = 0
_RANK_DEFER = 1
_RANK_PROVISIONAL_KILL = 2
_RANK_NAMES = {_RANK_PROVISIONAL_PASS: "provisional-pass",
               _RANK_DEFER: "defer",
               _RANK_PROVISIONAL_KILL: "provisional-kill"}


def _drain_rank(row: dict) -> int:
    """Which population this backlog row belongs to, ordered by what a re-vet can produce.

    WHY RANK AND NOT JUST AGE. Oldest-first is fair and, on this backlog, expensive: the three
    populations have completely different expected values and the sort could not see it.

      0  provisional PASS — a real PASS that the publish gate refuses solely because an untrusted
         brain ruled it (`decision == PASS and not provisional`). One confirming re-vet turns it
         into sellable inventory. This is the population the drain was BUILT for.
      1  DEFER — no verdict was ever reached, so the idea is unjudged. A re-vet produces the
         first real answer, whatever it is.
      2  provisional KILL — already dead. A re-vet can only confirm the kill (changing nothing
         that can ever be sold) or, rarely, resurrect a wrongly-killed idea.

    Measured on the live index 2026-08-06, oldest-first put rank 2 FIRST: of the oldest 100
    drainable rows, 51 were provisional KILLs and exactly 1 was a provisional PASS, while the 72
    provisional PASSes were spread from 2026-06-21 to 2026-08-06. At the daemon's 3-per-tick
    bound, age order spends the budget almost entirely on rank 2. Rank order spends it on rank 0
    until there are none left, which is the whole point of running a drain at all.

    Age still breaks ties WITHIN a rank (`_cmd_resume`'s sort key), so nothing starves.
    """
    decision = str(row.get("decision", "") or "").lower()
    provisional = bool(row.get("provisional", 0))
    if provisional and decision == "pass":
        return _RANK_PROVISIONAL_PASS
    if decision == "defer":
        return _RANK_DEFER
    return _RANK_PROVISIONAL_KILL


class DrainSurvey(NamedTuple):
    """The backlog split into what a drain pass can move and what it provably cannot.

    `workable` is THE definition of "backlog" for every caller — the drain's bound is spent on
    it, and the scheduler's brake counts it. `orphaned`, `stalled` and `unpublishable` are the
    excluded rows, carried out by candidate_id so every caller can report them instead of
    absorbing them.
    """

    workable: list[dict]
    orphaned: list[str]
    stalled: list[str]
    unpublishable: list[str]


def drain_survey(store: Store, *, max_attempts: int = 0,
                 revet_provisional_kills: bool = True) -> DrainSurvey:
    """Split the DEFER + provisional population into workable rows and unmovable ones.

    Two populations need the moat to revisit them:
      1. DEFER — the moat was unavailable, so no verdict was reached at all.
      2. provisional — a real verdict WAS reached, but by the cheap emergency fallback tail
         (moat exhausted). Re-vet so the trusted moat overwrites the cheap ruling.
    De-duped by candidate_id (a dossier can't be both, but guard against overlap).

    Tombstoned rows are excluded from BOTH populations. A tombstone means the dossier is gone
    for good, so there is nothing to re-vet — and leaving them in inflated the backlog the
    operator reads (406 reported, 45 of them undrainable) and made the drain's ETA a fiction.
    They stay in the catalogue for history; they are just not work.

    THEN THREE EXCLUSIONS, all closing the same hole: a counted row the drain cannot move.

      * ORPHANED — an index row whose dossier JSON is not on disk. `store.get()` returns None
        and the drain can only print "dossier JSON missing, skipping". Measured 2026-08-06 on the
        live store: 46 of 406, with a leading unbroken run of 45 dated 2026-06-14..06-21, i.e.
        15 consecutive 3-row ticks (~1.2 days) of no-op drains reporting `attempted: 3`.
      * STALLED — a row that has absorbed `max_attempts` completed re-vets and is still
        drainable (`prospector/drain_state.py`). 0 disables this exclusion entirely.
      * UNPUBLISHABLE — a provisional row whose decision is already KILL, when
        `schedule.revet_provisional_kills` is False. The first two populations cannot be MOVED;
        this one moves fine and cannot PRODUCE, because a KILL never reaches the publish gate no
        matter which brain ruled it. Measured 2026-08-06: 161 of 318 drainable rows, ~$1.91 each,
        0 passes in the 15 drained that day — see `drain_state.revet_provisional_kills` for the
        full receipts. Excluding them is reversible config, not a tombstone: the rows keep their
        cited kill reason and `vet --resume --only provisional-kill` still reaches them.

    Why they belong HERE and not in `_cmd_resume`'s loop: the scheduler's backlog brake
    (`run_scheduled._backlog_size`) counts this same population to decide whether generation may
    run, and it releases itself when the count falls back under `schedule.backlog_cap`. Excluding
    unmovable rows only in the drain would leave the brake counting rows nothing can ever
    subtract — a generation freeze waiting on a number that cannot fall, with no human able to
    see why. One definition, or the rail deadlocks.

    A row that falls into more than one excluded class is reported once, in the order tested
    below; the lists are disjoint by construction, and either way the row is excluded.
    """
    deferred = [r for r in store.all(decision="defer") if not r.get("tombstone")]
    provisional = [r for r in store.provisional() if not r.get("tombstone")]
    seen_ids = {r.get("candidate_id", "") for r in deferred}
    rows = list(deferred) + [r for r in provisional
                             if r.get("candidate_id", "") not in seen_ids]

    attempts = drain_state.load(store.root) if max_attempts > 0 else {}
    workable: list[dict] = []
    orphaned: list[str] = []
    stalled: list[str] = []
    unpublishable: list[str] = []
    for row in rows:
        cid = str(row.get("candidate_id", "") or "")
        if max_attempts and attempts.get(cid, 0) >= max_attempts:
            stalled.append(cid)
        elif not store.has_dossier(cid):
            orphaned.append(cid)
        elif not revet_provisional_kills and _drain_rank(row) == _RANK_PROVISIONAL_KILL:
            # Tested AFTER the mechanical exclusions so a row that is both orphaned and
            # unpublishable is reported as orphaned — the older, load-bearing diagnosis.
            unpublishable.append(cid)
        else:
            workable.append(row)
    return DrainSurvey(workable, orphaned, stalled, unpublishable)


def drainable(store: Store, *, max_attempts: int = 0,
              revet_provisional_kills: bool = True) -> list[dict]:
    """The rows a re-vet pass can actually work on — `drain_survey(...).workable`.

    Kept as a name because callers and tests bind to it; see `drain_survey` for the definition
    and for why the exclusions live there rather than in the drain loop.
    """
    return drain_survey(store, max_attempts=max_attempts,
                        revet_provisional_kills=revet_provisional_kills).workable


def _with_exclusions(summary: dict, survey: DrainSurvey) -> dict:
    """Ride the excluded counts into the drain summary on EVERY return path.

    `orphaned` used to be attached on one path only — the one that actually ran a pass — so the
    tick that excluded every row returned a clean-looking `attempted: 0` and named no reason for
    it. The summary is what reaches `ticks.jsonl` and the state probe, so a count that is not in
    here is a count no operator will ever see.
    """
    if survey.orphaned:
        summary["orphaned"] = len(survey.orphaned)
    if survey.stalled:
        summary["stalled"] = len(survey.stalled)
    if survey.unpublishable:
        summary["unpublishable"] = len(survey.unpublishable)
    return summary


def _cmd_resume(args: argparse.Namespace, cfg: Config, op: Operator,
                fast_op: Operator, search: SearchProvider, store: Store,
                log_path: Optional[Path] = None) -> dict:
    """Re-vet all moat-deferred candidates.

    Called when `vet --resume` is used or when the moat comes back online after an outage.
    Loads each deferred candidate, re-runs the full verification pipeline (not partial —
    the moat is now available, so we run everything), and overwrites the DEFER decision
    with the fresh verdict.  Candidates that were deferred due to a real retrieval
    outage (not moat exhaustion) are also retried.

    `args.limit` bounds one pass. The unattended daemon sets it (see
    `scheduler/run_scheduled.py::_default_generate`) because the spend guard is evaluated
    once per tick, BEFORE the tick runs — an unbounded drain of a large backlog would run
    entirely inside a single guard decision and could clear the daily cap in one tick.
    On the CLI it defaults to unbounded, which is the behaviour this command has always had.

    Returns a summary dict so a caller (the daemon) can record what the pass did; the CLI
    ignores the return and reads the printed report.
    """
    # PARSE `--only` BEFORE the survey, because it decides what the survey may exclude.
    # `getattr` default keeps `resume_deferred`'s Namespace (the daemon's entry point, which has
    # no `only` attribute) on the historical "all" behaviour.
    only = str(getattr(args, "only", "all") or "all")
    if only not in RESUME_SELECTORS:
        print(f"Unknown --only {only!r}; expected one of {', '.join(RESUME_SELECTORS)}.",
              file=sys.stderr)
        sys.exit(2)

    max_att = drain_state.max_attempts(cfg)
    # An operator who NAMES the dead population gets it, whatever the config default says. The
    # exclusion exists to stop provisional KILLs silently eating the daemon's automatic bound;
    # it is not a lock on the rows, and `--only provisional-kill` is the documented way back in.
    revet_dead = (drain_state.revet_provisional_kills(cfg)
                  or only in ("provisional", "provisional-kill"))
    survey = drain_survey(store, max_attempts=max_att, revet_provisional_kills=revet_dead)
    pending = survey.workable
    backlog = len(pending)
    excluded = ""
    if survey.orphaned or survey.stalled or survey.unpublishable:
        # NAMED, not absorbed. These rows are the reason a backlog count can stop falling, so the
        # one place an operator is looking (the drain's own output, and the summary that reaches
        # ticks.jsonl) has to say how many were set aside and where the reversal switch is.
        parts = []
        if survey.orphaned:
            parts.append(f"{len(survey.orphaned)} orphaned (index row, no dossier JSON on disk)")
        if survey.stalled:
            parts.append(f"{len(survey.stalled)} stalled (>= {max_att} unresolved re-vets; "
                         f"rm {drain_state.ledger_path(store.root)} to retry them)")
        if survey.unpublishable:
            parts.append(f"{len(survey.unpublishable)} provisional KILLs (already dead — a KILL "
                         f"never reaches the publish gate; set schedule.revet_provisional_kills: "
                         f"true, or run `vet --resume --only provisional-kill`, to work them)")
        excluded = " Excluded: " + "; ".join(parts) + "."
    if not pending:
        if excluded:
            print(f"No backlogged candidate the drain can work on.{excluded}")
        else:
            print("No deferred or provisional candidates to resume. Moat is healthy.")
        return _with_exclusions({"backlog": 0, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0}, survey)

    # MOAT PREFLIGHT — never drain into a blind moat.
    #
    # `run_scheduled.py` gained this precondition for GENERATION on 2026-08-06 (392ce4c); the
    # drain never had one, and the standalone `vet --resume` invocation does not go through the
    # scheduler at all. Measured 2026-08-06 with `operator: [claude_cli]` — a ONE-brain moat —
    # marked dead for 3033s: the drain kept running and every re-vet raised
    # ProviderExhaustedError, which `verify.py` turns into retrieval_failed -> DEFER_GATE ->
    # Decision.DEFER. Over one 30-minute window that moved provisional -14 / defer +13: a net
    # backlog change of -1 for a full pass of CLI spend. The rows were relabelled, not resolved.
    #
    # Worse than useless: the drain competes for the same subscription CLI as the daemon, and
    # 392ce4c's own commit message records that the drain's load was implicated in the moat
    # flapping that minted the provisional rows in the first place. A drain that runs while the
    # brain is benched is helping to keep it benched.
    #
    # Deliberately no --force override: when no trusted brain can rule, there is no verdict to
    # be had, so "force" would only buy a more expensive way to write DEFER.
    from .health import moat_blind_reason
    blind = moat_blind_reason(cfg)
    if blind:
        print(f"Found {backlog} deferred + provisional candidate(s), but {blind}. "
              f"Re-vetting none — a drain into a blind moat only relabels rows "
              f"provisional->defer, and its own CLI load helps keep the brain benched.")
        return _with_exclusions({"backlog": backlog, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0, "skipped": blind}, survey)

    # Restrict to one population BEFORE the priority sort and the `--limit` slice, so the
    # bound is spent on the rows the operator asked for. `backlog` keeps counting the whole
    # drainable population: the printed line then reads "Found 351 ... re-vetting 72 of them",
    # which is the truth. (`only` is parsed and validated at the top of this function, because
    # it also decides whether the survey may exclude the provisional-KILL population.)
    if only != "all":
        pending = [r for r in pending if _resume_selects(r, only)]
        if not pending:
            print(f"Found {backlog} deferred + provisional candidate(s), but none match "
                  f"--only {only}. Nothing to re-vet.{excluded}")
            return _with_exclusions({"backlog": backlog, "attempted": 0, "resumed": 0,
                                     "passes": 0, "kills": 0, "defers": 0}, survey)

    limit = getattr(args, "limit", None)
    if limit is not None and limit <= 0:
        # 0 means "drain nothing" — NOT "drain everything". The old test was
        # `if limit is not None and limit > 0`, so a 0 fell through to the unsliced
        # `pending` and re-vetted the entire backlog (411 items on 2026-08-05) inside a
        # single guard decision. The daemon guards the call with `if n_resume:`, so it was
        # unreachable from there, but `schedule.resume_per_tick: 0` is documented as
        # "disables the drain entirely" (run_scheduled.py:83) and `_resume_per_tick` floors
        # negatives to 0 — one config edit or one direct call away from the exact unbounded
        # pass the spend rail exists to prevent. Only `None` (the CLI default) means
        # unbounded, which is what `vet --resume` has always done.
        print(f"Found {backlog} deferred + provisional candidate(s); limit={limit} "
              f"disables the drain — re-vetting none.{excluded}")
        return _with_exclusions({"backlog": backlog, "attempted": 0, "resumed": 0,
                                 "passes": 0, "kills": 0, "defers": 0}, survey)
    # HIGHEST-VALUE POPULATION FIRST, then oldest first within it (`_drain_rank`).
    #
    # Age alone was the whole sort key until 2026-08-06, and on this backlog it inverted the
    # priority: of the oldest 100 drainable rows, 51 were provisional KILLs — rows that cannot
    # publish under any verdict — and exactly 1 was a provisional PASS, the population a single
    # confirming re-vet turns into sellable inventory. At the daemon's 3-per-tick bound the
    # budget went almost entirely to the rows with nothing to produce.
    #
    # Age still decides WITHIN a rank, which is what the old comment was protecting: `store.all`
    # returns catalogue order, this backlog reaches back to 2026-06-14, and newest-first would
    # starve the oldest rows forever at 3 per tick. Nothing starves; the ranks just get served
    # in the order of what they can produce.
    pending = sorted(pending, key=lambda r: (_drain_rank(r), str(r.get("created_at", ""))))

    # UNMOVABLE ROWS MUST NOT CONSUME THE BOUNDED PASS — and `drain_survey` has already taken
    # them out, so this slice is a plain one.
    #
    # The exclusion used to happen HERE, inside the `limit` slice, and only for orphans. That was
    # right for the drain and wrong for the system: `run_scheduled._backlog_size` counts the same
    # population to decide whether generation may run, and it kept counting the rows this loop was
    # skipping — so the brake could sit engaged on a number no drain could ever reduce. Moving
    # both exclusions into `drain_survey` is what makes the brake self-releasing rather than a
    # freeze that outlives the reason for it.
    #
    # PROVEN on the live store 2026-08-06, first tick that ever ran the drain:
    #   ticks.jsonl result -> 'resumed': {'backlog': 406, 'attempted': 3, 'resumed': 0, ...}
    #   backlog 406, orphaned 46, leading unbroken run of orphans 45 (2026-06-14..06-21)
    # At 3 per tick that is 15 consecutive ticks — ~1.2 days — of no-op drains reporting
    # `attempted: 3` before the pass reaches its first real candidate.
    if limit is not None:
        pending = pending[:limit]

    # NAME THE MIX, not just the count. A bounded pass that reports only "re-vetting 3 of them"
    # cannot be told apart from one spending its whole budget on rows that can never publish —
    # which is exactly what was happening before the rank sort, unnoticed, for six weeks.
    _ranks = [_drain_rank(r) for r in pending]
    mix = ", ".join(f"{_ranks.count(i)} {_RANK_NAMES[i]}"
                    for i in sorted(set(_ranks)))
    print(f"Found {backlog} deferred + provisional candidate(s); re-vetting "
          f"{len(pending)} of them with the moat ({mix}; highest-value population "
          f"first)...{excluded}")
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

        # PER-ROW ATTEMPT ACCOUNTING. Only a COMPLETED re-vet with a verdict counts, and only if
        # that verdict left the row in the backlog — a DEFER, or a ruling that is provisional
        # again. The two outage paths never reach here (a blind moat returns before the loop; a
        # ProviderExhaustedError breaks out of it above), which is the point: the backlog exists
        # because of outages, so an outage must not be able to spend a row's budget.
        #
        # A resolved row is FORGOTTEN rather than left at its count, so if a later re-save puts it
        # back in the backlog it starts from a full budget instead of inheriting a spent one.
        if max_att:
            if d.decision == Decision.DEFER or bool(getattr(d, "provisional", False)):
                n = drain_state.record_unresolved(store.root, cid)
                if n >= max_att:
                    progress.note(
                        f"{cid}: {n} completed re-vets, still unresolved — no longer counted as "
                        f"backlog, so the generation brake can release. "
                        f"rm {drain_state.ledger_path(store.root)} to retry it.")
            else:
                drain_state.forget(store.root, cid)
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
    summary = {"backlog": backlog, "attempted": len(pending), "resumed": len(resumed_dossiers),
               "passes": n_pass, "kills": n_kill, "defers": n_defer,
               # In the RETURN value, not just the print above. Under launchd this function's
               # stdout is fd 1 → store/scheduler/launchd.out.log (measured on pid 48771 via
               # lsof), which nothing reads and which Python block-buffers because it is a
               # file — so at 00:58 the tick's cost report was still sitting unflushed in the
               # process. The summary dict is the stream that survives: run_scheduled.py:190
               # logs it to stderr and it lands in the tick row.
               #
               # `metered_usd`, NOT `cost_usd`. This is billed money only — the figure
               # `daily_cap_usd` enforces. It is legitimately 0.00 for a drain that ran on the
               # Claude Code subscription, which is the moat's primary brain, so a key called
               # `cost_usd` reading 0.0 would say "the drain was free" when it in fact spent
               # subscription allowance. The other leg is already in the same tick row as
               # `today_subscription_usd` (scheduler/guard.py:161). Two legs, two names —
               # guard.py:21-45 has the full measurement of why they must never be added up.
               "metered_usd": round(usage.get("total_cost_usd", 0.0), 4)}
    # Excluded counts surfaced into the tick row, so a store inconsistency or an exhausted attempt
    # budget is visible in ticks.jsonl and the state probe instead of showing up as an
    # inexplicable `attempted: 3, resumed: 0` — or, once the brake is engaged, as a generation
    # freeze with nothing anywhere naming the rows that are holding it.
    return _with_exclusions(summary, survey)


def resume_deferred(cfg: Config, *, limit: int | None = None,
                    publish: bool = False) -> dict:
    """Run one bounded re-vet pass over the DEFER + provisional backlog, in-process.

    THE GAP THIS CLOSES. `vet --resume` has always existed and always worked, but nothing
    ever called it. Measured 2026-08-05: 113 `*.defer.json` dossiers on disk, oldest
    2026-06-24, while `alerts.py:219` was telling the operator they "auto re-vet ... once
    the moat recovers". `grep -- --resume` over the repo found only log strings, the
    argparse flag, and docs — no scheduler path and none of the four launchd plists. So
    candidates that had already cost generation + prescreen sat unvetted for six weeks
    because a transient moat outage happened to catch them.

    Operators are built here the same way `_cmd_signal` builds them, so the daemon does not
    have to import the CLI's argparse plumbing.
    """
    from .operator import make_operator
    from .telemetry import reset_usage
    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    args = argparse.Namespace(limit=limit, publish=publish, board=None,
                              fixtures=None, search=None)
    search = _make_search(cfg, args)
    store = Store(cfg)
    # The same ledger `main()` passes for every CLI command (see the log_path it builds from
    # cfg.store_dir). Omitting it made the daemon's drain the one caller with no log path, so
    # its last line printed "No audit log at ." — the pass spends real money re-vetting and
    # the operator got no cost line for it, on the only run nobody is watching.
    return _cmd_resume(args, cfg, op, fast_op, search, store,
                       log_path=cfg.store_dir / "prospector.jsonl")


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

    for kind in ("deepseek", "minimax", "claude_cli"):
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
        from .errors import GroundingInfrastructureError, ProviderExhaustedError
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

        print(f"  {build_chain(_NONCRITICAL_ORDER, 'gen_op')}")
        print(f"  {build_chain(_NONCRITICAL_ORDER, 'fast_op')}")
    except Exception as e:
        print(f"  ✗ could not build chains: {e}")

    # ── 4. Generation prompt probe (optional) ─────────────────────────────
    if getattr(args, "gen", False):
        print("\n▸ Generation prompt probe (~7000 chars)")
        from .prompts import market_kwargs, render
        # Market vars included so the probe measures the REAL prompt size and never
        # sends a literal {market_context} to a live operator below.
        sys_p, usr_p = render("generate",
                               signal_text="AI tools for small businesses",
                               sector="", strategy_lens="broaden",
                               exploration_level=0.5,
                               **market_kwargs(cfg))
        print(f"  Prompt size: {len(sys_p) + len(usr_p)} chars")
        # Probe the non-critical chain operators only
        gen_ops = [(k, o, b) for k, o, b in available_ops
                   if o is not None and k in _NONCRITICAL_ORDER]
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


def _cmd_markets(args: argparse.Namespace, cfg: Config, log_path: Path) -> None:
    """list | show | probe | open | close — the Market-Readiness Gate."""
    from . import markets as mk

    action = getattr(args, "markets_action", "list") or "list"

    if action == "list":
        store = Store(cfg)
        try:
            counts = store.markets_present()
        except Exception:  # noqa: BLE001 — a fresh install has no catalogue yet
            counts = {}
        default = cfg.default_market
        print(f"{'code':<10}{'status':<10}{'dossiers':>9}  label")
        for code in sorted(c for c in (cfg.markets or {}) if c != "default"):
            block = cfg.market_config(code)
            flag = " (default)" if code == default else ""
            print(f"{code:<10}{cfg.market_status(code):<10}{counts.get(code, 0):>9}  "
                  f"{block.get('label', '')}{flag}")
        unknown = {m: n for m, n in counts.items() if m and m not in (cfg.markets or {})}
        if unknown:
            print(f"\nnot in config: {unknown}")
        if counts.get(""):
            print(f"\n{counts['']} dossier(s) predate the market dimension "
                  f"(market unset). See tools/backfill_market.py.")
        return

    market = getattr(args, "market", None) or cfg.default_market

    if action == "show":
        r = mk.load_readiness(cfg, market)
        if r is None:
            print(f"market {market!r}: status={cfg.market_status(market)}, "
                  f"no readiness probe recorded at {mk.readiness_path(cfg, market)}")
            return
        print(mk.format_readiness(r))
        current = mk.config_fingerprint(cfg, market)
        if current != r.config_fingerprint:
            print(f"\n  STALE: config has changed since this probe "
                  f"({r.config_fingerprint} → {current}). Re-probe before opening.")
        return

    if action == "probe":
        _run_market_probe(args, cfg, market, log_path)
        return

    if action == "open":
        r = mk.load_readiness(cfg, market)
        if r is None:
            print(f"error: cannot open {market!r} — no readiness probe at "
                  f"{mk.readiness_path(cfg, market)}. Run `markets probe` first.",
                  file=sys.stderr)
            sys.exit(2)
        if not r.ready:
            print(f"error: cannot open {market!r} — the probe says NOT READY:\n"
                  + "\n".join(f"  - {f}" for f in r.failures)
                  + "\n\nFix the evidence terrain (queries, authority domains, "
                    "calibration set). Do NOT lower the bar.", file=sys.stderr)
            sys.exit(2)
        current = mk.config_fingerprint(cfg, market)
        if current != r.config_fingerprint:
            print(f"error: cannot open {market!r} — the probe measured a different "
                  f"configuration ({r.config_fingerprint}, now {current}). Re-probe.",
                  file=sys.stderr)
            sys.exit(2)
        _set_market_status(args, market, "open")
        return

    if action == "close":
        _set_market_status(args, market, "closed")
        return

    print(f"error: unknown markets action {action!r}", file=sys.stderr)
    sys.exit(1)


def _set_market_status(args: argparse.Namespace, market: str, status: str) -> None:
    """Rewrite `status:` for one market in config.yaml, preserving comments."""
    import re
    from .config import REPO_ROOT

    path = Path(args.config) if getattr(args, "config", None) else REPO_ROOT / "config.yaml"
    text = path.read_text()
    # Match the market's own `status:` line: the key at 2-space indent inside `markets:`,
    # then its `status:` at 4-space indent. The body pattern only crosses lines that are
    # indented four or more (or blank), so it can never walk out of this market's block
    # and flip a SIBLING market's status — a market missing `status:` must fail loudly
    # below, not silently open the next market in the file.
    pattern = re.compile(
        rf"(^  {re.escape(market)}:\n(?:(?:[ \t]{{4,}}.*)?\n)*?    status:[ \t]*)(\S+)",
        re.MULTILINE)
    new_text, n = pattern.subn(rf"\g<1>{status}", text, count=1)
    if n != 1:
        print(f"error: could not find a `status:` line for market {market!r} in {path}. "
              f"Edit it by hand.", file=sys.stderr)
        sys.exit(1)
    path.write_text(new_text)
    print(f"market {market!r} is now {status} in {path}")


def _run_market_probe(args: argparse.Namespace, cfg: Config, market: str,
                      log_path: Path) -> None:
    """Run the calibration set through the real pipeline and record the measurement."""
    from . import markets as mk
    from . import progress
    from .operator import make_operator
    from .telemetry import reset_usage

    if not getattr(args, "set", None):
        print("error: --set PATH is required (a JSONL calibration set)", file=sys.stderr)
        sys.exit(2)
    entries = mk.load_calibration_set(args.set)

    # The probe is the ONE sanctioned way to run a closed market. Two containments keep
    # a calibration run from being mistaken for real output: publishing is refused, and
    # the dossiers land in an isolated store under the market's own probe directory
    # rather than the live catalogue. Without the second, a probe of a closed market
    # would write catalogue rows that the market_not_open alarm then flags as a breach.
    from dataclasses import replace as _replace

    args.probe = True
    # `real_cfg` keeps the live store dir so the READINESS artifact lands where the rest
    # of the engine looks for it; only the DOSSIER writes are diverted.
    real_cfg = _build_config_and_overrides(args).for_market(market)
    # Pack-shaped calibration ideas must be judged on the lane that matches them
    # (usually side_hustle). `--lane` already resolves gates via for_lane above; also
    # stamp ambition_tier on each candidate so dossiers/audit trail show the bar used,
    # and so any later for_lane(cand.ambition_tier) path cannot silently revert to the
    # venture default (which kills packs on incumbency — the wrong bar for £30 packs).
    lane = (getattr(args, "lane", None) or "").strip()
    probe_dir = Path(real_cfg.store_dir) / "markets" / market / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_cfg = _replace(real_cfg, store={**real_cfg.store, "dir": str(probe_dir)})
    store = Store(probe_cfg)
    reset_usage()
    op = make_operator(probe_cfg)
    fast_op = make_operator(probe_cfg, fast=True)
    search = _make_search(probe_cfg, args)

    lane_note = f" lane={lane!r}" if lane else " (default lane — pack sets usually want --lane side_hustle)"
    print(f"Probing market {market!r} with {len(entries)} calibration candidate(s){lane_note}…")
    outcomes = []
    for entry in entries:
        # Entry-level ambition_tier/lane wins when present; else CLI --lane; else unset.
        entry_lane = (entry.get("ambition_tier") or entry.get("lane") or lane or "").strip()
        cand = Candidate(title=entry["title"], one_liner=entry.get("one_liner", ""),
                         why_now=entry.get("why_now", ""), market=market,
                         ambition_tier=entry_lane)
        progress.banner(f"[probe {market}] {cand.title!r}")
        vet_cfg = probe_cfg.for_lane(entry_lane) if entry_lane else probe_cfg
        d = vet_candidate(cand, op, search, vet_cfg, store=store, query_op=fast_op,
                          publish=False, show_checks=False)
        outcome = mk.outcome_from_dossier(entry["expected"], d)
        outcomes.append(outcome)
        print(f"  expected={outcome.expected:<5} actual={outcome.actual:<5} "
              f"grounded={outcome.grounded_checks}/{outcome.total_checks}  {cand.title[:44]}")

    # Fingerprint against the market-scoped config WITHOUT --lane applied.
    # `markets show|open` load config with no lane pin; hashing the lane-resolved
    # hard_gates/thresholds here made every successful `probe --lane side_hustle`
    # look STALE immediately. Outcomes still reflect the lane used for vetting.
    fp_cfg = load_config().for_market(market)
    readiness = mk.evaluate(fp_cfg, market, outcomes)
    path = mk.save_readiness(fp_cfg, readiness)
    print("\n" + mk.format_readiness(readiness))
    print(f"\nwritten: {path}")
    print(f"probe dossiers (not catalogue): {probe_dir}")
    if readiness.ready:
        print(f"\nThis market is ready. To open it:\n"
              f"  python -m prospector.run markets open --market {market}")
    else:
        print("\nNot ready. Improve the evidence terrain (authority domains, query "
              "exemplars in prompts/markets/<code>/), then re-probe. Never lower the bar.")


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
    # NOT `required=True`. `--resume` re-vets a backlog read from the store, so there is no
    # title to give — and argparse rejected the command before `_cmd_vet` (run.py:972) could
    # ever look at `args.resume`. RUN.md:97 has documented `python -m prospector.run vet
    # --resume` since the flag was added, and that exact command has never once run:
    #     python -m prospector.run vet --resume
    #     error: the following arguments are required: --title
    # It stayed invisible because the daemon's drain calls `resume_deferred()` in-process and
    # never touches this parser. Requiredness is enforced below instead, where it can be
    # conditional on the mode.
    vet_p.add_argument("--title", help="Opportunity title (required unless --resume)")
    vet_p.add_argument("--one-liner", dest="one_liner", default="",
                       help="One-liner description")
    vet_p.add_argument("--why-now", dest="why_now", default="",
                       help="Why this opportunity exists now")
    vet_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    vet_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane to judge against (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    _add_market_args(vet_p)
    _add_archetype_arg(vet_p)
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
                            "Safe to re-run when the moat (Claude) comes back online.")
    vet_p.add_argument("--limit", type=int, metavar="N",
                       help="With --resume: re-vet only the N oldest deferred/provisional "
                            "candidates instead of the whole backlog. Default unbounded. "
                            "The daemon always passes a limit — the spend guard is evaluated "
                            "once per tick, so an unbounded drain would run inside a single "
                            "guard decision.")
    vet_p.add_argument("--only", choices=list(RESUME_SELECTORS), default="all",
                       help="With --resume: restrict the drain to one backlog population. "
                            "'provisional-pass' targets the only rows that can become "
                            "sellable inventory (a confirmed re-vet clears the "
                            "not-provisional publish gate); oldest-first ordering otherwise "
                            "buries them behind provisional KILLs and DEFERs. "
                            "Default 'all' = historical behaviour.")

    # ---- signal subcommand ----
    sig_p = sub.add_parser("signal", help="Run the full signal pipeline")
    sig_src = sig_p.add_mutually_exclusive_group(required=True)
    sig_src.add_argument("--text", metavar="TEXT", help="Signal text inline")
    sig_src.add_argument("--file", metavar="PATH", help="Path to signal text file")
    sig_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
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
    _add_market_args(sig_p)
    _add_archetype_arg(sig_p)
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
    gen_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    gen_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    gen_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")
    gen_p.add_argument("--lane", metavar="NAME",
                       help="Ambition lane for generation + vetting (e.g. side_hustle, venture). "
                            "Default: config active_lane.")
    _add_market_args(gen_p)
    _add_archetype_arg(gen_p)
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
                            "Safe to re-run when the non-critical chain (DeepSeek/MiniMax) recovers.")

    # ---- replicate subcommand (Epic D: cross-market replication) ----
    rep_p = sub.add_parser(
        "replicate",
        help="Re-vet proven PASSes from one market as fresh candidates in another")
    rep_p.add_argument("--from", dest="source_market", required=True, metavar="CODE",
                       help="Source market to take PASS dossiers from (e.g. uk)")
    rep_p.add_argument("-n", type=int, default=None, metavar="N",
                       help="Max candidates to replicate (default: all)")
    rep_p.add_argument("--min-composite", dest="min_composite", type=float, default=None,
                       metavar="X", help="Only replicate PASSes scoring at or above X")
    rep_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="List what would be replicated; run no checks")
    rep_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                       help="Override operator from config")
    rep_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    rep_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish on PASS")
    rep_p.add_argument("--lane", metavar="NAME", help="Ambition lane to judge against")
    rep_p.add_argument("--persona", metavar="NAME", help="Analytical persona")
    _add_market_args(rep_p)

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
    disc_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"],
                        help="Override operator from config")
    disc_p.add_argument("--lane", metavar="NAME",
                        help="Pin the sweep to a single ambition lane (default: multi-lane "
                             "across config active_lanes).")
    _add_market_args(disc_p)
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

    # ---- markets subcommand (Epic D: the Market-Readiness Gate) ----
    markets_p = sub.add_parser(
        "markets", help="Manage jurisdictions (list, show, probe, open, close)")
    markets_act = markets_p.add_subparsers(dest="markets_action", required=True)

    markets_act.add_parser("list", help="Show defined markets, status and dossier counts")

    show_p = markets_act.add_parser("show", help="Show a market's readiness measurement")
    show_p.add_argument("--market", metavar="CODE", required=True)

    probe_p = markets_act.add_parser(
        "probe", help="Run the calibration set through the real pipeline and measure")
    probe_p.add_argument("--market", metavar="CODE", required=True)
    probe_p.add_argument("--set", metavar="PATH", required=True,
                         help="JSONL calibration set: one "
                              '{"title","one_liner","expected":"pass|kill"} per line')
    probe_p.add_argument("--operator", choices=["claude", "claude_cli", "minimax", "deepseek", "mock"])
    probe_p.add_argument("--fixtures", metavar="PATH",
                         help="Path to fixtures JSON (offline probe)")
    probe_p.add_argument("--lane", metavar="NAME")

    open_p = markets_act.add_parser(
        "open", help="Open a market — refused unless a current probe says READY")
    open_p.add_argument("--market", metavar="CODE", required=True)

    close_p = markets_act.add_parser("close", help="Close a market")
    close_p.add_argument("--market", metavar="CODE", required=True)

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
        # Conditional requiredness — see the `--title` declaration for why argparse cannot
        # carry it. A single-candidate vet with no title is still a usage error, and it must
        # still exit 2 so scripts that check the code keep working.
        if not getattr(args, "resume", False) and not getattr(args, "title", None):
            print("Error: vet requires --title (or --resume to drain the backlog).",
                  file=sys.stderr)
            sys.exit(2)
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
    elif args.command == "markets":
        _cmd_markets(args, cfg_for_log, log_path)
    elif args.command == "replicate":
        _cmd_replicate(args, log_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

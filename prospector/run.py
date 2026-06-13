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
import sys
from typing import Optional

from .config import Config, load_config
from .dedup import dedup
from .dossier import build_dossier, render_markdown
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
    """
    set_context(candidate_id=cand.candidate_id, phase="vetting")
    logger.info(f"Vetting candidate: {cand.title!r}")

    from . import progress

    on_check = None
    if show_checks:
        def on_check(res) -> None:  # live per-check line (single-vet only; the
            v = res.verdict.value   # concurrent signal pool would interleave these)
            mark = "✗" if v in ("refuted", "unverifiable") else "✓"
            progress.note(f"{mark} {res.check_name}: {v} (conf {res.confidence:.2f})")

    verify = _get_verify()
    checks, adversarial, gate = verify(op, search, cfg, cand,
                                       on_check=on_check, query_op=query_op)

    score = None
    if gate is None:
        logger.info("Candidate survived all gates. Scoring...")
        score = score_candidate(op, cfg, cand, checks)

        if publish:
            # --- Task B: Secondary artifacts + claim-check (publish-time only) ---
            logger.info("Generating publish-time artifacts + marketing content...")
            from .artifacts import generate_artifacts, generate_marketing_content
            cand.tags["artifacts"] = generate_artifacts(op, cand, checks)
            cand.tags["marketing"] = generate_marketing_content(op, cand, checks)

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
        created_at=created_at,
        reverify_due_at=reverify_due_at,
    )

    if store is not None:
        store.save(dossier)

    if publish and dossier.decision == Decision.PASS:
        try:
            from publish.publish import publish as _publish
            _publish(dossier, cfg)
        except Exception as e:
            logger.error(f"Publication failed for {cand.candidate_id}", extra={"error": str(e)})

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
) -> list[Dossier]:
    """Generate candidates from a signal, dedup, prescreen, vet each, return dossiers.

    Any of cfg/op/search/store may be None — defaults are loaded automatically.
    Plain runs are cheap (verdict + score only); pass publish=True to also
    generate listing artifacts and publish PASSes.
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

    # Lighter model for mechanical calls (query-gen, prescreen); == op if unset.
    from .operator import make_operator as _make_op
    fast_op = _make_op(cfg, fast=True)

    if search is None:
        from .retrieval import make_provider
        search = make_provider(cfg)

    if store is None:
        store = Store(cfg)

    # --- Adaptive creativity (Part 3) ---
    from .adaptive import calculate_exploration_level, get_recent_failure_modes
    expl = calculate_exploration_level(store)
    fails = get_recent_failure_modes(store)
    logger.info(f"Adaptive Controller: expl={expl:.1f}", extra={"exploration_level": expl, "fails": fails})

    # --- Spend guard (Part 9) ---
    from .spend import SpendGuard
    guard = SpendGuard(daily_cap_usd=cfg.spend.daily_cap_usd,
                       warn_at_usd=cfg.spend.warn_at_usd)

    # --- Generate ---
    candidates = generate(
        op, cfg, signal_text=signal_text, k=k,
        exploration_level=expl, recent_failure_modes=fails
    )
    if not candidates:
        logger.warning("No candidates generated from signal")
        progress.step("generation produced 0 candidates — nothing to vet")
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

    # --- Prescreen ---
    kept: list[Candidate] = []
    for cand in final_candidates:
        keep, reason = prescreen(fast_op, cfg, cand)
        if keep:
            kept.append(cand)
        else:
            logger.info(f"PRESCREENED OUT: {cand.title!r}", extra={"reason": reason})
            progress.note(f"prescreened out: {cand.title!r}")

    if not kept:
        logger.warning("No candidates survived prescreen")
        progress.step("0 candidates survived prescreen")
        return []
    progress.step(f"vetting {len(kept)} candidate(s) (concurrency=5)…")

    # --- Vet each candidate (Bounded Concurrency Task E) ---
    from concurrent.futures import ThreadPoolExecutor
    dossiers: list[Dossier] = []

    # We use a max_workers=5 as suggested in the spec/handover
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for cand in kept:
            # Check spend guard (rough check before submitting)
            if guard.tripped():
                logger.error(f"ABORTING: Spend guard tripped (${guard.total():.2f})")
                break

            # Submit to pool
            futures.append(executor.submit(
                vet_candidate, cand, op, search, cfg,
                store=store, query_op=fast_op, publish=publish))
            # Rough cost estimate increment
            guard.add(0.01)

        total_submitted = len(futures)
        for i, future in enumerate(futures, start=1):
            try:
                d = future.result()
                gate_str = f" [gate={d.gate_fired}]" if d.gate_fired else ""
                logger.info(f"Result: {d.candidate.title!r} → {d.decision.value.upper()}{gate_str}",
                            extra={"candidate_id": d.candidate.candidate_id, "decision": d.decision.value, "score": d.score.composite if d.score else None})
                progress.result(i, total_submitted, d.decision.value, d.candidate.title,
                                gate=d.gate_fired,
                                composite=(d.score.composite if d.score else None))
                dossiers.append(d)
            except Exception as e:
                logger.error(f"ERROR vetting candidate: {e}", extra={"error": str(e)})
                progress.note(f"[{i}/{total_submitted}] ⚠ error: {e}")

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

    return cfg


def _make_search(cfg: Config, args: argparse.Namespace) -> SearchProvider:
    """Build the SearchProvider, injecting fixtures when --fixtures is passed."""
    from .retrieval import make_provider

    fixtures = None
    if hasattr(args, "fixtures") and args.fixtures:
        with open(args.fixtures, encoding="utf-8") as fh:
            fixtures = json.load(fh)

    return make_provider(cfg, fixtures=fixtures)


def _cmd_vet(args: argparse.Namespace) -> None:
    """Vet a single candidate specified on the command line."""
    cfg = _build_config_and_overrides(args)

    from .operator import make_operator
    from .telemetry import get_usage_summary, reset_usage
    reset_usage()
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)
    search = _make_search(cfg, args)
    store = Store(cfg)

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
                      show_checks=True)
    progress.summary(
        n_pass=1 if d.decision == Decision.PASS else 0,
        n_kill=1 if d.decision == Decision.KILL else 0,
        n_defer=1 if d.decision == Decision.DEFER else 0)
    print(render_markdown(d))
    usage = get_usage_summary()
    print(f"\n--- token/call audit ---\n{json.dumps(usage, indent=2)}")


def _cmd_signal(args: argparse.Namespace) -> None:
    """Run the full signal pipeline from text or file."""
    cfg = _build_config_and_overrides(args)

    if args.text:
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
                          publish=getattr(args, "publish", False))

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
    print(f"\n--- token/call audit ---\n{json.dumps(get_usage_summary(), indent=2)}")


def _cmd_report(args, cfg, log_path) -> None:
    """Render the catalogue / metrics / costs. Reads on-disk state only; no model calls."""
    from .report import (catalogue_report, metrics_report, costs_report, full_report)
    from .store import Store
    store = Store(cfg)
    if args.full:
        print(full_report(store, log_path))
    elif args.metrics:
        print(metrics_report(store))
    elif args.costs:
        print(costs_report(log_path))
    else:  # default: catalogue
        print(catalogue_report(store, decision=args.decision))


def main() -> None:
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
    vet_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "mock"],
                       help="Override operator from config")
    vet_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    vet_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish on PASS (extra model calls)")

    # ---- signal subcommand ----
    sig_p = sub.add_parser("signal", help="Run the full signal pipeline")
    sig_src = sig_p.add_mutually_exclusive_group(required=True)
    sig_src.add_argument("--text", metavar="TEXT", help="Signal text inline")
    sig_src.add_argument("--file", metavar="PATH", help="Path to signal text file")
    sig_p.add_argument("--operator", choices=["gemini_cli", "gemini", "claude", "mock"],
                       help="Override operator from config")
    sig_p.add_argument("--count", type=int, default=None, metavar="N",
                       help="Number of candidates to generate (default: config candidates_per_signal)")
    sig_p.add_argument("--fixtures", metavar="PATH",
                       help="Path to fixtures JSON (uses FixtureProvider)")
    sig_p.add_argument("--publish", action="store_true",
                       help="Generate listing artifacts + publish PASSes (extra model calls)")

    # ---- report subcommand ----
    rep_p = sub.add_parser("report", help="Read the catalogue, metrics, and costs (no model calls)")
    rep_view = rep_p.add_mutually_exclusive_group()
    rep_view.add_argument("--catalogue", action="store_true",
                          help="List vetted ideas grouped by decision (default)")
    rep_view.add_argument("--metrics", action="store_true",
                          help="Truth-loop health: kill rate, gate distribution")
    rep_view.add_argument("--costs", action="store_true",
                          help="Lifetime spend, tokens, slowest operations")
    rep_view.add_argument("--full", action="store_true",
                          help="All three views")
    rep_p.add_argument("--decision", choices=["pass", "kill", "defer"],
                       help="Filter the catalogue to one decision")

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
        _cmd_vet(args)
    elif args.command == "signal":
        _cmd_signal(args)
    elif args.command == "report":
        _cmd_report(args, cfg_for_log, log_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

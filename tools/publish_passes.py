"""Generate pack content for stored PASS dossiers and publish them live.

The catalogue holds PASS dossiers that cleared verification but never had their
£30 deliverable generated (build_spec/gtm_plan/ops_plan/financial_model + marketing).
This driver reconstructs a Dossier from the stored JSON, runs the artifact quality
chain (cfg.artifact_operator — cursor_cli→claude_cli) for pack prose, non-critical
for ancillary JSON, and moat for claim-check; then publishes via EngineBridge.

Usage:
    python -m tools.publish_passes store/dossiers/<id>.pass.json [more...]
    python -m tools.publish_passes --all          # every PASS in the store
    python -m tools.publish_passes --reuse-artifacts <paths...>
        # Re-bundle + re-publish from the artifacts already stored on the dossier, with no
        # model call. Use when the defect is in the BUNDLE, not the prose — e.g. repairing
        # the pre-2026-07-31 bundles that shipped without 00_Executive_Summary.md /
        # 05_First_Week_Checklist.md. Falls back to regeneration if the stored pack does
        # not clear validate_pack.
    python -m tools.publish_passes --dry-run --all
        # Answer "why is this pack not selling?" for FREE. Runs the deterministic gate
        # (validate_pack + audit_bundle + lint_pack), writes store/dossiers/<id>.lint.json
        # for every pack, and stops before the money rail: no Stripe object, no upload, no
        # catalogue row, no listing receipt. Implies --reuse-artifacts and never generates,
        # so it costs zero model calls and needs no quota. Use this BEFORE spending anything.
        #
        # "FREE" means free of MODEL cost, not free of time: the gate re-checks every
        # citation URL over the network and measured 945 SECONDS on one pack. So a pack
        # whose stored .lint.json is newer than the pack itself is reported FROM THAT
        # RECORD and not re-gated. Pass --force-regate to run the gate anyway.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from prospector.artifacts import generate_artifacts, generate_marketing_content
from prospector.config import load_config, store_root
from prospector.models import (
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    ScoreResult,
    Source,
    Verdict,
)
from prospector.operator import make_operator
from prospector.pack_floors import ensure_marketing_floor
from prospector.pack_validation import validate_pack
from prospector.run import (
    _NONCRITICAL_ORDER,
    _build_artifact_op,
    _build_marketing_op,
    _load_dotenv,
    _shelf_copy_breaches,
)
from publish.publish import publish

# Generation flakiness budget: regenerate the whole pack this many times before giving up
# and holding it back (unsold). 3 is enough to ride out a transient quota wall or a tier's
# one-off empty return without burning the batch.
MAX_GEN_ATTEMPTS = 3


def _source(s: dict) -> Source:
    return Source(
        source_id=s.get("source_id", ""),
        url=s.get("url", ""),
        text=s.get("text", ""),
        published_at=s.get("published_at"),
        query=s.get("query"),
        fetched_at=s.get("fetched_at"),
    )


def _check(c: dict) -> CheckResult:
    v = c.get("verdict")
    return CheckResult(
        check_name=c.get("check_name", ""),
        verdict=v if isinstance(v, Verdict) else Verdict(v),
        confidence=float(c.get("confidence", 0.0)),
        rationale=c.get("rationale", ""),
        citations=list(c.get("citations") or []),
        sources=[_source(s) for s in (c.get("sources") or [])],
        queries=list(c.get("queries") or []),
    )


def reconstruct(d: dict) -> Dossier:
    cand = Candidate.from_dict(d["candidate"])
    checks = [_check(c) for c in d.get("checks", [])]
    sc = d.get("score") or {}
    score = ScoreResult(
        scores=sc.get("scores", {}),
        justification=sc.get("justification", {}),
        composite=sc.get("composite", 0.0),
    ) if sc else None
    return Dossier(
        candidate=cand,
        decision=Decision.PASS,
        checks=checks,
        score=score,
        reason=d.get("reason", ""),
        model_version=d.get("model_version", ""),
        created_at=d.get("created_at", ""),
        reverify_due_at=d.get("reverify_due_at"),
    )


#: The stored verdict for a pack, but ONLY if it describes the pack as it is now.
#:
#: A gate run writes its full problem list to `store/dossiers/<id>.lint.json` every time
#: (`bridge.py:1102`), pass or fail. Re-running the gate to READ that list pays twice and
#: the second payment buys nothing. Measured 2026-08-17: 945 seconds for one pack, almost
#: all of it live network — while the answer sat on disk next to it. Reading 40 receipts
#: cost one command and named the whole shape of the backlog immediately.
#:
#: This is that lesson in code rather than in a rule. A rule gets forgotten; a default does
#: not.
def _fresh_lint(pass_path: str) -> dict | None:
    """The pack's own lint record if it is NEWER than the pack, else None.

    Freshness is mtime, not trust. The recovery tool rewrites the `.pass.json` and then
    re-gates, so a repaired pack is always newer than the receipt describing it before the
    repair — and this returns None there, which is exactly when running the gate is the only
    honest answer. Any unreadable or malformed record also returns None: the guard may cost
    a run it did not need to, never a wrong verdict.
    """
    lint_path = re.sub(r"\.pass\.json$", ".lint.json", pass_path)
    if lint_path == pass_path:
        return None
    try:
        if os.path.getmtime(lint_path) < os.path.getmtime(pass_path):
            return None
        with open(lint_path) as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _report_cached(cid: str, rec: dict) -> bool:
    """Print a stored verdict in the same shape a fresh one prints. True if it would list."""
    listed = bool(rec.get("ok"))
    errors = [pr for pr in (rec.get("problems") or [])
              if isinstance(pr, dict) and str(pr.get("severity")) == "error"]
    checks = sorted({str(pr.get("check")) for pr in errors})
    print(f"{cid}: gate (stored {rec.get('checked_at')}) -> "
          f"{'would list' if listed else 'blocked'}"
          + (f" on {', '.join(checks)}" if checks else ""), flush=True)
    for pr in errors[:6]:
        print(f"    {pr.get('check')}/{pr.get('where')}: {str(pr.get('detail'))[:150]}")
    if len(errors) > 6:
        print(f"    ... {len(errors) - 6} more")
    return listed


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    # Re-bundle without regenerating. Dossiers persist their generated artifacts under
    # candidate.tags["artifacts"], but this driver regenerated them unconditionally, so
    # repairing a pack whose ONLY defect is a deterministic floor (a missing executive
    # summary, a stub Marketing_Assets) cost a full LLM generation per pack. With this flag
    # a stored pack that already clears validate_pack is re-bundled and re-published as-is:
    # no model call, no cost, and byte-identical prose to what the moat already verified.
    reuse_artifacts = "--reuse-artifacts" in argv
    argv = [a for a in argv if a != "--reuse-artifacts"]

    # Pin THIS run's prose generation to the cheap metered tail instead of the subscription
    # CLI at the head of cfg.artifact_operator. Founder directive 2026-08-08 ("we can use
    # minimax for cheap vetting" / "why are we usinng claude?"): repairing a backlog of
    # already-verdicted packs is not worth Claude Code time, and the packs in that backlog
    # fail on MECHANICAL defects (a $ where £ belongs, a dead citation), not on prose quality.
    # A flag, not a config edit, because the default chain must stay claude_cli-led for the
    # normal path — the £49 deliverable's prose IS the product.
    #
    # SCOPE, and the correction that produced it. The first cut of this flag pinned only
    # `cfg.artifact_operator` and left `op` (the moat chain) alone, on the reasoning that
    # claim-check belongs on MOAT_PRIMARY. Measured on the very next run: 16 claude_cli calls
    # and **$2.52** in ~8 minutes across two packs, against $0.066 of minimax — because `op`
    # is not just the claim-check gate, it is also `gen_op` for the ancillary pieces and the
    # JSON calls at artifacts.py:365/491. "Only the truth gate stays expensive" was wrong by
    # a factor of 38. So --cheap now pins the moat chain too.
    #
    # The cost of that, stated plainly rather than buried: claim-check — the gate that vetoes
    # marketing copy the dossier does not support — runs on minimax under this flag. What
    # still holds is every DETERMINISTIC fence, and those are Python, not a model:
    # validate_pack (completeness), audit_bundle, and lint_pack's currency/citation/dash
    # checks, all evaluated in `content_ok` BEFORE any Stripe object is minted
    # (bridge.py:820, since 967457f). A weak cheap pack fails those and stays UNLISTED.
    # This flag is therefore right for repairing a backlog blocked on MECHANICAL defects and
    # wrong for minting new prose nobody has ever checked.
    cheap = "--cheap" in argv
    argv = [a for a in argv if a != "--cheap"]

    # Rehearse the gate, mint nothing. This exists because the deterministic verdict on a
    # pack was previously only obtainable as a side effect of a real publish: on 2026-08-09,
    # 9 of the 17 republishable PASS dossiers carried no .lint.json at all, so the honest
    # answer to "what is blocking them?" was "nobody has ever looked, and looking costs a
    # Stripe object". It IMPLIES --reuse-artifacts and skips generation outright rather than
    # merely defaulting to it: a rehearsal whose cost depends on which flags you remembered
    # is not one you will run first, and running it first is the entire point.
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if dry_run:
        reuse_artifacts = True

    # Re-run the gate even where a fresh receipt already answers the question. The one
    # reason to want this is checking the gate ITSELF — after changing a lint rule, the
    # stored records were written by the old rule and are worth nothing.
    force_regate = "--force-regate" in argv
    argv = [a for a in argv if a != "--force-regate"]

    # How many packs to GENERATE at once (publishing stays serial — see the fan-out below).
    # Default 1 keeps every existing invocation byte-identical in behaviour.
    jobs = 1
    for a in list(argv):
        if a.startswith("--jobs="):
            jobs = max(1, int(a.split("=", 1)[1]))
            argv.remove(a)

    if argv == ["--all"]:
        paths = sorted(glob.glob(str(store_root() / "dossiers" / "*.pass.json")))
    else:
        paths = argv

    # Same as prospector.run: pull gitignored .env so EngineBridge sees
    # PROSPECTOR_ENTITLEMENTS_API_KEY / STORE_* without a Claude Code session.
    _load_dotenv()
    cfg = load_config()
    # Match run.py publish path: claim-check stays on the moat; £49 prose uses
    # cfg.artifact_operator (cursor_cli → claude_cli). Ancillary JSON uses the
    # non-critical chain. Do NOT hardcode claude_cli — that wedges content_gen when
    # Claude Code is busy/unavailable (see publish_backfill_yield.log).
    if not getattr(cfg, "entitlements_api_key", ""):
        print("ERROR: PROSPECTOR_ENTITLEMENTS_API_KEY unset after .env load; "
              "EngineBridge will refuse publish.", file=sys.stderr)
        return 2
    noncritical_order = list(_NONCRITICAL_ORDER)
    if cheap:
        cfg.operator = ["minimax"]          # claim-check + ancillary JSON + gen_op
        cfg.artifact_operator = ["minimax"]  # the £49 prose
        cfg.marketing_operator = ["minimax"]  # ...and the shelf copy that sells it
        noncritical_order = ["minimax"]
    op = make_operator(cfg)
    quality_op = _build_artifact_op(cfg, op)
    marketing_op = _build_marketing_op(cfg, op)
    saved_operator = cfg.operator
    cfg.operator = noncritical_order
    fast_op = make_operator(cfg, fast=True)
    cfg.operator = saved_operator
    # getattr, for the same reason `_build_marketing_op` uses it: a Config predating the
    # 2026-08-14 split has no such attribute, and a banner line must never be what raises.
    print(f"artifact chain: {cfg.artifact_operator}  marketing chain: "
          f"{getattr(cfg, 'marketing_operator', None) or cfg.artifact_operator}  "
          f"noncritical: {noncritical_order}"
          f"{'  [--cheap: no subscription CLI in the generation path]' if cheap else ''}")

    def _prepare(p: str):
        """Generate + gate ONE pack. Pure with respect to other packs: it mutates only its
        own in-memory `cand.tags` and writes only under its own candidate id, which is what
        makes the fan-out below safe. Returns (path, dossier_or_None, complete, problems)."""
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if str(d.get("decision", "")).lower() != "pass":
            return p, None, False, ["not a pass dossier"]

        dossier = reconstruct(d)
        cand = dossier.candidate
        log = [f"\n=== {cand.candidate_id} :: {cand.title} ==="]

        # Generation is flaky (a tier can return empty/unparseable output, or hit a quota
        # wall). Retry until the pack passes the completeness gate, up to MAX_GEN_ATTEMPTS.
        # The same validate_pack() is the hard backstop in EngineBridge, so an incomplete
        # pack can never list even if we run out of attempts here — it just won't sell.
        complete = False
        problems: list[str] = []

        if reuse_artifacts:
            stored = cand.tags.get("artifacts") or {}
            stored_marketing = ensure_marketing_floor(
                cand.tags.get("marketing") or [], cand, dossier.checks)
            complete, problems = validate_pack(stored, stored_marketing)
            if complete:
                cand.tags["marketing"] = stored_marketing
                log.append(f"  reusing stored artifacts: "
                           f"{ {k: len(v or '') for k, v in stored.items()} } (no model call)")
            else:
                log.append(f"  stored artifacts incomplete -> regenerating. {problems}")

        # A dry run reports on what is ON DISK. It must never fall through to generation:
        # the incomplete packs are exactly the ones you most want a free verdict on, and
        # regenerating them here would turn a "free rehearsal" into the most expensive
        # command in the tool for precisely those packs.
        # Same guardrail as the daemon's `_generate_pack_content`, for the same reason: the
        # cheap chain writes the shelf copy, and copy the publish gate would refuse is
        # rewritten by the deliverable chain rather than shipped UNLISTED. One escalation per
        # pack — a chain that just failed this bar has no claim on the remaining attempts.
        copy_op = marketing_op
        escalated = copy_op is quality_op
        breaches: list = []
        for attempt in range(1, 1 if dry_run else MAX_GEN_ATTEMPTS + 1):
            if complete:
                break
            log.append(f"  generating artifacts, attempt {attempt}/{MAX_GEN_ATTEMPTS}...")
            # Pass the whole dossier, not just its checks: pack_data reads `.score` for the
            # scorecard and `.all_sources` for the price comparables. Without it this
            # republish path emitted `score_available: false` and an empty comparables file
            # while a fully-scored dossier sat right here in scope (register §27.2 item 4).
            cand.tags["artifacts"] = generate_artifacts(
                op, cand, dossier.checks, fast_op=fast_op, quality_op=quality_op, cfg=cfg,
                dossier=dossier)
            cand.tags["marketing"] = generate_marketing_content(
                op, cand, dossier.checks, fast_op=fast_op, quality_op=copy_op, check_op=op,
                cfg=cfg)
            # Epic C lite: if LLM listing_page fails claim-check, fill a claim-safe
            # floor from dossier fields only (same helper EngineBridge already uses).
            cand.tags["marketing"] = ensure_marketing_floor(
                cand.tags["marketing"], cand, dossier.checks)

            arts = cand.tags["artifacts"]
            log.append(f"  artifact sizes: { {k: len(v or '') for k, v in arts.items()} }")
            log.append(f"  marketing pieces: {[m.get('type') for m in cand.tags['marketing']]}")

            complete, problems = validate_pack(cand.tags["artifacts"], cand.tags["marketing"])
            # A breach is a FAILURE of this attempt, not a note on it: publishing here would
            # register the pack UNLISTED (bridge.py:927), which is the outcome the retry
            # exists to avoid.
            breaches = _shelf_copy_breaches(cand, cand.tags["marketing"], cfg)
            if breaches:
                complete = False
                problems = list(problems) + [f"marketing 'shelf copy' {b}" for b in breaches]
            if complete:
                log.append("  completeness gate: PASS")
                break
            log.append(f"  completeness gate: FAIL -> {problems}")
            if not escalated and any(str(pb).startswith("marketing '") for pb in problems):
                escalated = True
                copy_op = quality_op
                log.append("  shelf copy escalated to the deliverable chain "
                           "(cheap chain breached the publish-time bar)")

        print("\n".join(log), flush=True)
        return p, dossier, complete, problems

    # Generation is N independent network-bound waits; publishing is not. So the fan-out is
    # GENERATION ONLY and `publish()` stays strictly serial below.
    #
    # Why that split and not a blanket thread pool: publish() mints Stripe products/prices and
    # writes the shared catalogue + local receipts. Concurrency there risks two packs racing
    # the same money-rail bookkeeping, and this repo has already paid for orphan Stripe objects
    # once (8 products archived, 967457f). Generation has no such shared state — each pack
    # touches only its own candidate id — and the process ALREADY runs model calls concurrently
    # inside a single pack (artifacts.py:438/634/815 use ThreadPoolExecutor), so the operators,
    # the breaker and the spend ledger are on a path that is exercised concurrently today.
    # Fanning out across packs widens an existing pattern; it does not introduce one.
    # WHY THIS IS A LAZY ITERATOR AND NOT A LIST (2026-08-13, measured)
    # --------------------------------------------------------------------------------
    # `_prepare` persists NOTHING. It fills `cand.tags["artifacts"]` in memory; only
    # `publish()` writes the dossier, the bundle and the catalogue row. So while this read
    # `prepared = list(ex.map(_prepare, paths))`, the `list()` was a BARRIER: not one pack
    # could reach the shelf until all N had generated, and any interruption before that
    # discarded every artifact the run had paid for.
    #
    # What that cost, from this repo's own logs on 2026-08-13: two publish runs (PIDs 6920
    # and 10768) were stopped during generation and listed exactly zero packs between them,
    # after ~90 minutes of paid model calls each. A third run (PID 19308) had 3 of 20 packs
    # through the completeness gate at the 95-minute mark with nothing on disk and nothing
    # on the shelf — roughly five more hours of all-or-nothing exposure ahead of it. The
    # storefront sat at 50 listed packs through all of it. The engine was not failing to
    # produce; the tool was throwing the production away.
    #
    # `ex.map` ALREADY yields in submission order as each result completes — `list()` was
    # the only thing forcing the wait. Consuming it lazily publishes pack 1 while pack 20
    # is still generating, so an interrupted run keeps everything it had already listed.
    #
    # The serial-publish rule above is UNCHANGED, and is exactly why this stays `ex.map`
    # rather than `as_completed`: publish() still runs one at a time on this thread, in
    # submission order. The money rail sees the identical sequence it saw before. Only the
    # barrier is gone.
    ok = 0
    held_back = 0

    # THE RECEIPT COMES FIRST. Every pack whose stored lint record is newer than the pack is
    # reported from that record and dropped from the run. This is the whole saving: the gate
    # is a 945-second network job per pack and it writes down its own answer, so the second
    # run of it on an unchanged pack is pure waste. A repaired pack is newer than its record
    # and still gets a real gate run — see `_fresh_lint`.
    total = len(paths)
    if dry_run and not force_regate:
        remaining = []
        cached = 0
        for path in paths:
            rec = _fresh_lint(path)
            if rec is None:
                remaining.append(path)
                continue
            cached += 1
            if _report_cached(Path(path).name.split(".")[0], rec):
                ok += 1
            else:
                held_back += 1
        if cached:
            print(f"\n{cached} pack(s) answered from store/dossiers/<id>.lint.json — no gate "
                  f"run, no network. --force-regate re-runs the gate.\n", flush=True)
        paths = remaining
    if dry_run and not paths:
        print(f"\nDRY RUN — nothing was minted, uploaded or listed. "
              f"{ok}/{total} would list, {held_back} would publish UNLISTED. "
              f"Per-pack reasons: store/dossiers/<id>.lint.json")
        return 0

    ex = ThreadPoolExecutor(max_workers=jobs) if jobs > 1 else None
    prepared = ex.map(_prepare, paths) if ex is not None else (_prepare(p) for p in paths)
    try:
        for p, dossier, complete, problems in prepared:
            if dossier is None:
                print(f"SKIP (not pass): {p}")
                continue
            cid = dossier.candidate.candidate_id

            # An incomplete pack is SKIPPED on the real path (nothing to gain from bundling
            # something that cannot list) but GATED on the dry path — the lint report for a
            # pack that fails validate_pack still names its currency, citation and truncation
            # defects, and those are the ones a human has to fix by hand. Reporting only
            # "incomplete" would hide every blocker behind the first one.
            if not complete and not dry_run:
                print(f"{cid}: HELD BACK (not sellable after {MAX_GEN_ATTEMPTS} attempts): "
                      f"{problems}")
                held_back += 1
                continue

            res = publish(dossier, cfg, dry_run=dry_run) if dry_run else publish(dossier, cfg)
            print(f"{cid}: {'gate' if dry_run else 'publish'} -> {res}", flush=True)
            if res.get("status") == "published" or res.get("content_ok"):
                ok += 1
            elif dry_run:
                held_back += 1
    finally:
        # On the happy path the map is exhausted and there is nothing left to wait for. On an
        # interrupt, cancel the packs that have not started rather than blocking the exit on
        # generation whose output we are about to discard anyway.
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)

    if dry_run:
        # `total`, not `len(paths)`: paths has had the cached packs removed, and a summary
        # that counted only the packs it re-gated would under-report the run it just did.
        print(f"\nDRY RUN — nothing was minted, uploaded or listed. "
              f"{ok}/{total} would list, {held_back} would publish UNLISTED. "
              f"Per-pack reasons: store/dossiers/<id>.lint.json")
        return 0
    print(f"\nListed {ok}/{len(paths)} (held back {held_back})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

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
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from prospector.artifacts import generate_artifacts, generate_marketing_content
from prospector.config import load_config
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
from prospector.run import _NONCRITICAL_ORDER, _build_artifact_op, _load_dotenv
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

    if argv == ["--all"]:
        paths = sorted(glob.glob("store/dossiers/*.pass.json"))
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
    op = make_operator(cfg)
    quality_op = _build_artifact_op(cfg, op)
    saved_operator = cfg.operator
    cfg.operator = list(_NONCRITICAL_ORDER)
    fast_op = make_operator(cfg, fast=True)
    cfg.operator = saved_operator
    print(f"artifact chain: {cfg.artifact_operator}  noncritical: {list(_NONCRITICAL_ORDER)}")

    ok = 0
    held_back = 0
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if str(d.get("decision", "")).lower() != "pass":
            print(f"SKIP (not pass): {p}")
            continue

        dossier = reconstruct(d)
        cand = dossier.candidate
        print(f"\n=== {cand.candidate_id} :: {cand.title} ===")

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
                print(f"  reusing stored artifacts: "
                      f"{ {k: len(v or '') for k, v in stored.items()} } (no model call)")
            else:
                print(f"  stored artifacts incomplete -> regenerating. {problems}")

        for attempt in range(1, MAX_GEN_ATTEMPTS + 1):
            if complete:
                break
            print(f"  generating artifacts (artifact_operator chain), attempt {attempt}/{MAX_GEN_ATTEMPTS}...")
            # Pass the whole dossier, not just its checks: pack_data reads `.score` for the
            # scorecard and `.all_sources` for the price comparables. Without it this
            # republish path emitted `score_available: false` and an empty comparables file
            # while a fully-scored dossier sat right here in scope (register §27.2 item 4).
            cand.tags["artifacts"] = generate_artifacts(
                op, cand, dossier.checks, fast_op=fast_op, quality_op=quality_op, cfg=cfg,
                dossier=dossier)
            cand.tags["marketing"] = generate_marketing_content(
                op, cand, dossier.checks, fast_op=fast_op, quality_op=quality_op, check_op=op)
            # Epic C lite: if LLM listing_page fails claim-check, fill a claim-safe
            # floor from dossier fields only (same helper EngineBridge already uses).
            cand.tags["marketing"] = ensure_marketing_floor(
                cand.tags["marketing"], cand, dossier.checks)

            arts = cand.tags["artifacts"]
            sizes = {k: len(v or "") for k, v in arts.items()}
            print(f"  artifact sizes: {sizes}")
            print(f"  marketing pieces: {[m.get('type') for m in cand.tags['marketing']]}")

            complete, problems = validate_pack(cand.tags["artifacts"], cand.tags["marketing"])
            if complete:
                print("  completeness gate: PASS")
                break
            print(f"  completeness gate: FAIL -> {problems}")

        if not complete:
            print(f"  HELD BACK (not sellable after {MAX_GEN_ATTEMPTS} attempts): {problems}")
            held_back += 1
            continue

        res = publish(dossier, cfg)
        print(f"  publish -> {res}")
        if res.get("status") == "published":
            ok += 1

    print(f"\nListed {ok}/{len(paths)} (held back {held_back})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

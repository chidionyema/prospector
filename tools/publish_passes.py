"""Generate pack content for stored PASS dossiers and publish them live.

The catalogue holds PASS dossiers that cleared verification but never had their
£30 deliverable generated (build_spec/gtm_plan/ops_plan/financial_model + marketing).
This driver reconstructs a Dossier from the stored JSON, runs the *non-critical*
generation chain (DeepSeek→MiniMax→Gemini — never the moat) to produce the artifacts,
attaches them, and publishes via EngineBridge → R2 → Store API catalogue.

Usage:
    python -m tools.publish_passes store/dossiers/<id>.pass.json [more...]
    python -m tools.publish_passes --all          # every PASS in the store
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from prospector.config import load_config
from prospector.operator import make_operator
from prospector.models import (
    Candidate, CheckResult, ScoreResult, Source, Dossier, Decision, Verdict,
)
from prospector.artifacts import generate_artifacts, generate_marketing_content
from prospector.pack_validation import validate_pack
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

    if argv == ["--all"]:
        paths = sorted(glob.glob("store/dossiers/*.pass.json"))
    else:
        paths = argv

    cfg = load_config()
    # Generation is non-critical (never the verdict moat). The sanctioned cheap chain —
    # DeepSeek → MiniMax → Gemini-flash — is sufficient: the earlier "empty artifacts"
    # were NOT a model-capability problem but a prompt/parse bug. DeepSeek was returning a
    # valid financial_model object when asked for build_spec (the prompt's biggest schema
    # dominated), and _gen_one_artifact silently turned the type mismatch into "". That's
    # now fixed at the root (artifacts.md anchors the requested type; _validate_artifact_shape
    # raises on wrong-type/empty so complete_json's repair loop and then the chain failover
    # fire). So cheap models generate packs fine; no intelligent model required.
    cfg.operator = ["deepseek", "minimax", "gemini"]
    op = make_operator(cfg)
    fast_op = make_operator(cfg, fast=True)

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
        for attempt in range(1, MAX_GEN_ATTEMPTS + 1):
            print(f"  generating artifacts (non-critical chain), attempt {attempt}/{MAX_GEN_ATTEMPTS}...")
            cand.tags["artifacts"] = generate_artifacts(op, cand, dossier.checks, fast_op=fast_op)
            cand.tags["marketing"] = generate_marketing_content(op, cand, dossier.checks, fast_op=fast_op)

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

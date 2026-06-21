"""Publish PASS dossiers that ALREADY carry complete pack artifacts, with NO regeneration.

Unlike tools.publish_passes (which regenerates the deliverable via the non-critical LLM
chain), this driver publishes dossiers whose artifacts are already present and complete in
the stored JSON. Use it to ship pre-generated packs without burning LLM credits, and for
offline/local end-to-end verification of the publish path (engine -> bundle -> content
storage -> Store API catalogue).

A dossier with missing/incomplete artifacts is SKIPPED (not generated) — run
tools.publish_passes for those once LLM keys are configured.

Usage:
    python -m tools.publish_offline store/dossiers/<id>.pass.json [more...]
    python -m tools.publish_offline --all
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from prospector.config import load_config
from prospector.pack_validation import validate_pack
from tools.publish_passes import reconstruct  # reconstruct preserves tags (artifacts/marketing)
from publish.publish import publish


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    paths = sorted(glob.glob("store/dossiers/*.pass.json")) if argv == ["--all"] else argv
    cfg = load_config()

    ok = 0
    skipped = 0
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if str(d.get("decision", "")).lower() != "pass":
            print(f"SKIP (not pass): {p}")
            continue

        dossier = reconstruct(d)
        cand = dossier.candidate
        arts = cand.tags.get("artifacts", {}) or {}
        mkt = cand.tags.get("marketing", []) or []

        print(f"\n=== {cand.candidate_id} :: {cand.title} ===")
        complete, problems = validate_pack(arts, mkt)
        if not complete:
            print(f"  SKIP (no complete artifacts in JSON; run tools.publish_passes to generate): {problems}")
            skipped += 1
            continue

        sizes = {k: len(v or "") for k, v in arts.items()}
        print(f"  artifact sizes: {sizes}")
        res = publish(dossier, cfg)
        print(f"  publish -> {res}")
        if res.get("status") == "published":
            ok += 1

    print(f"\nListed {ok}/{len(paths)} (skipped {skipped})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

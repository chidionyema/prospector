"""E-101c — the entailment test the headline AUC does not contain.

E-101's primary measure separates the moat's RULED checks from its UNVERIFIABLE ones. A check is
`unverifiable` very largely because retrieval returned nothing on topic, so that split is mostly a
retrieval-success split and any on-topic detector scores well on it. The question this file answers
is the one that is actually about entailment:

    given that the passage IS on topic, can the arm tell `supported` from `refuted`?

AUC(supported vs refuted) on the cited-passage arm only. 0.5 is no signal. Below 0.5 means the arm
orders them backwards, which for an entailment scorer is worse than none.

The existing `tau_null_p95` column does NOT answer this. Its control borrows a passage from a
different candidate (`_groundedness.build_pairs`, offset n//2), so it tests whether the score
responds to the pairing at all. It does. That is a different claim.

Reads the frozen pair file and the on-disk score cache. Zero paid calls, zero network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]  # repo root, never a hardcoded checkout
sys.path.insert(0, str(HERE / "tools" / "experiments"))
sys.path.insert(0, str(HERE))

from _groundedness import maxscore  # noqa: E402
from _verifiers import ArmUnavailable, score_arm  # noqa: E402
from e101_verifier_sweep import _auc  # noqa: E402

PAIRS = Path(sys.argv[1])
ARMS = sys.argv[2].split(",") if len(sys.argv) > 2 else [
    "lex-token", "lex-3gram", "lex-number", "hhem", "nli-fever-bs"]

d = json.loads(PAIRS.read_text())
pairs = [tuple(p) for p in d["pairs"]]
plan, meta = d["plan"], d["sample_meta"]
assert len(plan) == len(meta), (len(plan), len(meta))

out = {"pairs_from": str(PAIRS), "corpus_fingerprint": d["corpus_fingerprint"],
       "n_checks": len(plan), "n_pairs": len(pairs), "results": {}}

for arm in ARMS:
    try:
        scores, _ = score_arm(arm, pairs, use_cache=True)
    except ArmUnavailable as exc:
        out["results"][arm] = {"unavailable": str(exc)}
        print(f"  {arm:14s} UNAVAILABLE — {exc}")
        continue

    sup, ref, unv = [], [], []
    for entry, m in zip(plan, meta):
        s = maxscore(entry["cited"], scores)
        if s is None:
            continue
        {"supported": sup, "refuted": ref, "unverifiable": unv}[m["verdict"]].append(s)

    row = {
        "n_supported": len(sup), "n_refuted": len(ref), "n_unverifiable": len(unv),
        "auc_supported_vs_refuted": round(_auc(sup, ref), 4),
        "auc_supported_vs_unverifiable": round(_auc(sup, unv), 4),
    }
    out["results"][arm] = row
    print(f"  {arm:14s} AUC(sup vs ref) = {row['auc_supported_vs_refuted']:.4f}   "
          f"n={len(sup)}/{len(ref)}")

dest = HERE / "tools" / "experiments" / "e101c_entailment_receipts.json"
dest.write_text(json.dumps(out, indent=1) + "\n")
print("receipt:", dest)

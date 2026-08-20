"""E-101 Stage A — score the Fly arms on the same frozen pair set, and prove the two hosts agree.

The lab host and this laptop ran different arms. Putting their numbers in one table is only honest
if a shared arm produces the SAME score vector on both. `hhem` was deliberately run in both places
for exactly that reason, so the first thing this file does is compare the two vectors and refuse to
publish if they disagree.

Metrics are identical to `e101_verifier_sweep.py`: AUC separating the moat's RULED checks from its
UNVERIFIABLE ones (primary), plus AUC(supported vs refuted) from E-101c, which is the entailment
question the primary measure does not contain.

Reads the frozen pair file, the pulled Fly score files, and the local on-disk cache. Zero paid
calls, zero network.

    tools/experiments/e101_merge_fly.py <pairs.json>
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from _groundedness import maxscore  # noqa: E402
from _verifiers import ARMS, _cache_path, _key  # noqa: E402
from e101_verifier_sweep import _auc, _spearman  # noqa: E402

# Two float32 pipelines on different CPUs do not agree bit for bit. They must agree to well
# within any difference that could move an AUC, and rank correlation is the measure that matters
# because every metric here is rank-based.
RHO_FLOOR = 0.99
MAX_ABS_FLOOR = 0.05


def local_cached_scores(name: str, pairs: list[tuple[str, str]]) -> list[float] | None:
    """The laptop's scores for one arm, from cache ONLY, or None if it never scored it.

    Deliberately does not call `score_arm`. A comparability check is bookkeeping and must cost
    nothing: an earlier version of this file called `score_arm` for every arm the Fly host ran,
    and for an arm whose weights happen to be on this disk but whose scores are not cached, that
    silently starts a multi-hour local scoring run instead of reporting "not shared". Loading a
    model to find out whether a model was loaded is the wrong shape.
    """
    arm = ARMS.get(name)
    if arm is None:
        return None
    cp = _cache_path(arm)
    if not cp.exists():
        return None
    try:
        cache = json.loads(cp.read_text())
    except Exception:
        return None
    keys = [_key(arm, p, h) for p, h in pairs]
    if any(k not in cache for k in keys):
        return None
    return [cache[k] for k in keys]


def metrics(scores: list[float], plan: list[dict], meta: list[dict]) -> dict:
    by = {"supported": [], "refuted": [], "unverifiable": []}
    for entry, m in zip(plan, meta):
        s = maxscore(entry["cited"], scores)
        if s is not None:
            by[m["verdict"]].append(s)
    ruled = by["supported"] + by["refuted"]
    return {
        "n": {k: len(v) for k, v in by.items()},
        "auc_ruled_vs_unverifiable": round(_auc(ruled, by["unverifiable"]), 4),
        "auc_supported_vs_unverifiable": round(_auc(by["supported"], by["unverifiable"]), 4),
        "auc_refuted_vs_unverifiable": round(_auc(by["refuted"], by["unverifiable"]), 4),
        "auc_supported_vs_refuted": round(_auc(by["supported"], by["refuted"]), 4),
        "median": {k: round(statistics.median(v), 4) for k, v in by.items() if v},
    }


def main() -> int:
    pairs_path = Path(sys.argv[1])
    d = json.loads(pairs_path.read_text())
    pairs = [tuple(p) for p in d["pairs"]]
    plan, meta = d["plan"], d["sample_meta"]

    fly_dir = HERE / "fly_scores"
    fly = {}
    for f in sorted(fly_dir.glob("*.json")):
        blob = json.loads(f.read_text())
        if blob["corpus_fingerprint"]["sha256"] != d["corpus_fingerprint"]["sha256"]:
            raise SystemExit(f"{f.name}: scored against a different corpus — not comparable")
        if len(blob["scores"]) != len(pairs):
            raise SystemExit(f"{f.name}: {len(blob['scores'])} scores for {len(pairs)} pairs")
        fly[blob["arm"]] = blob

    # --- the comparability check, before any number is published
    # Checks EVERY arm the laptop also scored, not a named one. `hhem` was run in both places on
    # purpose; `nli-fever-bs` turned out to be shared as well, and an instrument that only knows
    # about the arm someone remembered to hardcode cannot notice the second control it was handed.
    # An arm the laptop never scored has no cache entry and is skipped, not failed.
    cross = []
    for arm in sorted(fly):
        local = local_cached_scores(arm, pairs)
        if local is None:
            continue
        remote = fly[arm]["scores"]
        rho = _spearman(local, remote)
        worst = max(abs(a - b) for a, b in zip(local, remote))
        cross.append({
            "arm": arm, "spearman_local_vs_fly": round(rho, 6),
            "max_abs_difference": round(worst, 6),
            "mean_abs_difference": round(
                sum(abs(a - b) for a, b in zip(local, remote)) / len(local), 6),
            "floors": {"spearman": RHO_FLOOR, "max_abs": MAX_ABS_FLOOR},
            "comparable": bool(rho >= RHO_FLOOR and worst <= MAX_ABS_FLOOR),
        })

    out = {
        "corpus_fingerprint": d["corpus_fingerprint"],
        "pairs_from": str(pairs_path),
        "n_pairs": len(pairs),
        "cross_host_checks": cross,
        "shared_arms": [c["arm"] for c in cross],
        "results": {},
    }
    for arm, blob in sorted(fly.items()):
        row = metrics(blob["scores"], plan, meta)
        row["pairs_per_second"] = blob["pairs_per_second"]
        row["wall_seconds"] = blob["wall_seconds"]
        row["scored_on"] = blob["scored_on"]
        out["results"][arm] = row

    dest = HERE / "e101_fly_stageA_receipts.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")

    if not cross:
        print("cross-host check: NO shared arm — the merged table below is NOT licensed.")
    for c in cross:
        print(f"cross-host check ({c['arm']}): rho={c['spearman_local_vs_fly']} "
              f"max_abs={c['max_abs_difference']} comparable={c['comparable']}")
    if any(c["comparable"] is False for c in cross):
        print("REFUSING to publish a merged table: the two hosts disagree on a shared arm.")
    print(f"\n{'arm':16s}{'AUC ruled':>11s}{'AUC sup':>9s}{'AUC ref':>9s}"
          f"{'AUC sup|ref':>13s}{'pairs/s':>10s}")
    for arm, r in sorted(out["results"].items(), key=lambda kv: -kv[1]["auc_ruled_vs_unverifiable"]):
        print(f"{arm:16s}{r['auc_ruled_vs_unverifiable']:11.4f}"
              f"{r['auc_supported_vs_unverifiable']:9.4f}{r['auc_refuted_vs_unverifiable']:9.4f}"
              f"{r['auc_supported_vs_refuted']:13.4f}{r['pairs_per_second']:10.2f}")
    print("\nreceipt:", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

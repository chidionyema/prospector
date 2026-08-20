"""E-101d — what the `lex-token` pre-filter actually costs, and whether it beats a free signal.

E-101 licensed exactly one thing: `lex-token` as a screen in front of the moat, skipping checks it
predicts the moat would rule `unverifiable`. Two questions have to be answered before that is wired
into anything, and neither is in the E-101 receipt.

1. WHAT DOES THE SCREEN THROW AWAY? "95.1% precision" is a ratio. The engine cares about the count:
   how many checks that the moat would have RULED does the screen discard, and a discarded check
   becomes `unverifiable` in a dossier that reads as fully reasoned. That is the same failure shape
   as `store/dossiers/2102bacc6dd75cf9.kill.json`, a candidate killed by our own outage.

2. DOES IT BEAT SOMETHING FREE? If a check comes out `unverifiable` mostly because retrieval found
   nothing on topic, the engine may already know that without scoring anything. This file measures
   two zero-cost baselines the engine has in hand at the moment the question is asked:

     passage_count  — how many passages retrieval returned for this check
     passage_chars  — how much text it returned

   If either matches `lex-token`, the screen is not worth its own code.

Reads the frozen pair file and the on-disk score cache. Zero paid calls, zero network.

    tools/experiments/e101d_screen_cost.py <pairs.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from _groundedness import maxscore  # noqa: E402
from _verifiers import score_arm  # noqa: E402
from e101_verifier_sweep import _auc  # noqa: E402

TARGET_PRECISION = 0.95


def screen(values: list[float], ruled: list[bool]) -> dict:
    """Lowest-scoring checks are screened out. Find the highest threshold that still keeps
    precision >= target, where precision is 'of the checks screened, what share really were
    unverifiable'. Reports the COUNT wrongly discarded, not only the ratio."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    best = {"coverage": 0.0, "threshold": None, "precision": 0.0,
            "screened": 0, "ruled_lost": 0, "of": len(values)}
    correct = 0
    for k, i in enumerate(order, start=1):
        if not ruled[i]:
            correct += 1
        prec = correct / k
        if prec >= TARGET_PRECISION:
            best = {"coverage": round(k / len(values), 4), "threshold": round(values[i], 4),
                    "precision": round(prec, 4), "screened": k, "ruled_lost": k - correct,
                    "of": len(values)}
    return best


def main() -> int:
    d = json.loads(Path(sys.argv[1]).read_text())
    pairs = [tuple(p) for p in d["pairs"]]
    plan, meta = d["plan"], d["sample_meta"]

    ruled, lex, n_passages, n_chars = [], [], [], []
    scores, _ = score_arm("lex-token", pairs, use_cache=True)
    for entry, m in zip(plan, meta):
        s = maxscore(entry["cited"], scores)
        if s is None:
            continue
        ruled.append(m["verdict"] in ("supported", "refuted"))
        lex.append(s)
        idxs = entry["cited"]
        n_passages.append(float(len(idxs)))
        n_chars.append(float(sum(len(pairs[i][0]) for i in idxs)))

    total_ruled = sum(ruled)
    arms = {"lex-token": lex, "passage_count": n_passages, "passage_chars": n_chars}
    out = {
        "pairs_from": sys.argv[1],
        "corpus_fingerprint": d["corpus_fingerprint"],
        "n_checks": len(ruled), "n_ruled": total_ruled, "n_unverifiable": len(ruled) - total_ruled,
        "target_precision": TARGET_PRECISION,
        "results": {},
    }
    for name, vals in arms.items():
        pos = [v for v, r in zip(vals, ruled) if r]
        neg = [v for v, r in zip(vals, ruled) if not r]
        row = screen(vals, ruled)
        row["auc_ruled_vs_unverifiable"] = round(_auc(pos, neg), 4)
        row["ruled_lost_share_of_all_ruled"] = (
            round(row["ruled_lost"] / total_ruled, 4) if total_ruled else None)
        out["results"][name] = row
        print(f"{name:16s} AUC {row['auc_ruled_vs_unverifiable']:.4f}  "
              f"screens {row['coverage']:6.1%} ({row['screened']:4d}/{row['of']})  "
              f"loses {row['ruled_lost']:3d} ruled checks "
              f"({row['ruled_lost_share_of_all_ruled'] or 0:.1%} of all ruled)")

    dest = HERE / "e101d_screen_cost_receipts.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print("\nreceipt:", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

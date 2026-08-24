#!/usr/bin/env python
"""E19 — does `confidence` separate a ruled check from an unruled one?

W0.2's standing receipt reported a confidence gap (ruled minus unverifiable) of -0.0405: the
engine was MORE confident on checks it could not verify than on ones it ruled. That number sat
in a report and nothing in the engine changed. This module re-measures it on the full dossier
corpus, splits it by verdict, and names the mechanism.

THE MECHANISM, read off the code rather than inferred: `verify._calc_confidence` is
`citation_score + diversity_score + relevance_score` (`verify.py:91-199`) and contains no
verdict term. It measures how much evidence RETRIEVAL returned, not how well the claim was
established. For `supported`/`refuted` those track together; for `unverifiable` they invert.

POPULATION. Every `*.json` in the dossier store carrying a `checks` list, minus checks flagged
`retrieval_failed` or `degraded` — those already write confidence 0.0 by construction
(`verify.py:857`, `:898`) and including them would bias the unverifiable bucket toward the
answer this module is testing for.

LIMITATIONS.
  * Observational. It reads what the engine wrote; it does not re-run any check.
  * The store is live unless a frozen snapshot is passed, so two runs over different
    fingerprints are different samples, not a repeat.
  * `dense_reward` values already on disk were computed against the pre-guard confidences and
    are not comparable to ones written after it. They are deliberately not backfilled.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

RULED = ("supported", "refuted")


def collect(store: Path) -> tuple[dict[str, list[float]], dict[str, list[int]], int, int]:
    conf: dict[str, list[float]] = {}
    cites: dict[str, list[int]] = {}
    n_dossier = n_skipped = 0
    for f in sorted(store.glob("*.json")):
        try:
            o = json.loads(f.read_text())
        except Exception:
            continue
        checks = o.get("checks") or o.get("verdicts")
        if not isinstance(checks, list):
            continue
        n_dossier += 1
        for c in checks:
            if not isinstance(c, dict):
                continue
            v, k = c.get("verdict"), c.get("confidence")
            if v is None or not isinstance(k, (int, float)):
                continue
            if c.get("retrieval_failed") or c.get("degraded"):
                n_skipped += 1
                continue
            conf.setdefault(v, []).append(float(k))
            cites.setdefault(v, []).append(len(c.get("citations") or []))
    return conf, cites, n_dossier, n_skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="a store/dossiers directory")
    args = ap.parse_args()
    store = Path(args.store)
    conf, cites, n_dossier, n_skipped = collect(store)
    if not conf:
        print(f"no checks found under {store}")
        return 1

    print(f"dossiers with checks: {n_dossier}   checks skipped (failed/degraded): {n_skipped}")
    print(f"{'verdict':<14}{'n':>7}{'mean':>9}{'median':>9}{'mean cites':>12}{'%cite>0':>9}")
    per_verdict = {}
    for v in sorted(conf, key=lambda k: -len(conf[k])):
        b, cc = conf[v], cites[v]
        row = dict(n=len(b), mean=round(st.mean(b), 4), median=round(st.median(b), 3),
                   mean_citations=round(st.mean(cc), 2),
                   pct_citing=round(100 * sum(1 for x in cc if x > 0) / len(cc), 1))
        per_verdict[v] = row
        print(f"{v:<14}{row['n']:>7}{row['mean']:>9.4f}{row['median']:>9.3f}"
              f"{row['mean_citations']:>12.2f}{row['pct_citing']:>8.1f}%")

    ruled = [x for v in RULED for x in conf.get(v, [])]
    unv = conf.get("unverifiable", [])
    receipts = dict(store=str(store), dossiers=n_dossier, skipped_failed_or_degraded=n_skipped,
                    per_verdict=per_verdict)
    if ruled and unv:
        gap = st.mean(ruled) - st.mean(unv)
        median_inverted = st.median(unv) > st.median([x for x in conf.get("supported", [])] or [0])
        high = sum(1 for x in unv if x >= 0.5)
        receipts.update(
            confidence_gap_ruled_minus_unverifiable=round(gap, 4),
            ruled_n=len(ruled), unverifiable_n=len(unv),
            unverifiable_at_or_above_0_5=high,
            unverifiable_at_or_above_0_5_pct=round(100 * high / len(unv), 1),
            median_inverted_vs_supported=bool(median_inverted),
            verdict=("DEFECT — confidence does not separate ruled from unruled"
                     if abs(gap) < 0.05 or gap < 0 else "separates"))
        print(f"\nCONFIDENCE GAP (ruled - unverifiable) = {gap:+.4f}")
        print(f"  unverifiable scoring >= 0.5: {high} ({100 * high / len(unv):.1f}%)")
        print(f"  median unverifiable above median supported: {median_inverted}")
        print(f"  VERDICT: {receipts['verdict']}")

    out = Path(__file__).with_name("e19_confidence_gap_receipts.json")
    out.write_text(json.dumps(receipts, indent=2))
    print(f"\nreceipts -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

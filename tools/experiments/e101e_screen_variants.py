"""E-101e — can a cheap variant of the screen buy more coverage at the same precision?

E-101 refuted every local model as a verdict mechanism, so the screen is the only lever this line
produced. Its value is coverage at a fixed precision: every point of coverage is a paid moat call
that never happens. `lex-token` (plain token overlap) buys 28.2% held out at 0.95 target. This file
asks whether a variant that is still free buys more.

The variants, and why each is here rather than a longer list:

  lex-token   the incumbent, scored by the REAL E-101 arm through `score_arm`, not re-implemented
              here. An earlier draft of this file re-implemented it and got AUC 0.8201 against the
              arm's 0.8273 — close enough to look right and wrong enough to make every comparison
              below meaningless. The variants must beat the thing that actually runs.
  lex-idf     the same, weighted by inverse document frequency over the passage corpus. A claim
              sharing the word "market" with its passage means much less than sharing "Tallinn".
              Plain overlap counts them the same, which is the obvious defect to attack first.
  lex-rare    the extreme of that: overlap computed over the claim's rarest third of tokens only.
              Tests whether the IDF weighting is doing work or the rare tokens are doing all of it.

All three take the best of the check's passages, the same pooling the E-101 arms use, so the only
thing that differs between them is the weighting.

IDF is computed over THIS pair set's passages, which is the only corpus available at score time in
a real run too -- the engine has the retrieved passages in hand and nothing else. No global index,
no training, no held-out leakage beyond what the deployment would also have.

Precision and coverage are always reported HELD OUT, on the same deterministic alternating split as
E-101d, because E-101d showed the in-sample figure is optimistic by nine points of coverage.

It also prints the CEILING: the share of checks the moat rules `unverifiable` at all. No screen,
however good, can skip more than that, so the number bounds this entire line of work against the
programme's 100x target before anyone spends more effort on it.

Reads the frozen pair file. Zero paid calls, zero network, no model weights.

    tools/experiments/e101e_screen_variants.py <pairs.json>
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from _groundedness import maxscore  # noqa: E402
from _verifiers import score_arm  # noqa: E402
from e101_verifier_sweep import _auc  # noqa: E402

WORD = re.compile(r"[a-z0-9]+")
# Copied from _verifiers._content_words rather than imported: this file must keep working if that
# module's stopword list is tuned for the neural arms, and a screen whose tokeniser moves under it
# is a screen whose published coverage is unreproducible.
STOP = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for", "with", "as", "by",
    "at", "from", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that",
    "these", "those", "there", "their", "has", "have", "had", "not", "no", "can", "could", "will",
    "would", "may", "might", "do", "does", "did", "than", "then", "so", "such", "which", "who",
}


def toks(text: str) -> list[str]:
    return [w for w in WORD.findall((text or "").lower()) if w not in STOP and len(w) > 1]


def build_idf(passages: list[str]) -> dict[str, float]:
    df: Counter[str] = Counter()
    for p in passages:
        df.update(set(toks(p)))
    n = max(1, len(passages))
    return {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}


def sc_idf(claim: set[str], passage: set[str], idf: dict[str, float]) -> float:
    tot = sum(idf.get(w, 1.0) for w in claim)
    return sum(idf.get(w, 1.0) for w in claim & passage) / tot if tot else 0.0


def sc_rare(claim: set[str], passage: set[str], idf: dict[str, float]) -> float:
    if not claim:
        return 0.0
    # The word itself is the tie-break. Without it `claim` is a set, equal-IDF words rank in
    # whatever order iteration happened to yield, and three runs of this file gave lex-rare AUC
    # 0.7750, 0.7732 and 0.7718. A screen whose number moves between runs cannot be published.
    ranked = sorted(claim, key=lambda w: (-idf.get(w, 1.0), w))
    rare = set(ranked[:max(1, len(ranked) // 3)])
    return len(rare & passage) / len(rare)


# The incumbent is not in here: it comes from `score_arm`, so a change to the shipped arm shows up
# in this comparison instead of being silently reproduced.
VARIANTS = {"lex-idf": sc_idf, "lex-rare": sc_rare}


def screen_heldout(vals: list[float], ruled: list[bool], target: float) -> dict:
    fit_v, fit_r = vals[0::2], ruled[0::2]
    ho_v, ho_r = vals[1::2], ruled[1::2]

    order = sorted(range(len(fit_v)), key=lambda i: fit_v[i])
    thr, correct = None, 0
    for k, i in enumerate(order, start=1):
        if not fit_r[i]:
            correct += 1
        if correct / k >= target:
            thr = fit_v[i]
    if thr is None:
        return {"target": target, "threshold": None, "heldout_coverage": 0.0,
                "heldout_ruled_lost": 0, "heldout_precision": None}
    sel = [i for i, v in enumerate(ho_v) if v <= thr]
    lost = sum(1 for i in sel if ho_r[i])
    return {
        "target": target, "threshold": round(thr, 4),
        "heldout_coverage": round(len(sel) / len(ho_v), 4),
        "heldout_ruled_lost": lost,
        "heldout_precision": round((len(sel) - lost) / len(sel), 4) if sel else None,
        "heldout_n": len(ho_v), "heldout_ruled": sum(ho_r),
    }


def main() -> int:
    d = json.loads(Path(sys.argv[1]).read_text())
    pairs = [tuple(p) for p in d["pairs"]]
    idf = build_idf([p[0] for p in pairs])

    incumbent, _ = score_arm("lex-token", pairs, use_cache=True)

    ruled: list[bool] = []
    kept_meta: list[dict] = []   # the verdict of every check that survived the cited/scored filter
    per_variant: dict[str, list[float]] = {k: [] for k in VARIANTS}
    per_variant["lex-token"] = []
    for entry, meta in zip(d["plan"], d["sample_meta"]):
        idxs = entry["cited"]
        s_inc = maxscore(idxs, incumbent)
        if not idxs or s_inc is None:
            continue
        ruled.append(meta["verdict"] in ("supported", "refuted"))
        kept_meta.append(meta)
        per_variant["lex-token"].append(s_inc)
        # the hypothesis is identical across a check's passages; pairs are (passage, rationale)
        claim = set(toks(pairs[idxs[0]][1]))
        for name, fn in VARIANTS.items():
            per_variant[name].append(max(fn(claim, set(toks(pairs[i][0])), idf) for i in idxs))

    out = {
        "pairs_from": sys.argv[1], "corpus_fingerprint": d["corpus_fingerprint"],
        "n_checks": len(ruled), "n_ruled": sum(ruled),
        "idf_vocab": len(idf), "idf_built_over_passages": len(pairs),
        "incumbent": "lex-token", "results": {},
    }
    print(f"{len(ruled)} checks, {sum(ruled)} ruled, IDF vocabulary {len(idf)}\n")
    print(f"{'variant':12s}{'AUC':>8s}   " + "".join(f"{f'cov@{t}':>12s}" for t in (0.95, 0.98)))
    for name, vals in per_variant.items():
        pos = [v for v, r in zip(vals, ruled) if r]
        neg = [v for v, r in zip(vals, ruled) if not r]
        rows = [screen_heldout(vals, ruled, t) for t in (0.90, 0.95, 0.98, 0.99, 1.00)]
        out["results"][name] = {"auc_ruled_vs_unverifiable": round(_auc(pos, neg), 4),
                                "heldout_operating_points": rows}
        cov = {r["target"]: r for r in rows}
        print(f"{name:12s}{out['results'][name]['auc_ruled_vs_unverifiable']:8.4f}   "
              + "".join(f"{cov[t]['heldout_coverage']:11.1%} " for t in (0.95, 0.98))
              + f"  lost@0.95 {cov[0.95]['heldout_ruled_lost']}"
              + f"  lossless(fit@1.00) {cov[1.00]['heldout_coverage']:.1%}"
              + f"/lost {cov[1.00]['heldout_ruled_lost']}")

    # --- the union of the two lossless screens
    # Each variant, on its own, screens some checks at zero cost to the moat's ruled ones. They do
    # not necessarily screen the SAME checks: plain overlap and IDF-weighted overlap disagree most
    # on claims whose shared words are common ones. If the two lossless sets barely overlap, taking
    # either is strictly more coverage for the same promise. If they are the same set, it is not.
    # Thresholds come from the fit half only; coverage and loss are measured on the held-out half.
    def lossless_threshold(vals):
        order = sorted(range(len(vals[0::2])), key=lambda i: vals[0::2][i])
        fv, fr = vals[0::2], ruled[0::2]
        thr = None
        for k, i in enumerate(order, start=1):
            if fr[i]:
                break
            thr = fv[i]
        return thr

    t_tok = lossless_threshold(per_variant["lex-token"])
    t_idf = lossless_threshold(per_variant["lex-idf"])
    ho_r = ruled[1::2]
    ho_tok, ho_idf = per_variant["lex-token"][1::2], per_variant["lex-idf"][1::2]
    sets = {}
    for label, pred in (
        ("lex-token alone", lambda i: ho_tok[i] <= t_tok),
        ("lex-idf alone", lambda i: ho_idf[i] <= t_idf),
        ("either (union)", lambda i: ho_tok[i] <= t_tok or ho_idf[i] <= t_idf),
        ("both (intersection)", lambda i: ho_tok[i] <= t_tok and ho_idf[i] <= t_idf),
    ):
        sel = [i for i in range(len(ho_r)) if pred(i)]
        lost = sum(1 for i in sel if ho_r[i])
        sets[label] = {"heldout_screened": len(sel), "heldout_of": len(ho_r),
                       "heldout_coverage": round(len(sel) / len(ho_r), 4),
                       "heldout_ruled_lost": lost,
                       "heldout_precision": round((len(sel) - lost) / len(sel), 4) if sel else None}
    out["lossless_union"] = {"threshold_lex_token": t_tok, "threshold_lex_idf": t_idf,
                             "fitted_on": "fit half, target precision 1.00", "sets": sets}
    print("\nlossless screens, thresholds fitted on the fit half, measured held out:")
    for label, r in sets.items():
        print(f"  {label:22s} {r['heldout_coverage']:6.1%} "
              f"({r['heldout_screened']:3d}/{r['heldout_of']})  ruled lost {r['heldout_ruled_lost']}")

    # --- the ceiling on this whole line of work
    # A screen can only ever skip checks the moat would have ruled `unverifiable`. That share is a
    # property of the corpus, not of the screen, so it bounds every variant that will ever be tried
    # here — including a perfect one. Reporting it stops the next person spending a week chasing
    # coverage that does not exist. Speedup is on MOAT CALLS in the verify step, which is the only
    # thing a screen touches; it is not an end-to-end run-time claim.
    n = len(ruled)
    n_unver = n - sum(ruled)
    def speedup(cov):
        return round(1.0 / (1.0 - cov), 3) if cov < 1.0 else None
    ceiling = {
        "n_checks": n, "n_ruled": sum(ruled), "n_unverifiable": n_unver,
        "class_counts": dict(Counter(m["verdict"] for m in kept_meta)),
        "measures": "moat calls in the verify step; not an end-to-end run-time claim",
        "operating_points": {
            "free_lex_idf_fit_at_1.00": {
                "heldout_coverage": sets["lex-idf alone"]["heldout_coverage"],
                "ruled_lost": sets["lex-idf alone"]["heldout_ruled_lost"],
                "moat_call_speedup": speedup(sets["lex-idf alone"]["heldout_coverage"])},
            "decision_lex_token_at_0.95": {
                "heldout_coverage": out["results"]["lex-token"]["heldout_operating_points"][1][
                    "heldout_coverage"],
                "ruled_lost": out["results"]["lex-token"]["heldout_operating_points"][1][
                    "heldout_ruled_lost"],
                "moat_call_speedup": speedup(out["results"]["lex-token"][
                    "heldout_operating_points"][1]["heldout_coverage"])},
            "perfect_screen": {
                "heldout_coverage": round(n_unver / n, 4), "ruled_lost": 0,
                "moat_call_speedup": speedup(n_unver / n)},
        },
    }
    out["ceiling"] = ceiling
    print("\nceiling on moat-call speedup from ANY screen (this corpus):")
    for label, r in ceiling["operating_points"].items():
        print(f"  {label:28s} skips {r['heldout_coverage']:6.1%}  "
              f"loses {r['ruled_lost']:2d} ruled  ->  {r['moat_call_speedup']:.2f}x")

    dest = HERE / "e101e_screen_variants_receipts.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print("\nreceipt:", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

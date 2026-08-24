#!/usr/bin/env python3
"""E101 — exhaust the local-verifier options against the moat, on one identical pair set.

WHAT THIS ANSWERS. Can a small model that runs for free, locally, and always, do the mechanical
part of the moat's verdict step? A1 availability is 0%: when every hosted brain is dead the engine
stops. A local verifier that tracks the moat is the only route to a verdict path with no external
dependency at all, so the question is worth exhausting rather than sampling.

WHAT E17 LEFT OPEN, AND WHY THIS IS NOT A REPEAT OF IT. E17 measured exactly one model, HHEM-2.1,
and got AUC 0.673 separating the moat's ruled checks from its unverifiable ones -- weak. It stated
in its own docstring that MiniCheck was "skipped unless a local copy already exists". One number
from one instrument cannot distinguish "small models cannot do this" from "that particular small
model cannot do this", and those two conclusions lead opposite ways. This runs the field.

THE ARMS AND WHY EACH ONE IS HERE. Registry with sizes, formats and notes: `_verifiers.py`.

  lex-token / lex-3gram / lex-number   The floor. No model, no download. A neural arm that does
      not beat counting shared words has not earned a deployment, whatever its leaderboard row.
  hhem                                 The E17 baseline, re-measured on this exact sample so the
      comparison is paired rather than remembered.
  vitaminc                             Trained on VitaminC, whose labels ARE ours: its head emits
      SUPPORTS / REFUTES / NOT ENOUGH INFO, one-to-one with supported / refuted / unverifiable.
      59M parameters. The closest conceptual match in the field, and the smallest arm in it.
  nli-fever-bs / nli-fever-lg          General entailment trained through FEVER, 184M and 435M.
      The question they answer is whether generic NLI is enough or fact-verification training is
      what matters.

  Not runnable here, and the reason is a file format rather than a size: the whole MiniCheck
  family publishes pickle checkpoints, and transformers refuses torch.load below torch 2.6
  (CVE-2025-32434) while macOS x86_64 has no torch above 2.2.2. Those arms, plus Bespoke-MiniCheck
  -7B and Lynx-8B, run on a Fly host against this same frozen pair set. `--only`/`--skip` select.

THE MEASURE, FIXED BEFORE ANY ARM RAN. Primary is AUC separating the moat's RULED checks from its
UNVERIFIABLE ones -- rank-based, threshold-free, and identical to E17's so the numbers can be put
side by side. Reported split by class, never averaged into one "ruled" figure, because `refuted`
rationales are negations and entailment models score negations low for reasons that are the
instrument and not the moat. E17 established that confound and it applies unchanged here.

THE REFUTING OUTCOME, STATED BEFORE THE RUN. If no arm's AUC materially exceeds HHEM's 0.673, and
in particular if no arm beats `lex-token`, then the local-classifier route is dead as a verdict
mechanism and survives only as a cheap screen in front of the moat. That outcome is publishable
and it closes the question; it is not a failed experiment.

WHAT THIS IS NOT. Neither instrument is ground truth. The moat's labels are a model's judgements,
not adjudicated fact, so every number here is CONCORDANCE BETWEEN TWO INSTRUMENTS and never
accuracy. Nothing in this file licenses the sentence "arm X is 82% accurate".

Zero tokens, zero paid calls, zero network at score time.

Usage:
    .venv/bin/python tools/experiments/runner.py run E101 -- --limit 1200
    .venv/bin/python tools/experiments/runner.py run E101 -- --only vitaminc,hhem --limit 200
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _corpus import corpus_fingerprint  # noqa: E402
from _groundedness import (  # noqa: E402
    MAX_PASSAGES,
    build_pairs,
    collect_checks,
    maxscore,
    quantile,
    stratified_sample,
)
from _verifiers import (  # noqa: E402
    ARMS,
    ArmUnavailable,
    disk_free_gb,
    evict,
    number_fallback_rate,
    score_arm,
)

NAME = "E101"
CLASSES = ("supported", "refuted", "unverifiable")
RULED = {"supported", "refuted"}
DEFAULT_ARMS = ["lex-token", "lex-3gram", "lex-number", "vitaminc", "hhem",
                "nli-fever-bs", "nli-fever-lg"]


def describe() -> str:
    return ("E101 — sweep every locally-runnable verifier (3 lexical, 4 neural) against the "
            "moat's own verdicts on one identical pair set: AUC, per-class agreement, "
            "throughput, and how far the arms agree with each other.")


def _parse(args: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="E101", add_help=False)
    p.add_argument("--limit", type=int, default=1200)
    p.add_argument("--all", action="store_true", help="every eligible check, ignore --limit")
    p.add_argument("--only", default="", help="comma-separated arm names")
    p.add_argument("--skip", default="")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--evict-after", action="store_true",
                   help="delete each neural arm's weights once scored (disk is the constraint)")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("-h", "--help", action="help")
    return p.parse_args(args)


def _auc(pos: list[float], neg: list[float]) -> float:
    """Exact rank-based AUC (Mann-Whitney U / |pos||neg|), ties counted as half.

    Copied deliberately from E17 rather than imported through a refactor: E17's published 0.673
    must keep meaning exactly what it meant, and a shared helper that someone later 'improves'
    would silently move a number this experiment is compared against.
    """
    if not pos or not neg:
        return 0.0
    merged = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = {}, 0
    while i < len(merged):
        j = i
        while j + 1 < len(merged) and merged[j + 1][0] == merged[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum = sum(ranks[k] for k, (_v, lab) in enumerate(merged) if lab == 1)
    n1, n0 = len(pos), len(neg)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


def _spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation. Two arms at 0.95 are one arm with two download sizes."""
    def rank(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else 0.0


def _screen_coverage(per: list[dict], arm: str, target_precision: float = 0.95) -> dict:
    """The practical question behind the whole sweep, if no arm is good enough to RULE.

    If the arm cannot replace the moat it can still stand in front of it: score every check, and
    where the arm is confident enough that the moat would have said `unverifiable`, skip the moat
    call entirely. This finds the lowest threshold at which that skip is right at least
    `target_precision` of the time, and reports the share of the corpus it covers. A screen that
    covers 3% is not worth building; one that covers 40% halves the moat's bill.
    """
    rows = sorted(((r["scores"][arm], r["verdict"]) for r in per if arm in r["scores"]),
                  key=lambda x: x[0])
    if not rows:
        return {"coverage": 0.0, "threshold": None, "precision": 0.0, "n": 0}
    best = {"coverage": 0.0, "threshold": None, "precision": 0.0, "n": len(rows)}
    unver_below = 0
    for i, (score, verdict) in enumerate(rows, start=1):
        if verdict == "unverifiable":
            unver_below += 1
        prec = unver_below / i
        if prec >= target_precision:
            best = {"coverage": round(i / len(rows), 4), "threshold": round(score, 4),
                    "precision": round(prec, 4), "n": len(rows),
                    "checks_screened": i, "of": len(rows)}
    return best


def run(args: list[str] | None = None) -> dict:
    opts = _parse(list(args or []))

    wanted = [a.strip() for a in opts.only.split(",") if a.strip()] or list(DEFAULT_ARMS)
    skip = {a.strip() for a in opts.skip.split(",") if a.strip()}
    wanted = [a for a in wanted if a not in skip]
    unknown = [a for a in wanted if a not in ARMS]
    if unknown:
        raise SystemExit(f"unknown arm(s): {unknown}. Known: {sorted(ARMS)}")

    records, premise_source = [], defaultdict(int)
    for rec in collect_checks(verdicts=set(CLASSES)):
        if rec["cited"]:
            rec["_premise_source"] = "cited"
        elif rec["uncited"]:
            rec["_premise_source"] = "retrieved_uncited"
            rec["cited"] = rec["uncited"][:MAX_PASSAGES]
        else:
            premise_source["no_passage_at_all"] += 1
            continue
        premise_source[rec["_premise_source"]] += 1
        records.append(rec)
    if not records:
        raise RuntimeError("no checks with any stored passage on disk")

    eligible = len(records)
    limit = None if opts.all else opts.limit
    sample = stratified_sample(records, "verdict", limit)
    pairs, plan = build_pairs(sample, control=True, max_passages=2, uncited_arm=False)
    pairs = [tuple(p) for p in pairs]

    print(f"E101 verifier sweep — {len(sample)} of {eligible} eligible checks, "
          f"{len(pairs)} pairs, {len(wanted)} arms, disk free {disk_free_gb()} GB")

    arm_scores: dict[str, list[float]] = {}
    arm_meta: dict[str, dict] = {}
    unavailable: dict[str, str] = {}
    for name in wanted:
        t0 = time.time()
        try:
            scores, meta = score_arm(name, pairs, batch_size=opts.batch_size,
                                     use_cache=not opts.no_cache)
        except ArmUnavailable as exc:
            unavailable[name] = str(exc)
            print(f"  {name:14s} UNAVAILABLE — {exc}")
            continue
        wall = time.time() - t0
        meta["wall_seconds"] = round(wall, 2)
        meta["pairs_per_second"] = round(len(pairs) / wall, 2) if wall else None
        arm_scores[name], arm_meta[name] = scores, meta
        print(f"  {name:14s} done in {wall:7.1f}s  ({meta['pairs_per_second']} pairs/s)")
        if opts.evict_after and not ARMS[name].is_lexical:
            print(f"    evicted: {evict(name)}")

    if not arm_scores:
        raise RuntimeError(f"no arm produced a score. unavailable={unavailable}")

    # Collapse per-passage pair scores to one score per CHECK: max over the check's passages,
    # matching E17 and matching MiniCheck's own max-over-chunks aggregation.
    per: list[dict] = []
    null_by_arm: dict[str, list[float]] = defaultdict(list)
    for rec, entry in zip(sample, plan):
        row_scores = {}
        for arm, scores in arm_scores.items():
            s = maxscore(entry["cited"], scores)
            n = maxscore(entry["null"], scores)
            if n is not None:
                null_by_arm[arm].append(n)
            if s is not None:
                row_scores[arm] = s
        if not row_scores:
            continue
        per.append({"verdict": rec["verdict"], "check_name": rec["check_name"],
                    "premise_source": rec["_premise_source"], "provider": rec["provider"],
                    "scores": row_scores})

    class_n = {c: sum(1 for r in per if r["verdict"] == c) for c in CLASSES}
    results = {}
    for arm in arm_scores:
        vals = {c: [r["scores"][arm] for r in per
                    if r["verdict"] == c and arm in r["scores"]] for c in CLASSES}
        ruled = vals["supported"] + vals["refuted"]
        unver = vals["unverifiable"]
        # tau from the NULL arm: the score this arm gives a premise it has no business supporting.
        nulls = sorted(null_by_arm[arm])
        tau = round(quantile(nulls, 0.95), 4) if nulls else 0.5
        agree = {c: (round(sum(1 for v in vals[c] if (v >= tau) == (c in RULED)) / len(vals[c]), 4)
                     if vals[c] else None) for c in CLASSES}
        results[arm] = {
            "auc_ruled_vs_unverifiable": round(_auc(ruled, unver), 4),
            "auc_supported_vs_unverifiable": round(_auc(vals["supported"], unver), 4),
            "auc_refuted_vs_unverifiable": round(_auc(vals["refuted"], unver), 4),
            "tau_null_p95": tau,
            "agreement_at_tau": agree,
            "median": {c: round(quantile(sorted(vals[c]), 0.5), 4) if vals[c] else None
                       for c in CLASSES},
            "screen_at_95_precision": _screen_coverage(per, arm, 0.95),
            "wall_seconds": arm_meta[arm]["wall_seconds"],
            "pairs_per_second": arm_meta[arm]["pairs_per_second"],
            "weights_gb": ARMS[arm].weights_gb,
            "runs_where": ARMS[arm].where,
        }

    order = sorted(results, key=lambda a: -results[a]["auc_ruled_vs_unverifiable"])
    corr = {}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            common = [(r["scores"][a], r["scores"][b]) for r in per
                      if a in r["scores"] and b in r["scores"]]
            if common:
                corr[f"{a}|{b}"] = round(
                    _spearman([x for x, _ in common], [y for _, y in common]), 4)

    floor = max((results[a]["auc_ruled_vs_unverifiable"]
                 for a in results if ARMS[a].is_lexical), default=0.0)
    best = order[0]
    beats_floor = [a for a in order
                   if not ARMS[a].is_lexical
                   and results[a]["auc_ruled_vs_unverifiable"] > floor]

    print(f"\n{'arm':15s}{'AUC':>7s}{'sup':>7s}{'ref':>7s}{'tau':>8s}{'screen@95%':>12s}"
          f"{'pairs/s':>9s}  where")
    for a in order:
        r = results[a]
        print(f"  {a:13s}{r['auc_ruled_vs_unverifiable']:7.3f}"
              f"{r['auc_supported_vs_unverifiable']:7.3f}{r['auc_refuted_vs_unverifiable']:7.3f}"
              f"{r['tau_null_p95']:8.3f}{r['screen_at_95_precision']['coverage']:12.1%}"
              f"{(r['pairs_per_second'] or 0):9.1f}  {r['runs_where']}")
    print(f"\nlexical floor AUC {floor:.3f}; best arm {best} at "
          f"{results[best]['auc_ruled_vs_unverifiable']:.3f}; "
          f"neural arms beating the floor: {beats_floor or 'NONE'}")

    return {
        "question": ("Can any locally-runnable verifier reproduce the moat's ruled/unverifiable "
                     "split well enough to stand in for it, or in front of it?"),
        "corpus_fingerprint": corpus_fingerprint(),
        "eligible_checks": eligible,
        "sampled_checks": len(sample),
        "scored_checks": len(per),
        "pairs": len(pairs),
        "class_counts": class_n,
        "premise_source_counts": dict(premise_source),
        "number_fallback_rate_lex_number": round(number_fallback_rate(pairs), 4),
        "arms_run": order,
        "arms_unavailable": unavailable,
        "results": results,
        "spearman_between_arms": corr,
        "lexical_floor_auc": round(floor, 4),
        "best_arm": best,
        "neural_arms_beating_lexical_floor": beats_floor,
        "arm_meta": {a: {k: v for k, v in m.items() if k != "sidecar"}
                     for a, m in arm_meta.items()},
        "disk_free_gb_after": disk_free_gb(),
        "interpretation": {
            "not_accuracy": ("Both sides are instruments. The moat's labels are a model's "
                             "judgements, not adjudicated fact. Every number here is "
                             "concordance between two instruments."),
            "negation_confound": ("refuted rationales are negations and entailment models score "
                                  "negations low. auc_refuted_vs_unverifiable is therefore "
                                  "expected to sit below the supported column for reasons that "
                                  "are the instrument, not the moat. Established in E17."),
            "premise_clip": ("Premises are clipped to 1500 chars by _groundedness.py:35, chosen "
                             "for HHEM's 512-token window. Arms with longer windows are "
                             "handicapped by it. The clip is kept so the comparison stays "
                             "paired."),
            "floor_first": ("Read every neural AUC against lexical_floor_auc before reading it "
                            "against HHEM."),
        },
        "_receipt_suffix": "_full" if opts.all else "",
    }


def main() -> int:
    from runner import run_one
    result = run_one(NAME, sys.argv[1:])
    print(f"\nreceipts   -> {result['receipts_path']}")
    print(f"doc append -> {result['doc_append_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

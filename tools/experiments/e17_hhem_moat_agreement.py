#!/usr/bin/env python3
"""E17 — does a free local entailment model agree with the moat's own verdicts?

Programme doc §14 (line ~507): "E17: HHEM/MiniCheck agreement vs moat verdicts on the 2,458 ruled
checks (sharpens E14a with named models)."

WHY THIS IS THE E14 LADDER'S FIRST RUNG. §14 proposes moving the mechanical part of verification
to small local models and leaving the frontier model to compose the three-way verdict. That plan
is only worth costing if a small local model tracks the moat at all. This measures it on data
already on disk, for zero tokens.

THE AGREEMENT DEFINITION, STATED BEFORE THE NUMBERS. HHEM emits one number: P(rationale entailed
by passage). The moat emits one of three labels. Mapping the number onto the labels is a CHOICE,
so it is written down and defended rather than implied:

    supported / refuted  -> the moat RULED. It claims a passage settled the question, so a
                            faithful rationale should be entailed by that passage.
                            agreement := HHEM score >= tau
    unverifiable         -> the moat DECLINED to rule. The rationale is typically "no retrieved
                            passage addresses this", which by construction is not entailed by any
                            of them.
                            agreement := HHEM score <  tau

Under that mapping, agreement is a real test with a real way to fail: if HHEM scored every pair
the same, agreement on ruled and agreement on unverifiable would sum to ~1 and the instrument
would be shown to be measuring nothing. Both are reported, plus the rank-based separation (AUC)
between the ruled and unverifiable score distributions, which is threshold-free and is the honest
headline.

THE KNOWN CONFOUND, MEASURED NOT ASSUMED. `refuted` rationales are negations, and entailment
models systematically score negation lower. If refuted agreement is far below supported agreement,
that is at least partly the instrument, not the moat. The two classes are therefore never averaged
into a single "ruled" number without the split alongside it.

PREMISE SELECTION. Cited passages when the check has them; otherwise the passages the check
retrieved. `unverifiable` checks usually cite nothing, so without the fallback the class would be
empty and the comparison impossible. Which source was used is recorded per check and reported.

MINICHECK: skipped unless a local copy already exists. The module probes the HF cache and reports
what it found; it never downloads a model.

Zero tokens, zero paid calls, zero network. HHEM runs in the python3.12 sidecar (`_hhem.py`).

Usage:
    .venv/bin/python tools/experiments/runner.py run E17 -- --limit 1200
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import RULED, corpus_fingerprint, wilson  # noqa: E402
from _groundedness import (  # noqa: E402
    MAX_PASSAGES,
    build_pairs,
    collect_checks,
    maxscore,
    quantile,
    stratified_sample,
)
from _hhem import score_pairs  # noqa: E402

NAME = "E17"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §14 (line ~507)"

CLASSES = ("supported", "refuted", "unverifiable")
DEFAULT_LIMIT = 1200
HF_HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def describe() -> str:
    return ("HHEM entailment vs the moat's own verdict per class (supported/refuted/"
            "unverifiable): agreement, and the threshold-free AUC separation.")


def _parse(args: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="E17", add_help=False)
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--all", action="store_true")
    p.add_argument("--current-moat", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("-h", "--help", action="help")
    return p.parse_args(args)


def _minicheck_probe() -> dict:
    """Is a MiniCheck copy ALREADY on disk? A probe, not a paragraph — and never a download."""
    hits = []
    if HF_HUB.exists():
        hits = [p.name for p in HF_HUB.iterdir()
                if "minicheck" in p.name.lower() or "bespoke" in p.name.lower()]
    return {"hf_hub": str(HF_HUB), "hf_hub_exists": HF_HUB.exists(),
            "minicheck_dirs_found": hits,
            "status": "PRESENT" if hits else "SKIPPED — no local copy; no model was downloaded",
            "all_cached_models": sorted(p.name for p in HF_HUB.iterdir())
            if HF_HUB.exists() else []}


def _auc(pos: list[float], neg: list[float]) -> float:
    """Exact rank-based AUC (Mann-Whitney U / |pos||neg|), ties counted as half.

    Threshold-free, so it answers "does HHEM separate ruled from unverifiable at all" without
    depending on the tau chosen further down.
    """
    if not pos or not neg:
        return 0.0
    merged = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks = {}
    i = 0
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


def run(args: list[str] | None = None) -> dict:
    opts = _parse(list(args or []))

    records = []
    premise_source = defaultdict(int)
    for rec in collect_checks(verdicts=set(CLASSES), moat_only=opts.current_moat):
        if rec["cited"]:
            rec["_premise_source"] = "cited"
        elif rec["uncited"]:
            rec["_premise_source"] = "retrieved_uncited"
            rec["cited"] = rec["uncited"][:MAX_PASSAGES]     # premise fallback, recorded as such
        else:
            premise_source["no_passage_at_all"] += 1
            continue
        premise_source[rec["_premise_source"]] += 1
        records.append(rec)

    eligible = len(records)
    if not records:
        raise RuntimeError("no checks with any stored passage on disk")

    limit = None if opts.all else opts.limit
    sample = stratified_sample(records, "verdict", limit)
    rule = ("every eligible check" if limit is None else
            f"systematic every-k-th within each verdict class, quota proportional to the class "
            f"mix; deterministic, no RNG (limit={limit})")

    # E17 reads only the CITED and NULL arms; building the UNCITED arm here would
    # double the runtime for numbers this experiment never looks at.
    pairs, plan = build_pairs(sample, control=True, max_passages=2,
                              uncited_arm=False)
    print(f"E17 HHEM vs moat — {len(sample)} of {eligible} eligible checks, {len(pairs)} pairs")
    scores, meta = score_pairs(pairs, use_cache=not opts.no_cache)

    per = []
    null_s = []
    for rec, entry in zip(sample, plan):
        s = maxscore(entry["cited"], scores)
        n = maxscore(entry["null"], scores)
        if n is not None:
            null_s.append(n)
        if s is None:
            continue
        per.append({"path": rec["path"], "candidate_id": rec["candidate_id"],
                    "check_name": rec["check_name"], "verdict": rec["verdict"],
                    "confidence": rec["confidence"], "provider": rec["provider"],
                    "premise_source": rec["_premise_source"], "hhem": s,
                    "n_citations": rec["n_citations"], "n_dangling": rec["n_dangling"],
                    "rationale": rec["rationale"][:300]})

    tau = round(quantile(sorted(null_s), 0.95), 4) if null_s else 0.5

    by_class = defaultdict(list)
    for r in per:
        by_class[r["verdict"]].append(r["hhem"])

    ruled_scores = by_class["supported"] + by_class["refuted"]
    unver_scores = by_class["unverifiable"]
    auc = _auc(ruled_scores, unver_scores)

    agree = {}
    for cls in CLASSES:
        vals = by_class.get(cls, [])
        if not vals:
            agree[cls] = {"n": 0}
            continue
        want_grounded = cls in RULED
        ok = sum(1 for v in vals if (v >= tau) == want_grounded)
        lo, hi = wilson(ok, len(vals))
        agree[cls] = {
            "n": len(vals),
            "moat_expectation": "entailed" if want_grounded else "not entailed",
            "agree": ok,
            "agreement": round(ok / len(vals), 4),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "median_hhem": round(quantile(sorted(vals), 0.5), 4),
            "mean_hhem": round(statistics.fmean(vals), 4),
            "share_above_tau": round(sum(1 for v in vals if v >= tau) / len(vals), 4),
        }

    total_n = sum(a.get("n", 0) for a in agree.values())
    total_agree = sum(a.get("agree", 0) for a in agree.values())
    tlo, thi = wilson(total_agree, total_n)

    by_check = defaultdict(lambda: defaultdict(list))
    for r in per:
        by_check[r["check_name"]][r["verdict"]].append(r["hhem"])

    print()
    print(f"instrument: {meta.get('model')}   tau={tau} (95th pct of the NULL control, n="
          f"{len(null_s)})")
    print(f"premise source: {dict(premise_source)}")
    print()
    print("--- agreement with the moat, per verdict class ---")
    print(f"  {'class':<14}{'n':>6}  {'moat expects':<14}{'agreement':>11}   95% CI          "
          f"median HHEM")
    for cls in CLASSES:
        a = agree[cls]
        if not a.get("n"):
            print(f"  {cls:<14}{0:>6}   (none)")
            continue
        print(f"  {cls:<14}{a['n']:>6}  {a['moat_expectation']:<14}{a['agreement']:>10.1%}   "
              f"[{a['wilson95'][0]:.1%}-{a['wilson95'][1]:.1%}]   {a['median_hhem']}")
    print(f"  {'ALL':<14}{total_n:>6}  {'':<14}{total_agree/total_n:>10.1%}   "
          f"[{tlo:.1%}-{thi:.1%}]")
    print()
    print("--- threshold-free separation (the honest headline) ---")
    print(f"  AUC(ruled > unverifiable) = {auc:.4f}   "
          f"(0.5 = the instrument cannot tell them apart)")
    print(f"  median HHEM ruled={quantile(sorted(ruled_scores), 0.5):.4f}  "
          f"unverifiable={quantile(sorted(unver_scores), 0.5):.4f}" if unver_scores else "")
    print()
    print("--- the negation confound, measured ---")
    sup, ref = agree.get("supported", {}), agree.get("refuted", {})
    if sup.get("n") and ref.get("n"):
        print(f"  supported median {sup['median_hhem']} vs refuted median {ref['median_hhem']}  "
              f"(delta {sup['median_hhem'] - ref['median_hhem']:+.4f})")
        print("  a large positive delta is at least partly HHEM's known weakness on negation, "
              "not the moat's.")
    print()
    print("--- by check ---")
    for name in sorted(by_check):
        cols = " ".join(f"{c[:5]}={len(by_check[name][c])}/"
                        f"{quantile(sorted(by_check[name][c]), 0.5):.2f}"
                        for c in CLASSES if by_check[name][c])
        print(f"  {name:<22} {cols}")

    mc = _minicheck_probe()
    print()
    print(f"MiniCheck: {mc['status']}")
    print(f"  HF cache {mc['hf_hub']} holds: {', '.join(mc['all_cached_models']) or '(nothing)'}")

    verdict = (
        f"HHEM separates the moat's ruled checks from its unverifiable ones with AUC {auc:.3f}; "
        f"agreement at tau={tau} is supported {agree['supported'].get('agreement', 0):.1%} "
        f"(n={agree['supported'].get('n', 0)}), refuted "
        f"{agree['refuted'].get('agreement', 0):.1%} (n={agree['refuted'].get('n', 0)}), "
        f"unverifiable {agree['unverifiable'].get('agreement', 0):.1%} "
        f"(n={agree['unverifiable'].get('n', 0)})")
    print()
    print(f"VERDICT: {verdict}")

    return {
        "title": "HHEM agreement with moat verdicts per class (E14 ladder, first rung)",
        "programme_ref": DOC_REF,
        "corpus_fingerprint": corpus_fingerprint(),
        "instrument": {"model": meta.get("model"), **meta.get("sidecar", {}),
                       "sidecar_run": meta.get("sidecar_run")},
        "population": (f"every check with a rationale and >=1 stored passage across "
                       f"{CLASSES}: {eligible} eligible"
                       + (" (current moat only)" if opts.current_moat else "")
                       + f"; sampled {len(sample)} by: {rule}"),
        "register_claimed_ruled_checks": 2458,
        "eligible_checks": eligible,
        "sample_size": len(sample),
        "scored": len(per),
        "selection_rule": rule,
        "premise_source_counts": dict(premise_source),
        "tau_calibrated": tau,
        "tau_basis": "95th percentile of the NULL control (a different candidate's passage)",
        "agreement_mapping": {
            "supported": "agree iff HHEM >= tau", "refuted": "agree iff HHEM >= tau",
            "unverifiable": "agree iff HHEM < tau"},
        "agreement_by_class": agree,
        "agreement_overall": {"n": total_n, "agree": total_agree,
                              "share": round(total_agree / total_n, 4) if total_n else 0.0,
                              "wilson95": [round(tlo, 4), round(thi, 4)]},
        "auc_ruled_vs_unverifiable": round(auc, 4),
        "by_check_medians": {
            name: {c: {"n": len(by_check[name][c]),
                       "median": round(quantile(sorted(by_check[name][c]), 0.5), 4)}
                   for c in CLASSES if by_check[name][c]}
            for name in by_check},
        "minicheck": mc,
        "per_check_scores": per,
        "verdict": verdict,
        "headline": {
            "eligible checks (all 3 verdict classes, >=1 stored passage)": eligible,
            "sampled and scored": len(per),
            "register's ruled-check count (claimed) vs measured eligible": (
                f"2,458 claimed; measured eligible here {eligible}"),
            "calibrated tau": tau,
            "AUC ruled vs unverifiable (threshold-free)": round(auc, 4),
            "agreement — supported": (
                f"{agree['supported'].get('agree', 0)}/{agree['supported'].get('n', 0)} = "
                f"{agree['supported'].get('agreement', 0):.1%}"),
            "agreement — refuted": (
                f"{agree['refuted'].get('agree', 0)}/{agree['refuted'].get('n', 0)} = "
                f"{agree['refuted'].get('agreement', 0):.1%}"),
            "agreement — unverifiable": (
                f"{agree['unverifiable'].get('agree', 0)}/{agree['unverifiable'].get('n', 0)} = "
                f"{agree['unverifiable'].get('agreement', 0):.1%}"),
            "MiniCheck": mc["status"],
        },
        "limitations": [
            "The dossier store is live and tau is calibrated per run, so a re-run with a "
            "different `corpus_fingerprint` is a fresh sample, not a repeat. E15 measured that "
            "sensitivity directly: two runs 40 min apart moved tau 0.0589 -> 0.0691 and its "
            "headline rate 43.4% -> 48.9% on the same eligible population.",
            "Agreement depends on the number->label mapping stated in the module docstring. The "
            "AUC is published because it is threshold-free and mapping-free, and it is the number "
            "to quote if only one is quoted.",
            "`refuted` rationales are negations and entailment models score negation lower. The "
            "supported/refuted split is never collapsed into one 'ruled' number without it.",
            "`unverifiable` checks rarely cite anything, so their premise is the passages the "
            "check RETRIEVED. premise_source_counts reports how many checks used which. A "
            "retrieved-passage premise is a weaker premise than a cited one by construction.",
            "Agreement is not accuracy. Neither HHEM nor the moat is ground truth here; no human "
            "has labelled any pair. This measures concordance between two instruments.",
            "MiniCheck was not run and not downloaded — see the `minicheck` probe for what is "
            "actually in the local HF cache.",
        ],
        "_receipt_suffix": ("_current_moat" if opts.current_moat else "") + ("_full" if opts.all else ""),
    }


def main() -> int:
    from runner import run_one
    result = run_one(NAME, sys.argv[1:])
    print(f"\nreceipts   -> {result['receipts_path']}")
    print(f"doc append -> {result['doc_append_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

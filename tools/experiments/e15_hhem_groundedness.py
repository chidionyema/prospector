#!/usr/bin/env python3
"""E15 — HHEM groundedness audit of the live catalogue, and the rationale-infidelity rate.

Programme doc §14 (line ~504): "E15 (FREE, first): run HHEM over the existing dossiers'
claim-citation pairs vs their cached passages = a zero-token groundedness audit of the entire live
catalogue; also yields the measured rationale-infidelity rate (§11 gap 2)."

THE GAP THIS CLOSES. Source-or-die guarantees a ruled check carries a citation. Nothing has ever
checked that the RATIONALE the moat wrote is what the cited passage actually says. Q4c already
showed the gate is ruling-level while source-or-die is claim-level; this is the same seam one
layer down, and it is measurable for free because both halves — the rationale and the passage —
are already on disk.

INSTRUMENT. `vectara/hallucination_evaluation_model` (HHEM-2.1-Open), a 184M cross-encoder that
returns P(hypothesis is factually consistent with premise). It runs in a python3.12 sidecar
because the project venv is CPython 3.14 on macOS x86_64, where no torch wheel exists — see
`_hhem_sidecar.py`. Zero tokens, zero paid calls, zero network (HF_HUB_OFFLINE=1, model already
in the local HF cache).

PAIRING, CONTROLS AND THRESHOLD — see `_groundedness.py`. In short: premise = each cited passage
scored separately, max taken (concatenation would truncate at 512 tokens and manufacture the
finding); hypothesis = the check's `rationale`; two controls, NULL (a different candidate's
passage) and UNCITED (a passage this check retrieved but did not cite).

The decision threshold is NOT picked by eye. It is the 95th percentile of the NULL control's score
distribution, so by construction at most 5% of genuinely unrelated pairs clear it. Infidelity is
then reported at that calibrated threshold AND across a sweep, because a single threshold is a
choice and a sweep is a fact.

A NUMBER THIS EXPERIMENT REFUSES TO REPORT: it does not claim a rationale is FALSE. HHEM measures
whether the rationale is entailed by the passage cited for it. A true statement the model knew
from pretraining and did not read in the passage scores low here — and scoring low is exactly the
finding, because verdict-from-retrieval-only forbids ruling from prior knowledge.

Usage:
    .venv/bin/python tools/experiments/runner.py run E15 -- --limit 900
    .venv/bin/python tools/experiments/runner.py run E15 -- --all --current-moat
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import RULED, corpus_fingerprint, wilson  # noqa: E402
from _groundedness import (  # noqa: E402
    MAX_PASSAGES,
    MAX_PREMISE_CHARS,
    build_pairs,
    collect_checks,
    maxscore,
    quantile,
    stratified_sample,
)
from _hhem import score_pairs  # noqa: E402

NAME = "E15"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §14 (line ~504)"

DEFAULT_LIMIT = 900
SWEEP = (0.05, 0.10, 0.25, 0.50, 0.75)


def describe() -> str:
    return ("HHEM entailment of every ruled check's rationale against the passage it cited: "
            "the zero-token groundedness audit and the rationale-infidelity rate.")


def _parse(args: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="E15", add_help=False)
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help=f"checks to score (default {DEFAULT_LIMIT}); stratified by verdict")
    p.add_argument("--all", action="store_true", help="score every eligible check")
    p.add_argument("--current-moat", action="store_true",
                   help="restrict to checks ruled by claude_cli/claude")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("-h", "--help", action="help")
    return p.parse_args(args)


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {"n": len(s), "mean": round(statistics.fmean(s), 4),
            "p05": round(quantile(s, 0.05), 4), "p25": round(quantile(s, 0.25), 4),
            "median": round(quantile(s, 0.50), 4), "p75": round(quantile(s, 0.75), 4),
            "p95": round(quantile(s, 0.95), 4)}


def _citation_selectivity() -> dict:
    """Is `citations` a SUBSET of what the check retrieved, or all of it?

    The UNCITED control arm only exists if the moat ever retrieves a passage and
    then declines to cite it. This measures that directly over every dossier on
    disk, so an empty arm is reported as a property of the corpus rather than
    read as a broken experiment.
    """
    from _corpus import iter_dossiers
    with_cit = all_cited = partial = zero_cit = zero_cit_srcs = 0
    for _path, dossier in iter_dossiers():
        for chk in dossier.get("checks") or []:
            srcs = [s for s in (chk.get("sources") or [])
                    if isinstance(s, dict) and (s.get("text") or "").strip()]
            if not srcs:
                continue
            own = {str(s.get("source_id")) for s in srcs}
            cits = {str(c) for c in (chk.get("citations") or [])}
            if cits:
                with_cit += 1
                if own <= cits:
                    all_cited += 1
                else:
                    partial += 1
            else:
                zero_cit += 1
                zero_cit_srcs += len(srcs)
    return {
        "checks_with_at_least_one_citation": with_cit,
        "of_those_every_retrieved_passage_is_cited": all_cited,
        "of_those_some_retrieved_passage_left_uncited": partial,
        "selectivity_pct": round(100.0 * partial / with_cit, 2) if with_cit else None,
        "checks_with_zero_citations_but_passages_present": zero_cit,
        "passages_held_by_those_uncited_checks": zero_cit_srcs,
    }


def run(args: list[str] | None = None) -> dict:
    opts = _parse(list(args or []))

    records = [r for r in collect_checks(verdicts=RULED, moat_only=opts.current_moat)
               if r["cited"]]
    eligible_total = len(records)
    if not records:
        raise RuntimeError("no ruled checks with a resolvable, non-empty cited passage on disk")

    limit = None if opts.all else opts.limit
    sample = stratified_sample(records, "verdict", limit)
    rule = ("every eligible check" if limit is None else
            f"systematic every-k-th within each verdict class, k = class_size/quota, "
            f"quota proportional to the class mix; deterministic, no RNG (limit={limit})")

    fingerprint = corpus_fingerprint()
    selectivity = _citation_selectivity()

    pairs, plan = build_pairs(sample, control=True)
    print(f"E15 HHEM groundedness — {len(sample)} of {eligible_total} eligible ruled checks, "
          f"{len(pairs)} HHEM pairs")
    scores, meta = score_pairs(pairs, use_cache=not opts.no_cache)

    cited_s, uncited_s, null_s = [], [], []
    per_rec = []
    for rec, entry in zip(sample, plan):
        c = maxscore(entry["cited"], scores)
        u = maxscore(entry["uncited"], scores)
        n = maxscore(entry["null"], scores)
        if c is not None:
            cited_s.append(c)
        if u is not None:
            uncited_s.append(u)
        if n is not None:
            null_s.append(n)
        per_rec.append({**{k: rec[k] for k in
                           ("path", "candidate_id", "check_name", "verdict", "confidence",
                            "provider", "n_citations", "n_dangling", "gate_fired")},
                        "hhem_cited": c, "hhem_uncited": u, "hhem_null": n,
                        "rationale": rec["rationale"][:400],
                        "cited_passage": (rec["cited"][0].get("text") or "")[:400],
                        "cited_url": rec["cited"][0].get("url")})

    tau = round(quantile(sorted(null_s), 0.95), 4) if null_s else 0.5
    scored = [r for r in per_rec if r["hhem_cited"] is not None]
    infid = [r for r in scored if r["hhem_cited"] < tau]
    lo, hi = wilson(len(infid), len(scored))

    sweep = {}
    for t in SWEEP:
        bad = sum(1 for r in scored if r["hhem_cited"] < t)
        null_bad = sum(1 for v in null_s if v < t)
        sweep[str(t)] = {
            "infidelity": bad, "infidelity_share": round(bad / len(scored), 4) if scored else 0.0,
            "null_correctly_flagged": null_bad,
            "null_correctly_flagged_share": round(null_bad / len(null_s), 4) if null_s else 0.0,
        }

    by_verdict, by_check = defaultdict(list), defaultdict(list)
    for r in scored:
        by_verdict[r["verdict"]].append(r["hhem_cited"])
        by_check[r["check_name"]].append(r["hhem_cited"])

    def rate(vals: list[float]) -> dict:
        bad = sum(1 for v in vals if v < tau)
        a, b = wilson(bad, len(vals))
        return {"n": len(vals), "infidelity": bad,
                "share": round(bad / len(vals), 4) if vals else 0.0,
                "wilson95": [round(a, 4), round(b, 4)], "median": round(quantile(sorted(vals), 0.5), 4)}

    print()
    print("--- score distributions (HHEM P(rationale consistent with passage)) ---")
    for label, vals in (("CITED  (the evidence the model said it used)", cited_s),
                        ("UNCITED (retrieved by this check, not cited)", uncited_s),
                        ("NULL   (a different candidate's passage)   ", null_s)):
        st = _stats(vals)
        print(f"  {label}  n={st['n']:5d}  median={st.get('median')}  mean={st.get('mean')}  "
              f"p95={st.get('p95')}")
    disc = (statistics.fmean(cited_s) - statistics.fmean(null_s)) if (cited_s and null_s) else 0.0
    print(f"  DISCRIMINATION cited-mean minus null-mean = {disc:+.4f}  "
          f"(<=0 would mean the instrument measures nothing here)")
    sel = selectivity
    print(f"  the UNCITED arm is EMPTY by construction, not by accident: of "
          f"{sel['checks_with_at_least_one_citation']} checks corpus-wide that cite anything, "
          f"{sel['of_those_every_retrieved_passage_is_cited']} "
          f"({100 - (sel['selectivity_pct'] or 0):.2f}%) cite EVERY passage they retrieved; "
          f"{sel['of_those_some_retrieved_passage_left_uncited']} leave any passage uncited.")
    print("  so `cited` here means RETRIEVED-FOR-THIS-CHECK; citation carries no selectivity, "
          "and NULL is the only usable control.")

    print()
    print(f"--- rationale infidelity at the calibrated threshold tau={tau} "
          f"(95th pct of NULL) ---")
    print(f"  {len(infid)} / {len(scored)} = {len(infid)/len(scored):.1%} "
          f"[95% CI {lo:.1%}-{hi:.1%}] of ruled checks state a rationale that HHEM does not find "
          f"entailed by the passage it cited")
    print()
    print("--- threshold sweep (a single tau is a choice; the sweep is a fact) ---")
    for t in SWEEP:
        row = sweep[str(t)]
        print(f"  tau={t:<5} infidelity {row['infidelity']:5d}/{len(scored)} = "
              f"{row['infidelity_share']:6.1%}   null correctly flagged "
              f"{row['null_correctly_flagged_share']:6.1%}")
    print()
    print("--- by verdict class ---")
    for v in sorted(by_verdict):
        r = rate(by_verdict[v])
        print(f"  {v:<12} n={r['n']:5d}  infidelity {r['share']:6.1%} "
              f"[{r['wilson95'][0]:.1%}-{r['wilson95'][1]:.1%}]  median score {r['median']}")
    print()
    print("--- by check ---")
    for name in sorted(by_check, key=lambda k: -rate(by_check[k])["share"]):
        r = rate(by_check[name])
        print(f"  {name:<22} n={r['n']:5d}  infidelity {r['share']:6.1%}  median {r['median']}")

    worst = sorted(scored, key=lambda r: r["hhem_cited"])[:5]
    print()
    print("--- lowest-scoring examples (rationale vs the passage it cited) ---")
    for r in worst:
        print(f"\n  [{r['hhem_cited']:.4f}] {r['path']} {r['check_name']}/{r['verdict']}")
        print(f"    rationale: {r['rationale'][:260]}")
        print(f"    cited    : {r['cited_url']}")
        print(f"    passage  : {r['cited_passage'][:260]}")

    share = len(infid) / len(scored) if scored else 0.0
    verdict = (f"measured rationale-infidelity rate {share:.1%} "
               f"({len(infid)}/{len(scored)}, 95% CI {lo:.1%}-{hi:.1%}) at tau={tau}, "
               f"calibrated so 95% of unrelated pairs fall below it")

    return {
        "title": "HHEM groundedness audit of the live catalogue + rationale-infidelity rate",
        "programme_ref": DOC_REF,
        "instrument": {"model": meta.get("model"), **meta.get("sidecar", {}),
                       "sidecar_run": meta.get("sidecar_run"),
                       "cache_hits": meta.get("cache_hits")},
        "population": (f"ruled checks (supported|refuted) holding >=1 citation that resolves to a "
                       f"stored passage with text: {eligible_total} eligible"
                       + (" (current moat only)" if opts.current_moat else "")
                       + f"; sampled {len(sample)} by: {rule}"),
        "eligible_checks": eligible_total,
        "sample_size": len(sample),
        "selection_rule": rule,
        "hhem_pairs_scored": len(pairs),
        "max_passages_per_check": MAX_PASSAGES,
        "max_premise_chars": MAX_PREMISE_CHARS,
        "tau_calibrated": tau,
        "tau_basis": "95th percentile of the NULL control (a different candidate's passage)",
        "distributions": {"cited": _stats(cited_s), "uncited": _stats(uncited_s),
                          "null": _stats(null_s)},
        "corpus_fingerprint": fingerprint,
        "citation_selectivity": selectivity,
        "discrimination_cited_minus_null_mean": round(disc, 4),
        "infidelity": {"n_scored": len(scored), "n_infidelity": len(infid),
                       "share": round(share, 4), "wilson95": [round(lo, 4), round(hi, 4)]},
        "threshold_sweep": sweep,
        "by_verdict": {v: rate(by_verdict[v]) for v in by_verdict},
        "by_check": {k: rate(by_check[k]) for k in by_check},
        "worst_examples": worst,
        "per_check_scores": per_rec,
        "verdict": verdict,
        "headline": {
            "eligible ruled checks with a resolvable cited passage": eligible_total,
            "sampled and scored": len(scored),
            "HHEM pairs (cited + uncited + null controls)": len(pairs),
            "calibrated threshold tau (95th pct of NULL control)": tau,
            "median HHEM score, CITED passage": _stats(cited_s).get("median"),
            "median HHEM score, NULL control": _stats(null_s).get("median"),
            "rationale-infidelity rate": (
                f"{len(infid)}/{len(scored)} = {share:.1%} (95% CI {lo:.1%}-{hi:.1%})"),
        },
        "limitations": [
            "tau is calibrated PER RUN on that run's own NULL sample, and the dossier store is "
            "live, so the headline rate is stable to about +/-5pp, not to the decimal. Measured "
            "directly 2026-08-07: two runs 40 min apart over the same 2649-eligible population "
            "drew different 350-check samples (16 dossiers were rewritten in between) and gave "
            "tau 0.0589 -> 43.4% and tau 0.0691 -> 48.9%. Both runs agree the rate is near half; "
            "neither pins it finer. `corpus_fingerprint` in these receipts is what distinguishes "
            "a genuine repeat from a fresh sample. Discrimination was stable across both "
            "(+0.1230, +0.1253).",
            "The UNCITED control arm is EMPTY and cannot be filled from this corpus: of "
            f"{selectivity['checks_with_at_least_one_citation']} checks that cite anything, "
            f"{selectivity['of_those_every_retrieved_passage_is_cited']} cite EVERY passage they "
            "retrieved and 0 leave one out. `cited` therefore means "
            "RETRIEVED-FOR-THIS-CHECK; this experiment cannot test whether the model picked the "
            "RIGHT passage, only whether the passages it had entail what it wrote.",
            "HHEM measures ENTAILMENT of the rationale by the cited passage, not truth. A true "
            "statement recalled from pretraining rather than read in the passage scores low — "
            "which is the intended finding under verdict-from-retrieval-only, not a false "
            "positive.",
            "`refuted` rationales contain negation, which entailment models handle worse than "
            "affirmations. The by-verdict breakdown is published so that confound is visible "
            "rather than averaged away; E17 tests it directly.",
            f"Premise = each cited passage separately (max taken), capped at {MAX_PREMISE_CHARS} "
            f"chars and {MAX_PASSAGES} passages. Longer evidence is truncated by HHEM's 512-token "
            "window; concatenating instead would truncate MORE and bias the rate upward.",
            "tau is calibrated on the NULL control, not on human labels. No human has labelled "
            "any pair here, so the absolute rate is only as good as that calibration; the sweep "
            "is published so a different tau can be read off directly.",
            "store/dossiers is written by the live daemon; _meta.run_at_utc pins the corpus.",
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

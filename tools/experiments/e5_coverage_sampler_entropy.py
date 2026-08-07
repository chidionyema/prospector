"""E5 — does the V2 coverage sampler lift axis entropy, and can 3 batches vs 3 ever show it?

Registered at COMMERCIAL_READINESS_PROGRAM.md §4: "Coverage sampler lifts sector/persona
entropy without PASS-rate loss · V2 on for 3 batches vs 3 control · distribution entropy;
PASS rate".

SETUP ONLY (founder decision, §29). Nothing here generates, and nothing here flips the live
switch: `coverage_sampler.enabled` stays as it is on disk. What this establishes is whether
E5's live half is worth scheduling, by answering the two questions that decide it BEFORE any
batch is spent.

Q1. DOES THE TREATMENT ARM ENGAGE? `plan_cells` (`coverage.py:390`) is deliberately built to
    never break generation: it returns `[]` when the sampler is disabled, when the dossier
    index is missing, when every axis is suppressed by `min_coverage`, when `select_cells`
    raises, and when the config fails validation — five paths, four of them logging a warning
    and continuing. That is correct for production and lethal for an experiment: three
    "treatment" batches would run with the sampler inert, and the result would read "no
    entropy lift" when it means "the sampler never spoke". This is the same trap E1 carries a
    fence for (§18.3), and E5 is more exposed to it than E1 because the silence is by design.
    So the treatment is constructed here, offline, against the real index, and either produces
    cells or names which of the five paths fired.

Q2. CAN 3 BATCHES SEE IT? Entropy computed over a handful of candidates is a noisy statistic:
    a batch of 5 drawn from an unchanged distribution lands on a different entropy every time.
    If that batch-to-batch noise is wider than the lift the sampler could produce, then 3 vs 3
    cannot conclude anything and the design needs more batches, not a run. §4 specifies the
    arms without ever stating this, so it is stated here — by resampling the observed
    distribution, not by assuming one.

Read-only. Zero LLM, zero network, zero spend. The live flag is never written.
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

NAME = "E5"
DOC_REF = "COMMERCIAL_READINESS_PROGRAM.md §4 (experiment table)"


def describe() -> str:
    return ("E5 setup: prove the coverage sampler engages, and size the batch count its "
            "entropy lift would need (offline, zero spend, never flips the flag)")


def _shannon(counts: dict[str, int]) -> float:
    n = sum(counts.values())
    if n <= 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in counts.values() if c > 0)


def _normalised(counts: dict[str, int], domain_size: int) -> float | None:
    """H / Hmax. Without this, axes of different cardinality are not comparable and 'lift'
    has no scale — 1.8 bits is near-saturated on a 4-value axis and poor on a 13-value one."""
    if domain_size < 2:
        return None
    return round(_shannon(counts) / math.log2(domain_size), 4)


def _batch_entropy_noise(counts: dict[str, int], batch: int, domain_size: int,
                         trials: int, rng: random.Random) -> dict[str, Any]:
    """Resample batches of `batch` from the OBSERVED distribution and report the spread.

    This is the noise floor a real lift has to clear. It is measured, not assumed, because
    the answer depends entirely on how skewed the current distribution already is.
    """
    pop = [v for v, c in counts.items() for _ in range(c)]
    if len(pop) < batch or domain_size < 2:
        return {"trials": 0, "note": "not enough observed rows to resample"}
    hs = []
    for _ in range(trials):
        draw = collections.Counter(rng.choices(pop, k=batch))
        hs.append(_shannon(dict(draw)) / math.log2(domain_size))
    hs.sort()
    return {"trials": trials, "batch": batch,
            "mean": round(statistics.fmean(hs), 4),
            "sd": round(statistics.pstdev(hs), 4),
            "p05": round(hs[int(0.05 * len(hs))], 4),
            "p95": round(hs[int(0.95 * len(hs))], 4)}


def _batches_for(sd: float, target_mde: float) -> int | None:
    """Batches per arm to reach `target_mde`. The inverse of `_min_detectable`.

    "Underpowered" without this is a complaint; with it, it is a schedule.
    """
    if sd <= 0 or target_mde <= 0:
        return None
    return math.ceil(2 * ((1.959964 + 0.841621) * sd / target_mde) ** 2)


def _min_detectable(sd: float, n_batches: int) -> float | None:
    """Smallest normalised-entropy lift 3-vs-3 could separate at 95%/80%, two-sided.

    Two independent means of `n_batches` batches each: MDE = (z_a + z_b) * sd * sqrt(2/n).
    """
    if sd <= 0 or n_batches < 1:
        return None
    return round((1.959964 + 0.841621) * sd * math.sqrt(2 / n_batches), 4)


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="runner.py run E5")
    ap.add_argument("--batches", type=int, default=3,
                    help="batches per arm as specified in §4 (default 3)")
    ap.add_argument("--target-mde", type=float, default=0.10,
                    help="normalised-entropy lift E5 should be able to detect (default 0.10)")
    ap.add_argument("--trials", type=int, default=4000,
                    help="resamples for the noise floor (default 4000)")
    ap.add_argument("--k", type=int, default=None,
                    help="candidates per batch; defaults to config schedule.batch_size")
    ns = ap.parse_args(args)

    from prospector.config import load_config
    from prospector.coverage import (
        SamplerConfig,
        db_path_for,
        measure,
        plan_cells,
        select_cells,
    )

    cfg = load_config()
    raw = dict(getattr(cfg, "coverage_sampler", {}) or {})
    gen = getattr(cfg, "generation", {}) or {}
    forms = list(gen.get("structural_forms") or [])
    auds = list(gen.get("audience_forms") or [])
    sched = getattr(cfg, "schedule", {}) or {}
    k = ns.k or int(sched.get("batch_size") or 5)
    domains = {"structural_form": forms, "audience": auds}

    print(f"E5 coverage-sampler setup — enabled_on_disk={raw.get('enabled')!r} "
          f"method={raw.get('method')!r} axes={raw.get('axes')} k={k}")
    print(f"  domains: structural_form={len(forms)} values, audience={len(auds)} values")

    db = db_path_for(cfg)
    db_ok = db is not None and Path(db).exists()
    print(f"  dossier index: {db} — {'present' if db_ok else 'MISSING'}")

    # ---- Q1: does the treatment engage? ------------------------------------------------
    treat_cfg = copy.copy(cfg)
    treat_cfg.coverage_sampler = {**raw, "enabled": True}
    engaged: list[dict[str, str]] = []
    engage_fail = None
    try:
        engaged = plan_cells(treat_cfg, k, domains=domains)
    except Exception as e:  # noqa: BLE001 — plan_cells swallows, but be explicit if it ever stops
        engage_fail = f"{type(e).__name__}: {e}"

    control = plan_cells(cfg, k, domains=domains)   # the arm that runs today
    print()
    print(f"  CONTROL arm (flag as on disk): {len(control)} cell(s) "
          f"— {'rotation, as expected' if not control else 'SAMPLER IS ALREADY STEERING'}")
    if engaged:
        print(f"  TREATMENT arm ENGAGES: {len(engaged)} cell(s), e.g. {engaged[:2]}")
    else:
        # Name which of the five silent paths fired, instead of reporting an inert arm as
        # "no effect" three batches later.
        why = engage_fail or "plan_cells returned [] with the flag ON"
        detail = {"db_present": db_ok}
        if db_ok:
            try:
                scfg = SamplerConfig.from_mapping({**raw, "enabled": True})
                rep = measure(db, scfg)
                detail["rows"] = rep.rows
                detail["suppressed"] = dict(rep.suppressed)
                detail["axis_coverage"] = {a: round(c.coverage, 3) for a, c in rep.axes.items()}
                detail["select_cells"] = len(select_cells(rep, scfg, k, domains=domains))
            except Exception as e:  # noqa: BLE001
                detail["measure_error"] = f"{type(e).__name__}: {e}"
        print(f"  TREATMENT ARM IS INERT — {why}")
        print(f"    diagnosis: {json.dumps(detail, default=str)}")

    # ---- Q2: entropy now, and the noise a lift must clear -------------------------------
    axes_out: dict[str, Any] = {}
    noise_out: dict[str, Any] = {}
    rep_dict: dict[str, Any] = {}
    if db_ok:
        scfg = SamplerConfig.from_mapping({**raw, "enabled": True})
        rep = measure(db, scfg)
        rep_dict = rep.to_dict()
        rng = random.Random(int(raw.get("seed") or 0))
        print()
        print(f"  entropy over {rep.rows} indexed rows "
              f"(recent_window={raw.get('recent_window')})")
        print(f"  {'axis':<18} {'distinct':>8} {'cover':>7} {'H_norm':>7} "
              f"{'batch sd':>9} {'MDE @' + str(ns.batches) + 'v' + str(ns.batches):>9} "
              f"{'batches@' + format(ns.target_mde, '.2f'):>13}")
        for axis, cov in rep.axes.items():
            counts = dict(cov.counts)
            # The domain must cover what was OBSERVED, not just what config declares today.
            # First run printed h_norm=1.365 for structural_form — impossible for a normalised
            # entropy, and the tell that the corpus holds 29 distinct values against a
            # configured vocabulary of 8. Dividing by log2(8) then inflates the statistic
            # instead of exposing the mismatch. The gap is itself a finding, so it is reported.
            configured = len(domains.get(axis) or [])
            dom = max(configured, len(counts), 2)
            hn = _normalised(counts, dom)
            noise = _batch_entropy_noise(counts, k, dom, ns.trials, rng)
            mde = _min_detectable(noise.get("sd", 0.0), ns.batches)
            need = _batches_for(noise.get("sd", 0.0), ns.target_mde)
            axes_out[axis] = {"distinct": cov.distinct, "coverage": round(cov.coverage, 4),
                              "unknown": cov.unknown, "h_norm": hn, "domain_size": dom,
                              "configured_domain": configured,
                              "values_outside_config": sorted(
                                  set(counts) - set(domains.get(axis) or []))[:20]
                              if configured else []}
            noise_out[axis] = {**noise, "mde_normalised": mde,
                               "batches_for_target_mde": need}
            sd_txt = f"{noise['sd']:.3f}" if noise.get("trials") else "n/a"
            hn_txt = f"{hn:.3f}" if hn is not None else "n/a"
            mde_txt = f"{mde:.3f}" if mde else "n/a"
            print(f"  {axis:<18} {cov.distinct:>8} {cov.coverage:>7.1%} "
                  f"{hn_txt:>7} {sd_txt:>9} {mde_txt:>9} "
                  f"{(str(need) if need else 'n/a'):>13}")
        if rep.suppressed:
            print(f"  suppressed axes (below min_coverage={raw.get('min_coverage')}): "
                  f"{dict(rep.suppressed)}")

    # ---- the verdict on the DESIGN, which is what setup owes ----------------------------
    print()
    steerable = [a for a in axes_out if a not in (rep_dict.get("suppressed") or {})]
    worst_mde = max((v["mde_normalised"] or 0) for v in noise_out.values()) if noise_out else None
    need_max = max((v.get("batches_for_target_mde") or 0)
                   for v in noise_out.values()) if noise_out else None
    runnable = bool(engaged) and bool(steerable)
    if not engaged:
        print("  DESIGN VERDICT: NOT RUNNABLE — the treatment arm is inert, so 3 batches would "
              "measure the control against itself. Fix the diagnosis above first.")
    elif worst_mde and worst_mde >= 0.20:
        print(f"  DESIGN VERDICT: UNDERPOWERED at {ns.batches} batches/arm — batch-to-batch "
              f"entropy noise alone spans an MDE of {worst_mde:.3f} normalised bits on the "
              f"worst axis. §4's '{ns.batches} batches vs {ns.batches}' cannot separate a lift "
              f"smaller than that. Detecting {ns.target_mde:.2f} needs {need_max} batches "
              f"PER ARM.")
    else:
        print(f"  DESIGN VERDICT: RUNNABLE at {ns.batches} batches/arm — smallest separable "
              f"lift is {worst_mde} normalised bits on the worst axis.")

    return {
        "headline": {
            "enabled_on_disk": raw.get("enabled"),
            "flag_untouched": True,
            "index_present": db_ok,
            "control_cells": len(control),
            "treatment_engages": bool(engaged),
            "treatment_cells": len(engaged),
            "batches_per_arm": ns.batches,
            "k_per_batch": k,
            "worst_axis_mde_normalised": worst_mde,
            "target_mde": ns.target_mde,
            "batches_per_arm_for_target": need_max,
            "design_runnable": runnable,
        },
        "engagement": {"cells": engaged[:10], "failure": engage_fail,
                       "control_cells": control[:10]},
        "axes": axes_out,
        "batch_noise": noise_out,
        "coverage_report": rep_dict,
        "method": {
            "entropy": "Shannon over each axis's observed counts, normalised by log2(domain "
                       "size) so axes of different cardinality are comparable",
            "noise_floor": f"{ns.trials} resamples of {k} rows from the observed distribution",
            "mde": "(1.96+0.84)*sd*sqrt(2/batches), two independent arm means",
            "engagement": "plan_cells called on a COPY of the config with enabled=True; the "
                          "on-disk flag is never written",
        },
        "corpus_fingerprint": corpus.corpus_fingerprint(),
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1:])["headline"], indent=2))

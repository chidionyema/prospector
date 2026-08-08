"""E2 — is the B2C persona spectrum structurally ungroundable, and how big a batch proves it?

Registered at COMMERCIAL_READINESS_PROGRAM.md §4 (the experiment table) and §8 (the baseline).

WHY THIS FILE EXISTS. §8's baseline was computed by a "script in session log", and the session
log is gone. That is the same failure as a spec living only in a transcript: the number survives
as prose that nobody can re-derive, drifts silently as the corpus grows, and cannot be diffed
against the live arm it is supposed to be the control for. This makes the baseline a command.

WHAT IT ADDS TO §8, beyond re-runnability:

1. INTERVALS. §8 states "persona class moves PASS rate ~9x" from smb_owner 21/242 (9%) against
   public_sector_worker 2/148 (1%). At those counts the honest question is whether the two are
   separable at all, and §8 does not ask it. Every rate here carries a Wilson interval and the
   pairwise verdict is printed, so the 9x either survives or it does not.

2. THE CLASS SPLIT, NAMED. §8 reasons "payer_solvency grounds when the payer is a business" but
   reports per-persona rates only. `PAYER_IS_A_BUSINESS` below makes that hypothesis an explicit
   partition of the vocabulary, so the class contrast is measured directly rather than eyeballed
   off a sorted list.

3. POWER. §8 says the operator/B2B arm "should beat the 1% tail" without saying how much
   evidence that takes. A live arm sized by vibes is how an experiment returns "no effect" that
   means "too small to see". This prints n-per-arm for the observed effect, and therefore the
   number of batches E2's live half actually costs.

4. THE V1 COVERAGE CHECK. The five operator personas were added 2026-08-06 (`886c9d6`). If the
   corpus carries few or no dossiers tagged with them, then the baseline is SILENT about exactly
   the arm E2 wants to run, and saying so is the point of setup.

Read-only over `store/dossiers/*.json`. Zero LLM, zero network, zero spend.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

NAME = "E2"
DOC_REF = "COMMERCIAL_READINESS_PROGRAM.md §4 (table), §8 (baseline)"

# The hypothesis under test, as a partition rather than a hunch: E2 claims grounding follows the
# PAYER, not the topic — a persona who buys out of a business budget leaves a public trail of
# prices, vendors and procurement that `payer_solvency` and `distribution` can actually cite,
# and a household payer does not. Membership is read from config; only the split is declared
# here, because it is a definition of the measurement and not a runtime parameter.
PAYER_IS_A_BUSINESS = frozenset({
    "smb_owner",            # the sole business payer in the original 8 — §8's top of the table
    "startup_operator", "software_developer", "agency_owner", "ops_manager", "ecommerce_seller",
})
# Added 2026-08-06 by 886c9d6; the baseline predates them by construction.
V1_OPERATOR_PERSONAS = frozenset(PAYER_IS_A_BUSINESS - {"smb_owner"})

# The two checks §8 measured as starved 5:1 and 2.5:1. E1 targets the same pair.
STARVED_CHECKS = ("payer_solvency", "distribution")


def describe() -> str:
    return ("E2 baseline: PASS rate and grounding by audience persona, with intervals and the "
            "batch size the live arm needs (offline, zero spend)")


def _audience(d: dict) -> str:
    tags = (d.get("candidate") or {}).get("tags") or {}
    a = tags.get("audience")
    return a.strip() if isinstance(a, str) and a.strip() else ""


def _config_personas() -> list[str]:
    """The vocabulary, from config. `cfg.generation` is a plain DICT, not an object.

    The first draft used `getattr(gen, "audience_forms", None)` and got None, so the harness
    reported "audience_forms in config: 0" and flagged all twelve observed personas
    "(not in config)" — a reader bug rendering as a data finding, which is the same class of
    defect as an empty denominator printing as a null result. An empty vocabulary is now an
    explicit failure, because there is no corpus in which zero is the right answer.
    """
    from prospector.config import load_config
    gen = getattr(load_config(), "generation", None) or {}
    forms = gen.get("audience_forms") if isinstance(gen, dict) else \
        getattr(gen, "audience_forms", None)
    if not forms:
        raise SystemExit(
            "REFUSING: config generation.audience_forms is empty or unreadable, so every "
            "persona would be reported as 'not in config'. The config shape moved; fix the "
            "reader rather than publishing a table of false flags.")
    return list(forms)


def _wilson_row(k: int, n: int) -> dict[str, Any]:
    lo, hi = corpus.wilson(k, n) if n else (0.0, 0.0)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "lo": round(lo, 4), "hi": round(hi, 4)}


def _separable(a: dict, b: dict) -> bool:
    """Non-overlapping 95% Wilson intervals. Conservative, and deliberately so."""
    if not a["n"] or not b["n"]:
        return False
    return a["hi"] < b["lo"] or b["hi"] < a["lo"]


def _n_per_arm(p1: float, p2: float, power: float = 0.80) -> int | None:
    """Two-proportion sample size per arm, 95% two-sided.

    The number §8 never states. Without it the live arm cannot be scheduled, only hoped for.
    """
    if p1 == p2 or not (0 < p1 < 1) or not (0 < p2 < 1):
        return None
    z_a, z_b = 1.959964, {0.80: 0.841621, 0.90: 1.281552}.get(power, 0.841621)
    pbar = (p1 + p2) / 2
    num = (z_a * math.sqrt(2 * pbar * (1 - pbar))
           + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p1 - p2) ** 2)


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="runner.py run E2")
    ap.add_argument("--min-n", type=int, default=30,
                    help="personas with fewer dossiers than this are reported but excluded "
                         "from the separability verdict (default 30)")
    ap.add_argument("--power", type=float, default=0.80, choices=[0.80, 0.90],
                    help="power for the batch-size calculation (default 0.80)")
    ns = ap.parse_args(args)

    vocab = _config_personas()
    per: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"pass": 0, "kill": 0, "defer": 0, "moat_ungrounded": 0,
                 "checks": collections.defaultdict(collections.Counter)})
    untagged = collections.Counter()
    total = 0

    for _path, d in corpus.iter_dossiers():
        total += 1
        decision = (d.get("decision") or "").lower()
        aud = _audience(d)
        if not aud:
            untagged[decision or "(none)"] += 1
            continue
        row = per[aud]
        if decision in ("pass", "kill", "defer"):
            row[decision] += 1
        if decision == "kill" and d.get("gate_fired") == "moat_ungrounded":
            row["moat_ungrounded"] += 1
        for chk in d.get("checks") or []:
            name = chk.get("check_name")
            if name in STARVED_CHECKS:
                row["checks"][name][(chk.get("verdict") or "").lower()] += 1

    tagged = sum(r["pass"] + r["kill"] + r["defer"] for r in per.values())
    print(f"E2 persona baseline — {total} dossiers, {tagged} with a decision AND an audience tag")
    print(f"  audience_forms in config: {len(vocab)}; seen in corpus: {len(per)}")
    if untagged:
        print(f"  untagged: {dict(untagged)} (selection-bias guard: "
              f"{round(100 * sum(untagged.values()) / total, 1)}% of the corpus)")

    # ---- per-persona table -------------------------------------------------------------
    rows = []
    for aud, r in per.items():
        n = r["pass"] + r["kill"] + r["defer"]
        rows.append({
            "audience": aud, "in_config": aud in vocab,
            "payer_class": "business" if aud in PAYER_IS_A_BUSINESS else "household",
            "v1_operator": aud in V1_OPERATOR_PERSONAS,
            "n": n, "pass": r["pass"], "kill": r["kill"], "defer": r["defer"],
            "pass_rate": _wilson_row(r["pass"], n),
            "moat_ungrounded_kills": r["moat_ungrounded"],
            "starved_checks": {c: dict(r["checks"][c]) for c in STARVED_CHECKS},
        })
    rows.sort(key=lambda x: (-(x["pass_rate"]["rate"] or 0), -x["n"]))

    print()
    print(f"  {'persona':<22} {'class':<10} {'n':>5} {'pass':>5} {'rate':>7} {'95% CI':>16} "
          f"{'ungrounded':>11}")
    for x in rows:
        p = x["pass_rate"]
        ci = f"[{p['lo']:.1%},{p['hi']:.1%}]" if p["n"] else "n/a"
        rate = f"{p['rate']:.1%}" if p["rate"] is not None else "n/a"
        flag = "" if x["in_config"] else "  (not in config)"
        print(f"  {x['audience']:<22} {x['payer_class']:<10} {x['n']:>5} {x['pass']:>5} "
              f"{rate:>7} {ci:>16} {x['moat_ungrounded_kills']:>11}{flag}")

    # ---- the 9x claim, tested ----------------------------------------------------------
    eligible = [x for x in rows if x["n"] >= ns.min_n]
    verdict: dict[str, Any] = {"tested": False}
    if len(eligible) >= 2:
        best, worst = eligible[0], eligible[-1]
        sep = _separable(best["pass_rate"], worst["pass_rate"])
        ratio = (None if not worst["pass_rate"]["rate"]
                 else round((best["pass_rate"]["rate"] or 0) / worst["pass_rate"]["rate"], 2))
        verdict = {"tested": True, "best": best["audience"], "worst": worst["audience"],
                   "ratio": ratio, "separable": sep,
                   "best_ci": [best["pass_rate"]["lo"], best["pass_rate"]["hi"]],
                   "worst_ci": [worst["pass_rate"]["lo"], worst["pass_rate"]["hi"]]}
        print()
        print(f"  spread: {best['audience']} {best['pass']}/{best['n']} vs "
              f"{worst['audience']} {worst['pass']}/{worst['n']} = "
              f"{ratio if ratio is not None else 'n/a'}x — intervals "
              f"{'DO NOT overlap (separable)' if sep else 'OVERLAP (not separable)'}")

    # ---- the class contrast, which is what E2 actually claims ---------------------------
    cls: dict[str, dict[str, int]] = {c: {"pass": 0, "n": 0, "ungrounded": 0, "kill": 0}
                                      for c in ("business", "household")}
    starved: dict[str, collections.Counter] = {c: collections.Counter()
                                               for c in ("business", "household")}
    for x in rows:
        c = x["payer_class"]
        cls[c]["pass"] += x["pass"]
        cls[c]["n"] += x["n"]
        cls[c]["kill"] += x["kill"]
        cls[c]["ungrounded"] += x["moat_ungrounded_kills"]
        for chk in STARVED_CHECKS:
            starved[c].update(x["starved_checks"][chk])
    class_rates = {c: _wilson_row(v["pass"], v["n"]) for c, v in cls.items()}
    class_sep = _separable(class_rates["business"], class_rates["household"])

    print()
    for c, r in class_rates.items():
        u = cls[c]
        rate = f"{r['rate']:.1%}" if r["rate"] is not None else "n/a"
        unv = starved[c]["unverifiable"]
        sup = starved[c]["supported"]
        ratio = f"{unv / sup:.1f}:1" if sup else "n/a"
        print(f"  payer={c:<10} pass {u['pass']:>3}/{u['n']:<5} {rate:>6} "
              f"[{r['lo']:.1%},{r['hi']:.1%}]   moat_ungrounded {u['ungrounded']:>3}   "
              f"{'/'.join(STARVED_CHECKS)} unverifiable:supported = {ratio}")
    print(f"  class separable at 95% Wilson: {'YES' if class_sep else 'no'}")

    # ---- what the live arm costs -------------------------------------------------------
    pb, ph = class_rates["business"]["rate"], class_rates["household"]["rate"]
    n_arm = _n_per_arm(pb, ph, ns.power) if (pb and ph) else None
    print()
    if n_arm:
        print(f"  LIVE ARM SIZE: to confirm {pb:.1%} vs {ph:.1%} at 95%/{ns.power:.0%} power "
              f"needs {n_arm} candidates PER ARM ({2 * n_arm} total).")
    else:
        print("  LIVE ARM SIZE: not computable — one class has a zero or undefined rate.")

    v1_n = sum(x["n"] for x in rows if x["v1_operator"])
    print(f"  V1 operator personas ({', '.join(sorted(V1_OPERATOR_PERSONAS))}): "
          f"{v1_n} dossiers in the corpus.")
    if v1_n < ns.min_n:
        print("  => The baseline is SILENT about the arm E2 wants to run. The five operator "
              "personas were added 2026-08-06; the corpus predates them, so smb_owner is the "
              "ONLY business-payer evidence here and the class contrast above rests on it.")

    unseen = sorted(set(vocab) - set(per))
    if unseen:
        print(f"  personas in config with ZERO dossiers: {unseen}")

    return {
        "headline": {
            "dossiers": total, "tagged_with_decision": tagged,
            "personas_seen": len(per), "personas_in_config": len(vocab),
            "spread_verdict": verdict,
            "class_pass_rate": {c: r["rate"] for c, r in class_rates.items()},
            "class_separable": class_sep,
            "live_arm_n_per_arm": n_arm,
            "power": ns.power,
            "v1_operator_dossiers": v1_n,
            "baseline_covers_v1_arm": v1_n >= ns.min_n,
            "personas_with_zero_dossiers": unseen,
        },
        "per_persona": rows,
        "per_class": {c: {**cls[c], "rate": class_rates[c],
                          "starved_checks": dict(starved[c])} for c in cls},
        "untagged": dict(untagged),
        "method": {
            "source": "store/dossiers/*.json, read-only, zero LLM",
            "payer_class": "declared in this module (PAYER_IS_A_BUSINESS); membership from "
                           "config.yaml generation.audience_forms",
            "intervals": "95% Wilson; 'separable' means the two intervals do not overlap",
            "min_n": ns.min_n,
            "caveat": "full history spans several query-gen eras — this is the CONTROL for "
                      "E2's biased batches, not the A/B itself (§8's caveat, still true)",
        },
        "corpus_fingerprint": corpus.corpus_fingerprint(),
    }


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1:])["headline"], indent=2))

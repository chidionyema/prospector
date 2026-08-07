#!/usr/bin/env python3
"""E1 - do entity-template queries ground the checks the LLM arm cannot?

REGISTER: `docs/COMMERCIAL_READINESS_PROGRAM.md` §3 row E1, and §18.3/§18.4 which corrected it.
The register's original arm list was `payer_solvency` + `distribution`; §18.3 replaced
`distribution` (37.5% unverifiable, the fifth-BEST check of ten, so almost no headroom) with
`incumbency` (55.0%) and `legality` (54.8%), next to `payer_solvency` (60.5%, the worst).

WHAT §18.3 SAYS IS BLOCKING, AND WHY THAT IS NO LONGER TRUE. §18.3 records that
`_ENTITY_TEMPLATES` "has exactly two keys" and that extending it "is a code change, and it is
the natural E1 follow-on". Verified on disk 2026-08-07: `prospector/entity_templates.py` now
has FOUR keys - `payer_solvency` (:23), `distribution` (:27), `incumbency` (:35), `legality`
(:39) - landed by `d01ae78`. The doc drifted; the code change already happened. This module is
therefore runnable today, and `--preflight` proves that claim rather than restating it.

THE TRAP THIS MODULE IS BUILT AROUND. §18.3: "`retrieval.hybrid_entity_checks` looks like a
general switch and is not. Listing `incumbency` or `legality` there is INERT - no error, no
log, the arm simply never engages and the experiment reads as 'no effect'." An experiment whose
null result and whose broken result are the same output is not an experiment. So the treatment
arm is FENCED: every check in it must come back stamped `query_source == "entity_template"`
(`verify.py:564`), and a run where it does not ABORTS instead of reporting a delta. Note that
`config._validate_hybrid_entity_checks` (`config.py:275-309`) now rejects a templateless check
at load time too, which closes the same trap from the other side - the fence here is kept
because it checks the OUTCOME (the arm ran) rather than the CONFIG (the arm was requested).

PAIRED, AND PER-CHECK RATHER THAN PER-LANE. Both arms see the SAME candidates, and each
(candidate, check) is run through `verify.run_check` directly rather than through the lane.
`verify()` is kill-fast: it stops at the first hard fail, so a lane-level A/B would evaluate
different check SETS in the two arms whenever an early check disagreed, and the per-check
unverifiable rates would then be computed over different denominators. Running the checks
directly costs the same calls and keeps the denominators identical.

WHAT THE CONTROL ARM IS. `gen_queries_batched` (`verify.py:347`), the same call production uses
(`verify.py:836`), fed to `run_check` as `precomputed_queries` so the control is stamped
`llm_batched` - production's actual query source, not a per-check legacy path that no live run
takes. The comparison is therefore entity-template queries vs the LLM queries the engine really
generates today.

PREFLIGHT IS THE DEFAULT, AND THAT IS DELIBERATE. Memory
`paid-ab-harness-must-be-fixture-tested-first.md`: a previous paid A/B harness billed six live
calls and kept zero rows. `--preflight` (default) spends NOTHING: it loads the candidates,
builds both arms' queries offline, asserts the treatment arm is non-empty for every target
check, and prints the call budget the live run would spend. `--live` is the only way to bill.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

NAME = "E1"
DOC_REF = ("docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E1), §18.3 'What this changes about "
           "E1', §18.4 'A limit on E1's measurement plan'")

# §18.3's revised arm list. `distribution` is deliberately NOT here.
DEFAULT_CHECKS = ("payer_solvency", "incumbency", "legality")
UNVERIFIABLE = "unverifiable"


def describe() -> str:
    return ("E1: paired A/B of entity-template vs LLM query generation on the three worst-"
            "grounded checks, fenced so an arm that never engaged aborts instead of reading "
            "as 'no effect'.")


# ---------------------------------------------------------------------------
# candidate selection
# ---------------------------------------------------------------------------

def _load_candidates(n: int, seed_checks: tuple[str, ...]) -> list[tuple[str, dict]]:
    """Newest dossiers that actually RAN every target check, newest first.

    Selecting on "ran the check" rather than on recency alone matters: a candidate killed
    before `legality` was reached has no control reading for it, and pairing needs both arms to
    have something to compare on the same check.
    """
    paths = corpus.dossier_paths()
    picked: list[tuple[str, dict]] = []
    for path, d in corpus.iter_dossiers(sorted(paths, key=lambda p: Path(p).stat().st_mtime,
                                               reverse=True)):
        checks = {c.get("check_name") for c in (d.get("checks") or [])}
        if not set(seed_checks) <= checks:
            continue
        if not (d.get("candidate") or {}).get("title"):
            continue
        picked.append((path, d))
        if len(picked) >= n:
            break
    return picked


def _candidate_from(d: dict):
    from prospector.models import Candidate
    raw = dict(d.get("candidate") or {})
    fields = {f.name for f in Candidate.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return Candidate(**{k: v for k, v in raw.items() if k in fields})


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------

def _arm_config(checks: tuple[str, ...], hybrid: bool):
    """A Config whose ONLY difference between arms is `retrieval.hybrid_entity_checks`.

    Loaded fresh per arm rather than mutated in place: `Config` objects are shared by reference
    through the engine, and a mutated singleton would silently apply the treatment to the
    control the moment anything cached a reference to it.
    """
    from prospector.config import load_config
    cfg = load_config()
    cfg.retrieval.hybrid_entity_checks = list(checks) if hybrid else []
    return cfg


def _preflight(cands: list[tuple[str, dict]], checks: tuple[str, ...]) -> dict[str, Any]:
    """Prove offline that the treatment arm engages. Zero LLM calls, zero network."""
    from prospector.verify import _entity_queries

    cfg = _arm_config(checks, hybrid=True)
    per_check: dict[str, dict[str, Any]] = {}
    empties: list[str] = []
    for check in checks:
        counts, samples = [], []
        for path, d in cands:
            q = _entity_queries(_candidate_from(d), check,
                                cfg.retrieval.queries_per_check or cfg.retrieval.fast_queries)
            counts.append(len(q))
            if not q:
                empties.append(f"{corpus.candidate_id(path, d)}/{check}")
            elif len(samples) < 2:
                samples.append(q[0])
        per_check[check] = {"n_candidates": len(counts),
                            "queries_min": min(counts) if counts else 0,
                            "queries_median": statistics.median(counts) if counts else 0,
                            "sample_queries": samples}
    return {"per_check": per_check, "empty_arm_cells": empties}


def _run_arm(cands: list[tuple[str, dict]], checks: tuple[str, ...], hybrid: bool,
             verbose: bool) -> list[dict[str, Any]]:
    from prospector.retrieval import build_search
    from prospector.run import _build_operator  # the same builder the engine uses
    from prospector.verify import gen_queries_batched, run_check

    cfg = _arm_config(checks, hybrid=hybrid)
    op = _build_operator(cfg)
    search = build_search(cfg)
    rows: list[dict[str, Any]] = []

    for path, d in cands:
        cand = _candidate_from(d)
        cid = corpus.candidate_id(path, d)
        # The control's queries come from the SAME batched call production makes
        # (verify.py:836). Computed for both arms so the two differ only in which source
        # `run_check` then prefers -- computing it only for the control would make the arms
        # differ by one extra LLM call as well as by the query source.
        try:
            precomputed = gen_queries_batched(op, cand, list(checks), cfg=cfg)
        except Exception as e:  # noqa: BLE001 - a failed batch is a datum, not a crash
            precomputed = {}
            if verbose:
                print(f"    [{cid}] batched query-gen failed: {type(e).__name__}: {e}")
        for check in checks:
            t0 = time.monotonic()
            try:
                res = run_check(op, search, cfg, cand, check, precomputed_queries=precomputed)
                row = {
                    "candidate_id": cid, "check": check,
                    "arm": "entity" if hybrid else "llm",
                    "query_source": res.query_source,
                    "verdict": getattr(res.verdict, "value", str(res.verdict)),
                    "confidence": res.confidence,
                    "n_citations": len(res.citations or []),
                    "n_sources": len(res.sources or []),
                    "retrieval_failed": bool(res.retrieval_failed),
                    "degraded": bool(res.degraded),
                    "provider": res.provider,
                    "queries": list(res.queries or []),
                    "latency_s": round(time.monotonic() - t0, 2),
                    "error": None,
                }
            except Exception as e:  # noqa: BLE001
                row = {"candidate_id": cid, "check": check,
                       "arm": "entity" if hybrid else "llm",
                       "query_source": None, "verdict": None, "confidence": None,
                       "n_citations": 0, "n_sources": 0, "retrieval_failed": True,
                       "degraded": True, "provider": None, "queries": [],
                       "latency_s": round(time.monotonic() - t0, 2),
                       "error": f"{type(e).__name__}: {e}"}
            rows.append(row)
            if verbose:
                print(f"    [{cid}] {check:<16} {row['arm']:<6} "
                      f"src={row['query_source']} verdict={row['verdict']} "
                      f"cites={row['n_citations']} {row['latency_s']}s")
    return rows


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def _rate(rows: list[dict[str, Any]], check: str, arm: str) -> dict[str, Any]:
    """Unverifiable rate on RULED cells only.

    A cell whose retrieval failed is excluded from BOTH numerator and denominator. Counting it
    as unverifiable would let a retrieval outage during one arm's turn masquerade as that arm
    grounding worse, which is precisely the confound a paired design exists to remove.
    """
    cells = [r for r in rows if r["check"] == check and r["arm"] == arm
             and not r["retrieval_failed"] and r["error"] is None]
    n = len(cells)
    unv = sum(1 for r in cells if (r["verdict"] or "").lower() == UNVERIFIABLE)
    lo, hi = corpus.wilson(unv, n) if n else (0.0, 0.0)
    return {"n_ruled": n, "unverifiable": unv,
            "rate": round(unv / n, 4) if n else None,
            "wilson_lo": round(lo, 4), "wilson_hi": round(hi, 4),
            "excluded_retrieval_failed": sum(
                1 for r in rows if r["check"] == check and r["arm"] == arm
                and (r["retrieval_failed"] or r["error"]))}


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="runner.py run E1")
    ap.add_argument("--candidates", type=int, default=8,
                    help="paired candidates per arm (default 8)")
    ap.add_argument("--checks", default=",".join(DEFAULT_CHECKS),
                    help=f"comma-separated check names (default {','.join(DEFAULT_CHECKS)}; "
                         "§18.3 replaced `distribution` with incumbency+legality)")
    ap.add_argument("--live", action="store_true",
                    help="actually run both arms against the moat. WITHOUT this the module "
                         "only preflights, and spends nothing.")
    ap.add_argument("--quiet-daemon-ok", action="store_true",
                    help="run live even with no PAUSE file. The daemon then competes for the "
                         "same machine-wide governor slots and for the moat itself.")
    ap.add_argument("--verbose", action="store_true", help="print every cell as it lands")
    ns = ap.parse_args(args)
    checks = tuple(c.strip() for c in ns.checks.split(",") if c.strip())

    # The doc-drift check, asserted rather than described (see the module docstring).
    from prospector.entity_templates import ENTITY_TEMPLATES
    missing = [c for c in checks if not ENTITY_TEMPLATES.get(c)]
    if missing:
        raise SystemExit(
            f"REFUSING: {missing} have no entry in prospector/entity_templates.py, so the "
            "treatment arm would be INERT for them and the run would report 'no effect' when "
            "it means 'never ran' (§18.3). Add templates first.")

    cands = _load_candidates(ns.candidates, checks)
    if len(cands) < 2:
        raise SystemExit(
            f"REFUSING: only {len(cands)} dossier(s) ran all of {list(checks)}, which is not a "
            "pairing. Widen --checks or wait for the daemon to produce more.")

    print(f"E1 hybrid query arms — checks {list(checks)}, {len(cands)} paired candidates")
    print(f"  entity templates present for: {sorted(set(checks) & set(ENTITY_TEMPLATES))}")

    pre = _preflight(cands, checks)
    for check, info in pre["per_check"].items():
        print(f"  preflight {check:<16} median {info['queries_median']:g} template "
              f"queries/candidate, min {info['queries_min']}")
        for q in info["sample_queries"]:
            print(f"      e.g. {q!r}")
    if pre["empty_arm_cells"]:
        raise SystemExit(
            f"REFUSING: the treatment arm produces NO queries for {len(pre['empty_arm_cells'])} "
            f"cell(s), e.g. {pre['empty_arm_cells'][:3]}. That is §18.3's inert-arm trap: the "
            "run would bill both arms and report a null that means 'never engaged'.")

    budget = len(cands) * len(checks) * 2
    print(f"  live cost if run: {budget} check runs ({budget} verdict calls + "
          f"{len(cands) * 2} batched query-gen calls) plus their searches")

    out: dict[str, Any] = {
        "headline": {
            "mode": "live" if ns.live else "preflight",
            "checks": list(checks),
            "paired_candidates": len(cands),
            "templates_present": sorted(set(checks) & set(ENTITY_TEMPLATES)),
            "arm_engages_offline": True,
            "planned_check_runs": budget,
        },
        "preflight": pre,
        "candidate_ids": [corpus.candidate_id(p, d) for p, d in cands],
        "corpus_fingerprint": corpus.corpus_fingerprint(),
        "method": {
            "design": "paired, per-check via verify.run_check (NOT the kill-fast lane)",
            "control_arm": "gen_queries_batched -> precomputed_queries, stamped llm_batched",
            "treatment_arm": "retrieval.hybrid_entity_checks set, stamped entity_template",
            "liveness_fence": "every treatment cell must be stamped entity_template or the run "
                              "aborts (§18.3 inert-arm trap)",
            "retrieval_failures": "excluded from both numerator and denominator",
        },
    }
    if not ns.live:
        print("  PREFLIGHT ONLY — nothing was billed. Re-run with --live to measure.")
        return out

    from pathlib import Path as _P
    sched = _P(__file__).resolve().parents[2] / "store" / "scheduler"
    if not ((sched / "PAUSE").exists() or (sched / "PAUSE_GENERATION").exists()) \
            and not ns.quiet_daemon_ok:
        raise SystemExit(
            "REFUSING: no store/scheduler/PAUSE file, so the daemon is free to take the moat "
            "and the governor slots mid-run. Create PAUSE, run, and DELETE it afterwards. "
            "Override with --quiet-daemon-ok.")

    print("  arm A (control, llm_batched) …")
    rows = _run_arm(cands, checks, hybrid=False, verbose=ns.verbose)
    print("  arm B (treatment, entity_template) …")
    rows += _run_arm(cands, checks, hybrid=True, verbose=ns.verbose)

    # THE FENCE. Checked before any rate is computed, so a broken arm can never be reported as
    # a null result.
    inert = [f"{r['candidate_id']}/{r['check']}={r['query_source']}"
             for r in rows if r["arm"] == "entity" and r["error"] is None
             and r["query_source"] != "entity_template"]
    if inert:
        return {**out, "headline": {**out["headline"], "aborted": "treatment_arm_inert"},
                "inert_cells": inert, "rows": rows,
                "abort_reason": (
                    f"{len(inert)} treatment cell(s) were not stamped entity_template, e.g. "
                    f"{inert[:3]}. §18.3's trap fired: the arm did not engage, so no delta "
                    "computed. This is NOT a null result.")}

    table = []
    for check in checks:
        ctrl, treat = _rate(rows, check, "llm"), _rate(rows, check, "entity")
        delta = (None if ctrl["rate"] is None or treat["rate"] is None
                 else round(treat["rate"] - ctrl["rate"], 4))
        table.append({"check": check, "control": ctrl, "treatment": treat,
                      "unverifiable_delta": delta,
                      # Overlap of the two Wilson intervals: with n this small the honest
                      # statement is usually "cannot distinguish", and saying so is the point.
                      "intervals_overlap": not (treat["wilson_hi"] < ctrl["wilson_lo"]
                                                or ctrl["wilson_hi"] < treat["wilson_lo"])})

    print()
    print(f"  {'check':<16} {'ctrl_unv':>9} {'treat_unv':>10} {'delta':>8} {'separable':>10}")
    for t in table:
        c, tr = t["control"], t["treatment"]
        d = t["unverifiable_delta"]
        delta_txt = "n/a" if d is None else f"{d:+.0%}"
        print(f"  {t['check']:<16} {c['unverifiable']}/{c['n_ruled']:<7} "
              f"{tr['unverifiable']}/{tr['n_ruled']:<8} {delta_txt:>8} "
              f"{('no' if t['intervals_overlap'] else 'YES'):>10}")

    decided = [t for t in table if not t["intervals_overlap"]]
    print()
    print(f"  separable on {len(decided)} of {len(table)} checks at 95% Wilson; "
          f"E1's kill bar is 'no drop in unverifiable rate'")
    return {**out,
            "headline": {**out["headline"],
                         "separable_checks": [t["check"] for t in decided],
                         "deltas": {t["check"]: t["unverifiable_delta"] for t in table}},
            "table": table, "rows": rows}


def main() -> None:
    print(json.dumps(run(sys.argv[1:])["headline"], indent=2))


if __name__ == "__main__":
    main()

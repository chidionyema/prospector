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
import collections
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
import _corpus as corpus  # noqa: E402  - sibling helper, path set above

from prospector.config import store_root  # noqa: E402

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


def _resolve_live_path(checks: tuple[str, ...]) -> dict[str, str]:
    """Import and CONSTRUCT everything the live arms need, spending nothing.

    Why this runs during preflight. The first live attempt of this harness died on
    `ImportError: cannot import name 'build_search'` — a name I had invented — after printing
    "arm A (control) …", i.e. at the moment it committed to billing. Preflight was green,
    because preflight builds queries offline and never touches the operator or retrieval
    layer, so the two halves of the module had no check that they agreed.

    Constructing both objects is free (no call is issued until `_raw`/`search`), so there is no
    reason for the live path's first proof of existence to be a billed run. This is the same
    principle as `--preflight` itself, applied to the wiring rather than to the arms.
    """
    from prospector.operator import is_provisional_provider, make_operator, moat_primary
    from prospector.retrieval import make_provider
    from prospector.verify import gen_queries_batched, run_check  # noqa: F401 - existence check

    cfg = _arm_config(checks, hybrid=False)

    # E1 measures VERDICTS, so a provisional brain ruling here would not be a weaker result —
    # it would be a different experiment. `is_provisional_provider` stamps anything outside
    # MOAT_PRIMARY as provisional; refuse rather than silently measure that.
    #
    # This fence runs BEFORE the constructors, and the order is load-bearing. Every metered
    # adapter raises in `__init__` on a missing key (`operator.py:167/197/305/412/517`) and
    # `make_operator` (`:1086`) builds EVERY configured tier eagerly. Built first, a chain with
    # an unusable provisional tail therefore failed as `RuntimeError: <X>_API_KEY not set` —
    # a credential complaint about a brain E1 is about to refuse to use anyway, which sends the
    # reader hunting for a key instead of reading the actual refusal. The fence is a statement
    # about configuration, so it must not depend on the environment to be reachable.
    ruling = cfg.operator if isinstance(cfg.operator, list) else [cfg.operator]
    provisional = [r for r in ruling if is_provisional_provider(r)]
    if provisional:
        raise SystemExit(
            f"REFUSING: cfg.operator {ruling} includes provisional provider(s) {provisional}; "
            f"only {sorted(moat_primary())} may rule a verdict, so an E1 delta measured here "
            "would describe the fallback tail, not the moat.")

    op = make_operator(cfg)
    search = make_provider(cfg)
    return {"operator": op.name, "search": search.name if hasattr(search, "name") else
            type(search).__name__, "ruling_providers": ",".join(ruling)}


def _run_arm(cands: list[tuple[str, dict]], checks: tuple[str, ...], hybrid: bool,
             verbose: bool) -> tuple[list[dict[str, Any]], str | None]:
    """Run one arm. Returns (rows, dead_arm_reason).

    `dead_arm_reason` is set when the moat stops answering: two consecutive candidates whose
    every cell came back unruled. Measured 2026-08-08 — run `ba5ah4zyn` ground through all 48
    cells against a live usage wall ("capacity returns 2026-08-08 00:25:47"), every one
    deferring, and then printed a delta table of `0/0`. Nothing was measured and nothing was
    learned; the only thing spent was 48 cells of wall-clock and the operator's attention on a
    table that read like a result. Same rule E3 already carries: an outage is the end of the
    measurement, not a datum.

    Two candidates, not one, because a single candidate whose three checks all fail retrieval is
    a plausible property of that candidate. Six consecutive unruled cells is a property of the
    moat.
    """
    # The names production uses, verified on disk 2026-08-08 rather than recalled: the moat
    # operator is `make_operator(cfg)` (`run.py:576`, `:1126`) and retrieval is
    # `make_provider(cfg)` (`run.py:640`). An earlier draft of this file imported
    # `retrieval.build_search` and `run._build_operator`, neither of which exists at those
    # paths — `_build_operator` lives in `prospector.operator` and takes `(kind, cfg, fast)`.
    # Both were invented, and `--preflight` could not catch them because preflight never
    # touches the retrieval or operator layer. See the note in `main()`.
    from prospector.operator import make_operator
    from prospector.retrieval import make_provider
    from prospector.verify import gen_queries_batched, run_check

    cfg = _arm_config(checks, hybrid=hybrid)
    op = make_operator(cfg)
    search = make_provider(cfg)
    rows: list[dict[str, Any]] = []
    unruled_streak = 0
    dead_arm_after = 2 * len(checks)

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
                    # The two DEFER paths are indistinguishable from `retrieval_failed` alone:
                    # "Retrieval unavailable — all searches failed" (verify.py:621) is a SEARCH
                    # outage, "Verdict call failed; fail-safe." (verify.py:469) is a BRAIN
                    # outage. Recording it is what lets the abort below name the cause instead
                    # of reporting an unattributed hole.
                    "rationale": (res.rationale or "")[:200],
                }
            except Exception as e:  # noqa: BLE001
                row = {"candidate_id": cid, "check": check,
                       "arm": "entity" if hybrid else "llm",
                       "query_source": None, "verdict": None, "confidence": None,
                       "n_citations": 0, "n_sources": 0, "retrieval_failed": True,
                       "degraded": True, "provider": None, "queries": [],
                       "latency_s": round(time.monotonic() - t0, 2),
                       "error": f"{type(e).__name__}: {e}", "rationale": ""}
            row["quiet"] = _quiet_now()
            rows.append(row)
            unruled_streak = 0 if _is_ruled(row) else unruled_streak + 1
            if verbose:
                print(f"    [{cid}] {check:<16} {row['arm']:<6} "
                      f"src={row['query_source']} verdict={row['verdict']} "
                      f"cites={row['n_citations']} {row['latency_s']}s")
        if unruled_streak >= dead_arm_after:
            reason = (f"{unruled_streak} consecutive unruled cells "
                      f"({dead_arm_after // len(checks)} whole candidates) in arm "
                      f"{'entity' if hybrid else 'llm'}: {_why_unruled(rows)}")
            print(f"  ABORTING ARM — {reason}")
            return rows, reason
    return rows, None


def _quiet_now() -> bool:
    """Is the daemon still fenced off, RIGHT NOW?

    The startup check in `run()` proves the fence existed when the run began and nothing more.
    Observed 2026-08-08 during run `bo2mosjog`: the PAUSE file created at 00:25Z was gone by
    00:35Z with the run still in flight and the daemon (pid 66223) live. Nothing in this repo
    deletes PAUSE — `grep -rn PAUSE prospector/ tools/ scripts/` finds no unlink, and the
    control centre only prints "Delete it to resume" (`control_center/pages/_overview.py:112`) —
    so the deleter is outside the process and cannot be prevented from here. It CAN be recorded.

    Recorded, not aborted: a daemon competing for the two governor slots slows the run and can
    push cells into the usage wall, but both arms are billed under the same conditions, so the
    contrast survives. What does not survive is an unqualified cost or latency number. If the
    competition is severe enough to stop the moat answering, the dead-arm abort catches it.
    """
    sched = store_root() / "scheduler"
    return (sched / "PAUSE").exists() or (sched / "PAUSE_GENERATION").exists()


def _mcnemar(rows: list[dict[str, Any]], check: str | None) -> dict[str, Any]:
    """The paired test the design was built for, on the pairs where BOTH arms ruled.

    E1 runs the same candidates through both arms precisely so each candidate is its own control.
    Comparing two independent Wilson intervals discards that pairing, and at n<=8 per arm two such
    intervals overlap almost regardless of the effect — so the unpaired read is a null-result
    generator.

    Measured on run `bo2mosjog` (2026-08-08), the same 48 rows read two ways:
      unpaired Wilson : "separable on 0 of 3 checks"
      paired McNemar  : 19 usable pairs, 9 treatment-worse vs 1 treatment-better,
                        exact two-sided p = 0.0215

    Cells the moat never ruled are excluded from BOTH members of a pair, so the five quota
    failures that fell entirely in the second arm cannot manufacture the result.
    """
    # `check=None` pools every (candidate, check) pair. Pooling is reported because a per-check
    # test on 4-6 discordant pairs can detect almost nothing — but the three checks of one
    # candidate share a retrieved corpus, so the pooled pairs are NOT independent and the pooled
    # p is optimistic. It is a direction-consistency signal, never the verdict.
    by_cand: dict[tuple[str, str], dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    for r in rows:
        if (check is None or r["check"] == check) and _is_ruled(r):
            by_cand[(r["candidate_id"], r["check"])][r["arm"]] = r

    worse = better = concordant = 0
    for arms in by_cand.values():
        ctrl, treat = arms.get("llm"), arms.get("entity")
        if not (ctrl and treat):
            continue
        cu = ctrl["verdict"] == "unverifiable"
        tu = treat["verdict"] == "unverifiable"
        if cu == tu:
            concordant += 1
        elif tu:
            worse += 1
        else:
            better += 1

    disc = worse + better
    # Exact binomial (sign) test, not the chi-square approximation: with disc in the teens the
    # continuity-corrected chi-square is not trustworthy and there is no reason to approximate.
    p = (min(1.0, 2 * sum(math.comb(disc, k) for k in range(min(worse, better) + 1)) / 2 ** disc)
         if disc else None)
    return {"n_pairs": worse + better + concordant, "concordant": concordant,
            "treatment_worse": worse, "treatment_better": better,
            "p_exact": None if p is None else round(p, 4),
            "separable": bool(p is not None and p < 0.05),
            "direction": None if not disc else ("treatment_worse" if worse > better
                                                else "treatment_better" if better > worse else "tie")}


def _quiet_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Did the fence hold for every billed cell? A startup-only check cannot answer this."""
    seen = [bool(r.get("quiet")) for r in rows if "quiet" in r]
    lost = next((i for i, q in enumerate(seen) if not q), None)
    held = bool(seen) and lost is None
    note = ""
    if not held and seen:
        note = (f"the daemon fence (store/scheduler/PAUSE) was GONE from cell {lost + 1} of "
                f"{len(seen)} onward — {sum(1 for q in seen if not q)} of {len(seen)} cells were "
                "billed with the daemon free to compete for the moat and the two governor slots. "
                "The arm contrast still holds (both arms ran under the same conditions); the "
                "latency and cost figures from this run are contaminated and must not be quoted.")
    return {"held": held, "cells_observed": len(seen),
            "cells_unfenced": sum(1 for q in seen if not q),
            "lost_at_cell": None if lost is None else lost + 1, "note": note}


def _is_ruled(row: dict[str, Any]) -> bool:
    """The denominator's definition, in one place. `_rate` must agree with the abort."""
    return row["error"] is None and not row["retrieval_failed"]


def _why_unruled(rows: list[dict[str, Any]]) -> str:
    """Name the dominant cause across the unruled tail, so an abort is attributable."""
    causes = collections.Counter(
        (r["error"] or r.get("rationale") or "unruled, no cause recorded")[:120]
        for r in rows if not _is_ruled(r))
    return "; ".join(f"{n}x {c!r}" for c, n in causes.most_common(2))


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
            "outage_fence": "two whole candidates unruled aborts the arm (arm B is then not "
                            "billed); any check/arm cell with a zero denominator aborts the "
                            "run. An outage is the end of the measurement, not a datum.",
        },
    }
    # Prove the LIVE path exists before claiming preflight is green. Free: construction only.
    wiring = _resolve_live_path(checks)
    print(f"  live path resolves: operator={wiring['operator']} search={wiring['search']} "
          f"ruling={wiring['ruling_providers']}")
    out["headline"]["live_path"] = wiring

    if not ns.live:
        print("  PREFLIGHT ONLY — nothing was billed. Re-run with --live to measure.")
        return out

    sched = store_root() / "scheduler"
    if not ((sched / "PAUSE").exists() or (sched / "PAUSE_GENERATION").exists()) \
            and not ns.quiet_daemon_ok:
        raise SystemExit(
            "REFUSING: no store/scheduler/PAUSE file, so the daemon is free to take the moat "
            "and the governor slots mid-run. Create PAUSE, run, and DELETE it afterwards. "
            "Override with --quiet-daemon-ok.")

    def _outage(rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return {**out, "headline": {**out["headline"], "aborted": "moat_outage",
                                    "separable_checks": None, "deltas": None,
                                    # An abort still reports the fence: "the daemon was
                                    # competing" is a candidate explanation for the outage.
                                    "quiet_fence": _quiet_report(rows)},
                "rows": rows,
                "abort_reason": (
                    f"{reason}. NOT a null result: with an empty denominator there is no rate "
                    "to compare, so E1's kill bar ('no drop in unverifiable rate') was never "
                    "tested. Re-run when the moat answers.")}

    print("  arm A (control, llm_batched) …")
    rows, dead = _run_arm(cands, checks, hybrid=False, verbose=ns.verbose)
    if dead:
        # Arm B is not billed: the moat that just refused arm A rules arm B too.
        return _outage(rows, dead)
    print("  arm B (treatment, entity_template) …")
    rows_b, dead = _run_arm(cands, checks, hybrid=True, verbose=ns.verbose)
    rows += rows_b
    if dead:
        return _outage(rows, dead)

    # THE FENCE. Checked before any rate is computed, so a broken arm can never be reported as
    # a null result.
    # `_is_ruled`, not `error is None`: a cell that DEFERRED (retrieval_failed, no exception)
    # carries no query_source, because it never got as far as searching. Judging it by the
    # stamp reports an outage as a wiring bug — the harness would say "the treatment arm did
    # not engage" when the truth is "the moat did not answer". An unruled cell is evidence
    # about the moat and about nothing else; it falls through to the outage fence below.
    inert = [f"{r['candidate_id']}/{r['check']}={r['query_source']}"
             for r in rows if r["arm"] == "entity" and _is_ruled(r)
             and r["query_source"] != "entity_template"]
    if inert:
        return {**out, "headline": {**out["headline"], "aborted": "treatment_arm_inert"},
                "inert_cells": inert, "rows": rows,
                "abort_reason": (
                    f"{len(inert)} treatment cell(s) were not stamped entity_template, e.g. "
                    f"{inert[:3]}. §18.3's trap fired: the arm did not engage, so no delta "
                    "computed. This is NOT a null result.")}

    # THE SECOND FENCE: an empty denominator. The streak abort above catches a total outage;
    # this catches a scattered one that never lines up six-in-a-row but still leaves a cell
    # with nothing in it. `_rate` returns rate=None for n=0, the delta becomes None, and
    # `intervals_overlap` computes True over two zero-width intervals — so the headline reads
    # "separable on 0 of 3", which is verbatim E1's kill bar. A hole must never render as a
    # finding.
    empty = [f"{check}/{arm}" for check in checks for arm in ("llm", "entity")
             if not [r for r in rows if r["check"] == check and r["arm"] == arm
                     and _is_ruled(r)]]
    if empty:
        return _outage(rows, f"{len(empty)} of {2 * len(checks)} cells ruled nothing "
                             f"({', '.join(empty)}): {_why_unruled(rows)}")

    table = []
    for check in checks:
        ctrl, treat = _rate(rows, check, "llm"), _rate(rows, check, "entity")
        delta = (None if ctrl["rate"] is None or treat["rate"] is None
                 else round(treat["rate"] - ctrl["rate"], 4))
        table.append({"check": check, "control": ctrl, "treatment": treat,
                      "unverifiable_delta": delta,
                      # The design's own test. `intervals_overlap` below is kept as the unpaired
                      # reference, NOT as the verdict — see `_mcnemar`.
                      "paired": _mcnemar(rows, check),
                      # Overlap of the two Wilson intervals: with n this small the honest
                      # statement is usually "cannot distinguish", and saying so is the point.
                      "intervals_overlap": not (treat["wilson_hi"] < ctrl["wilson_lo"]
                                                or ctrl["wilson_hi"] < treat["wilson_lo"])})

    print()
    print(f"  {'check':<16} {'ctrl_unv':>9} {'treat_unv':>10} {'delta':>8} "
          f"{'pairs w/b':>10} {'p_exact':>8} {'separable':>10}")
    for t in table:
        c, tr, pr = t["control"], t["treatment"], t["paired"]
        d = t["unverifiable_delta"]
        delta_txt = "n/a" if d is None else f"{d:+.0%}"
        p_txt = "n/a" if pr["p_exact"] is None else f"{pr['p_exact']:.4f}"
        print(f"  {t['check']:<16} {c['unverifiable']}/{c['n_ruled']:<7} "
              f"{tr['unverifiable']}/{tr['n_ruled']:<8} {delta_txt:>8} "
              f"{pr['treatment_worse']}/{pr['treatment_better']:<9} {p_txt:>8} "
              f"{('YES' if pr['separable'] else 'no'):>10}")

    # The paired test is the verdict; the unpaired Wilson columns above are reference only.
    decided = [t for t in table if t["paired"]["separable"]]
    print()
    print(f"  separable on {len(decided)} of {len(table)} checks by exact paired McNemar "
          f"(p<0.05); E1's kill bar is 'no drop in unverifiable rate'")
    worse = [t["check"] for t in table if t["paired"]["direction"] == "treatment_worse"]
    if worse:
        print(f"  direction: treatment (entity_template) is WORSE on {len(worse)} of "
              f"{len(table)} checks — {', '.join(worse)}")
    pooled = _mcnemar(rows, None)
    print(f"  pooled across checks: {pooled['treatment_worse']} treatment-worse vs "
          f"{pooled['treatment_better']} treatment-better of {pooled['n_pairs']} pairs, "
          f"exact p={pooled['p_exact']} — NOT independent (3 checks share one candidate's "
          f"corpus), so this is a direction signal, not the verdict.")
    quiet = _quiet_report(rows)
    if not quiet["held"]:
        print(f"  NOTE: {quiet['note']}")
    return {**out,
            "headline": {**out["headline"],
                         "separable_checks": [t["check"] for t in decided],
                         "separable_basis": "mcnemar_exact_paired_p<0.05",
                         "paired": {t["check"]: t["paired"] for t in table},
                         "paired_pooled": pooled,
                         "deltas": {t["check"]: t["unverifiable_delta"] for t in table},
                         "quiet_fence": quiet},
            "table": table, "rows": rows}


def main() -> None:
    print(json.dumps(run(sys.argv[1:])["headline"], indent=2))


if __name__ == "__main__":
    main()

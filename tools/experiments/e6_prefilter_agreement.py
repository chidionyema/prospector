#!/usr/bin/env python3
"""E6 — does the local-embedding prescreen prefilter earn its place?

Bar (programme doc §3, row E6): **>=20% of LLM prescreen calls dropped, at no PASS
loss.** Shadow mode logs what the prefilter WOULD have done without acting
(`prescreen_prefilter.record`, :517), so agreement is measurable before anything ships.

This module reads `store/prescreen_shadow/shadow-*.jsonl` and answers three questions,
in increasing order of how much they survive a small sample:

  1. OBSERVED — what did the prefilter actually do on the rows we have?
  2. THRESHOLD SWEEP — at what threshold would it hit 20%, and what does that cost in
     false drops? (`would_drop` is recomputed from the logged `prefilter_score`, so the
     sweep needs no re-run of the pipeline.)
  3. THE CEILING — two of them, and the second one settles E6 outright.

THE ARITHMETIC CEILING, which is the whole answer. The bar has two halves and they
fight each other: ">=20% of calls dropped" AND "no PASS loss". No PASS loss means no
false drops, so every candidate the prefilter drops must be one the LLM would have
rejected anyway. The most calls it can therefore save is exactly the LLM's reject rate
— and that is a measured number, not a modelled one. Over 94 batches and 975 real
prescreen decisions (`store/scheduler/batch_diagnostics.jsonl`, `funnel.prescreen_in`
vs `funnel.prescreened_out`) the LLM prescreen rejects **4.72%**, Wilson 95% CI
[3.56%, 6.24%]. A 20% bar sits above the CI's upper bound by more than 3x.

Nothing about the prefilter can move that. A better embedder, a dense backend, a tuned
threshold, more neighbours, a bigger corpus — all of them change WHICH candidates get
dropped, none of them changes how many candidates exist that are safe to drop. E6 is
unreachable as specified, and it is unreachable for a reason that was knowable from the
funnel counts before the prefilter was written.

Why (3) is decisive. `score()` (:491-513) returns a similarity-weighted **keep-rate**
over the k nearest exemplars, and the exemplars are the LLM's own past decisions. So
`prefilter_score` is an estimate of "how often does the LLM keep things that look like
this", and `would_drop` fires only when that estimate falls below `threshold`. With a
keep-biased LLM prescreen (`run.py:781` — "keep-biased", and it NEVER raises), the
corpus is overwhelmingly keeps, every neighbourhood is overwhelmingly keeps, and the
score sits near 1.0 by construction. The prefilter cannot drop at 20% unless the thing
it is imitating rejects far more than it does.

READ BEFORE TRUSTING A RECEIPT FROM THIS FILE: rows whose `candidate_id` matches a test
fixture are excluded. On 2026-08-07 the entire 80-row corpus was ONE fixture candidate
written by the suite (`tests/behavioural/test_prescreen_preserves_novelty.py:28`)
because `resolve_log_path` fell through to the real `cfg.store_dir` and no conftest
fixture redirected it. Those rows are quarantined beside the log, and `--include-all`
is deliberately NOT offered: there is no legitimate analysis that wants them.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

NAME = "E6"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E6), §22"

# The bar, from the programme doc. Both halves must hold.
CALL_REDUCTION_BAR = 0.20
FALSE_DROPS_ALLOWED = 0  # "at no PASS loss"

# Below this many out-of-sample rows, report but refuse to rule on the OBSERVED number.
MIN_ROWS_TO_RULE = 100

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402

DEFAULT_LOG_DIR = store_root() / "prescreen_shadow"


def describe() -> str:
    return ("E6: prescreen-prefilter agreement vs the LLM. Bar: >=20% call reduction at "
            "no PASS loss. Reads store/prescreen_shadow/, excludes fixture rows.")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _load_rows(log_dir: Path) -> tuple[list[dict], list[str]]:
    """Every shadow row from live logs. QUARANTINE-* files are never read."""
    rows: list[dict] = []
    read: list[str] = []
    for p in sorted(log_dir.glob("shadow-*.jsonl")):
        if p.name.startswith("QUARANTINE"):
            continue
        n = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
                n += 1
            except json.JSONDecodeError:
                continue  # a torn append is a missing row, never a crash
        read.append(f"{p.name}:{n}")
    return rows, read


def _drop_fixture_rows(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Remove rows that are provably test fixtures.

    The tell is not the title, it is the shape: a single candidate_id repeated far more
    than a batch could produce. `batch_size` is 15, so a candidate appearing dozens of
    times is the suite looping, not the daemon.
    """
    counts = Counter(r.get("candidate_id", "") for r in rows)
    suspect = {cid for cid, n in counts.items() if n > 15}
    kept = [r for r in rows if r.get("candidate_id", "") not in suspect]
    return kept, {cid: counts[cid] for cid in suspect}


# --------------------------------------------------------------------------- #
# The three analyses
# --------------------------------------------------------------------------- #

def _observed(rows: list[dict]) -> dict[str, Any]:
    """What the prefilter actually did. Abstentions can never save a call."""
    scored = [r for r in rows if not r.get("abstained")]
    drops = [r for r in scored if r.get("would_drop")]
    false_drops = [r for r in drops if r.get("llm_keep")]
    return {
        "rows_total": len(rows),
        "rows_abstained": len(rows) - len(scored),
        "abstain_reasons": dict(Counter(r.get("abstain_reason", "") for r in rows
                                        if r.get("abstained"))),
        "rows_scored": len(scored),
        "would_drop": len(drops),
        "call_reduction": (len(drops) / len(scored)) if scored else 0.0,
        "false_drops": len(false_drops),
        "agreement": dict(Counter(r.get("agreement", "") for r in rows)),
        "llm_keep_rate": (sum(1 for r in rows if r.get("llm_keep")) / len(rows)) if rows else 0.0,
    }


def _threshold_sweep(rows: list[dict]) -> list[dict[str, Any]]:
    """Recompute would_drop at each candidate threshold from the logged score.

    A sweep is the only honest way to report a thresholded metric: quoting the observed
    rate at one threshold hides that the knob was never the sample.
    """
    scored = [r for r in rows if not r.get("abstained") and r.get("prefilter_score") is not None]
    out = []
    for t in (0.35, 0.50, 0.65, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99, 1.0):
        drops = [r for r in scored if float(r["prefilter_score"]) < t]
        false_drops = [r for r in drops if r.get("llm_keep")]
        out.append({
            "threshold": t,
            "scored": len(scored),
            "would_drop": len(drops),
            "call_reduction": (len(drops) / len(scored)) if scored else 0.0,
            "false_drops": len(false_drops),
            "meets_bar": (len(scored) > 0
                          and (len(drops) / len(scored)) >= CALL_REDUCTION_BAR
                          and len(false_drops) <= FALSE_DROPS_ALLOWED),
        })
    return out


def _ceiling(keep_rate: float, neighbours: int, threshold: float) -> dict[str, Any]:
    """The drop rate available at a given LLM keep base-rate, independent of sample size.

    Model: the k neighbours are drawn from a corpus that is `keep_rate` keeps, and the
    score is the keep fraction among them (the similarity weights are near-equal in
    practice, so an unweighted fraction is the right first-order model — and it is the
    OPTIMISTIC one, since equal weights make extreme scores MORE reachable, not less).
    `would_drop` needs the keep fraction strictly below `threshold`, i.e. at most
    floor(threshold*k - epsilon) of k neighbours being keeps.

    This is a ceiling on E6, not a prediction of it: it assumes neighbours are drawn
    independently of the candidate, which understates clustering. Clustering helps the
    prefilter, so a real corpus could beat this — the point is the ORDER of magnitude.
    """
    max_keeps = math.ceil(threshold * neighbours) - 1
    if max_keeps < 0:
        return {"keep_rate": keep_rate, "neighbours": neighbours, "threshold": threshold,
                "expected_drop_rate": 0.0,
                "note": "threshold too low for any neighbourhood to drop"}
    p = keep_rate
    total = 0.0
    for j in range(0, max_keeps + 1):  # j = number of KEEP neighbours
        total += math.comb(neighbours, j) * (p ** j) * ((1 - p) ** (neighbours - j))
    return {
        "keep_rate": round(p, 4),
        "neighbours": neighbours,
        "threshold": threshold,
        "max_keep_neighbours_that_still_drops": max_keeps,
        "expected_drop_rate": total,
        "shortfall_vs_bar_x": (CALL_REDUCTION_BAR / total) if total > 0 else float("inf"),
    }


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Normal-approximation CIs are wrong at rates this low —
    they can even reach below zero — and the whole claim here is about a small rate."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _historical_prescreen_rates(path: Path) -> dict[str, Any]:
    """The LLM prescreen's real reject rate, from the batch funnel.

    This is the load-bearing measurement in the module. `config.yaml:1029-1031` states
    that no historical prescreen DECISION is persisted, which is true and is why the
    prefilter has to learn from live ticks — but the per-batch COUNTS are persisted, and
    the counts are all the arithmetic ceiling needs.
    """
    if not path.exists():
        return {"available": False, "reason": f"{path} not found"}
    n_in = n_out = batches = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            funnel = (json.loads(line).get("funnel") or {})
        except json.JSONDecodeError:
            continue
        if "prescreen_in" in funnel and "prescreened_out" in funnel:
            n_in += int(funnel["prescreen_in"])
            n_out += int(funnel["prescreened_out"])
            batches += 1
    if n_in <= 0:
        return {"available": False, "reason": "no funnel counts found"}
    reject_rate = n_out / n_in
    lo, hi = _wilson(n_out, n_in)
    return {
        "available": True,
        "batches": batches,
        "prescreen_in": n_in,
        "prescreened_out": n_out,
        "reject_rate": reject_rate,
        "reject_rate_ci95": [lo, hi],
        # The bar can only be met if the reject rate itself clears it.
        "bar_reachable": reject_rate >= CALL_REDUCTION_BAR,
        "bar_reachable_at_ci_upper": hi >= CALL_REDUCTION_BAR,
    }


def _keep_rate_for_bar(neighbours: int, threshold: float) -> float | None:
    """The LLM keep base-rate at which the bar becomes reachable at all. Bisection."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _ceiling(mid, neighbours, threshold)["expected_drop_rate"] >= CALL_REDUCTION_BAR:
            lo = mid
        else:
            hi = mid
    return lo


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def run(args: list[str]) -> dict[str, Any]:
    log_dir = DEFAULT_LOG_DIR
    if args and not args[0].startswith("-"):
        log_dir = Path(args[0])

    raw, files = _load_rows(log_dir)
    rows, excluded = _drop_fixture_rows(raw)

    print(f"log dir      : {log_dir}")
    print(f"files read   : {', '.join(files) if files else '(none)'}")
    print(f"rows raw     : {len(raw)}")
    if excluded:
        print(f"rows EXCLUDED as fixture repeats: {sum(excluded.values())} "
              f"({', '.join(f'{c}x{n}' for c, n in excluded.items())})")
    print(f"rows usable  : {len(rows)}")

    obs = _observed(rows)
    print("\n-- OBSERVED --")
    for k in ("rows_total", "rows_scored", "rows_abstained", "would_drop",
              "false_drops", "call_reduction", "llm_keep_rate"):
        print(f"  {k:18} {obs[k]}")
    print(f"  agreement          {obs['agreement']}")
    print(f"  abstain_reasons    {obs['abstain_reasons']}")

    sweep = _threshold_sweep(rows)
    print("\n-- THRESHOLD SWEEP (would_drop recomputed from the logged score) --")
    print(f"  {'thr':>5} {'scored':>7} {'drops':>6} {'reduction':>10} {'false_drops':>12} {'meets bar':>10}")
    for s in sweep:
        print(f"  {s['threshold']:>5} {s['scored']:>7} {s['would_drop']:>6} "
              f"{s['call_reduction']:>9.1%} {s['false_drops']:>12} {str(s['meets_bar']):>10}")

    # The ceiling uses the observed keep base-rate and the shipped settings.
    neighbours = int(rows[0].get("neighbours_used") or 5) if rows else 5
    neighbours = max(neighbours, 1)
    threshold = float(rows[0].get("threshold", 0.35)) if rows else 0.35
    ceil_shipped = _ceiling(obs["llm_keep_rate"], neighbours, threshold)
    needed_keep_rate = _keep_rate_for_bar(neighbours, threshold)

    print("\n-- CEILING (independent of sample size) --")
    print(f"  LLM keep base-rate observed      : {obs['llm_keep_rate']:.1%}")
    print(f"  neighbours / threshold in force  : {neighbours} / {threshold}")
    print(f"  drop rate this base-rate permits : {ceil_shipped['expected_drop_rate']:.3%}")
    print(f"  bar                              : {CALL_REDUCTION_BAR:.0%}")
    print(f"  short of the bar by              : {ceil_shipped['shortfall_vs_bar_x']:.0f}x")
    print(f"  keep-rate at which bar is reachable: <= {needed_keep_rate:.1%}")

    hist = _historical_prescreen_rates(
        store_root() / "scheduler" / "batch_diagnostics.jsonl")
    print("\n-- ARITHMETIC CEILING (the one that settles it) --")
    if hist.get("available"):
        lo, hi = hist["reject_rate_ci95"]
        print(f"  LLM prescreen decisions measured : {hist['prescreen_in']} "
              f"over {hist['batches']} batches")
        print(f"  rejected by the LLM              : {hist['prescreened_out']} "
              f"= {hist['reject_rate']:.2%}")
        print(f"  Wilson 95% CI                    : [{lo:.2%}, {hi:.2%}]")
        print(f"  MAX call reduction at 0 false drops = the reject rate = {hist['reject_rate']:.2%}")
        print(f"  bar                              : {CALL_REDUCTION_BAR:.0%}")
        print(f"  bar reachable                    : {hist['bar_reachable']}"
              f"   (at CI upper bound: {hist['bar_reachable_at_ci_upper']})")
    else:
        print(f"  UNAVAILABLE: {hist.get('reason')}")

    ruled = len(rows) >= MIN_ROWS_TO_RULE
    meets_at_shipped = (obs["call_reduction"] >= CALL_REDUCTION_BAR
                        and obs["false_drops"] <= FALSE_DROPS_ALLOWED)
    sweep_ok = [s for s in sweep if s["meets_bar"]]

    # The KILL rests on the funnel counts, not on the shadow sample. That distinction is
    # the point: the shadow rows are too few to rule on, and they do not need to be.
    killed_on_arithmetic = bool(hist.get("available") and not hist["bar_reachable_at_ci_upper"])

    verdict = {
        "observed_meets_bar": meets_at_shipped,
        "any_threshold_meets_bar": bool(sweep_ok),
        "sample_large_enough_to_rule_on_observed": ruled,
        "min_rows_to_rule": MIN_ROWS_TO_RULE,
        "killed_on_arithmetic_ceiling": killed_on_arithmetic,
        "decision": ("KILL" if killed_on_arithmetic
                     else ("SHIP" if meets_at_shipped else "UNDECIDED")),
    }
    print("\n-- VERDICT --")
    if not ruled:
        print(f"  OBSERVED rate is not ruled on: {len(rows)} usable rows < {MIN_ROWS_TO_RULE}."
              f" It does not need to be — see below.")
    print(f"  meets bar at shipped threshold  : {meets_at_shipped}")
    print(f"  meets bar at ANY swept threshold: {bool(sweep_ok)}"
          + (f" ({sweep_ok[0]['threshold']})" if sweep_ok else ""))
    if killed_on_arithmetic:
        print("\n  DECISION: KILL E6 as specified.")
        print("  'No PASS loss' makes every saved call a candidate the LLM would have")
        print("  rejected, so the reject rate IS the ceiling on call reduction. It is")
        print(f"  {hist['reject_rate']:.2%} over {hist['prescreen_in']} decisions, and the bar is "
              f"{CALL_REDUCTION_BAR:.0%}.")
        print("  No embedder, threshold or corpus size can change that — they change")
        print("  WHICH calls are dropped, not how many are safe to drop.")

    return {
        "headline": {
            "decision": verdict["decision"],
            "llm_reject_rate": round(hist.get("reject_rate", 0.0), 4),
            "llm_decisions_measured": hist.get("prescreen_in", 0),
            "max_call_reduction_at_zero_false_drops": round(hist.get("reject_rate", 0.0), 4),
            "bar": CALL_REDUCTION_BAR,
            "bar_reachable_at_ci_upper": hist.get("bar_reachable_at_ci_upper"),
            "usable_shadow_rows": len(rows),
            "fixture_rows_excluded": sum(excluded.values()),
            "observed_call_reduction": round(obs["call_reduction"], 4),
            "observed_false_drops": obs["false_drops"],
        },
        "observed": obs,
        "threshold_sweep": sweep,
        "ceiling_neighbourhood_model": ceil_shipped,
        "ceiling_arithmetic": hist,
        "keep_rate_at_which_neighbourhood_bar_is_reachable": needed_keep_rate,
        "verdict": verdict,
        "files_read": files,
        "fixture_rows_excluded": excluded,
    }


if __name__ == "__main__":
    import sys
    run(sys.argv[1:])

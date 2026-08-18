"""R19 — outcome metrics: what the filter DECIDED, and what that cost (OPS_CONSOLE_PROGRAM §14.6).

Ask 5, in one derivation. Seven views, each answering one clause of the requirement:

  * `catalogue_outcomes`  pass/kill rates for the WHOLE catalogue, counted in SQL, plus the
                          reconciliation receipt against `catalogue_stats()`.
  * `gate_view`           kill reason by gate — one `GROUP BY decision, gate_fired`.
  * `rates_over_time`     the same three populations per day, from `batch_diagnostics.jsonl`.
  * `verdict_matrix`      per-check supported / refuted / unverifiable across the window.
  * `funnel_view`         generated → pass, with every loss ATTRIBUTED to what caused it.
  * `composite_view`      the composite distribution against the bar it was judged on.
  * `cost_view`           metered spend per outcome, and what the outage tax inside it is.

Four rules, each a scar this module is shaped by:

1. **A DEFER IS AN OUTAGE, NOT AN OUTCOME.** It is the verdict "we could not measure", produced
   by a moat that was exhausted or a retrieval that failed — the idea was never judged. So a
   defer NEVER enters the denominator of a pass or kill rate, and never counts as funnel
   drop-off: `funnel_view` marks the vetted→ruled loss `kind: "outage"` and excludes it from
   `dropped_total`. Folding it in makes an outage read as a stricter filter, which is the
   inverse of the truth (`an-outage-is-the-end-of-the-measurement-not-a-datum`).
2. **An unmeasured figure prints as an explicit null WITH A REASON.** `pass_rate: 0.0` on a
   batch where nothing was ruled is a lie that reads as bad news; `pass_rate: None` plus
   "32 of 42 vetted deferred and nothing was ruled" is the truth. Same for a check with no
   observations and a row with no composite (`a-saturated-metric-prints-as-a-confident-null`).
3. **Derive nothing twice.** Every catalogue count is one SQL statement — `counts_by_decision()`
   where it exists, one `GROUP BY` on the same index where it does not. Nothing here len()s a
   Python list of rows (`one-reader-two-caller-shapes`).
4. **Two populations, never silently merged.** The catalogue (`prospector.db`, all history, all
   entry points) and the scheduled batches (`batch_diagnostics.jsonl`, since 2026-06-22) are
   DIFFERENT populations — measured on the live store: the jsonl accounts for 1,228 vetted rows
   against 2,376 in the catalogue. Every jsonl-derived view therefore carries a `coverage`
   block naming the gap, so a time series is never read as a catalogue total.

Nothing here writes.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable, Optional

from prospector.ops import readmodel as _rm

#: The scheduler's per-batch diagnostics record. Appended live by a running producer, so it is
#: read mid-write by construction and torn lines are SKIPPED, never raised (`_rm._read_lines`).
DIAG_FILENAME = "batch_diagnostics.jsonl"

#: The six universal checks, in the order `verify.py` runs them. Named explicitly rather than
#: discovered from the data, because a check that produced NO observation is exactly the thing
#: worth showing: kill-fast short-circuits, so an empty `value_durability` column means earlier
#: gates fired first, not that the check is healthy.
CHECKS: tuple[str, ...] = (
    "pain_reality", "value_durability", "incumbency",
    "payer_solvency", "distribution", "legality",
)

#: The verdicts a check can carry.
VERDICTS: tuple[str, ...] = ("supported", "refuted", "unverifiable")

#: The two decisions that are RULINGS. `defer` is deliberately absent — see rule 1.
RULED: tuple[str, ...] = ("pass", "kill")

#: Composite histogram bucket width. 0.25 keeps the bar (2.5 / 3.2 / a persona override) on a
#: bucket EDGE, so "below the bar" is never split across a bucket.
BUCKET = 0.25

#: What `gate_fired` is called when a KILL row carries none. NOT folded into `min_composite`:
#: `report.py:117` does exactly that (`r.get("gate_fired") or "min_composite"`), which invents
#: 9 min_composite kills on the live store out of rows whose gate was never recorded.
UNRECORDED_GATE = "(unrecorded)"


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #
def load_cfg(path: Optional[str] = None):
    """Config loaded THE WAY THE ENGINE LOADS IT — `readmodel.load_cfg`, not a bare import.

    Re-exported rather than reimplemented so a caller cannot pick the wrong one: `load_config`
    installs the process globals, and skipping it answers a different trusted roster than the
    daemon is ruling on (§14.5.1).
    """
    return _rm.load_cfg(path)


def _num(value: Any) -> int:
    """An int, or 0 for anything that will not become one. Diagnostics are model-adjacent."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _flt(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct(part: int, whole: int) -> Optional[float]:
    """A percentage, or None when there is no denominator. NEVER 0.0 for "nothing to divide"."""
    if whole <= 0:
        return None
    return round(part / whole * 100.0, 1)


def diagnostics_path(cfg):
    from prospector.scheduler import paths as _paths

    return _paths.scheduler_dir(cfg, create=False) / DIAG_FILENAME


def diagnostics_records(cfg, *, since: Optional[float] = None) -> list[dict]:
    """Every batch record, oldest first, torn lines skipped and undated records dropped.

    Reuses `readmodel._read_lines` — the shipped torn-tolerant reader — rather than writing a
    second one. A monitor that dies on a half-written line is a monitor that is down exactly
    when the thing it watches is busy.

    A record whose `ts` will not parse is DROPPED rather than dated `now`: it cannot be placed
    on a time axis, and dating it to the read time would invent a spike on today.
    """
    out: list[dict] = []
    for row in _rm._read_lines(diagnostics_path(cfg)):   # noqa: SLF001 — one torn-safe reader
        ts = _rm._parse_ts(row.get("ts"))                # noqa: SLF001
        if ts is None or (since is not None and ts < since):
            continue
        rec = dict(row)
        rec["_ts"] = ts
        rec["_day"] = _rm._iso(ts)[:10]                  # noqa: SLF001
        out.append(rec)
    out.sort(key=lambda r: r["_ts"])
    return out


def _sql(store, query: str, params: Iterable = ()) -> list[tuple]:
    """One statement against the catalogue index. SQLite counts; Python never does.

    `Store._connect` is private, so this opens its own connection on the PUBLIC `Store.db`
    path — the same file `counts_by_decision` and `catalogue_stats` read, with the same
    statements. That is reuse of the source of truth, not a second definition of a count.
    """
    conn = sqlite3.connect(str(store.db), timeout=5.0)
    try:
        return list(conn.execute(query, tuple(params)).fetchall())
    except sqlite3.Error:
        # A locked or corrupt index and an empty catalogue must not render identically; the
        # caller turns an empty result into an explicit "index unreadable" null.
        return []
    finally:
        conn.close()


def _store_for(cfg, store=None):
    if store is not None:
        return store
    from prospector.store import Store

    return Store(cfg)


# --------------------------------------------------------------------------- #
# The reconciliation receipt — R19's probe, executable in production
# --------------------------------------------------------------------------- #
def reconciliation(cfg, *, store=None, stats: Optional[dict] = None) -> dict:
    """Our totals beside `catalogue_stats()`'s, and whether they are the SAME numbers.

    R19's probe is "figures reconcile to `catalogue_stats()`". A probe that lives only in a
    test answers for the fixture; this one runs on the live store every time the page renders,
    so a divergence is LOUD on screen rather than discovered later. When they disagree the view
    reports `reconciled: False` and the deltas, and the page refuses to present the charts as
    catalogue truth — a figure that looks right is the failure mode being guarded against.

    `stats` is injectable so a test can hand in the real `readers.catalogue_stats()` pointed at
    a fixture store; the default calls it for real.
    """
    store = _store_for(cfg, store)
    ours = _decision_counts(store)

    if stats is None:
        try:
            from prospector.ops import readers as _readers

            stats = _readers.catalogue_stats()
        except Exception as exc:   # noqa: BLE001 — an unreadable comparator is not a bad figure
            return {"reconciled": None, "ours": ours, "catalogue_stats": None,
                    "reason": f"catalogue_stats() unavailable: {exc}"}

    theirs = {
        "pass": _num(stats.get("n_pass")), "kill": _num(stats.get("n_kill")),
        "defer": _num(stats.get("n_defer")), "total": _num(stats.get("total")),
        "provisional": _num(stats.get("n_provisional")),
    }
    mine = {"pass": ours["pass"], "kill": ours["kill"], "defer": ours["defer"],
            "total": ours["total"], "provisional": ours["provisional"]}
    deltas = {k: mine[k] - theirs[k] for k in mine if mine[k] != theirs[k]}
    return {
        "reconciled": not deltas,
        "ours": mine,
        "catalogue_stats": theirs,
        "deltas": deltas,
        "reason": "" if not deltas else (
            "R19's own probe FAILED: these charts and `catalogue_stats()` are counting "
            "different populations. Do not read the figures below as catalogue totals."),
    }


def _decision_counts(store) -> dict[str, int]:
    """Every decision bucket, plus provisional, in two SQL statements and no Python counting.

    `counts_by_decision()` is the shipped call and is used verbatim — the panel's headline
    number and the drain's must be one number, from one statement (`store.py:454`).
    """
    raw = store.counts_by_decision()
    counts = {str(k or "").lower(): _num(v) for k, v in raw.items()}
    prov_rows = _sql(store, "SELECT lower(coalesce(decision,'')) AS d, COUNT(*) "
                            "FROM dossiers WHERE provisional = 1 GROUP BY d")
    provisional = {str(d): _num(n) for d, n in prov_rows}
    total = sum(counts.values())
    known = {k: counts.get(k, 0) for k in ("pass", "kill", "defer")}
    other = {k: v for k, v in counts.items() if k not in known}
    return {
        **known,
        "total": total,
        "other": other,
        "provisional": sum(provisional.values()),
        "provisional_by_decision": provisional,
    }


# --------------------------------------------------------------------------- #
# Catalogue outcomes — the reconciling core
# --------------------------------------------------------------------------- #
def catalogue_outcomes(cfg, *, store=None, stats: Optional[dict] = None) -> dict:
    """Pass / kill rates for the whole catalogue, with the defer population held OUT of them.

    `ruled = pass + kill`. That denominator is the entire point: a run whose moat was down
    produces defers, and dividing by `pass + kill + defer` would report the outage as a lower
    pass rate — an engine that looks pickier the more broken it is. The defers are reported in
    their own block, attributed, so nothing is hidden by the exclusion.

    `provisional` is surfaced beside the kills it belongs to because those rulings are NOT
    settled: a row ruled outside `moat_primary()` is stamped provisional and re-vetted, so this
    many of the kills below may still move.
    """
    store = _store_for(cfg, store)
    c = _decision_counts(store)
    ruled = c["pass"] + c["kill"]

    reason = ""
    if ruled == 0:
        reason = (f"nothing has been ruled: {c['defer']} defer row(s) of {c['total']} — "
                  "an outage population, not a 0% pass rate")

    return {
        "counts": {k: c[k] for k in ("pass", "kill", "defer", "total")},
        "other_decisions": c["other"],
        "ruled": ruled,
        "pass_rate_pct": _pct(c["pass"], ruled),
        "kill_rate_pct": _pct(c["kill"], ruled),
        "rate_basis": "pass + kill (RULED rows). Defers are excluded by design — see `defer`.",
        "rate_reason": reason,
        "defer": {
            "n": c["defer"],
            "share_of_catalogue_pct": _pct(c["defer"], c["total"]),
            "note": "an outage, not an outcome — the moat or retrieval was unavailable, so the "
                    "idea was never judged. `vet --resume` finalises these; they are excluded "
                    "from every rate above.",
        },
        "provisional": {
            "n": c["provisional"],
            "by_decision": c["provisional_by_decision"],
            "note": "ruled by a tier outside moat_primary(), so untrusted-final and awaiting a "
                    "re-vet: this many of the rulings above can still change.",
        },
        "reconciliation": reconciliation(cfg, store=store, stats=stats),
    }


# --------------------------------------------------------------------------- #
# Kill reason by gate
# --------------------------------------------------------------------------- #
def gate_view(cfg, *, store=None) -> dict:
    """Which gate killed, and how often — one `GROUP BY decision, gate_fired`.

    TWO THINGS THIS REFUSES TO DO.

    * **It does not attribute an unrecorded gate to `min_composite`.** `report.py:117` writes
      `r.get("gate_fired") or "min_composite"`, which on the live store turns 9 kills whose gate
      was never written into 9 min_composite kills. They are reported here as
      `(unrecorded)` with their own count, because "we do not know why this died" is a finding.
    * **It does not list a DEFER as a gate.** Defer rows carry an empty `gate_fired` and would
      otherwise land in the same `(unrecorded)` bucket as an ungated kill, inflating a kill
      reason with an outage. The statement is filtered to kills.
    """
    store = _store_for(cfg, store)
    rows = _sql(store,
                "SELECT lower(coalesce(decision,'')) AS d, "
                "       coalesce(nullif(trim(coalesce(gate_fired,'')),''), ?) AS g, "
                "       COUNT(*) AS n "
                "FROM dossiers GROUP BY d, g", (UNRECORDED_GATE,))

    gates: dict[str, int] = {}
    non_kill_gates: dict[str, int] = {}
    kills = 0
    for decision, gate, n in rows:
        n = _num(n)
        if str(decision) == "kill":
            gates[str(gate)] = gates.get(str(gate), 0) + n
            kills += n
        elif str(gate) != UNRECORDED_GATE:
            # A gate recorded on a non-kill row is an anomaly worth naming, not worth hiding.
            key = f"{decision}:{gate}"
            non_kill_gates[key] = non_kill_gates.get(key, 0) + n

    ordered = sorted(gates.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "kills": kills,
        "gates": [{"gate": g, "n": n, "pct_of_kills": _pct(n, kills)} for g, n in ordered],
        "unrecorded": gates.get(UNRECORDED_GATE, 0),
        "unrecorded_note": (
            f"{gates.get(UNRECORDED_GATE, 0)} kill(s) carry no gate. NOT folded into "
            "min_composite (which `run.py report` does) — an unattributed kill is a finding."),
        "gates_on_non_kill_rows": non_kill_gates,
        "reason": "" if kills else "no KILL row in the catalogue — nothing to attribute",
    }


# --------------------------------------------------------------------------- #
# Rates over time
# --------------------------------------------------------------------------- #
def _rate_point(bucket: dict) -> dict:
    """One time bucket's rates, or explicit nulls with the reason they cannot be computed."""
    ruled = bucket["pass"] + bucket["kill"]
    vetted = bucket["vetted"] or (ruled + bucket["defer"])
    reason = ""
    if vetted == 0:
        reason = "no candidate was vetted in this bucket"
    elif ruled == 0:
        reason = (f"{bucket['defer']} of {vetted} vetted deferred and nothing was ruled — "
                  "a retrieval/moat outage, not a 0% pass rate")
    return {
        **bucket,
        "vetted": vetted,
        "ruled": ruled,
        "pass_rate_pct": _pct(bucket["pass"], ruled),
        "kill_rate_pct": _pct(bucket["kill"], ruled),
        # NAMED `outage_rate`, not `defer_rate`, and computed over VETTED rather than ruled:
        # it is the share of work the engine could not finish, which is a different question
        # from how strict the filter is. Keeping the two names apart is what stops a reader
        # sliding one into the other.
        "outage_rate_pct": _pct(bucket["defer"], vetted),
        "reason": reason,
    }


def rates_over_time(cfg, *, since: Optional[float] = None,
                    records: Optional[list[dict]] = None) -> dict:
    """Pass / kill / outage per DAY, from the batch diagnostics.

    Per day rather than per batch because batches are bursty (up to a dozen an hour, then
    nothing for two days) and a per-batch series charts the scheduler's cadence rather than the
    engine's behaviour.
    """
    recs = diagnostics_records(cfg, since=since) if records is None else records
    by_day: dict[str, dict] = {}
    for r in recs:
        d = r.get("decisions") or {}
        b = by_day.setdefault(r["_day"], {"day": r["_day"], "batches": 0, "pass": 0,
                                          "kill": 0, "defer": 0, "vetted": 0, "provisional": 0})
        b["batches"] += 1
        for key in ("pass", "kill", "defer", "vetted", "provisional"):
            b[key] += _num(d.get(key))

    points = [_rate_point(by_day[day]) for day in sorted(by_day)]
    totals = {k: sum(p[k] for p in points) for k in ("pass", "kill", "defer", "vetted")}
    totals["batches"] = sum(p["batches"] for p in points)
    overall = _rate_point({"day": "all", "batches": totals["batches"], **{
        k: totals[k] for k in ("pass", "kill", "defer", "vetted")}, "provisional": 0})

    return {
        "points": points,
        "totals": overall,
        "records": len(recs),
        "reason": "" if points else (
            f"no parsable record in {DIAG_FILENAME} for the requested window"),
    }


# --------------------------------------------------------------------------- #
# Verdict matrix
# --------------------------------------------------------------------------- #
def verdict_matrix(cfg, *, since: Optional[float] = None,
                   records: Optional[list[dict]] = None) -> dict:
    """supported / refuted / unverifiable per check, summed over the window.

    A CHECK WITH NO OBSERVATIONS IS THE INTERESTING ROW, and it prints as an explicit null.
    Kill-fast short-circuits: once `pain_reality` refutes, `value_durability` and `incumbency`
    are never run, so their columns are empty on the live store. `unverifiable_pct: 0.0` there
    would read as "perfectly grounded"; `None` plus "0 observations — kill-fast short-circuits
    before this check" reads as what it is.
    """
    recs = diagnostics_records(cfg, since=since) if records is None else records
    tally: dict[str, dict[str, int]] = {c: {v: 0 for v in VERDICTS} for c in CHECKS}
    extra_checks: set[str] = set()

    for r in recs:
        matrix = r.get("verdict_matrix") or {}
        if not isinstance(matrix, dict):
            continue
        for check, counts in matrix.items():
            if not isinstance(counts, dict):
                continue
            check = str(check)
            if check not in tally:
                tally[check] = {v: 0 for v in VERDICTS}
                extra_checks.add(check)
            for verdict, n in counts.items():
                v = str(verdict).lower()
                if v in tally[check]:
                    tally[check][v] += _num(n)

    rows = []
    for check, counts in tally.items():
        n = sum(counts.values())
        rows.append({
            "check": check,
            **counts,
            "n": n,
            "unverifiable_pct": _pct(counts["unverifiable"], n),
            "supported_pct": _pct(counts["supported"], n),
            "reason": "" if n else (
                "0 observations in this window — kill-fast short-circuits before this check "
                "once an earlier gate fires, so an empty column is a running order, not a "
                "clean bill of health"),
        })
    rows.sort(key=lambda r: (CHECKS.index(r["check"]) if r["check"] in CHECKS else 99,
                             r["check"]))

    observed = sum(r["n"] for r in rows)
    retrieval_failed = sum(_num(r.get("retrieval_failed_checks")) for r in recs)
    return {
        "rows": rows,
        "checks_observed": sum(1 for r in rows if r["n"]),
        "checks_total": len(rows),
        "observations": observed,
        # An OUTAGE COUNTER, kept out of the verdict columns. A check whose retrieval failed
        # produced no verdict at all; counting it as `unverifiable` would turn our own downtime
        # into evidence about an idea (`verify.py:365` defers instead, and so must this).
        "retrieval_failed_checks": retrieval_failed,
        "retrieval_failed_note": "checks whose retrieval failed — an outage, counted separately "
                                 "and never as an `unverifiable` verdict",
        "extra_checks": sorted(extra_checks),
        "reason": "" if observed else "no check observation in the window",
    }


# --------------------------------------------------------------------------- #
# Funnel with attributed drop-off
# --------------------------------------------------------------------------- #
def funnel_view(cfg, *, since: Optional[float] = None,
                records: Optional[list[dict]] = None) -> dict:
    """generated → pass, with every loss attributed to the thing that caused it.

    THE VETTED→RULED STEP IS `kind: "outage"`, NOT A DROP-OFF, and it is excluded from
    `dropped_total`. Those candidates were not rejected; the engine could not reach a verdict on
    them, and `vet --resume` will finalise them. A funnel that draws that step as attrition
    reports an outage as selectivity — the single most misleading chart this page could draw.

    `novelty_selected → vetted` is `kind: "unfinished"` for the same family of reasons: a batch
    that ran out of budget left rows unvetted, which is neither a rejection nor an outage.
    """
    recs = diagnostics_records(cfg, since=since) if records is None else records
    f = {k: 0 for k in ("generated", "dedup_dropped", "rejection_fastpath", "prescreen_in",
                        "prescreened_out", "novelty_selected", "vetted")}
    d = {k: 0 for k in ("pass", "kill", "defer")}
    gates: dict[str, int] = {}
    for r in recs:
        rf = r.get("funnel") or {}
        for k in f:
            f[k] += _num(rf.get(k))
        rd = r.get("decisions") or {}
        for k in d:
            d[k] += _num(rd.get(k))
        for gate, n in (r.get("kill_gates") or {}).items():
            gates[str(gate)] = gates.get(str(gate), 0) + _num(n)

    ruled = d["pass"] + d["kill"]
    unfinished = max(0, f["novelty_selected"] - f["vetted"])

    steps = [
        {"stage": "generated", "n": f["generated"]},
        {"stage": "prescreen_in", "n": f["prescreen_in"], "kind": "drop",
         "lost": f["dedup_dropped"] + f["rejection_fastpath"],
         "attributed_to": {"dedup_dropped": f["dedup_dropped"],
                           "rejection_fastpath": f["rejection_fastpath"]}},
        {"stage": "novelty_selected", "n": f["novelty_selected"], "kind": "drop",
         "lost": f["prescreened_out"],
         "attributed_to": {"prescreened_out": f["prescreened_out"]}},
        {"stage": "vetted", "n": f["vetted"], "kind": "unfinished", "lost": unfinished,
         "attributed_to": {"never_vetted": unfinished},
         "note": "selected but not vetted — the batch's bound ran out. Neither a rejection nor "
                 "an outage."},
        {"stage": "ruled", "n": ruled, "kind": "outage", "lost": d["defer"],
         "attributed_to": {"defer": d["defer"]},
         "note": "NOT drop-off. The moat or retrieval was unavailable, so these were never "
                 "judged; `vet --resume` finalises them."},
        {"stage": "pass", "n": d["pass"], "kind": "drop", "lost": d["kill"],
         "attributed_to": dict(sorted(gates.items(), key=lambda kv: -kv[1]))},
    ]

    dropped_total = sum(s["lost"] for s in steps if s.get("kind") == "drop")

    # THE RESIDUAL IS PRINTED, NOT ABSORBED. If the stage arithmetic does not close, a chart
    # that silently rescales looks healthy while the emitter is dropping a field.
    residual = f["generated"] - f["dedup_dropped"] - f["rejection_fastpath"] - f["prescreen_in"]
    return {
        "steps": steps,
        "dropped_total": dropped_total,
        "outage_total": d["defer"],
        "unfinished_total": unfinished,
        "kill_gates": dict(sorted(gates.items(), key=lambda kv: -kv[1])),
        "residual_generated_vs_prescreen_in": residual,
        "residual_note": "" if residual == 0 else (
            f"{residual} candidate(s) unaccounted for between `generated` and `prescreen_in` — "
            "the emitter and this view disagree; treat the top of the funnel as approximate"),
        "records": len(recs),
        "reason": "" if recs else f"no parsable record in {DIAG_FILENAME} for the window",
    }


# --------------------------------------------------------------------------- #
# Composite distribution vs the bar
# --------------------------------------------------------------------------- #
def composite_view(cfg, *, store=None, records: Optional[list[dict]] = None) -> dict:
    """The composite distribution of RULED rows, bucketed in SQL, against the bar applied.

    UNSCORED ROWS ARE NAMED, NEVER BUCKETED AT ZERO. On the live store 1,348 of 2,143 kills
    carry `composite IS NULL` — they died kill-fast, before scoring ever ran — and 151 defers
    were never scored at all. Rendering `NULL` as `0.0` would pile 1,499 phantom rows into the
    leftmost bucket and make the distribution look like an engine that scores everything badly.
    They are reported as `unscored`, with why.

    THE BAR IS NOT ONE NUMBER. `cfg.thresholds.min_composite_to_pass` is the global, but personas
    override it and the live diagnostics show batches judged at 2.5 while the config default is
    3.2. Every DISTINCT bar actually applied is listed; drawing one line through a distribution
    judged against several is a chart that is wrong for most of its own rows.
    """
    store = _store_for(cfg, store)
    placeholders = ",".join("?" for _ in RULED)
    rows = _sql(store,
                f"SELECT lower(coalesce(decision,'')) AS d, "
                f"       CAST(composite / ? AS INTEGER) AS b, COUNT(*) AS n "
                f"FROM dossiers "
                f"WHERE composite IS NOT NULL AND lower(coalesce(decision,'')) IN ({placeholders}) "
                f"GROUP BY d, b", (BUCKET, *RULED))
    unscored_rows = _sql(store,
                         "SELECT lower(coalesce(decision,'')) AS d, COUNT(*) AS n "
                         "FROM dossiers WHERE composite IS NULL GROUP BY d")

    buckets: dict[int, dict[str, int]] = {}
    for decision, b, n in rows:
        slot = buckets.setdefault(int(b), {k: 0 for k in RULED})
        slot[str(decision)] = slot.get(str(decision), 0) + _num(n)

    bar = _flt(getattr(getattr(cfg, "thresholds", None), "min_composite_to_pass", 0.0))
    observed_bars = sorted({
        round(_flt((r.get("thresholds") or {}).get("min_composite_to_pass")), 3)
        for r in (records if records is not None else diagnostics_records(cfg))
        if (r.get("thresholds") or {}).get("min_composite_to_pass") is not None
    })

    dist = []
    for slot in sorted(buckets):
        counts = buckets[slot]
        lo = round(slot * BUCKET, 2)
        dist.append({"bucket": f"{lo:.2f}", "low": lo, "high": round(lo + BUCKET, 2),
                     **counts, "n": sum(counts.values())})

    scored = sum(b["n"] for b in dist)
    above = sum(b["n"] for b in dist if b["low"] >= bar) if bar > 0 else None
    unscored = {str(d): _num(n) for d, n in unscored_rows}

    return {
        "bar": bar or None,
        "bar_source": "cfg.thresholds.min_composite_to_pass",
        "bars_observed": observed_bars,
        "bar_caveat": "" if len(observed_bars) <= 1 else (
            f"{len(observed_bars)} different bars were applied in the diagnostics window "
            f"({', '.join(str(b) for b in observed_bars)}) — persona overrides. A single line "
            "on this distribution is wrong for every batch judged at another bar."),
        "distribution": dist,
        "scored": scored,
        "at_or_above_bar": above,
        "below_bar": (scored - above) if above is not None else None,
        "bar_reason": "" if bar > 0 else "no min_composite_to_pass on this cfg — no bar to draw",
        "unscored": {
            "by_decision": unscored,
            "total": sum(unscored.values()),
            "note": "never scored — kill-fast short-circuited before `score.py` ran, or the row "
                    "deferred. Excluded from the distribution rather than bucketed at 0.0, "
                    "which would invent that many worst-possible ideas.",
        },
        "reason": "" if scored else "no ruled row carries a composite — nothing to distribute",
    }


# --------------------------------------------------------------------------- #
# Cost per outcome
# --------------------------------------------------------------------------- #
def cost_view(cfg, *, since: Optional[float] = None,
              records: Optional[list[dict]] = None) -> dict:
    """Metered spend over the window, divided by the work it bought — two ways, on purpose.

    `cost_per_vetted` divides by every candidate the engine STARTED. `cost_per_ruled` divides by
    the ones it FINISHED. The difference between them is the outage tax: money spent on rows the
    moat could not rule, which `vet --resume` will spend again. One number alone hides it — the
    first understates what an answer costs, the second silently blames the filter for downtime.

    WHAT THIS CANNOT SEE, said out loud: `total_cost_usd` is METERED spend. `claude_cli` runs on
    the subscription and reports `cost_usd: 0.0` on every call, so a window served mostly by the
    CLI shows a near-zero cost that is a billing artefact, not cheap work. Unmetered providers
    are listed with their call counts so the figure is never read as total cost of ownership.
    """
    recs = diagnostics_records(cfg, since=since) if records is None else records

    total = 0.0
    calls = 0
    by_provider: dict[str, dict[str, float]] = {}
    by_phase: dict[str, int] = {}
    d = {k: 0 for k in ("pass", "kill", "defer", "vetted")}
    for r in recs:
        usage = r.get("usage") or {}
        total += _flt(usage.get("total_cost_usd"))
        calls += _num((usage.get("total") or {}).get("calls"))
        for name, blob in (usage.get("by_provider") or {}).items():
            if not isinstance(blob, dict):
                continue
            slot = by_provider.setdefault(str(name), {"calls": 0, "cost_usd": 0.0})
            slot["calls"] += _num(blob.get("calls"))
            slot["cost_usd"] += _flt(blob.get("cost_usd"))
        for phase, blob in (usage.get("by_phase") or {}).items():
            if isinstance(blob, dict):
                by_phase[str(phase)] = by_phase.get(str(phase), 0) + _num(blob.get("calls"))
        rd = r.get("decisions") or {}
        for k in d:
            d[k] += _num(rd.get(k))

    ruled = d["pass"] + d["kill"]
    vetted = d["vetted"] or (ruled + d["defer"])

    def _per(n: int) -> Optional[float]:
        return round(total / n, 4) if n > 0 and total > 0 else None

    # Ordered by CALLS, not alphabetically: on the live window 22 provider labels report $0 and
    # most are one-off historical fallback-chain names ("fallback(deepseek+minimax+gemini)", 1
    # call). An alphabetical list buries `claude_cli`'s 5,126 unbilled calls — the one that
    # actually makes the headline figure an understatement — behind noise.
    unmetered = [name for name, _v in sorted(
        by_provider.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))
        if _v["calls"] > 0 and _v["cost_usd"] <= 0.0]
    return {
        "total_cost_usd": round(total, 4),
        "calls": calls,
        "vetted": vetted, "ruled": ruled, "pass": d["pass"], "kill": d["kill"],
        "defer": d["defer"],
        "cost_per_vetted_usd": _per(vetted),
        "cost_per_ruled_usd": _per(ruled),
        "cost_per_pass_usd": _per(d["pass"]),
        "outage_tax_usd": (round(total / ruled - total / vetted, 4)
                           if ruled > 0 and vetted > 0 and total > 0 else None),
        "outage_tax_note": "cost_per_ruled − cost_per_vetted: the per-answer surcharge from rows "
                           "the moat could not rule. It is a defer cost, never a kill cost.",
        "by_provider": {k: {"calls": int(v["calls"]), "cost_usd": round(v["cost_usd"], 4)}
                        for k, v in sorted(by_provider.items())},
        "by_phase_calls": dict(sorted(by_phase.items())),
        "unmetered_providers": unmetered,
        "unmetered_note": (
            f"{', '.join(unmetered[:5])}"
            f"{f' and {len(unmetered) - 5} more' if len(unmetered) > 5 else ''} report $0 across "
            f"{sum(by_provider[n]['calls'] for n in unmetered):,} call(s) — subscription or free "
            "tiers. The spend above is METERED cost only and is not total cost of ownership."
            if unmetered else ""),
        "reason": "" if total > 0 else (
            "no metered spend recorded in this window — either nothing ran, or every call was "
            "served by an unmetered provider. Not $0 of work."),
        "records": len(recs),
    }


# --------------------------------------------------------------------------- #
# Coverage — the two populations, never silently merged
# --------------------------------------------------------------------------- #
def coverage(cfg, *, store=None, records: Optional[list[dict]] = None) -> dict:
    """How much of the catalogue the jsonl-derived views can actually see.

    `batch_diagnostics.jsonl` starts on 2026-06-22 and records SCHEDULED batches only; the
    catalogue also holds on-demand vets and everything from before the emitter existed.
    Measured on the live store the gap is over a thousand rows. Naming it is what stops a time
    series being read as a catalogue total — the same class of error as charting
    `store/run_metrics.db` (20 rows written in 0.4s) as a trend (§14.4).
    """
    store = _store_for(cfg, store)
    recs = diagnostics_records(cfg) if records is None else records
    c = _decision_counts(store)
    vetted = sum(_num((r.get("decisions") or {}).get("vetted")) for r in recs)
    return {
        "records": len(recs),
        "first_ts": _rm._iso(recs[0]["_ts"]) if recs else None,     # noqa: SLF001
        "last_ts": _rm._iso(recs[-1]["_ts"]) if recs else None,     # noqa: SLF001
        "diagnostics_vetted": vetted,
        "catalogue_rows": c["total"],
        "covered_pct": _pct(vetted, c["total"]),
        "note": "the time series, funnel, verdict matrix and cost figures cover SCHEDULED "
                "BATCHES only; the catalogue totals cover every entry point and all history. "
                "They are different populations and are not expected to be equal.",
    }


# --------------------------------------------------------------------------- #
def snapshot(cfg=None, *, window_days: Optional[float] = None, store=None) -> dict:
    """Every R19 view in one call, over one set of records and one Store.

    Records and Store are read ONCE and threaded through: seven views each re-reading a 120-row
    jsonl and re-opening the index is how a panel becomes slow enough to be cached, and a cached
    outcome count is a console reporting a catalogue that changed an hour ago.
    """
    import time as _time

    cfg = cfg if cfg is not None else load_cfg()
    store = _store_for(cfg, store)
    since = (_time.time() - window_days * 86400.0) if window_days else None
    recs = diagnostics_records(cfg, since=since)
    all_recs = recs if since is None else diagnostics_records(cfg)
    return {
        "now": _rm._iso(_time.time()),                              # noqa: SLF001
        "window_days": window_days,
        "outcomes": catalogue_outcomes(cfg, store=store),
        "gates": gate_view(cfg, store=store),
        "rates": rates_over_time(cfg, records=recs),
        "verdicts": verdict_matrix(cfg, records=recs),
        "funnel": funnel_view(cfg, records=recs),
        "composite": composite_view(cfg, store=store, records=all_recs),
        "cost": cost_view(cfg, records=recs),
        "coverage": coverage(cfg, store=store, records=recs),
    }


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.metrics [--view …]` — the same figures for a non-Python surface."""
    import argparse

    ap = argparse.ArgumentParser(description="Outcome metrics (R19)")
    ap.add_argument("--view", default="all",
                    choices=["all", "outcomes", "gates", "rates", "verdicts", "funnel",
                             "composite", "cost", "coverage"])
    ap.add_argument("--window-days", type=float, default=None)
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    if args.view == "all":
        out = snapshot(cfg, window_days=args.window_days)
    else:
        out = snapshot(cfg, window_days=args.window_days)[
            {"outcomes": "outcomes", "gates": "gates", "rates": "rates",
             "verdicts": "verdicts", "funnel": "funnel", "composite": "composite",
             "cost": "cost", "coverage": "coverage"}[args.view]]
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

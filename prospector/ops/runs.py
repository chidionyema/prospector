"""The per-run internals view — one run, every candidate, every check (OPS_CONSOLE_PROGRAM R18).

Ask 4 of the programme, in one derivation: *one run → generation → per candidate → per check →
query, provider, the passage quoted, verdict, confidence, cost, latency → gate fired → score →
publish.* Two entry points, both pure reads:

  * `run_index` / `run_view`  — the run spine. A "run" is `prospector.audit`'s `run_id`: minted
    once per PROCESS, which is the only identity in this estate that separates the daemon from a
    backfill from a manual CLI on the same day-file (`audit.py:110-152`). Grouping a day-file by
    time instead would interleave three processes into one confidently wrong story — it did,
    twice in one session on 2026-07-31, which is why `run_id` exists at all.
  * `candidate_view`          — one candidate's whole causal chain, read from the dossier JSON
    through `Store`, joined to that run's audit rows for query-grain latency.

Four rules this module exists to keep, each of them a scar:

1. **`retrieval_failed` is an OUTAGE, never a datum (§7.2 T2).** A check whose verdict CALL failed
   carries `verdict=None, confidence=None` here — the fields a renderer would print simply do not
   hold a reading. What the engine wrote as a fail-safe placeholder is nested inside `outage`,
   labelled as a placeholder. The defect is on disk: `store/dossiers/2102bacc6dd75cf9.kill.json`
   is a KILL on `min_composite` whose SEVEN checks all read `unverifiable, conf 0.0, "Verdict call
   failed; fail-safe."` — a candidate killed by our own outage, in a dossier that reads as fully
   reasoned (memory: `an-outage-is-the-end-of-the-measurement-not-a-datum`). That dossier predates
   `verify.py` setting the flag, so `classify_check` ALSO matches the engine's own fail-safe
   rationale (`verify.py:561`); a rule that only read the flag would render the very dossier this
   requirement is named after as seven ordinary readings.
2. **Derive nothing twice.** The decision, the gate, the composite and the publish status are read
   as the engine WROTE them. `score.composite_recomputed` is computed only to say whether it
   RECONCILES; the stored number stays authoritative either way. A panel that recomputes a verdict
   is a second engine (`one-reader-two-caller-shapes`).
3. **Every number carries its provenance, or is an explicit null with a REASON.** Per-check cost
   is `None` with the reason naming where cost DOES exist, because the ledger attributes at the
   process grain and the dossier records none (`attribute-at-the-actuators-grain`). A confident
   null is the failure mode (`a-saturated-metric-prints-as-a-confident-null`).
4. **Missing or torn input is "unreadable", never an exception.** A monitor that dies on a
   half-written line is down exactly when the thing it watches is busy.

Nothing here writes.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
import sqlite3

#: The engine's own fail-safe rationale when a verdict CALL raised (`verify.py:561`). Dossiers
#: written before 2026-08-06 carry it with `retrieval_failed` UNSET — the flag was added by the
#: same fix — so the string is the only marker those rows have. Matched exactly, never fuzzily:
#: a substring rule would swallow real rationales that merely discuss a failure.
OUTAGE_RATIONALES: frozenset[str] = frozenset({
    "Verdict call failed; fail-safe.",
})

#: `kind` on every entry of `checks`. The chain keeps its order; the two kinds never merge.
KIND_EVIDENCE = "evidence"
KIND_OUTAGE = "outage"

#: How many day-partitioned audit files a lookup reads by default.
DEFAULT_DAYS = 3

#: Audit events that name a candidate, in the order the engine emits them.
_CANDIDATE_EVENTS = ("candidate_start", "verify_search", "check_result",
                     "soft_early_exit", "candidate_done")


# --------------------------------------------------------------------------- #
# Reading — nothing in this section may raise on bad input
# --------------------------------------------------------------------------- #
def audit_dir(explicit: Optional[Path] = None) -> Path:
    """The directory `prospector.audit` WRITES to, resolved the way the writer resolves it.

    Precedence copies `audit.py:134-137` exactly — `PROSPECTOR_AUDIT_DIR`, else the checkout's
    `store/scheduler/audit`. The env var is re-read HERE rather than trusted from the writer's
    module global because that global is computed at IMPORT: a reader that only looked at
    `audit._AUDIT_DIR` would follow the process's first import instead of the environment the
    caller (or a test) is actually pointing at.
    """
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("PROSPECTOR_AUDIT_DIR")
    if env:
        return Path(env)
    from prospector import audit as _audit

    return Path(_audit._AUDIT_DIR)  # noqa: SLF001 — the writer's own path, verbatim


def _read_jsonl(path: Path) -> tuple[list[dict], int]:
    """`(rows, torn_lines)`. An absent file is `([], 0)`; a torn line is COUNTED, not fatal.

    Counted rather than swallowed: the caller reports `unreadable_lines` so an operator can tell
    "this run had no searches" from "this file was being appended to while I read it".
    """
    try:
        raw = Path(path).read_text(errors="replace")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, OSError):
        return [], 0
    rows: list[dict] = []
    torn = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            torn += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            torn += 1
    return rows, torn


def _day_files(directory: Path, days: int, now: Optional[float]) -> list[Path]:
    """The last `days` day-files that EXIST, newest last.

    Named by date rather than globbed-and-sorted so a stray file (a `.bak`, an editor swap) can
    never be read as engine state, and so a day with no rows is silently absent rather than a
    hole in the middle of a listing.
    """
    now_dt = datetime.fromtimestamp(now, timezone.utc) if now else datetime.now(timezone.utc)
    out = []
    for back in range(max(1, int(days)) - 1, -1, -1):
        p = Path(directory) / f"{(now_dt - timedelta(days=back)).strftime('%Y-%m-%d')}.jsonl"
        if p.exists():
            out.append(p)
    return out


def audit_rows(*, days: int = DEFAULT_DAYS, directory: Optional[Path] = None,
               now: Optional[float] = None, run_id: Optional[str] = None) -> dict:
    """Every audit row in the window, with the provenance of the read itself.

    Returns `rows`, `files` (what was actually read — an empty list is why a run is missing, and
    it is a different answer from "the run recorded nothing"), and `unreadable_lines`.
    """
    d = audit_dir(directory)
    files = _day_files(d, days, now)
    rows: list[dict] = []
    torn_total = 0
    for f in files:
        got, torn = _read_jsonl(f)
        rows.extend(got)
        torn_total += torn
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    rows.sort(key=lambda r: (int(r.get("seq") or 0)))
    return {"rows": rows, "dir": str(d), "files": [str(f) for f in files],
            "unreadable_lines": torn_total,
            "note": ("no audit day-file exists in this window — the log is day-partitioned, so "
                     "an older run is not missing, it is out of range")
            if not files else ""}


# --------------------------------------------------------------------------- #
# The outage rule (§7.2 T2) — the one classification this module makes
# --------------------------------------------------------------------------- #
def classify_check(raw: dict) -> tuple[str, str]:
    """`(kind, why)` for one check dict as it sits in the dossier JSON.

    OUTAGE means the verdict/retrieval CALL failed — quota, bad JSON, a crashed adapter. It is
    the END of the measurement, not a datum in it (`verify.py:548-562`; `kill_filter.py:34` is
    the engine agreeing, by refusing to hard-fail on such a check).

    `degraded` alone is NOT an outage: `verify.py:590` demotes a check to `unverifiable` with
    `degraded=True` when passages WERE fetched and simply did not support the claim. That is a
    real reading and must stay one — conflating the two would hide genuine unverifiables behind
    an outage banner, which is this rule run backwards.
    """
    if raw.get("retrieval_failed"):
        return KIND_OUTAGE, ("retrieval_failed=True — every search/verdict call for this check "
                             "errored (verify.py:562); the measurement never happened")
    if str(raw.get("rationale") or "").strip() in OUTAGE_RATIONALES:
        return KIND_OUTAGE, ("the engine's fail-safe rationale, written when the verdict call "
                             "raised (verify.py:561). This dossier predates the fix that sets "
                             "retrieval_failed, so the flag is absent and the string is the "
                             "only marker — see store/dossiers/2102bacc6dd75cf9.kill.json")
    return KIND_EVIDENCE, ""


# --------------------------------------------------------------------------- #
# Latency — attributed by an exact join key, or not at all
# --------------------------------------------------------------------------- #
def _latency_by_query(rows: Iterable[dict]) -> dict[str, dict]:
    """`{query: {ms, calls, providers, errors, ambiguous}}` from this run's retrieval rows."""
    out: dict[str, dict] = {}
    for r in rows:
        if r.get("event") not in ("search", "page_fetch", "fallback_resolved"):
            continue
        q = str(r.get("query") or "")
        if not q:
            continue
        e = out.setdefault(q, {"ms": 0, "calls": 0, "providers": set(), "errors": 0})
        try:
            e["ms"] += int(r.get("latency_ms") or 0)
        except (TypeError, ValueError):
            pass
        e["calls"] += 1
        prov = r.get("provider") or r.get("actual_provider")
        if prov:
            e["providers"].add(str(prov))
        if str(r.get("status") or "ok") != "ok":
            e["errors"] += 1
    return out


def _check_latency(queries: list[str], by_query: dict[str, dict],
                   query_owners: Counter) -> dict:
    """Retrieval latency for one check, or an explicit null naming why it cannot be attributed.

    The join key is the QUERY STRING recorded on both sides — `CheckResult.queries` in the
    dossier and `query` on the audit row — never the ordering of the log. Ordering would be a
    guess: `minimax_concurrency` is 8, so eight candidates' searches interleave inside one
    `run_id`, and a per-check number sliced out of that interleaving is attribution at the wrong
    grain (`attribute-at-the-actuators-grain`). When one query string served more than one check
    in the run, that too is said out loud rather than double-counted.
    """
    if not queries:
        return {"ms": None, "null_reason": "the dossier records no queries for this check",
                "calls": 0, "providers": [], "errors": 0}
    matched = [q for q in queries if q in by_query]
    if not matched:
        return {"ms": None, "calls": 0, "providers": [], "errors": 0,
                "null_reason": ("no audit row in this run carries any of this check's queries — "
                                "the run is out of the audit window, or retrieval was served "
                                "from cache")}
    shared = [q for q in matched if query_owners[q] > 1]
    if shared:
        return {"ms": None, "calls": 0, "providers": [], "errors": 0,
                "null_reason": (f"{len(shared)} of this check's queries were issued for more "
                                "than one check in this run; per-check attribution would be a "
                                "guess, so it is not made")}
    ms = sum(by_query[q]["ms"] for q in matched)
    providers = sorted({p for q in matched for p in by_query[q]["providers"]})
    return {"ms": ms, "null_reason": "",
            "calls": sum(by_query[q]["calls"] for q in matched),
            "providers": providers,
            "errors": sum(by_query[q]["errors"] for q in matched),
            "provenance": f"sum of audit search/page_fetch latency_ms for {len(matched)} query "
                          f"string(s), joined exactly"}


#: Why cost is null at every grain finer than the process. Stated once, rendered everywhere it
#: applies, so no surface can quietly print a zero.
COST_NULL_REASON = (
    "not recorded at this grain: the dossier stores no cost, and store/scheduler/"
    "batch_diagnostics.jsonl attributes spend per TICK and per PROVIDER — a tick carries no "
    "run_id and no candidate_id, so the join does not exist in the data"
)


# --------------------------------------------------------------------------- #
# R18 — the run spine
# --------------------------------------------------------------------------- #
def run_index(*, days: int = DEFAULT_DAYS, directory: Optional[Path] = None,
              now: Optional[float] = None) -> dict:
    """Every run visible in the window, newest first, with what it actually did.

    Counts come from the events themselves. `outage_checks` is `check_result` rows carrying
    `retrieval_failed` — the audit log records the flag at the moment of the call, so a run's
    outage count is visible here without opening a single dossier.
    """
    read = audit_rows(days=days, directory=directory, now=now)
    runs: dict[str, dict] = {}
    for r in read["rows"]:
        rid = str(r.get("run_id") or "")
        if not rid:
            continue
        e = runs.setdefault(rid, {
            "run_id": rid, "pid": r.get("pid"), "first_ts": r.get("ts"), "last_ts": r.get("ts"),
            "events": 0, "candidates": set(), "decisions": Counter(),
            "checks": 0, "outage_checks": 0, "searches": 0, "search_errors": 0,
        })
        e["events"] += 1
        if r.get("ts"):
            if not e["first_ts"] or str(r["ts"]) < str(e["first_ts"]):
                e["first_ts"] = r["ts"]
            if not e["last_ts"] or str(r["ts"]) > str(e["last_ts"]):
                e["last_ts"] = r["ts"]
        ev = r.get("event")
        if r.get("candidate_id"):
            e["candidates"].add(str(r["candidate_id"]))
        if ev == "candidate_done":
            e["decisions"][str(r.get("decision") or "?")] += 1
        elif ev == "check_result":
            e["checks"] += 1
            if r.get("retrieval_failed"):
                e["outage_checks"] += 1
        elif ev in ("search", "fallback_resolved"):
            e["searches"] += 1
            if str(r.get("status") or "ok") != "ok":
                e["search_errors"] += 1

    out = []
    for e in runs.values():
        out.append({**e, "candidates": len(e["candidates"]),
                    "decisions": dict(e["decisions"]),
                    "cost_usd": None, "cost_null_reason": COST_NULL_REASON})
    out.sort(key=lambda e: str(e["last_ts"] or ""), reverse=True)
    return {"runs": out, "window_days": days, "dir": read["dir"], "files": read["files"],
            "unreadable_lines": read["unreadable_lines"], "note": read["note"]}


def run_view(cfg, run_id: str, *, store=None, days: int = DEFAULT_DAYS,
             directory: Optional[Path] = None, now: Optional[float] = None) -> dict:
    """One run: its candidates in the order it ruled them, each joined to its dossier.

    The audit spine is the ORDER and the identity; the dossier is the content. A candidate the
    run started but never finished shows `decision: None` with a reason rather than being dropped
    — an unfinished candidate is the single most interesting row in a run that died mid-batch.
    """
    read = audit_rows(days=days, directory=directory, now=now, run_id=run_id)
    rows = read["rows"]
    store = store if store is not None else _store(cfg)

    started: dict[str, dict] = {}
    for r in rows:
        if r.get("event") not in _CANDIDATE_EVENTS:
            continue
        cid = str(r.get("candidate_id") or "")
        if not cid:
            continue
        e = started.setdefault(cid, {
            "candidate_id": cid, "title": None, "tier": None, "full_vet": None,
            "started_at": None, "done_at": None, "decision": None, "gate": None,
            "provisional": None, "checks_seen": 0, "outage_checks": 0,
            "soft_early_exit": None,
        })
        ev = r.get("event")
        if ev == "candidate_start":
            e["title"] = r.get("title")
            e["tier"] = r.get("tier")
            e["full_vet"] = r.get("full_vet")
            e["started_at"] = r.get("ts")
        elif ev == "check_result":
            e["checks_seen"] += 1
            if r.get("retrieval_failed"):
                e["outage_checks"] += 1
        elif ev == "soft_early_exit":
            e["soft_early_exit"] = {"after_check": r.get("after_check"), "gate": r.get("gate"),
                                    "skipped": r.get("skipped_checks")}
        elif ev == "candidate_done":
            e["done_at"] = r.get("ts")
            e["decision"] = r.get("decision")
            e["gate"] = r.get("gate")
            e["provisional"] = r.get("provisional")

    candidates = []
    for cid, e in started.items():
        if e["decision"] is None:
            e["decision_null_reason"] = (
                "this run logged candidate_start but no candidate_done — the process ended, was "
                "paused, or the moat went blind mid-candidate")
        doc = _load_dossier(store, cid)
        e["dossier"] = {"status": doc["status"], "reason": doc["reason"],
                        "path": doc["path"],
                        "decision": (doc["data"] or {}).get("decision"),
                        "gate_fired": (doc["data"] or {}).get("gate_fired")}
        candidates.append(e)
    candidates.sort(key=lambda c: str(c["started_at"] or c["done_at"] or ""))

    by_query = _latency_by_query(rows)
    retrieval_ms = sum(v["ms"] for v in by_query.values())
    return {
        "run_id": run_id,
        "found": bool(rows),
        "not_found_reason": "" if rows else (
            f"no audit row with this run_id in the last {days} day-file(s) — "
            f"{read['note'] or 'the run is older than the window, or the id is wrong'}"),
        "pid": next((r.get("pid") for r in rows if r.get("pid") is not None), None),
        "first_ts": rows[0].get("ts") if rows else None,
        "last_ts": rows[-1].get("ts") if rows else None,
        "events": len(rows),
        "candidates": candidates,
        "retrieval": {
            "distinct_queries": len(by_query),
            "latency_ms": retrieval_ms if by_query else None,
            "latency_null_reason": "" if by_query else "this run issued no retrieval calls",
            "errors": sum(v["errors"] for v in by_query.values()),
        },
        "cost_usd": None,
        "cost_null_reason": COST_NULL_REASON,
        "unreadable_lines": read["unreadable_lines"],
        "files": read["files"],
    }


# --------------------------------------------------------------------------- #
# R18 — one candidate, the whole chain
# --------------------------------------------------------------------------- #
def _store(cfg):
    from prospector.store import Store

    return Store(cfg)


def _index_row(store, candidate_id: str) -> Optional[dict]:
    """The SQLite index row, verbatim, for provenance.

    `Store.get()` returns the parsed JSON and drops the path it read it from; this view must be
    able to name the file behind every number it prints, and the index is where the engine
    recorded that path. Same connection helper the Store's own reads use — not a second path
    derivation off `store.root`, which is how a console comes to read a file the engine never
    wrote.
    """
    try:
        with store._connect() as conn:  # noqa: SLF001 — the index row, for audit
            row = conn.execute(
                "SELECT * FROM dossiers WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return dict(row) if row is not None else None
    except (sqlite3.Error, OSError):  # a missing/locked index is "unreadable", never a crash
        return None


def _load_dossier(store, candidate_id: str) -> dict:
    """`{status, reason, path, data}` — `ok` | `missing` | `unreadable`, never an exception.

    `Store.get` raises `json.JSONDecodeError` on a torn file (`store.py:407`), which on a live
    tree happens exactly while the engine is writing. A console that 500s on that is a console
    that is down whenever the thing it watches is busy.
    """
    row = _index_row(store, candidate_id)
    path = str((row or {}).get("path") or "") or None
    try:
        data = store.get(candidate_id)
    except (ValueError, OSError) as exc:
        return {"status": "unreadable", "data": None, "path": path,
                "reason": f"dossier JSON did not parse ({type(exc).__name__}: {exc})"}
    if data is None:
        if row is None:
            return {"status": "missing", "data": None, "path": None,
                    "reason": "no row for this candidate_id in the store index"}
        return {"status": "unreadable", "data": None, "path": path,
                "reason": f"index row points at {path}, which is not on disk"}
    return {"status": "ok", "data": data, "path": path, "reason": ""}


def _source_view(s: dict) -> dict:
    """One retrieved passage: the QUOTE, the query that surfaced it, and where it came from."""
    return {
        "source_id": s.get("source_id"),
        "url": s.get("url"),
        "quote": s.get("text") or "",
        "query": s.get("query"),
        "published_at": s.get("published_at"),
        "fetched_at": s.get("fetched_at"),
        "retrieved_by": s.get("retrieved_by"),
        "archived_url": s.get("archived_url"),
    }


def _check_view(raw: dict, latency: dict) -> dict:
    """One check, classified. An OUTAGE carries no verdict and no confidence — by construction.

    This is §7.2 T2 expressed as a data shape rather than as a rendering convention: a surface
    cannot print `unverifiable, 0.0` for a failed call, because those fields are `None` and the
    reason for the null sits beside them. What the engine wrote as its fail-safe is preserved
    under `outage.fail_safe_placeholder` — visible for audit, impossible to mistake for a
    reading.
    """
    kind, why = classify_check(raw)
    sources = [_source_view(s) for s in (raw.get("sources") or []) if isinstance(s, dict)]
    view = {
        "kind": kind,
        "check_name": raw.get("check_name"),
        "provider": raw.get("provider") or None,
        "provisional": bool(raw.get("provisional")),
        "queries": list(raw.get("queries") or []),
        "query_source": raw.get("query_source") or None,
        "sources": sources,
        "n_sources": len(sources),
        "latency_ms": latency.get("ms"),
        "latency_null_reason": latency.get("null_reason", ""),
        "latency_provenance": latency.get("provenance", ""),
        "retrieval_providers": latency.get("providers", []),
        "cost_usd": None,
        "cost_null_reason": COST_NULL_REASON,
    }
    if kind == KIND_OUTAGE:
        view.update({
            "verdict": None,
            "confidence": None,
            "rationale": None,
            "citations": [],
            "untraceable_figures": None,
            "null_reason": "the verdict call failed; this check has no reading to report",
            "outage": {
                "why": why,
                "detected_by": ("retrieval_failed flag" if raw.get("retrieval_failed")
                                else "legacy fail-safe rationale"),
                "fail_safe_placeholder": {
                    "verdict": raw.get("verdict"),
                    "confidence": raw.get("confidence"),
                    "rationale": raw.get("rationale"),
                },
                "placeholder_note": ("what the engine wrote so the pipeline could continue. NOT "
                                     "a reading, and kill_filter.py:34 refuses to hard-fail on "
                                     "it"),
            },
        })
        return view
    view.update({
        "verdict": raw.get("verdict"),
        "confidence": raw.get("confidence"),
        "rationale": raw.get("rationale") or "",
        "citations": list(raw.get("citations") or []),
        "untraceable_figures": raw.get("untraceable_figures"),
        # `None` and `[]` differ and the difference is load-bearing (`models.py:312`): None means
        # the figure trace never ran, [] means it ran and found nothing. Never collapsed here.
        "figures_traced": raw.get("untraceable_figures") is not None,
        "degraded": bool(raw.get("degraded")),
        "null_reason": "",
        "outage": None,
    })
    return view


def _score_view(raw: Optional[dict], cfg) -> dict:
    """The score, as the engine stored it, with axis × weight shown and reconciliation checked.

    `score_failed` is the same class of defect as `retrieval_failed` one stage later (`models.py:
    399-403`): the all-zero scores are a fail-safe, not a 0/5 reading, so the composite renders as
    a null with a reason instead of a number an operator would compare to a threshold.
    """
    threshold = getattr(cfg, "min_composite_to_pass", None)
    weights = dict(getattr(cfg, "weights", None) or {})
    if not raw:
        return {"status": "absent", "composite": None, "threshold": threshold,
                "null_reason": "the dossier records no score (killed before scoring, or deferred)",
                "axes": []}
    scores = dict(raw.get("scores") or {})
    axes = [{"axis": a, "score": scores.get(a), "weight": weights.get(a),
             "contribution": (None if scores.get(a) is None or weights.get(a) is None
                              else round(float(scores[a]) * float(weights[a]), 4)),
             "justification": (raw.get("justification") or {}).get(a)}
            for a in sorted(set(scores) | set(weights))]
    stored = raw.get("composite")
    recomputed = sum(a["contribution"] for a in axes if a["contribution"] is not None) or 0.0
    if raw.get("score_failed"):
        return {"status": "failed", "composite": None, "threshold": threshold, "axes": axes,
                "null_reason": ("score_failed=True — the scoring call could not be computed and "
                                "the zeros are a fail-safe, NOT a 0/5 verdict (models.py:399)"),
                "fail_safe_placeholder": {"composite": stored, "scores": scores}}
    reconciles = stored is not None and abs(float(stored) - recomputed) < 0.01
    return {
        "status": "ok", "composite": stored, "threshold": threshold, "axes": axes,
        "null_reason": "",
        # The stored number stays authoritative. The recomputation exists ONLY to say whether the
        # weights on disk today still explain it — a lane/market override changes the weights
        # without touching the dossier, and a console silently recomputing would then print a
        # composite the engine never ruled on.
        "composite_recomputed": round(recomputed, 4),
        "reconciles": reconciles,
        "reconcile_note": "" if reconciles else (
            "the composite on disk is not Σ(score × weight) under TODAY's config weights — the "
            "run used a different lane/market weighting. The stored number is the one the gate "
            "actually applied"),
    }


def candidate_view(cfg, candidate_id: str, *, store=None, days: int = DEFAULT_DAYS,
                   directory: Optional[Path] = None, now: Optional[float] = None,
                   run_id: Optional[str] = None) -> dict:
    """One candidate's whole causal chain: generation → checks → gate → score → publish.

    Reads the dossier through `Store` and joins this candidate's audit rows for query-grain
    latency. A candidate whose dossier is missing or torn returns `status: unreadable` with the
    reason and NO invented fields — a chain rendered from half a file is worse than no chain.
    """
    store = store if store is not None else _store(cfg)
    doc = _load_dossier(store, candidate_id)
    row = _index_row(store, candidate_id)

    # The run this candidate was ruled in, found by its own audit rows. Absent is a REASON, not
    # an empty string: the audit log is day-partitioned, so an older dossier is out of range
    # rather than unlogged, and those two look identical if the null is silent.
    read = audit_rows(days=days, directory=directory, now=now)
    mine = [r for r in read["rows"]
            if str(r.get("candidate_id") or "") == candidate_id
            and (run_id is None or r.get("run_id") == run_id)]
    found_run = next((str(r.get("run_id")) for r in mine if r.get("run_id")), None)
    run_rows = ([r for r in read["rows"] if r.get("run_id") == found_run] if found_run else [])

    if doc["status"] != "ok":
        return {"candidate_id": candidate_id, "status": doc["status"], "reason": doc["reason"],
                "dossier_path": doc["path"], "index_row": row,
                "run": {"run_id": found_run, "null_reason": "" if found_run else
                        f"no audit row for this candidate in the last {days} day-file(s)"},
                "checks": [], "outages": [], "evidence_checks": []}

    d = doc["data"]
    by_query = _latency_by_query(run_rows)
    owners: Counter = Counter()
    for c in (d.get("checks") or []):
        for q in set(c.get("queries") or []):
            owners[q] += 1

    checks = [_check_view(c, _check_latency(list(c.get("queries") or []), by_query, owners))
              for c in (d.get("checks") or []) if isinstance(c, dict)]
    outages = [c for c in checks if c["kind"] == KIND_OUTAGE]
    evidence = [c for c in checks if c["kind"] == KIND_EVIDENCE]

    cand = d.get("candidate") or {}
    tags = cand.get("tags") or {}
    decision = d.get("decision")

    # THE 2102bacc WARNING. A terminal decision reached while some checks were outages is exactly
    # the shape of the dossier this requirement is named after: it reads as fully reasoned, and
    # the gate that fired was applied to readings that do not exist.
    integrity = ""
    if outages and str(decision) in ("kill", "pass"):
        integrity = (f"{len(outages)} of {len(checks)} checks were OUTAGES (the call failed), yet "
                     f"this dossier is a terminal {decision}. The honest verdict on an "
                     f"unevaluated check is 'come back to it' — see "
                     f"store/dossiers/2102bacc6dd75cf9.kill.json")

    return {
        "candidate_id": candidate_id,
        "status": "ok",
        "reason": "",
        "dossier_path": doc["path"],
        "run": {"run_id": found_run,
                "events": len(mine),
                "null_reason": "" if found_run else
                (f"no audit row for this candidate in the last {days} day-file(s) — the audit "
                 f"log is day-partitioned, so an older run is out of range, not missing")},
        "generation": {
            "created_at": d.get("created_at"),
            "model_version": d.get("model_version") or None,
            "provider_chain": d.get("provider_chain") or None,
            "seed_kind": tags.get("seed_kind"),
            "audience": tags.get("audience"),
            "persona": d.get("persona") or (row or {}).get("persona"),
            "ambition_tier": d.get("ambition_tier") or cand.get("ambition_tier"),
            "market": cand.get("market"),
            "structural_form": cand.get("structural_form"),
            "typicality": tags.get("typicality"),
            "refinements": len(cand.get("refinement_history") or []),
            "cost_usd": None,
            "cost_null_reason": COST_NULL_REASON,
        },
        "candidate": {k: cand.get(k) for k in
                      ("title", "one_liner", "hypothesis", "who_pays", "why_now",
                       "weak_monetisation", "automatability")},
        "checks": checks,
        "evidence_checks": evidence,
        "outages": outages,
        "outage_summary": {
            "any": bool(outages),
            "n": len(outages),
            "of": len(checks),
            "checks": [c["check_name"] for c in outages],
            "banner": ("" if not outages else
                       f"{len(outages)} of {len(checks)} checks did not run — the call failed. "
                       f"These are OUTAGE markers, not readings, and none of them is evidence "
                       f"for or against this idea."),
            "integrity_warning": integrity,
        },
        "adversarial": d.get("adversarial"),
        "gate": {
            "decision": decision,
            "gate_fired": d.get("gate_fired"),
            "reason": d.get("reason") or "",
            "provisional": bool(d.get("provisional")),
            "reverify_due_at": d.get("reverify_due_at"),
        },
        "score": _score_view(d.get("score"), cfg),
        "publish": {
            "status": d.get("publish_status"),
            "error": d.get("publish_error"),
            "null_reason": "" if d.get("publish_status") else (
                "the dossier records no publish attempt: only a PASS is published, and a "
                "provisional PASS never publishes (run.py:864)"),
            "blocked_by_provisional": bool(d.get("provisional")) and str(decision) == "pass",
        },
        "index_row": row,
    }


# --------------------------------------------------------------------------- #
# CLI — the same views for a surface that is not Python
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    """`python -m prospector.ops.runs --runs | --run <id> | --candidate <id>`."""
    import argparse

    from prospector.ops.readmodel import load_cfg

    ap = argparse.ArgumentParser(description="Per-run internals (R18)")
    ap.add_argument("--runs", action="store_true", help="list runs in the window")
    ap.add_argument("--run", default=None, help="one run_id")
    ap.add_argument("--candidate", default=None, help="one candidate_id")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--config", default=os.environ.get("PROSPECTOR_CONFIG") or None)
    args = ap.parse_args(argv)

    if args.runs or not (args.run or args.candidate):
        print(json.dumps(run_index(days=args.days), indent=2, default=str))
        return 0
    cfg = load_cfg(args.config)
    if args.run:
        print(json.dumps(run_view(cfg, args.run, days=args.days), indent=2, default=str))
    else:
        print(json.dumps(candidate_view(cfg, args.candidate, days=args.days),
                         indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

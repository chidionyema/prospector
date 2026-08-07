"""Self-diagnostics for filter calibration — so calibration is *watched*, not
hand-checked. Two tiers:

  1. calibration_alarms(store, cfg)  — FREE, no model calls. Reads the catalogue and
     flags calibration pathologies the moment they appear.
     Lane-aware: each alarm reports per-lane kill rates separately so a dominant
     gate in one lane is not masked by different patterns in another.

  2. run_calibration(cfg)            — uses the PRODUCTION failover chain against
     fixed golden evidence (deterministic, no live web). Returns discrimination
     + per-case expected-vs-actual gate confusion list + a pass/fail vs a floor.

Neither tier hand-pins a provider: the brain is whatever the config chain resolves to,
so diagnostics keep working when one provider's quota is exhausted (it just fails over).
"""
from __future__ import annotations

import copy
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .jsonl_atomic import append_jsonl
from .store import Store

# The six grounded checks, in kill-fast order (matches verify.py run order).
_CHECKS = ["pain_reality", "value_durability", "incumbency",
           "payer_solvency", "distribution", "legality"]


def _norm_dossier(d: Any) -> dict:
    """Normalise a Dossier (object OR on-disk dict) into a flat dict the batch
    diagnostic can read uniformly. Defensive: missing fields degrade to safe defaults."""
    if isinstance(d, dict):
        out = dict(d)
        sc = out.get("score")
        if sc is not None and not isinstance(sc, dict):
            out["score"] = {"composite": getattr(sc, "composite", None)}
        return out
    dec = getattr(d, "decision", None)
    sc = getattr(d, "score", None)
    cand = getattr(d, "candidate", None)
    checks = []
    for c in (getattr(d, "checks", None) or []):
        v = getattr(c, "verdict", None)
        checks.append({
            "check_name": getattr(c, "check_name", None),
            "verdict": getattr(v, "value", v),
            "confidence": getattr(c, "confidence", 0.0),
            "sources": list(getattr(c, "sources", []) or []),
            "provider": getattr(c, "provider", None),
            "provisional": getattr(c, "provisional", False),
        })
    return {
        "decision": getattr(dec, "value", dec),
        "gate_fired": getattr(d, "gate_fired", None),
        "provisional": getattr(d, "provisional", False),
        "score": {"composite": getattr(sc, "composite", None)} if sc else None,
        "candidate": {"title": getattr(cand, "title", None),
                      "market": getattr(cand, "market", "") or ""} if cand else {},
        "checks": checks,
    }


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), 3),
            "med": round(statistics.median(xs), 3),
            "max": round(max(xs), 3),
            "mean": round(statistics.mean(xs), 3)}


def _market_breakdown(ds: list[dict]) -> dict:
    """Decisions and grounding per market.

    Returned only when the batch actually spans markets or carries a market at all, so a
    single-market run's report is unchanged.
    """
    markets = {(x.get("candidate") or {}).get("market") or "" for x in ds}
    if not markets or markets == {""}:
        return {}

    out: dict[str, dict] = {}
    for market in sorted(markets):
        rows = [x for x in ds
                if ((x.get("candidate") or {}).get("market") or "") == market]
        checks = [c for x in rows for c in (x.get("checks") or [])]
        unverifiable = sum(1 for c in checks
                           if (c.get("verdict") or "").lower() == "unverifiable")
        empty = sum(1 for c in checks if not (c.get("sources") or []))
        dec = Counter((x.get("decision") or "?").lower() for x in rows)
        out[market or "(unset)"] = {
            "vetted": len(rows),
            "pass": dec.get("pass", 0),
            "kill": dec.get("kill", 0),
            "defer": dec.get("defer", 0),
            "checks": len(checks),
            "unverifiable_pct": round(100 * unverifiable / len(checks), 1) if checks else 0.0,
            "retrieval_empty_checks": empty,
            "kill_gates": dict(Counter(
                x.get("gate_fired") or "min_composite" for x in rows
                if (x.get("decision") or "").lower() == "kill").most_common()),
        }
    return out


def diagnose_batch(dossiers: list[Any], *, stage_counts: Optional[dict] = None,
                   usage: Any = None, cfg: Optional[Config] = None) -> dict:
    """Full-funnel diagnostic for ONE batch (one run_signal call).

    Pure: derives every stat from the batch's own dossiers + the optional top-of-funnel
    `stage_counts` (generated/dedup/prescreen drops, which dossiers don't carry). This is
    the per-run insight that ships WITH every generation (founder requirement 2026-06-22):
    where candidates die, how grounded each check was, how far from the PASS bar, on which
    brain, and at what token cost.
    """
    ds = [_norm_dossier(d) for d in dossiers]
    floor = float(getattr(getattr(cfg, "thresholds", None), "confidence_floor", 0.0) or 0.0)
    bar = float(getattr(getattr(cfg, "thresholds", None), "min_composite_to_pass", 3.2) or 3.2)

    # ── Decisions + gates ────────────────────────────────────────────────────
    dec = Counter((x.get("decision") or "?").lower() for x in ds)
    gates = Counter(x.get("gate_fired") or "min_composite"
                    for x in ds if (x.get("decision") or "").lower() == "kill")
    provisional = sum(1 for x in ds if x.get("provisional"))

    # ── Per-check verdict matrix + sources/confidence/provider ───────────────
    matrix: dict[str, Counter] = {c: Counter() for c in _CHECKS}
    src_dist: Counter = Counter()
    conf_by_verdict: dict[str, list[float]] = {"supported": [], "refuted": [], "unverifiable": []}
    providers: Counter = Counter()
    retrieval_failed = 0
    for x in ds:
        for c in (x.get("checks") or []):
            name = c.get("check_name") or "?"
            v = (c.get("verdict") or "").lower()
            if name in matrix:
                matrix[name][v] += 1
            n_src = len(c.get("sources") or [])
            src_dist[n_src] += 1
            if n_src == 0:
                retrieval_failed += 1
            if v in conf_by_verdict:
                conf_by_verdict[v].append(float(c.get("confidence") or 0.0))
            providers[c.get("provider") or "?"] += 1

    total_checks = sum(src_dist.values()) or 1
    unverif = sum(matrix[c].get("unverifiable", 0) for c in _CHECKS)

    # ── Composite distance to the PASS bar (only scored survivors carry one) ──
    comps = [x["score"]["composite"] for x in ds
             if x.get("score") and x["score"].get("composite") is not None]
    near_bar = sum(1 for c in comps if c >= bar - 0.5)

    # ── Closest-to-pass kills (actionable: what almost made it) ──────────────
    scored_kills = [(x["score"]["composite"], (x.get("candidate") or {}).get("title"))
                    for x in ds
                    if (x.get("decision") or "").lower() == "kill"
                    and x.get("score") and x["score"].get("composite") is not None]
    scored_kills.sort(reverse=True)
    passes = [(x.get("candidate") or {}).get("title") for x in ds
              if (x.get("decision") or "").lower() == "pass"]

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thresholds": {"confidence_floor": floor, "min_composite_to_pass": bar},
        # Aggregate numbers hide a dead market: 40% unverifiable across two markets can be
        # a healthy one averaged with one that grounds nothing. Break it out.
        "by_market": _market_breakdown(ds),
        "funnel": stage_counts or {"note": "top-of-funnel counts unavailable (post-hoc run)"},
        "decisions": {"pass": dec.get("pass", 0), "kill": dec.get("kill", 0),
                      "defer": dec.get("defer", 0), "vetted": len(ds),
                      "provisional": provisional},
        "kill_gates": dict(gates.most_common()),
        "verdict_matrix": {c: dict(matrix[c]) for c in _CHECKS},
        "unverifiable_pct": round(100 * unverif / total_checks, 1),
        "sources_per_check": dict(sorted(src_dist.items())),
        "retrieval_failed_checks": retrieval_failed,
        "confidence": {v: _stats(xs) for v, xs in conf_by_verdict.items()},
        "providers": dict(providers.most_common()),
        "composite": {**_stats(comps), "near_bar_within_0.5": near_bar},
        "closest_kills": scored_kills[:5],
        "passes": passes,
        "usage": usage,
    }


def render_batch_diagnostics(r: dict) -> str:
    """Human-readable per-batch funnel report."""
    L = ["═" * 72, f"BATCH DIAGNOSTICS  ·  {r.get('ts','')}", "═" * 72]
    f = r.get("funnel") or {}
    if "note" not in f:
        L.append("── Funnel (top → bottom) ──")
        order = ["generated", "dedup_dropped", "rejection_fastpath", "prescreen_in",
                 "prescreened_out", "novelty_selected", "vetted"]
        L.append("  " + "  ".join(f"{k}={f[k]}" for k in order if k in f))
    d = r.get("decisions", {})
    L.append(f"── Decisions ──  PASS {d.get('pass',0)} · KILL {d.get('kill',0)} · "
             f"DEFER {d.get('defer',0)} · provisional {d.get('provisional',0)} "
             f"(of {d.get('vetted',0)} vetted)")
    if r.get("kill_gates"):
        L.append("  kill gates: " + ", ".join(f"{k}={v}" for k, v in r["kill_gates"].items()))
    by_market = r.get("by_market") or {}
    if len(by_market) > 1:
        L.append("── Per market (aggregates above span ALL markets) ──")
        for market, m in by_market.items():
            L.append(f"  {market:<10} vetted {m['vetted']:3d} · PASS {m['pass']:2d} "
                     f"KILL {m['kill']:2d} DEFER {m['defer']:2d} · "
                     f"unverifiable {m['unverifiable_pct']}% · "
                     f"retrieval-empty {m['retrieval_empty_checks']}")
    L.append(f"── Grounding ──  unverifiable {r.get('unverifiable_pct')}%  ·  "
             f"sources/check {r.get('sources_per_check')}  ·  "
             f"retrieval-empty checks {r.get('retrieval_failed_checks')}")
    L.append("── Per-check verdicts (supported / refuted / unverifiable) ──")
    for c in _CHECKS:
        m = r.get("verdict_matrix", {}).get(c, {})
        L.append(f"  {c:18s} sup {m.get('supported',0):2d} | ref {m.get('refuted',0):2d} | "
                 f"unv {m.get('unverifiable',0):2d}")
    cf = r.get("confidence", {})
    def _c(v):
        s = cf.get(v, {})
        return f"{v} med={s.get('med','-')} (n={s.get('n',0)})" if s.get("n") else f"{v} n=0"
    L.append("── Confidence ──  " + "  ·  ".join(_c(v) for v in ("supported", "refuted", "unverifiable")))
    comp = r.get("composite", {})
    bar = r.get("thresholds", {}).get("min_composite_to_pass", 3.2)
    if comp.get("n"):
        L.append(f"── Composite (need ≥{bar}) ──  n={comp['n']} min={comp.get('min')} "
                 f"med={comp.get('med')} max={comp.get('max')} · within-0.5-of-bar={comp.get('near_bar_within_0.5')}")
    else:
        L.append(f"── Composite (need ≥{bar}) ──  0 candidates reached scoring (all died kill-fast)")
    L.append("── Brain ──  " + ", ".join(f"{k}={v}" for k, v in (r.get("providers") or {}).items()))
    if r.get("closest_kills"):
        L.append("── Closest-to-pass kills ──")
        for comp_v, title in r["closest_kills"]:
            L.append(f"  {comp_v:.2f}  {title}")
    if r.get("passes"):
        L.append("── PASSES ──  " + "; ".join(t for t in r["passes"] if t))
    if r.get("usage"):
        L.append(f"── Cost ──  {r['usage']}")
    return "\n".join(L)


def persist_batch_diagnostics(report: dict, store: Store) -> Path:
    """Append the batch diagnostic to a jsonl trail and overwrite the latest text report.
    Lives under store/scheduler/ next to ticks.jsonl so the operator finds it in one place."""
    base = store._dossier_dir.parent / "scheduler"
    base.mkdir(parents=True, exist_ok=True)
    # R3: single O_APPEND write + fsync (see prospector/jsonl_atomic.py). Diagnostic reports are
    # the largest records written under store/scheduler/, so they are also the likeliest to be
    # caught half-written by a reader running concurrently with the daemon.
    append_jsonl(base / "batch_diagnostics.jsonl", report)
    (base / "DIAGNOSTICS_LATEST.txt").write_text(render_batch_diagnostics(report), encoding="utf-8")
    return base

# An alarm is {level: "alarm"|"warn", code, message, lane: Optional[str]}
# lane=None means the alarm spans the whole catalogue; lane="X" means it is lane-specific.
Alarm = dict[str, Any]


def _gate_map_for_lane(cfg: Config, lane: Optional[str]) -> dict[str, list[str]]:
    """Return the gate map for a specific lane (or the default gates if no lane set)."""
    if lane and lane in (cfg.lanes or {}):
        lane_cfg = cfg.lanes[lane]
        gates: list[dict[str, Any]] = lane_cfg.get("hard_gates") or []
    else:
        gates = cfg.hard_gates
    out: dict[str, list[str]] = {}
    for g in gates:
        for k, v in g.items():
            if k != "adversarial_decisive":
                out[k] = list(v)
    return out


def calibration_alarms(store: Store, cfg: Config, *,
                      dominance_threshold: float = 0.85,
                      min_sample: int = 5) -> list[Alarm]:
    """Flag calibration pathologies from the catalogue. No model calls.

    All alarms are lane-aware: if the catalogue mixes ambition tiers, each lane's
    kill-rate and gate distribution is reported separately so a dominant gate in
    one lane does not mask different patterns in another.
    """
    alarms: list[Alarm] = []

    # ── Catalogue-wide metrics (all decisions) ───────────────────────────────────
    all_rows = store.all()
    if not all_rows:
        return alarms

    # ── Per-lane breakdown ─────────────────────────────────────────────────
    # Group rows by ambition_tier (indexed in the SQLite store).
    by_lane: dict[str, list[dict]] = {}
    for r in all_rows:
        lane = r.get("ambition_tier") or ""
        by_lane.setdefault(lane, []).append(r)

    # Also check the raw dossier JSON for any that missed the index (backwards compat).
    # Load from JSON only for lanes with no indexed data.
    indexed_ids = {r["candidate_id"] for r in all_rows}
    for f in store._dossier_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            cid = d.get("candidate", {}).get("candidate_id", "")
            if cid in indexed_ids:
                continue
            lane = d.get("candidate", {}).get("ambition_tier", "") or ""
            by_lane.setdefault(lane, []).append(d)
        except Exception:
            pass

    for lane, rows in sorted(by_lane.items()):
        alarms.extend(_lane_alarms(rows, lane, cfg, dominance_threshold, min_sample))

    # ── Per-market breakdown ───────────────────────────────────────────────
    # Keyed separately from lanes: a market failing is an EVIDENCE problem (the engine
    # cannot see that jurisdiction), whereas a lane failing is a CALIBRATION problem.
    # Averaged together they cancel out and neither is visible.
    by_market: dict[str, list[dict]] = {}
    for r in all_rows:
        by_market.setdefault(r.get("market") or "", []).append(r)
    if len([m for m in by_market if m]) > 1:
        for market, rows in sorted(by_market.items()):
            if market:
                alarms.extend(_market_alarms(rows, market, cfg, min_sample))

    # ── Catalogue-wide structural quality alarms ───────────────────────────────
    # These span all lanes and flag generation quality, not calibration.
    alarms.extend(_generation_quality_alarms(store))

    # ── Persona Drift / Consensus Collapse (Part 16 principal upgrade) ───────
    # Measures whether personas are actually providing distinct viewpoints.
    from .adaptive import calculate_persona_drift
    drifts = calculate_persona_drift(store)
    for p_name, drift_rate in drifts.items():
        if drift_rate < 0.1: # Alarming if disagreement is < 10%
            alarms.append({
                "level": "warn", "code": "consensus_collapse",
                "message": (
                    f"Persona {p_name!r} agrees with primary 90%+ of the time. "
                    f"Analytical multi-tenancy is failing; the personas are not "
                    f"distinct enough or prompts need sharpening."
                ),
                "lane": None,
                "persona": p_name,
                "drift_rate": drift_rate
            })

    # ── Generative Alpha / Quality Decay (Part 16 principal upgrade) ────────
    # Measures the rolling average of composite scores for PASS dossiers.
    alpha = calculate_generative_alpha(store)
    if alpha.get("rolling_avg", 0) < 3.0 and alpha.get("n", 0) >= 5:
        alarms.append({
            "level": "alarm", "code": "quality_decay",
            "message": (
                f"Rolling alpha (avg score of passes) has dropped to {alpha['rolling_avg']:.2f}. "
                f"Generator is producing lower-value ideas. Check exploration levels "
                f"and recent failure mode feedback."
            ),
            "lane": None,
            "alpha": alpha["rolling_avg"]
        })

    return alarms


def calculate_generative_alpha(store: Store, window: int = 50) -> dict[str, Any]:
    """Calculate rolling quality metrics for passed ideas (Generative Alpha)."""
    rows = store.all(decision="pass")
    if not rows:
        return {"n": 0, "rolling_avg": 0.0, "axis_averages": {}}

    # Most recent first
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    
    n = len(recent)
    avg = sum(float(r.get("composite") or 0) for r in recent) / n
    
    # Per-axis averages (requires loading full dossiers for axis breakdown)
    # We only sample the top 10 to keep it fast.
    axis_sums = Counter()
    axis_n = 0
    for r in recent[:10]:
        d = store.get(r["candidate_id"])
        if d and d.get("score") and d["score"].get("scores"):
            for axis, val in d["score"]["scores"].items():
                axis_sums[axis] += float(val)
            axis_n += 1
            
    axis_avgs = {ax: total / axis_n for ax, total in axis_sums.items()} if axis_n else {}

    return {
        "n": n,
        "rolling_avg": round(avg, 2),
        "axis_averages": axis_avgs
    }


def calculate_yield(store: Store, window: int = 50) -> float:
    """Calculate the Exploration-Yield Ratio.
    
    Yield = (Advisory Board Passes) / (Avg Exploration Level).
    High exploration with low pass rate signals 'hallucinatory noise'.
    """
    rows = store.all()
    if len(rows) < 10:
        return 0.0
    
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent = rows[:window]
    
    passes = sum(1 for r in recent if r.get("decision") == "pass")
    # This is a proxy: higher survival = higher yield
    return passes / len(recent)


def _market_alarms(rows: list[dict], market: str, cfg: Config,
                   min_sample: int) -> list[Alarm]:
    """Alarms for one market. A market failing means the engine cannot SEE that
    jurisdiction — the fix is evidence terrain (authority domains, query exemplars),
    never a lower bar."""
    alarms: list[Alarm] = []
    if len(rows) < min_sample:
        return alarms

    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    n_pass, n_kill, n_defer = dec.get("pass", 0), dec.get("kill", 0), dec.get("defer", 0)
    ruled = n_pass + n_kill

    if ruled >= min_sample and n_pass == 0:
        alarms.append({
            "level": "alarm", "code": "market_zero_yield",
            "message": (
                f"[{market}] 0 PASS across {ruled} ruled candidates. This market's "
                f"evidence terrain is likely wrong (authority domains, search region, "
                f"query exemplars in prompts/markets/{market}/) — fix the grounding, "
                f"not the bar."),
            "lane": None, "market": market, "n_ruled": ruled, "n_pass": n_pass,
        })

    if rows and n_defer / len(rows) >= 0.5:
        alarms.append({
            "level": "warn", "code": "market_defer_rate",
            "message": (
                f"[{market}] {n_defer}/{len(rows)} candidates DEFERRED — that is an "
                f"infrastructure signal, not a market signal. Re-run `vet --resume` "
                f"before reading anything into this market's numbers."),
            "lane": None, "market": market, "defer_rate": n_defer / len(rows),
        })

    degraded = sum(1 for r in rows if r.get("retrieval_degraded"))
    if rows and degraded / len(rows) >= 0.3:
        alarms.append({
            "level": "warn", "code": "market_retrieval_degraded",
            "message": (
                f"[{market}] {degraded}/{len(rows)} candidates vetted with degraded "
                f"retrieval. Verdicts here rest on thin evidence."),
            "lane": None, "market": market,
        })

    try:
        if cfg.market_status(market) != "open":
            alarms.append({
                "level": "alarm", "code": "market_not_open",
                "message": (
                    f"[{market}] {len(rows)} dossier(s) exist but the market is "
                    f"{cfg.market_status(market)}. Either a probe run leaked into the "
                    f"catalogue or the readiness gate was bypassed."),
                "lane": None, "market": market,
            })
    except Exception:  # noqa: BLE001 — an unconfigured market simply has no status
        pass

    return alarms


def _lane_alarms(rows: list[dict], lane: str, cfg: Config,
                  dominance_threshold: float, min_sample: int) -> list[Alarm]:
    """Compute alarms for one lane. Returns a list (may be empty)."""
    alarms: list[Alarm] = []
    n = len(rows)
    if n < min_sample:
        return alarms  # not enough data to judge this lane

    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    n_pass = dec.get("pass", 0)
    n_kill = dec.get("kill", 0)
    ruled = n_pass + n_kill  # defers never reached a verdict
    kill_rate = n_kill / ruled if ruled else 0.0
    lane_label = f"[{lane}] " if lane else "[all] "

    # ── zero-yield: nothing survives over a meaningful sample ──────────────
    if ruled >= min_sample and n_pass == 0:
        # NOT a calibration bug: check whether generation is the problem first.
        # If form diversity is low and the dominant gate is value_durability, the
        # generator is producing wrappers that the filter correctly kills.
        forms = _structural_forms_in(rows)
        gates = Counter(r.get("gate_fired") or r.get("gate_fired") or "min_composite"
                       for r in rows if (r.get("decision") or "").lower() == "kill")
        top_gate = gates.most_common(1)[0] if gates else (None, 0)
        vd_share = gates.get("value_durability", 0) / n_kill if n_kill else 0.0
        low_form_diversity = len(forms) <= 2 and n_kill >= 3
        if vd_share >= 0.7 and low_form_diversity:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates — "
                f"but {top_gate[0]!r} fired {vd_share:.0%} of kills and only "
                f"{len(forms)} structural form(s) seen. "
                f"Root cause is GENERATION QUALITY (generator keeps producing the "
                f"same dead shape), not calibration. Fix the signal/diversity axis."
            )
        elif vd_share >= 0.5:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates. "
                f"value_durability dominates ({vd_share:.0%} of kills). "
                f"Possible generator monoculture or genuine selectivity problem. "
                f"Check signal diversity and anti-obvious rules."
            )
        else:
            message = (
                f"0 PASS across {ruled} {lane_label}ruled candidates — "
                f"investigate whether this reflects genuine selectivity or "
                f"a calibration regression."
            )
        alarms.append({"level": "alarm", "code": "zero_yield",
                      "message": message, "lane": lane or None,
                      "kill_rate": kill_rate, "n_ruled": ruled, "n_pass": n_pass})

    # ── gate-dominance: one gate executes almost all kills ─────────────────
    kill_gates = Counter(r.get("gate_fired") or r.get("gate_fired") or "min_composite"
                        for r in rows if (r.get("decision") or "").lower() == "kill")
    if n_kill >= min_sample and kill_gates:
        top_gate, top_n = kill_gates.most_common(1)[0]
        share = top_n / n_kill
        # Only alarm if this gate is NOT configured to dominate this lane
        # (i.e., it's dominating by accident, not by design).
        expected_gates = set(_gate_map_for_lane(cfg, lane or None).keys())
        if top_gate not in expected_gates and share >= dominance_threshold:
            alarms.append({
                "level": "alarm", "code": "gate_dominance",
                "message": (
                    f"{lane_label}{top_gate!r} fired {top_n}/{n_kill} kills "
                    f"({share:.0%}) — exceeds the {dominance_threshold:.0%} threshold "
                    f"and is not the expected dominant gate for this lane. "
                    f"It may be masking other gate failures under kill-fast."
                ),
                "lane": lane or None,
                "top_gate": top_gate,
                "share": share,
                "n_kill": n_kill,
            })

    # ── dead-gate: a configured gate has never fired in this lane ─────────
    configured = set(_gate_map_for_lane(cfg, lane or None).keys())
    fired = {g for g in kill_gates if g in configured}
    dead = configured - fired
    if ruled >= min_sample and dead:
        # Distinguish intentionally-non-decisive gates from truly dead ones.
        # legality and pain_reality in venture lane are often unverifiable — not dead.
        quiet_ok = {"legality", "pain_reality"} if not lane else set()
        genuinely_dead = dead - quiet_ok
        if genuinely_dead:
            alarms.append({
                "level": "warn", "code": "dead_gate",
                "message": (
                    f"{lane_label}configured gate(s) never fired: "
                    f"{sorted(genuinely_dead)} — untested discrimination "
                    f"(may be unreachable behind kill-fast)."
                ),
                "lane": lane or None,
                "dead_gates": sorted(genuinely_dead),
            })

    return alarms


def _structural_forms_in(rows: list[dict]) -> set[str]:
    """Extract structural forms seen in a set of rows (index or JSON)."""
    forms: set[str] = set()
    for r in rows:
        # Canonical first-class field (dossier index column + candidate field).
        # The legacy tags["form:*"] scan below is back-compat for pre-field rows.
        sform = r.get("structural_form")
        if sform:
            forms.add(str(sform))
        cand = r.get("candidate")
        if isinstance(cand, dict) and cand.get("structural_form"):
            forms.add(str(cand["structural_form"]))

        tags = r.get("tags", {})
        if isinstance(tags, dict):
            for k in tags:
                if k.startswith("form:"):
                    v = tags[k]
                    forms.add(str(v) if v else k.replace("form:", ""))
        elif isinstance(tags, list):
            for item in tags:
                if isinstance(item, str) and item.startswith("form:"):
                    forms.add(item.replace("form:", ""))
    return forms


def _generation_quality_alarms(store: Store) -> list[Alarm]:
    """Flag generation-quality problems that are NOT calibration bugs.

    These are observable from the catalogue alone without any model calls.
    """
    alarms: list[Alarm] = []
    rows = store.all()
    if len(rows) < 5:
        return alarms

    # ── Structural form diversity ───────────────────────────────────────────
    forms = _structural_forms_in(rows)
    if len(forms) <= 2 and len(rows) >= 10:
        alarms.append({
            "level": "warn", "code": "low_form_diversity",
            "message": (
                f"Only {len(forms)} structural form(s) across {len(rows)} candidates — "
                f"forms: {sorted(forms)}. "
                f"The generator may be collapsing to one shape. "
                f"Check signal diversity and the structural-form rotation logic."
            ),
            "lane": None,
            "forms": sorted(forms),
            "n_candidates": len(rows),
        })

    # ── No PASS candidates across the whole catalogue ──────────────────────
    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    if dec["pass"] == 0 and len(rows) >= 10:
        # Check whether it's a generation problem vs. a filter problem.
        gates = Counter(r.get("gate_fired") or "min_composite"
                       for r in rows if (r.get("decision") or "").lower() == "kill")
        top_gate = gates.most_common(1)[0] if gates else (None, 0)
        alarms.append({
            "level": "alarm", "code": "catalogue_zero_pass",
            "message": (
                f"Entire catalogue ({len(rows)} candidates) has 0 PASS — "
                f"top kill gate: {top_gate[0]!r} ({top_gate[1]} kills). "
                f"Check: (1) Is the signal producing the right diversity of ideas? "
                f"(2) Are the anti-obvious rules specific enough? "
                f"(3) Is value_durability killing on silence (unverifiable)? "
                f"This is a generation + calibration joint diagnostic — both axes need review."
            ),
            "lane": None,
            "n": len(rows),
            "top_gate": top_gate[0],
        })

    return alarms


def render_alarms(alarms: list[Alarm]) -> str:
    if not alarms:
        return "  ✓ calibration: no pathologies detected"
    glyph = {"alarm": "🚨", "warn": "⚠️"}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_lane: dict[str | None, list[Alarm]] = {}
    for a in alarms:
        by_lane.setdefault(a.get("lane"), []).append(a)
    lines = [f"  diagnostics @ {now}"]
    for lane_key, lane_alarms in sorted(by_lane.items(), key=lambda x: (x[0] is not None, x[0] or "")):
        if lane_key:
            lines.append(f"  ── lane: {lane_key!r} ──")
        for a in lane_alarms:
            g = glyph.get(a.get("level", "warn"), "•")
            lines.append(f"  {g} [{a['code']}] {a['message']}")
    return "\n".join(lines)


def run_calibration(cfg: Config,
                    golden_set_path: str = "fixtures/golden_set.json",
                    golden_fixtures_path: str = "fixtures/golden_fixtures.json",
                    floor: float = 0.75) -> dict[str, Any]:
    """Run the golden set through the PRODUCTION brain chain against fixed evidence.

    Returns {discrimination, floor, ok, cases:[{idea, expected, actual,
    expected_gate, actual_gate, passed, lane}].  Deterministic grounding (fixtures), so the
    only variable under test is the brain + prompts + gate config.
    """
    from .golden import run_golden_set
    from .operator import make_operator
    from .retrieval import make_provider

    diag_cfg = copy.deepcopy(cfg)
    diag_cfg.retrieval.provider = "fixture"
    diag_cfg.retrieval.cache = False

    fixtures = json.loads(Path(golden_fixtures_path).read_text(encoding="utf-8"))
    op = make_operator(diag_cfg)
    search = make_provider(diag_cfg, fixtures=fixtures)

    discrimination, results = run_golden_set(op, search, diag_cfg, golden_set_path)
    cases = [{
        "idea": r.get("idea") or r.get("title"),
        "expected": r.get("expected_decision"),
        "actual": r.get("actual_decision"),
        "expected_gate": r.get("expected_gate"),
        "actual_gate": r.get("actual_gate"),
        "passed": r.get("passed"),
        "lane": r.get("lane", ""),
    } for r in results]
    return {"discrimination": discrimination, "floor": floor,
            "ok": discrimination >= floor, "cases": cases}


def diagnostics_data(store, cfg, golden_dir: str = "store/golden_runs/",
                     floor: float = 0.75) -> dict[str, Any]:
    """Return structured diagnostics for the Control Center UI.


    Combines calibration alarms (free, no model call) with the latest golden-set
    run results and the trend of discrimination scores over time.

    Returns: {alarms: [Alarm],
              latest_golden: {discrimination, floor, ok, cases} | None,
              golden_trend: [{ts, discrimination, ok, operator}]}
    """
    alarms = calibration_alarms(store, cfg)

    # ── Latest golden run ─────────────────────────────────────────────────
    golden_path = Path(golden_dir)
    latest_golden: dict[str, Any] | None = None
    if golden_path.exists():
        runs = sorted(golden_path.glob("*.json"), reverse=True)
        if runs:
            try:
                latest = json.loads(runs[0].read_text(encoding="utf-8"))
                latest_golden = latest
            except Exception:
                pass

    # ── Golden discrimination trend ──────────────────────────────────────
    golden_trend: list[dict[str, Any]] = []
    if golden_path.exists():
        for f in sorted(golden_path.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                golden_trend.append({
                    "filename": f.name,
                    "ts": d.get("ts") or f.stat().st_mtime,
                    "discrimination": d.get("discrimination"),
                    "floor": d.get("floor", floor),
                    "ok": d.get("ok"),
                    "operator": d.get("operator"),
                })
            except Exception:
                pass
    golden_trend.sort(key=lambda x: x.get("ts", 0), reverse=True)

    return {
        "alarms": alarms,
        "latest_golden": latest_golden,
        "golden_trend": golden_trend,
    }


def run_diagnostics(store, cfg, golden_dir: str = "store/golden_runs/",
                       floor: float = 0.75) -> str:
    """Run calibration harness (with model calls) + return human-readable diagnostics.


    This is the full diagnostic: alarms (free) + golden-set harness (paid).
    For the UI use diagnostics_data() instead.
    """
    data = diagnostics_data(store, cfg, golden_dir, floor)
    alarm_text = render_alarms(data["alarms"])
    parts = ["═" * 72, "CALIBRATION + DIAGNOSTICS", "═" * 72,
             "\n── Calibration alarms ──\n" + alarm_text]
    if data["latest_golden"]:
        parts.append("\n── Golden set (latest) ──\n"
                     + render_calibration(data["latest_golden"]))
    return "\n".join(parts)


def render_calibration(report: dict[str, Any]) -> str:
    out = ["═" * 72, "CALIBRATION HARNESS (real brain · fixed golden evidence)", "═" * 72,
           f"  discrimination   {report['discrimination']:.0%}   (floor {report['floor']:.0%})  "
           f"{'✅ OK' if report['ok'] else '🚨 REGRESSION'}", ""]
    for c in report["cases"]:
        mark = "✅" if c["passed"] else "❌"
        lane_tag = f"  [{c.get('lane', '')}]" if c.get('lane') else ""
        gate_diff = (f"  gate exp={c.get('expected_gate', '')} got={c.get('actual_gate', '')}"
                     if not c["passed"] else "")
        out.append(f"  {mark} expect={c['expected']:<4} got={c['actual']:<4}{lane_tag}  {c['idea']}{gate_diff}")
    return "\n".join(out)

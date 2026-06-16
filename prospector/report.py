"""Human-readable reporting over the catalogue + audit log.

The engine records everything: dossiers in store/, token/cost/latency in
store/prospector.jsonl.  This module turns that state into five views:

  - catalogue : every vetted idea grouped by decision + lane.
  - metrics   : decision counts, kill rate, which gate kills most, per-lane breakdown.
  - costs     : lifetime $ spend + token usage + slowest operations (errors excluded).
  - quality   : generation quality — form diversity, audience spread, dedup rate.
  - trend     : rolling 7/30/90d cohort metrics (kill rate, gate distribution trend).

All five read on-disk state only; safe to run any time, mutates nothing.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from .store import Store

_GLYPH = {"pass": "✅", "kill": "🛑", "defer": "⏸️"}
_ORDER = {"pass": 0, "defer": 1, "kill": 2}


# ---------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------
def catalogue_report(store: Store, decision: Optional[str] = None) -> str:
    rows = store.all(decision)
    if not rows:
        scope = f" with decision={decision!r}" if decision else ""
        return (f"No vetted ideas in the catalogue{scope} yet. "
                "Run `vet` or `signal` first.")

    rows.sort(key=lambda r: (_ORDER.get((r.get("decision") or "").lower(), 9),
                             -(r.get("composite") or 0)))
    by_dec: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_dec[(r.get("decision") or "?").lower()].append(r)

    out: list[str] = ["═" * 72, "PROSPECTOR CATALOGUE", "═" * 72]
    for dec in ("pass", "defer", "kill"):
        items = by_dec.get(dec)
        if not items:
            continue
        out.append(f"\n{_GLYPH.get(dec, '•')} {dec.upper()}  ({len(items)})")
        out.append("─" * 72)
        for r in items:
            title = r.get("title") or "(untitled)"
            lane = r.get("ambition_tier") or ""
            if dec == "pass":
                tail = f"composite={r.get('composite', 0):.2f}"
                tail += f"  [{lane}]" if lane else ""
            elif dec == "defer":
                tail = "retrieval unavailable — re-vet"
            else:
                tail = f"gate={r.get('gate_fired') or 'min_composite'}"
                tail += f"  [{lane}]" if lane else ""
            out.append(f"  {title}")
            out.append(f"      {tail}   id={r.get('candidate_id')}")
    out.append("")
    out.append(f"Full dossier JSON: store/dossiers/<id>.<decision>.json")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# metrics (per-lane truth-loop health)
# ---------------------------------------------------------------------------
def metrics_report(store: Store) -> str:
    rows = store.all()
    if not rows:
        return "No vetted ideas yet — no metrics to report."
    n = len(rows)
    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    vetted = dec["pass"] + dec["kill"]
    kill_rate = (dec["kill"] / vetted * 100) if vetted else 0.0
    pass_rate = (dec["pass"] / vetted * 100) if vetted else 0.0

    out = ["═" * 72, "TRUTH-LOOP METRICS", "═" * 72,
            f"  total dossiers       {n}",
            f"  ✅ pass              {dec['pass']}  ({pass_rate:.1f}% of vetted)",
            f"  🛑 kill              {dec['kill']}  ({kill_rate:.1f}% of vetted)",
            f"  ⏸️  defer             {dec['defer']}  (retrieval unavailable, not a verdict)",
            ""]

    # ── Per-lane breakdown ────────────────────────────────────────────────
    by_lane: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        lane = r.get("ambition_tier") or "(unset)"
        by_lane[lane].append(r)

    lanes_with_data = {k: v for k, v in sorted(by_lane.items()) if len(v) >= 2}
    if lanes_with_data:
        out.append("  PER-LANE BREAKDOWN:")
        out.append("  " + "─" * 50)
        for lane, lane_rows in lanes_with_data.items():
            l_pass = sum(1 for r in lane_rows if (r.get("decision") or "").lower() == "pass")
            l_kill = sum(1 for r in lane_rows if (r.get("decision") or "").lower() == "kill")
            l_ruled = l_pass + l_kill
            l_kr = l_kill / l_ruled * 100 if l_ruled else 0.0
            forms = _structural_forms(lane_rows)
            gates = Counter(r.get("gate_fired") or "min_composite"
                           for r in lane_rows if (r.get("decision") or "").lower() == "kill")
            top = gates.most_common(1)
            top_str = f"{top[0][0]} ({top[0][1]})" if top else "none"
            out.append(
                f"  {lane:<20} n={len(lane_rows):>3}  "
                f"pass={l_pass}  kill={l_kill} ({l_kr:.0f}%)  "
                f"forms={len(forms)}  top_gate={top_str}"
            )
        out.append("")

    # ── Kill gate distribution ──────────────────────────────────────────
    gates = Counter(r.get("gate_fired") or "min_composite"
                    for r in rows if (r.get("decision") or "").lower() == "kill")
    if gates:
        out.append("  KILL GATE DISTRIBUTION:")
        out.append("  " + "─" * 50)
        for gate, c in gates.most_common():
            bar = "█" * round(c / max(gates.values()) * 24)
            out.append(f"  {gate:<22} {c:>3}  {bar}")

    # ── Search & Grounding ──────────────────────────────────────────────
    retrieval_fail = sum(1 for r in rows if r.get("retrieval_failed"))
    degraded = sum(1 for r in rows if r.get("degraded"))
    
    out.append("")
    out.append("  SEARCH & GROUNDING:")
    out.append("  " + "─" * 50)
    out.append(f"  total search outages  {retrieval_fail}  ({retrieval_fail/n*100:.1f}%)")
    out.append(f"  degraded (local) runs {degraded}  ({degraded/n*100:.1f}%)")
    
    return "\n".join(out)


# ---------------------------------------------------------------------------
# generation quality (what the generator produces, not what the filter lets through)
# ---------------------------------------------------------------------------
def generation_quality_report(store: Store) -> str:
    """Measure generation quality independently of the filter.

    This answers: is the generator producing diverse ideas, or collapsing to one shape?
    Runs without any model calls — pure catalogue analysis.
    """
    rows = store.all()
    if not rows:
        return "No vetted ideas yet — nothing to measure generation quality from."

    # ── Structural form coverage ─────────────────────────────────────────
    forms = _structural_forms(rows)
    n = len(rows)

    # ── Audience coverage ───────────────────────────────────────────────
    audiences = Counter()
    for r in rows:
        tags = r.get("tags", {})
        if isinstance(tags, dict):
            aud = tags.get("audience")
            if aud:
                audiences[aud] += 1
        elif isinstance(tags, list):
            for item in tags:
                if isinstance(item, dict) and item.get("type") == "audience":
                    audiences[item.get("value", "")] += 1

    # ── Prescreen rate from audit log ────────────────────────────────────
    prescreen_reject = 0
    prescreen_keep = 0
    jsonl_path = store._root / "prospector.jsonl"
    if jsonl_path.exists():
        for line in jsonl_path.read_text().splitlines():
            try:
                d = json.loads(line)
                msg = d.get("message", "")
                if "PRESCREENED OUT" in msg or "prescreened out" in msg.lower():
                    prescreen_reject += 1
                elif "Prescreen kept" in msg:
                    prescreen_keep += 1
            except Exception:
                pass

    prescreen_total = prescreen_reject + prescreen_keep
    prescreen_reject_pct = (prescreen_reject / prescreen_total * 100
                             if prescreen_total else 0.0)

    out = ["═" * 72, "GENERATION QUALITY (catalogue analysis, no model calls)", "═" * 72]
    out.append(f"  candidates vetted       {n}")
    out.append(f"  structural forms      {len(forms)} seen  {sorted(forms) if forms else 'none'}")
    out.append(f"  audience personas     {len(audiences)} seen")
    for aud, cnt in audiences.most_common(5):
        out.append(f"    {aud:<40} {cnt}")
    out.append("")

    if prescreen_total:
        out.append(f"  prescreen pass rate   {100 - prescreen_reject_pct:.0f}%  "
                   f"({prescreen_keep}/{prescreen_total}; "
                   f"{prescreen_reject} rejected)")
    else:
        out.append("  prescreen data        (audit log not available)")

    # Dedup rate: how many generated candidates were near-duplicates?
    # (store doesn't track this — estimate from structural form duplication)
    if len(forms) == 1 and n >= 10:
        out.append("")
        out.append("  ⚠️  WARNING: only 1 structural form across all candidates — "
                   "generator may be collapsing to one shape.")
    elif len(forms) <= 2 and n >= 15:
        out.append("")
        out.append(f"  ⚠️  Low form diversity: only {len(forms)} forms across {n} candidates.")
        out.append("     Check signal diversity and the anti-obvious rules.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# trend (rolling cohort analysis)
# ---------------------------------------------------------------------------
def trend_report(store: Store, windows: tuple[int, ...] = (7, 30, 90)) -> str:
    """Rolling cohort metrics over 7/30/90-day windows.

    Cumulative totals hide whether the kill rate is improving or worsening.
    Rolling windows show the trend.
    """
    rows = store.all()
    if not rows:
        return "No vetted ideas yet — no trend data."

    now = datetime.now(timezone.utc)
    out = ["═" * 72, "TRUTH-LOOP TREND (rolling cohorts)", "═" * 72]

    for days in windows:
        cutoff = now - timedelta(days=days)
        window_rows = []
        for r in rows:
            ts = r.get("created_at", "")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt >= cutoff:
                window_rows.append(r)

        n = len(window_rows)
        if n == 0:
            out.append(f"\n  {days}d window: no data yet")
            continue

        dec = Counter((r.get("decision") or "?").lower() for r in window_rows)
        vetted = dec["pass"] + dec["kill"]
        kr = dec["kill"] / vetted * 100 if vetted else 0.0
        pr = dec["pass"] / vetted * 100 if vetted else 0.0
        gates = Counter(r.get("gate_fired") or "min_composite"
                       for r in window_rows
                       if (r.get("decision") or "").lower() == "kill")
        top_gate = gates.most_common(1)
        forms = _structural_forms(window_rows)
        lanes = Counter(r.get("ambition_tier") or "" for r in window_rows)

        out.append(f"\n  {days}d window: {n} candidates  "
                   f"pass={dec['pass']} ({pr:.0f}%)  "
                   f"kill={dec['kill']} ({kr:.0f}%)  "
                   f"defer={dec['defer']}")
        out.append(f"  forms: {len(forms)}  top gate: "
                   f"{top_gate[0][0] if top_gate else 'none'}  "
                   f"lanes: {dict(lanes.most_common(3))}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# costs (parsed from the audit log — errors excluded)
# ---------------------------------------------------------------------------
def costs_report(jsonl_path: str | Path) -> str:
    p = Path(jsonl_path)
    if not p.exists():
        return f"No audit log at {p} — run something first."

    # Parse full log for lifetime metrics
    lifetime_usd_from_events = 0.0
    tok = {"input": 0, "output": 0, "total": 0, "cached": 0, "self_corrections": 0}
    err_count = 0
    lat_total: dict[str, float] = defaultdict(float)
    lat_count: dict[str, int] = defaultdict(int)
    spend_by_phase: dict[str, float] = defaultdict(float)
    
    # Per-provider call counts and spend
    provider_stats: dict[str, dict[str, Any]] = {}

    with p.open() as f:
        for line in f:
            try: d = json.loads(line)
            except: continue
            
            ev = d.get("event")
            # 1. Track errors (latency status="error")
            if ev == "latency" and d.get("status") == "error":
                err_count += 1
                continue

            # 2. Authoritative spend events
            if ev == "spend":
                amt = float(d.get("amount_usd", 0) or 0)
                lifetime_usd_from_events += amt
                spend_by_phase[d.get("phase") or "main"] += amt
                continue
                
            # 3. Latency tracking
            if ev == "latency":
                op = d.get("operation") or "?"
                lat_total[op] += float(d.get("latency_ms", 0) or 0)
                lat_count[op] += 1
                # Latency events don't attribute usage to providers here to avoid phantom rows

            # 4. Actual usage logs (LLM calls)
            inp = int(d.get("input", 0) or 0)
            outp = int(d.get("output", 0) or 0)
            if inp > 0 or outp > 0:
                # Attribution rule: only from actual usage entries
                provider = d.get("provider") or d.get("model", "").split("/")[0]
                # Backward compat for older logs
                if not provider and "message" in d:
                    msg = d["message"].lower()
                    if "claude cli usage" in msg: provider = "claude"
                    elif "gemini cli usage" in msg: provider = "gemini"
                
                if provider:
                    root = provider.split("/")[0].lower()
                    s = provider_stats.setdefault(root, {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0, "self_corrections": 0})
                    
                    s["calls"] += 1
                    s["input"] += inp
                    s["output"] += outp
                    s["self_corrections"] += 1 if d.get("self_correction") else 0
                    
                    tok["input"] += inp
                    tok["output"] += outp
                    tok["total"] += int(d.get("total", 0) or (inp + outp))
                    tok["cached"] += int(d.get("cached", 0) or 0)
                    tok["self_corrections"] += 1 if d.get("self_correction") else 0
                    
                    # Estimate cost for this entry
                    # (Claude CLI reports its real billed cost per call in 'cost_usd')
                    cost = float(d.get("cost_usd", 0) or 0)
                    if cost:
                        s["cost_usd"] += cost
                    else:
                        from .telemetry import PRICING
                        price = PRICING.get(root, {"input": 0, "output": 0})
                        s["cost_usd"] += (inp * price["input"] / 1_000_000) + (outp * price["output"] / 1_000_000)

    # COST AUTHORITY RULE:
    # 1. Total spend = max(explicit spend events, sum of per-provider costs).
    # 2. Header total ALWAYS equals the sum of the per-provider column for internal consistency.
    # 3. Any difference between authoritative spend and attributed usage is shown as 'legacy / unattributed'.
    sum_attributed = sum(s["cost_usd"] for s in provider_stats.values())
    total_spend = max(lifetime_usd_from_events, sum_attributed)
    
    if total_spend > sum_attributed:
        provider_stats["legacy / unattributed"] = {"cost_usd": total_spend - sum_attributed}

    out = ["═" * 72, "LIFETIME COST & USAGE BREAKDOWN (from audit log)", "═" * 72,
            f"  total estimated spend  ${total_spend:.4f}",
            f"  total model calls      {sum(s.get('calls', 0) for s in provider_stats.values())}",
            f"  errors excluded        {err_count}  (from latency totals)",
            ""]
    
    if provider_stats:
        out.append("  SPEND BY AGENT / PROVIDER:")
        out.append("  " + "─" * 50)
        sorted_prov = sorted(provider_stats.items(), key=lambda x: -x[1].get("cost_usd", 0))
        for prov, stats in sorted_prov:
            cost = stats.get("cost_usd", 0)
            calls = stats.get("calls", 0)
            inp, outp = stats.get("input", 0), stats.get("output", 0)
            rep = stats.get("self_corrections", 0)
            rep_str = f", {rep} repairs" if rep else ""
            call_str = f"({calls:>3} calls, {inp:,} in / {outp:,} out{rep_str})" if calls else ""
            out.append(f"  {prov:<25} ${cost:7.4f}  {call_str}")
        out.append("")

    out.extend([
        f"  total tokens in        {tok['input']:,}",
        f"  total tokens out       {tok['output']:,}",
        f"  total tokens total     {tok['total']:,}   ({tok['cached']:,} cached)",
    ])
    
    if spend_by_phase:
        out.append("")
        out.append("  spend by phase:")
        for ph, amt in sorted(spend_by_phase.items(), key=lambda x: -x[1]):
            out.append(f"    {ph:<22} ${amt:.2f}")

    if lat_total:
        out.append("")
        out.append("  slowest operations (total wall-clock, errors excluded):")
        out.append("  " + "─" * 50)
        slowest = sorted(lat_total.items(), key=lambda x: -x[1])[:6]
        for op, ms in slowest:
            n = lat_count[op]
            out.append(f"    {op:<22} {ms/1000:7.1f}s total   "
                       f"{ms/n/1000:5.1f}s avg × {n}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _structural_forms(rows: list[dict]) -> set[str]:
    forms: set[str] = set()
    for r in rows:
        # Canonical: structural_form is a first-class field on the dossier index
        # (and on candidate). Read it directly — the legacy tags["form:*"] scheme
        # below is kept only for back-compat with pre-field rows.
        sform = r.get("structural_form")
        if sform:
            forms.add(str(sform))
        cand = r.get("candidate")
        if isinstance(cand, dict) and cand.get("structural_form"):
            forms.add(str(cand["structural_form"]))

        tags = r.get("tags", {})
        if isinstance(tags, dict):
            for k, v in tags.items():
                if k.startswith("form:"):
                    forms.add(str(v) if v else k.replace("form:", ""))
        elif isinstance(tags, list):
            for item in tags:
                if isinstance(item, str) and item.startswith("form:"):
                    forms.add(item.replace("form:", ""))
    return forms


def full_report(store: Store, jsonl_path: str | Path,
                trend_windows: tuple[int, ...] = (7, 30, 90)) -> str:
    return "\n\n".join([
        catalogue_report(store),
        metrics_report(store),
        generation_quality_report(store),
        trend_report(store, trend_windows),
        costs_report(jsonl_path),
    ])

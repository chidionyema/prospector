"""Human-readable reporting over the catalogue + audit log.

The engine already records everything (dossiers in store/, token/cost/latency in
store/prospector.jsonl). This module turns that raw state into the three views an
operator actually wants — WITHOUT re-running any model call:

  - catalogue : every vetted idea grouped by decision (PASS / KILL / DEFER),
                with kill gate or composite — the "what came through" view.
  - metrics   : decision counts, kill rate, which gate kills most, defer rate —
                the truth-loop health view (is the filter discriminating?).
  - costs     : lifetime $ spend + token usage + slowest operations, parsed from
                the audit log — the "what is this costing me" view.

All three read on-disk state only; safe to run any time, mutates nothing.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from .store import Store

_GLYPH = {"pass": "✅", "kill": "🛑", "defer": "⏸️"}
_ORDER = {"pass": 0, "defer": 1, "kill": 2}  # PASS first — that's what you publish


# ---------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------
def catalogue_report(store: Store, decision: Optional[str] = None) -> str:
    rows = store.all(decision)
    if not rows:
        scope = f" with decision={decision!r}" if decision else ""
        return f"No vetted ideas in the catalogue{scope} yet. Run `vet` or `signal` first."

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
            if dec == "pass":
                tail = f"composite={r.get('composite'):.2f}" if r.get("composite") is not None else ""
            elif dec == "defer":
                tail = "retrieval unavailable — re-vet"
            else:
                tail = f"gate={r.get('gate_fired') or 'min_composite'}"
            out.append(f"  {title}")
            out.append(f"      {tail}   id={r.get('candidate_id')}")
    out.append("")
    out.append(f"Full dossier JSON: store/dossiers/<id>.<decision>.json")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# metrics (truth-loop health)
# ---------------------------------------------------------------------------
def metrics_report(store: Store) -> str:
    rows = store.all()
    if not rows:
        return "No vetted ideas yet — no metrics to report."
    n = len(rows)
    dec = Counter((r.get("decision") or "?").lower() for r in rows)
    gates = Counter(r.get("gate_fired") or "min_composite"
                    for r in rows if (r.get("decision") or "").lower() == "kill")
    vetted = dec["pass"] + dec["kill"]  # defers never reached a verdict
    kill_rate = (dec["kill"] / vetted * 100) if vetted else 0.0
    pass_rate = (dec["pass"] / vetted * 100) if vetted else 0.0

    out = ["═" * 72, "TRUTH-LOOP METRICS", "═" * 72,
           f"  total dossiers      {n}",
           f"  ✅ pass             {dec['pass']}",
           f"  🛑 kill             {dec['kill']}",
           f"  ⏸️  defer            {dec['defer']}  (retrieval unavailable, not a verdict)",
           "",
           f"  pass rate           {pass_rate:5.1f}%   (of {vetted} that reached a verdict)",
           f"  kill rate           {kill_rate:5.1f}%"]
    if gates:
        out += ["", "  KILL gate distribution (which check kills most):", "  " + "─" * 50]
        for gate, c in gates.most_common():
            bar = "█" * round(c / max(gates.values()) * 24)
            out.append(f"  {gate:<22} {c:>3}  {bar}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# costs (parsed from the audit log)
# ---------------------------------------------------------------------------
def costs_report(jsonl_path: str | Path) -> str:
    p = Path(jsonl_path)
    if not p.exists():
        return f"No audit log at {p} — run something first."

    spend_usd = 0.0
    tok = {"input": 0, "output": 0, "total": 0, "cached": 0}
    calls = web_calls = 0
    lat_total: dict[str, float] = defaultdict(float)
    lat_count: dict[str, int] = defaultdict(int)
    spend_by_phase: dict[str, float] = defaultdict(float)

    with p.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ev = d.get("event")
            if ev == "spend":
                amt = float(d.get("amount_usd", 0) or 0)
                spend_usd += amt
                spend_by_phase[d.get("phase") or "main"] += amt
            elif ev == "latency":
                op = d.get("operation") or "?"
                lat_total[op] += float(d.get("latency_ms", 0) or 0)
                lat_count[op] += 1
            elif d.get("message") in ("Gemini CLI usage", "Claude CLI usage"):
                calls += 1
                if d.get("web"):
                    web_calls += 1
                for k in tok:
                    tok[k] += int(d.get(k, 0) or 0)
                # Claude CLI reports its real billed cost per call — fold it into spend.
                cost = float(d.get("cost_usd", 0) or 0)
                if cost:
                    spend_usd += cost
                    spend_by_phase[d.get("phase") or "main"] += cost

    out = ["═" * 72, "COST & USAGE (lifetime, from audit log)", "═" * 72,
           f"  estimated spend     ${spend_usd:.2f}",
           f"  model calls         {calls}   ({web_calls} web-search, {calls - web_calls} inference)",
           f"  tokens in           {tok['input']:,}",
           f"  tokens out          {tok['output']:,}",
           f"  tokens total        {tok['total']:,}   ({tok['cached']:,} cached)"]
    if spend_by_phase:
        out += ["", "  spend by phase:"]
        for ph, amt in sorted(spend_by_phase.items(), key=lambda x: -x[1]):
            out.append(f"    {ph:<22} ${amt:.2f}")
    if lat_total:
        out += ["", "  slowest operations (total wall-clock):", "  " + "─" * 50]
        slowest = sorted(lat_total.items(), key=lambda x: -x[1])[:6]
        for op, ms in slowest:
            n = lat_count[op]
            out.append(f"    {op:<22} {ms/1000:7.1f}s total   {ms/n/1000:5.1f}s avg × {n}")
    return "\n".join(out)


def full_report(store: Store, jsonl_path: str | Path) -> str:
    return "\n\n".join([catalogue_report(store), metrics_report(store),
                        costs_report(jsonl_path)])

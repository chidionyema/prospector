#!/usr/bin/env python3
"""cc-token-report.py — read-only Claude Code token forensics.

Parses ~/.claude/projects/**/*.jsonl (every session transcript) and reports where
your token WEIGHT goes, so token-cutting changes can be proven before/after.

It writes nothing and calls no network. Run it to snapshot a baseline, apply
changes, run it again, and diff the numbers.

Key metric: per request, "resident context" = input + cache_read + cache_creation
(the whole prompt billed that turn). cache_read dominates real usage, and
cache_read ~= turns x resident_context. Marathon sessions (many turns x large
resident context) are therefore the usual #1 cost — not a bad cache-hit rate.

Usage:
  cc-token-report.py                 # all-time summary
  cc-token-report.py --since 7d      # only sessions with activity in last 7 days
  cc-token-report.py --top 15        # show top N sessions / projects (default 10)
  cc-token-report.py --project foo   # only projects whose slug contains 'foo'
  cc-token-report.py --json out.json # also dump the full machine-readable report
"""
import argparse
import glob
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.expanduser("~/.claude/projects")

# List-price $/MTok by model family — for a cost-WEIGHT proxy only (your subscription
# caps actual dollars; these expose where the token weight sits). Tweak if rates change.
RATES = {  # (input, cache_write, cache_read, output) per 1M tokens
    "opus":   (15.0, 18.75, 1.50, 75.0),
    "sonnet": (3.0,  3.75,  0.30, 15.0),
    "haiku":  (1.0,  1.25,  0.10, 5.0),
}
def _family(model):
    m = (model or "").lower()
    for fam in RATES:
        if fam in m:
            return fam
    return "opus"  # unknown -> price as the expensive case, don't undercount

def _cost(u, model):
    inp, cw, cr, out = RATES[_family(model)]
    return (u["input"]*inp + u["cache_creation"]*cw + u["cache_read"]*cr + u["output"]*out) / 1e6

def _parse_since(s):
    if not s:
        return None
    unit = s[-1].lower()
    n = float(s[:-1])
    mult = {"d": 1, "w": 7, "h": 1/24}.get(unit)
    if mult is None:
        sys.exit(f"bad --since '{s}'; use e.g. 7d, 2w, 12h")
    return datetime.now(timezone.utc) - timedelta(days=n*mult)

def _ts(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except Exception:
        return None

def _fmt(n):
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n/div:.2f}{unit}"
    return f"{n:.0f}"

def blank():
    return {"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}

def add(dst, u):
    for k in dst:
        dst[k] += u[k]

def main():
    ap = argparse.ArgumentParser(description="Claude Code token forensics (read-only).")
    ap.add_argument("--since", help="only sessions active within e.g. 7d, 2w, 12h")
    ap.add_argument("--top", type=int, default=10, help="rows in top lists (default 10)")
    ap.add_argument("--project", help="filter to project slugs containing this substring")
    ap.add_argument("--marathon-turns", type=int, default=500, help="turn count that flags a marathon")
    ap.add_argument("--json", dest="json_out", help="also write full report JSON to this path")
    args = ap.parse_args()
    since = _parse_since(args.since)

    files = [f for f in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True)
             if os.path.getsize(f) > 0]
    if args.project:
        files = [f for f in files if args.project in f]
    if not files:
        sys.exit(f"no transcripts found under {ROOT}")

    grand = blank()
    by_model, by_project = {}, {}          # name -> usage dict
    by_model_cost, by_project_cost = {}, {}
    sessions = {}                          # session_id -> stats
    mcp_calls = {}                         # mcp tool name -> count
    total_cost = 0.0

    for fp in files:
        slug = os.path.basename(os.path.dirname(fp))
        sess_active = None
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") != "assistant":
                    # still scan user/tool records for mcp tool_result + compaction markers
                    if rec.get("isCompactSummary"):
                        sid = rec.get("sessionId") or slug
                        sessions.setdefault(sid, _new_sess(slug))["compactions"] += 1
                    continue
                msg = rec.get("message") or {}
                u_raw = msg.get("usage") or {}
                if not u_raw:
                    continue
                u = {
                    "input": u_raw.get("input_tokens", 0) or 0,
                    "cache_read": u_raw.get("cache_read_input_tokens", 0) or 0,
                    "cache_creation": u_raw.get("cache_creation_input_tokens", 0) or 0,
                    "output": u_raw.get("output_tokens", 0) or 0,
                }
                ts = _ts(rec)
                model = msg.get("model") or "unknown"
                sid = rec.get("sessionId") or slug

                # count MCP tool invocations from assistant tool_use blocks
                for block in (msg.get("content") or []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name.startswith("mcp__"):
                            mcp_calls[name] = mcp_calls.get(name, 0) + 1

                resident = u["input"] + u["cache_read"] + u["cache_creation"]
                cost = _cost(u, model)
                total_cost += cost

                add(grand, u)
                add(by_model.setdefault(model, blank()), u)
                by_model_cost[model] = by_model_cost.get(model, 0.0) + cost
                add(by_project.setdefault(slug, blank()), u)
                by_project_cost[slug] = by_project_cost.get(slug, 0.0) + cost

                s = sessions.setdefault(sid, _new_sess(slug))
                s["turns"] += 1
                s["resident"].append(resident)
                add(s["usage"], u)
                s["cost"] += cost
                s["models"].add(model)
                if ts:
                    s["first"] = ts if s["first"] is None else min(s["first"], ts)
                    s["last"] = ts if s["last"] is None else max(s["last"], ts)
                    sess_active = ts if sess_active is None else max(sess_active, ts)

        if since and (sess_active is None or sess_active < since):
            # drop this file's sessions from the report if it had no recent activity
            for sid in list(sessions):
                if sessions[sid]["slug"] == slug and sessions[sid].get("first") and \
                   sessions[sid]["last"] and sessions[sid]["last"] < since:
                    sessions.pop(sid, None)

    if since:
        # recompute aggregates from surviving sessions only
        grand = blank()
        by_model = {}
        by_project = {}
        by_model_cost = {}
        by_project_cost = {}
        total_cost = 0.0
        for s in sessions.values():
            add(grand, s["usage"])
            total_cost += s["cost"]
            add(by_project.setdefault(s["slug"], blank()), s["usage"])
            by_project_cost[s["slug"]] = by_project_cost.get(s["slug"], 0.0) + s["cost"]
            for m in s["models"]:
                by_model.setdefault(m, blank())  # model split approximate under --since

    _print_report(args, grand, total_cost, by_model, by_model_cost,
                  by_project, by_project_cost, sessions, mcp_calls)

    if args.json_out:
        _dump_json(args.json_out, grand, total_cost, by_model, by_project, sessions, mcp_calls)
        print(f"\nFull report written to {args.json_out}")

def _new_sess(slug):
    return {"slug": slug, "turns": 0, "resident": [], "usage": blank(), "cost": 0.0,
            "first": None, "last": None, "compactions": 0, "models": set()}

def _bar(frac, width=24):
    fill = int(round(frac * width))
    return "█" * fill + "·" * (width - fill)

def _print_report(args, grand, total_cost, by_model, by_model_cost,
                  by_project, by_project_cost, sessions, mcp_calls):
    total = sum(grand.values())
    cache_denom = grand["cache_read"] + grand["cache_creation"] + grand["input"]
    hit = grand["cache_read"] / cache_denom if cache_denom else 0.0
    cr_share = grand["cache_read"] / total if total else 0.0

    print("=" * 72)
    print("  CLAUDE CODE TOKEN REPORT" + (f"  (since {args.since})" if args.since else "  (all-time)"))
    print("=" * 72)
    print(f"  sessions: {len(sessions)}    total token-weight: {_fmt(total)}    "
          f"cost-weight(list): ${total_cost:,.0f}")
    print()
    print(f"  input          {_fmt(grand['input']):>9}")
    print(f"  output         {_fmt(grand['output']):>9}")
    print(f"  cache_read     {_fmt(grand['cache_read']):>9}   {cr_share*100:4.1f}% of all tokens")
    print(f"  cache_creation {_fmt(grand['cache_creation']):>9}")
    print(f"  cache-hit ratio: {hit*100:.1f}%  "
          + ("(already near-optimal — caching is NOT the leak)" if hit > 0.9 else ""))
    print()
    print("  --> When cache_read dominates, the lever is turns x resident_context:")
    print("      shorter sessions + leaner context, NOT a better cache-hit rate.")

    # by model
    print("\n  BY MODEL" + " " * 18 + "weight        cost(list)   share")
    rows = sorted(by_model.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
    for model, u in rows[:args.top]:
        w = sum(u.values())
        print(f"  {model:<26} {_fmt(w):>8}   ${by_model_cost.get(model,0):>10,.0f}   "
              f"{_bar(w/total if total else 0)}")

    # by project
    print("\n  BY PROJECT (slug)            weight        cost(list)")
    rows = sorted(by_project.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
    for slug, u in rows[:args.top]:
        short = slug.replace("-Users-chidionyema-", "~/").replace("-", "/")
        short = short if len(short) <= 34 else "…" + short[-33:]
        print(f"  {short:<34} {_fmt(sum(u.values())):>8}   ${by_project_cost.get(slug,0):>10,.0f}")

    # marathon sessions — the headline
    print(f"\n  MARATHON SESSIONS (>{args.marathon_turns} turns OR multi-day) — the prime leak")
    print("  turns   medianCtx  maxCtx   days  compact   cost   project")
    mara = []
    for sid, s in sessions.items():
        if not s["resident"]:
            continue
        days = ((s["last"] - s["first"]).total_seconds() / 86400) if (s["first"] and s["last"]) else 0
        is_marathon = s["turns"] > args.marathon_turns or days >= 1
        if is_marathon:
            mara.append((s, days))
    mara.sort(key=lambda x: x[0]["cost"], reverse=True)
    if not mara:
        print("  (none — sessions are well-scoped. nice.)")
    for s, days in mara[:args.top]:
        med = statistics.median(s["resident"])
        mx = max(s["resident"])
        short = s["slug"].split("-")[-1]
        print(f"  {s['turns']:>5}   {_fmt(med):>8}  {_fmt(mx):>7}  {days:>4.1f}  "
              f"{s['compactions']:>6}   ${s['cost']:>5,.0f}   {short}")
    marathon_cost = sum(s["cost"] for s, _ in mara)
    if total_cost:
        print(f"\n  marathon sessions = ${marathon_cost:,.0f} of ${total_cost:,.0f} "
              f"({marathon_cost/total_cost*100:.0f}% of cost-weight)")

    # MCP tax
    print("\n  MCP TOOL USAGE (schemas are taxed into EVERY request whether used or not)")
    if mcp_calls:
        for name, n in sorted(mcp_calls.items(), key=lambda kv: -kv[1])[:args.top]:
            print(f"    {n:>6}  {name}")
    else:
        print("    0 MCP tool calls found across all transcripts.")
        print("    => any connected MCP server is pure per-request schema tax. Drop unused ones (/mcp).")
    print("=" * 72)

def _dump_json(path, grand, total_cost, by_model, by_project, sessions, mcp_calls):
    out = {
        "grand": grand, "total_cost_list": total_cost,
        "cache_hit_ratio": grand["cache_read"] / max(1, grand["cache_read"] + grand["cache_creation"] + grand["input"]),
        "by_model": {k: v for k, v in by_model.items()},
        "by_project": {k: v for k, v in by_project.items()},
        "mcp_calls": mcp_calls,
        "sessions": {
            sid: {
                "slug": s["slug"], "turns": s["turns"], "cost": s["cost"],
                "median_resident": statistics.median(s["resident"]) if s["resident"] else 0,
                "max_resident": max(s["resident"]) if s["resident"] else 0,
                "compactions": s["compactions"],
                "first": s["first"].isoformat() if s["first"] else None,
                "last": s["last"].isoformat() if s["last"] else None,
            } for sid, s in sessions.items()
        },
    }
    with open(os.path.expanduser(path), "w") as fh:
        json.dump(out, fh, indent=2)

if __name__ == "__main__":
    main()

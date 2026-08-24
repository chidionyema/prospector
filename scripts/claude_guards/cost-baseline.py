#!/usr/bin/env python3
"""cost-baseline.py — measured $/request by model, straight from the transcripts.

The point: "Opus->Sonnet is 0.6x on every rate" is a rate-card claim. This turns it
into a MEASURED before/after on real traffic, so the saving can be proven rather than
asserted. Run it before the switch (baseline) and after (proof).

Usage:
  cost-baseline.py                 # today, this machine, all projects
  cost-baseline.py --date 2026-08-06
  cost-baseline.py --since 2026-08-01 --project -Users-chidionyema-Documents-code-prospector

Every figure is derived from usage counters the API returned, never estimated from
character counts. Requests with no usage block are counted separately and excluded.
"""
import json, os, glob, argparse, collections, datetime

# $ per million tokens. Source: CLAUDE.md model routing ladder (in / cache_write / cache_read / out).
RATES = {
    "claude-opus-5":   (5.00, 6.25, 0.50, 25.00),
    "claude-opus-5[1m]": (5.00, 6.25, 0.50, 25.00),
    "claude-sonnet-5": (3.00, 3.75, 0.30, 15.00),
    "claude-sonnet-5[1m]": (3.00, 3.75, 0.30, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 1.25, 0.10, 5.00),
}

def cost(model, u):
    r = RATES.get(model)
    if not r:
        return None
    inp, cw, cr, out = r
    return (u.get("input_tokens", 0) * inp
            + u.get("cache_creation_input_tokens", 0) * cw
            + u.get("cache_read_input_tokens", 0) * cr
            + u.get("output_tokens", 0) * out) / 1_000_000

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--since")
    ap.add_argument("--project", default="*")
    a = ap.parse_args()
    day = a.date or (None if a.since else datetime.date.today().isoformat())

    agg = collections.defaultdict(lambda: {"n": 0, "usd": 0.0, "in": 0, "cw": 0, "cr": 0, "out": 0})
    unpriced = collections.Counter()
    seen = set()  # (file, message.id) — see the dedup note in the loop below

    for f in glob.glob(os.path.expanduser(f"~/.claude/projects/{a.project}/*.jsonl")):
        try:
            fh = open(f)
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ts = r.get("timestamp") or ""
                if day and not ts.startswith(day):
                    continue
                if a.since and ts[:10] < a.since:
                    continue
                m = (r.get("message") or {})
                model, u = m.get("model"), m.get("usage")
                if not model or not u:
                    continue
                # One assistant turn = one API request, but Claude Code writes it as SEVERAL
                # jsonl records sharing a `message.id`, each repeating `usage` byte-identically.
                # Counting per record inflated this report ~1.96x ($1,792 vs $914 on 2026-08-06).
                # Memory: transcript-totals-double-count-per-record.md
                mid = m.get("id")
                if mid is not None:
                    k = (f, mid)
                    if k in seen:
                        continue
                    seen.add(k)
                c = cost(model, u)
                if c is None:
                    unpriced[model] += 1
                    continue
                d = agg[model]
                d["n"] += 1; d["usd"] += c
                d["in"] += u.get("input_tokens", 0)
                d["cw"] += u.get("cache_creation_input_tokens", 0)
                d["cr"] += u.get("cache_read_input_tokens", 0)
                d["out"] += u.get("output_tokens", 0)

    scope = f"date={day}" if day else f"since={a.since}"
    print(f"── MEASURED COST BY MODEL ── {scope}  project={a.project}")
    if not agg:
        print("  (no priced requests in scope)")
        return
    print(f"  {'model':26s} {'reqs':>6s} {'total $':>10s} {'$/req':>9s} {'cache_read %':>13s}")
    tot_usd = tot_n = 0
    for model, d in sorted(agg.items(), key=lambda x: -x[1]["usd"]):
        toks = d["in"] + d["cw"] + d["cr"] + d["out"]
        crpct = 100 * d["cr"] / toks if toks else 0
        print(f"  {model:26s} {d['n']:6d} {d['usd']:10.2f} {d['usd']/d['n']:9.4f} {crpct:12.1f}%")
        tot_usd += d["usd"]; tot_n += d["n"]
    print(f"  {'TOTAL':26s} {tot_n:6d} {tot_usd:10.2f} {tot_usd/tot_n:9.4f}")

    # The counterfactual: what the same token traffic would have cost on Sonnet.
    saved = 0.0
    for model, d in agg.items():
        if "opus" in model:
            s = (d["in"] * 3.00 + d["cw"] * 3.75 + d["cr"] * 0.30 + d["out"] * 15.00) / 1_000_000
            saved += d["usd"] - s
    if saved:
        print(f"\n  counterfactual: the SAME traffic on Sonnet costs ${tot_usd - saved:.2f} "
              f"→ saving ${saved:.2f} ({100*saved/tot_usd:.1f}%)")
    if unpriced:
        print(f"  unpriced models skipped: {dict(unpriced)}")

if __name__ == "__main__":
    main()

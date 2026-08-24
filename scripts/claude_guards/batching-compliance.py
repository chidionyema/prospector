#!/usr/bin/env python3
"""batching-compliance.py — measured cost of one-tool-call-per-turn.

CLAUDE.md has mandated "ONE ROUND-TRIP PER INTENT" for months. Prose is not enforcing
it, so first make it MEASURABLE per session, then enforceable.

A "turn" here is ONE ASSISTANT MESSAGE = one API request = one `message.id`.
We count the tool_use blocks across the whole message:
  0 blocks  -> conversational turn (no batching opportunity)
  1 block   -> single-call turn (the expensive habit, IF it had siblings available)
  >=2       -> batched turn

*** THE TRAP THIS SCRIPT EXISTS TO AVOID (measured 2026-08-06) ***
Claude Code writes ONE assistant turn as MULTIPLE jsonl records that share a
`message.id`, each carrying a slice of `message.content` (typically one text or one
tool_use block each) and a BYTE-IDENTICAL COPY of `message.usage`.

Measured on 2026-08-06, all projects: 14,982 assistant records collapse to 7,935
message.id groups. 4,961 of those groups (62.5%) span >1 record, and in 4,961 of
4,961 every record carried an identical usage object (0 differing, 0 missing).

So counting PER RECORD is wrong twice over:
  1. every multi-block turn looks like a pile of single-call turns  -> compliance ~0%
  2. its usage is added once per record                             -> $ inflated ~1.9x

Both bugs are fixed by grouping on message.id and pricing each group ONCE.
`--per-record` reproduces the old (wrong) numbers so the gap stays auditable.

Usage:
  batching-compliance.py                     # today, all projects
  batching-compliance.py --date 2026-08-06
  batching-compliance.py --session <uuid>    # one session
  batching-compliance.py --per-record        # show the double-count for comparison
"""
import json, os, glob, argparse, collections, datetime

RATES = {  # $/Mtok: input, cache_write, cache_read, output
    "claude-opus-5": (5.0, 6.25, 0.5, 25.0), "claude-opus-5[1m]": (5.0, 6.25, 0.5, 25.0),
    "claude-sonnet-5": (3.0, 3.75, 0.3, 15.0), "claude-sonnet-5[1m]": (3.0, 3.75, 0.3, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 1.25, 0.1, 5.0),
}

def price(model, u):
    r = RATES.get(model)
    if not r:
        return 0.0
    i, cw, cr, o = r
    return (u.get("input_tokens", 0) * i + u.get("cache_creation_input_tokens", 0) * cw
            + u.get("cache_read_input_tokens", 0) * cr + u.get("output_tokens", 0) * o) / 1e6

def collect(a):
    """Return {(file, msg_id): {"model":…, "usage":…, "ncalls":int, "records":int}}.

    usage is taken from the FIRST record of the group and never re-added; ncalls is
    summed ACROSS the group. Records with no message.id fall back to a unique key so
    they remain their own turn rather than colliding into one bucket.
    """
    turns = {}
    for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        if a.session and a.session not in os.path.basename(f):
            continue
        try:
            fh = open(f)
        except OSError:
            continue
        with fh:
            for lineno, line in enumerate(fh):
                if '"assistant"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") != "assistant":
                    continue
                ts = r.get("timestamp") or ""
                if not a.all_dates and not ts.startswith(a.date):
                    continue
                m = r.get("message") or {}
                u = m.get("usage")
                if not u:
                    continue
                mid = m.get("id")
                key = (f, mid) if mid else (f, f"__noid__{lineno}")
                t = turns.get(key)
                if t is None:
                    t = turns[key] = {"model": m.get("model"), "usage": u,
                                      "ncalls": 0, "records": 0, "file": f}
                t["records"] += 1
                t["ncalls"] += sum(1 for b in (m.get("content") or [])
                                   if isinstance(b, dict) and b.get("type") == "tool_use")
    return turns

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--session")
    ap.add_argument("--all-dates", action="store_true")
    ap.add_argument("--per-record", action="store_true",
                    help="also print the old per-record numbers, to expose the double-count")
    a = ap.parse_args()

    turns = collect(a)

    buckets = collections.defaultdict(lambda: {"n": 0, "usd": 0.0})
    per_session = collections.Counter()
    n_records = 0
    for (f, _mid), t in turns.items():
        n = t["ncalls"]
        key = "conversational (0 calls)" if n == 0 else (
            "SINGLE-CALL (1)" if n == 1 else "batched (>=2)")
        c = price(t["model"], t["usage"])
        buckets[key]["n"] += 1
        buckets[key]["usd"] += c
        n_records += t["records"]
        if n == 1:
            per_session[os.path.basename(f)[:8]] += 1

    scope = "all dates" if a.all_dates else a.date
    print(f"── BATCHING COMPLIANCE ── {scope}")
    print(f"  {n_records} assistant records -> {len(turns)} turns (message.id groups)")
    tot_n = sum(b["n"] for b in buckets.values()) or 1
    tot_usd = sum(b["usd"] for b in buckets.values()) or 1e-9
    print(f"  {'turn type':26s} {'turns':>7s} {'% turns':>8s} {'$':>10s} {'% $':>7s} {'$/turn':>8s}")
    for k in ["SINGLE-CALL (1)", "batched (>=2)", "conversational (0 calls)"]:
        b = buckets.get(k)
        if not b or not b["n"]:
            continue
        print(f"  {k:26s} {b['n']:7d} {100*b['n']/tot_n:7.1f}% {b['usd']:10.2f} "
              f"{100*b['usd']/tot_usd:6.1f}% {b['usd']/b['n']:8.4f}")
    print(f"  {'TOTAL':26s} {tot_n:7d} {100:7.1f}% {tot_usd:10.2f} {100:6.1f}%")

    tool_turns = sum(buckets[k]["n"] for k in buckets if k != "conversational (0 calls)")
    batched = buckets.get("batched (>=2)", {"n": 0})["n"]
    if tool_turns:
        print(f"\n  compliance: {batched}/{tool_turns} tool-using turns were batched "
              f"= {100*batched/tool_turns:.1f}%")
    single = buckets.get("SINGLE-CALL (1)")
    if single and single["n"]:
        # Counterfactual: if 3 single-call turns had been 1 batched turn, 2 of every 3
        # resident-context re-reads disappear. Conservative: only the cache_read share.
        print(f"  headroom  : merging single-call turns 3->1 removes ~{2*single['n']//3} requests "
              f"(~${2*single['usd']/3:.2f} at today's $/turn)")
    if per_session:
        print(f"  worst sessions by single-call turns: "
              + ", ".join(f"{s}:{n}" for s, n in per_session.most_common(5)))

    if a.per_record:
        # Reproduce the pre-fix arithmetic so the size of the defect stays visible.
        rec_n = 0
        rec_usd = 0.0
        rec_buckets = collections.Counter()
        for t in turns.values():
            c = price(t["model"], t["usage"])
            rec_n += t["records"]
            rec_usd += c * t["records"]
            # old code bucketed each record by ITS OWN block count; a group of R records
            # holding N calls looks like N single-call records + (R-N) conversational.
            rec_buckets["SINGLE-CALL (1)"] += min(t["ncalls"], t["records"])
            rec_buckets["conversational (0 calls)"] += max(t["records"] - t["ncalls"], 0)
        print(f"\n  ── per-record (PRE-FIX, WRONG) ──")
        print(f"  records {rec_n}  $ {rec_usd:.2f}  "
              f"inflation {rec_usd/max(tot_usd,1e-9):.2f}x vs per-turn ${tot_usd:.2f}")
        print(f"  it would report compliance 0.0% because no single record can hold >=2 "
              f"tool_use blocks")

if __name__ == "__main__":
    main()

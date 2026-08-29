#!/usr/bin/env python3
"""Estate-wide Claude Code cost audit. READ-ONLY.

Reconstructs billed cost from every session transcript under ~/.claude/projects/.
Pricing constants and the per-file dedupe are lifted verbatim from
~/.claude/scripts/token-audit.py, which reproduces Claude Code's own
~/.claude.json ledger to 7+ significant figures (see its docstring).
"""
import json, os, sys, glob, collections, datetime

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".claude", "projects")

RATES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
READ_MULT, WRITE_5M, WRITE_1H = 0.1, 1.25, 2.0
UNKNOWN = collections.Counter()


def rate(model):
    m = (model or "").split("[")[0]
    for k, v in RATES.items():
        if m.startswith(k):
            return v
    UNKNOWN[m] += 1
    return RATES["claude-opus-5"]


def split_cost(model, u):
    base, outrate = rate(model)
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0)
    w1 = cc.get("ephemeral_1h_input_tokens", 0)
    if not (w5 or w1):
        w1 = u.get("cache_creation_input_tokens", 0)
    return {
        "raw_input": u.get("input_tokens", 0) * base / 1e6,
        "cache_read": u.get("cache_read_input_tokens", 0) * base * READ_MULT / 1e6,
        "cache_write": (w5 * WRITE_5M + w1 * WRITE_1H) * base / 1e6,
        "output": u.get("output_tokens", 0) * outrate / 1e6,
    }


def norm_model(m):
    return (m or "?").split("-2025")[0].split("-2026")[0]


by_project = collections.Counter()
by_model = collections.Counter()
by_day = collections.Counter()
by_day_project = collections.Counter()
by_driver = collections.Counter()
by_project_model = collections.Counter()
reqs_project = collections.Counter()
sidechain = collections.Counter()
grand = 0.0
nreq = 0
nfiles = 0

files = glob.glob(os.path.join(ROOT, "*", "*.jsonl"))
sys.stderr.write(f"parsing {len(files)} transcripts...\n")

for i, path in enumerate(files):
    if i % 5000 == 0:
        sys.stderr.write(f"  {i}/{len(files)}  ${grand:,.0f}\n")
        sys.stderr.flush()
    slug = os.path.basename(os.path.dirname(path))
    # collapse the thousands of ephemeral hermes worktree slugs into one bucket
    bucket = slug
    if slug.startswith("-Users-chidionyema--hermes-worktrees-"):
        bucket = "-Users-chidionyema--hermes-worktrees-*"
    seen = set()
    nfiles += 1
    try:
        fh = open(path, errors="ignore")
    except OSError:
        continue
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            if not u or msg.get("model") == "<synthetic>":
                continue
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            model = norm_model(msg.get("model"))
            parts = split_cost(msg.get("model"), u)
            c = sum(parts.values())
            grand += c
            nreq += 1
            by_project[bucket] += c
            by_model[model] += c
            by_project_model[(bucket, model)] += c
            reqs_project[bucket] += 1
            sidechain["subagent" if d.get("isSidechain") else "main"] += c
            for k, v in parts.items():
                by_driver[k] += v
            ts = d.get("timestamp") or ""
            if len(ts) >= 10:
                by_day[ts[:10]] += c
                by_day_project[(ts[:10], bucket)] += c

W = 78
def hdr(t):
    print("\n" + "=" * W); print(t); print("=" * W)

print(f"ESTATE CLAUDE CODE COST AUDIT   generated over {nfiles:,} transcripts, {nreq:,} API requests")
print(f"TOTAL RECONSTRUCTED SPEND: ${grand:,.2f}")

hdr("1. SPEND BY PROJECT (subscription-equivalent, all time)")
print(f"{'project':<48}{'requests':>10}{'$':>12}{'%':>7}")
for k, v in by_project.most_common(25):
    print(f"{k[:47]:<48}{reqs_project[k]:>10,}{v:>12,.2f}{v/grand:>7.1%}")

hdr("2. SPEND BY MODEL")
print(f"{'model':<32}{'$':>12}{'%':>8}")
for k, v in by_model.most_common():
    print(f"{k[:31]:<32}{v:>12,.2f}{v/grand:>8.1%}")

hdr("3. WHERE THE MONEY GOES (cost driver)")
print(f"{'driver':<20}{'$':>12}{'%':>8}")
for k, v in by_driver.most_common():
    print(f"{k:<20}{v:>12,.2f}{v/grand:>8.1%}")

hdr("4. MAIN LOOP vs SUBAGENT")
for k, v in sidechain.most_common():
    print(f"{k:<20}{v:>12,.2f}{v/grand:>8.1%}")

hdr("5. LAST 21 DAYS")
print(f"{'day':<14}{'$':>12}   top project")
for day in sorted(by_day)[-21:]:
    tops = [(p, c) for (d, p), c in by_day_project.items() if d == day]
    tops.sort(key=lambda x: -x[1])
    t = f"{tops[0][0][:44]} ${tops[0][1]:,.0f}" if tops else ""
    print(f"{day:<14}{by_day[day]:>12,.2f}   {t}")

hdr("6. PER-PROJECT MODEL MIX (top 8 projects)")
for proj, _ in by_project.most_common(8):
    print(f"\n  {proj}")
    rows = [(m, c) for (p, m), c in by_project_model.items() if p == proj]
    rows.sort(key=lambda x: -x[1])
    tot = sum(c for _, c in rows) or 1
    for m, c in rows:
        print(f"     {m[:30]:<32}{c:>10,.2f}{c/tot:>8.1%}")

if UNKNOWN:
    hdr("UNPRICED MODEL IDS (defaulted to Opus rates)")
    for k, v in UNKNOWN.most_common(15):
        print(f"  {k}  x{v}")

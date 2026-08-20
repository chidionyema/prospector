#!/usr/bin/env python3
"""Estate-wide Claude spend meter — reads GROUND TRUTH, not our own bookkeeping.

WHY THIS EXISTS
---------------
On 2026-08-06 the estate burned $852.22 in one day with no alarm. Every meter that could
have caught it was measuring something our own code chose to write down:

  * `spend.daily_cap_usd` counts ledger rows tagged `event: "spend"` — metered API money
    only. Measured over 30 days: metered $71.97 vs subscription $1,548.10. It bounded 4.4%.
  * The subscription leg IS recorded (`claude_cli._record_claude_usage`) — but only on the
    SUCCESS path. A call that times out or exits non-zero raises before reaching it, having
    already spent the money. Measured 2026-08-06: 1,926 daemon calls made costed API
    requests, 1,568 reached the ledger — 358 missing (18.6%, $104.89).
  * Hermes' `coordinator.db` records `claude-cli` at $0.0000 for 143 calls; lifetime
    recorded $0.0567 against $240.37 actually burned. A 4,240x under-report.

The common failure is structural, not a bug in any one of them: a meter fed by our own
instrumentation goes blind exactly when our code breaks, which is exactly when spend runs
away. So this meter reads the transcripts under `~/.claude/projects/`, which Claude Code
writes for itself on every request. Nothing in this estate has to remember to log for the
number to be right, and a crash cannot hide a request.

TRUST
-----
Costs are reconstructed from `message.usage` with the rate table validated in
`~/.claude/scripts/token-audit.py:33-43`, which reproduces `~/.claude.json`'s own
`lastModelUsage.costUSD` to 7+ significant figures. `--verify` cross-checks this incremental
scan against a full-corpus scan; they must agree.

Requests are deduped by `message.id` WITHIN each file. Assistant turns are re-emitted on
retries and streaming updates, so an undeduped sum over-counts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict

PROJECTS = os.path.expanduser("~/.claude/projects")

# $/MTok (input, output). Validated against token-audit.py:33-43.
RATES = {
    "opus-5":   (5.00, 25.00),
    "fable-5":  (10.00, 50.00),
    "sonnet-5": (3.00, 15.00),
    "haiku-4-5": (1.00, 5.00),
}
_DEFAULT = RATES["opus-5"]
READ_MULT = 0.1     # cache_read billed at 0.1x input
WRITE_5M = 1.25     # 5-minute TTL cache write
WRITE_1H = 2.0      # 1-hour TTL cache write


def norm_model(m: str) -> str:
    m = (m or "").lower()
    if "fable" in m:
        return "fable-5"
    if "haiku" in m:
        return "haiku-4-5"
    if "sonnet" in m:
        return "sonnet-5"
    if "opus" in m:
        return "opus-5"
    return "opus-5"


def split_cost(model: str, u: dict) -> dict:
    """Per-driver cost. Kept split because WHICH driver dominates changes the remedy:
    output-heavy means pick a cheaper model, cache_write-heavy means fix cache reuse.
    On 2026-08-06 it was cache_write 44.7% + cache_read 34.6% — only 20.7% was output,
    so a model downgrade would have addressed a fifth of the problem."""
    base, outrate = RATES.get(norm_model(model), _DEFAULT)
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0)
    w1 = cc.get("ephemeral_1h_input_tokens", 0)
    if not (w5 or w1):
        # Older rows carry only the flat total; the 1h tier is the conservative read.
        w1 = u.get("cache_creation_input_tokens", 0)
    return {
        "raw_input": u.get("input_tokens", 0) * base / 1e6,
        "cache_read": u.get("cache_read_input_tokens", 0) * base * READ_MULT / 1e6,
        "cache_write": (w5 * WRITE_5M + w1 * WRITE_1H) * base / 1e6,
        "output": u.get("output_tokens", 0) * outrate / 1e6,
    }


def bucket(slug: str) -> str:
    """Collapse a project slug into an accountable owner.

    The daemon mints one slug per `claude -p` cwd, so its spend arrives shredded across
    thousands of directories — 16,390 of them on 2026-08-06. Summed per slug it looks like
    noise; summed per owner it was 60% of the day.
    """
    if "prospector_cli_cwd" in slug or slug.startswith("-private-var-folders"):
        return "prospector-daemon (headless claude -p)"
    if "hermes" in slug:
        return "hermes"
    if "prospector" in slug:
        return "prospector-interactive"
    return slug.strip("-") or "unknown"


def scan(day: str | None, full: bool = False) -> dict:
    """Aggregate spend for `day` (YYYY-MM-DD, local) or all days when day is None.

    Incremental by default: a transcript whose mtime predates the target day cannot contain
    rows for it, so it is skipped without being opened. That is what makes this cheap enough
    to run on a schedule — a full scan of 84k files takes minutes, this takes seconds.
    `full=True` disables the skip and is what `--verify` uses to prove the skip is safe.
    """
    cutoff = 0.0
    if day and not full:
        d = dt.date.fromisoformat(day)
        # Local midnight, minus a day of slack for clock skew and late flushes.
        cutoff = dt.datetime.combine(d, dt.time.min).timestamp() - 86400

    total = 0.0
    by_owner: dict[str, float] = defaultdict(float)
    # Per-owner REQUEST counts, not just dollars. The daily total alone cannot tell a cheaper
    # daemon from a less busy one, and $/request is the figure that survives a change in batch
    # size — it is what the 2026-08-06 finding rested on ($0.2650 vs $0.0937) and what the
    # halt cap has to be set against.
    reqs_owner: dict[str, int] = defaultdict(int)
    by_model: dict[str, float] = defaultdict(float)
    by_driver: dict[str, float] = defaultdict(float)
    reqs = 0
    files = 0

    if not os.path.isdir(PROJECTS):
        return {"day": day, "total": 0.0, "requests": 0, "files": 0,
                "by_owner": {}, "by_model": {}, "by_driver": {},
                "reqs_by_owner": {}}

    with os.scandir(PROJECTS) as projects:
        for entry in projects:
            if not entry.is_dir():
                continue
            owner = bucket(entry.name)
            try:
                transcripts = list(os.scandir(entry.path))
            except OSError:
                continue
            for t in transcripts:
                if not t.name.endswith(".jsonl"):
                    continue
                try:
                    if cutoff and t.stat().st_mtime < cutoff:
                        continue
                except OSError:
                    continue
                files += 1
                seen: set[str] = set()
                try:
                    with open(t.path, "r", errors="replace") as fh:
                        for line in fh:
                            if '"usage"' not in line:
                                continue          # cheap reject before the JSON parse
                            try:
                                row = json.loads(line)
                            except Exception:
                                continue
                            msg = row.get("message") or {}
                            usage = msg.get("usage")
                            if not usage:
                                continue
                            if day and not str(row.get("timestamp", "")).startswith(day):
                                # Transcript timestamps are ISO-8601 UTC with a Z suffix.
                                local = _local_day(row.get("timestamp"))
                                if local != day:
                                    continue
                            mid = msg.get("id")
                            if mid:
                                if mid in seen:
                                    continue      # retries re-emit the same assistant turn
                                seen.add(mid)
                            parts = split_cost(msg.get("model", ""), usage)
                            c = sum(parts.values())
                            total += c
                            by_owner[owner] += c
                            reqs_owner[owner] += 1
                            by_model[norm_model(msg.get("model", ""))] += c
                            for k, v in parts.items():
                                by_driver[k] += v
                            reqs += 1
                except OSError:
                    continue

    return {"day": day, "total": round(total, 4), "requests": reqs, "files": files,
            "by_owner": dict(by_owner), "by_model": dict(by_model),
            "by_driver": dict(by_driver), "reqs_by_owner": dict(reqs_owner)}


def _local_day(ts: str | None) -> str | None:
    """UTC transcript stamp -> LOCAL calendar day.

    Not cosmetic: `guard.py` sums by LOCAL day (its docstring records a spend figure that
    appeared to reset at 23:00 UTC and was really local midnight). A meter that halts on a
    UTC day while the guard reports a local one disagrees for an hour every evening, and
    the disagreement looks like a bug in whichever you check second.
    """
    if not ts:
        return None
    try:
        return (dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                .astimezone().date().isoformat())
    except ValueError:
        return None


def fmt(res: dict, cap: float = 0.0) -> str:
    lines = [f"Claude spend {res['day'] or 'all-time'}: ${res['total']:,.2f}"
             f"{f' of ${cap:,.0f} cap' if cap else ''}"
             f"  ({res['requests']:,} requests)"]
    for k, v in sorted(res["by_owner"].items(), key=lambda x: -x[1])[:6]:
        n = (res.get("reqs_by_owner") or {}).get(k, 0)
        rate = f"  ${v / n:.4f}/req" if n else ""
        lines.append(f"  {k[:40]:<40} ${v:>9,.2f}  {v / (res['total'] or 1):>5.1%}{rate}")
    if res["by_driver"]:
        d = res["by_driver"]
        transport = d.get("cache_read", 0) + d.get("cache_write", 0)
        lines.append(f"  context transport {transport / (res['total'] or 1):.0%} "
                     f"| output {d.get('output', 0) / (res['total'] or 1):.0%}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", default=dt.date.today().isoformat(),
                    help="YYYY-MM-DD local (default today); 'all' for the whole corpus")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--cap", type=float, default=0.0,
                    help="alert threshold in USD; exit 2 when today's spend is at or above it")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check the incremental scan against a full-corpus scan")
    args = ap.parse_args()

    day = None if args.day == "all" else args.day
    res = scan(day)

    if args.verify:
        ref = scan(day, full=True)
        drift = abs(ref["total"] - res["total"])
        print(f"incremental ${res['total']:,.4f} ({res['files']} files) vs "
              f"full ${ref['total']:,.4f} ({ref['files']} files) -> drift ${drift:,.4f}")
        # A cent of drift over hundreds of dollars is float noise; anything more means the
        # mtime skip dropped real rows and the fast path cannot be trusted to gate a halt.
        return 0 if drift < 0.01 else 1

    if args.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print(fmt(res, args.cap))

    if args.cap and res["total"] >= args.cap:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

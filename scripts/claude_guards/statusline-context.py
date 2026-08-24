#!/usr/bin/env python3
"""statusline-context.py — Claude Code status line that surfaces the ONE number
that drives token cost: live resident context (input + cache_read + cache_creation
of the most recent turn). cache_read ~= turns x resident_context, so a session that
quietly grows to ~900K context and runs for days is ~all of the cost. This makes
that growth visible and nags you to /clear or /compact before it snowballs.

Claude Code pipes a JSON blob on stdin (model, transcript_path, cwd, cost, ...).
We tail the transcript for the last assistant `usage` and render one compact line.
Output must be a single line; ANSI colors are supported.
"""
import json, os, sys

# context thresholds (tokens) -> (emoji, ansi color, optional nudge)
GREEN, YELLOW, RED, BOLD, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"

def tail_bytes(path, n=200_000):
    """Read the last n bytes of a (possibly huge) transcript without loading it all."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > n:
                fh.seek(size - n)
                fh.readline()  # discard partial first line
            return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""

def last_resident(path):
    """Resident context of the most recent assistant turn, and its model."""
    resident, model = 0, None
    for line in tail_bytes(path).splitlines():
        line = line.strip()
        if not line or '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") != "assistant":
            continue
        u = (rec.get("message") or {}).get("usage") or {}
        if not u:
            continue
        resident = (u.get("input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0) \
            + (u.get("cache_creation_input_tokens", 0) or 0)
        model = (rec.get("message") or {}).get("model")
    return resident, model

def fmt_tok(n):
    return f"{n/1000:.0f}K" if n < 1_000_000 else f"{n/1_000_000:.2f}M"

HISTORY = os.path.expanduser("~/.claude/estate-spend-history.jsonl")
BUDGET = os.path.expanduser("~/.claude/estate-budget.json")

def estate_spend():
    """Today's ESTATE-WIDE spend, from the sentinel's cached history.

    Deliberately a cache read, not a scan: this renders on every keystroke-ish refresh and
    `estate_spend.scan()` takes ~30s. The sentinel (launchd, every 15m) does the scanning
    and writes the row; here we only tail one line.

    Why the estate number and not this session's: on 2026-08-06 interactive coding was
    $426.93 of a $1,008.73 day spread over 40 sessions averaging $8.39. No single session
    looked alarming, which is exactly how the day got to $1,008 unnoticed. The per-session
    figure is the one that misleads; the estate total is the one that bites.

    Stale rows are shown as stale rather than hidden — a number that silently stops updating
    is worse than no number, because it reads as "spend has stopped".
    """
    try:
        raw = tail_bytes(HISTORY, 4000).strip().splitlines()
        if not raw:
            return None
        row = json.loads(raw[-1])
        if row.get("day") != __import__("datetime").date.today().isoformat():
            return None  # yesterday's row is not today's spend
        import datetime as _dt
        age_min = (_dt.datetime.now()
                   - _dt.datetime.fromisoformat(row["at"])).total_seconds() / 60
        return float(row["total"]), age_min
    except Exception:
        return None

def spend_segment():
    """One coloured `$today` segment, or '' if the sentinel has never run."""
    got = estate_spend()
    if not got:
        return ""
    total, age_min = got
    try:
        with open(BUDGET) as fh:
            cfg = json.load(fh)
        warn = float(cfg.get("warn_usd") or 0)
        halt = float(cfg.get("halt_usd") or 0)
    except Exception:
        warn, halt = 0.0, 0.0
    if halt and total >= halt:
        col, mark = RED, "■"
    elif warn and total >= warn:
        col, mark = RED if total >= warn * 2 else YELLOW, "▲"
    else:
        col, mark = GREEN, "●"
    # >45m means roughly three missed 15-minute runs: the job is wedged, not merely between ticks.
    stale = f"{DIM} ({age_min/60:.0f}h old){RESET}" if age_min > 45 else ""
    return f"{col}{mark} ${total:,.0f} estate/day{RESET}{stale}"

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    model = (data.get("model") or {}).get("display_name") or "?"
    cwd = data.get("workspace", {}).get("current_dir") or data.get("cwd") or ""
    proj = os.path.basename(cwd.rstrip("/")) if cwd else ""
    transcript = data.get("transcript_path") or ""

    resident, tmodel = last_resident(transcript) if transcript else (0, None)

    # color + nudge by how close we are to the danger zone the report exposed (500K-967K).
    if resident >= 400_000:
        color, mark, nudge = RED, "■", "  /clear or /compact"
    elif resident >= 200_000:
        color, mark, nudge = YELLOW, "▲", "  getting heavy"
    elif resident >= 100_000:
        color, mark, nudge = YELLOW, "●", ""
    else:
        color, mark, nudge = GREEN, "●", ""

    ctx = f"{color}{mark} ctx {fmt_tok(resident)}{RESET}{DIM}{nudge}{RESET}" if resident else f"{DIM}● ctx –{RESET}"
    parts = [f"{BOLD}{model}{RESET}", ctx]
    spend = spend_segment()
    if spend:
        parts.append(spend)
    if proj:
        parts.append(f"{DIM}{proj}{RESET}")
    print(" │ ".join(parts))

if __name__ == "__main__":
    main()

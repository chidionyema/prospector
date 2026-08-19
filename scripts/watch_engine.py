#!/usr/bin/env python3
"""Live view of what the engine is doing right now.

    .venv/bin/python scripts/watch_engine.py

Two processes run the engine and neither one prints anything you can watch:

  * the PRODUCER (`com.prospector.scheduler`) invents new ideas and puts them in the queue,
  * the CONSUMER (`com.prospector.consumer`) takes ideas off the queue and judges them.

Both write a heartbeat file every 60s and both append to today's audit log, so the state is
already on disk — it just has no viewer. This is the viewer. It reads only; it never writes,
never sends a signal, and never touches the queue, so it is safe to leave running.

Why it tails the audit file by byte offset instead of re-reading it: the file is already
~10MB by mid-afternoon and re-parsing it every 2s would cost more CPU than the engine.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHED = store_root() / "scheduler"
AUDIT_DIR = SCHED / "audit"

# ANSI. Kept to bold/dim/colour only, so the view survives any terminal.
CLEAR = "\033[H\033[2J"
B, D, R = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED, CYAN = "\033[32m", "\033[33m", "\033[31m", "\033[36m"


def _now() -> float:
    return time.time()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text() or "{}")
    except Exception:
        return {}


def _age_s(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds()


def _mins(secs: float | None) -> str:
    if secs is None:
        return "?"
    if secs < 90:
        return f"{int(secs)}s"
    if secs < 5400:
        return f"{secs/60:.0f}m"
    return f"{secs/3600:.1f}h"


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


class AuditTail:
    """Follows today's audit log from wherever it was when we started.

    Rolls over at UTC midnight by re-checking the filename each poll. A missing file is not
    an error — the engine may simply not have logged anything today yet.
    """

    def __init__(self, keep_s: float = 900.0) -> None:
        self.keep_s = keep_s
        self.path: Path | None = None
        self.pos = 0
        self.events: deque[tuple[float, dict]] = deque()

    def _today(self) -> Path:
        return AUDIT_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"

    def poll(self) -> None:
        path = self._today()
        if path != self.path:
            self.path = path
            # Seed from the tail of the file rather than from its end, so the FIRST frame
            # already shows real activity. Starting at the end left `--once` printing
            # "nothing logged yet" over a busy engine. 400KB is ~1500 events here.
            size = path.stat().st_size if path.exists() else 0
            self.pos = max(0, size - 400_000)
        if not path.exists():
            return
        size = path.stat().st_size
        if size < self.pos:      # truncated or rotated under us
            self.pos = 0
        if size == self.pos:
            return
        with path.open("r", errors="replace") as fh:
            fh.seek(self.pos)
            chunk = fh.read()
            self.pos = fh.tell()
        now = _now()
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            # Timestamp each event by WHEN THE ENGINE WROTE IT, not when we read it. With the
            # seeded tail above, arrival time would stamp a 20-minute-old backlog as "now" and
            # the 5-minute rates would read several times too high on the first frame.
            age = _age_s(d.get("ts"))
            self.events.append((now - age if age is not None else now, d))
        cutoff = now - self.keep_s
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()

    def since(self, secs: float) -> list[dict]:
        cutoff = _now() - secs
        return [d for t, d in self.events if t >= cutoff]

    def last(self, event: str) -> dict | None:
        for _, d in reversed(self.events):
            if d.get("event") == event:
                return d
        return None


def _producer_line(hb: dict) -> str:
    pid = hb.get("pid")
    up = _alive(pid)
    age = _age_s(hb.get("ts"))
    phase = hb.get("phase", "?")
    if not up:
        return f"{RED}DOWN{R}  (last beat {_mins(age)} ago, pid {pid})"
    if age is not None and age > 180:
        state = f"{YELLOW}STALLED{R} — no beat for {_mins(age)}"
    elif phase == "sleeping":
        interval = float(hb.get("interval_s") or 0)
        slept = float(hb.get("slept_s") or 0)
        left = max(0.0, interval - slept)
        state = f"{D}waiting{R} — next batch of new ideas in {_mins(left)}"
    else:
        state = f"{GREEN}making new ideas{R} ({phase})"
    return f"{state}   {D}pid {pid} · {hb.get('cycles', 0)} rounds · beat {_mins(age)} ago{R}"


def _consumer_line(hb: dict) -> str:
    pid = hb.get("pid")
    up = _alive(pid)
    age = _age_s(hb.get("ts"))
    if not up:
        return f"{RED}DOWN{R}  (last beat {_mins(age)} ago, pid {pid})"
    phase = hb.get("phase", "?")
    word = {"draining": f"{GREEN}judging ideas{R}", "idle": f"{D}nothing to judge{R}",
            "blocked": f"{YELLOW}held back (paused or over budget){R}"}.get(phase, phase)
    if age is not None and age > 180:
        word = f"{YELLOW}NO BEAT for {_mins(age)}{R} (was {phase})"
    return (f"{word}   {D}pid {pid} · wave {hb.get('cycle', 0)} · "
            f"up to {hb.get('batch', '?')} ideas per wave · "
            f"{hb.get('resumed_total', 0)} judged since start · "
            f"{hb.get('errors', 0)} errors · beat {_mins(age)} ago{R}")


def _now_doing(tail: AuditTail) -> list[str]:
    """The last thing each phase actually did, newest first."""
    out = []
    cs = tail.last("candidate_start")
    cd = tail.last("candidate_done")
    if cs:
        title = (cs.get("title") or cs.get("candidate_id") or "?")[:64]
        out.append(f"{CYAN}idea{R}    {title}")
    s = tail.last("search")
    if s:
        q = (s.get("query") or "")[:70]
        out.append(f"{CYAN}search{R}  {D}{s.get('provider','?')} · "
                   f"{s.get('returned_n','?')} results · "
                   f"{int(s.get('latency_ms') or 0)/1000:.1f}s{R}  {q}")
    cr = tail.last("check_result")
    if cr:
        out.append(f"{CYAN}check{R}   {cr.get('check','?')} → {cr.get('verdict','?')} "
                   f"{D}conf {cr.get('confidence','?')}{R}")
    if cd:
        out.append(f"{CYAN}ruled{R}   {cd.get('decision', cd.get('verdict','?'))} "
                   f"{D}{(cd.get('title') or '')[:50]}{R}")
    return out or [f"{D}(nothing logged yet — the viewer starts at the end of the log){R}"]


def _rate_block(tail: AuditTail) -> str:
    w5 = Counter(d.get("event") for d in tail.since(300))
    searches = w5.get("search", 0)
    esc = w5.get("search_relevance_escalate", 0)
    checks = w5.get("check_result", 0)
    started = w5.get("candidate_start", 0)
    done = w5.get("candidate_done", 0)
    lat = [d.get("latency_ms") or 0 for d in tail.since(300) if d.get("event") == "search"]
    med = sorted(lat)[len(lat) // 2] / 1000 if lat else 0.0
    return (f"last 5 min   {B}{searches}{R} searches ({esc} second opinions, median "
            f"{med:.1f}s) · {B}{checks}{R} checks finished · "
            f"{B}{started}{R} ideas started, {B}{done}{R} ruled")


def _local(iso: str | None) -> str:
    """Wall-clock time in the founder's own timezone. The engine stamps everything UTC,
    which is an hour off local here — a run list that reads 04:29 for something that
    happened at 05:29 is worse than no timestamp, because it looks authoritative."""
    if not iso:
        return "  ?  "
    try:
        t = datetime.fromisoformat(iso)
    except Exception:
        return "  ?  "
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone().strftime("%H:%M:%S")


def _run_rows(runs: list[dict], limit: int = 6) -> list[str]:
    """One line per engine run, newest first, every one of them time-stamped.

    A run is a process's slice of the audit log: `run_id` + pid, bounded by the first and
    last event it wrote. `last_ts` is therefore "when it last did something", which is why
    a run whose last event is within one heartbeat is shown as still going rather than
    finished — the log cannot tell us it exited, only that it went quiet.
    """
    rows = sorted(runs, key=lambda r: r.get("last_ts") or "", reverse=True)[:limit]
    out = []
    for r in rows:
        started, ended = r.get("first_ts"), r.get("last_ts")
        dur = (_age_s(started) or 0) - (_age_s(ended) or 0)
        quiet = _age_s(ended)
        live = quiet is not None and quiet < 90
        mark = f"{GREEN}▶{R}" if live else f"{D}■{R}"
        decisions = r.get("decisions") or {}
        verdicts = " ".join(f"{k}:{v}" for k, v in sorted(decisions.items())) or "—"
        errs = int(r.get("search_errors") or 0)
        err = f" {YELLOW}{errs} search errors{R}" if errs else ""
        out.append(
            f"{mark} {_local(started)}→{_local(ended)} "
            f"{D}({_mins(dur)}, {'now' if live else _mins(quiet) + ' ago'}){R}  "
            f"pid {r.get('pid','?'):<6} {r.get('candidates',0)} ideas · "
            f"{r.get('checks',0)} checks · {r.get('searches',0)} searches · {verdicts}{err}")
    return out


def render(tail: AuditTail, queue: dict, queue_age: float, runs: list[dict]) -> str:
    prod = _read_json(SCHED / "heartbeat.json")
    cons = _read_json(SCHED / "consumer_heartbeat.json")
    lines = [
        f"{B}PROSPECTOR ENGINE{R}   {datetime.now().strftime('%H:%M:%S')}   "
        f"{D}ctrl-c to stop{R}",
        "",
        f"{B}PRODUCER{R}  invents ideas      {_producer_line(prod)}",
        f"{B}CONSUMER{R}  judges them        {_consumer_line(cons)}",
        "",
    ]
    if queue:
        bl = queue.get("backlog", {})
        by = queue.get("by_decision", {})
        lines += [
            f"{B}QUEUE{R}     {B}{bl.get('workable', '?')}{R} ideas waiting to be judged"
            f"   {D}(judged so far: {by.get('pass',0)} passed, {by.get('kill',0)} rejected)"
            f" · oldest {_mins(_age_s(bl.get('oldest_created_at')))} old"
            f" · read {int(queue_age)}s ago{R}",
            "",
        ]
    lines.append(f"{B}RIGHT NOW{R}")
    lines += ["  " + s for s in _now_doing(tail)]
    lines += ["", "  " + _rate_block(tail)]
    if runs:
        lines += ["", f"{B}RECENT RUNS{R}  {D}started · ended · how long · how long ago{R}"]
        lines += ["  " + s for s in _run_rows(runs)]
    if (SCHED / "PAUSE").exists():
        lines += ["", f"{RED}PAUSE file present — the whole engine is stopped{R}"]
    if (SCHED / "PAUSE_GENERATION").exists():
        lines += ["", f"{YELLOW}PAUSE_GENERATION present — no new ideas, judging continues{R}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between refreshes (default 2)")
    ap.add_argument("--queue-every", type=float, default=20.0,
                    help="seconds between queue reads; it costs ~1.8s of sqlite (default 20)")
    ap.add_argument("--once", action="store_true", help="print one frame and exit")
    args = ap.parse_args(argv)

    tail = AuditTail()
    queue: dict = {}
    runs: list[dict] = []
    queue_read_at = 0.0
    try:
        from prospector.ops import readmodel as R
        from prospector.ops import runs as RUNS
        cfg = R.load_cfg()
    except Exception as exc:                                   # pragma: no cover - env issue
        print(f"cannot load config: {exc}", file=sys.stderr)
        return 2

    try:
        while True:
            tail.poll()
            if _now() - queue_read_at >= args.queue_every:
                try:
                    queue = R.queue_view(cfg)
                except Exception:
                    queue = queue or {}
                try:
                    runs = (RUNS.run_index(days=1) or {}).get("runs") or runs
                except Exception:
                    pass
                queue_read_at = _now()
            frame = render(tail, queue, _now() - queue_read_at, runs)
            sys.stdout.write(("" if args.once else CLEAR) + frame)
            sys.stdout.flush()
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

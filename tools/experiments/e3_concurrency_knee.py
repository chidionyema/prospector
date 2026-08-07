#!/usr/bin/env python3
"""E3 — where the Claude-CLI concurrency knee sits, re-probed post-cursor_cli.

The register (`docs/COMMERCIAL_READINESS_PROGRAM.md` §3 row E3, §16 "E3 — the methodology,
recovered") records that the 2026-07-31 numbers came from an AD-HOC run that survives only as
a comment at `config.yaml:127-131`. There was no script. This is the script, so the next
re-probe is a command rather than an afternoon.

WHAT IT DRIVES. `PROSPECTOR_CLAUDE_CONCURRENCY` (`prospector/claude_cli.py:46`), not the
config key. `_MAX_CLI` and the governor are bound AT IMPORT (`claude_cli.py:46,49`) and
`configure_concurrency` returns early whenever the env var is set (`:60-62`) — so a single
process cannot honestly sweep N. Each level therefore runs in its own SUBPROCESS with the env
var exported, which is also exactly how an operator would drive it.

WHAT A COLLISION MEANS, AND HOW THIS DETECTS ONE. Claude Code derives its per-project session
slug from the CWD PATH, so concurrent `claude -p` in a shared directory clobber each other's
session state and degrade to non-JSON meta output (proven 2026-07-02: concurrency=2 → 0/3
candidates, serialized → 2/3). Every call here carries a UNIQUE token and is asked to echo it
back. Three outcomes are then distinguishable, where a pass/fail count alone would conflate
them:

  * `ok`            — the call returned its OWN token;
  * `cross_talk`    — it returned a DIFFERENT call's token. That is session clobbering caught
                      red-handed, and it is the failure the whole knee question is about;
  * `malformed`     — it returned neither (meta output, prose, an exception).

THE PROBE MUST NOT "FIX" COLLISIONS BY RANDOMISING CWD. `claude_cli.py:150-176` binds the cwd
to the governor's SLOT INDEX precisely so the path is stable across calls; a mkdtemp-per-call
variant cost $412.19 of pure cache_write in one day. This script changes nothing about that —
it only sets N and measures. If the knee has moved, the answer is a different N, never a
different cwd policy.

QUIET DAEMON REQUIRED. The daemon competes for the same machine-wide flock slots
(`cli_governor.py`), so a probe run against a live tick measures contention, not the knee.
`--require-quiet` (default on) refuses to start unless `store/scheduler/PAUSE_GENERATION` (or
`PAUSE`) is present, and the receipt records which. Note that PAUSE_GENERATION is a HALF stop:
it leaves the re-vet drain running, so it does not by itself prove the machine was quiet. On
the 2026-08-07 sweep it happened not to matter and that was checked rather than assumed - the
last tick row in `store/scheduler/ticks.jsonl` was 21:51:59 and the sweep ran from 22:29, so
the daemon wrote nothing during the window and daemon contention is REFUTED as the explanation
of that sweep's spread. It is not refuted in general; use `PAUSE` for a full stop.

EQUAL CALL BUDGET PER LEVEL, and why the first design could not have worked. Each level used
to fire exactly N calls, so the fixed cost of the level - subprocess spawn plus the cold CLI
start its first call pays - was spread over 1 call at N=1 and over 8 at N=8. `calls_per_s`
then measured overhead amortisation and concurrency mixed together, and since the N=1 row was
the denominator of every ratio, the table reported 34x and 50x throughput against a governor
capped at 8. Arithmetically impossible, so the design was wrong, not the machine: the
2026-08-07 sweep read four IDENTICAL N=1 measurements as 5.26s, 44.33s, 207.32s and 211.02s,
a 40x spread on a one-call-per-level baseline. Every level now runs the same number of
measured calls (`--calls-per-level`, default 16) in waves of N, and each level discards its
own first wave, so the fixed cost is paid once per level and is outside the measured wall
whatever N is.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NAME = "E3"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E3), §16 'E3 — the methodology, recovered'"

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LEVELS = (1, 4, 6, 8)
# Per-call timeout. Generous: this measures the knee, and a call that is merely slow under
# load is the SIGNAL, not a failure. Anything past this is a genuine hang.
CALL_TIMEOUT_S = 180


def describe() -> str:
    return ("E3: sweeps PROSPECTOR_CLAUDE_CONCURRENCY (one subprocess per level) and measures "
            "p50/max call latency, throughput and CROSS-TALK — the collision the knee is about.")


# ---------------------------------------------------------------------------
# worker half — runs inside a subprocess with PROSPECTOR_CLAUDE_CONCURRENCY set
# ---------------------------------------------------------------------------

def _worker(n: int, calls: int, warm_waves: int) -> dict[str, Any]:
    """Run `calls` measured calls at concurrency n, in waves of n, discarding `warm_waves`.

    Imported HERE, not at module top: the whole point is that `claude_cli` binds the governor
    at import, so the import must happen after the env var is set in this process.
    """
    from prospector.claude_cli import _MAX_CLI, run_claude_cli
    from prospector.errors import classify_exhaustion

    # Deliberately trivial and deterministic. This measures the TRANSPORT (subprocess spawn,
    # session setup, governor queueing), not the model's reasoning, so a heavier prompt would
    # add variance without adding signal.
    def _prompt(tok: str) -> str:
        return (f"Reply with ONLY this exact string and nothing else: {tok}")

    def _wave() -> tuple[list[dict[str, Any]], float]:
        tokens = [uuid.uuid4().hex[:12] for _ in range(n)]

        def _one(i: int) -> dict[str, Any]:
            t0 = time.monotonic()
            try:
                # retries=0: this is a measurement, not a resilience test. A retried call would
                # report a latency that no real caller ever experiences.
                text = run_claude_cli(_prompt(tokens[i]), timeout=CALL_TIMEOUT_S, retries=0)
                err = None
            except Exception as e:  # noqa: BLE001 — every failure mode is a datum here
                text, err = "", f"{type(e).__name__}: {e}"
            return {"i": i, "latency_s": round(time.monotonic() - t0, 3),
                    "text": (text or "")[:400], "error": err}

        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=n) as pool:
            # All n submitted at once — the GOVERNOR is what limits real parallelism, which is
            # the thing under test. Capping the pool at n instead would measure the pool.
            results = list(pool.map(_one, range(n)))
        wall = time.monotonic() - t0

        for r in results:
            own = tokens[r["i"]]
            others = [t for j, t in enumerate(tokens) if j != r["i"]]
            if r["error"]:
                r["outcome"] = "error"
            elif own in r["text"]:
                r["outcome"] = "ok"
            elif any(t in r["text"] for t in others):
                r["outcome"] = "cross_talk"
            else:
                r["outcome"] = "malformed"
            del r["text"]  # the token is the datum; the prose is noise in a receipt
        return results, wall

    # The per-level warm-up. Discarded, and discarded INSIDE the level rather than once for the
    # whole sweep, because the cost it absorbs (this subprocess's cold CLI start) is paid once
    # per level. A single sweep-wide warm-up leaves it inside whichever level runs first.
    warm: list[dict[str, Any]] = []
    warm_wall = 0.0
    for _ in range(warm_waves):
        wr, ww = _wave()
        warm.extend(wr)
        warm_wall += ww

    waves = max(1, -(-calls // n))  # ceil, so every level gets at least `calls` measured calls
    measured: list[dict[str, Any]] = []
    wall_s = 0.0
    aborted: str | None = None
    for _ in range(waves):
        res, w = _wave()
        measured.extend(res)
        wall_s += w
        # SELF-HEAL: stop spending into a provider already known to be dead. Run #6 on
        # 2026-08-07 hit the account's monthly spend limit part-way through and then ran 50
        # further calls, every one of which failed the same way — and, worse, POOLED those
        # zero-throughput waves into the same rows as the good ones, so the table reported a
        # billing outage as a property of N. A permanent exhaustion is not a datum about
        # concurrency; it is the end of the measurement. Transient backpressure is left alone
        # deliberately: a call that is merely slow or 429'd under load IS the signal here.
        perm = [r for r in res if r["error"]
                and classify_exhaustion(r["error"]) == "permanent"]
        if perm:
            aborted = f"permanent_exhaustion: {perm[0]['error'][:200]}"
            break

    return {"n": n, "governor_max": _MAX_CLI, "wall_s": round(wall_s, 3),
            "waves": waves, "waves_run": len(measured) // max(1, n), "warm_waves": warm_waves,
            "aborted": aborted,
            "warm_wall_s": round(warm_wall, 3),
            "warm_outcomes": {o: sum(1 for r in warm if r["outcome"] == o)
                              for o in {r["outcome"] for r in warm}},
            "calls": measured}


# ---------------------------------------------------------------------------
# parent half
# ---------------------------------------------------------------------------

def _quiet_state() -> dict[str, Any]:
    sched = REPO / "store" / "scheduler"
    return {
        "PAUSE": (sched / "PAUSE").exists(),
        "PAUSE_GENERATION": (sched / "PAUSE_GENERATION").exists(),
    }


def _foreign_cli_census(own_pids: set[int]) -> dict[str, Any]:
    """Every `claude -p` on the machine that is NOT this probe's.

    A pause file is a statement about PROSPECTOR, and the governor is machine-wide, so a pause
    file is not a statement about the machine. Observed live on 2026-08-07 during this very
    sweep, at a moment when `store/scheduler/PAUSE` existed:

      * pid 49184, ppid 11795 - the paused scheduler daemon, running a verdict call anyway
        (PAUSE is read at tick START, so an in-flight tick walks straight through it);
      * pids 48628 / 49138, ppid 46096 - the HERMES estate executor
        (`~/.hermes/executor-settings.json`), a different estate entirely, which no prospector
        pause file can reach.

    Both take the same machine-wide flock slots this probe is trying to measure. The census is
    recorded per level so a contaminated table says so on its face instead of being read as a
    statement about N.
    """
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid,command"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception as e:  # noqa: BLE001 - an unmeasurable environment is itself a datum
        return {"error": f"{type(e).__name__}: {e}"}
    foreign: list[dict[str, Any]] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3 or "claude -p" not in parts[2]:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        if pid in own_pids or ppid in own_pids:
            continue
        kind = ("hermes_executor" if "hermes" in parts[2]
                else "prospector_daemon" if ppid in _daemon_pids()
                else "unknown")
        foreign.append({"pid": pid, "ppid": ppid, "kind": kind})
    return {"count": len(foreign), "procs": foreign[:12],
            "kinds": sorted({f["kind"] for f in foreign})}


def _daemon_pids() -> set[int]:
    try:
        out = subprocess.run(["pgrep", "-f", "prospector.scheduler.run_scheduled"],
                             capture_output=True, text=True, timeout=10).stdout
        return {int(x) for x in out.split() if x.strip().isdigit()}
    except Exception:  # noqa: BLE001
        return set()


def _run_level(n: int, calls: int, warm_waves: int) -> dict[str, Any]:
    env = dict(os.environ)
    env["PROSPECTOR_CLAUDE_CONCURRENCY"] = str(n)
    # cwd=REPO is not enough: this file is run by absolute path, so the child's sys.path[0] is
    # tools/experiments/, not the repo root, and `import prospector` fails.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    waves = max(1, -(-calls // n)) + warm_waves
    # Scales with the WAVE COUNT. A fixed budget silently truncated N=1, which needs
    # `calls` sequential waves where N=8 needs `calls`/8.
    deadline = time.time() + CALL_TIMEOUT_S * waves + 120
    # Files, not PIPEs. Polling the child for a census means NOT reading its pipes, and a
    # worker that fills the 64KB buffer would block forever on a write while this loop waits
    # forever for an exit — a deadlock that would look exactly like a slow level.
    with tempfile.TemporaryDirectory() as td:
        op, ep = Path(td) / "out", Path(td) / "err"
        with op.open("w") as ofh, ep.open("w") as efh:
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--worker", "--n", str(n),
                 "--calls", str(calls), "--warm-waves", str(warm_waves)],
                stdout=ofh, stderr=efh, text=True, cwd=str(REPO), env=env)
            # Sample the machine WHILE the level runs, not before it. A pre-level census would
            # miss a daemon tick that starts mid-level, which is what happened on 2026-08-07.
            own = {proc.pid}
            census = {"count": 0, "procs": [], "kinds": []}
            while proc.poll() is None:
                if time.time() > deadline:
                    proc.kill()
                    raise RuntimeError(f"level N={n} exceeded {CALL_TIMEOUT_S * waves + 120}s")
                c = _foreign_cli_census(own)
                if c.get("count", 0) > census["count"]:
                    census = c
                time.sleep(5)
        out, err = op.read_text(), ep.read_text()
    marker = "@@E3@@"
    for line in out.splitlines():
        if line.startswith(marker):
            res = json.loads(line[len(marker):])
            res["foreign_cli_peak"] = census
            return res
    raise RuntimeError(
        f"level N={n} produced no result line. stderr tail: {err.strip()[-500:]!r} "
        f"stdout tail: {out.strip()[-300:]!r}")


def _summarise(reps: list[dict[str, Any]], baseline_rate: float | None) -> dict[str, Any]:
    """Pool every repetition of one level into a single row.

    Pooling, not averaging-of-medians: one rep at N=1 is a p50 over ONE call, and the first
    version of this probe reported exactly that. The 24% swing between two single-call
    readings of the same level is why `--reps` exists at all — a knee ruled off a
    one-sample denominator is a coin flip with a decimal point.
    """
    calls = [c for r in reps for c in r["calls"]]
    lat = sorted(c["latency_s"] for c in calls)
    outcomes: dict[str, int] = {}
    for c in calls:
        outcomes[c["outcome"]] = outcomes.get(c["outcome"], 0) + 1
    n = reps[0]["n"]
    walls = [r["wall_s"] for r in reps]
    # Rate, not wall time: reps of the same level are independent batches, so calls/sec is the
    # quantity that composes across them. The numerator is the number of calls actually
    # MEASURED (`len(r["calls"])`), never the level's N — every level now runs the same call
    # budget in waves, so N is not a call count.
    rate = len(calls) / sum(walls) if sum(walls) > 0 else None
    row = {
        "n": n,
        "reps": len(reps),
        "calls": len(calls),
        "governor_max": reps[0]["governor_max"],
        "ok": outcomes.get("ok", 0),
        "cross_talk": outcomes.get("cross_talk", 0),
        "malformed": outcomes.get("malformed", 0),
        "error": outcomes.get("error", 0),
        "p50_s": round(statistics.median(lat), 2) if lat else None,
        "p90_s": round(lat[int(0.9 * (len(lat) - 1))], 2) if lat else None,
        "max_s": round(max(lat), 2) if lat else None,
        "wall_s_per_rep": [round(w, 2) for w in walls],
        "calls_per_s": round(rate, 3) if rate else None,
    }
    if baseline_rate and rate:
        row["throughput_x"] = round(rate / baseline_rate, 2)
    return row


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="runner.py run E3")
    ap.add_argument("--levels", default=",".join(str(x) for x in DEFAULT_LEVELS),
                    help="comma-separated N values (default 1,4,6,8)")
    ap.add_argument("--allow-live-daemon", action="store_true",
                    help="run even with no PAUSE file. The measurement is then contaminated by "
                         "the daemon competing for the same machine-wide governor slots, and "
                         "the receipt says so.")
    ap.add_argument("--calls-per-level", type=int, default=16,
                    help="measured calls per level per rep (default 16). EQUAL across levels on "
                         "purpose: a per-level fixed cost spread over 1 call at N=1 and 8 at "
                         "N=8 is what produced the impossible 50x throughput row.")
    ap.add_argument("--warm-waves", type=int, default=1,
                    help="waves discarded at the start of EVERY level (default 1), absorbing "
                         "that subprocess's cold CLI start. 0 reproduces the artefact.")
    ap.add_argument("--no-repeat", action="store_true",
                    help="skip re-running the first level at the end (the ordering control).")
    ap.add_argument("--reps", type=int, default=2,
                    help="repetitions per level, interleaved (default 2). Each rep is already "
                         "--calls-per-level calls, so the reps buy separation in TIME, not "
                         "sample size.")
    ap.add_argument("--min-gain", type=float, default=0.15,
                    help="throughput gain over the previous level required to keep climbing "
                         "(default 0.15).")
    ns = ap.parse_args(args)
    levels = [int(x) for x in ns.levels.split(",") if x.strip()]

    quiet = _quiet_state()
    is_quiet = quiet["PAUSE"] or quiet["PAUSE_GENERATION"]
    if not is_quiet and not ns.allow_live_daemon:
        raise SystemExit(
            "REFUSING: neither store/scheduler/PAUSE nor PAUSE_GENERATION is present, so the "
            "daemon is free to take machine-wide governor slots mid-probe and this would "
            "measure contention rather than the knee. Create PAUSE_GENERATION (it halts "
            "generation while leaving the re-vet drain running), run the probe, and DELETE it "
            "afterwards. Override with --allow-live-daemon if you want the contaminated number.")

    print(f"E3 concurrency knee — levels {levels}")
    print(f"  daemon quiet: {is_quiet}  ({quiet})")
    print(f"  {ns.calls_per_level} measured calls per level per rep, "
          f"{ns.warm_waves} discarded wave(s) per level")
    if not is_quiet:
        print("  ⚠ CONTAMINATED: running against a live daemon by explicit request.")

    # Levels are INTERLEAVED across reps (1,4,6,8, 1,4,6,8, …) rather than run
    # rep-after-rep per level. If machine load drifts during the sweep, interleaving spreads
    # that drift across every level instead of loading it entirely onto whichever level
    # happened to run while it was busy.
    by_level: dict[int, list[dict[str, Any]]] = {n: [] for n in levels}
    sweep_aborted: str | None = None
    for rep_i in range(ns.reps):
        for n in levels:
            print(f"  rep {rep_i + 1}/{ns.reps}  N={n} … ", end="", flush=True)
            lvl = _run_level(n, ns.calls_per_level, ns.warm_waves)
            by_level[n].append(lvl)
            print(f"wall {lvl['wall_s']}s over {len(lvl['calls'])} calls "
                  f"(discarded {lvl['warm_wall_s']}s)"
                  + ("  ⛔ ABORTED" if lvl.get("aborted") else ""))
            if lvl.get("aborted"):
                sweep_aborted = lvl["aborted"]
                # Drop the partial level entirely rather than pooling it. A level that stopped
                # early is not a slower level; it is an unmeasured one, and averaging it in is
                # exactly how run #6 reported a spend limit as a property of N.
                by_level[n].pop()
                break
        if sweep_aborted:
            break

    # ORDERING CONTROL: the first level, once more, at the very end. If the two readings of
    # the same N disagree, the table is about the clock rather than about N.
    repeat = None
    if not ns.no_repeat and levels:
        print(f"  N={levels[0]} (ordering control, last) … ", end="", flush=True)
        repeat = _run_level(levels[0], ns.calls_per_level, ns.warm_waves)
        print(f"wall {repeat['wall_s']}s")

    if sweep_aborted:
        print()
        print(f"  ⛔ SWEEP ABORTED — {sweep_aborted}")
        print("     No knee is reported. A partial sweep cannot be compared across levels: the "
              "levels that ran and the levels that did not are not two readings of the same "
              "machine. Restore the allowance and re-run.")
        levels = [n for n in levels if by_level[n]]
        if not levels:
            return {"headline": {"aborted": sweep_aborted, "knee_n": None,
                                 "levels_completed": []},
                    "quiet_state": quiet}

    base_reps = by_level.get(1) or by_level[levels[0]]
    base_row = _summarise(base_reps, None)
    baseline_rate = base_row["calls_per_s"]
    table = [_summarise(by_level[n], baseline_rate) for n in levels]

    total_calls = sum(r["calls"] for r in table)
    total_cross = sum(r["cross_talk"] for r in table)
    total_bad = sum(r["cross_talk"] + r["malformed"] + r["error"] for r in table)

    # THE KNEE RULE, and why it is a throughput rule rather than the latency rule this probe
    # first used. Concurrency is bought for throughput and paid for in per-call latency, so a
    # rule that disqualifies any N whose p50 rose is a rule that always answers N=1 — it did,
    # on the first clean sweep here, while throughput was still climbing at N=8. The knee is
    # therefore the largest N that is still EARNING its latency: every step up to it added at
    # least `--min-gain` (default 15%) of throughput over the previous level, and returned
    # every call clean. Latency inflation is reported next to it, never used to veto it.
    knee, gains = None, []
    prev_rate = None
    for r in table:
        gain = None if prev_rate in (None, 0) else round(r["calls_per_s"] / prev_rate - 1, 3)
        gains.append({"n": r["n"], "gain_over_prev": gain})
        clean = r["cross_talk"] == 0 and r["malformed"] == 0 and r["error"] == 0
        if clean and (gain is None or gain >= ns.min_gain):
            knee = r["n"]
        elif clean and gain is not None and gain < ns.min_gain:
            break
        prev_rate = r["calls_per_s"]

    p50_1 = base_row["p50_s"]
    print()
    hdr = (f"  {'N':>3} {'calls':>6} {'ok':>4} {'xtalk':>6} {'bad':>4} {'p50_s':>7} "
           f"{'p90_s':>7} {'max_s':>7} {'call/s':>7} {'thru_x':>7} {'p50/p50_1':>10}")
    print(hdr)
    for r in table:
        infl = f"{r['p50_s'] / p50_1:.2f}x" if p50_1 and r["p50_s"] else "—"
        print(f"  {r['n']:>3} {r['calls']:>6} {r['ok']:>4} {r['cross_talk']:>6} "
              f"{r['malformed'] + r['error']:>4} {str(r['p50_s']):>7} {str(r['p90_s']):>7} "
              f"{str(r['max_s']):>7} {str(r['calls_per_s']):>7} "
              f"{str(r.get('throughput_x', '—')):>7} {infl:>10}")
    ordering = None
    if repeat is not None:
        first = table[0]
        rep = _summarise([repeat], baseline_rate)
        if first["p50_s"] and rep["p50_s"]:
            drift = abs(rep["p50_s"] - first["p50_s"]) / first["p50_s"]
            ordering = {"n": repeat["n"], "p50_pooled_s": first["p50_s"],
                        "p50_last_s": rep["p50_s"], "drift_frac": round(drift, 3),
                        "order_effect_material": drift > 0.25}
    print()
    if ordering:
        verdict = ("ORDER EFFECT — treat the table as a statement about the clock"
                   if ordering["order_effect_material"] else "no material order effect")
        print(f"  ordering control: N={ordering['n']} p50 {ordering['p50_pooled_s']}s pooled vs "
              f"{ordering['p50_last_s']}s at the end ({ordering['drift_frac']:.0%}) — {verdict}")
    parts = []
    for g in gains:
        v = g["gain_over_prev"]
        parts.append(f"N={g['n']}:" + ("—" if v is None else f"{v:+.0%}"))
    print("  throughput gain over the previous level: " + ", ".join(parts))
    print(f"  knee (largest N still adding >= {ns.min_gain:.0%} throughput, zero bad calls): "
          f"N={knee}")
    if ordering and ordering["order_effect_material"]:
        print("  ⚠ the knee above is NOT trustworthy while the ordering control disagrees "
              "with itself — re-run with the levels reversed before quoting it.")
    if total_cross:
        print(f"  ⚠ CROSS-TALK OBSERVED on {total_cross} call(s) — the per-slot stable cwd "
              "(claude_cli.py:150-176) is not holding at these levels.")

    # A pause file is a statement about prospector; the governor is machine-wide. Report what
    # else was actually holding slots, per level, so the table cannot be read as single-tenant.
    peaks = {n: max((r.get("foreign_cli_peak", {}).get("count", 0) for r in by_level[n]),
                    default=0) for n in levels}
    kinds = sorted({k for n in levels for r in by_level[n]
                    for k in r.get("foreign_cli_peak", {}).get("kinds", [])})
    foreign_peak = max(peaks.values(), default=0)
    if foreign_peak:
        print(f"  ⚠ FOREIGN `claude -p` PROCESSES held slots during the sweep: peak "
              f"{foreign_peak} ({', '.join(kinds) or 'unknown'}); per level " +
              ", ".join(f"N={n}:{peaks[n]}" for n in levels))
        print("    The knee above is therefore the knee ON A SHARED MACHINE, which is the "
              "condition the daemon actually runs in — it is NOT a single-tenant ceiling.")
    else:
        print("  foreign `claude -p` processes during the sweep: none observed (sampled every 5s)")

    return {
        "headline": {
            "levels": levels,
            "knee_n": knee,
            "cross_talk_calls": total_cross,
            "bad_calls": total_bad,
            "total_calls": total_calls,
            "daemon_quiet": is_quiet,
            "foreign_cli_peak": foreign_peak,
            "foreign_cli_kinds": kinds,
            "single_tenant": foreign_peak == 0,
            "aborted": sweep_aborted,
            "order_effect_material": (ordering or {}).get("order_effect_material"),
        },
        "quiet_state": quiet,
        "foreign_cli_peak_by_level": peaks,
        "table": table,
        "gains": gains,
        "ordering_control": ordering,
        "raw": {str(n): by_level[n] for n in levels},
        "method": {
            "knob": "PROSPECTOR_CLAUDE_CONCURRENCY (claude_cli.py:46), one subprocess per level",
            "reps_per_level": ns.reps,
            "calls_per_level_per_rep": ns.calls_per_level,
            "warm_waves_discarded_per_level": ns.warm_waves,
            "level_order": "interleaved across reps",
            "knee_rule": (f"largest N with zero bad calls that still added >= {ns.min_gain:.0%} "
                          "throughput over the previous level; latency inflation reported, "
                          "never used to veto"),
            "collision_detector": "unique per-call token echoed back; a foreign token is cross_talk",
            "retries": 0,
            "call_timeout_s": CALL_TIMEOUT_S,
            "prior_2026_07_31": {"1": {"p50": 8.9}, "8": {"p50": 9.2, "max": 15.5},
                                 "14": {"p50": 13.1, "max": 34.7}},
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--calls", type=int, default=16)
    ap.add_argument("--warm-waves", type=int, default=1)
    ns, rest = ap.parse_known_args()
    if ns.worker:
        print("@@E3@@" + json.dumps(_worker(ns.n, ns.calls, ns.warm_waves)))
        return
    out = run(rest)
    print(json.dumps(out["headline"], indent=2))


if __name__ == "__main__":
    main()

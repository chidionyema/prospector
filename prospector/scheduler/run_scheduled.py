"""Always-on, unattended generation daemon.

Continuously stocks the catalogue by running bounded blue-sky `generate` batches on a fixed
cadence, with NO human in the loop (founder decision, 2026-06-20). The automated backstop in
`scheduler.guard` (daily spend ceiling + PAUSE kill switch) is what bounds it. See
specs/launch-hardening-execution.md WS2.

Modes:
    python -m prospector.scheduler.run_scheduled --once            # one bounded batch, then exit
    python -m prospector.scheduler.run_scheduled --daemon          # loop forever (default 2h cadence)
    python -m prospector.scheduler.run_scheduled --daemon --interval 3600
    python -m prospector.scheduler.run_scheduled --once --dry-run  # guards only, no generation

Each cycle re-evaluates the guard, so the switches take effect with no restart:
    touch store/scheduler/PAUSE     # daemon idles, re-checking every cycle
    rm    store/scheduler/PAUSE     # daemon resumes

Under launchd the job is KeepAlive, so a crash restarts the daemon automatically.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from prospector.config import load_config
from prospector.errors import GroundingInfrastructureError
from prospector.scheduler.guard import guard_from_config

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 2 * 60 * 60  # 2h cadence — continuous but not a tight spin


def _load_env_file(repo_root: Path | None = None) -> int:
    """Populate os.environ from the repo `.env` BEFORE config/operators read keys.

    The engine reads API keys straight from the process environment; an interactive shell exports
    them, but launchd's clean environment does not (hence API keys not found under launchd).
    There is no python-dotenv in the venv, so this is a deliberately tiny stdlib parser: split each
    line on the FIRST '=' only (values may contain '='), skip comments/blanks, and DO NOT override a
    var already set (an explicit env still wins). Returns how many keys were injected. Secrets stay
    in the gitignored .env — never in the tracked plist.
    """
    root = repo_root or Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    if not env_path.exists():
        return 0
    injected = 0
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        # Strip surrounding matching quotes — .env stores keys as KEY="value"; without this the
        # literal quotes become part of the value and the key is rejected (400 API_KEY_INVALID).
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val
            injected += 1
    return injected


def _store_dir(cfg) -> Path:
    return Path(getattr(cfg, "store_dir", "store"))


# How many backlogged (DEFER / provisional) candidates one tick may re-vet before it
# generates. Deliberately small: measured 2026-07-02 a fully-grounded candidate takes ~10 min
# on the claude_cli chain, and the tick's hard deadline is 3h with generation already using
# most of it. At 3 per tick and a 2h interval this drains the 113-item backlog found on
# 2026-08-05 in roughly three days without displacing a single generation batch.
# Override in config under `schedule.resume_per_tick`; 0 disables the drain entirely.
_RESUME_PER_TICK_DEFAULT = 3


def _batch_size(cfg, override: int | None) -> int:
    if override is not None:
        return override
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        return int(schedule.get("batch_size", 5) or 5)
    return int(getattr(schedule, "batch_size", 5) or 5)


def _ticks_path(cfg) -> Path:
    d = _store_dir(cfg) / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ticks.jsonl"


def _append_tick(cfg, tick: dict) -> None:
    path = _ticks_path(cfg)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(tick, default=str) + "\n")
    except OSError as exc:
        logger.error("Failed to write tick log: %s", exc)


def _heartbeat_path(cfg) -> Path:
    d = _store_dir(cfg) / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d / "heartbeat.json"


def _write_heartbeat(cfg, *, phase: str, **extra) -> None:
    """Overwrite a single liveness file the moment a phase changes.

    The completed-tick log (`ticks.jsonl`) only records ticks that FINISH, so a hung or killed
    batch — exactly what a 15–30 min grounded run can do — leaves no trace there. This heartbeat is
    written at the START of work (and on sleep), so a monitor can flag "phase=generating, but
    heartbeat is 40 min stale" as a stall. `next_check` (when set) lets a watchdog tell idle from dead.
    """
    beat = {"ts": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), "phase": phase, **extra}
    try:
        _heartbeat_path(cfg).write_text(json.dumps(beat, default=str), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write heartbeat: %s", exc)


def _resume_per_tick(cfg) -> int:
    """How many backlogged candidates one tick may re-vet. 0 disables the drain."""
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        return max(0, int(schedule.get("resume_per_tick", _RESUME_PER_TICK_DEFAULT) or 0))
    return max(0, int(getattr(schedule, "resume_per_tick", _RESUME_PER_TICK_DEFAULT) or 0))


def _default_generate(cfg, batch_size: int) -> dict:
    """Run one bounded blue-sky generation batch in-process and publish PASSes.

    Returns a small summary dict. Generation may DEFER (moat providers exhausted in a headless
    environment) — that surfaces as an exception which the caller records as a soft error; the
    daemon keeps looping and the signal is recoverable via `generate --resume` / `vet --resume`.

    Before generating, this drains a few of the DEFER/provisional backlog. That drain is the
    thing the phrase "auto re-vet via `vet --resume`" in `alerts.py` promised and nothing
    delivered: measured 2026-08-05 there were 113 `*.defer.json` dossiers on disk, the oldest
    from 2026-06-24, and no scheduler path or launchd plist ever invoked the command. Every one
    of them had already been paid for through generation and prescreen and was then stranded by
    a transient moat outage.

    It runs BEFORE generation, not after, on purpose: a backlogged candidate is strictly cheaper
    to finish than a new one is to create (generation and prescreen are already spent on it), and
    the tick's hard deadline can force-exit mid-tick — whatever runs second is what gets dropped.
    It is bounded per tick because the spend guard evaluates once, before the tick.
    """
    from prospector.run import run_signal, _resolve_lanes, resume_deferred

    resumed = None
    n_resume = _resume_per_tick(cfg)
    if n_resume:
        try:
            resumed = resume_deferred(cfg, limit=n_resume, publish=True)
            logger.info("Tick resume pass: %s", resumed)
            # STDERR, not stdout. Under launchd the two streams land in DIFFERENT files
            # (`StandardOutPath`=launchd.out.log, `StandardErrorPath`=launchd.err.log) and
            # every other daemon diagnostic — the whole progress stream, progress.py:43 —
            # goes to stderr. Measured 2026-08-05 while the daemon held fd 1 open on it:
            # launchd.out.log was 1 byte, mtime Jun 24. So a print to stdout is not "the
            # daemon log"; it is a file no operator and no probe has ever read. Printing
            # the drain's outcome into a second, empty file is the same invisibility this
            # print exists to fix, just relocated.
            print(f"↻ tick resume pass: {resumed}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            # A drain failure must never cost the tick its generation batch — the backlog has
            # waited weeks already and can wait one more tick. Recorded, not raised.
            resumed = {"error": f"{type(exc).__name__}: {exc}"}
            logger.warning("Tick resume pass failed (generation continues): %s", resumed["error"])
            # PRINTED, not just logged. The daemon's launchd log captures stdout/stderr but
            # NOT logging below CRITICAL — verified 2026-08-05: "TICK HARD DEADLINE"
            # (logger.critical) appears 18 times in launchd.err.log while "Daemon starting"
            # and "Unproductive tick" (both logger.info) appear zero times. So the first live
            # tick after this shipped swallowed the drain's outcome entirely and the pass was
            # indistinguishable from never having run. A failure that only logs at WARNING is
            # invisible here; that is the whole reason this line is a print. It goes to
            # STDERR for the reason spelled out on the success branch above.
            print(f"↻ tick resume pass FAILED (generation continues): {resumed['error']}",
                  file=sys.stderr, flush=True)

    # Multi-lane by default (Part 14). Until 2026-08-01 this call passed no `lanes=`, so
    # run_signal took its no-lane default branch (run.py:604) and every unattended batch ran
    # the single implicit default — `generation.operator_archetype: solo_agent`. The four
    # configured lanes and their small_team/startup archetypes were dead config in the daemon:
    # they were only ever resolved on the CLI paths (run.py:1182/1224/1277/1837). PROVEN by
    # `ambition_tier` being absent from every one of the last 50 dossiers ordered by
    # `created_at`, and by the batch mode-collapsing onto one shape (2026-08-01T03:25 batch:
    # the PASS and all three closest-to-pass kills were "fixed-fee pack for one individual").
    # `_resolve_lanes` honours the same precedence as the CLI (active_lane pins a single tier,
    # else active_lanes); an empty config still yields None => the previous behaviour exactly.
    lanes = _resolve_lanes(cfg, argparse.Namespace(lane=None))
    dossiers = run_signal("", cfg=cfg, k=batch_size, publish=True, lanes=lanes)

    def _decision(d) -> str:
        # Dossier carries `.decision` (a Decision enum) — NOT `.verdict`. Reading the wrong
        # attribute made `passes` structurally always 0, so the zero_yield alert cried wolf on
        # every batch and a real PASS was invisible in telemetry.
        return str(getattr(getattr(d, "decision", None), "value", "")).lower()

    passes = sum(1 for d in dossiers if _decision(d) == "pass")
    defers = sum(1 for d in dossiers if _decision(d) == "defer")
    # A dossier ruled by the EMERGENCY cheap tail (moat exhausted) is `provisional`: it never
    # publishes and auto re-vets. Surfacing the count lets the tick alerter fire a CRITICAL when
    # the trusted moat is down but the cheap tail kept ruling — a silent failure mode that the
    # all-DEFER `moat_deferred` alert misses entirely (provisional batches defer nothing).
    provisional = sum(1 for d in dossiers if getattr(d, "provisional", False))
    out = {"dossiers": len(dossiers), "passes": passes, "defers": defers,
           "provisional": provisional}
    if resumed is not None:
        out["resumed"] = resumed
    return out


# A trickled LLM response body defeats per-recv socket timeouts (proven 2026-07-01: a MiniMax TLS
# read hung the daemon 34+ min while the alert-only watchdog watched it sit dead for 8.5h). No
# single tick may hang the process longer than this; on breach the daemon force-exits and launchd
# KeepAlive (ThrottleInterval=30) relaunches a clean daemon. Default 75 min (env-overridable):
# measured 2026-07-02 a fully-grounded vetted candidate takes ~10 min on the claude_cli chain.
# Batch size 15 + cursor_cli primary (faster) + exa in grounding → ~120-150 min per tick.
# Default bumped to 10800s (3h) on founder directive 2026-07-31. Still env-overridable
# via PROSPECTOR_TICK_DEADLINE_S for tuning without code changes.
# The watchdog's 'generating' stall threshold is derived from this constant (see _liveness) so
# the in-process deadline always fires first and the process self-heals before the watchdog acts.
_TICK_HARD_DEADLINE_S = int(os.environ.get("PROSPECTOR_TICK_DEADLINE_S", "10800"))  # 3h

# After an unproductive tick (error or 0 dossiers despite the guard allowing spend) retry soon
# instead of burning the full 2h cadence idle — one provider blip cost days of ~$0 barren ticks.
_RETRY_BACKOFF_S = 300  # 5 min


def _retry_sleep_s(consecutive: int, interval: int) -> int:
    """Seconds to sleep after `consecutive` unproductive ticks in a row.

    The retry was flat: EVERY unproductive tick slept 300s, forever, with no escalation.
    That is right for the blip it was written for and wrong for an outage. Measured on the
    2026-08-01/02 moat outage: 144 real ticks, 131 of them failing
    `moat_preflight: no trusted moat brain answered: cursor_cli: ProviderExhaustedError`,
    retrying every 5 minutes for two days — 24x the normal 7200s cadence, each one paying
    for a preflight CLI call to re-learn the same fact. The moat recovered on its own;
    nothing the daemon did during those two days helped it.

    So: keep the first retry fast (a blip is still the common case), then double, capped at
    the normal cadence. An outage costs ~6 probes before it settles to the ordinary
    heartbeat, instead of 288 a day. Never longer than `interval`, because a recovered moat
    must not wait longer than a healthy daemon would to notice.
    """
    if consecutive <= 0:
        return interval
    backoff = _RETRY_BACKOFF_S * (2 ** (consecutive - 1))
    return max(1, min(interval, backoff))


def _force_exit_hung_tick(batch_size: int, cfg=None, tick: dict | None = None) -> None:
    logger.critical(
        "TICK HARD DEADLINE (%ds) exceeded during generation (batch=%s) — force-exiting so "
        "launchd KeepAlive relaunches a clean daemon.", _TICK_HARD_DEADLINE_S, batch_size)
    # Record the tick + fire the CRITICAL alert BEFORE exiting — a silent os._exit leaves no
    # tick row and no alert, so a repeating deadline breach looks like the daemon never ran
    # (proven live 2026-07-02: 4h of relaunch loops with zero tick rows). The main thread is
    # hung, so writing from this timer thread is safe; any bookkeeping failure must still exit.
    if cfg is not None and tick is not None:
        try:
            tick["error"] = (f"tick_hard_deadline: exceeded {_TICK_HARD_DEADLINE_S}s during "
                             f"generation (batch={batch_size}); force-exited for relaunch")
            _append_tick(cfg, tick)
            _emit_tick_alerts(cfg, tick)
        except Exception:  # noqa: BLE001 — bookkeeping must never block the force-exit
            logger.exception("Deadline bookkeeping failed; force-exiting anyway")
    os._exit(2)


def _tick_unproductive(tick: dict) -> bool:
    """True if a real (non-dry, guard-allowed) tick failed or stocked nothing — retry soon."""
    if tick.get("error"):
        return True
    if tick.get("allowed") and not tick.get("dry_run"):
        res = tick.get("result") or {}
        if res.get("dossiers", 0) == 0:
            return True
    return False


def run_tick(cfg, *, dry_run: bool = False, candidates: int | None = None, generate_fn=None) -> dict:
    """Execute one scheduler tick: evaluate the guard, then maybe run one batch.

    `generate_fn(cfg, batch_size) -> dict` is injectable so tests never spawn real generation.
    """
    # A dry-run is a manual diagnostic, NOT the daemon. Writing the shared liveness heartbeat
    # here would let a one-shot `--dry-run` reset the watchdog clock (masking a dead daemon) or
    # leave a stale "evaluating" beat that trips the 45-min stuck check while the daemon sleeps
    # fine. Only real ticks (the daemon loop) own the liveness heartbeat.
    if not dry_run:
        _write_heartbeat(cfg, phase="evaluating", dry_run=dry_run)
    guard = guard_from_config(cfg)
    decision = guard.evaluate()
    batch_size = _batch_size(cfg, candidates)

    tick = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "allowed": decision.can_run,
        "reason": decision.reason,
        "dry_run": dry_run,
        "today_spend_usd": decision.today_spend_usd,
        "daily_cap_usd": decision.daily_cap_usd,
        # Recorded even though only the metered leg is enforced by default: for weeks the tick
        # row carried one figure covering 2% of the day's model consumption and every reader
        # (probe, control centre, me) took it for the whole. See scheduler/guard.py.
        "today_subscription_usd": decision.today_subscription_usd,
        "daily_subscription_cap_usd": decision.daily_subscription_cap_usd,
        "spend_day": decision.day,  # LOCAL calendar day, not UTC — the rollover misled once
        "batch_size": batch_size if decision.can_run else None,
        "result": None,
        "error": None,
    }

    if not decision.can_run:
        logger.info("Tick skipped: %s", decision.reason)
        _append_tick(cfg, tick)
        return tick

    if dry_run:
        logger.info("Dry run: guard passed (%s); would generate %d candidates", decision.reason, batch_size)
        _append_tick(cfg, tick)
        return tick

    gen = generate_fn or _default_generate
    _write_heartbeat(cfg, phase="generating", batch_size=batch_size)
    # Hard wall-clock guard: if generation hangs past _TICK_HARD_DEADLINE_S the timer force-exits
    # the process (launchd relaunches it). Cancelled the instant generation returns.
    deadline = threading.Timer(_TICK_HARD_DEADLINE_S, _force_exit_hung_tick,
                               args=(batch_size, cfg, tick))
    deadline.daemon = True
    deadline.start()
    halt = False
    try:
        logger.info("Tick: generating %d candidates (%s)", batch_size, decision.reason)
        tick["result"] = gen(cfg, batch_size)
        logger.info("Tick complete: %s", tick["result"])
    except GroundingInfrastructureError as exc:
        # Record the tick + fire the CRITICAL alert BEFORE exiting — a silent exit here
        # leaves no tick row and no alert, so the founder never learns the daemon died.
        tick["error"] = f"GroundingInfrastructureError: {exc}"
        halt = True
        logger.critical("GROUNDING LAYER COLLAPSE: all search providers dead. "
                        "Halting daemon to prevent runaway LLM spend.")
    except Exception as exc:  # noqa: BLE001 — daemon must survive any single batch failing
        tick["error"] = f"{type(exc).__name__}: {exc}"
        logger.error("Tick generation failed (daemon continues): %s", tick["error"])
    finally:
        deadline.cancel()

    _append_tick(cfg, tick)
    _emit_tick_alerts(cfg, tick)
    _write_heartbeat(cfg, phase="idle", last_result=tick["result"], last_error=tick["error"])
    if halt:
        # launchd KeepAlive relaunches the exited daemon; _startup_grounding_check (run at
        # daemon startup) then refuses to start on one cheap probe search, so the relaunch
        # loop costs a probe every ThrottleInterval instead of a full LLM generation batch.
        sys.exit(1)
    return tick


def _trailing_barren_count(cfg, window: int = 50) -> int:
    """Count the trailing streak of barren real ticks in ticks.jsonl, EXCLUDING the
    just-appended current tick (callers run after _append_tick). Guard-skipped and
    dry-run rows are ignored entirely (controlled idle is not evidence either way);
    the streak breaks on any real tick with dossiers > 0 or an error (errors alert
    on their own key). Never raises."""
    streak = 0
    try:
        with open(_ticks_path(cfg), encoding="utf-8") as f:
            rows = f.readlines()[-window:]
        for line in reversed(rows[:-1]):  # rows[-1] is the current tick
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not t.get("allowed") or t.get("dry_run"):
                continue
            res = t.get("result") or {}
            if t.get("error") or int(res.get("dossiers", 0) or 0) > 0:
                break
            streak += 1
    except OSError:
        pass
    return streak


def _emit_tick_alerts(cfg, tick: dict) -> None:
    """Fire real-time operator alerts for a bad tick (error / barren / zero-yield).

    This is the missing nerve: the engine already KNOWS when a batch fails or stocks nothing; this
    pushes that to the founder (desktop + opt-in webhook) instead of leaving it in a log.
    """
    from prospector.scheduler.alerts import alerts_for_tick, emit_alert

    for spec in alerts_for_tick(tick, consecutive_barren=_trailing_barren_count(cfg)):
        try:
            emit_alert(cfg, **spec)
        except Exception:  # noqa: BLE001 — alerting must never break the daemon
            logger.exception("Failed to emit alert for tick")


class _StopFlag:
    """SIGTERM/SIGINT-aware stop flag so launchd can stop the daemon cleanly mid-sleep."""

    def __init__(self) -> None:
        self.stop = False

    def request(self, *_a) -> None:
        self.stop = True


def _startup_grounding_check(cfg) -> None:
    """Refuse to start if the grounding layer is dead — one dummy search first."""
    from prospector.retrieval import DiskCache, make_provider
    try:
        provider = make_provider(cfg)
        # Probe the LIVE stack, not the cache: the fixed probe query is cached after
        # the first-ever run, so a DiskCache hit "passes" a dead retrieval stack
        # (observed 2026-07-28: audit row provider=cache, cache_hit=true).
        if isinstance(provider, DiskCache):
            provider = provider.inner
        provider.search("startup sanity check", k=1)
        logger.info("Grounding layer healthy — daemon starting")
    except Exception as e:
        raise RuntimeError(
            f"REFUSING TO START: grounding provider is dead on arrival. "
            f"Fix search API keys/credits before starting Prospector. "
            f"Error: {e}"
        ) from e


def run_daemon(cfg, *, interval: int, candidates: int | None = None, generate_fn=None,
               max_cycles: int | None = None, sleep_fn=time.sleep) -> int:
    """Loop forever (or `max_cycles` times in tests): tick, then sleep `interval` seconds.

    The guard is re-evaluated every cycle, so PAUSE and the daily cap take effect without a
    restart. Returns the number of cycles executed.
    """
    flag = _StopFlag()
    signal.signal(signal.SIGTERM, flag.request)
    signal.signal(signal.SIGINT, flag.request)

    logger.info("Daemon starting: interval=%ds, store=%s", interval, _store_dir(cfg))
    cycles = 0
    consecutive_unproductive = 0
    while not flag.stop:
        tick = None
        try:
            tick = run_tick(cfg, candidates=candidates, generate_fn=generate_fn)
        except Exception:  # noqa: BLE001 — a tick failure (e.g. a transient ledger read error
            # inside the guard, before any spend) must not kill the daemon. Log and continue so
            # the next cycle re-evaluates the guard rather than crash-looping under launchd.
            logger.exception("Scheduler tick failed; continuing to next cycle")
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        # A healthy tick sleeps the full cadence; a failed/barren one retries in minutes so a
        # single provider blip can't waste a whole 2h window (root cause of days of $0 ticks).
        # A guard-blocked tick (spend cap) is intentional, not a failure — full cadence.
        sleep_target = interval
        if tick is not None and _tick_unproductive(tick):
            consecutive_unproductive += 1
            sleep_target = _retry_sleep_s(consecutive_unproductive, interval)
            logger.info("Unproductive tick #%d in a row — retrying in %ds instead of %ds",
                        consecutive_unproductive, sleep_target, interval)
        else:
            # Reset on ANY productive tick, including a guard-blocked one: the spend cap
            # firing is the system working, not a failure, and must not inherit an outage's
            # backoff. `_tick_unproductive` already excludes it.
            consecutive_unproductive = 0
        # Sleep in short slices so a stop request is honoured promptly mid-cadence.
        _write_heartbeat(cfg, phase="sleeping", interval_s=sleep_target, cycles=cycles)
        slept = 0
        while slept < sleep_target and not flag.stop:
            chunk = min(5, sleep_target - slept)
            sleep_fn(chunk)
            slept += chunk
    logger.info("Daemon stopped after %d cycle(s)", cycles)
    return cycles


def _route_ledger(cfg) -> None:
    """Send telemetry to the canonical ledger so the guard's spend math sees real costs."""
    from prospector.telemetry import route_logs_to_file

    route_logs_to_file(str(_store_dir(cfg) / "prospector.jsonl"))


def _err_log_path(cfg) -> Path:
    return _store_dir(cfg) / "scheduler" / "launchd.err.log"


def _tail_errors(cfg, n: int = 4) -> list[str]:
    """Last few non-blank lines of the launchd stderr log — the daemon's actual crash reason.

    The blind spot that let "a dead daemon look alive for 15h" was that heartbeat/ticks never show
    WHY it died. launchd captures stderr here; surfacing its tail in --status closes that gap.
    """
    path = _err_log_path(cfg)
    if not path.exists():
        return []
    try:
        lines = [l.rstrip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return []
    return lines[-n:]


def _aggregate_ticks(cfg) -> dict:
    """Roll up ticks.jsonl into run-rate signal: candidates made, PASSes, DEFER/error count, last PASS.

    `ticks.jsonl` records every COMPLETED tick with `result={"dossiers":N,"passes":M}` or an `error`.
    Aggregating tells the founder whether the factory is actually producing, not just breathing.
    """
    path = _ticks_path(cfg)
    agg = {"ticks": 0, "candidates": 0, "passes": 0, "errors": 0, "skipped": 0,
           "last_pass_ts": None, "last_error": None}
    if not path.exists():
        return agg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
        except json.JSONDecodeError:
            continue
        agg["ticks"] += 1
        if t.get("error"):
            agg["errors"] += 1
            agg["last_error"] = t["error"]
        elif not t.get("allowed"):
            agg["skipped"] += 1
        res = t.get("result") or {}
        if isinstance(res, dict):
            agg["candidates"] += int(res.get("dossiers", 0) or 0)
            p = int(res.get("passes", 0) or 0)
            agg["passes"] += p
            if p > 0:
                agg["last_pass_ts"] = t.get("ts")
    return agg


def _status_lines(cfg) -> list[str]:
    """Build the health readout as a list of lines (so --watch can clear and reprint cleanly).

    Liveness = heartbeat age vs cadence. A heartbeat in phase `generating` much older than a normal
    batch (≈30 min) is a STALL; a `sleeping` heartbeat older than the interval means the loop died.
    """
    now = datetime.now(timezone.utc)
    out = [f"Prospector daemon status  ({now.isoformat()})", "-" * 60]

    hb_path = _heartbeat_path(cfg)
    if hb_path.exists():
        beat = json.loads(hb_path.read_text(encoding="utf-8"))
        age_min = (now - datetime.fromisoformat(beat["ts"])).total_seconds() / 60
        phase = beat.get("phase", "?")
        stale = (phase == "generating" and age_min > 45) or \
                (phase == "sleeping" and age_min > beat.get("interval_s", 7200) / 60 + 35)
        flag = "  ⚠ STALE / likely dead" if stale else ""
        extra = ""
        if phase == "sleeping":
            wake_in = beat.get("interval_s", 7200) / 60 - age_min
            extra = f", next wake ~{wake_in:.0f} min" if wake_in > 0 else ", wake overdue"
        out.append(f"  heartbeat   : {phase}  ({age_min:.1f} min ago, pid {beat.get('pid')}{extra}){flag}")
    else:
        out.append("  heartbeat   : NONE — daemon has never run a tick (not installed/started?)")

    d = guard_from_config(cfg).evaluate()
    pause = "PAUSED (store/scheduler/PAUSE present)" if not d.can_run and "pause" in d.reason.lower() else d.reason
    out.append(f"  guard       : {'OK' if d.can_run else 'BLOCKED'} — {pause}")
    out.append(f"  spend today : ${d.today_spend_usd:.2f} of ${d.daily_cap_usd:.2f} cap "
               f"(metered/billed, local day {d.day})")
    sub_cap = (f"of ${d.daily_subscription_cap_usd:.2f} cap"
               if d.daily_subscription_cap_usd > 0 else "UNCAPPED")
    out.append(f"  cli usage   : ${d.today_subscription_usd:.2f} {sub_cap} "
               f"(Claude Code subscription-equivalent, not billed)")

    agg = _aggregate_ticks(cfg)
    if agg["ticks"]:
        rate = (agg["passes"] / agg["candidates"] * 100) if agg["candidates"] else 0.0
        out.append(f"  production  : {agg['candidates']} candidates → {agg['passes']} PASS ({rate:.0f}%) "
                   f"over {agg['ticks']} ticks")
        out.append(f"  last PASS   : {agg['last_pass_ts'] or 'none yet'}")
        out.append(f"  ticks       : {agg['errors']} errored, {agg['skipped']} skipped (guard/PAUSE)")
        if agg["last_error"]:
            out.append(f"  last error  : {agg['last_error'][:80]}")
    else:
        out.append("  production  : no completed ticks logged yet")

    errs = _tail_errors(cfg)
    if errs:
        out.append("  stderr tail :")
        out.extend(f"      {line[:88]}" for line in errs)
    return out


def _liveness(cfg) -> tuple[bool, str]:
    """Decide whether the daemon looks ALIVE, purely from the heartbeat file.

    Returns (ok, reason). This is deliberately separate from the in-loop alerts: if the daemon
    crash-loops or hangs, NO tick fires, so only an external check (run on its own schedule) can
    notice. A `generating` heartbeat older than the tick deadline + 10 min grace (see stall_min
    below — do not restate it as a literal here, it moves) is a stall; a `sleeping`
    heartbeat older than interval + grace means the loop died; a missing heartbeat means it never
    started. This is the active form of the "looked alive for 15h" guard.
    """
    hb = _heartbeat_path(cfg)
    if not hb.exists():
        return False, "no heartbeat file — daemon has never run (not installed/started?)"
    try:
        beat = json.loads(hb.read_text(encoding="utf-8"))
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(beat["ts"])).total_seconds() / 60
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return False, f"unreadable heartbeat ({exc})"
    phase = beat.get("phase", "?")
    # Derived from the tick hard deadline (+10 min grace) so the in-process deadline always
    # self-exits a hung tick FIRST; the watchdog kill is the backstop for when even the
    # in-process timer wedges. A fixed number here silently strands the coupling when the
    # deadline changes (proven: the old hardcoded 55 assumed the old 45-min deadline).
    stall_min = _TICK_HARD_DEADLINE_S / 60 + 10
    if phase == "generating" and age_min > stall_min:
        return False, (f"stuck in 'generating' for {age_min:.0f} min "
                       f"(deadline {_TICK_HARD_DEADLINE_S // 60} min should have force-exited it)")
    if phase == "sleeping":
        budget = beat.get("interval_s", 7200) / 60 + 35  # interval + grace
        if age_min > budget:
            return False, f"'sleeping' heartbeat {age_min:.0f} min old (> interval+grace {budget:.0f}); loop likely dead"
    if phase in ("evaluating", "idle") and age_min > 45:
        return False, f"stuck in '{phase}' for {age_min:.0f} min"
    return True, f"alive (phase={phase}, {age_min:.1f} min ago)"


def _kill_stale_daemon(cfg) -> None:
    """SIGKILL the hung daemon pid so launchd KeepAlive relaunches a clean process.

    launchd KeepAlive only restarts on process EXIT — a hung-but-alive process (a wedged socket
    read) is never restarted on its own. The 2026-07-01 incident was exactly this: the alert-only
    watchdog watched a wedged pid sit dead for 8.5h. Killing it converts "hung" into "exited",
    which KeepAlive (ThrottleInterval=30) then heals.
    """
    hb = _heartbeat_path(cfg)
    try:
        beat = json.loads(hb.read_text(encoding="utf-8"))
        pid = int(beat["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.error("Watchdog: cannot read daemon pid to restart: %s", exc)
        return
    if pid == os.getpid():
        return  # never kill the watchdog process itself
    # The heartbeat is ≥45 min stale by the time this fires; if the daemon already died,
    # the OS may have recycled its pid onto an unrelated process. Confirm the pid still
    # runs prospector before SIGKILLing it.
    import subprocess
    try:
        cmdline = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                 capture_output=True, text=True, timeout=5).stdout
    except Exception as exc:  # noqa: BLE001 — a broken ps must not crash the watchdog
        logger.error("Watchdog: could not inspect pid %d (%s); refusing to kill blind.", pid, exc)
        return
    if "prospector" not in cmdline:
        logger.info("Watchdog: pid %d is not a prospector process (%r) — already exited; "
                    "launchd will relaunch.", pid, cmdline.strip()[:80])
        return
    try:
        os.kill(pid, signal.SIGKILL)
        logger.critical("Watchdog: SIGKILLed hung daemon pid %d — launchd KeepAlive will relaunch.", pid)
        print(f"⚠ watchdog killed hung daemon pid {pid}; launchd will relaunch it")
    except ProcessLookupError:
        logger.info("Watchdog: daemon pid %d already gone; launchd will relaunch.", pid)
    except PermissionError as exc:
        logger.error("Watchdog: not permitted to kill pid %d: %s", pid, exc)


def _run_watchdog(cfg) -> int:
    """One-shot liveness check that RESTARTS the daemon if it is hung. Run on its own schedule.

    Intended to be invoked every ~15 min by a separate launchd job (com.prospector.watchdog.plist),
    so a dead/hung daemon is caught even though it emits no ticks. On a stale heartbeat it alerts
    AND kills the wedged pid so launchd KeepAlive relaunches it. Returns 0 if alive, 1 if not.
    """
    from prospector.scheduler.alerts import emit_alert, CRITICAL

    ok, reason = _liveness(cfg)
    if ok:
        logger.info("Watchdog: %s", reason)
        return 0
    emit_alert(cfg, severity=CRITICAL, key="liveness",
               title="Generation daemon is DOWN", message=reason, throttle_s=3600)
    print(f"⚠ daemon DOWN: {reason}")
    _kill_stale_daemon(cfg)
    return 1


def _print_status(cfg) -> None:
    print("\n".join(_status_lines(cfg)))


def _watch_status(cfg, interval: int) -> None:
    """Live dashboard: clear the screen and reprint the status every `interval` seconds.

    A founder-run readout (no network bind, no daemon attach) — Ctrl-C to stop. This is the
    'watch it work' view for the 15–30 min grounded batches.
    """
    try:
        while True:
            # ANSI clear+home so the readout refreshes in place rather than scrolling.
            sys.stdout.write("\033[2J\033[H")
            print("\n".join(_status_lines(cfg)))
            print(f"\n  (refreshing every {interval}s — Ctrl-C to stop)")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Prospector always-on generation daemon")
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run a single bounded batch, then exit (default)")
    mode.add_argument("--daemon", action="store_true", help="Run continuously on a fixed cadence")
    p.add_argument("--interval", type=int, default=_DEFAULT_INTERVAL_SECONDS,
                   help=f"Daemon cadence in seconds (default {_DEFAULT_INTERVAL_SECONDS})")
    p.add_argument("--candidates", type=int, default=None, help="Override batch size (default: config schedule.batch_size)")
    p.add_argument("--dry-run", action="store_true", help="Evaluate guards only; never generate")
    p.add_argument("--status", action="store_true", help="Print daemon health (heartbeat, guard, production, stderr) and exit")
    p.add_argument("--watch", type=int, nargs="?", const=30, default=None, metavar="SECONDS",
                   help="Live-refresh the status readout every SECONDS (default 30); Ctrl-C to stop")
    p.add_argument("--watchdog", action="store_true",
                   help="One-shot liveness check; ALERTS if the daemon is down. For a cron/launchd timer.")
    args = p.parse_args(argv)

    injected = _load_env_file()
    if injected:
        logger.info("Loaded %d key(s) from .env into the environment", injected)

    cfg = load_config(args.config)

    if args.watch is not None:
        _watch_status(cfg, args.watch)
        return

    if args.watchdog:
        sys.exit(_run_watchdog(cfg))

    if args.status:
        _print_status(cfg)
        return

    _route_ledger(cfg)

    if args.daemon:
        # One cheap probe search before committing to the loop: if grounding is dead on
        # arrival (all providers 402/keyless/down), refuse to start instead of burning a
        # full LLM generation batch per launchd relaunch. This is the other half of the
        # GroundingInfrastructureError halt in run_tick — exit + KeepAlive relaunch lands
        # here, so the crash loop costs one probe, not one batch.
        _startup_grounding_check(cfg)
        run_daemon(cfg, interval=args.interval, candidates=args.candidates)
        return

    tick = run_tick(cfg, dry_run=args.dry_run, candidates=args.candidates)
    if tick["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

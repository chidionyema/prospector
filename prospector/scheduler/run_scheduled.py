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

from prospector.audit import run_id as audit_run_id
from prospector.config import load_config
from prospector.errors import GroundingInfrastructureError
from prospector.scheduler import paths
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
    # See prospector/scheduler/paths.py: the old cwd-relative default silently aimed every
    # scheduler write at whatever `./store` the current directory had.
    return paths.store_dir(cfg)


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
    """Append one completed tick, stamped with the process that produced it.

    ATTRIBUTION, added 2026-08-06 after measuring who actually writes this file. `ticks.jsonl`
    is NOT written by the daemon alone. Caught live by watching the file and dumping `ps` on
    every append::

        32982  hermes_cli.main gateway run --replace
         └ 37045  ~/.hermes/scripts/otto-dispatch.py
           └ 37094  bash ~/.hermes/scripts/prospector-run.sh
             └ 37096  timeout 110 uv run --directory <this repo> \
                          python -m prospector.scheduler.run_scheduled --once --dry-run

    A driver in the ADJACENT estate fires a one-shot dry run into this checkout's production log
    at a measured 59.6 rows/hour, while the daemon's own real ticks are ~2.5 h apart. Nothing in
    the row said so, which is why it went unnoticed — the same blindness `prospector/audit.py`
    was just fixed for, in the log that actually drives the alerts. `run_id` is shared with the
    audit log (one identity per process), so a tick and the searches it performed can be joined.
    """
    path = _ticks_path(cfg)
    # Identity last: a tick dict assembled upstream must not be able to misattribute itself.
    row = {**tick, "pid": os.getpid(), "run_id": audit_run_id()}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
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
    written at the START of work (and repeatedly during sleep), so a monitor can flag
    "phase=generating, but heartbeat is 40 min stale" as a stall. `next_check` (when set) lets a
    watchdog tell idle from dead.

    `mono` is `time.monotonic()` alongside the wall-clock `ts`, because the two disagree in exactly
    the cases that matter and only their difference names the cause. A wall clock that is stepped
    (NTP correction, a VM/laptop resuming, the 1970-dated ticks this machine has produced) inflates
    the wall age while the loop is turning normally; a loop that has actually stopped inflates both.
    Written, not yet acted on — see `_liveness`.
    """
    beat = {"ts": datetime.now(timezone.utc).isoformat(), "mono": time.monotonic(),
            "pid": os.getpid(), "phase": phase, **extra}
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


def _moat_brains(cfg) -> list[str]:
    """The trusted brains on this config's verdict chain, in order.

    Delegates to `prospector.health.moat_brains` — moved there 2026-08-06 so the drain's
    preflight and this one cannot drift apart. Kept as a name here because tests and callers
    already bind to it.
    """
    from prospector.health import moat_brains
    return moat_brains(cfg)


def _moat_blind_reason(cfg) -> str:
    """Why this tick must not run, or "" if the moat can rule.

    Generation had NO provider-health precondition until 2026-08-06: `run_tick` called
    `gen(cfg, batch_size)` unconditionally, so the daemon happily generated a full batch while
    every trusted brain carried a live dead mark. What came out was 15 candidates the moat
    could not rule, each one owing a full re-vet later. Meanwhile a `vet --resume` drain was
    running to clear exactly that backlog, and the two competed for the same subscription CLI.
    The system was manufacturing its own backlog faster than it could pay it down.

    A tick that cannot verify has nothing worth doing: generation is only useful if the moat
    can then rule on it, and the drain needs the same brains. So skip the whole tick.

    Uses `dead_until()`, NOT `is_dead()`: `is_dead` can CLAIM the half-open probe slot
    (health.py), and a bookkeeping check must never consume the one call whose job is to
    measure recovery. This reads the mark; it does not spend the probe.
    """
    from prospector.health import moat_blind_reason
    return moat_blind_reason(cfg)


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

# How often the daemon re-stamps its heartbeat while asleep (see the refresh loop in
# `run_daemon`). 60s against a 5s sleep slice, so it costs one small file write per twelve slices
# — roughly 120 writes across a 2h cadence, against a watchdog that samples every ~15 min. The
# point is the RATIO: any budget the watchdog sets is now compared against a write that should
# never be more than a minute old, instead of one that is legitimately two hours old.
_SLEEP_HEARTBEAT_REFRESH_S = 60

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
    # A moat-blind skip is unproductive by definition — nothing was stocked. It must use the
    # escalating retry (5m, 10m, 20m…) rather than the full 2h cadence, so a moat that heals in
    # ninety seconds is picked up in minutes instead of hours.
    if tick.get("moat_blind"):
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

    # MOAT PREFLIGHT. Checked after the guard (spend/PAUSE still own the money rails) and
    # before any work, because both halves of a tick — the resume drain and generation — need a
    # trusted brain. Generating into a blind moat produces `provisional` rows that cannot
    # publish and must be re-vetted, i.e. it pays twice for one answer while the moat is the
    # scarce resource. Skipped only when EVERY trusted brain is marked dead; one live brain is
    # enough to run.
    #
    # It deliberately applies to an injected `generate_fn` too. Exempting the test seam would
    # make the preflight unprovable by the suite — the same shape as the 2026-08-06 defect
    # where a copy fix was "verified" by a test that read only the one file that was edited.
    blind = _moat_blind_reason(cfg)
    if blind:
        tick["moat_blind"] = True
        tick["reason"] = blind
        tick["batch_size"] = None
        logger.critical("Tick skipped: %s", blind)  # CRITICAL: below it never reaches the
        # daemon's launchd log at all (verified 2026-08-05), and a tick that silently does
        # nothing is exactly the invisible degradation this whole change is about.
        print(f"⏸ tick skipped — {blind}", file=sys.stderr, flush=True)
        _append_tick(cfg, tick)
        _emit_tick_alerts(cfg, tick)
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


#: How many trailing LINES to scan to find `window` real ticks. Sized against the measured
#: pollution rate: an external driver appends ~60 dry-run rows/hour (see `_append_tick`) and the
#: daemon's real ticks are ~2.5 h apart, so ~150 junk rows can separate two real ones. 5000 lines
#: covers ~33 real ticks at that ratio and costs one read of a file that is ~1300 lines today.
_TICK_SCAN_LINES = 5000


def _trailing_barren_count(cfg, window: int = 50) -> int:
    """Count the trailing streak of barren real ticks in ticks.jsonl, EXCLUDING the
    just-appended current tick (callers run after _append_tick). Guard-skipped and
    dry-run rows are ignored entirely (controlled idle is not evidence either way);
    the streak breaks on any real tick with dossiers > 0 or an error (errors alert
    on their own key). Never raises.

    `window` counts REAL TICKS, not lines. It used to count lines, and that made this alert
    structurally dead rather than merely noisy. Measured 2026-08-06 on the live log: the last 50
    rows held 1 real tick and 49 skipped ones, because a driver in the adjacent estate appends a
    dry run every ~60 seconds (see `_append_tick`). With a 50-LINE window, two consecutive real
    ticks — 2.5 h and ~150 junk rows apart — could never both be inside it, so the streak could
    never reach 2 and `barren_streak` could never fire. An alert that cannot fire is worse than
    no alert: it reads as an all-clear. Nothing here changes what counts as barren; it changes
    only how far back we look to find the ticks that count.
    """
    streak = 0
    try:
        with open(_ticks_path(cfg), encoding="utf-8") as f:
            lines = f.readlines()[-_TICK_SCAN_LINES:]
    except OSError:
        return 0
    real = []
    for line in lines:
        try:
            t = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not t.get("allowed") or t.get("dry_run"):
            continue
        real.append(t)
    # real[-1] is the current tick when the caller's tick was itself real. When it was not, the
    # value this function returns is discarded — `alerts_for_tick` yields nothing for a skipped,
    # dry or errored tick — so dropping one extra row there costs nothing.
    for t in reversed(real[-window:][:-1]):
        res = t.get("result") or {}
        if t.get("error") or int(res.get("dossiers", 0) or 0) > 0:
            break
        streak += 1
    return streak


def _emit_tick_alerts(cfg, tick: dict) -> None:
    """Fire real-time operator alerts for a bad tick (error / barren / zero-yield).

    This is the missing nerve: the engine already KNOWS when a batch fails or stocks nothing; this
    pushes that to the founder (desktop + opt-in webhook) instead of leaving it in a log.
    """
    from prospector.scheduler.alerts import (TICK_ALERT_KEYS, alerts_for_tick, emit_alert,
                                             reconcile_alert_txt, resolve_alert)

    specs = alerts_for_tick(tick, consecutive_barren=_trailing_barren_count(cfg))
    for spec in specs:
        try:
            emit_alert(cfg, **spec)
        except Exception:  # noqa: BLE001 — alerting must never break the daemon
            logger.exception("Failed to emit alert for tick")

    # RECOVERY. A tick that actually ran generation and raised nothing is positive evidence that
    # the conditions it checks are over — so clear them, instead of leaving ALERT.txt showing a
    # CRITICAL from hours ago (measured 2026-08-06: it still showed `moat_provisional` from
    # 2026-08-05T15:29 while the newest real batch had 0 provisional).
    #
    # The eligibility test is deliberately narrow, because "no alert" is NOT the same as
    # "healthy":
    #   * a guard-skipped tick (PAUSE / spend cap) never ran, so it proves nothing;
    #   * a dry run never ran either;
    #   * an errored tick is itself an alert.
    # `alerts_for_tick` returns [] for all three, so keying recovery off "no specs" alone would
    # let a PAUSE file silently clear a real moat outage.
    if not tick.get("allowed") or tick.get("dry_run") or tick.get("error"):
        return
    if not isinstance(tick.get("result"), dict):
        return
    raised = {s["key"] for s in specs}
    for key in TICK_ALERT_KEYS:
        if key in raised:
            continue
        try:
            resolve_alert(cfg, key=key,
                          reason=f"clean tick at {tick.get('ts')}: {tick.get('result')}")
        except Exception:  # noqa: BLE001 — recovery bookkeeping must never break the daemon
            logger.exception("Failed to resolve alert '%s'", key)

    # Then make the file match the active set outright. `resolve_alert` only rewrites when it
    # removed something, so a store written by the old code — no `_active` key, a stale banner —
    # would never converge: every resolve returns False and the CRITICAL from yesterday survives
    # the fix meant to clear it. That is the exact shape of the live store on 2026-08-06.
    try:
        reconcile_alert_txt(cfg)
    except Exception:  # noqa: BLE001 — see above
        logger.exception("Failed to reconcile ALERT.txt")


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
        # Sleep in short slices so a stop request is honoured promptly mid-cadence, and REFRESH
        # the heartbeat from inside that sleep rather than stamping it once on the way in.
        #
        # Stamped once, a `sleeping` heartbeat is a full cadence old by the end of a normal sleep,
        # so "is it stale?" was really asking "has the WALL CLOCK moved more than interval+35min
        # since a single write?" — a question that a clock step, an NTP correction or a system
        # suspend answers wrongly, and that says nothing about whether the loop is turning.
        # Refreshed every ~60s, a stale `sleeping` heartbeat can only mean the loop STOPPED, which
        # is the property the watchdog is there to watch. Damage this is meant to end: 47 SIGKILLs
        # of daemons that `ps` proved were live, every one of them `phase=sleeping`, ages clustered
        # 156–175 min against a 155 min budget.
        #
        # `beat_every_s` marks the new format. `_liveness` keeps the old, generous budget for a
        # heartbeat without it: a daemon that went to sleep under the old code and wakes up after
        # this deploy must not be judged dead by the watchdog's next 15-min pass and SIGKILLed for
        # running exactly the code it was started with.
        slept = 0

        def _beat() -> None:
            _write_heartbeat(cfg, phase="sleeping", interval_s=sleep_target, cycles=cycles,
                             beat_every_s=_SLEEP_HEARTBEAT_REFRESH_S, slept_s=slept)

        _beat()
        since_beat = 0
        while slept < sleep_target and not flag.stop:
            chunk = min(5, sleep_target - slept)
            sleep_fn(chunk)
            slept += chunk
            since_beat += chunk
            if since_beat >= _SLEEP_HEARTBEAT_REFRESH_S:
                _beat()
                since_beat = 0
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
    agg = {"ticks": 0, "dry_runs": 0, "candidates": 0, "passes": 0, "errors": 0, "skipped": 0,
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
        # A dry run generated nothing and cost nothing; counting it as a tick inflates the one
        # number a founder reads as "is the factory running?". Measured 2026-08-06: 133 of the
        # 315 August rows were dry runs, nearly all of them fired by a driver outside this repo
        # (see `_append_tick`). Reported separately so the pollution stays VISIBLE rather than
        # being silently dropped — a tick count that quietly shrank would be its own puzzle.
        if t.get("dry_run"):
            agg["dry_runs"] += 1
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
    # The monotonic age beside the wall-clock one, whenever the heartbeat carries a `mono`.
    #
    # Every budget below is written in wall-clock minutes and is UNCHANGED here, on purpose: a
    # large wall age is what the watchdog has always acted on, and narrowing that on an unproven
    # theory would trade 47 false criticals for a missed real stall (the 8.5h wedge of 2026-07-01
    # is why the kill exists at all). What changes is that the reason string now carries both
    # numbers, so the NEXT stale heartbeat identifies its own cause instead of being unexplainable:
    # a loop that stopped shows both ages large, while a stepped clock or a suspended machine shows
    # a large wall age beside a small monotonic one.
    #
    # HYPOTHESIS this instruments (unproven, do not act on it yet): the 47 SIGKILLs were wall-clock
    # artefacts, not dead loops. Circumstantial support — ages clustered 156–175 min against a
    # 155 min budget, drift measured at only +0.057% (needs 38.3% to reach 166 min), `pmset` showing
    # no suspend around pid 91757's last beat, and 110 ticks dated 1970 found on this machine.
    # Confirmed if a future failure prints a wall age far above its monotonic age; killed if the two
    # track each other, which would mean the loop really did stop and the refresh above is the fix.
    # NOTE the monotonic reading is only comparable within one boot: after a restart the daemon
    # rewrites the heartbeat within seconds, so a cross-boot comparison is not a state this reaches
    # in practice, and a negative age is reported rather than hidden.
    mono = beat.get("mono")
    age_mono_min = (time.monotonic() - mono) / 60 if isinstance(mono, (int, float)) else None
    ages = (f"{age_min:.0f} min old"
            if age_mono_min is None
            else f"{age_min:.0f} min old by wall clock / {age_mono_min:.0f} min monotonic")
    # Derived from the tick hard deadline (+10 min grace) so the in-process deadline always
    # self-exits a hung tick FIRST; the watchdog kill is the backstop for when even the
    # in-process timer wedges. A fixed number here silently strands the coupling when the
    # deadline changes (proven: the old hardcoded 55 assumed the old 45-min deadline).
    stall_min = _TICK_HARD_DEADLINE_S / 60 + 10
    if phase == "generating" and age_min > stall_min:
        return False, (f"stuck in 'generating', heartbeat {ages} "
                       f"(deadline {_TICK_HARD_DEADLINE_S // 60} min should have force-exited it)")
    if phase == "sleeping":
        budget = beat.get("interval_s", 7200) / 60 + 35  # interval + grace
        if age_min > budget:
            return False, (f"'sleeping' heartbeat {ages} (> interval+grace {budget:.0f}); "
                           f"loop likely dead")
    if phase in ("evaluating", "idle") and age_min > 45:
        return False, f"stuck in '{phase}', heartbeat {ages}"
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
    from prospector.scheduler.alerts import emit_alert, resolve_alert, CRITICAL

    ok, reason = _liveness(cfg)
    if ok:
        logger.info("Watchdog: %s", reason)
        # The watchdog owns `liveness` in both directions. A tick completing is also evidence the
        # daemon is alive, but the tick path must not clear an alert it does not own: the watchdog
        # runs every ~15 min and the tick cadence is 2h, so letting the tick clear it would leave
        # the file green for up to two hours after the daemon actually died.
        resolve_alert(cfg, key="liveness", reason=f"watchdog check passed: {reason}")
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


def _log_formatter() -> logging.Formatter:
    """The one line format for everything this entry point logs: UTC timestamp, level, message.

    Split out from `_configure_logging` so the shape is assertable without installing a handler.
    """
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime  # UTC, matching the heartbeat's `ts` so the two can be diffed
    return fmt


def _configure_logging() -> None:
    """Install that formatter on the root logger. Nothing else in this package configures logging.

    Without it, `logger.critical` fell through to `logging.lastResort`, which writes the bare
    message to stderr with no time and no level. The cost was concrete and current: 173 lines of
    `watchdog.err.log` recording 47 SIGKILLs, not one of which can be placed in time, correlated
    with a tick, or checked against `pmset` — so the alerts could be counted and never explained.
    Every liveness theory in `_liveness` is only testable once the kills carry timestamps.

    Level INFO, because `lastResort` also swallows the watchdog's PASS line (`logger.info`
    "Watchdog: %s"), leaving a log that records only the kills — which reads as though the daemon
    is killed every time it is checked. Guarded on `root.handlers` so a caller that has already
    configured logging (a test harness, an embedding process) keeps its own setup.
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_log_formatter())
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> None:
    _configure_logging()
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

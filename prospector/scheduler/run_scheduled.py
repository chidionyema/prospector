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
import contextlib
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from prospector import usage_wall
from prospector.audit import run_id as audit_run_id
from prospector.config import load_config
from prospector.errors import GroundingInfrastructureError
from prospector.jsonl_atomic import append_jsonl, iter_jsonl, read_jsonl
from prospector.scheduler import paths
from prospector.scheduler.alerts import _load_hermes_sender
from prospector.scheduler.guard import guard_from_config

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 2 * 60 * 60  # 2h cadence — continuous but not a tight spin

#: Floor for `schedule.interval_s`. The daemon takes no cross-cycle lock, so a cadence shorter
#: than one generation batch starts a second batch beside the first and pays for both.
_MIN_INTERVAL_SECONDS = 60


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


def _interval_s(cfg, fallback: int) -> int:
    """Seconds between daemon cycles. `schedule.interval_s` wins over the `--interval` argv.

    The cadence used to live ONLY in the launchd plist (`--interval 7200`), which put the
    single number controlling how often the system produces anything outside config, outside
    the console, and reachable only by editing a plist and reloading the job by hand. Config
    is now the control point and argv is the fallback, so the operator sets it where every
    other scheduler number already lives.

    It takes effect without a manual restart: `code_fingerprint` covers config.yaml, so a
    saved change re-execs the daemon at the next cycle boundary (see `run_daemon`).

    Floored at `_MIN_INTERVAL_SECONDS`, not at 1. A cadence below that is not "continuous", it
    is a spin that starts a new generation batch while the previous one is still running — the
    daemon holds no cross-cycle lock, so overlap is real work paid twice.
    """
    raw = _sched(cfg, "interval_s", None)
    if raw in (None, "", 0):
        return int(fallback)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        logger.warning("schedule.interval_s=%r is not an integer; using %ds", raw, fallback)
        return int(fallback)
    if val < _MIN_INTERVAL_SECONDS:
        logger.warning("schedule.interval_s=%ds is below the %ds floor; using the floor",
                       val, _MIN_INTERVAL_SECONDS)
        return _MIN_INTERVAL_SECONDS
    return val


def _queue_target_depth(cfg) -> int:
    """Optional: hold the queue at this many workable rows. 0 (the default) means OFF.

    OFF is the default on purpose. Following the queue makes the production RATE an emergent
    property of how fast the consumer happens to be draining, which is the opposite of being
    able to set it — the operator would no longer have a number to turn. `batch_size` on
    `interval_s` stays the plain answer to "how much, how often".

    Turn it on for the case it is actually good at: a consumer that has stalled or slowed, where
    minting a full batch every cycle only deepens a queue nobody is working. Above the target the
    tick skips generation; below it, the tick mints the shortfall, capped at `batch_size`.
    """
    try:
        return max(0, int(_sched(cfg, "queue_target_depth", 0) or 0))
    except (TypeError, ValueError):
        logger.warning("schedule.queue_target_depth=%r is not an integer; treating as off",
                       _sched(cfg, "queue_target_depth", 0))
        return 0


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
    # DURATION, added 2026-08-17. 4559 rows and not one of them said how long a tick took, so
    # every question about the cadence and the deadline — is 2h too long, is 3h too short, does
    # a full batch fit — had to be answered from assumption. `ts` is stamped when the tick
    # starts and this runs when it ends, so the number is free; derived here rather than at each
    # `return` because `run_tick` has eight of them and a duration missing from three would be
    # worse than none at all.
    if "duration_s" not in row:
        try:
            started = datetime.fromisoformat(str(row.get("ts")))
            row["duration_s"] = round(
                (datetime.now(timezone.utc) - started).total_seconds(), 1)
        except (TypeError, ValueError):
            pass
    try:
        # R3: one O_APPEND write + fsync. NOT tmp+rename — this file has concurrent appenders
        # (the daemon and an out-of-repo driver, see above), and a read-modify-rename would
        # delete every line a peer wrote between the read and the rename.
        append_jsonl(path, row)
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
    if _RUNNING_CODE_FP:
        # What this process is RUNNING, so a monitor can diff it against `code_fingerprint()` on
        # disk. The previous freshness check compared the daemon's start time to the newest commit
        # — a heuristic that is wrong in both directions (an uncommitted edit is invisible; a
        # commit touching only tests reads as a stale daemon).
        beat.setdefault("code", _RUNNING_CODE_FP[:12])
    # ATOMIC, and this is load-bearing rather than tidiness. `write_text` truncates and then
    # writes, so every reader has a window in which the file is 0 bytes or half a JSON object —
    # and the readers do not treat that as "try again". `_watchdog_liveness` catches
    # `json.JSONDecodeError` and returns `(False, "unreadable heartbeat")`, which `_kill_stale_
    # daemon` turns into a SIGKILL: a torn read is a dead daemon as far as the watchdog is
    # concerned. Proven by this file's own tests — sampling the heartbeat from inside a tick hit
    # `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`, i.e. an EMPTY read, not corrupt
    # JSON, which is the signature of reading mid-truncate.
    #
    # The window used to be one write per phase and is now one per `_WORK_HEARTBEAT_REFRESH_S`
    # across the daemon's longest phases, so the refresh above would have multiplied a real kill
    # risk by ~120 per tick had this stayed a truncating write. `os.replace` is atomic on POSIX:
    # a reader sees either the whole previous beat or the whole new one, never a partial file.
    path = _heartbeat_path(cfg)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(beat, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.error("Failed to write heartbeat: %s", exc)
        # A failed replace leaves the temp behind; it is named per-pid so it can never collide
        # with another daemon's, and leaving it would accumulate one file per failed write.
        with contextlib.suppress(OSError):
            tmp.unlink()


def producer_mode(cfg) -> bool:
    """`schedule.producer_mode` — is this daemon the PRODUCER half of the split?

    False (the default) is the tick exactly as it has always been: drain, then generate, vet,
    and publish, all inside one 3-hour deadline. Nothing about the split changes a deployment
    that has not asked for it — the flag is the only thing that moves.

    True makes the tick a producer: it generates, parks every survivor in the queue as a DEFER
    row (`run.enqueue_candidates`), and returns. It does NOT vet, does NOT publish, and does NOT
    drain — a consumer process (`python -m prospector.run consume`) owns all three.

    THE DRAIN IS SKIPPED HERE ON PURPOSE, and it is the part worth stating. Leaving it on would
    be SAFE — the queue lease (`store.claim`) already stops two workers vetting one row — but it
    would put the tick back on the moat's clock, which is the entire thing the split exists to
    end: a generation tick would once again stall behind a benched brain, and the 3-hour deadline
    would once again be shared by a phase that cannot be bounded. Half a split is the worst of
    both, so the flag moves both halves at once.
    """
    return bool(_sched(cfg, "producer_mode", False))


def _resume_per_tick(cfg) -> int:
    """How many backlogged candidates one tick may re-vet. 0 disables the drain."""
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        return max(0, int(schedule.get("resume_per_tick", _RESUME_PER_TICK_DEFAULT) or 0))
    return max(0, int(getattr(schedule, "resume_per_tick", _RESUME_PER_TICK_DEFAULT) or 0))


#: Kill switch for GENERATION ONLY. `PAUSE` (guard.py) halts the entire tick — generation and
#: the drain together — because it is the liability rail CLAUDE.md requires, and a rail with
#: exceptions is not a rail. But that made the founder's actual 2026-08-06 decision
#: ("pause generation, let drain run") impossible to express: setting PAUSE to stop the treadmill
#: also stopped the only thing that pays it down, so the 343-row backlog could not recover on its
#: own even after the moat healed. This file expresses the other half.
_GENERATION_PAUSE_FILENAME = "PAUSE_GENERATION"


def _sched(cfg, key: str, default):
    """One accessor for `schedule.*`, which is a dict in config.yaml and a namespace in tests."""
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        return schedule.get(key, default)
    return getattr(schedule, key, default)


def _gen_budget_frac(cfg) -> float:
    """`schedule.gen_budget_frac` — the share of the tick deadline generation may spend.

    Default 0.35: generous against the measured healthy phase (~3 min of a 41-66 min k=15
    tick, launchd.err.log 2026-08-11) and still leaves ~2h of a 3h tick for vetting,
    artifacts and publish when the chain is degraded. 0 disables the budget entirely.
    """
    try:
        return max(0.0, float(_sched(cfg, "gen_budget_frac", 0.35)))
    except (TypeError, ValueError):
        return 0.35


def _artifact_budget_frac(cfg) -> float:
    """`schedule.artifact_budget_frac` — the share of the tick deadline the ARTIFACT +
    MARKETING-CONTENT phase (prospector/artifacts.py: `generate_artifacts`,
    `generate_marketing_content`, invoked from run.py's `_generate_pack_content` on
    every PASS) may spend, mirroring `_gen_budget_frac` above for the phase generation's
    rail never covered.

    PROVEN, not hypothetical: on the 2026-08-15 10:17->13:17 breach, artifact/content
    markers in store/scheduler/launchd.err.log span 10:40 -> 13:12 — 152 of the tick's
    180 minutes (84%) — spent with NO budget at all, while `gen_budget_frac` bounded
    generation alone. Three of the five `_TICK_HARD_DEADLINE_S` breaches recorded in
    store/scheduler/ticks.jsonl landed in the 48h before this reader was added.

    Default 0.40: with `gen_budget_frac` at 0.35, 0.35 + 0.40 = 0.75 of the 10800s tick,
    leaving 0.25 (45 min) for verify/publish/drain, which carry no budget of their own —
    the two rails together can never alone exceed the tick deadline. 0.40 x 10800s =
    4320s (72 min) is still generous against a healthy call — each artifact call
    measures ~90s of wall-clock (run.py:462) with four running in parallel per batch —
    so, like `gen_budget_frac`, this only ever bites once the chain is degraded. 0
    disables the rail (same convention as `gen_budget_frac`).

    WIRED AND LIVE since 2026-08-15 (this paragraph replaces the "NOT YET CONSUMED" note that
    stood here for the hours between the rail being built and `run.py` being able to receive
    it — an unconsumed budget is an inert rail, and an inert rail that reads as installed is
    worse than none). The three-hop path is now:
      `_default_generate` -> `run_signal(artifact_time_budget_s=)`
      -> `vet_candidate(artifact_time_budget_s=)`
      -> `_generate_pack_content`, which converts it ONCE into an absolute
         `time.monotonic()` deadline shared by all `_MAX_PACK_GEN_ATTEMPTS` retries and
         forwards it as `deadline_mono=` to both `generate_artifacts` and
         `generate_marketing_content`.
    It is a PER-CANDIDATE ceiling, not a tick-absolute one. A tick-absolute artifact deadline
    would let the first survivors spend the whole allowance and hand every later survivor an
    empty build_spec/gtm_plan/ops_plan, which publishes UNLISTED and unsellable — see
    `run.py::_generate_pack_content`, where 12 of 24 off-shelf passes are exactly that fossil.

    HISTORICAL, kept because it names the parameter shapes: `generate_artifacts` and
    `generate_marketing_content` both already accept and enforce a `deadline_mono`
    parameter (a `time.monotonic()` absolute deadline, bounding their ThreadPoolExecutor
    batch's `as_completed(..., timeout=...)` wait exactly like generate.py:771), but
    `run_signal` (prospector/run.py — owned by a different session this file's changes
    were made alongside, and out of scope here) has no `artifact_time_budget_s`
    parameter to receive the seconds this function resolves, so nothing in this daemon
    calls it outside its own unit tests today. The three-hop wire-up run.py needs,
    mirroring exactly how `gen_time_budget_s` reaches `generate.py`'s wave loop
    (run.py:1071, :1089, :1102, :1114):
      1. `run_signal(..., artifact_time_budget_s: Optional[float] = None)` — new kwarg,
         converted once near `_gen_deadline` (run.py:1071) into an absolute deadline:
         `_artifact_deadline = (_time.monotonic() + artifact_time_budget_s)
          if artifact_time_budget_s else None`.
      2. Thread `_artifact_deadline` into every `vet_candidate(...)` call inside the
         per-candidate `executor.submit(...)` (run.py:~1294) as a new
         `artifact_deadline_mono=` kwarg; `vet_candidate`'s own signature (run.py:663)
         needs the matching parameter.
      3. Forward it from `vet_candidate` into `_generate_pack_content(...,
         deadline_mono=artifact_deadline_mono)` (run.py:~838), and `_generate_pack_content`
         (run.py:418) forwards the SAME `deadline_mono` into both
         `generate_artifacts(...)` and `generate_marketing_content(...)` (run.py:465,
         :467-468) — reused across all `_MAX_PACK_GEN_ATTEMPTS` (3) retry attempts, since
         it is one wall-clock ceiling for the whole phase, not per-attempt.
    Once wired, `_default_generate` (this module, ~line 930) should resolve this the same
    way `_gen_budget_frac` is resolved just below it:
        art_frac = _artifact_budget_frac(cfg)
        artifact_budget = (art_frac * _TICK_HARD_DEADLINE_S) if art_frac > 0 else None
        ... run_signal(..., artifact_time_budget_s=artifact_budget)
    """
    try:
        return max(0.0, float(_sched(cfg, "artifact_budget_frac", 0.40)))
    except (TypeError, ValueError):
        return 0.40


_ARTIFACT_BUDGET_FLOOR_S = 1200.0


def _artifact_budget_floor_s(cfg) -> float:
    """`schedule.artifact_budget_floor_s` — the least time a PASS's content phase may get.

    THE TRAP THIS CLOSES. `artifact_budget_frac` is a SHARE, so it shrinks whenever another
    phase runs long, and on 2026-08-15 it shrank to nothing: candidate f2ac7df9995c334e
    cleared all seven checks and then published UNLISTED with three empty artifacts, its
    three retries all logged in the same second because the share was already spent.

    Cutting this phase is the most expensive cut available. Generation, prescreen, dedup,
    retrieval, seven verdict calls and adversarial review have all been PAID FOR by the time
    it runs; it is the step that turns that spend into something sellable. Cutting it strands
    100% of the upstream cost to save the cheapest thing in the tick (~90s/call, run.py:462).
    If a tick cannot afford everything, the phase to cut is GENERATION — fewer candidates
    costs nothing already spent — never the finishing of a candidate that already passed.

    So the ceiling exists only to stop a HUNG chain, and 1200s is ~13x a healthy call. It
    cannot overrun the tick: `_generate_pack_content` clamps it against the batch's vet
    deadline (run.py:559-561), which stops the batch regardless. 0 disables the floor and
    restores the pure-share behaviour.
    """
    try:
        return max(0.0, float(_sched(cfg, "artifact_budget_floor_s",
                                     _ARTIFACT_BUDGET_FLOOR_S)))
    except (TypeError, ValueError):
        return _ARTIFACT_BUDGET_FLOOR_S


def _vet_budget_frac(cfg) -> float:
    """`schedule.vet_budget_frac` — the share of the tick deadline the WHOLE vetting loop
    (`run.py::run_signal`'s ThreadPoolExecutor over every prescreened candidate, artifacts
    and publish included) may spend before it stops taking new work.

    This is the rail that makes a tick terminate on its own decision. The other two budgets
    bound a PHASE; this one bounds the batch, and it is the only one that can answer the
    question k=50 actually poses.

    THE ARITHMETIC, measured rather than assumed. The tick that force-exited at
    2026-08-15T13:17:56Z ran batch=15 for the full 10800s and produced: 18 vets completed, 9
    survivors, 3 EngineBridge publishes, 528 LLM calls, $2.31 of minimax spend — 1200s of wall
    clock per surviving candidate. `batch_size` is 50 as of 2026-08-15, so a full batch is
    ~10 hours of work inside a 3h deadline on a 2h interval. NO budget makes that fit, and any
    number claiming to is a lie about throughput. What this rail buys is the difference
    between the two available failures:
      - without it: `_force_exit_hung_tick` SIGKILLs the process mid-candidate. Nothing is
        banked from the in-flight vet, no tick row is written, and the daemon relaunches
        knowing nothing. Five recorded breaches, 2026-08-13 to 2026-08-15, all at batch=15.
      - with it: the loop cancels un-started vets, banks every verdict already paid for
        (`store.save` runs inside `vet_candidate`), logs how many it declined to start, and
        returns. The next tick picks the work back up.

    Default 0.85: 9180s of the 10800s deadline, leaving 1620s (27 min) for the publish,
    telemetry and drain work that follows `run_signal` inside the same tick and carries no
    budget of its own. It is deliberately BELOW the force-exit timer rather than equal to it —
    a rail that fires at the same instant as the thing it exists to pre-empt is a coin toss.
    0 disables it and restores the pre-2026-08-15 behaviour, in which the force-exit timer is
    the only stop. Same convention as `gen_budget_frac` and `artifact_budget_frac`.
    """
    try:
        return max(0.0, float(_sched(cfg, "vet_budget_frac", 0.85)))
    except (TypeError, ValueError):
        return 0.85


def _backlog_size(cfg) -> int | None:
    """How many rows a drain could work on right now, or None if it cannot be counted.

    Counts the SAME population `run.py::_cmd_resume` will later drain, via the shared
    `run.drain_survey` — see its docstring for why one definition matters. None (not 0) on any
    failure: 0 would read as "backlog clear" and silently release the generation brake, which
    is the exact direction a counting bug must never fail in.

    The survey's EXCLUDED rows (orphaned, attempt-capped) are printed, not just logged. This
    brake is the one rail that can deadlock — it engages on a count and waits for that count to
    fall — so the rows it is waiting on have to be nameable. `logger.warning` does not reach
    `launchd.err.log` (measured 2026-08-05: `logger.critical` lines appear 18 times there while
    `logger.info` lines appear zero times), so a print to stderr is the only form an operator
    reading the daemon log will ever see.
    """
    try:
        from prospector.drain_state import ledger_path, max_attempts, revet_provisional_kills
        from prospector.run import drain_survey
        from prospector.store import Store
        cap_attempts = max_attempts(cfg)
        # The SAME exclusion the drain will apply (`run._cmd_resume` reads the same knob), or the
        # brake would sit engaged on 161 rows the automatic drain is no longer working — the
        # deadlock this whole shared-definition arrangement exists to prevent.
        revet_dead = revet_provisional_kills(cfg)
        survey = drain_survey(Store(cfg), max_attempts=cap_attempts,
                              revet_provisional_kills=revet_dead)
        if survey.orphaned or survey.stalled or survey.unpublishable:
            note = (f"↻ backlog brake counts {len(survey.workable)} workable row(s); excluded "
                    f"{len(survey.orphaned)} orphaned (index row, no dossier JSON) + "
                    f"{len(survey.stalled)} stalled (>= {cap_attempts} unresolved re-vets, "
                    f"rm {ledger_path(cfg.store_dir)} to retry) + "
                    f"{len(survey.unpublishable)} provisional KILLs (already dead; "
                    f"schedule.revet_provisional_kills: true to work them)")
            logger.warning("%s", note)
            print(note, file=sys.stderr, flush=True)
        return len(survey.workable)
    except Exception as exc:  # noqa: BLE001 — a brake that crashes the daemon is worse than no brake
        # ERROR + stderr, not warning, for the reason spelled out above: logger.warning never
        # reaches launchd.err.log (measured 2026-08-05), so the one line that says "the rail could
        # not read its own input" was written where no operator would ever see it. The caller
        # (`_generation_suppressed`) fails CLOSED on this None — a silent brake is still a brake,
        # but an operator has to be able to find out WHY the daemon stopped generating.
        logger.error("Backlog count failed, brake cannot engage this tick: %s", exc)
        print(f"↻ backlog brake: count FAILED ({exc}) — draining only", file=sys.stderr, flush=True)
        return None


def _spend_cfg(cfg, key: str, default):
    """Read one key from the `spend:` block, dict-or-attr, mirroring `_sched`."""
    spend = getattr(cfg, "spend", None)
    if spend is None:
        return default
    if isinstance(spend, dict):
        return spend.get(key, default)
    return getattr(spend, key, default)


def _subscription_soft_cap_reason(cfg, decision) -> str:
    """Why the SUBSCRIPTION burn should stop generation this tick, or "".

    WHY THIS EXISTS AS A SEPARATE, SOFTER CAP. `spend.daily_subscription_cap_usd` already
    existed and was unarmable in practice: `guard.evaluate()` returns `can_run=False` for it,
    and `run_tick` (:562-565) returns on `not can_run` BEFORE the drain — so arming it freezes
    the backlog at whatever it happens to be when the cap trips. That is exactly the defect
    0efe40e was written to close ("stopping the treadmill also stopped the only thing paying
    it down"), reintroduced through the money rail instead of through PAUSE. The cost of
    freezing the backlog is not hypothetical: every unresolved row owes a full re-vet later,
    so a hard stop does not save that money, it defers it AND holds the rows hostage.

    Consequence, measured 2026-08-06: because arming it broke the drain, it stayed at 0.0 —
    and the estate meter recorded $438.68 of subscription burn that day against no ceiling of
    any kind, while the metered `daily_cap_usd: 20.0` governed 4.4% of consumption.

    So the ceiling that can actually be armed is this one: stop DIGGING, keep RESOLVING. It
    reuses the brake path below, which already carries the wall-clock backstop (5cc325a) and
    the CRITICAL-level logging a silent stop needs. The hard cap is deliberately left in place
    above it as the true floor-of-last-resort; soft is a brake, hard is a wall.

    Reads `decision.today_subscription_usd` rather than rescanning: the guard already paid for
    that scan this tick, and a second scan could disagree with the number the tick logged.
    """
    if decision is None:
        return ""
    cap = _spend_cfg(cfg, "daily_subscription_soft_cap_usd", 0.0)
    try:
        cap = float(cap or 0.0)
    except (TypeError, ValueError):
        # FAIL CLOSED, not open. This used to return "" — i.e. a typo in the one knob that caps
        # subscription burn silently removed the cap and the tick generated as if no ceiling had
        # ever been configured, at warning level, on the rail that recorded $438.68 of ungoverned
        # burn in a day (see above). An unparseable ceiling is not consent to spend, exactly as
        # `_backlog_size`'s None is not consent to generate; the drain keeps running either way,
        # so this is a brake and not a halt, and the next tick re-reads the config.
        logger.error("spend.daily_subscription_soft_cap_usd=%r is not a number — the subscription "
                     "brake cannot be evaluated, so this tick only drains", cap)
        return (f"subscription soft cap UNREADABLE: daily_subscription_soft_cap_usd={cap!r} is not "
                f"a number, so the brake cannot prove it is safe to generate — draining only "
                f"until the config parses")
    if cap <= 0:
        return ""
    spent = float(getattr(decision, "today_subscription_usd", 0.0) or 0.0)
    if spent < cap:
        return ""
    hard = float(getattr(decision, "daily_subscription_cap_usd", 0.0) or 0.0)
    if 0 < hard <= cap:
        # Not fatal, but the operator has expressed a contradiction: the hard wall sits at or
        # below the brake, so guard.evaluate() halts the whole tick first and this never fires.
        logger.warning("spend.daily_subscription_soft_cap_usd=%.2f >= daily_subscription_cap_usd"
                       "=%.2f — the hard cap fires first and the drain will NOT keep running",
                       cap, hard)
    return (f"subscription soft cap: ${spent:.2f} >= ${cap:.2f} subscription-equivalent today "
            f"— generating {_batch_size(cfg, None)} more would dig, so this tick only drains")


#: Wall-clock bound on the PER-TICK grounding probe. Bounded at all because an unbounded probe on
#: the tick path would wedge the daemon loop exactly the way it once wedged startup
#: (`_startup_grounding_check`).
#:
#: 45 -> 120 on 2026-08-15, matching the startup probe. 45s was set as "a tick that cannot get an
#: answer this quickly should not generate", but it was never checked against what the live chain
#: actually costs: the audit log for the same period records a ddg search ANSWERING in 92,184 ms.
#: So the budget sat below normal latency and condemned every tick — the daemon logged
#: "Generation suppressed: grounding degraded" and generated ZERO candidates from 06:25Z onward
#: while retrieval was slow but working. A degradation gate whose threshold is under the healthy
#: latency is not a gate, it is an outage. Re-measure this against the ddg/exa p95 before lowering.
_TICK_PROBE_TIMEOUT_S = 120


def _probe_grounding_once(cfg, timeout_s: int) -> tuple[str, BaseException | None]:
    """One live search against the LIVE grounding stack, hard-bounded by `timeout_s`.

    Returns ("", None) when healthy, ("timeout", None) when the probe did not answer in time, or
    ("error", exc) when it raised. Shared by the startup refusal and the per-tick generation gate
    so the two can never drift into disagreeing about what "grounding is up" means.

    The DiskCache unwrap is load-bearing and is not an optimisation: the probe query is fixed, so
    it is cached after the first-ever run and a cache hit "passes" a completely dead retrieval
    stack (observed 2026-07-28: audit row provider=cache, cache_hit=true).
    """
    outcome: dict = {}

    def _probe() -> None:
        try:
            from prospector.retrieval import DiskCache, make_provider
            provider = make_provider(cfg)
            if isinstance(provider, DiskCache):
                provider = provider.inner
            provider.search("startup sanity check", k=1)
            outcome["ok"] = True
        except BaseException as exc:  # noqa: BLE001 — carried to the caller, which decides
            outcome["error"] = exc

    probe = threading.Thread(target=_probe, name="grounding-probe", daemon=True)
    probe.start()
    probe.join(timeout_s)
    if probe.is_alive():
        return "timeout", None
    if "error" in outcome:
        return "error", outcome["error"]
    return "", None


def _grounding_degraded_reason(cfg) -> str:
    """Why this tick must skip GENERATION because retrieval is degraded RIGHT NOW, or "".

    THE CONTROL VARIABLE, AND WHY IT IS THIS ONE. `schedule.backlog_cap` gated generation on a
    STOCK — how many unresolved rows exist. Measured 2026-08-06 against the live store, that is
    the wrong variable, and the whole catalogue says so:

      * 154 of 154 drainable rows carry `retrieval_degraded=1`. Every single one.
      * The flag discriminates rather than tautologically marking everything: across all 1,483
        non-tombstoned rows only 180 (12%) are degraded. 1,220 KILLs and 83 PASSes were
        generated and fully ruled with `degraded=0` — they never touched the backlog.
      * So generation VOLUME does not mint backlog rows; failed RETRIEVAL does. 88% of
        everything ever generated was ruled on the spot.

    That makes the backlog burst-shaped, not treadmill-shaped. By `created_at`: 95 rows on
    2026-06-24, 44 on 2026-08-06, and 0-4 on every other day across six weeks. The
    "+12 backlog rows per tick BY DESIGN" arithmetic this module used to assert predicts ~144
    new rows EVERY day at a 2h cadence; the histogram refutes it. The +12 holds only while
    retrieval is broken, which is the condition this function tests directly.

    The failure mode of stock-based control is unbounded memory: on 2026-08-06 the 2026-06-24
    outage alone was 95 of the 154 rows, so removing that one day puts the backlog at 59, under
    the cap of 100. A six-week-old retrieval outage was the reason the daemon generated nothing
    that afternoon — and draining old rows does nothing whatsoever to make new retrieval succeed.

    A rate has no such memory. This probe answers "is retrieval working, now", so a tick
    suppressed by a genuine outage un-suppresses itself the moment the outage ends, with no
    state file, no hysteresis and nothing to reset by hand.

    FAIL-CLOSED ON GENERATION, deliberately: a probe we could not complete is not evidence that
    retrieval works, and generating into a broken stack is precisely what mints the DEFER rows.
    The drain keeps running either way — this returns a reason, and every caller of
    `_generation_suppressed` drains on it. Costs one search call per tick (free on the ddg head
    of the chain), against a 2h cadence.
    """
    if not _sched(cfg, "gate_generation_on_grounding", True):
        return ""
    kind, exc = _probe_grounding_once(cfg, _TICK_PROBE_TIMEOUT_S)
    if not kind:
        return ""
    if kind == "timeout":
        return (f"grounding degraded: the retrieval probe did not answer within "
                f"{_TICK_PROBE_TIMEOUT_S}s — generating now would mint DEFER rows rather than "
                f"verdicts, so this tick only drains")
    return (f"grounding degraded: the retrieval stack failed its probe ({exc}) — generating now "
            f"would mint DEFER rows rather than verdicts, so this tick only drains")


def _generation_suppressed(cfg, decision=None) -> str:
    """Why this tick must skip GENERATION but still DRAIN, or "" to generate normally.

    Four triggers, one manual and three automatic, in the order they are tested:

      * `store/scheduler/PAUSE_GENERATION` — the operator's half-stop.
      * `spend.daily_subscription_soft_cap_usd` — the money brake. Default OFF (0.0).
      * `schedule.gate_generation_on_grounding` — the CAUSAL gate. Default ON. Suppresses
        generation exactly when retrieval is degraded, which is the only condition under which
        generating adds to the backlog at all. See `_grounding_degraded_reason` for the
        measurement that picked this variable over the backlog count.
      * `schedule.backlog_cap` — the legacy stock-based brake. Default OFF (None), and set to 0
        in this repo's config.yaml as of 2026-08-06 because it controlled on the wrong variable:
        it suppressed generation for six weeks over an outage that had already ended. Retained,
        not deleted, as a floor-of-last-resort against unbounded queue growth.

    THE DEFECT THE BACKLOG CAP ORIGINALLY CLOSED, and the correction. It was introduced against
    `batch_size: 15` versus a `resume_per_tick` of 3, described as "+12 backlog rows per tick BY
    DESIGN — not moat flakiness, arithmetic". The arithmetic is right only when every generated
    candidate DEFERS, i.e. only during a retrieval outage. Measured across the live store on
    2026-08-06, 88% of generated rows were ruled immediately and never entered the backlog, so
    in normal operation the true rate is near zero and steady-state creation (0-4 rows/day) sits
    far below drain capacity (3/tick x 12 ticks = 36/day). The queue was never a treadmill; it
    was two outages.

    Deliberately NO hysteresis band on the backlog cap. A single threshold can alternate
    tick-to-tick at the boundary, and that is harmless here because BOTH sides of the
    alternation do useful work: above the cap the tick drains, below it the tick generates.
    """
    pause_file = Path(str(cfg.store_dir)) / "scheduler" / _GENERATION_PAUSE_FILENAME
    if pause_file.exists():
        return f"generation paused: {pause_file} present (the drain still runs)"

    # Money before backlog: when both would fire, the operator needs to be told it is the SPEND
    # that stopped the tick, not the queue depth. Both outcomes are identical (drain only).
    soft = _subscription_soft_cap_reason(cfg, decision)
    if soft:
        return soft

    # Cause before symptom: when both would fire, the operator needs to be told retrieval is
    # broken, not that a queue is deep — the queue is downstream of exactly this. Tested before
    # the backlog cap for that reason, and because it is the gate that self-clears.
    grounding = _grounding_degraded_reason(cfg)
    if grounding:
        return grounding

    cap = _sched(cfg, "backlog_cap", None)
    if cap is None:
        return ""
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        # FAIL OPEN — the brake goes OFF, generation continues — and this is deliberately the
        # OPPOSITE of the `backlog is None` branch below. The two look symmetrical and are not:
        #
        #   * `backlog is None` is an operator who opted in with a VALID cap, whose rail then
        #     could not count. The threshold is known; only the reading failed. Stopping is
        #     honest and it self-clears the moment the count works.
        #   * an unparseable cap is a config that never expressed a threshold at all. There is
        #     no number to be under or over, so there is nothing to prove safe — and nothing
        #     self-clears, because the config does not change on its own. Failing closed here
        #     freezes generation indefinitely on a typo, which is exactly the unbounded-memory
        #     failure that "gate on the RATE, not the stock" exists to kill (CLAUDE.md).
        #
        # It is also the only consistent reading: `cap <= 0` below already treats 0 AND -1 —
        # equally unusable thresholds from an operator who "opted in" — as brake-off. Singling
        # out a bad STRING to freeze on, while waving through a bad INT, is not a safety policy.
        #
        # This branch briefly failed closed on the integrate/minimax-into-main branch (0b5e655)
        # and is restored here on merge. Its grievance was real and is answered without the
        # freeze: a typo used to be a log line nobody reads, so it now raises a CRITICAL
        # operator alert. The floor-of-last-resort being off is worth waking someone for; it is
        # not worth stopping the supply of the storefront for.
        logger.critical("schedule.backlog_cap=%r is not an integer — the backlog brake is OFF "
                        "until this is fixed; generation continues unbraked", cap)
        try:
            from prospector.scheduler.alerts import emit_alert
            emit_alert(cfg, severity="critical", key="backlog_cap_unreadable",
                       title="Backlog brake is OFF: schedule.backlog_cap does not parse",
                       message=(f"schedule.backlog_cap={cap!r} is not an integer, so the brake "
                                f"has no threshold to apply. Generation is running UNBRAKED. "
                                f"Fix the value in config.yaml; the daemon reads it on restart."),
                       backlog_cap=repr(cap))
        except Exception as exc:  # alerting must never decide whether the daemon generates
            logger.error("Could not raise the backlog_cap_unreadable alert: %s", exc)
        return ""
    if cap <= 0:
        return ""
    backlog = _backlog_size(cfg)
    if backlog is None:
        # THE RAIL CANNOT FUNCTION, SO IT STOPS — it does not wave the tick through. Same call
        # guard.py makes when the clock goes backwards and the daily cap can no longer be summed:
        # "the honest answer when the rail cannot function is to stop, not to spend." The
        # operator opted into this brake explicitly (it is default-off); an unreadable store is
        # not consent to generate. The drain still runs, so this is a pause, not a deadlock —
        # and the very next tick re-counts.
        return ("backlog brake: the drainable backlog could not be counted, so the brake cannot "
                "prove it is safe to generate — draining only until the count works")
    if backlog < cap:
        return ""
    return (f"backlog brake: {backlog} drainable rows >= schedule.backlog_cap {cap} "
            f"— generating {_batch_size(cfg, None)} more would dig, so this tick only drains")


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

    A tick that cannot verify has nothing worth doing: generation is only useful if some brain
    can then rule on it. So skip the whole tick.

    `trusted_only=False` (founder directive 2026-08-08, which re-added minimax to `operator:`):
    a tick is blind only when EVERY configured verdict brain is dead, not merely every TRUSTED
    one. With a provisional tail alive the moat CAN rule — provisionally now, finally on the
    re-vet — and that is the trade the founder accepted. Leaving this trusted-only would have
    made the whole re-add inert, because the daemon would still have skipped every tick in
    exactly the situation the fallback exists for: claude_cli down.

    This does NOT wave the drain through. `run.py::_cmd_resume` runs its own preflight at the
    default `trusted_only=True`, so a drain-only tick still refuses to re-vet into a chain that
    can only re-stamp `provisional` — the row would not move, and the drain's CLI load is part
    of what keeps the trusted brain benched. The two callers deliberately disagree; they share
    the one classifier so that they cannot disagree by ACCIDENT.

    Uses `dead_until()`, NOT `is_dead()`: `is_dead` can CLAIM the half-open probe slot
    (health.py), and a bookkeeping check must never consume the one call whose job is to
    measure recovery. This reads the mark; it does not spend the probe.
    """
    from prospector.health import moat_blind_reason
    return moat_blind_reason(cfg, trusted_only=False)


#: Share of the tick's hard deadline the backlog drain may spend. 0 disables the wall.
#:
#: MEASURED, not chosen by feel. The drain runs FIRST in a tick, inside the hard-deadline
#: Timer, and until 2026-08-15 it had no budget of any kind. On the daemon's own log:
#:   tick 2026-08-15T10:16:59Z — 3 rows took 4197s of a 10800s tick (39%) before generation;
#:   tick 2026-08-15T13:23:07Z — row 1 alone took 4127s, row 2 was still running at +5885s (55%).
#: So the tick's largest single consumer was the one phase nothing bounded, and the vetting
#: rails downstream were being handed a tick that had already been spent.
#:
#: 0.15 x 10800s = 1620s, against a measured 122s for a KILL that gates out early and ~2800-4100s
#: for a row that passes and generates artifacts. The wall therefore binds on exactly the rows it
#: should: it will not interrupt a cheap re-vet, and it stops the drain from spending a whole
#: tick on one expensive one. Stopping is lossless — an unreached row keeps its state and its
#: place in the backlog — which is why a hard wall is the right instrument here and a parked
#: DEFER row is the right one in the vetting batch.
_DRAIN_BUDGET_FRAC = 0.15


def _drain_budget_frac(cfg) -> float:
    """`schedule.drain_budget_frac`, bounded to [0, 1]. Junk or missing -> the default."""
    raw = _sched(cfg, "drain_budget_frac", _DRAIN_BUDGET_FRAC)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DRAIN_BUDGET_FRAC
    # Negative can never become a deadline already in the past at t=0, which would skip every
    # row and report a drain that ran; >1 can never promise more than the tick has.
    return min(1.0, max(0.0, val))


def _drain_pass(cfg, n_resume: int) -> dict | None:
    """Re-vet up to `n_resume` backlogged candidates. Never raises. None if the drain is off.

    Extracted from `_default_generate` on 2026-08-06 so a tick that is NOT generating can still
    drain. Before that the drain lived inside generation, so every reason to skip generation —
    `PAUSE`, and now the backlog brake — also silently switched off the only mechanism that pays
    the backlog down. Stopping the treadmill and stopping the recovery were the same act, which
    is why setting `PAUSE` at 10:30Z could not have cleared the 343 rows no matter how long it
    ran.
    """
    # RECOVERY RUNS BEFORE THE DRAIN'S OWN OFF-SWITCH, and is not governed by it. Work abandoned
    # by a killed process has no index row, so it is not backlog and no backlog policy is about
    # it — `resume_per_tick: 0` turns the treadmill off, not the repair. This is the same
    # coupling the drain was pulled out of `_default_generate` to break, one cause over.
    # Measured 2026-08-17: 12 candidates abandoned in four days, 10 with no record in `store/`.
    try:
        from prospector.run import recover_abandoned
        healed = recover_abandoned(cfg, publish=True)
        if healed.get("orphans"):
            logger.critical("Tick recovery pass: %s", healed, extra={"recovery": healed})
    except Exception as exc:  # noqa: BLE001 — a failed repair must never stop the tick
        logger.warning("Tick recovery pass failed: %s", exc)

    if not n_resume:
        return None
    from prospector.run import resume_deferred
    d_frac = _drain_budget_frac(cfg)
    drain_budget = (d_frac * _TICK_HARD_DEADLINE_S) if d_frac > 0 else None
    # The per-row artifact ceiling, from the SAME key the vetting batch uses, applied to the
    # drain's own budget rather than the tick's: a drained row's content phase measured 51-56%
    # of its total cost, so bounding the pass without bounding the phase inside it would just
    # move the overrun one level down.
    a_frac = _artifact_budget_frac(cfg)
    drain_art_budget = (a_frac * drain_budget) if (a_frac > 0 and drain_budget) else None
    logger.critical(
        "Drain budget: %s for %d row(s), artifacts/row %s (tick hard deadline %ds)",
        f"{drain_budget:.0f}s" if drain_budget else "unbounded", n_resume,
        f"{drain_art_budget:.0f}s" if drain_art_budget else "unbounded",
        _TICK_HARD_DEADLINE_S,
        extra={"drain_budget_s": drain_budget, "drain_artifact_budget_s": drain_art_budget,
               "n_resume": n_resume, "tick_deadline_s": _TICK_HARD_DEADLINE_S})
    try:
        resumed = resume_deferred(cfg, limit=n_resume, publish=True,
                                  budget_s=drain_budget,
                                  artifact_time_budget_s=drain_art_budget)
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
        return resumed
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
        return resumed


#: Cadence while the generation brake is engaged. 15 min: fast enough that the live 343-row
#: backlog clears in ~6 h at 15 rows/tick instead of ~46 h on the 2 h generation cadence, and
#: slow enough that each pass finishes first — the measured drain rate is ~5.5 min/candidate,
#: so 15 rows is well over one window and the loop is paced by the work, not the timer.
_DRAIN_ONLY_INTERVAL_S = 900


def _drain_only_interval_s(cfg, interval: int) -> int:
    """Sleep between drain-only ticks. Never longer than the normal interval — the brake must
    not be able to make the daemon *slower* than it would be with generation running."""
    raw = _sched(cfg, "drain_only_interval_s", _DRAIN_ONLY_INTERVAL_S)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        logger.warning("schedule.drain_only_interval_s=%r is not an integer", raw)
        val = _DRAIN_ONLY_INTERVAL_S
    return max(1, min(int(interval), val))


def _drain_only_resume_per_tick(cfg) -> int:
    """How many rows a DRAIN-ONLY tick may re-vet. Defaults to `batch_size`, not 3.

    `resume_per_tick` is 3 because a normal tick spends most of its budget generating. A tick
    that is not generating has that whole budget free, and the bound exists only because the
    spend guard evaluates once per tick — so the honest default is the batch it is not running.
    At the live config that is 15 rather than 3: 343 rows clear in ~23 ticks instead of ~114.
    """
    explicit = _sched(cfg, "drain_only_resume_per_tick", None)
    if explicit is not None:
        try:
            return max(0, int(explicit))
        except (TypeError, ValueError):
            logger.warning("schedule.drain_only_resume_per_tick=%r is not an integer", explicit)
    return max(_resume_per_tick(cfg), _batch_size(cfg, None))


#: How many SLA-expired PASSes one tick may re-verify. Deliberately NOT 0.
#:
#: `prospector/decay.py::run_decay_loop` shipped with no production caller at all — its only
#: importer was `tests/sim/test_decay.py` — so `reverify_due_at` was written on every dossier
#: and read by nothing. Measured 2026-08-06: 29 of 83 live PASSes were past their SLA, and the
#: 5 that fail today's `moat_ungrounded` gate were ALL minted on or before 2026-06-28, the day
#: that gate landed (73ae976). Shipping this defaulted to 0 would reproduce the exact bug it
#: fixes: a rail that exists, is tested, and never runs.
#:
#: 2 per tick is small on purpose. A re-vet is a full moat run (~5.5 min measured) competing
#: with the drain for the same subscription CLI slots, so this is a trickle that clears the
#: overdue population over roughly a day at the live cadence, not a burst that starves the
#: drain. Override with `schedule.decay_per_tick`; 0 disables the sweep.
_DECAY_PER_TICK_DEFAULT = 2


def _decay_per_tick(cfg) -> int:
    """How many SLA-expired PASSes one tick may re-verify. 0 disables the decay sweep."""
    raw = _sched(cfg, "decay_per_tick", _DECAY_PER_TICK_DEFAULT)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        logger.warning("schedule.decay_per_tick=%r is not an integer", raw)
        return _DECAY_PER_TICK_DEFAULT


def _decay_sweep_budget(cfg) -> int:
    """How many rows THIS process may re-verify: `_decay_per_tick`, or 0 in producer mode.

    THE SWEEP IS MOAT WORK, AND THE PRODUCER OWNS NO MOAT WORK. It is the same class as the
    drain — `run_decay_sweep` re-verifies SLA-expired PASSes through the full verdict chain —
    so leaving it on the producer's tick left the split half-built: the tick would still block
    on the moat's clock, the one thing the split exists to end. Not a small residue either. At
    the worst measured vet (4127s, 2026-08-15) two rows is 8254s against the 10800s tick
    deadline, so the sweep alone can take three quarters of the budget that was supposed to
    belong to generation. `prospector/consumer.py` runs it instead, on its own cadence.

    THE UNLIST DRAIN IS NOT GATED, AND MUST NEVER BE. `_decay_pass` calls `_unlist_pass`
    outside its `if n_decay`, so a producer returning 0 here still pulls KILLed packs off sale
    every tick. The asymmetry is the point: the sweep is expensive LLM work that can wait for
    the half of the estate that owns a brain, while the unlist drain is a cheap one-way
    actuator whose cost when skipped is a killed pack still taking money — six of them,
    measured 2026-08-09. It is safe in both roles at once by construction, because it can only
    ever set `isListed: false` and never charges anyone, so both halves running it costs a
    wasted round trip and nothing worse.
    """
    return 0 if producer_mode(cfg) else _decay_per_tick(cfg)


#: `tools/unlist_killed.py` needs the Store.Api internal key, which is exactly why the
#: unattended re-vet sweep does not call Store.Api itself. Running it as a bounded subprocess
#: preserves that boundary: the sweep stays credential-free, the drain is a separate idempotent
#: process.
_UNLIST_TIMEOUT_S = 180


def _proc_tail(proc) -> str:
    """The last 300 characters a subprocess said, WITHOUT dropping the stream that says why.

    This was `(proc.stdout or proc.stderr)`, which discards stderr whenever stdout is non-empty --
    and a python script that prints progress and then raises does exactly that, so the tail logged
    beside "killed pack(s) may still be selling" was the progress and not the traceback. Same
    defect, same day, as `scripts/worktree_snapshot.py::git`; memory
    `a-step-that-discards-the-stderr-explaining-its-own-death`.

    On success stdout alone, because it is the report. On failure both, stderr last, because the
    tail is cut from the END and the reason is what must survive the cut.
    """
    if proc.returncode == 0:
        return (proc.stdout or "").strip()[-300:]
    both = "\n".join(x for x in (proc.stdout, proc.stderr) if x and x.strip())
    return both.strip()[-300:]


def _unlist_pass(cfg) -> dict | None:
    """Drain `pending_unlist.jsonl` against Store.Api. Never raises. None if nothing is queued.

    Self-gating on an empty queue keeps a normal tick free: the check is one file read, and the
    HTTP round trip happens only when there is actually a pack to pull off sale.

    Safe to run unattended in one direction only, which is the direction it runs: the drain
    sends `PATCH /internal/catalog/{id}/listing` with `isListed: false` and verifies the echoed
    row (`tools/unlist_killed.py:_unlist_one`), re-queueing anything that arrived mid-flight
    (`:_commit`). It can never list a pack and never charges anyone. So the cost of running it
    too often is a wasted round trip, while the cost of not running it is a KILLed pack taking
    money — measured 2026-08-09, when the previous `fly ssh` + `sqlite3` actuator had been
    failing silently and left 6 killed packs on sale.
    """
    import subprocess  # local, matching this module's existing convention

    queue = Path(str(cfg.store_dir)) / "scheduler" / "pending_unlist.jsonl"
    try:
        if not queue.exists() or queue.stat().st_size == 0:
            return None
    except OSError as exc:
        # NOT None. None is this function's word for "the queue is empty, nothing to pull off
        # sale", and every other failure path below already returns {"error": ...} at CRITICAL.
        # A queue we cannot stat is the one state where "nothing queued" and "a KILLed pack may
        # still be selling" looked identical to the caller (`_decay_pass` merges this into the
        # tick dict) — the exact silence that left 6 killed packs on sale on 2026-08-09.
        out = {"error": f"queue unreadable: {type(exc).__name__}: {exc}"}
        logger.critical("Unlist queue unreadable — killed pack(s) may still be selling: %s", exc)
        print(f"🛒 unlist queue UNREADABLE (tick continues): {exc}", file=sys.stderr, flush=True)
        return out

    script = Path(__file__).resolve().parents[2] / "tools" / "unlist_killed.py"
    if not script.exists():
        logger.critical("pending_unlist.jsonl has entries but %s is missing — killed pack(s) "
                        "may still be selling", script)
        return {"error": f"missing {script.name}"}
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                              timeout=_UNLIST_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        out = {"error": f"{type(exc).__name__}: {exc}"}
        logger.critical("Unlist drain FAILED — killed pack(s) may still be selling: %s",
                        out["error"])
        print(f"🛒 unlist drain FAILED (tick continues): {out['error']}",
              file=sys.stderr, flush=True)
        return out

    out = {"rc": proc.returncode, "tail": _proc_tail(proc)}
    # CRITICAL on BOTH paths: below it never reaches launchd.err.log (verified 2026-08-05), and a
    # shelf actuator whose success is invisible is how this loop stayed unwired for two months.
    if proc.returncode == 0:
        logger.critical("Unlist drain: %s", out["tail"])
        print(f"🛒 unlist drain: {out['tail']}", file=sys.stderr, flush=True)
    else:
        logger.critical("Unlist drain rc=%d — killed pack(s) may still be selling: %s",
                        proc.returncode, out["tail"])
        print(f"🛒 unlist drain rc={proc.returncode}: {out['tail']}", file=sys.stderr, flush=True)
    return out


_RECOVER_TIMEOUT_S = 900


def _recover_pass(cfg) -> dict | None:
    """Retry the PASSes the publish gate refused. None when it is not this tick's turn.

    WHY THIS EXISTS. `alerts.py` already says it, and said it before this rail was built: "a
    PASS that is not on the shelf stays off it forever on its own — the engine has no retry
    that republishes, so the state is permanent until a human runs a republish." That is why
    44 packs were stranded on 2026-08-17, every one of them passed within the same month:
    the strand is not a legacy backlog, it re-accumulates continuously. An alert names the
    problem; only a retry pays it down.

    Bounded three ways, because this runs inside a tick that has a hard deadline:
    `schedule.recover_per_tick` caps the packs, `_RECOVER_TIMEOUT_S` caps the wall clock,
    and `schedule.recover_interval_s` caps the cadence. `regenerate` is deliberately NOT in
    the route list — it is full artifact generation and belongs to the generation budget,
    not to a repair pass.

    The ledger (`store/ops/pack_recovery.jsonl`) is what stops this becoming a treadmill: a
    route that has failed MAX_ATTEMPTS times on an identical failure signature is skipped,
    so a pack that genuinely cannot recover is paid for at most three times, not once per
    tick forever.
    """
    import subprocess  # local, matching this module's existing convention

    if not _sched(cfg, "recover_stranded_packs", True):
        return None
    limit = int(_sched(cfg, "recover_per_tick", 3) or 0)
    if limit <= 0:
        return None

    marker = Path(str(cfg.store_dir)) / "scheduler" / "last_pack_recovery"
    interval = int(_sched(cfg, "recover_interval_s", 3600) or 0)
    try:
        if interval and marker.exists() and (time.time() - marker.stat().st_mtime) < interval:
            return None
    except OSError:
        pass                                   # an unreadable marker means "run it", not "skip"

    script = Path(__file__).resolve().parents[2] / "tools" / "recover_stranded_passes.py"
    if not script.exists():
        logger.error("Pack recovery skipped: %s is missing", script)
        return {"error": f"missing {script.name}"}

    # --timeout below _RECOVER_TIMEOUT_S, not equal to it: the gate resolves every citation
    # URL over the network (`lint_check_urls`) and a pack with 30+ citations, some of them
    # timing out, runs for minutes. Without a per-pack cap the FIRST slow pack eats the whole
    # budget and the outer timeout kills the run before it writes a single ledger row.
    # `publish` belongs in this list whenever --publish is on, and leaving it out cost the
    # shelf a day of sales. The child routes each pack to exactly ONE route, and a pack that
    # lints clean and was simply never listed routes to `publish`
    # (`tools/recover_stranded_passes.py::_route`). The route filter runs FIRST
    # (`recover_stranded_passes.py:397`), so a `publish`-routed pack was dropped with
    # "route publish not selected" before the --publish flag could ever apply to it. Measured
    # on the live tick of 2026-08-18T18:53Z: `SKIP [0fcc840981645d85] publish: route publish
    # not selected`, one of three packs that were finished, clean and unsold. Two switches
    # that have to agree, so derive one from the other rather than writing it twice.
    routes = ["audit", "rebundle", "copy"]
    publish = bool(_sched(cfg, "recover_publish", True))
    if publish:
        routes.append("publish")
    cmd = [sys.executable, str(script), "--apply", "--routes", ",".join(routes),
           "--limit", str(limit), "--jobs", "2", "--timeout", "240"]
    if publish:
        # The same money-rail action the engine already takes on any fresh PASS, applied to
        # a repaired one: it lists only what the deterministic gate now passes.
        cmd.append("--publish")
    # Pin the child to THIS tick's store. `recover_stranded_passes.py:56` reads
    # PROSPECTOR_STORE_DIR and falls back to the store beside its own file, so a child launched
    # without it repairs and republishes whatever store the ambient environment happens to name --
    # not the one the tick is running against. That is a money-rail action (`--publish` above) on
    # someone else's catalogue, and it is how a unit test with a tmp_path store reached the
    # operator's real one on 2026-08-17.
    env = dict(os.environ, PROSPECTOR_STORE_DIR=str(cfg.store_dir))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_RECOVER_TIMEOUT_S, env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Pack recovery FAILED (tick continues): %s: %s", type(exc).__name__, exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        except OSError:
            pass                               # cadence is an optimisation, not a correctness rail

    out = {"rc": proc.returncode, "tail": _proc_tail(proc)}
    logger.info("Pack recovery: %s", out["tail"])
    return out


def _decay_pass(cfg, n_decay: int) -> dict | None:
    """Re-verify up to `n_decay` SLA-expired PASSes, then unlist whatever that killed.

    Never raises. None when the sweep is off AND nothing was queued to unlist.

    Callers must already have cleared the guard (spend/PAUSE) and the moat preflight — a decay
    sweep on a blind moat would only DEFER every row, which `run_decay_loop` correctly refuses
    to persist, so it would be pure cost for no state change.

    THE UNLIST DRAIN RUNS LAST, AND RUNS EVEN WHEN THE SWEEP IS OFF. `decay.py::_queue_unlist`
    (`:83-107`) appends to `pending_unlist.jsonl` the moment a re-vet turns a published PASS into
    a KILL, but it holds no Fly credentials, so the queue is inert until something drains it —
    and until 2026-08-07 nothing in production did. That cost real money twice: 4 packs on
    2026-08-06 and 2 more on 2026-08-07 (`f75365e48af08750`, `839afa0ef83b82be`) stayed on sale
    at £49 on mumchimp.com with only a `.kill.json` dossier on disk. Draining even when
    `n_decay` is 0 matters because switching the sweep off must not strand a queue an earlier
    tick already wrote.
    """
    out: dict | None = None
    if n_decay:
        # Late import, mirroring `_drain_pass`: a tick that returned early never builds brains.
        from prospector.run import run_decay_sweep
        try:
            out = run_decay_sweep(cfg, limit=n_decay)
            logger.info("Tick decay sweep: %s", out)
            # STDERR + print for the same reason as `_drain_pass`: logging below CRITICAL never
            # reaches launchd.err.log (verified 2026-08-05), so a sweep that only logged at INFO
            # would be indistinguishable from the "no caller" bug this whole change fixes.
            print(f"⟳ tick decay sweep: {out}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            # A decay failure must never cost the tick its generation batch. Recorded, not raised.
            out = {"error": f"{type(exc).__name__}: {exc}"}
            logger.warning("Tick decay sweep failed (tick continues): %s", out["error"])
            print(f"⟳ tick decay sweep FAILED (tick continues): {out['error']}",
                  file=sys.stderr, flush=True)

    unlisted = _unlist_pass(cfg)
    if unlisted is not None:
        out = dict(out or {})
        out["unlisted"] = unlisted
    return out


#: Cursor for `schedule.market_rotation`, in the scheduler dir beside the other tick state.
#: Persisted rather than derived from a tick counter because the daemon re-execs itself whenever
#: config.yaml or the sources change (`reload_on_code_change`), and an in-memory counter would
#: restart at 0 on every re-exec — which on a two-code rotation means the FIRST code every time
#: and the second one never. A file is the only thing that survives the re-exec.
_MARKET_ROTATION_STATE = "market_rotation.json"


def _market_rotation(cfg) -> list[str]:
    """Validated codes from `schedule.market_rotation`. `[]` => rotation off.

    All-or-nothing on purpose (see the config.yaml prose): one unresolvable code disables the
    whole rotation and falls back to `active_market`, because a rotation silently reduced to its
    valid subset is indistinguishable — from the phone, from the logs, from the dossiers — from
    one that is working.
    """
    raw = _sched(cfg, "market_rotation", "") or ""
    codes = (
        [str(c).strip().lower() for c in raw]
        if isinstance(raw, (list, tuple))
        else [c.strip().lower() for c in str(raw).split(",")]
    )
    codes = [c for c in codes if c]
    if not codes:
        return []
    for code in codes:
        try:
            cfg.resolve_market(code)
        except Exception as exc:  # noqa: BLE001 — UnknownMarketError, but never crash a tick
            logger.warning(
                "schedule.market_rotation=%r disabled: %r does not resolve (%s). "
                "Generation falls back to active_market=%r.",
                raw, code, exc, getattr(cfg, "active_market", ""),
            )
            return []
    return codes


def _rotate_market(cfg):
    """`(cfg, code)` for this batch's market. `code` is None when rotation is off.

    Advances the persisted cursor BEFORE generating, so a batch that dies mid-run does not pin
    the rotation to one market forever. Any failure to read or write the cursor degrades to
    "no rotation" and leaves `cfg` untouched — steering must never be able to stop a tick.
    """
    codes = _market_rotation(cfg)
    if not codes:
        return cfg, None
    path = paths.scheduler_dir(cfg) / _MARKET_ROTATION_STATE
    idx = 0
    try:
        if path.is_file():
            idx = int(json.loads(path.read_text(encoding="utf-8")).get("next", 0))
    except (OSError, ValueError, TypeError) as exc:
        # Narrowed from `except Exception`: these three are everything read_text/json.loads/int
        # can actually raise here (json.JSONDecodeError subclasses ValueError). A broad catch made
        # a refactor's AttributeError look exactly like a missing cursor file — silently pinning
        # the rotation to codes[0] forever, which is the failure this cursor exists to prevent.
        logger.warning("market rotation cursor unreadable (%s); restarting at 0", exc)
        idx = 0
    code = codes[idx % len(codes)]
    try:
        path.write_text(
            json.dumps({"next": (idx + 1) % len(codes), "codes": codes, "last": code}),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("market rotation cursor unwritable (%s); rotation may repeat", exc)
    try:
        return cfg.for_market(code), code
    except Exception as exc:  # noqa: BLE001
        logger.warning("market rotation could not apply %r (%s); using active_market", code, exc)
        return cfg, None


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
    from prospector.run import _resolve_lanes, run_signal

    # THE CLOCK THE BUDGETS BELOW ARE FRACTIONS OF. The caller arms the hard-deadline Timer
    # immediately before calling this function (`threading.Timer(_TICK_HARD_DEADLINE_S, ...)`,
    # ~line 1424), so this instant is the tick's T0 to within the cost of one log line.
    _tick_started_mono = time.monotonic()
    # PRODUCER MODE owns both halves of the tick or neither (see `producer_mode`). A producer
    # does not drain: the consumer process does, on the queue's schedule instead of this one's.
    _producer = producer_mode(cfg)
    resumed = None if _producer else _drain_pass(cfg, _resume_per_tick(cfg))
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
    # Market rotation applies to GENERATION ONLY, and deliberately after the drain above: a
    # backlogged candidate was created under the market it was created under, and re-vetting it
    # through a different market's retrieval and framing would change the question it is being
    # asked. The drain keeps `active_market`; only the new batch rotates.
    cfg, rotated_market = _rotate_market(cfg)
    lanes = _resolve_lanes(cfg, argparse.Namespace(lane=None))
    # GENERATION TIME BUDGET (the rail behind the 2026-08-14 force-exit): generation gets
    # at most `schedule.gen_budget_frac` (default 0.35) of the tick's hard deadline, then
    # returns whatever it has so vetting/artifacts/publish still run. 0 disables the rail.
    # 0.35 x 10800s = 63 min, against a measured healthy generation phase of ~3 min
    # (launchd.err.log 2026-08-11 ticks: 2.9 min for k=15) — the budget only bites when
    # the chain is degraded, which is exactly when the old behaviour ate the whole tick.
    #
    # ALL THREE ARE FRACTIONS OF THE TIME THAT IS LEFT, NOT OF THE WHOLE DEADLINE.
    # This was the hole the first live k=50 proof run opened, 2026-08-15, before it reached
    # vetting at all: the drain above runs INSIDE the hard-deadline Timer but has no budget of
    # its own, and `run_signal` starts its vet clock when it is called. Fractions of the FULL
    # deadline therefore promised `drain + 0.85 x D` of work inside a `D` fence — the rail
    # would have been overrun by the force-exit it exists to prevent whenever the drain took
    # more than 15% of the tick. That is not a corner: `_resume_per_tick` re-vets 3 rows at a
    # measured ~1200s of wall clock per candidate (2026-08-15 profile of the 10:17:56Z tick),
    # i.e. up to a third of a 10800s tick spent before the first budget is even computed.
    # Measuring the remainder makes the rails a guarantee again — whatever the drain costs,
    # vetting stops at 85% of what survives it and 15% of that remainder is left as headroom.
    _spent = time.monotonic() - _tick_started_mono
    _left = max(0.0, _TICK_HARD_DEADLINE_S - _spent)
    frac = _gen_budget_frac(cfg)
    budget = (frac * _left) if frac > 0 else None
    # THE OTHER TWO RAILS, added 2026-08-15 (see `_artifact_budget_frac` and
    # `_vet_budget_frac` for the measurements). `gen_budget_frac` alone bounded ~3 minutes of
    # a 180-minute tick; the artifact/content phase spanned 152 of those minutes with no
    # budget at all, and the batch as a whole had no stop except a SIGKILL.
    #   art_budget — PER-CANDIDATE ceiling on artifacts + marketing copy.
    #   vet_budget — ceiling on the WHOLE batch; past it the loop cancels un-started vets and
    #                returns what it banked, so the tick ends by decision, not by force-exit.
    art_frac = _artifact_budget_frac(cfg)
    art_budget = (art_frac * _left) if art_frac > 0 else None
    # THE CEILING IS A HANG DETECTOR, NOT A SHARE OF THE TICK. Measured 2026-08-15 in the
    # k=50 proof run: candidate f2ac7df9995c334e PASSED all seven checks, then published
    # UNLISTED with build_spec/gtm_plan/ops_plan all empty, because a share-of-the-remainder
    # ceiling had already been spent by the time its content phase began. All three retries
    # logged in the SAME second (15:36:08Z) — the phase never ran at all.
    #
    # A share is the trap: it shrinks when some OTHER phase is slow, so a healthy artifact
    # call (~90s, run.py:462) gets killed because generation was slow — punishing the phase
    # that did nothing wrong, and cutting the LAST step, which is the one that converts a
    # paid-for PASS into something sellable. Everything upstream is stranded with it.
    #
    # A floor makes it what it should always have been: enough for a healthy chain, plus
    # slack, so it only bites a chain that is actually hung. Raising it cannot overrun the
    # tick — `_generate_pack_content` clamps this against the batch's own vet deadline
    # (run.py:559-561, `min(...)`), so the batch rail still has the last word.
    art_floor = _artifact_budget_floor_s(cfg)
    if art_budget is not None and art_floor > 0:
        art_budget = max(art_budget, art_floor)
    vet_frac = _vet_budget_frac(cfg)
    vet_budget = (vet_frac * _left) if vet_frac > 0 else None
    logger.critical(
        "Tick budgets: generation %s, artifacts/candidate %s, vetting batch %s "
        "(tick hard deadline %ds, %.0fs already spent on the drain, %.0fs left, batch=%s)",
        f"{budget:.0f}s" if budget else "unbounded",
        f"{art_budget:.0f}s" if art_budget else "unbounded",
        f"{vet_budget:.0f}s" if vet_budget else "unbounded",
        _TICK_HARD_DEADLINE_S, _spent, _left, batch_size,
        extra={"gen_budget_s": budget, "artifact_budget_s": art_budget,
               "vet_budget_s": vet_budget, "tick_deadline_s": _TICK_HARD_DEADLINE_S,
               "drain_spent_s": _spent, "tick_remaining_s": _left,
               "batch_size": batch_size})
    # `vet=False` returns after the survivors are queued, so `publish` could only ever be inert
    # in producer mode — it is passed as False rather than left True so the call states what the
    # tick actually does. `_cmd_generate` refuses the same combination outright (run.py:2858).
    dossiers = run_signal("", cfg=cfg, k=batch_size, publish=not _producer, lanes=lanes,
                          vet=not _producer,
                          gen_time_budget_s=budget,
                          artifact_time_budget_s=art_budget,
                          vet_time_budget_s=vet_budget)

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
    if _producer:
        # THE TICK MUST SAY WHICH KIND OF TICK IT WAS, or the alerter reads a healthy producer
        # as an outage: every row a producer writes is a DEFER, so `defers >= dossiers` — the
        # exact condition of the CRITICAL "Moat outage: all N candidates DEFERRED" page
        # (alerts.py:466). That would fire on EVERY tick, and an alert that always fires trains
        # the founder to ignore the channel that carries the real ones.
        #
        # `queued` rather than reusing `passes`: a producer's success metric is rows handed to
        # the queue, and it has no verdict to report by construction. Anything downstream that
        # wants "did the factory work" must read the number the factory actually produces.
        out["mode"] = "producer"
        out["queued"] = len(dossiers)
    if resumed is not None:
        out["resumed"] = resumed
    # Which market this batch was generated for. Recorded whenever rotation is ON, so the tick
    # log and the operator's phone can attribute a batch to a market — without it a rotating
    # daemon produces two populations that are indistinguishable after the fact.
    if rotated_market:
        out["market"] = rotated_market
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
_TICK_DEADLINE_DEFAULT_S = 10800  # 3h
_TICK_HARD_DEADLINE_S = int(os.environ.get("PROSPECTOR_TICK_DEADLINE_S",
                                           str(_TICK_DEADLINE_DEFAULT_S)))


def _refresh_tick_deadline(cfg) -> int:
    """Re-read the tick deadline from config, and return it.

    Seventeen places read `_TICK_HARD_DEADLINE_S` — budget fractions, the watchdog's stall
    threshold, the force-exit timer, three log lines. Threading a cfg argument through all of
    them to move one number would be a large diff for no extra correctness, so the module
    constant stays the single name every reader uses and this refreshes it from config once at
    the top of each tick. It was already process-global mutable state seeded from the
    environment; this only gives config a say in what it is seeded with.

    Precedence: `PROSPECTOR_TICK_DEADLINE_S` (one process, for a manual run) beats
    `schedule.tick_deadline_s` beats 10800s. The env keeps the top slot so an operator
    debugging a single tick by hand is not overridden by the file.
    """
    global _TICK_HARD_DEADLINE_S
    env = os.environ.get("PROSPECTOR_TICK_DEADLINE_S")
    if env:
        try:
            _TICK_HARD_DEADLINE_S = int(env)
            return _TICK_HARD_DEADLINE_S
        except ValueError:
            logger.warning("PROSPECTOR_TICK_DEADLINE_S=%r is not an integer; ignoring", env)
    raw = _sched(cfg, "tick_deadline_s", None)
    if raw in (None, "", 0):
        # Nothing specifies a deadline, so LEAVE the current value alone rather than stamping the
        # default over it. Two reasons, and the second is the load-bearing one:
        #   * the constant was already initialised from env-or-default at import, so "leave it"
        #     and "reset to default" are the same value on a real daemon;
        #   * 26 references across 8 test files set this constant directly to drive a sub-second
        #     deadline. Resetting it here would silently undo every one of them, and a deadline
        #     test that no longer tests a deadline still passes.
        return _TICK_HARD_DEADLINE_S
    try:
        val = int(raw)
    except (TypeError, ValueError):
        logger.warning("schedule.tick_deadline_s=%r is not an integer; using %ds",
                       raw, _TICK_DEADLINE_DEFAULT_S)
        _TICK_HARD_DEADLINE_S = _TICK_DEADLINE_DEFAULT_S
        return _TICK_HARD_DEADLINE_S
    # Floored at 60s. A deadline shorter than a single vet force-exits the daemon mid-work every
    # cycle, and launchd's KeepAlive turns that into a crash loop that looks like an outage.
    _TICK_HARD_DEADLINE_S = max(60, val)
    return _TICK_HARD_DEADLINE_S

# How often the daemon re-stamps its heartbeat while asleep (see the refresh loop in
# `run_daemon`). 60s against a 5s sleep slice, so it costs one small file write per twelve slices
# — roughly 120 writes across a 2h cadence, against a watchdog that samples every ~15 min. The
# point is the RATIO: any budget the watchdog sets is now compared against a write that should
# never be more than a minute old, instead of one that is legitimately two hours old.
_SLEEP_HEARTBEAT_REFRESH_S = 60

#: How often a long WORKING phase (`generating`, `draining`) re-stamps the heartbeat. Same 60s as
#: the sleep refresh, for the same reason and against the same defect — the sleep loop was fixed in
#: isolation, and the two phases where the daemon spends its actual hours were left stamped once.
_WORK_HEARTBEAT_REFRESH_S = 60


@contextlib.contextmanager
def _beating(cfg, phase: str, **extra):
    """Re-stamp `phase`'s heartbeat every `_WORK_HEARTBEAT_REFRESH_S` for the life of the block.

    WHAT WAS BROKEN. `generating` and `draining` were each stamped exactly ONCE, on the way in, and
    a batch legitimately runs 15-30+ min (the drain, ~5.5 min/candidate x 15 rows, ~82 min). So the
    age of that heartbeat answered "how far has the wall clock moved since one write?" — not "is the
    loop still turning?". Those are different questions, and only the second one is liveness. This
    is the identical defect already fixed for `sleeping` (see the refresh loop in `run_daemon` and
    the 47 SIGKILLs of demonstrably-live daemons it was written for); the fix simply never reached
    the two phases where the daemon spends most of its wall time.

    WHAT THIS DELIBERATELY DOES NOT DO: move any budget. `_watchdog_liveness` still judges
    `generating`/`draining` against `_TICK_HARD_DEADLINE_S / 60 + 10`, and that file's own comment
    fences the narrowing off — a real 8.5h wedge on 2026-07-01 is why the kill exists, and
    tightening on the (still unproven) wall-clock-artefact hypothesis would trade 47 false criticals
    for a missed real stall. What changes here is what the EXISTING budget measures: against a
    once-stamped beat, a 190-minute age could mean a healthy long batch; against a beat refreshed
    every 60s it can only mean the loop stopped writing. Same threshold, a signal instead of noise.

    Known gap, stated rather than left implied: `beat_every_s` is written by this helper and by the
    sleep loop and is read by NOTHING (`rg beat_every_s prospector/` -> two write sites, no reader).
    Making it load-bearing means deriving a budget from it, which IS the narrowing the paragraph
    above fences off, so it stays a marker until that hypothesis is settled.

    The thread is a daemon thread and is joined on exit, so a caller that returns or raises always
    stops the beating before the tick writes its terminal `idle` beat — a refresher outliving its
    phase would overwrite that and report work still in flight.
    """
    _write_heartbeat(cfg, phase=phase, beat_every_s=_WORK_HEARTBEAT_REFRESH_S, **extra)
    stop = threading.Event()

    def _refresh() -> None:
        while not stop.wait(_WORK_HEARTBEAT_REFRESH_S):
            # `_write_heartbeat` already swallows OSError; anything else here must not take the
            # tick down, because a failure to REPORT work is not a failure to DO it.
            try:
                _write_heartbeat(cfg, phase=phase, beat_every_s=_WORK_HEARTBEAT_REFRESH_S, **extra)
            except Exception as exc:  # noqa: BLE001 — liveness reporting is never fatal
                logger.error("Heartbeat refresh failed in phase %s: %s", phase, exc)

    beater = threading.Thread(target=_refresh, name=f"heartbeat-{phase}", daemon=True)
    beater.start()
    try:
        yield
    finally:
        stop.set()
        beater.join(timeout=_WORK_HEARTBEAT_REFRESH_S)


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


def _force_exit_hung_tick(batch_size: int, cfg=None, tick: dict | None = None,
                          *, phase: str = "generation") -> None:
    # `phase` because the drain-only branch now arms this timer too, and a breach that says
    # "during generation" on a tick whose batch_size was 0 sends the next reader looking at the
    # wrong half of the daemon.
    logger.critical(
        "TICK HARD DEADLINE (%ds) exceeded during %s (batch=%s) — force-exiting so "
        "launchd KeepAlive relaunches a clean daemon.", _TICK_HARD_DEADLINE_S, phase, batch_size)
    # Record the tick + fire the CRITICAL alert BEFORE exiting — a silent os._exit leaves no
    # tick row and no alert, so a repeating deadline breach looks like the daemon never ran
    # (proven live 2026-07-02: 4h of relaunch loops with zero tick rows). The main thread is
    # hung, so writing from this timer thread is safe; any bookkeeping failure must still exit.
    if cfg is not None and tick is not None:
        try:
            # ELAPSED + COUNTS, not just the constant deadline (founder, 2026-08-15: "the
            # one event we most need evidence about leaves the least evidence"). Before
            # this, the row recorded only `_TICK_HARD_DEADLINE_S` — a FIXED number, true
            # of every breach that ever has or ever will happen — and the configured
            # `batch_size`, neither of which says how FAR the hung phase got before it
            # hung. `elapsed_s` is real wall-clock since THIS tick's own `tick["ts"]`
            # (stamped at the top of `run_tick`), not the constant. `breach_heartbeat` is
            # a snapshot of the liveness file `_beating` has been re-stamping every
            # `_WORK_HEARTBEAT_REFRESH_S` (60s) for the life of the phase — the one
            # channel a periodically-live loop keeps fresh even though its OWN return
            # value is what never came back, so it is the freshest available answer to
            # "how far did it get" without waiting on the very call that is hung. A torn
            # or missing heartbeat read must not block the force-exit itself (same
            # reasoning as the outer `except Exception` below) — it degrades to `{}`.
            elapsed_s = None
            try:
                started = datetime.fromisoformat(tick["ts"])
                elapsed_s = (datetime.now(timezone.utc) - started).total_seconds()
            except (KeyError, ValueError, TypeError):
                pass
            breach_heartbeat: dict = {}
            try:
                hb_path = _heartbeat_path(cfg)
                if hb_path.exists():
                    breach_heartbeat = json.loads(hb_path.read_text())
            except (OSError, json.JSONDecodeError):
                pass
            tick["error"] = (f"tick_hard_deadline: exceeded {_TICK_HARD_DEADLINE_S}s during "
                             f"{phase} (batch={batch_size}); force-exited for relaunch")
            tick["breach_phase"] = phase
            tick["elapsed_s"] = elapsed_s
            tick["breach_heartbeat"] = breach_heartbeat
            _append_tick(cfg, tick)
            _emit_tick_alerts(cfg, tick)
            _emit_tick_digest(cfg, tick)
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
    # A usage-wall skip is unproductive for exactly the same reason, and it is the case where the
    # escalating retry pays best: the marker carries a real reset time, so polling a file every
    # few minutes picks capacity up the moment it returns instead of up to 2h later.
    if tick.get("usage_wall"):
        return True
    # A queue-full skip is the OPPOSITE: the operator asked for a queue of N and the queue holds
    # N. Nothing is wrong, so this must not inherit the outage backoff — which would also read
    # backwards, since a full queue is the moment to wait longer, not to retry in five minutes.
    if tick.get("queue_full"):
        return False
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
    # Before anything reads it: every budget below is a fraction of this number.
    _refresh_tick_deadline(cfg)
    guard = guard_from_config(cfg)
    decision = guard.evaluate()
    batch_size = _batch_size(cfg, candidates)

    # OPTIONAL queue-following, off unless `schedule.queue_target_depth` is set. An explicit
    # `--candidates` is an operator saying how many they want, so it is never second-guessed.
    queue_target = _queue_target_depth(cfg) if candidates is None else 0
    queue_depth = None
    if queue_target:
        queue_depth = _backlog_size(cfg)
        if queue_depth is None:
            # Uncountable queue. Generate the plain batch rather than guessing — the same
            # direction `_backlog_size` fails in for the backlog brake, for the same reason: a
            # counting failure must never read as "the queue is empty, mint everything".
            logger.warning("queue_target_depth is set but the queue could not be counted; "
                           "generating the full batch of %d", batch_size)
        else:
            batch_size = max(0, min(batch_size, queue_target - queue_depth))

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
        "tick_deadline_s": _TICK_HARD_DEADLINE_S,
        "result": None,
        "error": None,
    }
    if queue_target:
        tick["queue_target_depth"] = queue_target
        tick["queue_depth"] = queue_depth

    if not decision.can_run:
        logger.info("Tick skipped: %s", decision.reason)
        _append_tick(cfg, tick)
        return tick

    if queue_target and batch_size == 0:
        # The queue already holds what the operator asked it to hold. Not an outage and not a
        # failure, so `_tick_unproductive` must not see it as one and escalate the retry
        # backoff — `queue_full` is its own reason, checked there.
        tick["reason"] = (f"queue_full: {queue_depth} row(s) waiting, target {queue_target}")
        tick["queue_full"] = True
        logger.info("Tick generated nothing: %s", tick["reason"])
        _append_tick(cfg, tick)
        return tick

    if dry_run:
        logger.info("Dry run: guard passed (%s); would generate %d candidates", decision.reason, batch_size)
        _append_tick(cfg, tick)
        return tick

    # USAGE-WALL PREFLIGHT. Checked BEFORE the moat preflight because a live wall is the CAUSE
    # and a dead mark is only its symptom: this reports the reset time, where "every trusted
    # brain is dead" hands the operator a puzzle instead of an answer. Otto and this daemon draw
    # on ONE subscription, and whichever meets the wall records when it lifts; measured
    # 2026-08-07 23:44, Otto recorded a wall until 23:59:05 that this daemon had no way to read.
    #
    # Like the moat preflight it skips the WHOLE tick, drain included — the walled resource is
    # the one subscription CLI heading both the moat and the non-critical chain, so neither half
    # of a tick can make progress. It costs one file read and no CLI call, and `_tick_unproductive`
    # counts it so the escalating 5m/10m/20m retry applies rather than the 2h cadence.
    walled = usage_wall.reason()
    if walled:
        tick["usage_wall"] = True
        tick["reason"] = walled
        tick["batch_size"] = None
        logger.critical("Tick skipped: %s", walled)  # CRITICAL for the same reason as below.
        print(f"⏸ tick skipped — {walled}", file=sys.stderr, flush=True)
        _append_tick(cfg, tick)
        _emit_tick_alerts(cfg, tick)
        _emit_tick_digest(cfg, tick)
        return tick

    # HEARTBEAT. Founder directive 2026-08-21: "need heatbeat", "for all nodels in platforn".
    #
    # It runs HERE, immediately before the moat preflight, for two reasons. The preflight reads
    # dead marks, so anything the heartbeat learns is one line older than the decision that uses
    # it. And a tick that is about to be skipped still leaves a fresh answer behind: the hours
    # when nothing runs are exactly the hours somebody opens the console asking which brain is
    # alive, and before this the honest answer was "nothing has asked since the last real call".
    #
    # It is BELOW the PAUSE and spend guards on purpose. PAUSE halts the entire tick and a rail
    # with exceptions is not a rail, so a paused engine takes no rounds — the console's
    # `providers.test` action is the manual path while paused, and it says so on the page.
    #
    # It never raises into the tick. A monitor that can stop the thing it monitors is worse than
    # no monitor, and it marks nothing dead (see prospector/ops/heartbeat.py), so it cannot bench
    # a brain or eat the half-open recovery probe the next real call is entitled to.
    try:
        from ..ops.heartbeat import run_heartbeat

        beat = run_heartbeat(cfg)
        if beat["probed"]:
            tick["heartbeat"] = {"probed": beat["probed"], "alive": beat["alive"],
                                 "down": beat["down"]}
            logger.info("Heartbeat: %d alive, %d down", len(beat["alive"]), len(beat["down"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Heartbeat failed, continuing: %s", exc)

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
        _emit_tick_digest(cfg, tick)
        return tick

    # GENERATION BRAKE — skip generation, but keep draining.
    #
    # Checked after the moat preflight, because a drain-only tick needs a trusted brain just as
    # much as a generating one does; running it into a blind moat is the exact waste the
    # preflight above (and `run.py::_cmd_resume`) exists to stop.
    #
    # This is the one skip in the tick that still does work. Every other early return — guard,
    # dry-run, moat-blind — is a genuine no-op, and the drain living inside `_default_generate`
    # meant they all silently disabled recovery too. The whole point of the brake is that the
    # backlog goes DOWN while it is engaged; a brake that also stopped the drain would freeze
    # the number it is waiting on and never release.
    suppressed = _generation_suppressed(cfg, decision)
    if suppressed:
        tick["generation_suppressed"] = suppressed
        tick["batch_size"] = 0
        tick["reason"] = f"{decision.reason}; {suppressed}"
        # CRITICAL for the same reason as the moat-blind skip: logging below CRITICAL never
        # reaches launchd.err.log (verified 2026-08-05), and a daemon that has quietly stopped
        # generating is precisely the invisible degradation this change is about.
        logger.critical("Generation suppressed: %s", suppressed)
        print(f"⏸ generation suppressed — {suppressed}", file=sys.stderr, flush=True)
        # The SAME hard wall-clock guard the generation branch gets below. Without it this was
        # the one path in the tick with neither backstop, and it is now the daemon's entire
        # workload while the brake is engaged:
        #   * `_drain_pass` swallows every exception by design (a drain failure must not cost
        #     the tick), so a wedged re-vet never raises and the branch never returns;
        #   * the deadline Timer was started AFTER this branch returns, so it never covered it;
        #   * `phase="draining"` matched no branch in `_liveness`, which fell through to
        #     "alive" — so the watchdog reported a hung drain healthy, indefinitely.
        # That is the 2026-07-01 failure mode exactly (a trickled LLM response body defeating
        # per-recv socket timeouts, 34+ min hung, watched dead for 8.5h), re-opened on a new path.
        # `_beating` replaces the single `phase="draining"` stamp this branch wrote on the way in.
        # A drain-only pass is long BY DESIGN — 15 rows at the measured ~5.5 min/candidate is
        # ~82 min — so a once-stamped beat spent most of a HEALTHY pass looking stale, which is
        # precisely the reading that produced 47 SIGKILLs of live daemons in the sleeping phase.
        with _beating(cfg, "draining"):
            deadline = threading.Timer(_TICK_HARD_DEADLINE_S, _force_exit_hung_tick,
                                       args=(0, cfg, tick), kwargs={"phase": "the drain"})
            deadline.daemon = True
            deadline.start()
            try:
                # NOT IN PRODUCER MODE. Everything above this line argues that a brake which
                # also stopped the drain would freeze the number it is waiting on — and that is
                # exactly right for the classic single-process tick, where this branch is the
                # daemon's whole workload. In a SPLIT estate the argument inverts: the consumer
                # is already draining, continuously and with no deadline, so the number goes
                # down whether or not the producer helps. What draining here would actually buy
                # is the one thing the split exists to remove — the producer back on the moat's
                # clock, for up to the full 3h deadline, in precisely the situation (a queue
                # deeper than the cap) where the moat is already the bottleneck. A second
                # drainer does not make a saturated brain faster.
                #
                # So the producer's brake is a plain stop: no generation, no vetting, and the
                # unlist drain below still runs. It self-releases under the cap on the
                # consumer's progress rather than its own.
                resumed = None if producer_mode(cfg) else _drain_pass(
                    cfg, _drain_only_resume_per_tick(cfg))
                # Inside the deadline guard, for the reason spelled out above it: this branch is
                # the daemon's entire workload while the brake is engaged, and `_decay_pass`
                # swallows every exception by design, so an uncovered sweep could wedge the tick
                # invisibly.
                decayed = _decay_pass(cfg, _decay_sweep_budget(cfg))
                # Recovery runs on the braked tick too, and deliberately: a brake stops
                # MAKING passes, it does not make the ones already paid for sellable.
                recovered = _recover_pass(cfg)
            finally:
                deadline.cancel()
        tick["result"] = {"dossiers": 0, "resumed": resumed, "decayed": decayed,
                          "recovered": recovered}
        _append_tick(cfg, tick)
        _emit_tick_alerts(cfg, tick)
        _emit_tick_digest(cfg, tick)
        _write_heartbeat(cfg, phase="idle", last_result=tick["result"], last_error=None)
        return tick

    gen = generate_fn or _default_generate
    halt = False
    # `_beating` replaces the single `phase="generating"` stamp this branch wrote on the way in.
    # A grounded batch runs 15-30+ min, so the old beat was a full batch stale by the time the
    # batch finished normally, and its age measured the wall clock rather than the loop.
    #
    # Hard wall-clock guard, unchanged and INSIDE the beating: if generation hangs past
    # _TICK_HARD_DEADLINE_S the timer force-exits the process (launchd relaunches it). Cancelled
    # the instant generation returns. The refresher stops with the block, so the terminal `idle`
    # beat written after this is never overwritten by a straggler.
    with _beating(cfg, "generating", batch_size=batch_size):
        deadline = threading.Timer(_TICK_HARD_DEADLINE_S, _force_exit_hung_tick,
                                   args=(batch_size, cfg, tick))
        deadline.daemon = True
        deadline.start()
        try:
            logger.info("Tick: generating %d candidates (%s)", batch_size, decision.reason)
            tick["result"] = gen(cfg, batch_size)
            # After generation, inside the same deadline guard. The SLA sweep is re-vet work of the
            # same class as the drain, and it must run on a normal tick too — a decay rail that
            # only fired while the generation brake was engaged would be as good as unwired for any
            # week the brake never engages, which is the failure this whole change exists to fix.
            # `_decay_sweep_budget` returns 0 in producer mode: the SWEEP is moat work that
            # belongs to the consumer, while the unlist drain inside `_decay_pass` still runs.
            decayed = _decay_pass(cfg, _decay_sweep_budget(cfg))
            if isinstance(tick.get("result"), dict) and decayed is not None:
                tick["result"]["decayed"] = decayed
            recovered = _recover_pass(cfg)
            if isinstance(tick.get("result"), dict) and recovered is not None:
                tick["result"]["recovered"] = recovered
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
    _emit_tick_digest(cfg, tick)
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
    # R3 tolerant reader: a torn trailing line (an append caught in flight by this very read,
    # or truncated by a crash) is skipped, and every intact row before it is still returned.
    # The old readlines() handed the fragment to json.loads, which is only accidentally safe —
    # a truncated row can be valid JSON, e.g. `{"allowed": true}` is a prefix of a real tick.
    rows = read_jsonl(_ticks_path(cfg), tail=_TICK_SCAN_LINES, warn=False)
    real = []
    for t in rows:
        if not isinstance(t, dict):
            continue
        if not t.get("allowed") or t.get("dry_run"):
            continue
        # A cycle the engine deliberately SUPPRESSED produced nothing on purpose, so it is a
        # skipped cycle, not a barren one — exactly like a dry run. Counting it barren is how
        # a working engine pages the founder: on 2026-08-16 eight consecutive suppressed
        # cycles (07:30Z-09:36Z, retrieval probe timing out) fired "Generation DEAD: 8 barren
        # ticks" at CRITICAL, naming three causes that were all healthy, while the engine was
        # doing the right thing. A separate alert must own "suppressed too long"; this counter
        # answers "did generation run and stock nothing", and a suppressed cycle never ran.
        if t.get("generation_suppressed"):
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
    from prospector.scheduler.alerts import (
        TICK_ALERT_KEYS,
        alerts_for_tick,
        emit_alert,
        reconcile_alert_txt,
        resolve_alert,
    )

    # FIRST, and deliberately above every early return below: a PASS the buyer cannot reach is
    # the engine's most expensive silent state — the work is done and paid for, and the shelf is
    # empty anyway. It is also orthogonal to whether THIS tick went well, so it must not be
    # gated on the recovery path's eligibility test. Its own guards (dry run / not allowed) live
    # inside the function.
    _emit_stranded_pass_alert(cfg, tick)

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


#: Budget for the shelf-coverage subprocess. It reads the live catalogue over the network and the
#: local dossier index; the session probe gives it 12s and it fits. 30s here because a tick is
#: 2h and being slow is not a reason to stop checking whether the shop has stock.
_COVERAGE_TIMEOUT_S = 30


def _run_coverage_check() -> "subprocess.CompletedProcess | None":
    """Run `tools/verify_pass_shelf_coverage.py`, or return None if it must not run.

    UNDER PYTEST THIS ALWAYS RETURNS None, for the same reason `alerts._load_hermes_sender`
    refuses to load: the script reads the LIVE catalogue over the network and the production
    dossier index. Wiring it into `_emit_tick_alerts` immediately dragged three unrelated
    suites into doing exactly that — test_alert_resolution.py and test_tick_hard_deadline.py
    went red on 2026-08-14 with a REAL finding about three real production packs. A test that
    reaches production is a defect even when it passes; this repo has the scars
    (tests-polluted-the-production-audit-log, test-suite-called-stripe-for-real).

    Tests that need the branches monkeypatch THIS function, which is why it is a seam and not
    an inline subprocess call.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    script = Path(__file__).resolve().parents[2] / "tools" / "verify_pass_shelf_coverage.py"
    if not script.exists():
        return None
    try:
        return subprocess.run(  # noqa: S603 — our own script, fixed argv, no shell
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=_COVERAGE_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        # Narrowed (TimeoutExpired is a SubprocessError) and raised to ERROR. The alert path reads
        # None as "did not look", which is also what the pytest fence and a missing script return —
        # indistinguishable to the caller by design, since none of the three may alert. But a check
        # that stopped running has to be findable in the log: this monitor exists precisely because
        # three PASSes sat unbuyable while nothing said so, and a monitor that silently stops is
        # that same defect one level up.
        logger.error("Shelf-coverage check did not run (%s) — stranded PASSes are UNMONITORED "
                     "this tick", exc)
        return None


def _emit_stranded_pass_alert(cfg, tick: dict) -> None:
    """Alert when the engine has produced a PASS that no buyer can reach.

    WHY THIS IS SEPARATE FROM `alerts_for_tick`. That function is pure over the tick dict, and
    this condition is not in the tick: a pack strands at PUBLISH time, from a lint error or a
    failed upload, and the tick that made it reports a perfectly healthy `passes: 1`. So the
    engine's own success metric cannot see it.

    WHY IT EXISTS AT ALL (2026-08-14). Three PASSes sat unbuyable — `25363e54b649587a` blocked on
    a title initialism, plus `3d20db251950c20a` and `5b8720247589ae96` — and NOTHING alerted. The
    only reader of `tools/verify_pass_shelf_coverage.py` was the session-start probe, i.e. it
    reported to whoever happened to open a session, and the founder found out by asking. A check
    that runs only when a human is already looking is not monitoring.

    Exit codes are the tool's contract: 0 clean, 1 stranded, 2 shelf unreadable. A 2 must NOT
    alert — "could not look" is not "found something", and turning it red trains the reader to
    ignore the line. It resolves itself: a later clean run clears the key.
    """
    from prospector.scheduler.alerts import emit_alert, resolve_alert

    if not tick.get("allowed") or tick.get("dry_run"):
        return
    proc = _run_coverage_check()
    if proc is None:
        return

    if proc.returncode == 2:
        logger.info("Shelf-coverage UNKNOWN (catalogue unreadable); not alerting")
        return
    if proc.returncode == 0:
        try:
            resolve_alert(cfg, key="stranded_passes",
                          reason=f"every PASS is on the shelf at {tick.get('ts')}")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to resolve stranded_passes")
        return

    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
    count = next((ln.split(":", 1)[1].strip() for ln in proc.stdout.splitlines()
                  if ln.startswith("stranded passes")), str(len(lines)))
    try:
        emit_alert(
            cfg,
            severity="critical",
            key="stranded_passes",
            title=f"{count} PASS(es) stranded off the shelf",
            message=("The engine produced packs no one can buy. "
                     + " | ".join(lines[:3])
                     + (f" (+{len(lines) - 3} more)" if len(lines) > 3 else "")
                     + " — fix: .venv/bin/python tools/verify_pass_shelf_coverage.py"),
            throttle_s=21600,   # 6h: it is a standing condition, not an event
            stranded=len(lines),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to emit stranded_passes alert")


def _emit_tick_digest(cfg, tick: dict) -> None:
    """Push a one-line status digest to Telegram after each tick (debounced 2h).

    Mirrors `_telegram_push` discipline: best-effort, never raises, honored under
    PYTEST_CURRENT_TEST. The debounce lives in send_operator_alert (its debounce_s window),
    keyed by `prospector:tick_digest` so a fresh tick ALERT path still pages immediately.

    The digest is the `🎛 Now` data: heartbeat + last tick + spend + providers + alerts +
    backlog, formatted into one Telegram-ready line by `prospector.scheduler.status`. Wired
    at the same six sites as `_emit_tick_alerts` so the founder sees the same digest on
    every branch — a skipped, errored, moat-blind or healthy tick all push one.
    """
    # Both handlers below split the EXPECTED condition from OUR OWN BUGS and log the second at
    # ERROR with a traceback. The daemon still survives either — a digest may never break a tick —
    # but a `TypeError` from a refactor no longer reads in the log exactly like an absent module,
    # which is how the founder's only continuous visibility surface could go dark unnoticed.
    try:
        from prospector.scheduler.status import format_status_snapshot, status_snapshot
    except ImportError as exc:
        logger.warning("status digest unavailable (modules not importable): %s", exc)
        return
    except Exception:  # noqa: BLE001 — a broken status module must never break the daemon
        # swallow-ok: the SECOND half of a deliberate split (ImportError above), and it already
        # logs at ERROR with a traceback — the fix ladder's step 3, done. The auditor counts two
        # returns in two handlers and cannot see that one of them is the logged branch.
        logger.exception("status module failed to IMPORT (this is a bug, not a missing estate); "
                         "tick digest skipped")
        return
    try:
        snap = status_snapshot(cfg)
        text = format_status_snapshot(snap)
    except Exception:  # noqa: BLE001 — status_snapshot documents "never raises"; if it did, that
        # is our bug and it needs a traceback, not a one-line warning that reads like a missing file.
        logger.exception("status_snapshot() raised despite its never-raises contract; "
                         "tick digest skipped")
        return
    send = _load_hermes_sender()
    if send is None:
        # WARNING, not INFO. The old line named estate_alert.py, which reads as "this machine
        # simply has no Hermes" — and on the Fly container that was true and harmless-looking
        # while every digest was being dropped (issue #355). There is an in-repo sender now, so
        # None here means a real defect.
        logger.warning("Tick digest sink unavailable (no sender could be loaded); "
                       "digest stayed local")
        return
    try:
        sent = send(text, debounce_key="prospector:tick_digest", debounce_s=7200.0,
                    dry_run="PYTEST_CURRENT_TEST" in os.environ)
        logger.info("Tick digest sent=%s (len=%d)", sent, len(text))
    except Exception as exc:  # noqa: BLE001 — documented never-raises, but trust nothing here
        logger.warning("Tick digest push failed: %s", exc)


class _StopFlag:
    """SIGTERM/SIGINT-aware stop flag so launchd can stop the daemon cleanly mid-sleep."""

    def __init__(self) -> None:
        self.stop = False

    def request(self, *_a) -> None:
        self.stop = True


#: Wall-clock bound on the startup grounding probe. One search against a live HTTP provider; 120s
#: is far past any healthy answer and far short of the watchdog's own cadence, so a wedge here
#: self-heals long before anything else has to notice it.
_STARTUP_PROBE_TIMEOUT_S = 120


def _startup_grounding_check(cfg) -> None:
    """Refuse to start if the grounding layer is dead — one dummy search first, time-bounded.

    THE HOLE THIS CLOSES: this ran before the first tick, so before any heartbeat existed, and it
    made a blocking network call with NO timeout of its own. A provider that accepts the TCP
    connection and never answers wedges the daemon here permanently, and every recovery mechanism
    reads past it:

      * launchd `KeepAlive` restarts on process EXIT; a wedged-but-alive process never exits.
      * `_liveness` reads the heartbeat, which at this point still holds the PREVIOUS run's
        `sleeping`/`idle` beat, so the watchdog's kill lands on the OLD pid.
      * `_kill_stale_daemon` then finds that pid gone (launchd already replaced it), logs
        "already exited; launchd will relaunch" and returns satisfied — while the process it
        should have killed goes on hanging. launchd HAS relaunched; the relaunch is the wedge.

    Two independent fixes, deliberately both:

      1. The probe runs on a daemon thread with a hard `join` bound, so a hang becomes an EXIT
         and launchd's KeepAlive heals it. The thread is a daemon thread precisely so a socket
         read stuck in the kernel cannot hold the interpreter open on the way out.
      2. A `starting` heartbeat is written BEFORE the probe, so the file names the pid that is
         actually at risk and `_liveness` has a phase to judge (see its `starting` branch). This
         is the backstop for a wedge the bound cannot cover, and it is what turns "invisible" into
         "one stale-heartbeat line naming the wedged pid".

    Coverage boundary, stated rather than implied: the heartbeat starts here, so a hang in
    `_load_env_file`, `load_config` or `_route_ledger` — all local filesystem work, none of it a
    network call — is still outside it.
    """
    _write_heartbeat(cfg, phase="starting", probe_timeout_s=_STARTUP_PROBE_TIMEOUT_S)
    # Shares `_probe_grounding_once` with the per-tick generation gate. The two ask the identical
    # question of the identical stack and differ only in their bound and in what they do with a
    # "no": startup EXITS (so launchd relaunches), a tick DRAINS (so the backlog still falls).
    kind, exc = _probe_grounding_once(cfg, _STARTUP_PROBE_TIMEOUT_S)
    if kind == "timeout":
        raise RuntimeError(
            f"REFUSING TO START: the grounding probe did not answer within "
            f"{_STARTUP_PROBE_TIMEOUT_S}s — the provider took the connection and never replied. "
            f"Exiting so launchd KeepAlive relaunches: a relaunch costs one probe, while hanging "
            f"here costs every tick until a human notices."
        )
    if kind == "error":
        raise RuntimeError(
            f"REFUSING TO START: grounding provider is dead on arrival. "
            f"Fix search API keys/credits before starting Prospector. "
            f"Error: {exc}"
        ) from exc
    logger.info("Grounding layer healthy — daemon starting")


_DAEMON_MODULE = "prospector.scheduler.run_scheduled"
_CODE_RELOAD_DEFAULT = True
#: The fingerprint this process is actually RUNNING. Set once at daemon start and stamped on every
#: heartbeat, so a monitor can compare "what is loaded" against "what is on disk" by equality rather
#: than by guessing from timestamps.
_RUNNING_CODE_FP: str | None = None


def code_fingerprint(config_path=None) -> str | None:
    """SHA-256 over the BYTES of every module in the `prospector` package, plus config.yaml.

    This is the identity of the code a process LOADED. The daemon imports the engine in-process
    (`from prospector.run import run_signal`, below) and `load_config` runs once in `main`, so
    every module and the config are frozen at start: editing a file on disk changes nothing about
    a daemon that is already up. On 2026-08-08 that meant a daemon started 11:50 was still serving
    the pre-fix `bridge.py` — the money rail — hours after the fix was written and committed.

    Bytes, not mtimes, and deliberately so. An mtime moves for reasons that are not a code change:
    a `touch`, a branch switch that restores identical content, an NTP step, a worktree copy. Each
    would force a re-exec, and a re-exec that lands mid-cadence costs a real batch. Content is the
    property we actually care about, and hashing ~1MB once per 2h tick is free next to one LLM call.

    Returns None if the tree cannot be read; callers treat that as "cannot tell", never as "changed",
    because the failure mode of guessing wrong here is killing a running batch.
    """
    package_dir = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    try:
        paths = sorted(p for p in package_dir.rglob("*.py") if "__pycache__" not in p.parts)
        if config_path:
            resolved = Path(config_path).resolve()
            if resolved.is_file():
                paths.append(resolved)   # appended last: order stays deterministic
        for path in paths:
            digest.update(str(path).encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError as exc:
        logger.warning("Code fingerprint failed (%s) — treating code as unchanged this cycle", exc)
        return None
    return digest.hexdigest()


def _reload_on_code_change(cfg) -> bool:
    """`schedule.reload_on_code_change` — default ON. A rail that ships off is an inert rail."""
    return bool(_sched(cfg, "reload_on_code_change", _CODE_RELOAD_DEFAULT))


def _redeploy(exec_fn=os.execv) -> None:
    """Replace this process with a fresh one running the code now on disk, preserving the pid.

    `os.execv`, not `sys.exit`: exec keeps the pid, so launchd sees no exit at all and neither
    `KeepAlive` nor `ThrottleInterval` is involved. That makes the reload work identically when the
    daemon is run by hand outside launchd, and it cannot interact with the watchdog's kill path.
    The argv is rebuilt in the `-m` form the plist uses, so the relaunch is the same command line.
    """
    cmd = [sys.executable, "-m", _DAEMON_MODULE, *sys.argv[1:]]
    logger.warning("Code changed on disk — re-executing at the tick boundary to deploy it: %s",
                   " ".join(cmd))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (ValueError, OSError):  # a closed stream must not block the redeploy
            pass
    exec_fn(sys.executable, cmd)


def run_daemon(cfg, *, interval: int, candidates: int | None = None, generate_fn=None,
               max_cycles: int | None = None, sleep_fn=time.sleep, config_path=None,
               exec_fn=os.execv) -> int:
    """Loop forever (or `max_cycles` times in tests): tick, then sleep `interval` seconds.

    The guard is re-evaluated every cycle, so PAUSE and the daily cap take effect without a
    restart. Code is NOT: see `code_fingerprint`. So the loop also re-execs itself when the code on
    disk stops matching the code it started with. Returns the number of cycles executed.
    """
    flag = _StopFlag()
    signal.signal(signal.SIGTERM, flag.request)
    signal.signal(signal.SIGINT, flag.request)

    # `interval` as passed is the FALLBACK — argv, i.e. the plist. `schedule.interval_s` wins,
    # and is re-read at the bottom of every cycle so the operator can change the cadence from
    # the console without touching a plist or restarting the job.
    argv_interval = interval
    interval = _interval_s(cfg, argv_interval)
    logger.info("Daemon starting: interval=%ds (argv %ds), store=%s",
                interval, argv_interval, _store_dir(cfg))
    global _RUNNING_CODE_FP
    startup_fp = code_fingerprint(config_path)
    _RUNNING_CODE_FP = startup_fp
    logger.info("Running code fingerprint: %s", (startup_fp or "unknown")[:12])
    cycles = 0
    consecutive_unproductive = 0
    while not flag.stop:
        # The ONE safe point to swap code: a tick has finished and the next has not begun, so no
        # batch, no drain and no publish is in flight. Compared against the fingerprint taken at
        # STARTUP (not the previous cycle's), which is what makes this self-limiting: the process
        # that replaces us re-reads disk on the way in, so a stream of edits costs at most one
        # re-exec per cadence and can never become an exec loop.
        if startup_fp and _reload_on_code_change(cfg):
            current_fp = code_fingerprint(config_path)
            if current_fp and current_fp != startup_fp:
                _write_heartbeat(cfg, phase="redeploying", cycles=cycles)
                _redeploy(exec_fn)
                return cycles  # unreachable after a real execv; reached only with a test double
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
        # Re-read every cycle, so `schedule.interval_s` is the live control point rather than
        # the `--interval` argv frozen into a launchd plist at install time.
        interval = _interval_s(cfg, argv_interval)
        sleep_target = interval
        if tick is not None and tick.get("generation_suppressed"):
            # A drain-only tick gets its OWN cadence, not the 2h generation interval and not the
            # outage backoff. Both of the existing paths are wrong for it:
            #   * the full interval would clear 343 rows at 15/tick in ~46 hours of wall clock;
            #   * `_tick_unproductive` sees `dossiers == 0` and would escalate 5m/10m/20m/40m/80m
            #     to the 2h cap, i.e. treat a working drain as a deepening outage and slow it
            #     down exactly as it made progress.
            # The brake is a temporary state the system is trying to leave, so the cadence while
            # it is engaged should be the one that leaves it soonest. Reset the outage counter
            # too: nothing failed here.
            consecutive_unproductive = 0
            sleep_target = _drain_only_interval_s(cfg, interval)
            logger.info("Drain-only tick — next in %ds (not the %ds generation cadence)",
                        sleep_target, interval)
        elif tick is not None and _tick_unproductive(tick):
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
    from prospector.log_shipper import attach as attach_central_log
    from prospector.telemetry import route_logs_to_file

    route_logs_to_file(str(_store_dir(cfg) / "prospector.jsonl"))
    # And to the central ingest. No-op without STORE_INTERNAL_API_KEY; cannot raise; does
    # no I/O on the tick's own thread (docs/LOGGING_AND_RETENTION.md Part 8 step 7).
    attach_central_log("scheduler")


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
        lines = [line.rstrip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError as exc:
        # The failure goes into the readout, not into a silent []. `[]` is this function's word for
        # "the daemon logged no errors", which is the single most reassuring thing --status can
        # say; printing it because we could not OPEN the log is the whole blind spot this function
        # was written to close ("a dead daemon looked alive for 15h").
        logger.error("Cannot read %s for the status readout: %s", path, exc)
        return [f"(stderr log at {path} UNREADABLE: {exc} — 'no errors' below is not evidence)"]
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
    # R3 tolerant reader: skips a torn trailing line (this runs while the daemon is appending)
    # and streams rather than loading an ever-growing file into memory.
    for t in iter_jsonl(path, warn=False):
        if not isinstance(t, dict):
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
        stale = (phase in ("generating", "draining") and age_min > _TICK_HARD_DEADLINE_S / 60 + 10) or \
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
    # `draining` shares `generating`'s deadline-derived budget, and deliberately NOT the 45-min
    # one used for evaluating/idle below: a drain-only pass is long BY DESIGN — 15 rows at the
    # measured ~5.5 min/candidate is ~82 min — so a 45-min budget would SIGKILL a perfectly
    # healthy drain on every brake tick, which is the failure this file already carries 47
    # instances of. Until now the phase matched no branch at all and fell through to the
    # "alive" return, so a wedged drain was reported healthy forever; the drain-only branch is
    # the daemon's whole workload while the backlog brake is engaged.
    if phase == "draining" and age_min > stall_min:
        return False, (f"stuck in 'draining', heartbeat {ages} "
                       f"(deadline {_TICK_HARD_DEADLINE_S // 60} min should have force-exited it)")
    if phase == "sleeping":
        budget = beat.get("interval_s", 7200) / 60 + 35  # interval + grace
        if age_min > budget:
            return False, (f"'sleeping' heartbeat {ages} (> interval+grace {budget:.0f}); "
                           f"loop likely dead")
    # `starting` — the pre-first-tick window, and the ONLY phase whose work has no in-process
    # deadline Timer behind it (the Timers live inside `run_tick`). Its budget is the startup
    # probe's own bound plus grace, read from the heartbeat so a config or constant change cannot
    # strand it: `_startup_grounding_check` stamps `probe_timeout_s` in the beat it writes.
    #
    # Without this branch `starting` matched nothing and fell through to the "alive" return below
    # — the same fall-through that reported a wedged `draining` tick healthy forever. Here it
    # mattered more, because a wedge at startup is the one case where the heartbeat's pid is the
    # only way `_kill_stale_daemon` can find the process that is actually stuck.
    if phase == "starting":
        budget = beat.get("probe_timeout_s", _STARTUP_PROBE_TIMEOUT_S) / 60 + 5
        if age_min > budget:
            return False, (f"stuck in 'starting', heartbeat {ages} (> probe bound + grace "
                           f"{budget:.0f} min) — startup wedged before the first tick, so no "
                           f"in-process deadline covers it")
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
    except (subprocess.SubprocessError, OSError) as exc:
        # Narrowed from `except Exception` (TimeoutExpired is a SubprocessError): refusing to kill
        # is the right answer to a broken `ps`, but it is the WRONG answer to a bug in this code,
        # and the broad catch made the two identical while the daemon stayed wedged.
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


def _ensure_supervisor_loaded(cfg) -> dict:
    """Make "launchd KeepAlive will relaunch it" true before relying on it.

    Returns the supervisor receipt so a caller (or a test) can read the outcome. `ok` is False
    when the check itself failed, which is a different thing from "the job was already loaded".

    Every exit in `_kill_stale_daemon` promises launchd will bring the daemon back. That promise
    holds only while `com.prospector.scheduler` is bootstrapped into the user's launchd domain.

    On 2026-08-16 it was not. The plist was on disk with KeepAlive=1 and RunAtLoad=1, the service
    was absent from the domain, and the daemon stayed dead from 12:52 UTC while this watchdog went
    on logging that launchd had it in hand. The check is one `launchctl print`; the assumption it
    replaces cost hours of dead engine.
    """
    from prospector.ops.supervisor import PRODUCER, ensure_loaded

    try:
        rec = ensure_loaded(cfg, PRODUCER, actor="watchdog")
    except Exception as exc:  # noqa: BLE001 — a broken repair must not take the watchdog with it
        logger.error("Watchdog: supervisor check failed: %s", exc)
        rec = {"changed": False, "message": str(exc)}
        rec["ok"] = False  # in the RETURN value: a caller cannot read the log line above
        return rec

    if rec.get("changed"):
        from prospector.scheduler.alerts import CRITICAL, emit_alert

        logger.critical("Watchdog: %s was NOT loaded in launchd — bootstrapped it. %s",
                        PRODUCER, rec.get("message"))
        print(f"⚠ {PRODUCER} was not loaded; watchdog bootstrapped it")
        emit_alert(cfg, severity=CRITICAL, key="supervisor",
                   title="Daemon launchd job was missing",
                   message=(f"{PRODUCER} was not loaded, so KeepAlive could not relaunch the "
                            f"daemon and every 'launchd will restart it' line in the log was "
                            f"false. The watchdog re-bootstrapped it: {rec.get('message')}"),
                   throttle_s=3600)
    elif rec.get("ok") is False:
        logger.error("Watchdog: launchd cannot relaunch %s — %s", PRODUCER, rec.get("message"))

    return rec


def _check_consumer(cfg) -> None:
    """Page when the CONSUMER has died, which no other alarm in this estate can see.

    Since the producer/consumer split, the drain is a separate process — and every alarm here
    watches the producer. Worse, `alerts_for_tick` SUPPRESSES the all-DEFER tick alarm by design
    (correct while the producer merely enqueues), so a dead consumer leaves the producer ticking
    green while the queue grows without bound. That combination is silent by construction, which
    is why this check lives in the watchdog: the watchdog's 900s cadence is the only clock in the
    estate faster than the 7200s tick, and it runs in a process that is not the one being judged.

    IT ALERTS BUT NEVER KILLS, unlike the daemon branch. A drain pass was measured at 4127s
    against a ~251s median, and that tail is the whole reason the consumer exists; killing a
    `late` consumer would abort the exact long vet it was built to finish, then bill it again on
    the relaunch. A hung consumer costs throughput; a killed one costs work.

    `unknown` is deliberately not an alarm: no heartbeat file is also what "not deployed yet"
    looks like, and paging for that on every box that has never run a consumer is how a channel
    gets muted.
    """
    from prospector.consumer import consumer_liveness
    from prospector.scheduler.alerts import CRITICAL, WARNING, emit_alert, resolve_alert

    try:
        live = consumer_liveness(cfg)
    except Exception as exc:  # noqa: BLE001 — a broken check must not take the daemon watchdog with it
        logger.warning("Watchdog: consumer liveness check failed: %s", exc)
        return

    state, reason = live.get("state"), live.get("reason") or ""
    if state == "dead":
        emit_alert(cfg, severity=CRITICAL, key="consumer_down",
                   title="Drain consumer is DEAD", message=reason, throttle_s=3600)
        print(f"⚠ consumer DEAD: {reason}")
        return
    if state == "late":
        # WARNING, not CRITICAL: the pid is alive, so the likeliest cause is a long pass rather
        # than a death, and the two are only distinguishable by waiting.
        emit_alert(cfg, severity=WARNING, key="consumer_down",
                   title="Drain consumer is not beating", message=reason, throttle_s=3600)
        print(f"⚠ consumer LATE: {reason}")
        return
    # running / blocked / stopped / unknown are all non-alarms — and the resolve must cover
    # `blocked` too, or an operator's own PAUSE would leave a CRITICAL banner up until they
    # noticed it themselves.
    resolve_alert(cfg, key="consumer_down", reason=f"consumer is {state}: {reason}")


def _run_watchdog(cfg) -> int:
    """One-shot liveness check that RESTARTS the daemon if it is hung. Run on its own schedule.

    Intended to be invoked every ~15 min by a separate launchd job (com.prospector.watchdog.plist),
    so a dead/hung daemon is caught even though it emits no ticks. On a stale heartbeat it alerts
    AND kills the wedged pid so launchd KeepAlive relaunches it. Returns 0 if alive, 1 if not.

    THE RETURN CODE IS THE PRODUCER'S ANSWER ONLY. The consumer is checked here too (see
    `_check_consumer`) because this is the estate's fastest clock, but it reports through its own
    alert key: this exit code is what decides whether the DAEMON was killed, and folding a second
    process into it would make "the daemon is fine" unreadable from the outside.
    """
    from prospector.scheduler.alerts import CRITICAL, emit_alert, resolve_alert

    # First, and outside the producer's branches, so a `return` on the producer path can never
    # skip it — the two processes fail independently and the common case is exactly one of them.
    _check_consumer(cfg)

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
    # AFTER the kill, not before: killing converts "hung" into "exited", and this is the check
    # that there is a supervisor to notice. Without it the kill is just a kill.
    _ensure_supervisor_loaded(cfg)
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
        run_daemon(cfg, interval=args.interval, candidates=args.candidates,
                   config_path=args.config)
        return

    tick = run_tick(cfg, dry_run=args.dry_run, candidates=args.candidates)
    if tick["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

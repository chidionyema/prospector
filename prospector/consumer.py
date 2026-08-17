"""THE CONSUMER: a vetting loop that runs on the queue's clock instead of a tick's.

WHAT THIS REPLACES. Vetting used to be the middle third of a scheduler tick that also
generated and swept decay, all three sharing one 3-hour deadline in one process. That
coupling is what produced the failures this module exists to end:

  * A vet was measured at 4127s against a ~251s median. Sizing generation for that tail
    starves the queue; not sizing for it force-exits mid-verdict. Both happened — five
    `os._exit` breaches, 2026-08-13 to 2026-08-15, every one at batch=15.
  * A benched moat stopped GENERATION, because the tick could not do one without risking
    the other.
  * A drain measured at 4197s of a 10800s tick (39%), and 5885s (55%) on the next one,
    left generation whatever was left over — an allocation nobody chose.

A consumer has no deadline to run out of, so none of those trades exist for it. It takes
work when there is work, sleeps when there is not, and its unit of loss is one row.

WHAT IT IS NOT. It is not a new drain. `resume_deferred` -> `_cmd_resume` remains the ONE
implementation of "re-vet a row": same lease, same moat preflight, same trusted-only
classifier, same worker pool, same exclusions. A second copy would drift, and the copy that
drifts is the one nobody is watching (the defect `errors.looks_exhausted` exists to prevent).
This module is a supervisor around that call — it decides WHEN to drain and for how long to
wait, never HOW.

THE RAILS IT KEEPS. Every rail that bounded the tick still binds here, because the rails are
about liability, not about tick structure:

  * `PAUSE` halts it entirely. CLAUDE.md: "a rail with exceptions is not a rail" — and the
    consumer is precisely the process a tempting exception would be written for.
  * The daily spend cap halts it, re-read every cycle so raising the cap resumes it without
    a restart.
  * A blind moat is a BACKOFF, never an exit. `_cmd_resume` already refuses the pass and
    says why; the consumer's job is to keep the process alive so the queue drains itself the
    moment the brain returns, which is exactly what a per-tick process could not do.

WHY IT SLEEPS INSTEAD OF EXITING — and what that is NOT an argument for. Every halt reason
here is transient: a pause is lifted, a cap rolls over at midnight, a brain comes back. So
each one sleeps and re-checks.

Be precise about why, because the obvious justification is wrong: exiting would NOT re-couple
the halves. Decoupling is done by the durable queue, not by this process's uptime — a
consumer that exits on PAUSE and is restarted by launchd leaves the producer just as
unblocked and the rows just as safe in SQLite. `consume --once` under a supervisor is a
legitimate deployment of this same code, and it is offered.

The reasons are cost and legibility, which are smaller claims than "it would break":

  * A restart re-pays config load and `make_operator`, which makes network calls
    (`run.py:2704-2721` builds both before the pass, deliberately outside the drain's budget).
  * A restart re-evaluates the guard, and `evaluate()` re-scans `store/prospector.jsonl` —
    measured at 108s on a 157 MB one (`scheduler/guard.py::pause_block_reason`). At a
    supervisor's restart cadence that costs more than the pass it is gating.
  * A process that exits and respawns every cycle reads as a crash loop. A blocked cycle
    inside a live process reads as a blocked cycle, and its summary stays cumulative.

None of that makes the loop the correctness boundary. The lease is (`store.claim`), and it
holds identically whether this process sleeps for 300s or dies and comes back.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("prospector")

#: The consumer's HALF-STOP, mirroring the producer's `PAUSE_GENERATION`
#: (`scheduler/run_scheduled.py:233`). `PAUSE` halts both roles because it is the liability
#: rail and a rail with exceptions is not a rail; this stops only the vetting half, so
#: "hold the drain while I look at the moat" does not have to be expressed by reaching for
#: the liability rail — which is how an operator ends up leaving the liability rail on.
CONSUMER_PAUSE_FILENAME = "PAUSE_CONSUMER"


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ConsumerConfig:
    """The loop's pacing, all of it config-declared (`config.yaml consumer:`).

    `batch` is how many rows one drain pass takes before the loop regains control. It is not
    a throughput limit — the pass runs `vet_workers` rows in parallel regardless — it is how
    often the rails are re-read. Smaller means a PAUSE takes effect sooner and costs one more
    pass of setup; larger amortises the setup and defers the rail check by up to one batch.

    The three sleeps are deliberately different numbers because they answer different
    questions. `busy_s` is "the queue had work, how hard do we hammer the store" (near zero:
    the drain itself is the slow part). `idle_s` is "the queue is empty, how fast do we
    notice the producer filling it". `blocked_s` is "a rail is refusing us, how fast do we
    notice it lifted" — the longest, because a blocked cycle costs a guard evaluation that
    re-scans the spend ledger, which measured 108s on a 157 MB one.
    """

    batch: int = 5
    busy_s: float = 0.0
    idle_s: float = 60.0
    blocked_s: float = 300.0
    #: Stop after N passes. `None` = never (the daemon). Tests and one-shot operator runs
    #: pass an integer; nothing else should.
    max_passes: Optional[int] = None
    publish: bool = False
    #: How often the consumer runs the SLA decay sweep, in seconds. It is a cadence and not a
    #: per-pass job because the consumer cycles far faster than the 2h tick that used to own
    #: this: run per pass and a bounded 2-row sweep becomes a continuous re-vet of the whole
    #: published catalogue, at full moat cost, competing with the drain it is supposed to be
    #: secondary to. Defaults to the tick interval it inherited the job from.
    decay_interval_s: float = 7200.0


def consumer_config(cfg) -> ConsumerConfig:
    """Read `config.yaml consumer:` with every value defaulted and bounded.

    Defensive on the SECTION, not just the keys: `cfg.consumer` may be absent entirely (a
    config predating this module), a dict (how config.py builds YAML blocks today), or an
    object if that ever changes. A loop that crashes on a missing config block is a loop that
    cannot be introduced to a running estate.

    Every number is clamped rather than trusted. A negative or zero `batch` would make each
    pass a no-op that still paid full operator construction, which reads as a wedged consumer
    and is really a typo; a negative sleep would spin.
    """
    section = getattr(cfg, "consumer", None)

    def _read(key, default):
        if isinstance(section, dict):
            return section.get(key, default)
        return getattr(section, key, default) if section is not None else default

    def _num(key, default, *, floor=0.0):
        try:
            return max(floor, float(_read(key, default)))
        except (TypeError, ValueError):
            return default

    try:
        batch = max(1, int(_read("batch", 5)))
    except (TypeError, ValueError):
        batch = 5

    return ConsumerConfig(
        batch=batch,
        busy_s=_num("busy_s", 0.0),
        idle_s=_num("idle_s", 60.0),
        blocked_s=_num("blocked_s", 300.0),
        decay_interval_s=_num("decay_interval_s", 7200.0),
    )


#: Where the consumer records that it attempted a sweep. A FILE and not an in-process timer,
#: because `KeepAlive` respawns this process: an in-memory "last swept" resets on every crash,
#: so a consumer crash-looping at the plist's 120s ThrottleInterval would fire a full moat
#: sweep every two minutes — a cost bug that only appears in the failure case, which is the
#: worst place to keep one.
_DECAY_MARKER_FILENAME = "consumer_decay.json"


def _decay_marker(cfg) -> Path:
    from .scheduler import paths as _paths
    return _paths.scheduler_dir(cfg) / _DECAY_MARKER_FILENAME


def _decay_due(cfg, conf: ConsumerConfig, *, now: float | None = None) -> bool:
    """Is the SLA sweep due? True on the first run, and every `decay_interval_s` after.

    An unreadable or absent marker reads as DUE. That is the safe direction here and the
    opposite of the pause probe's: skipping a sweep silently lets an expired PASS keep selling
    on evidence nobody has rechecked, while running one too often costs a bounded 2 rows.
    """
    if conf.decay_interval_s <= 0:
        return False
    now = time.time() if now is None else now
    try:
        raw = json.loads(_decay_marker(cfg).read_text())
        return (now - float(raw["at"])) >= conf.decay_interval_s
    except Exception:  # noqa: BLE001 — missing, unparsable or wrong-shaped all mean "due"
        return True


def _stamp_decay(cfg, *, now: float | None = None) -> None:
    """Record the ATTEMPT, before the sweep runs, never after.

    "Attempted at" rather than "succeeded at" is deliberate: a sweep that raises has already
    spent whatever it spent, and a marker written only on success would retry it every cycle.
    The interval retries anyway, so the cost of stamping early is at most one delayed sweep and
    the cost of stamping late is an unbounded retry loop against a failing moat.
    """
    try:
        path = _decay_marker(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": time.time() if now is None else now}))
    except OSError as exc:
        # Not fatal: the consumer's job is draining, and a sweep that runs too often is a cost
        # problem rather than a correctness one. Logged so it cannot be silent.
        logger.warning("consumer: could not stamp the decay marker (%s)", exc)


def _maybe_decay(cfg, conf: ConsumerConfig) -> Optional[dict]:
    """Run the SLA decay sweep if it is due AND this estate is actually split.

    GATED ON `producer_mode` SO THE SWEEP HAS EXACTLY ONE OWNER. In the classic single-tick
    deployment the scheduler still runs it (`run_scheduled._decay_sweep_budget` returns the
    full budget), so a consumer loaded alongside — which the plist header calls "safe but
    pointless" — would otherwise double-sweep: two processes re-verifying the same expired
    PASSes at full moat cost, and each stamping a marker the other does not read.

    Never raises. `_decay_pass` already swallows its own failures by design; this adds the
    same guarantee around the config read and the import, because a consumer that dies on a
    secondary job has abandoned the queue, which is the primary one.

    NOT-DUE AND BROKEN ARE DIFFERENT RETURN VALUES, and that is the whole contract of the
    handler below. `None` means "nothing to do" — not producer mode, or inside the interval.
    A failure returns `{"error": ...}`, because the caller's only question is which of the two
    it got: a sweep that throws every cycle and returns `None` is byte-identical to a healthy
    estate between intervals, so SLA re-verification would stop for good while the loop kept
    reporting clean. The log is not enough. The marker is stamped BEFORE the sweep, so after a
    crash the next cycle is genuinely not due, and nothing downstream would ever ask again.
    """
    try:
        from .scheduler.run_scheduled import _decay_pass, _decay_per_tick, producer_mode
        if not producer_mode(cfg) or not _decay_due(cfg, conf):
            return None
        _stamp_decay(cfg)
        out = _decay_pass(cfg, _decay_per_tick(cfg))
        if out is not None:
            logger.info("consumer: decay sweep %s", out, extra={"decay": out})
        return out
    except Exception as exc:  # noqa: BLE001 — a secondary job must never end the loop
        logger.error("consumer: decay sweep failed (loop continues): %s", exc, exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Stop signal
# --------------------------------------------------------------------------- #
@dataclass
class StopFlag:
    """A cooperative stop, so a restart never lands mid-verdict.

    SIGTERM (what launchd and `kill` send) sets the flag; the loop finishes the drain pass it
    is in and then exits. Killing mid-pass is survivable — the lease expires and the row
    returns to the queue — but survivable is not free: the row's partial vet is paid for and
    thrown away, and it stays invisible for `lease_ttl_s` (7200s) before anyone can retake it.

    The flag is only ever SET by the handler, never cleared there. A handler that could
    un-stop the loop would make two rapid signals race, and the second one is usually the
    operator wondering why the first did nothing.
    """

    stopped: bool = False
    reason: str = ""
    _installed: list = field(default_factory=list)

    def stop(self, reason: str = "requested") -> None:
        if not self.stopped:
            self.stopped, self.reason = True, reason

    def install(self) -> "StopFlag":
        """Catch SIGTERM/SIGINT where the platform allows it.

        `signal.signal` raises ValueError off the main thread, and this loop is importable
        from a test or a notebook that is not on it. That is not a reason to refuse to run —
        it is a reason to run without the handler, since `max_passes` and an explicit
        `stop()` are the other two ways out.
        """
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous = signal.signal(sig, lambda s, _f: self.stop(f"signal {s}"))
                self._installed.append((sig, previous))
            except (ValueError, OSError, AttributeError):
                logger.debug("consumer: could not install handler for %s", sig)
        return self

    def restore(self) -> None:
        for sig, previous in self._installed:
            try:
                signal.signal(sig, previous)
            except (ValueError, OSError, AttributeError):
                pass
        self._installed.clear()


# --------------------------------------------------------------------------- #
# Liveness
# --------------------------------------------------------------------------- #
#: The consumer's own heartbeat file, SEPARATE from the producer's `heartbeat.json`. The
#: separation is load-bearing rather than tidiness: a heartbeat write overwrites the whole file,
#: so two processes sharing one path would each erase the other's phase, and a monitor would read
#: whichever wrote last as "the engine" — the producer's `generating` and the consumer's `blocked`
#: alternating in one field, with no way to tell which of the two roles had stalled.
_HEARTBEAT_FILENAME = "consumer_heartbeat.json"

#: Resolved once per process. `code_fingerprint()` hashes every module in the package plus
#: config.yaml, which is far too expensive per cycle — and it cannot change under a running
#: process anyway. That is the point of stamping it: a monitor diffs what this process is RUNNING
#: against what is on disk, which needs the value the process STARTED with, not a fresh read.
#: `""` means "asked and failed", so a failure is not retried every cycle.
_RUNNING_CODE_FP: Optional[str] = None


def _heartbeat_path(cfg) -> Path:
    from .scheduler import paths as _paths
    return _paths.scheduler_dir(cfg) / _HEARTBEAT_FILENAME


def _running_code_fp() -> str:
    """The fingerprint of the code this process loaded, computed at most once."""
    global _RUNNING_CODE_FP
    if _RUNNING_CODE_FP is None:
        try:
            from .scheduler.run_scheduled import code_fingerprint

            # Passed explicitly, exactly as the daemon passes it (`run_scheduled.py:2063`).
            # Argless OMITS config.yaml, and a monitor comparing an argless consumer value to
            # the daemon's config-inclusive one would paint a healthy process STALE CODE — the
            # R8 panel's own first false reading, reproduced from the other end.
            _RUNNING_CODE_FP = code_fingerprint("config.yaml") or ""
        except (ImportError, OSError, ValueError):  # liveness never fails on a diagnostic extra
            _RUNNING_CODE_FP = ""
    return _RUNNING_CODE_FP


def _write_heartbeat(cfg, *, phase: str, **extra) -> None:
    """Overwrite the liveness file every cycle, INCLUDING the cycles that only sleep.

    WHY THIS EXISTS. Before it the consumer wrote nothing observable but `consumer_decay.json`,
    stamped at most once per `decay_interval_s` (7200s) — so a dead consumer and a healthy one
    were byte-identical for up to two hours. The gap is not symmetrical with the producer's,
    because `alerts.py::alerts_for_tick` SUPPRESSES the all-DEFER tick alarm by design: correct
    while the drain was the middle third of a tick, and precisely wrong now that it is another
    process. A dead consumer leaves the producer ticking green while the queue fills, and
    nothing else in the estate can see it.

    WRITTEN ON THE SLEEPING CYCLES, which is the whole point rather than an extra. The long
    waits are `blocked_s` (300s) and `idle_s` (60s), and those are exactly the states in which a
    stopped process and a working one are indistinguishable from outside. `next_check` carries
    when this cycle intends to wake, so a monitor can say "silent for 400s having promised 300s"
    (late) rather than guessing from one fixed staleness threshold — which must be wrong for at
    least one of two cadences that differ by 5x.

    `mono` accompanies the wall-clock `ts` for the reason the producer documents, and this box is
    a live instance rather than a hypothetical: `ps -o lstart` reports `1 Jan 1970` for
    long-running pids here, and `store/scheduler/audit/1970-01-01.jsonl` exists on disk. A
    stepped wall clock inflates the apparent age while the loop turns normally; a stopped loop
    inflates both. Only the difference between them names the cause.

    NEVER RAISES. Liveness is a diagnostic: a consumer that died because it could not write a
    heartbeat would be the monitor causing the outage it exists to report.
    """
    beat = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mono": time.monotonic(),
        "pid": os.getpid(),
        "role": "consumer",
        "phase": phase,
        **extra,
    }
    fp = _running_code_fp()
    if fp:
        beat.setdefault("code", fp[:12])
    # ATOMIC, and load-bearing for the same reason it is in the producer. `write_text` truncates
    # and THEN writes, so a reader can catch a 0-byte file — and readers do not treat that as
    # "try again": the producer's watchdog turns an unreadable heartbeat into a SIGKILL. An empty
    # read, not corrupt JSON, is the measured signature of reading mid-truncate. `os.replace` is
    # atomic on POSIX, so a reader sees the whole previous beat or the whole new one.
    # The pid in the temp name keeps two consumers (a daemon and an operator's `--once`) from
    # colliding on one another's partial file.
    #
    # The try covers PATH RESOLUTION as well as the write, and that is not defensive padding:
    # `paths.store_dir` RAISES `ValueError` on a cfg with no `store_dir` rather than guessing a
    # cwd-relative default (`paths.py:65`, which exists because such a default reached the
    # production audit log from pytest). Catching only `OSError` therefore let a diagnostic take
    # down the loop it exists to watch — for every caller holding a minimal cfg, which is every
    # existing consumer test. `Exception` is correct here precisely because the promise in this
    # docstring is unconditional.
    tmp = None
    try:
        path = _heartbeat_path(cfg)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(beat, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 — see above; liveness may never break the drain
        logger.warning("consumer: could not write the heartbeat (%s)", exc)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _record_drain(cfg, out: dict, *, attempted: int, resumed: int) -> None:
    """Append ONE line per completed drain pass to `store/scheduler/consumer_drains.jsonl`.

    WHY A SECOND FILE WHEN THE HEARTBEAT ALREADY EXISTS. The heartbeat is OVERWRITTEN every
    cycle: it can answer "what is happening now" and it structurally cannot answer "how fast is
    the queue draining", which is the only input an ETA has. Before the producer/consumer split
    that rate was readable from `ticks.jsonl` (`result.resumed`), because the producer drained
    inside its own tick; the split moved the work to this process and left the series behind, so
    the ops console's ETA would have been computed from a history that stopped on 2026-08-15.

    ONE LINE PER PASS THAT ATTEMPTED WORK — the idle cycles are already counted in the heartbeat,
    and logging them here would grow the file at the idle cadence (60s) to say nothing.

    `backlog` rides along because `_cmd_resume` measured it anyway (it is the survey it just ran):
    that makes this a real backlog time series at no extra cost, which is a strictly better ETA
    input than a rate — and the reader can fall back to the rate when the series is short.

    NEVER RAISES, for the same reason the heartbeat does not: a diagnostic that can end the drain
    is a bigger defect than the one it reports.
    """
    try:
        from .jsonl_atomic import append_jsonl
        from .ops.readmodel import DRAIN_LOG_FILENAME
        from .scheduler import paths as _paths

        append_jsonl(_paths.scheduler_dir(cfg) / DRAIN_LOG_FILENAME, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "attempted": attempted,
            "resumed": resumed,
            "backlog": out.get("backlog"),
            "passes": out.get("passes"),
            "kills": out.get("kills"),
            "defers": out.get("defers"),
            # PARKED ROWS RIDE IN THE RATE SERIES. On 2026-08-16 this file logged
            # `attempted: 24, resumed: 0` every ten seconds for 25 minutes, and nothing in the
            # row said why — the 24 rows were held by four SIGKILLed workers. A drain rate of
            # zero is only readable if the row says how much of the queue was unavailable.
            "leased_skipped": out.get("leased_skipped", 0),
            "metered_usd": out.get("metered_usd"),
        }, fsync=False)
    except Exception as exc:  # noqa: BLE001 — see the docstring; a rate log never breaks a drain
        logger.warning("consumer: could not record the drain pass (%s)", exc)


#: Grace added to a beat's own `next_check` before it counts as late. One cycle's worth of
#: scheduling jitter plus the guard's own cost: `_blocked_reason` re-scans the spend ledger,
#: measured at 108s on a 157 MB one, and that scan happens BETWEEN two beats. A grace shorter
#: than the slowest thing that can legitimately happen between beats is an alarm that pages for
#: a working consumer, which is how an operator learns to ignore the channel.
_LATE_GRACE_S = 180.0

#: Used only when a beat carries no `next_check` (an older writer, or a `draining` beat, whose
#: duration is genuinely unbounded — 4127s was measured). Deliberately generous: the pid check
#: below is what catches a dead consumer FAST, so this threshold only has to catch the rarer
#: case of a process that is alive and wedged.
_NO_NEXT_CHECK_STALE_S = 3600.0


def _pid_alive(pid: int) -> Optional[bool]:
    """Is that pid running? `None` when we cannot tell.

    `None` is a distinct answer and not a convenience: on a permissions error the process exists
    but is not ours, and reporting that as dead would page for a healthy consumer, while
    reporting it as alive would hide a real death. The caller renders it as `unproven` — the
    `VERDICT_GLYPHS` slot a hand-rolled panel always omits, which is how "the probe could not
    run" ends up painted green.
    """
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    except OSError:
        return None


def consumer_liveness(cfg, *, now: float | None = None) -> dict:
    """Is the consumer alive, and if not, what kind of not-alive?

    THE ONE READER of the heartbeat format, so the alarm and every panel answer this question
    identically. Two readers of one file is how a dashboard and a pager come to disagree about
    whether the estate is up (memory: `one-reader-two-caller-shapes`).

    `state` is one of:
      `running`  — beat fresh, pid alive, doing work or legitimately sleeping
      `blocked`  — a rail is refusing it ON PURPOSE (PAUSE_CONSUMER, the spend cap, the moat).
                   NOT an alarm: the rail working is not a fault, and paging for it trains the
                   operator to ignore the channel that also carries the real failures.
      `stopped`  — it wrote a final beat and left. An operator's stop, not a death.
      `dead`     — the pid is gone and the last beat was not `stopped`. This is the alarm.
      `late`     — the pid is alive but the beat is older than the consumer itself promised.
      `unknown`  — no heartbeat file at all, or one that will not parse.

    A DEAD PID SHORT-CIRCUITS STALENESS. Waiting for a beat to age out before declaring death
    would keep the queue silently filling for the grace period, and the grace has to be generous
    (see `_LATE_GRACE_S`) precisely because the sleeps are long. The pid is the fast, certain
    signal; staleness is only the backstop for a process that is alive and wedged.
    """
    now = time.time() if now is None else now
    out: dict = {"state": "unknown", "reason": "", "path": None, "phase": None,
                 "pid": None, "age_s": None, "alive": False, "beat": None}
    try:
        path = _heartbeat_path(cfg)
    except Exception as exc:  # noqa: BLE001 — same reason as the writer: `store_dir` raises
        out["reason"] = f"cannot resolve the heartbeat path: {exc}"
        return out
    out["path"] = str(path)
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(beat, dict):
            raise ValueError("heartbeat is not an object")
    except FileNotFoundError:
        out["reason"] = ("no consumer heartbeat has ever been written — either the consumer has "
                         "not run since this was built, or it is not deployed")
        return out
    except Exception as exc:  # noqa: BLE001 — unreadable and unparsable are the same answer
        # NOT escalated to `dead`. An empty read is the measured signature of catching an
        # atomic write mid-flight, and the producer's watchdog turning that into a SIGKILL is a
        # scar this estate already carries. `unknown` is the honest state; a second consecutive
        # unknown is what a caller should act on.
        out["reason"] = f"unreadable heartbeat: {exc}"
        return out

    out["beat"] = beat
    phase = beat.get("phase")
    pid = int(beat.get("pid") or 0)
    out["phase"], out["pid"] = phase, pid

    ts = beat.get("ts")
    try:
        age = now - datetime.fromisoformat(str(ts)).timestamp()
    except (TypeError, ValueError):
        # The known condition: `ts` absent or not an ISO-8601 string. Narrow, so a bug in
        # this arithmetic surfaces instead of reading as a heartbeat with no timestamp.
        age = None
    out["age_s"] = age

    alive = _pid_alive(pid)
    out["pid_alive"] = alive

    if phase == "stopped":
        out["state"] = "stopped"
        out["reason"] = str(beat.get("stopped_because") or "stopped")
        return out

    if alive is False:
        out["state"] = "dead"
        out["reason"] = (f"pid {pid} is gone and its last beat was '{phase}', not 'stopped' — "
                         f"the consumer died without saying so")
        return out

    # Late is measured against what THIS beat promised, not a global constant, because the two
    # cadences differ by 5x (`idle_s` 60 vs `blocked_s` 300) and one threshold must be wrong for
    # one of them: too tight for blocked, or too slack to notice an idle loop stopping.
    nxt = beat.get("next_check")
    if age is not None:
        if isinstance(nxt, (int, float)) and now > float(nxt) + _LATE_GRACE_S:
            out["state"] = "late"
            out["reason"] = (f"beat is {age:.0f}s old; it promised to check back by "
                             f"{max(0.0, float(nxt) - now):.0f}s from now")
            return out
        if not isinstance(nxt, (int, float)) and age > _NO_NEXT_CHECK_STALE_S:
            out["state"] = "late"
            out["reason"] = f"beat is {age:.0f}s old in phase '{phase}' with no next_check"
            return out

    out["alive"] = True
    if phase in ("blocked", "skipped"):
        out["state"] = "blocked"
        out["reason"] = str(beat.get("blocked_reason") or beat.get("skipped_reason") or phase)
    else:
        out["state"] = "running"
        out["reason"] = f"phase={phase}"
    return out


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def _blocked_reason(cfg) -> Optional[str]:
    """Why the consumer may not drain right now, or None.

    Only the LIABILITY rails live here — PAUSE and the daily spend cap — and they are read
    through `guard_check`, the daemon's own function, so the two processes can never disagree
    about whether spending is allowed. The moat preflight is deliberately NOT here: it lives
    inside `_cmd_resume`, is trusted-only there for a documented reason, and duplicating it
    would create exactly the second copy this module's docstring refuses.
    """
    from .scheduler.guard import guard_check

    # Checked BEFORE the guard on purpose: `guard_check` re-scans the spend ledger (measured
    # 108s on a 157 MB one), and an operator who has explicitly stopped the consumer should not
    # pay that per cycle to be told what they already know.
    try:
        from .scheduler import paths as _paths
        pause = _paths.scheduler_dir(cfg) / CONSUMER_PAUSE_FILENAME
        if pause.exists():
            return f"{CONSUMER_PAUSE_FILENAME} present ({pause})"
    except Exception:  # noqa: BLE001
        # An unreadable store dir must not stop the drain on its own — the guard below is the
        # rail allowed to do that, and it reports its own failure with a reason.
        pass

    try:
        allowed, reason = guard_check(cfg)
    except Exception as e:  # noqa: BLE001
        # A guard that cannot evaluate is not permission to spend. CLAUDE.md forbids
        # unattended running without the two rails, so an unreadable rail stops the loop —
        # and it stops it as a BLOCK (which retries) rather than an error (which would exit),
        # because the usual cause is a ledger being rewritten under us.
        logger.error("consumer: guard could not be evaluated: %s", e)
        return f"guard unavailable: {e}"
    return None if allowed else reason


def run_consumer(cfg, *, batch: int | None = None, publish: bool = False,
                 max_passes: int | None = None, stop: StopFlag | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> dict:
    """Drain the queue until stopped. Returns a summary of what the loop did.

    `sleep` is injected so tests can run the loop at full speed without the pacing becoming
    the thing under test — and, more importantly, so a test that expects an idle backoff FAILS
    when the loop does not take one, rather than hanging for 60s and passing by timeout.

    THE RETURN IS CUMULATIVE, not the last pass. A supervisor's summary that reported only its
    final cycle would show `resumed: 0` for any run that ended on an empty queue — which is
    every healthy run — and that is indistinguishable from a consumer that never worked at all.
    """
    conf = consumer_config(cfg)
    batch = conf.batch if batch is None else max(1, int(batch))
    max_passes = conf.max_passes if max_passes is None else max_passes
    flag = stop or StopFlag()

    from .run import resume_deferred

    totals = {"passes": 0, "attempted": 0, "resumed": 0, "leased_elsewhere": 0,
              "blocked": 0, "idle": 0, "errors": 0, "decay_sweeps": 0,
              "stopped_because": ""}
    #: Consecutive cycles that were refused before a pass could start. A blocked cycle does
    #: NOT spend the pass budget — a PAUSE lifted between two cycles must still leave `--once`
    #: with its one pass to run — but it cannot be free either, or a bounded run never returns:
    #: `max_passes` was checked only against `passes`, so a consumer started with `--once` while
    #: the spend cap was reached looped on the guard forever, and the operator's one-shot command
    #: simply never came back. A block that outlasts the whole budget is not lifting.
    blocked_streak = 0

    logger.info("consumer: starting (batch=%d, publish=%s)", batch, publish,
                extra={"batch": batch, "publish": publish})
    # Before the first cycle, not after it. The first `_blocked_reason` re-scans the spend ledger
    # (measured 108s on a 157 MB one), so a heartbeat written only after a completed cycle would
    # leave a freshly-started consumer looking dead for the first two minutes of every restart —
    # and a KeepAlive crash-loop would then look like a permanently dead consumer rather than a
    # restarting one, which is the opposite of the diagnosis an operator needs.
    _write_heartbeat(cfg, phase="starting", cycle=0, batch=batch, publish=publish)

    while not flag.stopped:
        if max_passes is not None and totals["passes"] >= max_passes:
            totals["stopped_because"] = f"max_passes={max_passes}"
            break

        blocked = _blocked_reason(cfg)
        if blocked:
            totals["blocked"] += 1
            blocked_streak += 1
            # INFO, not WARNING: a paused or capped consumer is the rail working. Logging it
            # at warning every `blocked_s` would train the operator to ignore the channel that
            # also carries the real failures.
            logger.info("consumer: blocked — %s", blocked, extra={"blocked_reason": blocked})
            if max_passes is not None and blocked_streak > max_passes:
                # Bounded run, and the rail has refused more cycles in a row than the run has
                # passes to give. The daemon (`max_passes is None`) never takes this exit: being
                # alive when the condition lifts is the whole point of it.
                totals["stopped_because"] = (
                    f"blocked {blocked_streak} cycle(s) in a row: {blocked}")
                break
            # A blocked consumer is the RAIL WORKING, so this must not read as a fault — but it
            # is also the longest sleep in the loop, so it is the state most easily mistaken for
            # death. The reason travels with the beat, which is what lets a monitor render
            # "paused by the operator" and "capped at $100" differently from "not responding".
            _write_heartbeat(cfg, phase="blocked", cycle=totals["passes"],
                             blocked_reason=blocked, blocked_streak=blocked_streak,
                             next_check=time.time() + conf.blocked_s)
            sleep(conf.blocked_s)
            continue

        blocked_streak = 0
        # BEFORE the drain and outside the `attempted == 0` idle path, so an empty queue still
        # gets its sweep. Decay is about packs ALREADY on sale, so tying it to the arrival of
        # new work would switch the shelf's own SLA off exactly when the producer stopped —
        # i.e. it would be least alive in the situation where the catalogue is most stale.
        decayed = _maybe_decay(cfg, conf)
        if decayed is not None:
            # A broken sweep is counted as an ERROR, never as a sweep. Counting both together
            # would make the totals report the loop's INTENT rather than its effect, and this
            # is the one job whose failure is otherwise invisible: the marker is already
            # stamped, so a crashed sweep is silently not-due for the next full interval.
            if decayed.get("error"):
                totals["errors"] += 1
            else:
                totals["decay_sweeps"] += 1

        totals["passes"] += 1
        # BEFORE the drain, because the drain is the phase that can hang: a vet was measured at
        # 4127s against a ~251s median, and that tail is the reason this process exists. A beat
        # written only after `resume_deferred` returns would be missing for exactly the duration
        # of the pathology it is meant to expose. `phase=draining` plus a stale `ts` is the
        # signature of a stuck pass; `phase=idle` plus a stale `ts` is a stopped loop.
        _write_heartbeat(cfg, phase="draining", cycle=totals["passes"], batch=batch,
                         resumed_total=totals["resumed"], errors=totals["errors"])
        try:
            out = resume_deferred(cfg, limit=batch, publish=publish)
        except Exception as e:  # noqa: BLE001 - one bad pass must not end the consumer
            # The whole point of a long-running consumer is that it is still there when the
            # transient thing ends. Exiting on an exception would hand the queue back to
            # whatever restarts the process, on that thing's schedule instead of the queue's.
            totals["errors"] += 1
            logger.exception("consumer: drain pass failed: %s", e)
            _write_heartbeat(cfg, phase="error", cycle=totals["passes"], error=str(e)[:200],
                             errors=totals["errors"], next_check=time.time() + conf.blocked_s)
            sleep(conf.blocked_s)
            continue

        attempted = int(out.get("attempted", 0) or 0)
        resumed = int(out.get("resumed", 0) or 0)
        totals["attempted"] += attempted
        totals["resumed"] += resumed
        totals["leased_elsewhere"] += int(out.get("leased_elsewhere", 0) or 0)

        if "skipped" in out:
            # The moat preflight refused the pass. A BLOCK, not an idle: the queue is not
            # empty, nothing is wrong with this process, and the wait should be the long one.
            totals["blocked"] += 1
            logger.info("consumer: pass skipped — %s", out["skipped"],
                        extra={"skipped": out["skipped"]})
            # A distinct phase from `blocked`, because the cause is distinct and the operator's
            # action differs: `blocked` is a rail this operator armed (PAUSE, the cap), `skipped`
            # is the moat refusing the pass. Collapsing them would send someone to the pause table
            # to fix a dead brain.
            _write_heartbeat(cfg, phase="skipped", cycle=totals["passes"],
                             skipped_reason=str(out["skipped"])[:200],
                             next_check=time.time() + conf.blocked_s)
            sleep(conf.blocked_s)
            continue

        if attempted == 0:
            # An empty queue. This is the healthy steady state of a fast consumer, so it is
            # counted rather than logged per cycle — `idle` divided by `passes` is how you see
            # whether the producer is keeping up, and a log line here would bury that in noise.
            totals["idle"] += 1
            _write_heartbeat(cfg, phase="idle", cycle=totals["passes"],
                             idle_streak=totals["idle"], resumed_total=totals["resumed"],
                             next_check=time.time() + conf.idle_s)
            sleep(conf.idle_s)
            continue

        logger.info("consumer: pass drained %d/%d row(s)", resumed, attempted,
                    extra={"resumed": resumed, "attempted": attempted})
        _record_drain(cfg, out, attempted=attempted, resumed=resumed)
        _write_heartbeat(cfg, phase="drained", cycle=totals["passes"], resumed=resumed,
                         attempted=attempted, resumed_total=totals["resumed"],
                         next_check=time.time() + conf.busy_s)
        sleep(conf.busy_s)

    if flag.stopped and not totals["stopped_because"]:
        totals["stopped_because"] = flag.reason or "stopped"
    # A DELIBERATE stop is not a death, and without this beat it is indistinguishable from one:
    # the file would simply stop moving. `phase=stopped` with its reason is what lets a monitor
    # stay quiet for an operator-requested stop and page for a SIGKILL — the case no writer can
    # cover, and which the reader resolves by finding a stale beat whose pid is gone.
    _write_heartbeat(cfg, phase="stopped", cycle=totals["passes"],
                     stopped_because=totals["stopped_because"], resumed_total=totals["resumed"],
                     errors=totals["errors"])
    logger.info("consumer: stopped after %d pass(es), %d row(s) resumed (%s)",
                totals["passes"], totals["resumed"], totals["stopped_because"],
                extra=dict(totals))
    return totals

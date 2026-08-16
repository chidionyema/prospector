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
import signal
import time
from dataclasses import dataclass, field
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
        try:
            out = resume_deferred(cfg, limit=batch, publish=publish)
        except Exception as e:  # noqa: BLE001 - one bad pass must not end the consumer
            # The whole point of a long-running consumer is that it is still there when the
            # transient thing ends. Exiting on an exception would hand the queue back to
            # whatever restarts the process, on that thing's schedule instead of the queue's.
            totals["errors"] += 1
            logger.exception("consumer: drain pass failed: %s", e)
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
            sleep(conf.blocked_s)
            continue

        if attempted == 0:
            # An empty queue. This is the healthy steady state of a fast consumer, so it is
            # counted rather than logged per cycle — `idle` divided by `passes` is how you see
            # whether the producer is keeping up, and a log line here would bury that in noise.
            totals["idle"] += 1
            sleep(conf.idle_s)
            continue

        logger.info("consumer: pass drained %d/%d row(s)", resumed, attempted,
                    extra={"resumed": resumed, "attempted": attempted})
        sleep(conf.busy_s)

    if flag.stopped and not totals["stopped_because"]:
        totals["stopped_because"] = flag.reason or "stopped"
    logger.info("consumer: stopped after %d pass(es), %d row(s) resumed (%s)",
                totals["passes"], totals["resumed"], totals["stopped_because"],
                extra=dict(totals))
    return totals

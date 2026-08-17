"""R15 — the consumer must be observable, because nothing else can see it die.

THE DEFECT THIS CLOSES. The producer writes `store/scheduler/heartbeat.json` from eight call
sites. The consumer, until this change, wrote nothing observable but `consumer_decay.json` —
stamped at most once per `decay_interval_s` (7200s), so a dead consumer and a healthy one were
byte-identical for up to two hours.

That gap is dangerous rather than merely untidy, and asymmetric with the producer's:
`alerts.py::alerts_for_tick` suppresses the all-DEFER tick alarm by design. That was right while
the drain was the middle third of a tick. Now that the drain is a separate process, a dead
consumer leaves the producer ticking green while the queue fills, and no alarm anywhere fires.

So most of what follows is about the SLEEPING cycles. A beat written only when work happens would
be missing in exactly the states — blocked (300s) and idle (60s) — where a stopped process and a
working one are indistinguishable from outside.
"""
from __future__ import annotations

import json
import os
import time
import types

from prospector import consumer as C


class _Sleeps(list):
    def __call__(self, s):
        self.append(s)


def _cfg(tmp_path, **consumer_block):
    """A cfg with a REAL store_dir. `paths.store_dir` raises rather than defaulting, so a test
    that forgot this would not quietly write into the live store — it would fail loudly."""
    return types.SimpleNamespace(store_dir=str(tmp_path), consumer=consumer_block or {})


def _quiet_decay(monkeypatch):
    """Decay is a separate job with its own tests; it must not run inside a liveness test."""
    monkeypatch.setattr(C, "_maybe_decay", lambda cfg, conf: None)


def _drain(monkeypatch, out=None):
    def _fake(cfg, *, limit=None, publish=False, **kw):
        return dict(out or {"attempted": 0, "resumed": 0})

    monkeypatch.setattr("prospector.run.resume_deferred", _fake, raising=False)


def _record(monkeypatch) -> list:
    """Every beat the loop emits, in order, still written through to disk."""
    beats: list = []
    real = C._write_heartbeat

    def _spy(cfg, *, phase, **extra):
        beats.append({"phase": phase, **extra})
        return real(cfg, phase=phase, **extra)

    monkeypatch.setattr(C, "_write_heartbeat", _spy)
    return beats


def _phases(beats) -> list:
    return [b["phase"] for b in beats]


def _on_disk(tmp_path) -> dict:
    return json.loads((tmp_path / "scheduler" / C._HEARTBEAT_FILENAME).read_text())


def _put(tmp_path, **beat) -> None:
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / C._HEARTBEAT_FILENAME).write_text(json.dumps(beat))


# --------------------------------------------------------------------------- #
# The writer
# --------------------------------------------------------------------------- #
def test_a_beat_lands_before_the_first_guard_is_evaluated(tmp_path, monkeypatch):
    """A restart must not look dead while it pays for its first guard evaluation.

    `_blocked_reason` re-scans the spend ledger — measured at 108s on a 157 MB one. A heartbeat
    written only after a completed cycle would leave every restart invisible for that long, and a
    KeepAlive crash-loop would then read as permanently dead rather than as restarting, which is
    the opposite of the diagnosis an operator needs.
    """
    seen: list = []
    _quiet_decay(monkeypatch)
    _drain(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: seen.append(_on_disk(tmp_path)))

    C.run_consumer(_cfg(tmp_path), max_passes=1, sleep=_Sleeps())

    assert seen, "the guard never ran; this test would pass vacuously"
    assert seen[0]["phase"] == "starting", (
        "the guard is the slow part of a restart — a beat must already be on disk when it begins")
    assert seen[0]["pid"] == os.getpid()


def test_a_blocked_cycle_beats_and_carries_its_reason(tmp_path, monkeypatch):
    """The rail refusing is not a fault — but it is the LONGEST sleep, so it is the state most
    easily mistaken for death. The reason travels with the beat so a monitor can render "paused by
    the operator" differently from "not responding"."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: "PAUSE_CONSUMER present")
    beats = _record(monkeypatch)

    C.run_consumer(_cfg(tmp_path, blocked_s=1.0), max_passes=2, sleep=_Sleeps())

    blocked = [b for b in beats if b["phase"] == "blocked"]
    assert blocked, f"a blocked consumer emitted no beat at all: {_phases(beats)}"
    assert "PAUSE_CONSUMER" in blocked[0]["blocked_reason"]
    assert blocked[0]["blocked_streak"] == 1
    assert blocked[0]["next_check"] > time.time() - 5, "a beat must say when it will look again"


def test_the_beat_precedes_the_drain_so_a_hung_pass_is_visible(tmp_path, monkeypatch):
    """The drain is the phase that can hang: a vet measured 4127s against a ~251s median, which is
    the tail this whole process exists for. A beat written only after `resume_deferred` returns
    would be absent for exactly the duration of the pathology it must expose."""
    mid_pass: list = []
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)

    def _hang(cfg, *, limit=None, publish=False, **kw):
        mid_pass.append(_on_disk(tmp_path))       # what a monitor would see WHILE it is stuck
        return {"attempted": 0, "resumed": 0}

    monkeypatch.setattr("prospector.run.resume_deferred", _hang, raising=False)
    C.run_consumer(_cfg(tmp_path), max_passes=1, sleep=_Sleeps())

    assert mid_pass and mid_pass[0]["phase"] == "draining", (
        "mid-pass the heartbeat must already read 'draining' — otherwise a stuck vet is "
        "indistinguishable from a stopped loop")


def test_an_idle_cycle_beats_with_its_next_check(tmp_path, monkeypatch):
    """The healthy steady state of a fast consumer is an empty queue. If that state is silent,
    "keeping up" and "dead" look the same."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch)
    beats = _record(monkeypatch)

    C.run_consumer(_cfg(tmp_path, idle_s=30.0), max_passes=1, sleep=_Sleeps())

    idle = [b for b in beats if b["phase"] == "idle"]
    assert idle, f"an idle cycle emitted no beat: {_phases(beats)}"
    assert idle[0]["next_check"] > time.time()


def test_a_deliberate_stop_writes_a_final_beat(tmp_path, monkeypatch):
    """Without this, an operator's stop and a SIGKILL are the same observation: the file simply
    stops moving. `phase=stopped` is what lets a monitor stay quiet for one and page for the
    other."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch)

    C.run_consumer(_cfg(tmp_path), max_passes=1, sleep=_Sleeps())

    beat = _on_disk(tmp_path)
    assert beat["phase"] == "stopped"
    assert beat["stopped_because"] == "max_passes=1"


def test_the_consumer_never_writes_the_producers_heartbeat(tmp_path, monkeypatch):
    """A heartbeat write replaces the WHOLE file. Two roles on one path would each erase the
    other's phase, and a monitor would read whichever wrote last as "the engine" — with no way to
    tell which of the two processes had stalled."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch)

    C.run_consumer(_cfg(tmp_path), max_passes=1, sleep=_Sleeps())

    assert C._HEARTBEAT_FILENAME != "heartbeat.json"
    assert not (tmp_path / "scheduler" / "heartbeat.json").exists()
    assert _on_disk(tmp_path)["role"] == "consumer"


def test_a_heartbeat_failure_never_stops_the_drain(tmp_path, monkeypatch):
    """The promise in `_write_heartbeat`'s docstring, enforced.

    Not hypothetical: `paths.store_dir` RAISES `ValueError` on a cfg with no `store_dir` (it
    refuses to guess, because a cwd-relative default once reached the production audit log). An
    earlier draft of the writer caught only `OSError`, so the diagnostic would have killed the
    loop it exists to watch — for every caller holding a minimal cfg, which is most of them.
    """
    cfg = types.SimpleNamespace(consumer={})            # no store_dir, on purpose
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch, {"attempted": 3, "resumed": 3})

    totals = C.run_consumer(cfg, max_passes=1, sleep=_Sleeps())
    assert totals["resumed"] == 3, "the drain must complete even when liveness cannot be written"


def test_the_write_is_atomic_and_leaves_no_temp_behind(tmp_path, monkeypatch):
    """`write_text` truncates and THEN writes, so a reader can catch a 0-byte file — and an empty
    read, not corrupt JSON, is the measured signature of that race. Hence tmp + `os.replace`."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch)

    C.run_consumer(_cfg(tmp_path), max_passes=2, sleep=_Sleeps())

    leftovers = list((tmp_path / "scheduler").glob(f"{C._HEARTBEAT_FILENAME}.*"))
    assert leftovers == [], f"atomic write left a temp file behind: {leftovers}"


def test_every_beat_carries_a_monotonic_clock(tmp_path, monkeypatch):
    """This box produces 1970-dated timestamps (`store/scheduler/audit/1970-01-01.jsonl` is
    tracked in git). A liveness check that could only subtract wall clocks would report a healthy
    consumer as 56 years stale, so the beat carries `mono` alongside `ts`."""
    _quiet_decay(monkeypatch)
    monkeypatch.setattr(C, "_blocked_reason", lambda cfg: None)
    _drain(monkeypatch)

    C.run_consumer(_cfg(tmp_path), max_passes=1, sleep=_Sleeps())

    beat = _on_disk(tmp_path)
    assert isinstance(beat["mono"], (int, float))
    assert beat["ts"]


# --------------------------------------------------------------------------- #
# The reader — one reader, so the alarm and every panel agree
# --------------------------------------------------------------------------- #
def test_no_heartbeat_at_all_is_unknown_not_dead(tmp_path):
    """Absence is not evidence of death: it is also what "not deployed yet" looks like."""
    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "unknown"
    assert out["alive"] is False


def test_a_dead_pid_is_the_alarm_and_does_not_wait_for_staleness(tmp_path):
    """THE case this requirement exists for.

    Waiting for the beat to age out first would keep the queue silently filling for the grace
    period — and the grace must be generous, because the sleeps are long. The pid is the fast,
    certain signal; staleness is only the backstop for a process that is alive and wedged.
    """
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), mono=1.0,
         pid=999_999, role="consumer", phase="draining")     # fresh beat, gone process

    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "dead", "a fresh beat from a dead pid is still a dead consumer"
    assert out["alive"] is False


def test_a_stopped_consumer_is_not_an_alarm(tmp_path):
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=999_999,
         phase="stopped", stopped_because="signal 15")

    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "stopped"
    assert out["reason"] == "signal 15"


def test_a_blocked_consumer_is_reported_as_blocked_not_dead(tmp_path):
    """Paging for a rail that is working as designed is how an operator learns to ignore the
    channel that also carries the real failures."""
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=os.getpid(),
         phase="blocked", blocked_reason="daily cap reached", next_check=time.time() + 300)

    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "blocked"
    assert out["alive"] is True
    assert "cap" in out["reason"]


def test_a_skipped_pass_names_the_moat_not_the_pause_table(tmp_path):
    """`blocked` is a rail this operator armed; `skipped` is the moat refusing the pass. Both are
    "not draining", but collapsing them sends someone to the pause table to fix a dead brain."""
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=os.getpid(),
         phase="skipped", skipped_reason="moat blind: every verdict brain is dead",
         next_check=time.time() + 300)

    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "blocked"
    assert "moat" in out["reason"]


def test_late_is_measured_against_what_the_beat_promised(tmp_path):
    """The two cadences differ by 5x (`idle_s` 60 vs `blocked_s` 300), so a single global
    staleness threshold must be wrong for one of them. The beat carries its own deadline."""
    now = time.time()
    _put(tmp_path, ts=C.datetime.fromtimestamp(now - 900, C.timezone.utc).isoformat(),
         pid=os.getpid(), phase="idle", next_check=now - 600)

    assert C.consumer_liveness(_cfg(tmp_path), now=now)["state"] == "late"


def test_a_beat_inside_its_promise_is_running_even_when_old(tmp_path):
    """A 290s-old beat is healthy on a 300s cadence and a stall on a 60s one. Only the beat's own
    `next_check` distinguishes them, which is why the writer emits it."""
    now = time.time()
    _put(tmp_path, ts=C.datetime.fromtimestamp(now - 290, C.timezone.utc).isoformat(),
         pid=os.getpid(), phase="draining", next_check=now + 10)

    assert C.consumer_liveness(_cfg(tmp_path), now=now)["state"] == "running"


def test_an_unreadable_beat_is_unknown_not_dead(tmp_path):
    """An empty read is the signature of catching the atomic write mid-flight. Escalating that to
    `dead` is a scar this estate already carries — the producer's watchdog SIGKILLed a live
    daemon over exactly this class of read."""
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / C._HEARTBEAT_FILENAME).write_text("")          # exactly what a torn read returns

    out = C.consumer_liveness(_cfg(tmp_path))
    assert out["state"] == "unknown"
    assert out["alive"] is False


def test_an_unresolvable_store_is_unknown_and_does_not_raise(tmp_path):
    assert C.consumer_liveness(types.SimpleNamespace(consumer={}))["state"] == "unknown"


# --------------------------------------------------------------------------- #
# Prove the probe fires on the BEFORE state
# --------------------------------------------------------------------------- #
def test_the_alarm_would_have_been_silent_before_this_change(tmp_path):
    """A guard that cannot fail on the pre-change state proves nothing (memory:
    `prove-the-probe-fires-on-the-before-state`).

    The world before R15 is exactly "the consumer writes no heartbeat", and the only other
    artefact it touched — `consumer_decay.json` — is stamped at most once per 7200s and says
    nothing about liveness. So reconstruct that world: a store containing the decay marker and
    nothing else. A DEAD consumer there reads `unknown`, indistinguishable from one that was
    never deployed. That silence is the gap R15 closes.
    """
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scheduler" / C._DECAY_MARKER_FILENAME).write_text(
        json.dumps({"at": time.time()}))                # the ONLY pre-change artefact

    assert C.consumer_liveness(_cfg(tmp_path))["state"] == "unknown", (
        "pre-change, a dead consumer was unreportable")

    # Post-change, the same dead process is named as dead, from the same store.
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=999_999, phase="draining")
    assert C.consumer_liveness(_cfg(tmp_path))["state"] == "dead"


# --------------------------------------------------------------------------- #
# The alarm — a state nobody reads is not monitoring
# --------------------------------------------------------------------------- #
def _watchdog_cfg(tmp_path, monkeypatch):
    """The watchdog's own cfg shape: `store_dir` only, no `consumer` block. That is what
    `test_alert_resolution.py` passes, and the liveness check must not need more than the alert
    machinery already has."""
    from prospector.scheduler import run_scheduled as rs

    monkeypatch.setattr(rs, "_liveness", lambda _c: (True, "heartbeat 3 min old, phase=idle"))
    return types.SimpleNamespace(store_dir=str(tmp_path)), rs


def test_a_dead_consumer_pages_even_though_the_producer_is_green(tmp_path, monkeypatch):
    """The whole point of R15.

    The producer is healthy here — `_liveness` says so — which before this change was the ONLY
    thing the watchdog asked. Combined with `alerts_for_tick` suppressing the all-DEFER alarm,
    that made "producer green, consumer dead, queue growing" a state with no alarm anywhere.
    """
    from prospector.scheduler.alerts import active_alerts

    cfg, rs = _watchdog_cfg(tmp_path, monkeypatch)
    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=999_999, phase="draining")

    rc = rs._run_watchdog(cfg)

    active = active_alerts(cfg)
    assert "consumer_down" in active, f"a dead consumer raised nothing: {active}"
    assert rc == 0, ("the exit code is the PRODUCER's answer — it is what decides whether the "
                     "daemon was killed, and the producer is fine in this scenario")


def test_the_dead_consumer_alarm_reaches_the_phone(tmp_path, monkeypatch):
    """An alarm that only lands in a local file is the defect it is meant to close, one level up:
    a state nobody is looking at. The founder's channel is Telegram."""
    from prospector.scheduler.alerts import TELEGRAM_KEYS

    assert "consumer_down" in TELEGRAM_KEYS


def test_the_watchdog_never_kills_the_consumer(tmp_path, monkeypatch):
    """A drain pass measured 4127s against a ~251s median, and that tail is the reason the
    consumer exists. Killing a `late` consumer aborts the exact long vet it was built to finish
    and bills it again on relaunch: a hung consumer costs throughput, a killed one costs work."""
    cfg, rs = _watchdog_cfg(tmp_path, monkeypatch)
    killed: list = []

    def _kill(pid, sig):
        # Signal 0 is `_pid_alive`'s existence probe, not a kill — counting it here would make
        # this test fail on the liveness check doing its job.
        if sig:
            killed.append((pid, sig))

    monkeypatch.setattr(rs.os, "kill", _kill)   # `C.os` is the same module object

    now = time.time()
    _put(tmp_path, ts=C.datetime.fromtimestamp(now - 9000, C.timezone.utc).isoformat(),
         pid=os.getpid(), phase="draining", next_check=now - 8000)   # alive, very late

    rs._run_watchdog(cfg)
    assert killed == [], f"the watchdog killed something: {killed}"


def test_an_operators_pause_does_not_leave_a_critical_banner_up(tmp_path, monkeypatch):
    """`blocked` is the rail working. If it did not RESOLVE, an operator pausing the consumer
    after an outage would stare at a stale CRITICAL until they thought to clear it themselves —
    and a banner that lies about the current state is how the whole surface stops being trusted.
    """
    from prospector.scheduler.alerts import CRITICAL, active_alerts, emit_alert

    cfg, rs = _watchdog_cfg(tmp_path, monkeypatch)
    emit_alert(cfg, severity=CRITICAL, key="consumer_down",
               title="Drain consumer is DEAD", message="pid 18594 is gone")
    assert "consumer_down" in active_alerts(cfg)

    _put(tmp_path, ts=C.datetime.now(C.timezone.utc).isoformat(), pid=os.getpid(),
         phase="blocked", blocked_reason="PAUSE_CONSUMER present", next_check=time.time() + 300)
    rs._run_watchdog(cfg)

    assert "consumer_down" not in active_alerts(cfg)


def test_a_consumer_that_never_ran_does_not_page(tmp_path, monkeypatch):
    """`unknown` is also what "not deployed on this box" looks like. Paging for it on every store
    without a consumer is how a channel gets muted, and a muted rail carries nothing."""
    from prospector.scheduler.alerts import active_alerts

    cfg, rs = _watchdog_cfg(tmp_path, monkeypatch)
    rs._run_watchdog(cfg)
    assert "consumer_down" not in active_alerts(cfg)


def test_a_broken_liveness_check_never_takes_the_daemon_watchdog_with_it(tmp_path, monkeypatch):
    """This check is a diagnostic bolted onto the process that restarts a hung daemon. If it can
    raise, a bug in the new code disables the older alarm — the failure mode where adding
    monitoring reduces coverage."""
    cfg, rs = _watchdog_cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(C, "consumer_liveness",
                        lambda cfg, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    assert rs._run_watchdog(cfg) == 0, "the producer's verdict must survive a broken consumer check"

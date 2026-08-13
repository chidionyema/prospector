"""The two phases where the daemon spends its hours were stamped once and left to go stale.

THE DEFECT. `_write_heartbeat` was called exactly ONCE on the way into `generating` and once on the
way into `draining`. Both phases are long by design — a grounded batch is 15-30+ min, and a drain
pass is 15 rows at the measured ~5.5 min/candidate (~82 min). So for almost the whole of a HEALTHY
tick, the age of that heartbeat answered "how far has the wall clock moved since one write?" rather
than "is the loop still turning?". Those are different questions and only the second is liveness:
a clock step, an NTP correction or a laptop suspend moves the first and says nothing about the
second.

This is not a new theory. It is the identical defect already fixed for `sleeping`, whose refresh
loop in `run_daemon` exists because 47 daemons that `ps` proved were alive were SIGKILLed, every
one of them `phase=sleeping`, ages clustered 156-175 min against a 155 min budget. That fix was
applied to the sleep loop alone and never reached the working phases.

WHAT IS DELIBERATELY NOT TESTED HERE, because it is deliberately not changed: any budget.
`_liveness` still judges `generating`/`draining` against `_TICK_HARD_DEADLINE_S / 60 + 10`, and
`test_drain_is_supervised.py` owns those thresholds. Narrowing them on the (still unproven)
wall-clock-artefact hypothesis would trade 47 false criticals for a missed real stall, which the
2026-07-01 8.5h wedge is the argument against. What changes is what the EXISTING budget measures.

So the assertions below are about the WRITES, not the thresholds: that the beat advances during
long work, and — the half that a naive fix gets wrong — that it stops advancing the moment the
phase ends, so a straggler thread cannot overwrite the terminal `idle` beat and report work that
has already finished.
"""
from __future__ import annotations

import json
import threading
import time
import types

import pytest

from prospector.scheduler import run_scheduled as rs

# Fast enough that a test takes tenths of a second, slow enough that the sampling loops below
# genuinely straddle several refreshes rather than racing the first one.
FAST_BEAT = 0.02


def _cfg(tmp_path, **schedule):
    sched = {"batch_size": 15, "backlog_cap": 0}
    sched.update(schedule)
    return types.SimpleNamespace(
        store_dir=tmp_path,
        spend=types.SimpleNamespace(daily_cap_usd=20.0, warn_at_usd=15.0),
        schedule=sched,
        operator=["claude_cli"],
    )


def _beat(cfg) -> dict:
    return json.loads(rs._heartbeat_path(cfg).read_text(encoding="utf-8"))


@pytest.fixture
def quiet_tick(monkeypatch):
    """Let a tick reach its work branch without touching the network, the moat or the digest.

    Every stub here is a rail with its OWN test elsewhere; leaving them live would let a leaked
    dead mark or a real grounding probe skip the branch under test and pass vacuously — the
    failure mode `test_drain_is_supervised.py` documents in its `brake_engaged` fixture.
    """
    monkeypatch.setattr(rs, "_moat_blind_reason", lambda cfg: None)
    monkeypatch.setattr(rs, "_generation_suppressed", lambda cfg, decision: None)
    monkeypatch.setattr(rs, "_decay_pass", lambda cfg, n: None)
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda cfg, t: None)
    monkeypatch.setattr(rs, "_emit_tick_digest", lambda cfg, t: None)


@pytest.fixture
def fast_beat(monkeypatch):
    monkeypatch.setattr(rs, "_WORK_HEARTBEAT_REFRESH_S", FAST_BEAT)


# ------------------------------------------------------------------ the beat advances during work

def test_a_long_generating_tick_restamps_its_heartbeat(tmp_path, quiet_tick, fast_beat):
    """The load-bearing test, and it samples the FILE from inside the work rather than counting
    calls to `_write_heartbeat`. What a monitor reads is the file; a test that counts calls would
    still pass if the refresher wrote somewhere else or wrote the same bytes."""
    cfg = _cfg(tmp_path)
    seen = []

    def _slow_gen(_cfg_arg, _n):
        for _ in range(15):
            time.sleep(FAST_BEAT)
            seen.append(_beat(cfg)["ts"])
        return {"dossiers": 1}

    rs.run_tick(cfg, generate_fn=_slow_gen)

    assert len(set(seen)) > 1, (
        "the `generating` heartbeat never advanced during a batch that ran many refresh intervals "
        f"— it is still stamped once and left to age ({len(seen)} samples, all identical)")


def test_a_long_drain_restamps_its_heartbeat(tmp_path, monkeypatch, fast_beat):
    """The drain half. It matters more than generation, not less: while the backlog brake is
    engaged the drain is the daemon's ENTIRE workload, and ~82 min of legitimate work spent
    looking stale is exactly the reading that produced the 47 kills."""
    monkeypatch.setattr(rs, "_backlog_size", lambda cfg: 343)
    monkeypatch.setattr(rs, "_moat_blind_reason", lambda cfg: None)
    monkeypatch.setattr(rs, "_decay_pass", lambda cfg, n: None)
    monkeypatch.setattr(rs, "_emit_tick_alerts", lambda cfg, t: None)
    monkeypatch.setattr(rs, "_emit_tick_digest", lambda cfg, t: None)
    cfg = _cfg(tmp_path, backlog_cap=100)
    seen = []

    def _slow_drain(_cfg_arg, _n):
        for _ in range(15):
            time.sleep(FAST_BEAT)
            seen.append(_beat(cfg)["ts"])
        return {"resumed": 15}

    monkeypatch.setattr(rs, "_drain_pass", _slow_drain)

    rs.run_tick(cfg, generate_fn=lambda c, n: pytest.fail("generation ran on a suppressed tick"))

    assert len(set(seen)) > 1, (
        "the `draining` heartbeat never advanced during a drain that ran many refresh intervals")


def test_a_working_beat_says_how_often_it_promises_to_write(tmp_path, quiet_tick, fast_beat):
    """`beat_every_s` is what turns "this beat is 3 min old" from ambiguous into a fact about the
    loop. It is currently written and read by nothing — see `_beating`'s docstring for why making
    it load-bearing is fenced off — but a reader cannot be added later to a field that was never
    written, and the sleep loop already sets the precedent."""
    cfg = _cfg(tmp_path)
    seen = []

    def _slow_gen(_cfg_arg, _n):
        time.sleep(FAST_BEAT * 3)
        seen.append(_beat(cfg))
        return {"dossiers": 1}

    rs.run_tick(cfg, generate_fn=_slow_gen)

    assert seen[0]["phase"] == "generating"
    assert seen[0]["beat_every_s"] == FAST_BEAT
    assert seen[0]["batch_size"] == 15, "the refresher must carry the phase's own fields, not drop them"


# --------------------------------------------------------------- and it STOPS when the phase does

def test_the_refresher_stops_and_cannot_overwrite_the_idle_beat(tmp_path, quiet_tick, fast_beat):
    """The half a naive fix gets wrong. A refresher that outlives its phase re-stamps
    `generating` on top of the terminal `idle` beat the tick writes on its way out, and the daemon
    then reports a batch permanently in flight — turning a liveness fix into a liveness bug."""
    cfg = _cfg(tmp_path)

    rs.run_tick(cfg, generate_fn=lambda c, n: {"dossiers": 1})
    assert _beat(cfg)["phase"] == "idle"

    time.sleep(FAST_BEAT * 10)

    assert _beat(cfg)["phase"] == "idle", (
        "a straggler refresh thread overwrote the terminal beat — the daemon now reports work "
        "that finished, which is the failure this change exists to prevent, inverted")


def test_the_refresher_stops_even_when_generation_raises(tmp_path, quiet_tick, fast_beat):
    """`run_tick` catches the exception and continues, so the stop must be in a `finally` rather
    than after the call. A leaked thread here survives into the daemon's SLEEP, where it would
    overwrite `sleeping` beats with `generating` and trip the watchdog's stall branch on a daemon
    that is resting normally."""
    cfg = _cfg(tmp_path)

    def _boom(_cfg_arg, _n):
        raise RuntimeError("batch blew up")

    tick = rs.run_tick(cfg, generate_fn=_boom)
    assert "RuntimeError" in tick["error"]
    assert _beat(cfg)["phase"] == "idle"

    time.sleep(FAST_BEAT * 10)

    assert _beat(cfg)["phase"] == "idle", "a raising batch leaked its heartbeat refresher"


def test_no_beating_thread_outlives_the_tick(tmp_path, quiet_tick, fast_beat):
    """The direct form of the two assertions above: threads are named, so a leak is nameable.
    Sampling the file can miss a straggler that happens to write between reads; this cannot."""
    cfg = _cfg(tmp_path)
    rs.run_tick(cfg, generate_fn=lambda c, n: {"dossiers": 1})

    time.sleep(FAST_BEAT * 5)
    leaked = [t.name for t in threading.enumerate() if t.name.startswith("heartbeat-")]

    assert leaked == [], f"heartbeat refresher threads outlived their tick: {leaked}"


# ------------------------------------------------ and a reader never catches it half-written

def test_the_heartbeat_is_never_readable_half_written(tmp_path):
    """FOUND BY THE TESTS ABOVE, and worse than the staleness they were written for.

    `_write_heartbeat` used `Path.write_text`, which truncates and then writes. A reader landing
    in that window gets 0 bytes. The first draft of `test_a_long_generating_tick_restamps_its_
    heartbeat` did exactly that and died on `JSONDecodeError: Expecting value: line 1 column 1
    (char 0)` — an EMPTY read, which is the signature of reading mid-truncate rather than of
    corrupt JSON.

    That is not a test-only annoyance, because of what the real reader does with it:
    `_watchdog_liveness` catches `JSONDecodeError` and returns `(False, "unreadable heartbeat")`,
    and `_kill_stale_daemon` turns a `False` into a SIGKILL. So a torn read is indistinguishable
    from a dead daemon, and the cure is to kill a healthy one. This file's own subject —
    refreshing the beat every `_WORK_HEARTBEAT_REFRESH_S` through the daemon's longest phases —
    multiplies the number of those windows per tick by roughly 120, so shipping the refresh on a
    truncating write would have made the 47-SIGKILL failure mode MORE likely, not less.

    The assertion is the violation itself (a reader observing a state that cannot be parsed),
    not the mechanism (`os.replace`), so a future rewrite that keeps atomicity by other means
    still passes and one that quietly drops it still fails.
    """
    cfg = _cfg(tmp_path)
    rs._write_heartbeat(cfg, phase="generating", batch_size=0)

    torn: list[str] = []
    stop = threading.Event()

    def _hammer_reads() -> None:
        while not stop.is_set():
            try:
                json.loads(rs._heartbeat_path(cfg).read_text(encoding="utf-8"))
            except FileNotFoundError:
                # `os.replace` never unlinks the destination, so this would itself be a defect;
                # recorded rather than ignored.
                torn.append("heartbeat vanished between writes")
            except ValueError as exc:
                torn.append(str(exc))

    reader = threading.Thread(target=_hammer_reads, name="hb-reader", daemon=True)
    reader.start()
    try:
        for i in range(400):
            rs._write_heartbeat(cfg, phase="generating", batch_size=i)
    finally:
        stop.set()
        reader.join(timeout=5)

    assert torn == [], (
        f"{len(torn)} of the reads caught the heartbeat mid-write (first: {torn[:1]}). The "
        "watchdog reads this file and treats an unparseable beat as a dead daemon, so a "
        "truncating write hands it a live daemon to SIGKILL.")


def test_a_failed_heartbeat_write_leaves_no_temp_files(tmp_path):
    """The cost of the atomic write is a temp file per call; a leaked one per FAILED write would
    accumulate silently in the scheduler dir forever, and the daemon writes thousands a day."""
    cfg = _cfg(tmp_path)
    rs._write_heartbeat(cfg, phase="idle")

    leftovers = list(rs._heartbeat_path(cfg).parent.glob("heartbeat.json.*"))

    assert leftovers == [], f"heartbeat temp files left behind: {leftovers}"

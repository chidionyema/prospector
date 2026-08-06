"""The watchdog SIGKILLed 47 daemons that `ps` proved were alive. These are the tests for the
two things that made those kills possible and unexplainable.

Every one of the 47 was `phase=sleeping`, with ages clustered 156-175 min against a budget of
`interval_s/60 + 35` = 155. Two defects combined:

  1. The `sleeping` heartbeat was stamped ONCE before a two-hour sleep, so its age measured
     "how far has the wall clock moved since a single write", not "is the loop turning". Any
     clock step, NTP correction or suspend inflates the first and says nothing about the second.
  2. Nothing configured logging, so `logger.critical` fell through to `logging.lastResort` and
     wrote a bare message with no timestamp — 173 lines recording 47 kills, none of which can be
     placed in time or checked against `pmset`.

The budgets themselves are deliberately NOT tightened here. A real 8.5h wedge on 2026-07-01 is
why the kill exists, and narrowing the window on an unproven theory trades false alarms for a
missed stall.
"""
from __future__ import annotations

import json
import logging
import re
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, cap=20.0, batch=3):
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=cap, warn_at_usd=cap * 0.75),
        schedule={"batch_size": batch},
    )


def _write_beat(tmp_path, **fields) -> None:
    hb = rs._heartbeat_path(_cfg(tmp_path))
    hb.write_text(json.dumps(fields), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# 1. The heartbeat is refreshed from inside the sleep
# --------------------------------------------------------------------------------------------

def _sleeping_beats(tmp_path, monkeypatch, *, interval: int) -> list[dict]:
    """Run one full cadence and return every `sleeping` heartbeat written during it.

    Spying on `_write_heartbeat` rather than reading the file, because the file is overwritten in
    place: on disk a refreshed heartbeat and a stamped-once one are byte-identical at the end of
    the sleep. The defect is a COUNT over time, so the count is what has to be observed.
    """
    beats: list[dict] = []
    real = rs._write_heartbeat

    def spy(cfg, *, phase, **extra):
        beats.append({"phase": phase, **extra})
        real(cfg, phase=phase, **extra)

    monkeypatch.setattr(rs, "_write_heartbeat", spy)
    rs.run_daemon(_cfg(tmp_path), interval=interval,
                  generate_fn=lambda c, n: {"dossiers": n},
                  max_cycles=2, sleep_fn=lambda s: None)
    return [b for b in beats if b["phase"] == "sleeping"]


def test_the_sleeping_heartbeat_is_refreshed_during_the_sleep(tmp_path, monkeypatch):
    beats = _sleeping_beats(tmp_path, monkeypatch, interval=600)
    assert len(beats) > 1, (
        "the sleeping heartbeat was stamped once and never refreshed — its age measures the wall "
        "clock, not the loop"
    )
    # Monotonic progress through the sleep, ending at the full cadence: proof these are refreshes
    # of one sleep and not repeated entries into it.
    slept = [b["slept_s"] for b in beats]
    assert slept == sorted(slept) and slept[0] == 0 and slept[-1] == 600


def test_no_healthy_gap_between_heartbeats_exceeds_the_refresh_interval(tmp_path, monkeypatch):
    """The property the watchdog actually needs: a live loop is never quiet for long.

    Without this the first test passes on a single mid-sleep refresh, which would still leave an
    hour-wide window in which a live daemon looks dead.
    """
    beats = _sleeping_beats(tmp_path, monkeypatch, interval=7200)  # the real 2h cadence
    gaps = [b["slept_s"] - a["slept_s"] for a, b in zip(beats, beats[1:])]
    assert gaps, "no refresh happened at all across a full 2h cadence"
    # +5 for the sleep slice the refresh check sits behind.
    assert max(gaps) <= rs._SLEEP_HEARTBEAT_REFRESH_S + 5, f"quiet for {max(gaps)}s"
    assert all(b["beat_every_s"] == rs._SLEEP_HEARTBEAT_REFRESH_S for b in beats), (
        "the refresh marker is missing, so `_liveness` cannot tell a new heartbeat from a legacy one"
    )


class _SteppedClock:
    """The wall clock the daemon reads, advanced only by the sleep it thinks it is doing.

    Stands in for `rs.datetime`, so `_write_heartbeat` and `_liveness` both see it. `fromisoformat`
    is proxied through because `_liveness` parses the stamp it wrote.
    """

    def __init__(self, start: datetime):
        self._now = start

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def now(self, tz=None) -> datetime:  # noqa: ARG002 — signature parity with datetime.now
        return self._now

    @staticmethod
    def fromisoformat(value: str) -> datetime:
        return datetime.fromisoformat(value)


def test_a_clock_step_mid_sleep_no_longer_reads_as_a_dead_loop(tmp_path, monkeypatch):
    """End to end reproduction of the state that produced 47 SIGKILLs of live daemons.

    A 2h cadence, with the wall clock stepping 50 min forward halfway through the sleep — an NTP
    correction, a resumed host, or whatever produced the 110 ticks dated 1970 on this machine. The
    loop never stops: `sleep_fn` is called for every slice, before and after the step.

    The daemon therefore emerges at wall-clock T+170 min against a budget of 155, which is squarely
    inside the observed kill cluster of 156-175 min. Stamped once, the heartbeat is 170 min old and
    the watchdog kills a process that has been turning the whole time. Refreshed every 60s, the
    newest stamp is written AFTER the step, so it is a minute old and the daemon reads as alive.

    Liveness is sampled every 15 simulated minutes from INSIDE the sleep, because that is where
    the watchdog runs and it is the only place the sleeping heartbeat is the current one — by the
    time `run_daemon` returns, the next tick has already overwritten it with `idle`, so a check
    afterwards would pass against the unfixed code and prove nothing.
    """
    cfg = _cfg(tmp_path)
    clock = _SteppedClock(datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(rs, "datetime", clock)

    interval = 7200
    elapsed = {"s": 0}
    STEP_AT, STEP_S, SAMPLE_EVERY = interval // 2, 50 * 60, 15 * 60
    verdicts: list[tuple[int, bool, str]] = []

    def sleep_fn(seconds):
        clock.advance(seconds)
        before, elapsed["s"] = elapsed["s"], elapsed["s"] + seconds
        if before < STEP_AT <= elapsed["s"]:
            clock.advance(STEP_S)  # the step itself: the clock moves, the loop does not stop
        if elapsed["s"] // SAMPLE_EVERY > before // SAMPLE_EVERY:
            ok, reason = rs._liveness(cfg)  # exactly what com.prospector.watchdog does
            verdicts.append((elapsed["s"], ok, reason))

    rs.run_daemon(cfg, interval=interval, generate_fn=lambda c, n: {"dossiers": n},
                  max_cycles=2, sleep_fn=sleep_fn)

    assert elapsed["s"] == interval, "the loop must have slept its full cadence, not exited early"
    assert len(verdicts) >= 7, f"only {len(verdicts)} watchdog passes simulated over 2h"
    down = [(s, r) for s, ok, r in verdicts if not ok]
    assert not down, (
        f"{len(down)} of {len(verdicts)} watchdog passes killed a loop that never stopped "
        f"(it called sleep_fn for every slice): {down[0][1]}"
    )


# --------------------------------------------------------------------------------------------
# 2. A failure reason that names its own cause
# --------------------------------------------------------------------------------------------

def test_a_stale_heartbeat_reports_wall_and_monotonic_age_side_by_side(tmp_path):
    """The shape a clock step or a suspend leaves: wall age huge, monotonic age tiny.

    Still judged DOWN — the budget is unchanged on purpose. What is new is that the alert says
    which of the two clocks moved, which is the fact the 47 existing kills cannot supply.
    """
    _write_beat(
        tmp_path,
        ts=(datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat(),
        mono=time.monotonic() - 120,
        pid=1, phase="sleeping", interval_s=7200, beat_every_s=60,
    )
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok
    assert "180 min old by wall clock" in reason
    assert "2 min monotonic" in reason


def test_a_genuinely_stopped_loop_reports_both_ages_large(tmp_path):
    """The other half of the discrimination — otherwise the reason string proves nothing.

    A wedged loop stops writing on both clocks, so both ages are large and the kill is correct.
    """
    _write_beat(
        tmp_path,
        ts=(datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat(),
        mono=time.monotonic() - 180 * 60,
        pid=1, phase="sleeping", interval_s=7200, beat_every_s=60,
    )
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok
    assert "180 min old by wall clock / 180 min monotonic" in reason


def test_a_legacy_heartbeat_without_a_monotonic_reading_still_reads(tmp_path):
    """A daemon mid-sleep across this deploy wrote no `mono` and no `beat_every_s`.

    It must not crash the watchdog and must not be judged by anything new: it is running exactly
    the code it was started with, and SIGKILLing it for that is the failure being fixed, repeated.
    """
    _write_beat(
        tmp_path,
        ts=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
        pid=1, phase="sleeping", interval_s=7200,
    )
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert ok, reason

    _write_beat(
        tmp_path,
        ts=(datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat(),
        pid=1, phase="sleeping", interval_s=7200,
    )
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok
    assert "180 min old" in reason and "monotonic" not in reason


# --------------------------------------------------------------------------------------------
# 3. Log lines that can be placed in time
# --------------------------------------------------------------------------------------------

def test_every_logged_line_carries_a_utc_timestamp_and_level():
    """`watchdog.err.log` has 173 lines and zero timestamps; that is what this stops.

    The message asserted is the real kill line from `_kill_stale_daemon`, formatted through the
    real formatter — the artifact that has to become correlatable, not a stand-in.
    """
    record = logging.LogRecord(
        "prospector.scheduler.run_scheduled", logging.CRITICAL, __file__, 1,
        "Watchdog: SIGKILLed hung daemon pid %d — launchd KeepAlive will relaunch.", (91757,), None,
    )
    line = rs._log_formatter().format(record)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z CRITICAL Watchdog: SIGKILLed", line), line
    # UTC, not local: the heartbeat's `ts` is UTC and the whole point is diffing the two.
    stamp = datetime.strptime(line.split("Z ")[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 120


def test_configure_logging_lets_the_watchdog_pass_line_through():
    """A log that records only kills reads as though every check kills the daemon.

    `lastResort` starts at WARNING, so the watchdog's INFO 'alive' line never reached the file —
    the same trap that made a completed run read as 'never ran'.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        root.handlers = []
        rs._configure_logging()
        assert root.isEnabledFor(logging.INFO)
        assert root.handlers, "no handler installed, so lines still fall through to lastResort"
        assert isinstance(root.handlers[0].formatter, logging.Formatter)
    finally:
        root.handlers, root.level = handlers, level


def test_configure_logging_does_not_stamp_on_a_caller_that_configured_its_own(tmp_path):
    """An embedding process (or a test harness) keeps its handler; only the level is raised."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        mine = logging.StreamHandler()
        root.handlers = [mine]
        rs._configure_logging()
        assert root.handlers == [mine]
    finally:
        root.handlers, root.level = handlers, level


def test_heartbeat_file_on_disk_carries_the_monotonic_reading(tmp_path):
    """`_liveness` reads a file, not a call — so the field has to survive the write."""
    rs._write_heartbeat(_cfg(tmp_path), phase="generating", batch_size=3)
    beat = json.loads(Path(rs._heartbeat_path(_cfg(tmp_path))).read_text(encoding="utf-8"))
    assert isinstance(beat["mono"], float)
    assert beat["phase"] == "generating"

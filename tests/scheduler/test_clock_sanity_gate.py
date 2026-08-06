"""A daily cap that sums by calendar day is disabled by a wrong clock, silently.

The failure is not theoretical and not subtle once you look for it. `SchedulerGuard` sums
today's spend by matching ledger rows on a `YYYY-MM-DD` prefix (`guard.py`, `_scan`). If the
system clock reads a day the ledger cannot have rows for, the sum is 0.00, the cap compares
0.00 against $20.00, and the daemon is cleared to generate without limit — while reporting
"ok: $0.0000 of $20.00 spent today", which reads like a healthy idle machine.

Measured on the live ledger before the gate existed::

    today=2026-08-06  ->  $1.1680 spent, can_run=True
    today=1970-01-01  ->  $0.0000 spent, can_run=True     <-- no cap at all

And it has happened in production: `store/scheduler/ticks.jsonl` holds 110 consecutive ticks
stamped 1970-01-01..03, every one reporting "$0.0000 of $20.00 spent today". They are real
daemon ticks (38-minute spacing, none under 10s apart, carrying the `batch_size: 5` of the
config in force at the time), not test pollution — see `prospector/scheduler/paths.py`.

CLAUDE.md makes the daily cap one of two automated rails that stand in for a human on an
unattended generator, and forbids unattended generation without them. So when the rail cannot
function, stopping is the only answer consistent with the rule; running is the thing the rule
exists to prevent.

What these tests pin is the boundary. The gate must fire on a clock behind the ledger, must
NOT fire on the ordinary cases that superficially resemble it (a clock ahead, a fresh store,
a ledger of undated rows), and must take its bound from the ledger's maximum rather than its
last line — because under this exact fault the last line is the oldest row in the file.
"""
from __future__ import annotations

import json

import pytest

from prospector.scheduler.guard import SchedulerGuard


def _store(tmp_path, rows):
    """A store whose ledger holds `rows` — (timestamp, usd) pairs, written in the given order."""
    (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
    with (tmp_path / "prospector.jsonl").open("w") as f:
        for ts, usd in rows:
            f.write(json.dumps({"timestamp": ts, "event": "spend", "amount_usd": usd}) + "\n")
    return tmp_path


LEDGER = [("2026-08-05T09:00:00", 3.0), ("2026-08-06T09:00:00", 4.0)]


# --------------------------------------------------------------------------- the fault
def test_an_epoch_clock_stops_the_daemon_instead_of_uncapping_it(tmp_path):
    guard = SchedulerGuard(_store(tmp_path, LEDGER), 20.0, today="1970-01-01")
    d = guard.evaluate()

    # The pre-gate behaviour was can_run=True with spend 0.00 — an uncapped generator that
    # looked idle. Refusing is not conservatism here; the cap is the liability backstop.
    assert d.can_run is False
    assert d.today_spend_usd == 0.0          # still 0.00: the gate is why it does not matter
    assert "clock is behind the ledger" in d.reason
    assert "1970-01-01" in d.reason and "2026-08-06" in d.reason


def test_one_day_behind_is_the_same_fault_as_thirty_years(tmp_path):
    # The damage does not scale with the size of the skew. A clock one day back sums a day
    # whose spend is already banked and cleared, which is a different number from today's and
    # is not bounded by it.
    d = SchedulerGuard(_store(tmp_path, LEDGER), 20.0, today="2026-08-05").evaluate()

    assert d.can_run is False
    assert "clock is behind the ledger" in d.reason


def test_the_bound_is_the_ledgers_maximum_not_its_last_row(tmp_path):
    # THE subtle one. The ledger is appended in wall-clock order, so under a backwards clock
    # the newest-appended row carries the OLDEST timestamp. Taking the bound from the last
    # line (the cheap O(1) seek) would read 1970, conclude the clock was fine, and pass the
    # exact fault this gate exists to catch.
    rows = LEDGER + [("1970-01-02T00:00:00", 0.0)]
    d = SchedulerGuard(_store(tmp_path, rows), 20.0, today="1970-01-03").evaluate()

    assert d.can_run is False
    assert "2026-08-06" in d.reason


# --------------------------------------------------------------------------- not the fault
def test_a_healthy_clock_still_reports_and_enforces_normally(tmp_path):
    d = SchedulerGuard(_store(tmp_path, LEDGER), 20.0, today="2026-08-06").evaluate()

    assert d.can_run is True
    assert d.today_spend_usd == 4.0          # the gate must not disturb the sum it protects
    assert "ok:" in d.reason


def test_a_clock_ahead_of_the_ledger_is_an_idle_machine_not_a_fault(tmp_path):
    # A daemon that has not run for a week, or simply the first tick after midnight, has
    # today > newest. Refusing there would brick the scheduler every night at 00:00.
    d = SchedulerGuard(_store(tmp_path, LEDGER), 20.0, today="2026-09-01").evaluate()

    assert d.can_run is True
    assert d.today_spend_usd == 0.0          # legitimately zero: a new day really has no rows


def test_a_fresh_store_with_no_ledger_is_not_bricked(tmp_path):
    (tmp_path / "scheduler").mkdir(parents=True)
    d = SchedulerGuard(tmp_path, 20.0, today="2026-08-06").evaluate()

    # No ledger means no lower bound on "now", so there is nothing to contradict. A gate that
    # fired here would make a first install unrunnable.
    assert d.can_run is True


def test_undated_rows_contribute_no_bound_rather_than_a_garbage_one(tmp_path):
    (tmp_path / "scheduler").mkdir(parents=True)
    (tmp_path / "prospector.jsonl").write_text(
        json.dumps({"timestamp": "yesterday afternoon", "event": "spend", "amount_usd": 1.0})
        + "\n")

    # An unanchored max over free text would compare "yesterday..." > any ISO date and refuse
    # forever, on a store that is perfectly healthy.
    d = SchedulerGuard(tmp_path, 20.0, today="2026-08-06").evaluate()
    assert d.can_run is True


# --------------------------------------------------------------------------- precedence
def test_an_explicit_pause_is_reported_as_a_pause_even_on_a_bad_clock(tmp_path):
    store = _store(tmp_path, LEDGER)
    (store / "scheduler" / "PAUSE").write_text("")

    d = SchedulerGuard(store, 20.0, today="1970-01-01").evaluate()

    # Both stop the daemon, so can_run is not the interesting part. The operator needs the
    # reason to name the thing they chose over the thing that broke: a PAUSE reported as a
    # clock fault sends someone to debug NTP over a file they created deliberately.
    assert d.can_run is False
    assert d.paused is True
    assert "paused" in d.reason


def test_a_bad_clock_is_reported_as_a_bad_clock_not_as_a_cap_breach(tmp_path):
    # Ordering is only observable when the skewed day itself trips the cap: reading 08-05,
    # the guard sums $500 and the cap fires. Cap-first stops the daemon for the right count
    # of the wrong day and says "daily cap reached" — which is a lie an operator acts on by
    # waiting for midnight, and midnight never comes on a stopped clock. Gate-first names the
    # thing that is actually broken.
    #
    # (Note the far more common skew, 1970, cannot distinguish the two orderings at all: the
    # sum is 0.00, so the cap never fires either way. A test built on that clock would assert
    # nothing — this one is built on the clock where the orderings genuinely differ.)
    rows = [("2026-08-05T09:00:00", 500.0), ("2026-08-06T09:00:00", 4.0)]
    d = SchedulerGuard(_store(tmp_path, rows), 20.0, today="2026-08-05").evaluate()

    assert d.can_run is False
    assert d.today_spend_usd == 500.0          # the cap WOULD fire on this number
    assert "clock is behind the ledger" in d.reason
    assert "daily cap reached" not in d.reason


# --------------------------------------------------------------------------- compatibility
def test_scan_today_keeps_its_two_value_shape(tmp_path):
    # `_scan` grew a third value; `scan_today` is the public read used for reporting and must
    # not change shape underneath a caller.
    metered, subscription = SchedulerGuard(_store(tmp_path, LEDGER), 20.0,
                                           today="2026-08-06").scan_today()
    assert (metered, subscription) == (4.0, 0.0)


@pytest.mark.parametrize("today,expected", [("2026-08-06", True), ("2026-08-04", False)])
def test_the_boundary_is_the_day_not_the_instant(tmp_path, today, expected):
    assert SchedulerGuard(_store(tmp_path, LEDGER), 20.0, today=today).evaluate().can_run is expected

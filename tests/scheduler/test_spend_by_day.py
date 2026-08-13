"""`SchedulerGuard.spend_by_day()` — the windowed reader, so nobody writes a second parser.

WHY THIS METHOD EXISTS AT ALL. Memory `never-hand-parse-the-spend-ledger`: answering "what was
spent?" by parsing `store/prospector.jsonl` in a caller returns a confident **$0.00 on a day with
real spend**, because the rows are keyed `timestamp` (not `date`) and the metered leg is
`event: "spend"` + `amount_usd`. A wrong key matches zero rows, sums nothing, raises nothing, and
fails in the safe-LOOKING direction. `scan_today()` covered exactly one day, so anything
reporting over a window — a batch receipt, a weekly $/vetted — had no reader to call and would
have written that second parse. `_scan` already accumulates the per-day mapping in the single
pass it makes for the cap; `spend_by_day` returns it instead of discarding it.

So the assertions below are about the two properties that make it a substitute for hand-parsing:
it splits the two legs by the same exclusive `event` test the cap uses, and the row shape a
hand-parser reaches for first sums to zero — proving the trap is still the trap, and that this
method does not fall into it.
"""
from __future__ import annotations

import json

from prospector.scheduler.guard import SchedulerGuard


def _ledger(tmp_path, rows: list[dict]):
    p = tmp_path / "prospector.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _guard(tmp_path, today="2026-08-13"):
    return SchedulerGuard(tmp_path, daily_cap_usd=20.0, today=today)


def test_metered_and_subscription_are_split_by_the_same_exclusive_event_test(tmp_path):
    """Both legs, per day, never merged: they differ by orders of magnitude ($2.71 metered vs
    $340 subscription on 2026-08-06), so a reader returning one number would read as total
    consumption whichever leg it picked."""
    _ledger(tmp_path, [
        {"timestamp": "2026-08-11T09:00:00Z", "event": "spend", "amount_usd": 1.25},
        {"timestamp": "2026-08-11T10:00:00Z", "cost_usd": 40.0},
        {"timestamp": "2026-08-12T10:00:00Z", "event": "spend", "amount_usd": 0.75},
        {"timestamp": "2026-08-12T11:00:00Z", "cost_usd": 12.5},
        # Both keys on one row must be counted ONCE, as metered: `_scan`'s branch is exclusive
        # so that a future provider emitting both cannot be double-billed against the cap.
        {"timestamp": "2026-08-12T12:00:00Z", "event": "spend", "amount_usd": 2.0,
         "cost_usd": 99.0},
    ])

    days = _guard(tmp_path).spend_by_day()

    assert days["2026-08-11"] == (1.25, 40.0)
    assert days["2026-08-12"] == (2.75, 12.5), (
        "a row carrying both amount_usd and cost_usd was counted on both legs — the cap and the "
        "subscription figure now disagree with the ledger")


def test_the_hand_parsers_row_shape_still_sums_to_zero(tmp_path):
    """The trap, frozen. `date`/`usd` is what a caller writing its own sum reaches for, and it
    matches nothing. If a future change ever made this shape count, the method would be silently
    accepting rows the CAP does not count, and the two numbers would drift apart."""
    _ledger(tmp_path, [
        {"date": "2026-08-11", "usd": 9.99},
        {"date": "2026-08-11", "spend": 9.99},
    ])

    assert _guard(tmp_path).spend_by_day() == {}, (
        "a row shape the daily cap ignores was counted here — the receipt and the rail would "
        "then report different money from the same file")


def test_a_day_with_no_rows_is_absent_not_zero(tmp_path):
    """Absent is the caller's decision to interpret, and the two readings are far apart: inside
    the scan's span it means the daemon spent nothing; before the span's oldest day it means the
    30-day checkpoint dropped it and the answer is unknown. Returning 0.0 for both would make the
    second indistinguishable from the first — which is the $0.00-on-a-real-day failure again,
    one level up."""
    _ledger(tmp_path, [
        {"timestamp": "2026-08-11T09:00:00Z", "event": "spend", "amount_usd": 1.0},
        {"timestamp": "2026-08-13T09:00:00Z", "event": "spend", "amount_usd": 1.0},
    ])

    days = _guard(tmp_path).spend_by_day()

    assert "2026-08-12" not in days
    assert sorted(days) == ["2026-08-11", "2026-08-13"]


def test_it_agrees_with_the_cap_on_today(tmp_path):
    """The rail and the receipt must never quote different money for the same day. This is the
    only assertion that ties the new reader to the enforced one."""
    _ledger(tmp_path, [
        {"timestamp": "2026-08-13T09:00:00Z", "event": "spend", "amount_usd": 3.5},
        {"timestamp": "2026-08-13T09:30:00Z", "cost_usd": 111.0},
        {"timestamp": "2026-08-01T09:00:00Z", "event": "spend", "amount_usd": 7.0},
    ])
    guard = _guard(tmp_path)

    metered, subscription = guard.scan_today()

    assert guard.spend_by_day()["2026-08-13"] == (metered, subscription)


def test_a_missing_ledger_is_an_empty_mapping_not_a_crash(tmp_path):
    """A fresh checkout has no ledger. A receipt that raises there would be removed from the
    first script it broke, and an unrun receipt measures nothing."""
    assert _guard(tmp_path).spend_by_day() == {}


def test_an_unparseable_line_is_skipped_without_losing_the_rest_of_the_day(tmp_path):
    """The ledger is appended by a live daemon, so a torn or truncated line is normal. Dropping
    the whole day on one bad line would understate spend exactly when the daemon is busiest."""
    p = tmp_path / "prospector.jsonl"
    p.write_text(
        json.dumps({"timestamp": "2026-08-13T09:00:00Z", "event": "spend", "amount_usd": 1.0})
        + "\n{ this is not json\n"
        + json.dumps({"timestamp": "2026-08-13T10:00:00Z", "event": "spend", "amount_usd": 2.0})
        + "\n", encoding="utf-8")

    assert _guard(tmp_path).spend_by_day()["2026-08-13"][0] == 3.0

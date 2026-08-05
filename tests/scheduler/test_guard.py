"""The automated backstop must actually fire: daily cap from the persistent ledger + PAUSE.

These supersede the prior in-process-telemetry tests. The daemon (and any per-tick subprocess)
runs as a fresh process whose in-process counter starts at ~0, so the cap MUST be derived from the
on-disk ledger to fire at all.
"""
from __future__ import annotations

import json
from pathlib import Path

from prospector.scheduler.guard import SchedulerGuard, guard_check

DAY = "2026-06-20"


def _write_ledger(store, events):
    p = Path(store) / "prospector.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for d in events:
            f.write(json.dumps(d) + "\n")


def _spend(amount, ts=f"{DAY} 09:00:00"):
    return {"event": "spend", "amount_usd": amount, "timestamp": ts}


def test_under_cap_can_run(tmp_path):
    _write_ledger(tmp_path, [_spend(2.0)])
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.can_run
    assert d.today_spend_usd == 2.0


def test_over_cap_blocks(tmp_path):
    _write_ledger(tmp_path, [_spend(12.0), _spend(9.0, f"{DAY} 10:00:00")])
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert not d.can_run
    assert "daily cap" in d.reason


def test_spend_only_counts_today(tmp_path):
    _write_ledger(tmp_path, [
        _spend(50.0, "2026-06-19 09:00:00"),  # yesterday — must be ignored
        _spend(1.0),
    ])
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    assert g.today_spend_usd() == 1.0
    assert g.evaluate().can_run


def test_pause_blocks_even_under_cap(tmp_path):
    _write_ledger(tmp_path, [_spend(0.0)])
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    g.scheduler_dir.mkdir(parents=True, exist_ok=True)
    g.pause_file.write_text("")
    d = g.evaluate()
    assert not d.can_run
    assert d.paused


def test_missing_ledger_is_zero_and_runs(tmp_path):
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    assert g.today_spend_usd() == 0.0
    assert g.evaluate().can_run


def test_malformed_lines_are_skipped(tmp_path):
    p = Path(tmp_path) / "prospector.jsonl"
    p.write_text("not json at all\n" + json.dumps(_spend(3.0)) + "\n", encoding="utf-8")
    assert SchedulerGuard(tmp_path, 20.0, today=DAY).today_spend_usd() == 3.0


def test_cap_is_inclusive(tmp_path):
    # Spending exactly the cap must block — the next batch would overshoot.
    _write_ledger(tmp_path, [_spend(20.0)])
    assert not SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate().can_run


# ── guard_check(cfg) compatibility wrapper ───────────────────────────────────

import types


def _cfg(store, cap):
    return types.SimpleNamespace(store_dir=str(store), spend=types.SimpleNamespace(daily_cap_usd=cap))


def test_guard_check_pause_wins(tmp_path):
    g = SchedulerGuard(tmp_path, 20.0)
    g.scheduler_dir.mkdir(parents=True, exist_ok=True)
    g.pause_file.write_text("")
    allowed, reason = guard_check(_cfg(tmp_path, 20.0))
    assert not allowed
    assert "paused" in reason


def test_guard_check_no_cap_disables_spend_rail(tmp_path):
    allowed, reason = guard_check(_cfg(tmp_path, 0.0))
    assert allowed
    assert "no daily cap" in reason


# ── the subscription leg the rail could not see ──────────────────────────────
#
# MEASURED 2026-08-05 on the live ledger (354,229 rows). Summing exactly as the guard did:
#
#   event=="spend" rows          : $1.6400  (370 rows, all minimax/MiniMax-M3)
#   "Claude CLI usage" rows      : $71.9393 (315 rows, cost_usd, NO `event` key)
#
# telemetry.py:225 emits `event: "spend"` only when the provider has non-zero pricing;
# claude_cli.py:82 logs its own billed figure under `cost_usd` with no event tag. So the rail
# bounded 2% of the day's model consumption while the probe printed "$1.64 of $20.00".
#
# CLI usage is subscription-equivalent, not invoiced, so it must NOT be folded into
# daily_cap_usd (that would halt the daemon daily for money nobody is billed). It must be
# MEASURED and REPORTED, with its own opt-in ceiling.


def _cli_usage(cost, ts=f"{DAY} 09:00:00"):
    """A real row shape, copied from store/prospector.jsonl on 2026-08-05."""
    return {"timestamp": ts, "level": "INFO", "name": "prospector",
            "message": "Claude CLI usage", "web": False, "input": 2, "output": 671,
            "total": 37441, "cached": 15273, "cost_usd": cost, "phase": "vetting"}


def test_cli_usage_is_measured_but_does_not_count_against_the_billed_cap(tmp_path):
    _write_ledger(tmp_path, [_spend(1.64)] + [_cli_usage(24.0) for _ in range(3)])
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()

    assert d.today_spend_usd == 1.64, "metered leg unchanged — only billed money gates the rail"
    assert d.today_subscription_usd == 72.0, (
        "the CLI leg was invisible: 315 such rows totalled $71.94 on 2026-08-05 and the guard "
        "reported $1.64 of $20.00 as if that were the day's consumption"
    )
    assert d.can_run, "72 > 20 must NOT halt the daemon: that is not billed money"
    assert "subscription-equivalent" in d.reason and "uncapped" in d.reason


def test_the_subscription_ceiling_is_opt_in_and_fires_when_armed(tmp_path):
    _write_ledger(tmp_path, [_spend(1.0)] + [_cli_usage(30.0) for _ in range(2)])

    off = SchedulerGuard(tmp_path, 20.0, today=DAY, daily_subscription_cap_usd=0.0).evaluate()
    assert off.can_run, "default 0 = disabled; arming it silently would halt a legal daemon"

    on = SchedulerGuard(tmp_path, 20.0, today=DAY, daily_subscription_cap_usd=50.0).evaluate()
    assert not on.can_run
    assert "daily subscription cap reached" in on.reason
    assert "not billed" in on.reason, "a halt here must never read as 'we spent real money'"


def test_the_two_legs_are_never_double_counted(tmp_path):
    """A row tagged `event: spend` that also carries cost_usd belongs to the metered leg only."""
    _write_ledger(tmp_path, [{"event": "spend", "amount_usd": 5.0, "cost_usd": 5.0,
                              "timestamp": f"{DAY} 09:00:00"}])
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_spend_usd == 5.0
    assert d.today_subscription_usd == 0.0


def test_cli_usage_respects_the_same_calendar_day(tmp_path):
    _write_ledger(tmp_path, [_cli_usage(99.0, "2026-06-19 23:30:00"), _cli_usage(4.0)])
    d = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert d.today_subscription_usd == 4.0
    assert d.day == DAY, (
        "the day must be reported: it is the LOCAL calendar day, and on 2026-08-05 the local "
        "rollover at 23:00 UTC made the spend figure fall $1.64 -> $0.13 mid-UTC-day, which "
        "read as a daemon restart resetting the rail"
    )

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

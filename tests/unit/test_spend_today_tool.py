"""`tools/spend_today.py` — the live read of the daily spend rail.

These lock two things, both of which failed for real on 2026-08-06.

1. The ledger's field names are `timestamp` / `event: "spend"` / `amount_usd`. A hand-rolled
   parse keyed on `date` and `metered_usd` matched zero rows and printed a confident
   "$0.00 of $20.00" for a day with real spend on it. The cap reading $0.00 is not a degraded
   cap, it is no cap — and it fails in the safe-LOOKING direction, so nothing surfaces it.
   `test_the_shape_a_hand_parse_assumes_contributes_nothing` is that bug, frozen.

2. The tool's exit code is the guard's decision, so it can gate a shell script. If it ever
   exits 0 while the guard refuses, an unattended job would run straight through the rail.
"""
from __future__ import annotations

import json

from prospector.scheduler.guard import SchedulerGuard


def _ledger(store: "object", rows: list[dict]) -> None:
    path = store / "prospector.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _guard(store, cap=20.0, today="2026-08-06") -> SchedulerGuard:
    (store / "scheduler").mkdir(parents=True, exist_ok=True)
    return SchedulerGuard(store, cap, today=today)


def test_real_ledger_shape_is_summed(tmp_path):
    _ledger(tmp_path, [
        {"timestamp": "2026-08-06 09:30:47,910", "event": "spend", "amount_usd": 0.008198},
        {"timestamp": "2026-08-06 09:31:13,552", "event": "spend", "amount_usd": 0.001335},
        {"timestamp": "2026-08-05 23:59:00,000", "event": "spend", "amount_usd": 99.0},
    ])
    guard = _guard(tmp_path)
    # Today's two rows only; yesterday's $99 must not leak across the day boundary.
    assert guard.today_spend_usd() == 0.009533


def test_the_shape_a_hand_parse_assumes_contributes_nothing(tmp_path):
    """The exact rows my broken parse expected. If these ever start summing, the ledger
    format changed and every reader keyed on the real names is now silently wrong."""
    _ledger(tmp_path, [
        {"date": "2026-08-06", "metered_usd": 5.0},
        {"date": "2026-08-06", "amount_usd": 7.0},
    ])
    assert _guard(tmp_path).today_spend_usd() == 0.0


def test_metered_and_subscription_are_never_conflated(tmp_path):
    """Subscription burn dwarfs metered (measured 2026-08-05: $1.64 vs $71.94). Folding it
    into the metered leg would halt the daemon against money nobody is invoiced for."""
    _ledger(tmp_path, [
        {"timestamp": "2026-08-06T09:00:00", "event": "spend", "amount_usd": 2.0},
        {"timestamp": "2026-08-06T09:00:01", "cost_usd": 71.94},
    ])
    guard = _guard(tmp_path)
    assert guard.today_spend_usd() == 2.0
    assert guard.today_subscription_usd() == 71.94


def test_tool_exit_code_is_the_guards_decision(tmp_path, monkeypatch, capsys):
    """Exit 0 only when the guard allows — this is what makes it usable as a shell gate."""
    import tools.spend_today as tool

    _ledger(tmp_path, [
        {"timestamp": "2026-08-06T09:00:00", "event": "spend", "amount_usd": 3.0},
    ])
    monkeypatch.setattr(tool, "load_config", lambda _p: object())
    monkeypatch.setattr(tool, "guard_from_config",
                        lambda _cfg, today=None: _guard(tmp_path, cap=20.0))
    monkeypatch.setattr("sys.argv", ["spend_today.py"])
    assert tool.main() == 0
    assert "$3.0000 of $20.00" in capsys.readouterr().out

    # Same ledger, cap now below what was spent: the rail must refuse.
    monkeypatch.setattr(tool, "guard_from_config",
                        lambda _cfg, today=None: _guard(tmp_path, cap=1.0))
    assert tool.main() == 1
    assert "REFUSE" in capsys.readouterr().out


def test_tool_refuses_when_the_clock_is_behind_the_ledger(tmp_path, monkeypatch, capsys):
    """A clock set back makes the cap sum a day with no rows and report $0.00 — no cap at
    all. It has happened: 110 live ticks dated 1970-01-01..03 all read '$0.0000 spent'."""
    import tools.spend_today as tool

    _ledger(tmp_path, [
        {"timestamp": "2026-08-06T09:00:00", "event": "spend", "amount_usd": 3.0},
    ])
    monkeypatch.setattr(tool, "load_config", lambda _p: object())
    monkeypatch.setattr(tool, "guard_from_config",
                        lambda _cfg, today=None: _guard(tmp_path, today="1970-01-01"))
    monkeypatch.setattr("sys.argv", ["spend_today.py"])
    assert tool.main() == 1
    out = capsys.readouterr().out
    assert "clock is behind the ledger" in out
    # The dangerous figure the rail would otherwise have enforced against.
    assert "$0.0000 of" in out

"""The spend scan must be incremental — and must still be the SAME number as a full re-scan.

Why this file exists (2026-08-10): `prospector-run.sh` runs the hourly guard/liveness probe under
`timeout 110`. `SchedulerGuard._scan` re-read the entire `store/prospector.jsonl` on every call —
measured live at 158 MB / 560,057 rows, 560,017 `json.loads` calls, 71 s per `--dry-run` probe —
so the cron job died with rc=124 and stderr `prospector: guard probe timed out after 110s`.

The scan is now checkpointed by byte offset. That makes the ledger's SIZE stop mattering, but it
also makes the figure that enforces `spend.daily_cap_usd` depend on cached state, so every way the
cache could lie is pinned here: appends, a day boundary crossed between ticks, a half-written row,
rotation, truncation, a corrupt cache, out-of-order (clock-fault) timestamps, and the escape hatch.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospector.scheduler import guard as guard_mod
from prospector.scheduler.guard import SchedulerGuard

DAY = "2026-06-20"
NEXT_DAY = "2026-06-21"


def _ledger(store) -> Path:
    return Path(store) / "prospector.jsonl"


def _append(store, rows, *, newline=True):
    p = _ledger(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for d in rows:
            f.write(json.dumps(d) + ("\n" if newline else ""))


def _spend(amount, ts=f"{DAY} 09:00:00"):
    return {"event": "spend", "amount_usd": amount, "timestamp": ts}


def _cli(cost, ts=f"{DAY} 09:00:00"):
    """A Claude Code CLI usage row: `cost_usd`, no `event` key (the subscription leg)."""
    return {"cost_usd": cost, "timestamp": ts, "message": "Claude CLI usage"}


def _full_scan(store, *, today, monkeypatch):
    """The uncached ground truth, via the documented escape hatch."""
    monkeypatch.setenv(guard_mod._FULL_SCAN_ENV, "1")
    try:
        return SchedulerGuard(store, 20.0, today=today)._scan()
    finally:
        monkeypatch.delenv(guard_mod._FULL_SCAN_ENV, raising=False)


def test_incremental_equals_full_scan_across_many_appends(tmp_path, monkeypatch):
    """The headline invariant: cached figure == uncached figure, tick after tick."""
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    _append(tmp_path, [_spend(1.5), _cli(4.0), _spend(0.25, "2026-06-19 23:00:00")])
    assert g._scan() == _full_scan(tmp_path, today=DAY, monkeypatch=monkeypatch)

    for i in range(5):
        _append(tmp_path, [_spend(0.1), _cli(0.2), {"noise": i}])
        fresh = SchedulerGuard(tmp_path, 20.0, today=DAY)  # new process each tick, as in prod
        assert fresh._scan() == _full_scan(tmp_path, today=DAY, monkeypatch=monkeypatch)

    metered, subscription, newest = SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()
    assert metered == pytest.approx(1.5 + 5 * 0.1)
    assert subscription == pytest.approx(4.0 + 5 * 0.2)
    assert newest == DAY


def test_second_tick_parses_only_the_new_rows(tmp_path, monkeypatch):
    """The actual fix: work per tick is O(rows appended), not O(ledger). This is the timeout."""
    _append(tmp_path, [_spend(1.0) for _ in range(200)])
    SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()  # warm the checkpoint

    real_loads = guard_mod.json.loads
    calls = []

    def counting_loads(s, *a, **kw):
        calls.append(1)
        return real_loads(s, *a, **kw)

    monkeypatch.setattr(guard_mod.json, "loads", counting_loads)
    _append(tmp_path, [_spend(2.0), _spend(3.0)])
    metered, _, _ = SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()

    assert metered == pytest.approx(205.0)          # all 202 rows are still counted
    assert len(calls) <= 3, f"re-parsed {len(calls)} rows; expected only the 2 appended (+cache)"


def test_day_boundary_crossed_between_ticks(tmp_path):
    """A checkpoint taken on day A must not strand day B's rows, nor leak A's into B."""
    g_a = SchedulerGuard(tmp_path, 20.0, today=DAY)
    _append(tmp_path, [_spend(7.0), _cli(1.0)])
    assert g_a._scan()[:2] == (7.0, 1.0)

    _append(tmp_path, [_spend(2.0, f"{NEXT_DAY} 01:00:00"), _cli(0.5, f"{NEXT_DAY} 01:00:00")])
    assert SchedulerGuard(tmp_path, 20.0, today=NEXT_DAY)._scan()[:2] == (2.0, 0.5)
    # ...and the earlier day is still exactly itself when asked for again.
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[:2] == (7.0, 1.0)


def test_partially_written_row_is_counted_exactly_once(tmp_path):
    """A row mid-append has no trailing newline: skip it, and do NOT advance past it."""
    _append(tmp_path, [_spend(1.0)])
    _append(tmp_path, [_spend(99.0)], newline=False)     # torn append in flight
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == 1.0

    with _ledger(tmp_path).open("a", encoding="utf-8") as f:
        f.write("\n")                                    # the writer finishes the row
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == pytest.approx(100.0)
    # Idempotent: a further tick must not double-count the row it just picked up.
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == pytest.approx(100.0)


def test_rotation_resets_the_checkpoint(tmp_path, monkeypatch):
    """A rotated ledger makes every cached offset meaningless — full re-scan, not a stale sum."""
    _append(tmp_path, [_spend(5.0) for _ in range(50)])
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == pytest.approx(250.0)

    _ledger(tmp_path).unlink()
    _append(tmp_path, [_spend(3.0)])                     # fresh file, different head, smaller
    got = SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()
    assert got[0] == pytest.approx(3.0)
    assert got == _full_scan(tmp_path, today=DAY, monkeypatch=monkeypatch)


def test_truncation_behind_the_offset_resets(tmp_path, monkeypatch):
    """Same head bytes, but the file shrank behind us: offset > size must force a re-scan."""
    _append(tmp_path, [_spend(1.0) for _ in range(20)])
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == pytest.approx(20.0)

    p = _ledger(tmp_path)
    keep = p.read_text(encoding="utf-8").splitlines(keepends=True)[:5]
    p.write_text("".join(keep), encoding="utf-8")
    got = SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()
    assert got[0] == pytest.approx(5.0)
    assert got == _full_scan(tmp_path, today=DAY, monkeypatch=monkeypatch)


@pytest.mark.parametrize("corrupt", [
    "not json at all",
    json.dumps({"version": 999, "head_sig": "x", "offset": 0, "newest": "", "days": {}}),
    json.dumps({"version": guard_mod._SCAN_CACHE_VERSION, "head_sig": "wrong",
                "offset": 10 ** 9, "newest": "", "days": {}}),
    json.dumps({"version": guard_mod._SCAN_CACHE_VERSION, "head_sig": "wrong",
                "offset": 0, "newest": "", "days": {DAY: ["oops", 0]}}),
])
def test_unusable_cache_falls_back_to_a_full_scan(tmp_path, monkeypatch, corrupt):
    _append(tmp_path, [_spend(4.0), _cli(2.0)])
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    g.scheduler_dir.mkdir(parents=True, exist_ok=True)
    g.scan_cache_path.write_text(corrupt, encoding="utf-8")
    assert g._scan() == _full_scan(tmp_path, today=DAY, monkeypatch=monkeypatch)
    assert g._scan()[:2] == (4.0, 2.0)


def test_newest_is_a_max_over_all_rows_not_the_last_one(tmp_path):
    """The clock-fault gate reads `newest`; a cached max must survive an out-of-order tail."""
    _append(tmp_path, [_spend(1.0, "2026-08-09 10:00:00")])
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[2] == "2026-08-09"

    _append(tmp_path, [_spend(1.0, "1970-01-01 00:00:00")])   # clock stepped backwards
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[2] == "2026-08-09"

    decision = SchedulerGuard(tmp_path, 20.0, today=DAY).evaluate()
    assert not decision.can_run and "clock is behind the ledger" in decision.reason


def test_full_scan_env_bypasses_and_does_not_write_the_cache(tmp_path, monkeypatch):
    _append(tmp_path, [_spend(6.0)])
    monkeypatch.setenv(guard_mod._FULL_SCAN_ENV, "1")
    g = SchedulerGuard(tmp_path, 20.0, today=DAY)
    assert g._scan()[0] == pytest.approx(6.0)
    assert not g.scan_cache_path.exists()


def test_non_dict_json_row_does_not_crash_the_rail(tmp_path):
    """A bare scalar line used to reach `.get` and raise; the guard must survive its own ledger."""
    _append(tmp_path, [_spend(1.0)])
    with _ledger(tmp_path).open("a", encoding="utf-8") as f:
        f.write("12345\n[]\n")
    _append(tmp_path, [_spend(2.0)])
    assert SchedulerGuard(tmp_path, 20.0, today=DAY)._scan()[0] == pytest.approx(3.0)

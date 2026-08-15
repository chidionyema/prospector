"""Failure-mode tests for `prospector.scheduler.status`.

THIS FILE IS THE DEFINITION OF "DONE" FOR THE WIRE-UP. The implementation must satisfy
every test below. The tests are intentionally read-only and use `tmp_path`/`monkeypatch`
exclusively — a real-store hit is the same test defect as a real Telegram send.

(failing-tests invariant 2026-08-08: this file is committed before the implementation so
the verify command can prove the delta is what made them green.)
"""
from __future__ import annotations

import json
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(tmp_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(store_dir=str(tmp_path))


def _write_heartbeat(tmp_path: Path, *, phase: str = "generating", ts: str | None = None,
                     pid: int = 22814) -> None:
    sd = tmp_path / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    if ts is None:
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    (sd / "heartbeat.json").write_text(json.dumps({"phase": phase, "ts": ts, "pid": pid}))


def _append_tick(tmp_path: Path, *, dry_run: bool = False, result: dict | None = None,
                 ts: str | None = None, allowed: bool = True, run_id: str = "abc") -> None:
    sd = tmp_path / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    row = {
        "ts": ts or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "allowed": allowed,
        "reason": "ok",
        "dry_run": dry_run,
        "today_spend_usd": 0.5,
        "daily_cap_usd": 20.0,
        "today_subscription_usd": 100.0,
        "batch_size": 15,
        "result": result,
        "run_id": run_id,
        "pid": 22814,
    }
    with (sd / "ticks.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def _write_alert_state(tmp_path: Path, active: dict) -> None:
    sd = tmp_path / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "alert_state.json").write_text(json.dumps({"_active": active}))


def _write_provider_health(tmp_path: Path, dead: list[str], moat_brains: list[str]) -> None:
    payload = {
        "providers": {name: {"dead_until": 9999999999.0} for name in dead},
        "moat_brains": moat_brains,
    }
    (tmp_path / "provider_health.json").write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# `status_snapshot`
# ---------------------------------------------------------------------------

def test_module_imports():
    from prospector.scheduler import status as S  # noqa: F401
    assert hasattr(S, "status_snapshot")
    assert hasattr(S, "format_status_snapshot")


def test_empty_store_returns_all_none_safely(tmp_path):
    """A brand-new store has no heartbeat, no ticks, no alerts. status_snapshot must
    never raise and must return a fully-populated dict with empty/None values."""
    from prospector.scheduler.status import status_snapshot

    snap = status_snapshot(_cfg(tmp_path))
    assert isinstance(snap, dict)
    assert snap["daemon"]["pid"] is None
    assert snap["daemon"]["phase"] is None
    assert snap["last_tick"] is None
    assert snap["spend"]["today_usd"] is None
    assert snap["spend"]["daily_cap_usd"] is None
    assert snap["providers"]["moat_blind"] is False
    assert snap["providers"]["dead"] == []
    assert snap["alerts"]["active"] == []
    assert snap["alerts"]["active_count"] == 0


def test_daemon_heartbeat_is_read(tmp_path):
    from prospector.scheduler.status import status_snapshot

    _write_heartbeat(tmp_path, phase="generating", ts=None)
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["daemon"]["phase"] == "generating"
    assert snap["daemon"]["pid"] == 22814
    assert snap["daemon"]["last_tick_age_s"] is not None
    assert 0 < snap["daemon"]["last_tick_age_s"] < 600


def test_dry_run_tick_rows_are_skipped(tmp_path):
    """The dry-run gating rows in ticks.jsonl must NOT count as the last tick result —
    the founder must see a real outcome, not a budget check (memory: hermes-cron-writes-dry-run-tick-rows)."""
    from prospector.scheduler.status import status_snapshot

    _append_tick(tmp_path, dry_run=True, result=None)
    _append_tick(tmp_path, dry_run=False, result={"dossiers": 11, "passes": 2, "kills": 8,
                                                  "defers": 1, "provisional": 0})
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["last_tick"] is not None
    assert snap["last_tick"]["dossiers"] == 11
    assert snap["last_tick"]["passes"] == 2
    assert snap["last_tick"]["kills"] == 8


def test_last_tick_only_when_real_result_present(tmp_path):
    """If only dry-run rows exist, last_tick is None (not a fake dossier=0)."""
    from prospector.scheduler.status import status_snapshot

    _append_tick(tmp_path, dry_run=True, result=None)
    _append_tick(tmp_path, dry_run=True, result=None)
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["last_tick"] is None


def test_spend_is_read_from_tick_history(tmp_path):
    from prospector.scheduler.status import status_snapshot

    _append_tick(tmp_path, today_spend_usd=1.23, daily_cap_usd=20.0,
                 today_subscription_usd=456.0)
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["spend"]["today_usd"] == 1.23
    assert snap["spend"]["daily_cap_usd"] == 20.0
    assert snap["spend"]["today_subscription_usd"] == 456.0


def test_moat_blind_is_true_when_every_brain_dead(tmp_path):
    from prospector.scheduler.status import status_snapshot

    _write_provider_health(tmp_path, dead=["claude_cli", "minimax"],
                            moat_brains=["claude_cli", "minimax"])
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["providers"]["moat_blind"] is True
    assert set(snap["providers"]["dead"]) == {"claude_cli", "minimax"}


def test_active_alerts_are_returned(tmp_path):
    from prospector.scheduler.status import status_snapshot

    _write_alert_state(tmp_path, {
        "zero_yield": {"key": "zero_yield", "severity": "warning",
                        "title": "Zero yield", "ts": "2026-08-08T11:34:49+00:00"}
    })
    snap = status_snapshot(_cfg(tmp_path))
    assert snap["alerts"]["active_count"] == 1
    assert snap["alerts"]["active"][0]["key"] == "zero_yield"


def test_backlog_counts_the_index_the_drain_works_from(tmp_path):
    """Backlog is the index's two populations, with the drain's own exclusions.

    Regression, measured 2026-08-08 on the live store: this counted `*.pass.json` as
    "deferred" and `*.provisional.json` as "provisional", and reported **76 / 0** where the
    index held **121 / 154**. `.pass.json` files are PASSES, and nothing is ever written as
    `*.provisional.json` — `provisional` is a column. The test that pinned the old behaviour
    invented a `c.provisional.json` fixture the engine never writes, so it stayed green while
    the number the founder actually read was wrong.
    """
    import sqlite3
    import types

    from prospector.scheduler.status import status_snapshot
    from prospector.store import Store

    cfg = types.SimpleNamespace(store_dir=tmp_path)
    store = Store(cfg)  # creates the schema, including the `tombstone` migration
    rows = [
        ("a", "defer", 0, None),      # plain defer
        ("b", "defer", 0, None),
        ("c", "pass", 1, None),       # provisional only
        ("d", "defer", 1, None),      # BOTH — must not be counted twice in `total`
        ("e", "kill", 0, None),       # terminal, never backlog
        ("f", "defer", 0, "gone"),    # tombstoned: run.py:1414-1415 drops it from both
    ]
    with sqlite3.connect(store.db) as conn:
        conn.executemany(
            "INSERT INTO dossiers (candidate_id, decision, provisional, tombstone) "
            "VALUES (?, ?, ?, ?)", rows)

    # A decoy in exactly the shape the old implementation looked for. If the count moves,
    # something is reading the filesystem again.
    d = tmp_path / "dossiers"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.provisional.json").write_text("{}")
    (d / "y.pass.json").write_text("{}")

    for shape, probe in (("Path", cfg), ("str", types.SimpleNamespace(store_dir=str(tmp_path)))):
        # BOTH caller shapes, because the two live callers disagree: the daemon passes a real
        # Config (Path) and the Telegram cockpit passes `SimpleNamespace(store_dir=str(...))`
        # (hermes-agent `gateway/operator_shell/prospector_now.py:290`). `store.py:71-72` calls
        # `.mkdir()` on the raw attribute, so the str shape read "—" on the phone while the
        # daemon read the truth — measured 2026-08-08 by rendering the real card.
        snap = status_snapshot(probe)
        assert snap["backlog"]["deferred"] == 3, f"{shape}: a, b, d — and NOT the tombstoned f"
        assert snap["backlog"]["provisional"] == 2, f"{shape}: c and d"
        assert snap["backlog"]["total"] == 4, f"{shape}: a, b, c, d — d is both, counted once"


def test_backlog_is_none_not_zero_when_the_index_is_unreadable(tmp_path):
    """An unreadable count must read as unknown. Zero is a claim the monitor cannot make."""
    import types

    from prospector.scheduler.status import status_snapshot

    # A DIRECTORY where the sqlite index should be: `store.all()` raises OperationalError.
    # The failure is isolated to the index on purpose — a bad `store_dir` makes
    # `paths.scheduler_dir()` raise first, and that raise is load-bearing (the cockpit probes
    # candidate repo paths by calling `status_snapshot` and catching). A str path is NOT a
    # failure either; see the test above.
    (tmp_path / "prospector.db").mkdir()
    snap = status_snapshot(types.SimpleNamespace(store_dir=tmp_path))
    assert snap["backlog"] == {"deferred": None, "provisional": None, "total": None}


# ---------------------------------------------------------------------------
# `format_status_snapshot`
# ---------------------------------------------------------------------------

def test_format_is_single_string_under_600_chars(tmp_path):
    from prospector.scheduler.status import format_status_snapshot, status_snapshot

    _write_heartbeat(tmp_path, phase="generating")
    _append_tick(tmp_path, dry_run=False, result={"dossiers": 11, "passes": 2, "kills": 8,
                                                   "defers": 1, "provisional": 0,
                                                   "total_cost_usd": 0.10})
    _write_alert_state(tmp_path, {"zero_yield": {"key": "zero_yield", "severity": "warning",
                                                  "title": "Zero yield",
                                                  "ts": "2026-08-08T11:34:49+00:00"}})
    _write_provider_health(tmp_path, dead=[], moat_brains=["claude_cli"])

    snap = status_snapshot(_cfg(tmp_path))
    msg = format_status_snapshot(snap)
    assert isinstance(msg, str)
    assert len(msg) <= 600, f"digest too long: {len(msg)} chars"
    assert "Zero yield" in msg or "⚠" in msg  # the active alert appears
    assert "11" in msg  # last tick dossiers echoed


def test_format_handles_empty_snapshot():
    from prospector.scheduler.status import format_status_snapshot

    snap = {"daemon": {"pid": None, "phase": None, "last_tick_age_s": None},
            "last_tick": None, "spend": {"today_usd": None, "daily_cap_usd": None,
                                          "today_subscription_usd": None},
            "providers": {"moat_blind": False, "dead": [], "moat_brains": [],
                           "blind_reason": None},
            "alerts": {"active": [], "active_count": 0},
            "backlog": {"deferred": None, "provisional": None}}
    msg = format_status_snapshot(snap)
    assert isinstance(msg, str)
    assert "no tick" in msg.lower() or "idle" in msg.lower() or "—" in msg

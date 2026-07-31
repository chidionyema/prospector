"""Real-time alerting: the daemon must turn bad ticks and daemon-death into operator alerts,
de-duplicate noisy conditions, and never let alerting crash the daemon."""
from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prospector.scheduler import alerts
from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path):
    return types.SimpleNamespace(store_dir=str(tmp_path))


# --- alerts_for_tick: pure classification ------------------------------------------------

def test_error_tick_is_critical():
    tick = {"allowed": True, "dry_run": False, "error": "RuntimeError: GEMINI_API_KEY not set",
            "result": None}
    specs = alerts.alerts_for_tick(tick)
    assert len(specs) == 1 and specs[0]["severity"] == alerts.CRITICAL
    assert specs[0]["key"] == "tick_error"


def test_barren_generation_warns():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "barren_generation"


def test_zero_yield_warns():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"
    assert "5" in specs[0]["title"]


def test_healthy_tick_no_alert():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 2}}
    assert alerts.alerts_for_tick(tick) == []


def test_all_deferred_is_critical_moat_outage():
    # Every candidate deferred => moat (Claude AND Gemini) down. Must be a distinct CRITICAL
    # outage alert, NOT mislabeled as a calibration "zero yield".
    tick = {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": 4, "passes": 0, "defers": 4}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "moat_deferred"
    assert specs[0]["severity"] == alerts.CRITICAL


def test_partial_defers_zero_yield_is_defer_aware():
    # Some deferred, some vetted-and-killed => still zero_yield, but the title says deferral so
    # the founder isn't pointed only at "calibration".
    tick = {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": 5, "passes": 0, "defers": 2}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"
    assert "deferred" in specs[0]["title"]


def test_missing_defers_field_is_safe():
    # Old ticks (pre-defers telemetry) must still classify as plain zero_yield, never crash.
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 5, "passes": 0}}
    specs = alerts.alerts_for_tick(tick)
    assert specs and specs[0]["key"] == "zero_yield"


def test_guarded_or_dry_run_never_alerts():
    assert alerts.alerts_for_tick({"allowed": False, "reason": "paused"}) == []
    assert alerts.alerts_for_tick({"allowed": True, "dry_run": True, "result": None}) == []


# --- emit_alert: audit trail + throttled notification ------------------------------------

def test_emit_logs_every_time_but_notifies_once(tmp_path, monkeypatch):
    notified = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda t, m: notified.append((t, m)))
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)
    cfg = _cfg(tmp_path)

    for _ in range(3):
        alerts.emit_alert(cfg, severity=alerts.WARNING, key="zero_yield",
                          title="Zero yield", message="0 PASS", throttle_s=3600)

    lines = (Path(tmp_path) / "scheduler" / "alerts.jsonl").read_text().splitlines()
    assert len(lines) == 3                    # audit trail records EVERY occurrence
    assert len(notified) == 1                 # but the founder is pinged once per throttle window
    assert json.loads(lines[0])["key"] == "zero_yield"


def test_alerting_never_raises(tmp_path, monkeypatch):
    # Even if a sink explodes, emit_alert must return cleanly (daemon resilience).
    def boom(*_a, **_k):
        raise RuntimeError("sink down")
    monkeypatch.setattr(alerts, "_desktop_notify", boom)
    rec = alerts.emit_alert(_cfg(tmp_path), severity=alerts.CRITICAL, key="x",
                            title="t", message="m")
    assert rec["key"] == "x"


# --- liveness watchdog -------------------------------------------------------------------

def _write_heartbeat(tmp_path, *, phase, age_min, interval_s=7200):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat()
    (sd / "heartbeat.json").write_text(json.dumps(
        {"ts": ts, "pid": 123, "phase": phase, "interval_s": interval_s}))


def test_liveness_missing_heartbeat_is_dead(tmp_path):
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok and "never run" in reason


def test_liveness_fresh_sleeping_is_alive(tmp_path):
    _write_heartbeat(tmp_path, phase="sleeping", age_min=10)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert ok


def test_liveness_stuck_generating_is_dead(tmp_path):
    # Derived from the deadline rather than hardcoded. _liveness computes
    # stall_min = _TICK_HARD_DEADLINE_S/60 + 10, so any fixed age here stops testing the
    # thing it names as soon as the deadline is retuned — which is exactly what happened:
    # a hardcoded 90 was a real assertion at the 75-min deadline and became a failure the
    # moment it moved to 3h. The constant's own comment warns about this trap on the
    # production side; the test carried the same bug.
    stall_min = rs._TICK_HARD_DEADLINE_S / 60 + 10
    _write_heartbeat(tmp_path, phase="generating", age_min=stall_min + 15)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok and "generating" in reason


def test_liveness_generating_within_deadline_is_alive(tmp_path):
    # The other half of the coupling, and the reason the test above is not enough on its
    # own: a watchdog that declared every 'generating' heartbeat dead would still satisfy
    # it, while force-exiting healthy long batches into the relaunch livelock the deadline
    # exists to prevent. A batch still inside its budget must be left alone.
    stall_min = rs._TICK_HARD_DEADLINE_S / 60 + 10
    _write_heartbeat(tmp_path, phase="generating", age_min=stall_min - 15)
    ok, _ = rs._liveness(_cfg(tmp_path))
    assert ok


def test_liveness_overdue_sleeping_is_dead(tmp_path):
    # interval 2h + 35 grace = ~155 min budget; 200 min old => dead.
    _write_heartbeat(tmp_path, phase="sleeping", age_min=200)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok


def test_watchdog_emits_alert_when_down(tmp_path, monkeypatch):
    fired = []
    monkeypatch.setattr(alerts, "_desktop_notify", lambda t, m: fired.append((t, m)))
    monkeypatch.setattr(alerts, "_webhook_post", lambda r: None)
    rc = rs._run_watchdog(_cfg(tmp_path))   # no heartbeat => down
    assert rc == 1 and len(fired) == 1
    assert "DOWN" in fired[0][0]


def test_barren_streak_escalates_to_critical():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick, consecutive_barren=3)
    assert len(specs) == 1 and specs[0]["severity"] == alerts.CRITICAL
    assert specs[0]["key"] == "barren_streak"
    assert "claude /login" in specs[0]["message"]


def test_barren_below_streak_threshold_stays_warning():
    tick = {"allowed": True, "dry_run": False, "error": None, "result": {"dossiers": 0, "passes": 0}}
    specs = alerts.alerts_for_tick(tick, consecutive_barren=2)
    assert specs and specs[0]["key"] == "barren_generation"
    assert specs[0]["severity"] == alerts.WARNING


def _write_ticks(cfg, rows):
    p = Path(cfg.store_dir) / "scheduler"
    p.mkdir(parents=True, exist_ok=True)
    (p / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _barren(dossiers=0, **kw):
    return {"allowed": True, "dry_run": False, "error": None,
            "result": {"dossiers": dossiers, "passes": 0}, **kw}


def test_trailing_barren_count_excludes_current_and_breaks_on_yield(tmp_path):
    cfg = _cfg(tmp_path)
    # oldest → newest: productive, barren, barren, barren(current)
    _write_ticks(cfg, [_barren(dossiers=5), _barren(), _barren(), _barren()])
    assert rs._trailing_barren_count(cfg) == 2  # current row excluded, streak stops at dossiers=5


def test_trailing_barren_count_skips_guard_rows_and_breaks_on_error(tmp_path):
    cfg = _cfg(tmp_path)
    _write_ticks(cfg, [
        _barren(error="boom"),                     # breaks the streak
        _barren(),
        {"allowed": False, "dry_run": False, "result": None},  # guard-skip: ignored
        _barren(dry_run=True),                     # dry-run: ignored
        _barren(),                                 # current tick
    ])
    assert rs._trailing_barren_count(cfg) == 1


def test_trailing_barren_count_missing_file_is_zero(tmp_path):
    assert rs._trailing_barren_count(_cfg(tmp_path)) == 0

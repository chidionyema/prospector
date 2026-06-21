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
    _write_heartbeat(tmp_path, phase="generating", age_min=90)
    ok, reason = rs._liveness(_cfg(tmp_path))
    assert not ok and "generating" in reason


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

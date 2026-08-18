"""The offsite backup must run where the store actually is, and must shout when it fails.

Before the Fly cutover on 2026-08-18 a launchd job at 03:40 backed the store up to R2. After the
cutover the store moved to the Fly volume at `/data/store` and the job kept running on the laptop,
against a `store/` nothing writes to any more. It was also invoking `backup_store.py --mirror-only`,
a flag that parser has never had (`scripts/backup_store.py:752-766` lists `--skip-mirror`), so
argparse exited 2 every night.

Neither failure was visible. Production went 34 hours with no offsite copy; the last receipt in
`store/backup.log` was `STORE_BACKUP PASS ... 2026-08-17T083751Z`.

These tests pin the replacement: the daemon loop backs up on its own cadence, and a failure raises
a CRITICAL alert instead of a log line nobody reads.
"""
from __future__ import annotations

import json
import subprocess
import types

import pytest

from prospector.scheduler import run_scheduled as rs


class _Cfg:
    def __init__(self, store_dir, **schedule):
        self.store_dir = str(store_dir)
        self.schedule = schedule


@pytest.fixture()
def cfg(tmp_path):
    (tmp_path / "scheduler").mkdir(parents=True)
    return _Cfg(tmp_path)


def _proc(rc, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_off_unless_the_deployment_says_this_machine_owns_it(cfg, monkeypatch):
    """Two machines running the schedule race for the same R2 keys. Opt in, never default on."""
    monkeypatch.delenv("ENGINE_BACKUPS_ENABLED", raising=False)
    calls = []
    assert rs.run_backup_if_due(cfg, run_fn=lambda *a, **k: calls.append(a)) is None
    assert calls == []


def test_runs_when_enabled_and_records_the_receipt_line(cfg, monkeypatch):
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    seen = {}

    def run_fn(cmd, **kw):
        seen["cmd"] = cmd
        return _proc(0, stdout="chatter\nSTORE_BACKUP PASS dossiers=2579 verified=8/8\n")

    rec = rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0, run_fn=run_fn)

    assert rec["rc"] == 0
    assert rec["verdict"] == "STORE_BACKUP PASS dossiers=2579 verified=8/8"
    # `--skip-mirror`, because the engine runs from a Docker image with no `/app/.git` and the
    # mirror step can only fail there.
    assert seen["cmd"][-1] == "--skip-mirror"
    assert seen["cmd"][1].endswith("scripts/backup_store.py")

    stamp = json.loads((cfg.store_dir + "/scheduler/last_backup.json") and
                       open(cfg.store_dir + "/scheduler/last_backup.json").read())
    assert stamp["ok_mono_wall"] == 1000.0


def test_at_most_once_per_interval(cfg, monkeypatch):
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    runs = []

    def run_fn(cmd, **kw):
        runs.append(cmd)
        return _proc(0, stdout="STORE_BACKUP PASS\n")

    rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0, run_fn=run_fn)
    rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0 + 3600, run_fn=run_fn)
    assert len(runs) == 1, "an hour later is not a day later"

    rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0 + 86_400, run_fn=run_fn)
    assert len(runs) == 2


def test_a_backwards_clock_does_not_park_the_backup_for_a_day(cfg, monkeypatch):
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    runs = []
    run_fn = lambda cmd, **kw: (runs.append(cmd), _proc(0, stdout="STORE_BACKUP PASS\n"))[1]

    rs.run_backup_if_due(cfg, now_fn=lambda: 1_000_000.0, run_fn=run_fn)
    # NTP steps the clock back. A naive `now - last >= interval` would wait out the difference.
    rs.run_backup_if_due(cfg, now_fn=lambda: 900_000.0, run_fn=run_fn)
    assert len(runs) == 2


def test_failure_raises_a_critical_alert_and_retries_next_tick(cfg, monkeypatch):
    """The whole defect: a stopped backup looked exactly like a quiet one."""
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    alerts = []
    monkeypatch.setattr("prospector.scheduler.alerts.emit_alert",
                        lambda cfg, **kw: alerts.append(kw))

    runs = []

    def run_fn(cmd, **kw):
        runs.append(cmd)
        return _proc(2, stderr="error: unrecognized arguments: --mirror-only")

    rec = rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0, run_fn=run_fn)
    assert rec["rc"] == 2
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["key"] == "backup"
    assert "--mirror-only" in alerts[0]["message"]

    # A failure must NOT stamp success, or one bad night silences the retry for a whole day.
    stamp = json.loads(open(cfg.store_dir + "/scheduler/last_backup.json").read())
    assert "ok_mono_wall" not in stamp
    rs.run_backup_if_due(cfg, now_fn=lambda: 1060.0, run_fn=run_fn)
    assert len(runs) == 2


def test_a_timeout_is_a_failure_not_a_hang(cfg, monkeypatch):
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    monkeypatch.setattr("prospector.scheduler.alerts.emit_alert", lambda cfg, **kw: None)

    def run_fn(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, rs._BACKUP_TIMEOUT_S)

    rec = rs.run_backup_if_due(cfg, now_fn=lambda: 1000.0, run_fn=run_fn)
    assert rec["rc"] == -1
    assert "timed out" in rec["detail"]


def test_interval_zero_disables_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_BACKUPS_ENABLED", "true")
    (tmp_path / "scheduler").mkdir(parents=True)
    cfg = _Cfg(tmp_path, backup_interval_s=0)
    runs = []
    assert rs.run_backup_if_due(cfg, run_fn=lambda *a, **k: runs.append(a)) is None
    assert runs == []

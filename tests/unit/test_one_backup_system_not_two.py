"""One backup system, not two.

Founder, 2026-08-21: "we dont eed 2 backup systes".

`scripts/backup_store.py` has copied store/prospector.jsonl and store/prospector.db to R2 since
2026-07-31. `scripts/engine_failover.py` ALSO carried 220 lines that pulled the same two files
off Fly over `fly ssh sftp` every 15 minutes, with its own size check, partial-tail trimmer,
shrink-refusal switch and stderr parser -- because sftp exits 0 on a short transfer.

Measured on the day it was deleted:

  R2's ledger snapshot     34,687,133 bytes, 2 minutes old
  the sftp path's last win      9,240,576 bytes of a 455,787,146-byte file, promoted as complete

and four distinct failures from the hand-rolled copy inside one day: `OSError: [Errno 28] No
space left on device`, `timed out after 600s`, a flyctl metrics WARNING parsed as "prospector.db
did not arrive", and `[1970-01-01T00:09:07Z]` in its own log.

These tests stop the second system growing back, and prove the failover restores from the first.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ef():
    return _load("engine_failover")


STATE = {
    "bucket": "prospector-backup",
    "ledger": {"key": "ledger/prospector-2026-08-21.jsonl.gz", "bytes": 34687133, "age_h": 0.5},
    "db": {"key": "db/prospector-2026-08-21.db.gz", "bytes": 978692, "age_h": 0.25},
    "oldest_age_h": 0.5,
    "complete": True,
}


# ── the second system stays deleted ───────────────────────────────────────────
DELETED = ("cmd_sync", "_source_size", "_rejects_arrival", "_trim_partial_tail",
           "_shrink_is_waived", "_db_is_intact")


@pytest.mark.parametrize("name", DELETED)
def test_the_hand_rolled_transfer_is_gone_and_stays_gone(ef, name):
    """Each of these existed only to answer "did the transfer finish?" -- a question the
    backup answers with Content-Length and a gzip CRC, in two lines, correctly."""
    assert not hasattr(ef, name), (
        f"{name} is back. The transfer-completeness question belongs to "
        f"scripts/backup_store.py, which checks it against Content-Length and the gzip CRC32 "
        f"written at compression time. Re-adding it here rebuilds the second backup system."
    )


def test_the_failover_watchdog_installs_no_sync_job():
    """The 900s launchd job is what made the failures recur every 15 minutes."""
    installer = (ROOT / "deploy" / "install_failover_watch.sh").read_text(encoding="utf-8")
    assert "standby-sync" not in installer, "the standby-sync launchd job is back"
    assert "com.prospector-control.failover-watch" in installer, "sanity: installer still parsed"


def test_the_module_imports_without_boto3(ef):
    """The frozen copy runs under /usr/bin/python3 -- no venv, no boto3. An import at module
    scope would make the watchdog unimportable on the machine it exists to protect."""
    source = (ROOT / "scripts" / "engine_failover.py").read_text(encoding="utf-8")
    imports = [ln for ln in source.splitlines()
               if ln.startswith(("import ", "from ")) and "boto3" in ln]
    assert not imports, imports
    assert ef.BACKUP_PY.name == "backup_store.py"


# ── the failover restores from the one that works ─────────────────────────────
def test_probe_standby_reports_what_the_bucket_holds(ef, monkeypatch):
    monkeypatch.setattr(ef, "backup_state", lambda: dict(STATE))
    out = ef.probe_standby()
    assert out["usable"] is True
    assert out["staleness_min"] == 30.0, out          # 0.5h, reported in minutes
    assert out["files"]["prospector.jsonl"]["bytes"] == 34687133
    assert out["files"]["prospector.db"]["key"] == "db/prospector-2026-08-21.db.gz"


def test_a_bucket_we_cannot_read_never_reports_usable(ef, monkeypatch):
    """`usable` is what do_failover branches on. Reporting True off an unreadable backup is
    how an operator learns at 4am that there was nothing to restore."""
    monkeypatch.setattr(ef, "backup_state", lambda: {"error": "no venv python at /nope"})
    out = ef.probe_standby()
    assert out["usable"] is False
    assert out["staleness_min"] == -1


def test_an_incomplete_backup_is_not_usable(ef, monkeypatch):
    """One of the two files missing means a failover cannot come up whole."""
    half = dict(STATE, db=None, complete=False)
    monkeypatch.setattr(ef, "backup_state", lambda: half)
    assert ef.probe_standby()["usable"] is False


def test_backup_state_shells_out_and_parses_the_json(ef, monkeypatch, tmp_path):
    fake_py = tmp_path / "python"
    fake_py.write_text("")
    monkeypatch.setattr(ef, "VENV_PY", fake_py)
    seen = {}

    def fake_sh(cmd, timeout=60):
        seen["cmd"] = cmd
        return 0, json.dumps(STATE), ""

    monkeypatch.setattr(ef, "sh", fake_sh)
    assert ef.backup_state()["complete"] is True
    assert "--money-state" in seen["cmd"], seen


def test_backup_state_reports_a_failure_instead_of_pretending(ef, monkeypatch, tmp_path):
    fake_py = tmp_path / "python"
    fake_py.write_text("")
    monkeypatch.setattr(ef, "VENV_PY", fake_py)
    monkeypatch.setattr(ef, "sh", lambda cmd, timeout=60: (1, "", "boom"))
    assert ef.backup_state()["error"] == "boom"


def test_restore_money_calls_the_backup_and_never_reimplements_it(ef, monkeypatch, tmp_path):
    fake_py = tmp_path / "python"
    fake_py.write_text("")
    monkeypatch.setattr(ef, "VENV_PY", fake_py)
    seen = {}

    def fake_sh(cmd, timeout=60):
        seen["cmd"] = cmd
        return 0, "STORE_BACKUP RESTORE_MONEY PASS ledger=x db=y\n", ""

    monkeypatch.setattr(ef, "sh", fake_sh)
    ok, detail = ef.restore_money(tmp_path / "dest")
    assert ok is True
    assert "RESTORE_MONEY PASS" in detail
    assert "--restore-money" in seen["cmd"], seen
    assert str(ef.BACKUP_PY) in seen["cmd"], seen

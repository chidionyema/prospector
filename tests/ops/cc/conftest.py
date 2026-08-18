"""Fixtures for control_center tests."""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

# Ensure the project root is on the Python path
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import prospector.ops.runner as _runner


@pytest.fixture(autouse=True)
def _isolate_runner_state(tmp_path, monkeypatch):
    """Point runner at a per-test temp jobs.json / runs dir.

    Without this, runner's module-level _JOBS_FILE and _RUNS_DIR would
    read/write the real store/control_center/ directory and leak state
    between tests.

    Teardown kills children AND waits briefly so daemon threads finish their
    final upsert against the *still-patched* temp path — never against
    production after monkeypatch unwinds.
    """
    cc = tmp_path / "control_center"
    cc.mkdir(parents=True, exist_ok=True)
    (cc / "runs").mkdir()
    monkeypatch.setattr(_runner, "_JOBS_FILE", cc / "jobs.json")
    monkeypatch.setattr(_runner, "_CC_DIR", cc)
    monkeypatch.setattr(_runner, "_RUNS_DIR", cc / "runs")
    _runner._RING_BUFFERS.clear()
    _runner._JOB_STATUS.clear()
    yield
    # Reap while paths are still patched (monkeypatch unwinds after this fixture).
    for j in list(_runner._load_jobs()):
        pid = j.get("pid")
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    # Give daemon threads a moment to observe wait() and upsert into the temp file.
    time.sleep(0.15)
    _runner._RING_BUFFERS.clear()
    _runner._JOB_STATUS.clear()

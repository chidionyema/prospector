"""Fixtures for control_center tests."""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import pytest

# Ensure the project root is on the Python path
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import prospector.control_center.runner as _runner


@pytest.fixture(autouse=True)
def _isolate_runner_state(tmp_path, monkeypatch):
    """Point runner at a per-test temp jobs.json / runs dir.

    Without this, runner's module-level _JOBS_FILE and _RUNS_DIR would
    read/write the real store/control_center/ directory and leak state
    between tests."""
    cc = tmp_path / "control_center"
    cc.mkdir(parents=True, exist_ok=True)
    (cc / "runs").mkdir()
    monkeypatch.setattr(_runner, "_JOBS_FILE", cc / "jobs.json")
    monkeypatch.setattr(_runner, "_CC_DIR", cc)
    monkeypatch.setattr(_runner, "_RUNS_DIR", cc / "runs")
    # Also clear the in-memory ring buffers + status map
    _runner._RING_BUFFERS.clear()
    _runner._JOB_STATUS.clear()
    yield
    # Reap any subprocesses this test spawned. The actuator-lock and cancel tests
    # launch `sleep(60)` children; without reaping they linger for 60s and their daemon
    # threads can write stale job state into a *later* test's jobs.json — the source of
    # the flaky cross-test failures and the suite timeout. _JOBS_FILE is still patched
    # to this test's temp file here (monkeypatch unwinds after fixture teardown).
    for j in _runner._load_jobs():
        pid = j.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    _runner._RING_BUFFERS.clear()
    _runner._JOB_STATUS.clear()

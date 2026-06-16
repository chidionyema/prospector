"""Behavioral tests for control_center.runner.

Tests the subprocess job manager: launch, cancel, status persistence, and
single-actuator concurrency.
"""
from __future__ import annotations

import json
import time

import pytest

import prospector.control_center.runner as runner


class TestLaunchPersist:
    """launch() must write a job to jobs.json and return a job_id."""

    def test_launch_returns_a_job_id(self, tmp_path):
        job_id = runner.launch(["echo", "hello"])
        assert job_id is not None
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_launch_writes_job_to_jobs_json(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        job_id = runner.launch(["echo", "test"])
        jobs = json.loads((cc / "jobs.json").read_text())
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == job_id
        assert jobs[0]["argv"] == ["echo", "test"]
        assert jobs[0]["status"] in ("queued", "running")

    def test_launch_creates_log_file(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "runs").mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        runner._RING_BUFFERS.clear()

        job_id = runner.launch(["python", "-c", "import time; time.sleep(0.2)"])
        time.sleep(0.8)  # let daemon thread write the log
        log_file = runner._RUNS_DIR / f"{job_id}.log"
        assert log_file.exists(), f"Log file not found at {log_file}"

    def test_launch_registers_pid_after_spawn(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        job_id = runner.launch(["python", "-c", "import time; time.sleep(0.5)"])
        # Wait a moment for the thread to start the subprocess
        time.sleep(0.3)
        jobs = json.loads((cc / "jobs.json").read_text())
        j = next(j for j in jobs if j["job_id"] == job_id)
        assert j["pid"] is not None


class TestCancel:
    """cancel_job() must mark the job cancelled in jobs.json."""

    def test_cancel_marks_job_cancelled(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        job_id = runner.launch(["python", "-c", "import time; time.sleep(60)"])
        # Wait for the log file to exist — means the daemon thread has fully started
        log_file = runner._RUNS_DIR / f"{job_id}.log"
        for _ in range(30):
            if log_file.exists():
                break
            time.sleep(0.1)
        runner.cancel_job(job_id)
        # cancel_job writes 'cancelled' synchronously to jobs.json before sending SIGTERM
        jobs = json.loads((cc / "jobs.json").read_text())
        j = next(j for j in jobs if j["job_id"] == job_id)
        assert j["status"] == "cancelled"


class TestLoadJobs:
    """load_jobs() must read jobs back from jobs.json and reap dead PIDs."""

    def test_load_jobs_returns_empty_list_when_no_jobs(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()

        jobs = runner.load_jobs()
        assert jobs == []

    def test_load_jobs_returns_saved_jobs(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        job_id = runner.launch(["echo", "persist"])
        jobs = runner.load_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == job_id

    def test_load_jobs_marks_dead_pids_unknown(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        # Manually write a dead job (PID that will never exist)
        jobs = [{
            "job_id": "fake_job",
            "pid": 999999,  # very unlikely to exist
            "argv": ["echo", "dead"],
            "start_ts": time.time() - 60,
            "status": "running",
            "log_file": str(cc / "runs" / "fake_job.log"),
        }]
        (cc / "jobs.json").write_text(json.dumps(jobs))
        (cc / "runs" / "fake_job.log").write_text("")

        loaded = runner.load_jobs()
        dead = next(j for j in loaded if j["job_id"] == "fake_job")
        assert dead["status"] == "unknown"


class TestSingleActuator:
    """Only one heavy run may be active at a time."""

    def test_second_launch_raises_runtime_error(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        # Start a long-running job
        job_id = runner.launch(["python", "-c", "import time; time.sleep(60)"])
        time.sleep(0.4)  # let it fully start

        # Attempt a second launch — must raise RuntimeError
        with pytest.raises(RuntimeError, match="already in progress"):
            runner.launch(["echo", "second"])


class TestGetLogLines:
    """get_log_lines() must return lines from ring buffer and/or on-disk log."""

    def test_get_log_lines_returns_empty_when_no_log(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()

        lines = runner.get_log_lines("nonexistent_job_id")
        assert lines == []

    def test_get_log_lines_returns_disk_lines(self, tmp_path, monkeypatch):
        cc = tmp_path / "cc"
        cc.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        (cc / "runs").mkdir()
        runner._RING_BUFFERS.clear()

        job_id = "disk_only_job"
        log_file = runner._RUNS_DIR / f"{job_id}.log"
        log_file.write_text("line one\nline two\nline three\n")

        lines = runner.get_log_lines(job_id)
        assert "line one" in lines
        assert "line two" in lines
        assert "line three" in lines

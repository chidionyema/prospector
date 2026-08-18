"""Regression: pytest/tmp ephemeral jobs must never drive the live cockpit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import prospector.ops.runner as runner
from prospector.ops.readers import watched_operators


class TestEphemeralJobFilter:
    def test_pytest_tmp_log_is_ephemeral(self):
        job = {
            "job_id": "20260730T185620386",
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "log_file": (
                "/private/var/folders/gq/x/T/pytest-of-chidionyema/"
                "pytest-37/test_second_launch_raises_runt0/cc/runs/x.log"
            ),
            "start_ts": 9999999999,
            "status": "failed",
        }
        assert runner.is_ephemeral_job(job) is True

    def test_dash_c_argv_is_ephemeral(self):
        job = {
            "job_id": "x",
            "argv": [sys.executable, "-c", "print(1)"],
            "log_file": "store/control_center/runs/x.log",
            "start_ts": 1,
            "status": "failed",
        }
        assert runner.is_ephemeral_job(job) is True

    def test_real_generate_job_not_ephemeral(self, tmp_path):
        # Use a path under cwd/store via monkeypatch-free relative path form.
        job = {
            "job_id": "20260730T184428678",
            "argv": [sys.executable, "-m", "prospector.run", "generate", "--candidates", "20"],
            "log_file": "store/control_center/runs/20260730T184428678.log",
            "start_ts": 100,
            "status": "failed",
        }
        assert runner.is_ephemeral_job(job) is False

    def test_filter_drops_pytest_keeps_real(self):
        jobs = [
            {
                "job_id": "junk",
                "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
                "log_file": "/private/var/folders/x/pytest-of-x/pytest-1/cc/runs/j.log",
                "start_ts": 200,
                "status": "failed",
            },
            {
                "job_id": "real",
                "argv": [sys.executable, "-m", "prospector.run", "generate", "--candidates", "20"],
                "log_file": "store/control_center/runs/real.log",
                "start_ts": 100,
                "status": "failed",
            },
        ]
        kept = runner.filter_production_jobs(jobs)
        assert len(kept) == 1
        assert kept[0]["job_id"] == "real"

class TestDaemonCannotClobberProduction:
    def test_upsert_uses_captured_jobs_file(self, tmp_path, monkeypatch):
        """Daemon path capture: final status lands in the temp file, not production."""
        cc = tmp_path / "cc"
        (cc / "runs").mkdir(parents=True)
        jobs_file = cc / "jobs.json"
        monkeypatch.setattr(runner, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(runner, "_CC_DIR", cc)
        monkeypatch.setattr(runner, "_RUNS_DIR", cc / "runs")
        runner._RING_BUFFERS.clear()
        runner._JOB_STATUS.clear()

        prod = Path("store/control_center/jobs.json")
        before = prod.read_text(encoding="utf-8") if prod.exists() else None

        job_id = runner.launch([sys.executable, "-c", "print('ok')"])
        # Wait for daemon to finish
        import time
        for _ in range(50):
            jobs = json.loads(jobs_file.read_text())
            j = next(x for x in jobs if x["job_id"] == job_id)
            if j.get("status") not in ("queued", "running"):
                break
            time.sleep(0.05)

        after = prod.read_text(encoding="utf-8") if prod.exists() else None
        assert after == before, "production jobs.json must be unchanged by test launch"
        assert job_id in jobs_file.read_text()


class TestWatchedOperatorsDedupe:
    def test_a_brain_on_both_chains_is_watched_once(self):
        # claude_cli is on BOTH chains after the 2026-08-06 cursor_cli removal, so this
        # dedupe is now load-bearing on the real config rather than a hypothetical.
        ops = watched_operators({
            "operator": ["claude_cli", "minimax"],
            "artifact_operator": ["claude_cli"],
        })
        assert ops.count("claude_cli") == 1
        assert "minimax" in ops
        assert "deepseek" in ops

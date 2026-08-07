"""Regression: CC jobs must survive parent/Streamlit death without Broken pipe."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import prospector.control_center.runner as runner

_CHILD_TICKER = r"""
import sys, time
# Mimic progress.py: write to stderr (CC redirects both to the log file).
for i in range(30):
    sys.stdout.write(f"out-{i}\n")
    sys.stdout.flush()
    sys.stderr.write(f"err-{i}\n")
    sys.stderr.flush()
    time.sleep(0.12)
sys.stdout.write("DONE\n")
sys.stdout.flush()
"""


class TestDetachedSpawnSurvivesParentDeath:
    def test_spawn_detached_no_pipe_and_log_grows_after_parent_closes_fd(
        self, tmp_path
    ):
        """Parent closes log FD immediately; child must keep writing (no EPIPE)."""
        log_file = tmp_path / "job.log"
        exit_file = tmp_path / "job.exit"
        argv = [sys.executable, "-c", _CHILD_TICKER]

        proc = runner.spawn_detached(argv, log_file, exit_file)
        assert proc.pid is not None
        # Parent must NOT hold a PIPE. stdout/stderr on Popen should be None/int
        # after spawn_detached closes the parent's FD copy.
        assert proc.stdout is None
        assert proc.stderr is None

        # Wait until the log has some content.
        size1 = 0
        for _ in range(50):
            if log_file.exists():
                size1 = log_file.stat().st_size
                if size1 > 20:
                    break
            time.sleep(0.1)
        assert size1 > 20, "child never wrote to log file"

        # Simulate Streamlit/parent death: drop Popen, abandon wait, GC the handle.
        pid = proc.pid
        # Closing any remaining refs must not kill a setsid child writing to a file.
        del proc

        time.sleep(0.8)
        assert runner._pid_alive(pid), "child died when parent dropped Popen handle"
        size2 = log_file.stat().st_size
        assert size2 > size1, "log must keep growing after parent abandoned the process"

        # Wait for completion.
        for _ in range(80):
            if not runner._pid_alive(pid):
                break
            time.sleep(0.1)

        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "Broken pipe" not in text
        assert "Errno 32" not in text
        assert "DONE" in text
        assert "err-0" in text  # stderr landed in the same file
        assert exit_file.exists()
        assert exit_file.read_text(encoding="utf-8").strip() == "0"

    def test_launch_survives_watcher_abandon(self, tmp_path, monkeypatch):
        """Full launch path: abandon LIVE_PROCS / ring like Streamlit restart."""
        cc = tmp_path / "cc"
        cc.mkdir()
        runs = cc / "runs"
        runs.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", runs)
        monkeypatch.setattr(runner, "_CC_DIR", cc)
        runner._RING_BUFFERS.clear()
        runner._LIVE_PROCS.clear()
        runner._JOB_STATUS.clear()

        job_id = runner.launch([sys.executable, "-c", _CHILD_TICKER])
        jobs = runner._load_jobs()
        j = next(x for x in jobs if x["job_id"] == job_id)
        pid = j["pid"]
        log_file = Path(j["log_file"])
        assert pid and runner._pid_alive(pid)

        # Wait for first bytes.
        for _ in range(50):
            if log_file.exists() and log_file.stat().st_size > 20:
                break
            time.sleep(0.1)
        size1 = log_file.stat().st_size
        assert size1 > 20

        # Simulate CC process death: drop live handles + ring (watcher may die too).
        runner._LIVE_PROCS.clear()
        runner._RING_BUFFERS.clear()

        time.sleep(0.9)
        assert runner._pid_alive(pid), "job must survive CC handle abandonment"
        size2 = log_file.stat().st_size
        assert size2 > size1, "log must grow without the CC watcher owning a pipe"

        # Poll finalize path (what Overview does on refresh after Streamlit restart).
        exit_file = runner._exit_file_for(log_file)
        for _ in range(100):
            if exit_file.exists() or not runner._pid_alive(pid):
                break
            time.sleep(0.1)
        assert exit_file.exists(), "wrapper must write .exit even after CC abandonment"
        loaded = runner.load_jobs()
        final = next(x for x in loaded if x["job_id"] == job_id)
        assert final["status"] == "succeeded", final
        assert final.get("exit_code") == 0
        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "Broken pipe" not in text
        assert "DONE" in text

    def test_progress_module_writes_survive_detach(self, tmp_path):
        """progress.step (stderr) must land in the log file under detached spawn."""
        log_file = tmp_path / "prog.log"
        exit_file = tmp_path / "prog.exit"
        code = r"""
import time
from prospector import progress
progress._QUIET = False
for i in range(8):
    progress.step(f"generated tick {i}")
    time.sleep(0.1)
progress.step("generated 20 candidates")
"""
        proc = runner.spawn_detached(
            [sys.executable, "-c", code],
            log_file,
            exit_file,
        )
        pid = proc.pid
        del proc
        for _ in range(80):
            if not runner._pid_alive(pid):
                break
            time.sleep(0.1)
        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "generated 20 candidates" in text
        assert "Broken pipe" not in text
        assert exit_file.read_text(encoding="utf-8").strip() == "0"

    def test_load_jobs_does_not_false_finalize_live_job(self, tmp_path, monkeypatch):
        """load_jobs must not mark a still-running detached job unknown/failed."""
        cc = tmp_path / "cc"
        cc.mkdir()
        runs = cc / "runs"
        runs.mkdir()
        monkeypatch.setattr(runner, "_JOBS_FILE", cc / "jobs.json")
        monkeypatch.setattr(runner, "_RUNS_DIR", runs)
        monkeypatch.setattr(runner, "_CC_DIR", cc)
        runner._RING_BUFFERS.clear()
        runner._LIVE_PROCS.clear()
        runner._JOB_STATUS.clear()

        job_id = runner.launch([
            sys.executable, "-c",
            "import time; time.sleep(8)",
        ])
        for _ in range(20):
            jobs = runner.load_jobs()
            j = next(x for x in jobs if x["job_id"] == job_id)
            assert j["status"] == "running", j
            assert j.get("pid") and runner._pid_alive(j["pid"])
            time.sleep(0.2)
        runner.cancel_job(job_id)

    def test_contrast_pipe_parent_death_would_break(self, tmp_path):
        """Sanity: a PIPE-backed child DOES get Broken pipe when parent closes — 
        documenting why we must never use PIPE for CC jobs."""
        log_probe = tmp_path / "pipe_child_out.txt"
        code = r"""
import sys, time
try:
    for i in range(40):
        print(f"p-{i}", flush=True)
        time.sleep(0.08)
    print("SURVIVED", flush=True)
except BrokenPipeError:
    sys.stderr = open(sys.argv[1], "w")
    print("HIT_BROKEN_PIPE", file=sys.stderr, flush=True)
    raise SystemExit(32)
except OSError as e:
    if e.errno == 32:
        sys.stderr = open(sys.argv[1], "w")
        print("HIT_EPIPE", file=sys.stderr, flush=True)
        raise SystemExit(32)
    raise
"""
        proc = __import__("subprocess").Popen(
            [sys.executable, "-u", "-c", code, str(log_probe)],
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").STDOUT,
            text=True,
        )
        # Read a little, then close the pipe (simulate Streamlit death).
        assert proc.stdout is not None
        proc.stdout.readline()
        proc.stdout.close()  # closes read end → next child write → EPIPE
        rc = proc.wait(timeout=10)
        # Child should have failed with our sentinel or been killed by SIGPIPE.
        assert rc != 0
        if log_probe.exists():
            assert "HIT_" in log_probe.read_text(encoding="utf-8")

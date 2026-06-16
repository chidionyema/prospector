"""Subprocess job manager for run.py invocations.

One active heavy run at a time (single-actuator lock). Job metadata is persisted
to store/control_center/jobs.json so history survives a Streamlit restart.

Ring buffer caps in-memory log lines at 2000 per job; full log always on disk.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Module-level singleton: in-memory ring buffers keyed by job_id
_RING_BUFFERS: dict[str, list[str]] = {}
_JOB_STATUS: dict[str, str] = {}  # job_id → canonical in-memory status
_RING_MAX = 2000
_JOBS_FILE = Path("store/control_center/jobs.json")
_CC_DIR = Path("store/control_center")
_RUNS_DIR = Path("store/control_center/runs")

# Grace period between SIGTERM and SIGKILL when cancelling a job.
_CANCEL_GRACE_SECONDS = 5

# Module-level lock for single-actuator concurrency
_ACTUATOR_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

def _load_jobs() -> list[dict[str, Any]]:
    if not _JOBS_FILE.exists():
        return []
    try:
        return json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_jobs(jobs: list[dict[str, Any]]) -> None:
    _CC_DIR.mkdir(parents=True, exist_ok=True)
    _JOBS_FILE.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")


def launch(argv: list[str]) -> str:
    """Launch run.py as a subprocess. Returns job_id. Blocks if a run is in flight.

    Raises RuntimeError if a job is already running.
    """
    with _ACTUATOR_LOCK:
        # Single-actuator: reject if a run is already running
        jobs = _load_jobs()
        for j in jobs:
            if j.get("status") == "running":
                raise RuntimeError("A run is already in progress. "
                                   "Cancel it before launching another.")

        job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}"
        start_ts = time.time()
        pid: int | None = None
        log_file = _RUNS_DIR / f"{job_id}.log"
        _RUNS_DIR.mkdir(parents=True, exist_ok=True)

        job = {
            "job_id": job_id,
            "pid": None,  # filled after Popen
            "argv": argv,
            "start_ts": start_ts,
            "status": "queued",
            "log_file": str(log_file),
            "elapsed_s": 0,
            "cost_usd": None,
            "exit_code": None,
        }
        jobs.append(job)
        _save_jobs(jobs)
        _RING_BUFFERS[job_id] = []
        _JOB_STATUS[job_id] = "queued"

        # Spawn subprocess in a daemon thread so this returns immediately
        thread = threading.Thread(target=_run_subprocess,
                                args=(job_id, argv, log_file), daemon=True)
        thread.start()

        return job_id


def _run_subprocess(job_id: str, argv: list[str], log_file: Path):
    """Internal: spawn run.py, stream stdout to ring buffer + disk."""
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr into stdout
        text=True,
        bufsize=1,  # line-buffered
    )

    # Update job with real PID — reuse the same jobs list throughout
    jobs = _load_jobs()
    target_job = None
    for j in jobs:
        if j.get("job_id") == job_id:
            j["pid"] = proc.pid
            j["status"] = "running"
            target_job = j
            break
    if target_job is None:
        return  # orphaned job (shouldn't happen)
    _save_jobs(jobs)

    buf = _RING_BUFFERS.get(job_id, [])
    log_handle = open(log_file, "w", encoding="utf-8")

    try:
        for line in proc.stdout or []:
            line = line.rstrip("\n")
            buf.append(line)
            if len(buf) > _RING_MAX:
                buf.pop(0)
            log_handle.write(line + "\n")
            log_handle.flush()
    finally:
        log_handle.close()

    exit_code = proc.wait()

    # Parse spend from log file
    cost_usd = _parse_spend_from_log(log_file)

    # Update job with final state.
    # Check _JOB_STATUS first — if cancel_job set 'cancelled', don't clobber it.
    if _JOB_STATUS.get(job_id) == "cancelled":
        target_job["status"] = "cancelled"
        _JOB_STATUS.pop(job_id, None)
    else:
        target_job["status"] = "deferred" if _was_deferred(log_file) else \
                              ("succeeded" if exit_code == 0 else "failed")
        _JOB_STATUS.pop(job_id, None)
    target_job["exit_code"] = exit_code
    target_job["elapsed_s"] = round(time.time() - target_job["start_ts"])
    target_job["cost_usd"] = cost_usd
    _save_jobs(jobs)


def _parse_spend_from_log(log_file: Path) -> float | None:
    """Extract spend from run log lines containing 'spend' events."""
    if not log_file.exists():
        return None
    total = 0.0
    for line in log_file.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            if d.get("event") == "spend":
                total += float(d.get("amount_usd", 0) or 0)
        except (json.JSONDecodeError, ValueError):
            # Try plain text: "spend $X.XX"
            import re
            m = re.search(r"[\$\£]\\s*([0-9.]+)", line)
            if m:
                total += float(m.group(1))
    return round(total, 4) if total else None


def _was_deferred(log_file: Path) -> bool:
    """Return True if the run ended with a moat_exhausted DEFER."""
    if not log_file.exists():
        return False
    text = log_file.read_text(encoding="utf-8").lower()
    return "moat_exhausted" in text or "defer" in text and "gate" not in text


def cancel_job(job_id: str) -> None:
    """Cancel a running job: SIGTERM → grace period → SIGKILL."""
    jobs = _load_jobs()
    for j in jobs:
        if j.get("job_id") != job_id:
            continue
        pid = j.get("pid")
        if pid is None:
            j["status"] = "cancelled"
            _JOB_STATUS[job_id] = "cancelled"
            _save_jobs(jobs)
            return

        j["status"] = "cancelled"
        _JOB_STATUS[job_id] = "cancelled"
        _save_jobs(jobs)


        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return  # already dead
        # Grace period: poll for a clean SIGTERM exit and escalate to SIGKILL only if
        # the process is still alive at the deadline. Returns as soon as the process is
        # gone, so a well-behaved process (and the test suite) never blocks for the full
        # grace window — and the UI thread that calls this isn't pinned for 5s.
        deadline = time.time() + _CANCEL_GRACE_SECONDS
        while time.time() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass  # already dead from SIGTERM


def get_log_lines(job_id: str, n: int = 200) -> list[str]:
    """Return the last N lines from the ring buffer + on-disk log."""
    buf = _RING_BUFFERS.get(job_id, [])
    log_file = _RUNS_DIR / f"{job_id}.log"
    disk_lines = []
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8").splitlines()
        disk_lines = lines[-n:] if len(lines) > n else lines
    combined = (buf[-n:] if len(buf) > n else buf) + disk_lines
    return list(dict.fromkeys(combined))[-n:]


def load_jobs() -> list[dict[str, Any]]:
    """Reload job list from disk, reaping dead PIDs."""
    jobs = _load_jobs()
    now = time.time()
    dirty = False
    for j in jobs:
        if j.get("status") == "running":
            pid = j.get("pid")
            if pid and not _pid_alive(pid):
                j["status"] = "unknown"
                dirty = True
    if dirty:
        _save_jobs(jobs)
    return sorted(jobs, key=lambda j: j.get("start_ts", 0), reverse=True)


def _pid_alive(pid: int) -> bool:
    """Return True if the PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

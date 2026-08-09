"""Subprocess job manager for run.py invocations.

One active heavy run at a time (single-actuator lock). Job metadata is persisted
to store/control_center/jobs.json so history survives a Streamlit restart.

Durability contract (do not break — operator #1 trust issue):
  - Child is spawned in a new session (setsid / start_new_session=True).
  - stdout AND stderr are real append FDs to store/control_center/runs/<id>.log
    opened BEFORE exec — NEVER a PIPE back to Streamlit/parent.
  - Parent closes its copy of the log FD immediately after spawn. Killing
    Streamlit / the watcher cannot SIGPIPE the job.
  - A thin wrapper writes <id>.exit with the return code so CC can finalize
    status on the next poll even if the host watcher died.
  - Watcher only tails the log file + polls PID; it is not required for the
    child to keep running or keep logging.

Path-isolation contract (do not break):
  Daemon threads capture jobs_file / runs_dir at launch time and ONLY write those
  paths. Monkeypatched pytest fixtures must not race with module-level restores —
  a stale in-memory jobs list must never overwrite production jobs.json.
"""
from __future__ import annotations

import errno
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

from prospector import paths

# Module-level singleton: in-memory ring buffers keyed by job_id
_RING_BUFFERS: dict[str, list[str]] = {}
_JOB_STATUS: dict[str, str] = {}  # job_id → canonical in-memory status
_RING_MAX = 2000
# Resolved per call, not bound at import (prospector/paths.py). The module-level names remain
# as overrides — `None` means "resolve now" — because tests/control_center/conftest.py pins all
# three with monkeypatch.setattr, and _runs_dir now DERIVES from _cc_dir so redirecting the
# directory cannot leave one of its children pointing at production.
_JOBS_FILE: Path | None = None
_CC_DIR: Path | None = None
_RUNS_DIR: Path | None = None


def _cc_dir() -> Path:
    return _CC_DIR or paths.store_path("control_center")


def _jobs_file() -> Path:
    return _JOBS_FILE or _cc_dir() / "jobs.json"


def _runs_dir() -> Path:
    return _RUNS_DIR or _cc_dir() / "runs"

# Grace period between SIGTERM and SIGKILL when cancelling a job.
_CANCEL_GRACE_SECONDS = 5

# Module-level lock for single-actuator concurrency
_ACTUATOR_LOCK = threading.Lock()
_JOBS_IO_LOCK = threading.Lock()

# Live Popen handles (optional — watcher may use these; GC must not kill children).
_LIVE_PROCS: dict[str, subprocess.Popen] = {}

# Wrapper records exit code to a sidecar so finalize works after parent death.
# stdout/stderr are already redirected to the run log by Popen — progress.print
# and engine prints land in the file with no PIPE to Streamlit.
_EXIT_WRAPPER = r"""
import sys, subprocess
from pathlib import Path
exit_path = Path(sys.argv[1])
cmd = sys.argv[2:]
rc = 1
try:
    rc = int(subprocess.call(cmd))
except Exception as e:
    try:
        sys.stderr.write(f"[cc-wrapper] exec failed: {e!r}\n")
        sys.stderr.flush()
    except Exception:
        pass
    rc = 127
finally:
    try:
        exit_path.write_text(str(rc), encoding="utf-8")
    except OSError:
        pass
raise SystemExit(rc)
"""


# ---------------------------------------------------------------------------
# Path helpers / production guards
# ---------------------------------------------------------------------------

def _production_jobs_file() -> Path:
    return paths.store_path("control_center", "jobs.json").resolve()


def is_ephemeral_job(job: dict[str, Any]) -> bool:
    """True for pytest/tmp sleep jobs that must never drive the live cockpit."""
    argv = job.get("argv") or []
    # `-c` may sit after `-u` once we inject unbuffered mode.
    if "-c" in list(argv[:5]):
        return True
    log_file = str(job.get("log_file") or "")
    lowered = log_file.lower()
    markers = (
        "pytest-",
        "/pytest-of-",
        "/tmp/pytest",
        "/private/var/folders/",
        "\\pytest-",
    )
    if any(m in lowered for m in markers):
        return True
    # Absolute log outside repo store/ is not a production CC run.
    if log_file:
        try:
            p = Path(log_file)
            if p.is_absolute():
                store_runs = paths.store_path("control_center", "runs").resolve()
                try:
                    p.resolve().relative_to(store_runs)
                except ValueError:
                    cwd_store = (Path.cwd() / "store" / "control_center" / "runs").resolve()
                    try:
                        p.resolve().relative_to(cwd_store)
                    except ValueError:
                        return True
        except OSError:
            return True
    return False


def filter_production_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop ephemeral/pytest junk so Overview/Launch never treat them as live state."""
    return [j for j in jobs if not is_ephemeral_job(j)]


def _looks_like_pytest_path(path: Path) -> bool:
    s = str(path).lower()
    return any(m in s for m in ("pytest-", "/pytest-of-", "/tmp/pytest"))


# ---------------------------------------------------------------------------
# Job persistence (merge-safe)
# ---------------------------------------------------------------------------

def _load_jobs_from(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _load_jobs() -> list[dict[str, Any]]:
    return _load_jobs_from(_jobs_file())


def _save_jobs_to(path: Path, jobs: list[dict[str, Any]]) -> None:
    """Write jobs list to ``path``. Refuses to clobber production with pytest paths."""
    path = Path(path)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    prod = _production_jobs_file()
    if resolved == prod:
        if _looks_like_pytest_path(path):
            return
        on_disk = _load_jobs_from(path)
        by_id = {j["job_id"]: j for j in filter_production_jobs(on_disk) if j.get("job_id")}
        for j in filter_production_jobs(jobs):
            jid = j.get("job_id")
            if jid:
                by_id[jid] = j
        jobs = list(by_id.values())

    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic, because this file has concurrent readers BY DESIGN: the per-job monitor daemon
    # thread upserts status here (:388) while the CLI, the tests and the Streamlit cockpit read
    # it. `write_text` truncates first, so a reader landing in that window gets an empty file —
    # measured 1636 empty and 8 partial reads out of 20000 against a concurrent writer. The
    # reader swallows it (`_load_jobs_from` returns [] on JSONDecodeError), so the symptom is
    # not a crash but jobs silently vanishing from the cockpit for one poll.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)  # rename is atomic within a filesystem: readers see old or new
    finally:
        tmp.unlink(missing_ok=True)


def _save_jobs(jobs: list[dict[str, Any]]) -> None:
    _cc_dir().mkdir(parents=True, exist_ok=True)
    _save_jobs_to(_jobs_file(), jobs)


def _upsert_job(jobs_file: Path, job_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Reload from disk, merge updates into one job, save. Returns updated job or None."""
    with _JOBS_IO_LOCK:
        jobs = _load_jobs_from(jobs_file)
        target = None
        for j in jobs:
            if j.get("job_id") == job_id:
                j.update(updates)
                target = j
                break
        if target is None:
            return None
        _save_jobs_to(jobs_file, jobs)
        return target


# ---------------------------------------------------------------------------
# Detached spawn (file FDs, new session — never PIPE)
# ---------------------------------------------------------------------------

def _ensure_unbuffered_python(argv: list[str]) -> list[str]:
    """Insert ``-u`` after a Python executable so run logs flush line-by-line."""
    if not argv:
        return list(argv)
    out = list(argv)
    exe = Path(out[0]).name.lower()
    is_python = (
        out[0] == sys.executable
        or exe.startswith("python")
        or exe in ("python", "python3")
    )
    if not is_python:
        return out
    for tok in out[1:4]:
        if tok == "-u" or (tok.startswith("-") and not tok.startswith("--") and "u" in tok):
            return out
        if tok in ("-m", "-c"):
            break
    out.insert(1, "-u")
    return out


def _exit_file_for(log_file: Path) -> Path:
    return log_file.with_suffix(".exit")


def _read_exit_code(exit_file: Path) -> int | None:
    if not exit_file.exists():
        return None
    try:
        return int(exit_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def spawn_detached(
    argv: list[str],
    log_file: Path,
    exit_file: Path | None = None,
) -> subprocess.Popen:
    """Spawn ``argv`` fully detached with stdout/stderr = append FDs to ``log_file``.

    - New session (setsid) — no controlling terminal; survives parent SIGHUP.
    - Log FD opened in the parent then inherited; parent closes its copy so
      parent death cannot close the child's only writer via a PIPE.
    - Never uses subprocess.PIPE.
    - Writes return code to ``exit_file`` via a thin wrapper.
    """
    argv = _ensure_unbuffered_python(list(argv))
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if exit_file is None:
        exit_file = _exit_file_for(log_file)
    else:
        exit_file = Path(exit_file)
    # Fresh log for this job id; then open append FD for the child.
    with open(log_file, "w", encoding="utf-8"):
        pass
    if exit_file.exists():
        try:
            exit_file.unlink()
        except OSError:
            pass

    log_fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Drop terminal-oriented hints that encourage interactive/TTY assumptions.
    env.pop("TERM", None)

    wrapped = [
        sys.executable, "-u", "-c", _EXIT_WRAPPER,
        str(exit_file),
        *argv,
    ]
    try:
        proc = subprocess.Popen(
            wrapped,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        # Critical: release parent's FD. Child retains its dup'd stdout/stderr.
        # If we kept a PIPE or held the only writer and died, child would get EPIPE.
        try:
            os.close(log_fd)
        except OSError:
            pass
    return proc


def _status_from_exit(exit_code: int | None, log_file: Path, cancelled: bool) -> str:
    if cancelled:
        return "cancelled"
    if exit_code is None:
        return "unknown"
    if exit_code == 0:
        return "deferred" if _was_deferred(log_file) else "succeeded"
    return "deferred" if _was_deferred(log_file) else "failed"


def _finalize_job(
    jobs_file: Path,
    job_id: str,
    *,
    log_file: Path,
    exit_file: Path,
    start_ts: float,
    pid: int | None,
) -> str:
    """Mark a dead/finished job in jobs.json. Idempotent."""
    # Cancel may have been written by another process (CC UI / CLI cancel_job);
    # the detached supervisor has an empty in-memory _JOB_STATUS and must honor disk.
    cancelled = _JOB_STATUS.get(job_id) == "cancelled"
    if not cancelled:
        try:
            for j in _load_jobs_from(jobs_file):
                if j.get("job_id") == job_id and j.get("status") == "cancelled":
                    cancelled = True
                    break
        except Exception:
            pass
    exit_code = _read_exit_code(exit_file)

    proc = _LIVE_PROCS.pop(job_id, None)
    if proc is not None:
        try:
            rc = proc.poll()
            if rc is None and not exit_file.exists():
                # Still running — do not finalize.
                _LIVE_PROCS[job_id] = proc
                return "running"
            if rc is None:
                try:
                    rc = proc.wait(timeout=2)
                except Exception:
                    rc = proc.poll()
            if rc is not None and exit_code is None:
                exit_code = int(rc)
        except Exception:
            pass

    if pid is not None:
        reaped = _reap_if_child(pid)
        if reaped is not None and exit_code is None:
            exit_code = reaped

    if not _job_complete(pid, exit_file):
        # Put Popen back if we raced.
        if proc is not None and proc.poll() is None:
            _LIVE_PROCS[job_id] = proc
        return "running"

    # One more moment for the wrapper to flush .exit after reaping.
    if exit_code is None:
        for _ in range(10):
            exit_code = _read_exit_code(exit_file)
            if exit_code is not None:
                break
            time.sleep(0.05)

    status = _status_from_exit(exit_code, log_file, cancelled)
    _JOB_STATUS.pop(job_id, None)
    cost_usd = _parse_spend_from_log(log_file)
    _upsert_job(jobs_file, job_id, {
        "status": status,
        "exit_code": exit_code,
        "elapsed_s": round(time.time() - float(start_ts or time.time())),
        "cost_usd": cost_usd,
        "pid": None,
    })
    return status


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

def launch(argv: list[str]) -> str:
    """Launch run.py as a detached subprocess. Returns job_id.

    Spawns the child *synchronously* before return so a one-shot CLI launcher
    cannot exit before the job exists. Raises RuntimeError if a job is already
    running.
    """
    with _ACTUATOR_LOCK:
        jobs_file = Path(_jobs_file())
        runs_dir = Path(_runs_dir())
        cc_dir = Path(_cc_dir())

        jobs = _load_jobs_from(jobs_file)
        try:
            writing_prod = jobs_file.resolve() == _production_jobs_file()
        except OSError:
            writing_prod = False
        for j in jobs:
            if j.get("status") != "running":
                continue
            if writing_prod and is_ephemeral_job(j):
                continue
            pid = j.get("pid")
            job_id_existing = j.get("job_id") or ""
            log_p = Path(j.get("log_file") or (runs_dir / f"{job_id_existing}.log"))
            exit_p = _exit_file_for(log_p)
            # Reap stale "running" rows whose child has finished (incl. zombies).
            if pid and _job_complete(int(pid), exit_p):
                _finalize_job(
                    jobs_file, job_id_existing,
                    log_file=log_p,
                    exit_file=exit_p,
                    start_ts=float(j.get("start_ts") or time.time()),
                    pid=int(pid),
                )
                continue
            if pid and _pid_alive(int(pid)):
                raise RuntimeError("A run is already in progress. "
                                   "Cancel it before launching another.")
            # status=running but no live pid — clear the wedge.
            _upsert_job(jobs_file, job_id_existing, {
                "status": "failed",
                "pid": None,
                "note": "stale running row with no live pid",
            })
            continue

        display_argv = _ensure_unbuffered_python(list(argv))
        job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}"
        start_ts = time.time()
        log_file = runs_dir / f"{job_id}.log"
        exit_file = _exit_file_for(log_file)
        runs_dir.mkdir(parents=True, exist_ok=True)
        cc_dir.mkdir(parents=True, exist_ok=True)

        try:
            log_file_str = str(log_file.resolve())
        except OSError:
            log_file_str = str(log_file)

        job = {
            "job_id": job_id,
            "pid": None,
            "argv": display_argv,
            "start_ts": start_ts,
            "status": "queued",
            "log_file": log_file_str,
            "elapsed_s": 0,
            "cost_usd": None,
            "exit_code": None,
        }
        jobs.append(job)
        _save_jobs_to(jobs_file, jobs)
        _RING_BUFFERS[job_id] = []
        _JOB_STATUS[job_id] = "queued"

        # Spawn BEFORE returning — child must outlive this function / Streamlit.
        try:
            proc = spawn_detached(display_argv, log_file, exit_file)
        except Exception as e:
            _upsert_job(jobs_file, job_id, {
                "status": "failed",
                "exit_code": None,
                "note": f"spawn failed: {e!r}",
                "pid": None,
            })
            raise

        _LIVE_PROCS[job_id] = proc
        if _upsert_job(jobs_file, job_id, {
            "pid": proc.pid,
            "status": "running",
        }) is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            _LIVE_PROCS.pop(job_id, None)
            return job_id

        thread = threading.Thread(
            target=_watch_job,
            args=(job_id, proc.pid, log_file, exit_file, jobs_file, start_ts),
            daemon=True,
            name=f"cc-watch-{job_id}",
        )
        thread.start()
        # Detached supervisor outlives Streamlit — finalizes jobs.json when the
        # child exits even if every CC thread/process is gone.
        _spawn_status_supervisor(
            jobs_file=jobs_file,
            job_id=job_id,
            pid=proc.pid,
            log_file=log_file,
            exit_file=exit_file,
            start_ts=start_ts,
        )
        return job_id


_SUPERVISOR = r"""
import sys, time
from pathlib import Path

# Durable finalize loop — no PIPE, no Streamlit dependency.
sys.path.insert(0, sys.argv[1])
from prospector.control_center.runner import (  # noqa: E402
    _finalize_job, _job_complete,
)

root, jobs_file, job_id, pid_s, log_file, exit_file, start_ts_s = sys.argv[1:8]
pid = int(pid_s)
start_ts = float(start_ts_s)
jobs_path = Path(jobs_file)
log_path = Path(log_file)
exit_path = Path(exit_file)
while True:
    if _job_complete(pid, exit_path):
        _finalize_job(
            jobs_path, job_id,
            log_file=log_path,
            exit_file=exit_path,
            start_ts=start_ts,
            pid=pid,
        )
        break
    time.sleep(1.0)
"""


def _spawn_status_supervisor(
    *,
    jobs_file: Path,
    job_id: str,
    pid: int,
    log_file: Path,
    exit_file: Path,
    start_ts: float,
) -> None:
    """Spawn a setsid supervisor that only polls PID / ``.exit`` and finalizes."""
    # runner.py → control_center → prospector → repo root
    root = str(Path(__file__).resolve().parent.parent.parent)
    try:
        jobs_s = str(Path(jobs_file).resolve())
    except OSError:
        jobs_s = str(jobs_file)
    argv = [
        sys.executable, "-u", "-c", _SUPERVISOR,
        root,
        jobs_s,
        job_id,
        str(pid),
        str(log_file),
        str(exit_file),
        str(start_ts),
    ]
    try:
        log_fd = os.open(str(log_file.with_suffix(".supervisor.log")),
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError:
        log_fd = subprocess.DEVNULL
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log_fd if log_fd != subprocess.DEVNULL else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_fd != subprocess.DEVNULL else subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            cwd=root,
        )
    finally:
        if log_fd != subprocess.DEVNULL:
            try:
                os.close(log_fd)
            except OSError:
                pass


def _watch_job(
    job_id: str,
    pid: int,
    log_file: Path,
    exit_file: Path,
    jobs_file: Path,
    start_ts: float,
) -> None:
    """Best-effort live tail + finalize. Job does NOT depend on this thread."""
    buf = _RING_BUFFERS.setdefault(job_id, [])
    offset = 0
    try:
        while True:
            # Tail new bytes from the on-disk log (child owns the write FD).
            try:
                if log_file.exists():
                    data = log_file.read_bytes()
                    if len(data) > offset:
                        chunk = data[offset:].decode("utf-8", errors="replace")
                        offset = len(data)
                        for line in chunk.splitlines():
                            buf.append(line)
                            if len(buf) > _RING_MAX:
                                buf.pop(0)
            except OSError:
                pass

            if _job_complete(pid, exit_file):
                for _ in range(20):
                    if exit_file.exists():
                        break
                    time.sleep(0.05)
                _finalize_job(
                    jobs_file, job_id,
                    log_file=log_file,
                    exit_file=exit_file,
                    start_ts=start_ts,
                    pid=pid,
                )
                return

            time.sleep(0.25)
    except Exception:
        # Watcher death must never be coupled to the child. Finalize on next poll.
        return


def cancel_job(job_id: str) -> None:
    """Cancel a running job: SIGTERM process group → grace → SIGKILL."""
    jobs_file = Path(_jobs_file())
    jobs = _load_jobs_from(jobs_file)
    for j in jobs:
        if j.get("job_id") != job_id:
            continue
        pid = j.get("pid")
        _JOB_STATUS[job_id] = "cancelled"
        _upsert_job(jobs_file, job_id, {"status": "cancelled"})

        if pid is None:
            return

        def _kill(sig: int) -> None:
            try:
                os.killpg(int(pid), sig)
            except OSError:
                try:
                    os.kill(int(pid), sig)
                except OSError:
                    pass

        _kill(signal.SIGTERM)
        deadline = time.time() + _CANCEL_GRACE_SECONDS
        while time.time() < deadline:
            if not _pid_alive(int(pid)):
                return
            time.sleep(0.05)
        _kill(signal.SIGKILL)
        return


def _resolve_log_file(job_id: str) -> Path:
    """Prefer the absolute ``log_file`` recorded in jobs.json; fall back to runs dir."""
    for j in _load_jobs():
        if j.get("job_id") != job_id:
            continue
        raw = j.get("log_file") or ""
        if raw:
            p = Path(raw)
            if p.exists():
                return p
        break
    return _runs_dir() / f"{job_id}.log"


def get_log_lines(job_id: str, n: int = 200) -> list[str]:
    """Return the last N lines for a job. Disk is authoritative after restart."""
    buf = _RING_BUFFERS.get(job_id, [])
    log_file = _resolve_log_file(job_id)
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines:
                return lines[-n:] if len(lines) > n else lines
        except OSError:
            pass
    return buf[-n:] if len(buf) > n else list(buf)


def load_jobs() -> list[dict[str, Any]]:
    """Reload job list from disk, finalizing dead PIDs via exit sidecars."""
    jobs = _load_jobs()
    dirty = False
    for j in jobs:
        status = j.get("status")
        if status not in ("running", "queued"):
            continue
        pid = j.get("pid")
        job_id = j.get("job_id") or ""
        log_file = Path(j.get("log_file") or (_runs_dir() / f"{job_id}.log"))
        exit_file = _exit_file_for(log_file)

        if status == "queued" and pid is None:
            # Spawn never happened (old daemon-thread race). Don't leave it wedged.
            if time.time() - float(j.get("start_ts") or 0) > 15:
                j["status"] = "failed"
                j["note"] = "spawn never registered a pid (launcher died early)"
                dirty = True
            continue

        if pid and _job_complete(int(pid), exit_file):
            new_status = _finalize_job(
                Path(_jobs_file()), job_id,
                log_file=log_file,
                exit_file=exit_file,
                start_ts=float(j.get("start_ts") or time.time()),
                pid=int(pid),
            )
            if new_status != "running":
                dirty = True

    # Reload after finalizes
    if dirty:
        jobs = _load_jobs()

    prod = _production_jobs_file()
    try:
        writing_prod = Path(_jobs_file()).resolve() == prod
    except OSError:
        writing_prod = False

    if writing_prod:
        cleaned = filter_production_jobs(jobs)
        if len(cleaned) != len(jobs):
            jobs = cleaned
            _save_jobs(jobs)

    visible = filter_production_jobs(jobs) if writing_prod else jobs
    return sorted(visible, key=lambda j: j.get("start_ts", 0), reverse=True)


def _parse_spend_from_log(log_file: Path) -> float | None:
    """Extract spend from run log lines containing 'spend' events."""
    if not log_file.exists():
        return None
    total = 0.0
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("event") == "spend":
                total += float(d.get("amount_usd", 0) or 0)
        except (json.JSONDecodeError, ValueError):
            import re
            m = re.search(r"[\$\£]\\s*([0-9.]+)", line)
            if m:
                total += float(m.group(1))
    return round(total, 4) if total else None


def _was_deferred(log_file: Path) -> bool:
    """Return True if the run ended with a moat_exhausted DEFER."""
    if not log_file.exists():
        return False
    text = log_file.read_text(encoding="utf-8", errors="replace").lower()
    return "moat_exhausted" in text or ("defer" in text and "gate" not in text)


def _pid_alive(pid: int | None) -> bool:
    """Return True if the PID exists (including when we lack permission / EPERM)."""
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError as e:
        # EPERM ⇒ process exists but signal not permitted — still alive.
        return getattr(e, "errno", None) == errno.EPERM
    # Reap zombies we own so a dead child is not reported as alive forever.
    if _reap_if_child(int(pid)) is not None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as e:
        return getattr(e, "errno", None) == errno.EPERM


def _reap_if_child(pid: int) -> int | None:
    """Non-blocking waitpid if ``pid`` is our child. Returns exit code or None."""
    try:
        wpid, status = os.waitpid(int(pid), os.WNOHANG)
    except ChildProcessError:
        return None
    except OSError:
        return None
    if wpid == 0:
        return None
    if os.WIFEXITED(status):
        return int(os.WEXITSTATUS(status))
    if os.WIFSIGNALED(status):
        return int(128 + os.WTERMSIG(status))
    return None


def _job_complete(pid: int | None, exit_file: Path) -> bool:
    """True when the wrapper has finished.

    Prefer the ``.exit`` sidecar (survives reparent-to-init). A live ``kill(pid,0)``
    always means *not* complete — even if waitpid returned something surprising.
    Only ESRCH (process gone) counts as completion without a sidecar. EPERM and
    other errors must NOT finalize (that false-marked a live generate as unknown).
    """
    if exit_file.exists():
        return True
    if pid is None:
        return False
    # Best-effort reap so zombies become ESRCH on the probe below.
    _reap_if_child(pid)
    try:
        os.kill(int(pid), 0)
        return False  # process table entry still present
    except ProcessLookupError:
        return True
    except OSError:
        return False


def sweep_old_logs(retain_days: int = 30) -> int:
    """CC go-live task #4 — prune run logs older than `retain_days`."""
    if not _runs_dir().exists():
        return 0

    cutoff = time.time() - (retain_days * 86400)
    removed = 0
    for log_file in _runs_dir().glob("*.log"):
        try:
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                removed += 1
                exit_side = _exit_file_for(log_file)
                if exit_side.exists():
                    exit_side.unlink()
        except OSError:
            pass
    return removed

"""Batch driver for tools/backfill_missing_listings.sh.

Was an inline heredoc, which made it untestable and — more importantly — unkillable in a
predictable way: a killed batch and a finished batch were the same event to the loop, so
terminating a child just advanced it to the next one. The two rules that fix that are here:

  * a signal sets `_stop` and terminates the running child, and the loop then EXITS;
  * a child killed by a signal (negative returncode) is fatal, while an ordinary non-zero
    exit is not — `publish_passes` legitimately returns 1 when every pack in a batch was
    held back by the completeness gate, and that must not abort the remaining batches.

Restart-safety is unchanged: the missing list is re-derived on every run and the per-batch
existence check re-runs, so anything that already has a listing is skipped.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Aliased: this module uses `paths` as a local variable name in two functions, and a bare
# `from prospector import paths` would read as though those locals shadowed the module.
from prospector import paths as _paths  # noqa: E402

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

# Each batch is a fresh `tools.publish_passes` process, so a small batch pays full
# interpreter + config + store startup per pack and cannot overlap CLI work across the
# boundary. 5 widens the window in which the shared CLI slots stay busy.
BATCH_SIZE = 5

EXIT_ALREADY_RUNNING = 3
# Resolved per call, not bound at import (prospector/paths.py): a cwd-relative lock file is a
# lock that only excludes processes started from the same directory, which is the one guarantee
# a lock must not have. `None` means "resolve now"; assigning a Path pins it.
LOCK_PATH: Path | None = None


def _lock_path() -> Path:
    return LOCK_PATH or _paths.store_path(".backfill_listings.lock")

_stop = False
_child: subprocess.Popen | None = None
_lock_handle = None  # module-level so the fd stays open for the process lifetime


def _acquire_single_instance() -> bool:
    """Refuse to start when another backfill holds the lock.

    Uses fcntl.flock rather than the flock(1) command — the utility does NOT exist on macOS,
    which is this project's host, so a shell-level lock would have made the backfill refuse
    to start every single time. The kernel drops this lock when the process dies for any
    reason, including SIGKILL, so a crashed run can never leave a stale lock behind.
    """
    global _lock_handle
    if fcntl is None:
        print("WARNING no fcntl — single-instance lock disabled", flush=True)
        return True
    _lock_path().parent.mkdir(parents=True, exist_ok=True)
    _lock_handle = open(_lock_path(), "w")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _lock_handle.close()
        _lock_handle = None
        return False
    return True


def _handle_signal(signum, _frame):
    global _stop
    _stop = True
    print(f"signal {signum} received — terminating current batch and stopping", flush=True)
    if _child is not None and _child.poll() is None:
        _child.terminate()


def _pending() -> list[str]:
    """PASS dossiers with no listing receipt yet."""
    paths: list[str] = []
    for f in sorted(_paths.store_path("dossiers").glob("*.pass.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(d.get("decision", "")).lower() != "pass" or d.get("provisional"):
            continue
        cid = (d.get("candidate") or {}).get("candidate_id") or f.stem.split(".")[0]
        if _paths.store_path("listings", f"{cid}.json").exists():
            continue
        paths.append(str(f))
    return paths


def _listing_count() -> int:
    return len(list(_paths.store_path("listings").glob("*.json")))


def main(argv: list[str]) -> int:
    global _child
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not _acquire_single_instance():
        print(f"backfill already running (lock: {_lock_path()}) — refusing to start a second one",
              flush=True)
        return EXIT_ALREADY_RUNNING

    extra = list(argv)  # forwarded to publish_passes, e.g. --reuse-artifacts

    # A pack that was mid-publish when a previous run died may be live in the catalog with no
    # local receipt, in which case it looks "missing" here and would be published twice.
    inflight = _paths.store_path("listings", ".inflight")
    stale = sorted(p.stem for p in inflight.glob("*.json")) if inflight.is_dir() else []
    if stale:
        print(f"WARNING unreconciled={stale} — these were interrupted mid-publish and may "
              f"already be live in the catalog; verify before trusting the missing count",
              flush=True)

    paths = _pending()
    print(f"missing={len(paths)}", flush=True)
    total_batches = (len(paths) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(paths), BATCH_SIZE):
        if _stop:
            print("stopped before next batch", flush=True)
            return 130
        batch = [
            p for p in paths[i:i + BATCH_SIZE]
            if not _paths.store_path("listings",
                                     f"{Path(p).name.replace('.pass.json', '')}.json").exists()
        ]
        if not batch:
            continue
        print(f"batch {i // BATCH_SIZE + 1}/{total_batches}: {batch}", flush=True)
        _child = subprocess.Popen(
            [sys.executable, "-u", "-m", "tools.publish_passes", *extra, *batch],
            cwd=str(_paths.repo_root()),
        )
        rc = _child.wait()
        _child = None
        print(f"exit={rc} listings_now={_listing_count()}", flush=True)

        if rc < 0 or _stop:
            # Negative rc means the batch was killed by a signal. Continuing here is exactly
            # the bug that made this script survive three rounds of kill attempts.
            print(f"batch terminated by signal {-rc if rc < 0 else ''} — stopping", flush=True)
            return 130
        # rc > 0 is NOT fatal: publish_passes returns 1 when a batch listed nothing because
        # every pack was held back by the completeness gate. Later batches may still list.

    print("backfill_missing_listings done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

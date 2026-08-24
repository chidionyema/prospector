"""Slow console reads are served from a snapshot, and refreshed off the page load.

MEASURED 2026-08-21, every one of the 38 views in `console_api.READS`, on the laptop, with the
libyaml loader already in place:

    median              0.83s
    34 of 38 views     under 2s
    drain               2.84s
    automations        10.16s
    deploys            12.45s
    processes         >125s   -- never returns

`OPS_READ_TIMEOUT_MS` is 120_000 (`src/lib/ops.ts:61`), so `processes` did not merely feel slow.
It could not succeed. `scripts/process_audit.py --json` takes 141.8s (34.6s user, 28.8s system,
44% CPU -- most of the wall clock is network wait), which is past the ceiling, so that panel spun
for two minutes and reported a gateway timeout every single time, while the panel beside it
answered in a quarter of a second.

That spread is the founder's word for this portal on 2026-08-21: "it is inconsistent".

The three slow views have one thing in common and it is not their code. They each ask other
people's services: Fly for the app list and a machine's status, GitHub for runners and workflow
runs, a `git fetch` per checkout, an HTTP probe per deployable. Dozens of network round trips,
serially. No amount of local optimisation makes that a page-load-time computation, and pretending
otherwise is what produced a page that cannot load.

So a read serves the last answer and says how old it is, and the refresh happens where it is
allowed to take three minutes.

WHAT THIS DELIBERATELY DOES NOT DO. It does not hide the age. Every payload carries `captured_at`,
`age_s` and `stale`, and the page prints them. An estate audit presented as current when it is
forty minutes old is worse than the slow page it replaced -- somebody acts on it. The rule here is
the same one the rest of this repo runs on: state is a probe, and a probe that answers from cache
says so.

Three entry points:

- `serve(view)` -- what a console READ calls. Disk only, no network. If what it found is stale it
  starts a detached refresh so the next visit is current, and returns immediately either way.
- `refresh(view)` -- run the producer for real and write the snapshot. What the console ACTION
  calls; the act path allows 1_860_000 ms, so 141.8s fits with room to spare.
- `python -m prospector.ops.slow_read <view>` -- one refresh, prints a receipt. This is what the
  detached child runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from prospector.config import store_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def _produce_processes(cfg: Any) -> Any:
    """`scripts/process_audit.py --json`, measured at 141.8s.

    The exit code decides nothing. That script exits 1 whenever anything on the estate is
    failing, which is the normal state and exactly what the page exists to show.
    """
    return _run_json_script("scripts/process_audit.py", timeout=300)


def _produce_deploys(cfg: Any) -> Any:
    """`scripts/deploy_status.py --json`, measured at 12.45s, plus the console's route columns.

    Same rule on the exit code: 1 means something is STALLED and 2 means something could not be
    measured, and both of those are the answer rather than a failure to read.
    """
    from . import console_api

    view = _run_json_script("scripts/deploy_status.py", timeout=300)
    for row in view.get("deployables", []):
        name = str(row.get("name") or "")
        row.update(console_api._deploy_route(name))
        row.update(console_api._rollback_route(name))
    return view


def _produce_automations(cfg: Any) -> Any:
    """`automations_view.read_automations`, measured at 10.16s. It runs every automation for real."""
    from .automations_view import read_automations

    return read_automations(cfg, {})


#: view name -> (producer, seconds before a read asks for a background refresh)
#:
#: The staleness windows are not round numbers chosen for tidiness. Each is how long the thing
#: being graded actually takes to change: launchd jobs, Fly machines and CI runners do not move
#: faster than a quarter of an hour, a deploy can land at any minute so its window is the
#: shortest, and the automations are cron-driven at five minutes and up.
PRODUCERS: dict[str, tuple[Callable[[Any], Any], float]] = {
    "processes": (_produce_processes, 900.0),
    "deploys": (_produce_deploys, 240.0),
    "automations": (_produce_automations, 300.0),
}

#: A refresh that has not finished in this long is dead: the machine slept, the process was
#: killed, the container was replaced. The lock is reclaimed rather than blocking forever.
LOCK_STALE_S = 600.0


def _run_json_script(rel: str, timeout: int) -> Any:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / rel), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)
    if not proc.stdout.strip():
        raise RuntimeError(f"{rel} produced nothing (exit {proc.returncode}): {proc.stderr[-400:]}")
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def _dir() -> Path:
    return store_root() / "ops" / "slow_reads"


def snapshot_path(view: str) -> Path:
    return _dir() / f"{_safe(view)}.json"


def lock_path(view: str) -> Path:
    return _dir() / f"{_safe(view)}.refreshing"


def _safe(view: str) -> str:
    """A view name becomes a filename, so it may not contain a path.

    Every caller passes a key out of `PRODUCERS`, but a filename built from an unchecked string
    is how a cache turns into an arbitrary write, and the check is one line.
    """
    if not view or not view.replace("_", "").isalnum():
        raise ValueError(f"not a view name: {view!r}")
    return view


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #

def load(view: str) -> dict[str, Any]:
    """The snapshot, its age, and whether a refresh is running. Disk only, never raises.

    An unreadable or truncated snapshot is reported as an absent one. A console read that dies
    because a cache file was half-written would be worse than the slow page it replaced.
    """
    _, stale_after = PRODUCERS.get(view, (None, 900.0))
    data: Optional[Any] = None
    captured_at = 0.0
    took = None
    try:
        raw = json.loads(snapshot_path(view).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "data" in raw:
            data = raw.get("data")
            captured_at = float(raw.get("captured_at") or 0.0)
            took = raw.get("took_s")
    except (OSError, ValueError, TypeError):
        data, captured_at, took = None, 0.0, None

    have = data is not None and captured_at > 0
    age = (time.time() - captured_at) if have else None
    return {
        "data": data,
        "have_snapshot": have,
        "captured_at": captured_at or None,
        "captured_at_iso": _iso(captured_at) if have else None,
        "age_s": round(age, 1) if age is not None else None,
        "took_s": took,
        "stale": (not have) or (age is not None and age > stale_after),
        "stale_after_s": stale_after,
        "refreshing": _lock_is_live(view),
    }


def serve(view: str) -> dict[str, Any]:
    """What a console READ calls. Returns in milliseconds, whatever the state.

    If the snapshot is missing or stale this starts a detached refresh, so the page heals itself
    and nobody has to press anything. The refresh is NOT awaited -- awaiting it would put us back
    where we started, with a 141-second read behind a 120-second ceiling.
    """
    payload = load(view)
    if payload["stale"] and not payload["refreshing"]:
        payload["refresh_started"] = refresh_in_background(view)
        if payload["refresh_started"]:
            payload["refreshing"] = True
    else:
        payload["refresh_started"] = False
    return payload


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# The lock. Taken by the PARENT before it spawns, never by the child.
# --------------------------------------------------------------------------- #

def _lock_is_live(view: str) -> bool:
    try:
        return (time.time() - lock_path(view).stat().st_mtime) < LOCK_STALE_S
    except OSError:
        return False


def _take_lock(view: str) -> bool:
    """Create the lock, or say no. `O_EXCL`, so two readers cannot both win.

    A stale lock is reclaimed once per call: unlink it, then try again. If that second attempt
    loses, somebody else reclaimed it first and the answer is still no.

    The lock is taken HERE, in the process that is about to spawn, and never inside the child. A
    child that took its own lock would leave a window in which every page load spawned another
    141-second audit, and this estate has already paid for that class of mistake once -- memory
    `a-recursion-fence-guards-only-its-own-doorstep.md`, load average 646.
    """
    _dir().mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock_path(view)), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {time.time():.0f}\n")
            return True
        except FileExistsError:
            if attempt == 2 or _lock_is_live(view):
                return False
            try:
                lock_path(view).unlink()
            except OSError:
                return False
        except OSError:
            return False
    return False


def _drop_lock(view: str) -> None:
    try:
        lock_path(view).unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #

def refresh(view: str, cfg: Any = None, take_lock: bool = True) -> dict[str, Any]:
    """Run the producer for real and write the snapshot. Returns a receipt, never raises.

    A producer that fails leaves the previous snapshot alone. A stale answer beats an empty one,
    and both beat a half-written file.
    """
    produce, _ = PRODUCERS.get(view, (None, 0.0))
    if produce is None:
        return {"written": False, "view": view, "reason": f"no producer for {view!r}"}

    got_lock = _take_lock(view) if take_lock else True
    if not got_lock:
        return {"written": False, "view": view, "reason": "another refresh is already running"}

    started = time.time()
    try:
        data = produce(cfg)
    except Exception as exc:  # noqa: BLE001 - a producer failure is a receipt, not a crash
        return {"written": False, "view": view, "took_s": round(time.time() - started, 1),
                "reason": f"{type(exc).__name__}: {exc}"[:400]}
    finally:
        if got_lock:
            _drop_lock(view)

    took = round(time.time() - started, 1)
    _write_atomic(view, {"captured_at": time.time(), "took_s": took, "data": data})
    return {"written": True, "view": view, "took_s": took, "path": str(snapshot_path(view))}


def _write_atomic(view: str, payload: dict[str, Any]) -> None:
    """Write beside the target and rename, so a reader never sees a partial file.

    The temp name carries the pid: two writers racing cannot truncate each other's temp file and
    hand `os.replace` half a document.
    """
    path = snapshot_path(view)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def refresh_in_background(view: str) -> bool:
    """Start a detached refresh unless one is running. True if this call started it.

    `start_new_session=True` is the load-bearing argument. The caller is a console read that
    exits in milliseconds, and the whole point is that the audit outlives it. In the read's own
    process group the child dies with it, the snapshot never appears, and every subsequent read
    starts another one.
    """
    if view not in PRODUCERS or not _take_lock(view):
        return False
    try:
        subprocess.Popen(
            [sys.executable, "-m", "prospector.ops.slow_read", view, "--locked"],
            cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return True
    except OSError:
        _drop_lock(view)
        return False


def main(argv: list[str]) -> int:
    # `--locked` means the parent already holds the lock and handed it to this child. The child
    # must not try to take it again -- it would fail -- and must still drop it when it is done.
    inherited = "--locked" in argv
    names = [a for a in argv if not a.startswith("-")]
    if not names:
        print(json.dumps({"written": False, "reason": f"usage: {sorted(PRODUCERS)}"}))
        return 2
    view = names[0]
    cfg = None
    cfg_error = ""
    try:
        from prospector.config import load_config
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001 - a producer that needs no cfg must still run
        # Not fatal: two of the three producers never look at cfg. But it must reach the
        # RECEIPT, not just this function. A snapshot taken with no config looks exactly like
        # one taken with it, and `deploys` is the view that would quietly lose its routes.
        cfg_error = f"{type(exc).__name__}: {exc}"
    try:
        receipt = refresh(view, cfg, take_lock=not inherited)
    finally:
        if inherited:
            _drop_lock(view)
    if cfg_error:
        receipt["config_error"] = cfg_error
    print(json.dumps(receipt))
    return 0 if receipt.get("written") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


def serve_merged(view: str) -> dict[str, Any]:
    """`serve`, flattened so the existing pages keep their field names.

    The three pages that read these views were written against the producer's own shape --
    `data.sections`, `data.deployables`, `data.automations`. Wrapping that in a `data` key would
    have been tidier and would have rewritten three pages for no gain, so the producer's fields
    stay at the top level and the freshness metadata arrives beside them under `snapshot`.

    When there is no snapshot yet the producer's keys are simply ABSENT. That is deliberate and
    the pages check `snapshot.have_snapshot` before they touch them: a page that invented an
    empty `sections: []` would render "nothing is installed", which is a lie about the estate
    rather than a statement about the cache.
    """
    payload = serve(view)
    data = payload.pop("data", None)
    out: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
    if data is not None and not isinstance(data, dict):
        out["rows"] = data
    out["snapshot"] = payload
    return out

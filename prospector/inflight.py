"""The candidate a process is vetting RIGHT NOW, on disk, so killing the process cannot lose it.

WHY THIS FILE EXISTS. A candidate was only ever persisted when its vet FINISHED. `vet_candidate`
writes the dossier and the index row on its single return path, so a process killed mid-vet left
nothing at all: no dossier, no index row, no queue entry. The idea itself — generated at cost,
then half-vetted at more cost — simply stopped existing, and no surface could report it, because
reporting needs a record and there was none.

MEASURED 2026-08-17 on the live store, over the four audit day-files 08-14..08-17: 12 candidates
had a `candidate_start` and no `candidate_done` from a process that no longer exists, and 10 of
those 12 had NO index row and NO dossier. Two daemon restarts (pids 30686 and 99800) account for
them. That is ten ideas paid for and thrown away in four days, with nothing on any screen.

HOW IT WORKS. One small JSON file per candidate under `store/inflight/`, written the moment work
starts and deleted the moment a verdict exists. A leftover file therefore means exactly one
thing: the process that owned it died before it could rule. `orphans()` is that population,
`process_alive` decides ownership, and `vet --resume` re-submits them.

WHY A FILE PER CANDIDATE, NOT ONE LEDGER. Several processes vet concurrently, and the daemon runs
a thread pool. One shared JSON would need a lock on every start and every finish, and a torn
write would lose every in-flight candidate at once instead of one. A file per candidate has no
shared state to tear: `os.replace` onto its own path is atomic, and a crash between write and
replace leaves the previous file intact.

WHAT IT IS NOT. This is not a queue and it is not a lease. It records what a live process is
holding so that a DEAD process's work can be found again. Nothing reads it to decide what to work
on next; the drain still works from index rows (`run.drainable`).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .telemetry import logger

_DIR_NAME = "inflight"

#: An in-flight record older than this is reported even when its pid still looks alive. macOS
#: reuses pids, so a long-dead run whose pid was handed to an unrelated process would otherwise
#: read as busy forever. Two days is far longer than any vet has ever taken.
STALE_S = 48 * 3600.0


def directory(store_root: Path) -> Path:
    return Path(store_root) / _DIR_NAME


def _path(store_root: Path, candidate_id: str) -> Path:
    # The id is content-addressed hex from `Candidate.__post_init__`, but this joins a path with
    # it, so anything that is not a bare filename is refused rather than escaping the directory.
    safe = "".join(ch for ch in str(candidate_id) if ch.isalnum() or ch in "-_")
    if not safe:
        raise ValueError(f"unusable candidate_id for an in-flight record: {candidate_id!r}")
    return directory(store_root) / f"{safe}.json"


def open_(store_root: Path, cand, *, run_id: str = "", label: str = "",
          full_vet: bool = False) -> Optional[Path]:
    """Record that this process has started vetting `cand`. Never raises.

    A failure here must not stop a vet. The ledger exists to recover work; refusing to do the
    work because the recovery note could not be written would be the cure causing the disease.
    """
    try:
        path = _path(store_root, cand.candidate_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "candidate_id": cand.candidate_id,
            "candidate": cand.to_dict(),
            "run_id": run_id,
            "pid": os.getpid(),
            "started_at": time.time(),
            "label": label or "",
            "full_vet": bool(full_vet),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        tmp.replace(path)  # atomic: a reader never sees half a record
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record in-flight candidate",
                       extra={"candidate_id": getattr(cand, "candidate_id", "?"),
                              "error": f"{exc}"})
        return None


def close(store_root: Path, candidate_id: str) -> bool:
    """The candidate has a verdict; drop its record. True when a record was actually removed."""
    try:
        _path(store_root, candidate_id).unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not clear in-flight record",
                       extra={"candidate_id": candidate_id, "error": f"{exc}"})
        return False


def _records(store_root: Path) -> list[dict[str, Any]]:
    d = directory(store_root)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            rec = json.loads(f.read_text(errors="replace"))
        except Exception as exc:  # noqa: BLE001 — a torn record is information, not a crash
            out.append({"path": str(f), "unreadable": f"{exc}",
                        "candidate_id": f.stem, "pid": None, "started_at": None})
            continue
        if isinstance(rec, dict):
            rec["path"] = str(f)
            out.append(rec)
    return out


def survey(store_root: Path, *, now: Optional[float] = None,
           alive: Optional[dict] = None) -> dict:
    """Every in-flight record, split into work still running and work whose process is gone.

    `alive` overrides the process probe, keyed by pid. Tests pass it; nothing else should.
    """
    from .ops.runs import process_alive

    clock = now if now is not None else time.time()
    probed = dict(alive or {})
    live, orphaned, unreadable = [], [], []
    for rec in _records(store_root):
        if rec.get("unreadable"):
            unreadable.append(rec)
            continue
        pid = rec.get("pid")
        if pid is None or rec.get("started_at") is None:
            # `open_` always writes both, so a record missing either was not written by this
            # module. Its owner is unknowable: calling it live would strand it forever, and
            # calling it abandoned could re-vet work a live process is holding. Neither guess is
            # honest, so it is reported as needing a human instead of being silently sorted.
            rec["unreadable"] = "the record names no process, so nothing can say whether it is " \
                                "still being worked"
            unreadable.append(rec)
            continue
        if pid not in probed:
            probed[pid] = process_alive(pid)
        started = rec.get("started_at")
        age_s = None if started is None else max(0.0, clock - float(started))
        rec["age_s"] = None if age_s is None else round(age_s, 1)
        rec["pid_alive"] = probed.get(pid) if pid is not None else None
        stale = age_s is not None and age_s >= STALE_S
        # UNKNOWN IS NOT DEAD. `process_alive` returns None when the probe itself failed, and
        # collapsing that into "abandoned" would re-vet a candidate a LIVE process is holding —
        # paying twice for one answer and racing two publishes into a Stripe mint that has no
        # lock of its own. So a record is only abandoned when the process is PROVEN gone, or when
        # it is older than any vet has ever taken. Same doctrine as `classify_unfinished`
        # (ops/runs.py:304): a failed measurement is never reported as a finding.
        if rec["pid_alive"] is False:
            rec["why"] = "the process that held it is gone"
            orphaned.append(rec)
        elif stale:
            rec["why"] = (f"held for more than {int(STALE_S // 3600)}h, "
                          f"longer than any vet takes")
            orphaned.append(rec)
        else:
            if rec["pid_alive"] is None:
                rec["note"] = ("could not tell whether the owning process is alive; treated as "
                               "still working, which is the safe direction")
            live.append(rec)
    return {"live": live, "orphaned": orphaned, "unreadable": unreadable,
            "dir": str(directory(store_root)),
            "counts": {"live": len(live), "orphaned": len(orphaned),
                       "unreadable": len(unreadable)}}


def orphans(store_root: Path, *, now: Optional[float] = None,
            alive: Optional[dict] = None) -> list[dict]:
    """Records whose owning process is gone — work that will never finish on its own."""
    return survey(store_root, now=now, alive=alive)["orphaned"]


#: How long a recovery claim is honoured. A recovering process that dies leaves its marker
#: behind, and the orphan would then be orphaned twice with nothing able to take it.
RECOVER_TTL_S = 4 * 3600.0


def _claim_path(store_root: Path, candidate_id: str) -> Path:
    return _path(store_root, candidate_id).with_suffix(".recovering")


def claim(store_root: Path, candidate_id: str, owner: str, *,
          ttl_s: float = RECOVER_TTL_S, now: Optional[float] = None) -> bool:
    """Take exclusive ownership of one orphan for recovery. True when THIS caller won it.

    `Store.claim` cannot do this job: it updates an index row, and the orphans that matter are
    exactly the ones with no index row (10 of 12, measured 2026-08-17). So ownership is taken on
    the filesystem instead — `O_CREAT | O_EXCL` is atomic on every filesystem this runs on, so
    two drains racing the same record produce one winner and one `FileExistsError`.
    """
    clock = now if now is not None else time.time()
    path = _claim_path(store_root, candidate_id)
    for attempt in (0, 1):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if attempt:  # someone else re-took it in the gap; theirs, not ours
                return False
            try:
                held = json.loads(path.read_text(errors="replace"))
                age = clock - float(held.get("at") or 0.0)
            except Exception:  # noqa: BLE001 — an unreadable marker is a dead marker
                age = ttl_s + 1.0
            if age <= ttl_s:
                return False
            # The claimant died holding it. Drop the marker and try once more.
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not claim in-flight record",
                           extra={"candidate_id": candidate_id, "error": f"{exc}"})
            return False
        with os.fdopen(fd, "w") as fh:
            json.dump({"owner": owner, "at": clock, "pid": os.getpid()}, fh)
        return True
    return False


def release_claim(store_root: Path, candidate_id: str) -> bool:
    """Drop a recovery claim. Called on every path out of a recovery, including a raise."""
    try:
        _claim_path(store_root, candidate_id).unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not release in-flight claim",
                       extra={"candidate_id": candidate_id, "error": f"{exc}"})
        return False


def candidate_of(record: dict):
    """The `Candidate` a record holds, or None when the record cannot rebuild one."""
    from .models import Candidate

    try:
        return Candidate.from_dict(dict(record.get("candidate") or {}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("in-flight record cannot rebuild its candidate",
                       extra={"candidate_id": record.get("candidate_id"), "error": f"{exc}"})
        return None

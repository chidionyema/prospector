"""Snapshot and roll back the engine's local state, so admin actions do not have to be hidden.

WHY THIS EXISTS (founder directive, 2026-08-16): "we just need rollback to be safe not to hide
actions". The console used to make a tool safe by refusing to run it. That is the wrong fence. A
tool the operator cannot reach from the console is a tool they run at a terminal instead, with no
preview, no receipt and no undo — so hiding it made the estate LESS safe, not more.

WHAT IT COVERS, AND WHAT IT CANNOT. This rolls back the local `store/` tree and nothing else. It
cannot undo a Stripe charge, a published pack on the live shelf, or a deleted remote row, because
those live on someone else's disk. Every caller must say which of the two it is; an undo that
silently covers half the blast radius is worse than no undo, because the operator acts on the
belief that it covers all of it.

WHY A COPY-ON-WRITE CLONE. `cp -Rc` on APFS shares the blocks until a file diverges, so a snapshot
of 430 MB costs almost no disk. Measured on this machine 2026-08-16:

    whole store/ (29,993 files, 560 MB)          83.2 s
    store/ minus store/_cache (3,035 files)      11.5 s

`store/_cache` is 26,939 of those files and is a content-addressed retrieval cache the engine
regenerates on demand. Excluding it removes 90% of the cost and loses nothing a rollback needs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

#: Directories under `store/` that are NEVER snapshotted. Only regenerable state belongs here.
#: `_cache` is the retrieval cache: 26,939 of the tree's 29,993 files, rebuilt on a miss. Rolling
#: it back would restore stale search results, which is the opposite of what an operator wants.
EXCLUDED = {"_cache"}

#: Where snapshots live. Outside `store/`, or a snapshot would clone the previous snapshot.
UNDO_DIRNAME = ".undo"

#: How many snapshots survive. Blocks share on APFS, so the cost of keeping them is small, but an
#: unbounded series would still outlive the disk.
DEFAULT_KEEP = 12

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", str(text).lower()).strip("-")[:48] or "action"


def undo_root(root: Path | None = None) -> Path:
    return (root or _repo_root()) / UNDO_DIRNAME


def _clone(src: Path, dst: Path) -> bool:
    """Copy `src` to `dst`, preferring an APFS clone. Returns True if the clone was used.

    A real copy is the fallback rather than a refusal: on a non-APFS volume the snapshot is slower
    and costs real disk, but the operator still gets their undo. Failing here would mean the
    action runs with no rollback at all, which is the outcome this module exists to prevent.
    """
    proc = subprocess.run(["cp", "-Rc", str(src), str(dst)], capture_output=True, text=True)
    if proc.returncode == 0:
        return True
    proc = subprocess.run(["cp", "-R", str(src), str(dst)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"could not snapshot {src.name}: {(proc.stderr or '').strip()}")
    return False


def _walk(base: Path, *, skip: set[str] = frozenset()) -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime_ns) for every file under `base`."""
    out: dict[str, tuple[int, int]] = {}
    if not base.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(base)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue  # a file that vanished mid-walk is not part of the snapshot
            out[str((rel_dir / name).as_posix()).lstrip("./")] = (st.st_size, st.st_mtime_ns)
    return out


def snapshot(label: str, *, root: Path | None = None, note: str = "",
             actor: str = "console") -> dict:
    """Clone the rollback-relevant part of `store/` and return the snapshot's record."""
    root = root or _repo_root()
    store = root / "store"
    if not store.is_dir():
        raise RuntimeError(f"no store/ directory at {store} — nothing to snapshot")

    stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    dest = undo_root(root) / f"{stamp}-{_slug(label)}"
    if dest.exists():  # same second, same label
        dest = Path(f"{dest}-{os.getpid()}")
    dest.mkdir(parents=True)

    started = time.time()
    cow = True
    for entry in sorted(store.iterdir()):
        if entry.name in EXCLUDED:
            continue
        cow = _clone(entry, dest / entry.name) and cow

    files = _walk(dest, skip={"manifest.json"})
    rec = {
        "id": dest.name,
        "ts": stamp,
        "label": label,
        "actor": actor,
        "note": note,
        "excluded": sorted(EXCLUDED),
        "files": len(files),
        "bytes": sum(size for size, _ in files.values()),
        "copy_on_write": cow,
        "took_s": round(time.time() - started, 1),
        "covers": "the local store/ tree only — NOT Stripe, NOT the live shelf, NOT config.yaml "
                  "(config has its own backups, see config.restore)",
    }
    (dest / "manifest.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    prune(root=root)
    return rec


def list_snapshots(root: Path | None = None) -> list[dict]:
    """Newest first. A snapshot with an unreadable manifest is listed as broken, never dropped."""
    base = undo_root(root)
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        try:
            rec = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            rec = {"id": d.name, "ts": d.name[:20], "label": "(unreadable manifest)",
                   "broken": True}
        rec["id"] = d.name
        out.append(rec)
    return sorted(out, key=lambda r: r.get("id", ""), reverse=True)


def prune(*, keep: int = DEFAULT_KEEP, root: Path | None = None) -> list[str]:
    """Delete all but the newest `keep` snapshots. Returns what was deleted."""
    if keep <= 0:
        return []
    base = undo_root(root)
    doomed = [r["id"] for r in list_snapshots(root)[keep:]]
    for name in doomed:
        shutil.rmtree(base / name, ignore_errors=True)
    return doomed


def _snapshot_dir(snap_id: str, root: Path | None = None) -> Path:
    base = undo_root(root)
    d = base / snap_id
    # A snapshot id comes off the wire. Resolve it and check it is really inside the undo dir, so
    # `../../` cannot make this function read or overwrite an arbitrary tree.
    if d.resolve().parent != base.resolve() or not d.is_dir():
        raise ValueError(f"no snapshot named {snap_id!r}")
    return d


def restore_plan(snap_id: str, *, root: Path | None = None) -> dict:
    """What a restore WOULD do, without doing it.

    Rollback means the tree ends up as it was, so this both puts files back and removes files
    created since. The removal list is the part an operator must see before confirming: anything
    the daemon wrote after the snapshot is in it.
    """
    root = root or _repo_root()
    snap = _snapshot_dir(snap_id, root)
    store = root / "store"

    before = _walk(snap, skip={"manifest.json"})
    before.pop("manifest.json", None)
    now = _walk(store, skip=EXCLUDED)

    overwrite = sorted(p for p, meta in before.items() if now.get(p) not in (meta, None))
    recreate = sorted(p for p in before if p not in now)
    delete = sorted(p for p in now if p not in before)
    return {
        "snapshot": snap_id,
        "restore": len(overwrite) + len(recreate),
        "overwrite": len(overwrite),
        "recreate": len(recreate),
        "delete": len(delete),
        "delete_sample": delete[:20],
        "overwrite_sample": overwrite[:20],
        "unchanged": len(before) - len(overwrite) - len(recreate),
        "excluded": sorted(EXCLUDED),
        "warning": "Files written since the snapshot are DELETED. If the scheduler or consumer is "
                   "running, arm PAUSE first or you roll back its work too.",
    }


def restore(snap_id: str, *, root: Path | None = None) -> dict:
    """Put `store/` back to the snapshot. Returns a receipt of what actually moved."""
    root = root or _repo_root()
    snap = _snapshot_dir(snap_id, root)
    store = root / "store"
    plan = restore_plan(snap_id, root=root)

    started = time.time()
    restored = deleted = 0
    errors: list[str] = []

    before = _walk(snap, skip={"manifest.json"})
    before.pop("manifest.json", None)
    now = _walk(store, skip=EXCLUDED)

    for rel, meta in before.items():
        if now.get(rel) == meta:
            continue
        src, dst = snap / rel, store / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".undo-tmp")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)  # atomic, so a reader never sees a half-written file
            restored += 1
        except OSError as exc:
            errors.append(f"restore {rel}: {exc}")

    for rel in now:
        if rel in before:
            continue
        try:
            (store / rel).unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f"delete {rel}: {exc}")

    return {
        "snapshot": snap_id,
        "planned": plan,
        "restored": restored,
        "deleted": deleted,
        "errors": errors[:20],
        "error_count": len(errors),
        "applied": not errors,
        "took_s": round(time.time() - started, 1),
    }

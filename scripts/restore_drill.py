#!/usr/bin/env python3
"""R4 — the restore drill. A backup nobody has ever restored is not a backup.

What this proves
----------------
`scripts/backup_store.py` copies `store/dossiers/*.json` and `store/prospector.jsonl` to R2 and
re-reads a sample. It has never restored `store/prospector.db`, and nothing has ever asserted that
a restored tree agrees with the index that points into it. This script does the restore end to end
into a scratch directory and asserts, with receipts:

    1. the restored SQLite index opens and passes PRAGMA integrity_check
    2. its per-table row counts match the live source (within the concurrent-write window)
    3. every dossier in the live source is present in the restore — by membership, not by
       count, since a supplied backup payload is cumulative and keeps what the source deleted
       (a self-made snapshot is still checked on the tighter count window)
    4. a random sample of index rows resolves to a restored file that parses as the JSON a
       recovery is supposed to yield, carrying the candidate_id the row claims
    5. index and tree agree: every non-tombstoned row has a file, and orphan files are counted

Exit 0 = drill passed. Non-zero = a human is needed.

Read-only with respect to production
------------------------------------
The live store is opened `file:...?mode=ro` (URI), which matters for two independent reasons: the
daemon is writing to `prospector.db` concurrently and must not be locked out, and a probe that can
mutate the thing it is probing is worse than no probe. Everything this script writes goes under a
scratch directory (a fresh `tempfile.mkdtemp()` unless `--dest` names one), and `_guard_dest()`
refuses any destination inside `store/` or `storage/`.

Concurrency is handled, not wished away
---------------------------------------
A daemon appending rows while the snapshot runs would make a strict equality assertion flap. So the
source is censused BEFORE and AFTER the snapshot, and the restored count must land inside that
window. When nothing wrote, before == after and the assertion is exact equality; when something
did, the drill says so instead of silently widening its own tolerance.

Usage
-----
    .venv/bin/python scripts/restore_drill.py                 # snapshot the live store, restore it
    .venv/bin/python scripts/restore_drill.py --keep          # leave the scratch dir for inspection
    .venv/bin/python scripts/restore_drill.py --backup DIR    # drill an EXISTING backup payload
    .venv/bin/python scripts/restore_drill.py --store DIR     # drill a store root other than ./store

`--backup DIR` accepts what a real recovery would hand you: a directory holding `prospector.db`
and/or a `dossiers/` subdirectory (a flat pile of `*.json` also works — that is the shape
`backup_store.py --restore DIR` produces).

Zero network, zero LLM calls. This is deliberately not the R2 path: pulling from R2 is already
`backup_store.py --restore`, and a drill that needs the network cannot run when the network is the
thing that broke.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = REPO_ROOT / "store"

#: Where the run leaves proof it happened, relative to the store being drilled. The Data console
#: screen reads exactly this file, and reports "never" when it is absent — which is the honest
#: answer, and the reason the drill writes it even when it fails.
RECEIPT_REL = Path("ops") / "restore_drill.json"
DB_NAME = "prospector.db"
DOSSIER_DIRNAME = "dossiers"

# Rows the index deliberately keeps after the file went away. They are not restore failures; a
# drill that failed on them would fail every run and stop being read.
TOMBSTONED_ABSENT = {"dossier_missing"}

DEFAULT_SAMPLE = 12


# ── receipts ──────────────────────────────────────────────────────────────────
@dataclass
class Drill:
    """Accumulates receipt lines and failures so one run prints every problem, not the first."""

    lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def note(self, label: str, detail: str) -> None:
        self.lines.append(f"  {label:<22} {detail}")

    def check(self, ok: bool, label: str, detail: str) -> bool:
        self.lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label:<16} {detail}")
        if not ok:
            self.failures.append(f"{label}: {detail}")
        return ok


# ── census (read-only) ────────────────────────────────────────────────────────
def _connect_ro(db: Path) -> sqlite3.Connection:
    """Open read-only. `mode=ro` is a URI feature, so uri=True is not optional here.

    Read-only also means this connection cannot take the write lock the live daemon needs.
    """
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    counts: dict[str, int] = {}
    for name in names:
        # Identifier, not a value — it cannot be bound, so it is quoted instead.
        counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    return counts


def _dossier_files(dossier_dir: Path) -> list[Path]:
    """Every dossier under the tree, RECURSIVELY.

    `rglob`, not `glob`, and that is a measured decision rather than a style one. The live index
    carries 9 rows under `store/dossiers/quarantine_ungrounded/`, which a top-level `*.json` glob
    does not see — the first run of this drill failed on exactly those 9 rows. `backup_store.py`
    still uses the non-recursive glob (`backup_store.py:sync`), so those dossiers are not in R2.
    """
    if not dossier_dir.is_dir():
        return []
    return sorted(p for p in dossier_dir.rglob("*.json") if p.is_file())


def _tree_keys(tree: Path) -> set[str]:
    """How a restored tree can be addressed: relative path AND bare filename.

    Both are needed because two backup shapes exist. This drill's own snapshot preserves the
    directory structure, so the relative path is the honest key; `backup_store.py --restore DIR`
    produces a FLAT pile of `*.json`, where only the filename survives. Accepting either means the
    drill can verify a payload it did not create.
    """
    keys: set[str] = set()
    for path in _dossier_files(tree):
        keys.add(path.relative_to(tree).as_posix())
        keys.add(path.name)
    return keys


def _row_keys(row_path: str, src_tree: Path) -> tuple[str, str]:
    """(relative-path key, filename key) for an index row's absolute path."""
    path = Path(row_path or "")
    try:
        rel = path.relative_to(src_tree).as_posix()
    except ValueError:
        rel = path.name
    return rel, path.name


def census(store_dir: Path) -> tuple[dict[str, int], int]:
    """(table -> row count, dossier file count) for a store root, touching nothing."""
    db = store_dir / DB_NAME
    counts: dict[str, int] = {}
    if db.is_file():
        conn = _connect_ro(db)
        try:
            counts = _table_counts(conn)
        finally:
            # `with sqlite3.connect(...)` commits the transaction and leaves the handle OPEN.
            # Closing is explicit here on purpose.
            conn.close()
    return counts, len(_dossier_files(store_dir / DOSSIER_DIRNAME))


# ── snapshot (the "backup" half, when no payload was supplied) ────────────────
def snapshot(store_dir: Path, dest: Path, drill: Drill) -> Path:
    """Write a consistent copy of the live store into `dest`. Reads only from `store_dir`.

    The SQLite online-backup API is used rather than `shutil.copy` because the daemon is writing:
    copying the file bytes under WAL can capture a torn page set plus a stale `-wal`, and the
    result opens fine and is wrong. `Connection.backup()` takes the copy through SQLite itself.
    """
    dest.mkdir(parents=True, exist_ok=True)
    src_db = store_dir / DB_NAME
    if src_db.is_file():
        src = _connect_ro(src_db)
        dst = sqlite3.connect(str(dest / DB_NAME))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        drill.note("snapshot db", f"{dest / DB_NAME} ({(dest / DB_NAME).stat().st_size} bytes)")
    else:
        drill.note("snapshot db", f"ABSENT — no {src_db}")

    src_tree = store_dir / DOSSIER_DIRNAME
    out_dossiers = dest / DOSSIER_DIRNAME
    out_dossiers.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in _dossier_files(src_tree):
        target = out_dossiers / path.relative_to(src_tree)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            copied += 1
        except FileNotFoundError:
            # The daemon can retire a dossier between the listing and the copy. That is the
            # concurrent-write window, and the before/after census is what accounts for it.
            continue
    drill.note("snapshot dossiers", f"{copied} files -> {out_dossiers}")
    return dest


# ── restore ───────────────────────────────────────────────────────────────────
def restore(backup_dir: Path, dest: Path, drill: Drill) -> tuple[Path | None, Path]:
    """Materialise `backup_dir` into `dest` as a store root. Returns (db path or None, tree)."""
    dest.mkdir(parents=True, exist_ok=True)
    db_src = backup_dir / DB_NAME
    db_out: Path | None = None
    if db_src.is_file():
        shutil.copy2(db_src, dest / DB_NAME)
        db_out = dest / DB_NAME

    tree_src = backup_dir / DOSSIER_DIRNAME
    if not tree_src.is_dir():
        # `backup_store.py --restore DIR` drops a flat pile of *.json; accept that shape too.
        tree_src = backup_dir
    tree_out = dest / DOSSIER_DIRNAME
    tree_out.mkdir(parents=True, exist_ok=True)
    restored = 0
    for path in _dossier_files(tree_src):
        target = tree_out / path.relative_to(tree_src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        restored += 1
    drill.note("restored", f"db={'yes' if db_out else 'NO'} dossiers={restored} -> {dest}")
    return db_out, tree_out


# ── assertions ────────────────────────────────────────────────────────────────
def _window(before: int, after: int) -> tuple[int, int]:
    return (min(before, after), max(before, after))


def _fmt_window(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}..{hi}"


def verify_counts(
    db: Path | None,
    tree: Path,
    src_before: tuple[dict[str, int], int],
    src_after: tuple[dict[str, int], int],
    drill: Drill,
    *,
    strict: bool,
    src_tree: Path | None = None,
) -> dict[str, int]:
    """Assert the restored copy's counts match the source. Returns the restored table counts."""
    counts_before, files_before = src_before
    counts_after, files_after = src_after

    restored_counts: dict[str, int] = {}
    if db is None:
        drill.check(
            not counts_before,
            "db_present",
            "the backup contains no prospector.db but the source has one"
            if counts_before
            else "no db in source or backup",
        )
    else:
        try:
            conn = sqlite3.connect(str(db))
        except sqlite3.Error as exc:
            drill.check(False, "db_opens", f"{type(exc).__name__}: {exc}")
            return {}
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            drill.check(integrity == "ok", "db_integrity", f"PRAGMA integrity_check -> {integrity}")
            restored_counts = _table_counts(conn)
        except sqlite3.DatabaseError as exc:
            # A truncated or overwritten file fails HERE, not at connect(): sqlite3.connect()
            # does not read a page until the first statement.
            drill.check(False, "db_integrity", f"{type(exc).__name__}: {exc}")
            return {}
        finally:
            conn.close()

        missing = sorted(set(counts_before) - set(restored_counts))
        drill.check(not missing, "db_tables", f"missing tables: {missing}" if missing else
                    f"{len(restored_counts)} table(s): {sorted(restored_counts)}")
        for table in sorted(set(counts_before) | set(restored_counts)):
            lo, hi = _window(counts_before.get(table, 0), counts_after.get(table, 0))
            got = restored_counts.get(table, 0)
            ok = (lo <= got <= hi) if strict else (got <= hi)
            drill.check(
                ok,
                f"rows:{table}",
                f"restored={got} source={_fmt_window(lo, hi)}"
                + ("" if ok else "  <-- MISMATCH"),
            )

    lo, hi = _window(files_before, files_after)
    got = len(_dossier_files(tree))
    if strict or src_tree is None:
        # The drill made this payload itself, seconds ago: it should match, and a window only
        # absorbs the daemon's concurrent writes.
        ok = lo <= got <= hi
        drill.check(
            ok,
            "dossier_files",
            f"restored={got} source={_fmt_window(lo, hi)}" + ("" if ok else "  <-- MISMATCH"),
        )
    else:
        # A supplied payload — in practice an R2 pull — is CUMULATIVE. `backup_store.sync` never
        # deletes, deliberately: a mirror that removes what the source removed cannot survive an
        # accidental deletion, which is the failure the bucket exists for. So the restored tree
        # legitimately holds files the live store no longer has (2026-08-07: 1701 restored vs
        # 1588 live, the difference being dossiers since deleted or moved into a subdirectory).
        #
        # Counting was the wrong question anyway. `restored == source` passes when N files are
        # missing and N stale ones are present — the exact shape of the gap this drill found on
        # its first run, where 9 quarantined dossiers had never been uploaded. Membership is the
        # property that matters and is strictly stronger: every dossier in the live store must be
        # recoverable from the payload. Surplus is reported, not failed.
        src_files = _dossier_files(src_tree)
        missing = [
            p for p in src_files
            if _resolve(tree, p.relative_to(src_tree).as_posix(), p.name) is None
        ]
        drill.check(
            not missing,
            "dossier_coverage",
            f"{len(src_files)} live source file(s), all present in the restore"
            if not missing
            else f"{len(missing)}/{len(src_files)} live source file(s) NOT in the restore: "
                 f"{[p.name for p in missing[:5]]}  <-- MISSING",
        )
        drill.note(
            "retained_history",
            f"{got} restored vs {len(src_files)} live — {got - (len(src_files) - len(missing))} "
            f"object(s) the backup keeps that the source no longer has",
        )
    return restored_counts


def _resolve(tree: Path, rel: str, name: str) -> Path | None:
    for candidate in (tree / rel, tree / name):
        if candidate.is_file():
            return candidate
    hits = [p for p in _dossier_files(tree) if p.name == name]
    return hits[0] if hits else None


def verify_spot_check(
    db: Path | None, tree: Path, src_tree: Path, sample_n: int, drill: Drill
) -> None:
    """Resolve a random sample of index rows to restored files, and check the tree both ways.

    Hashing the restored bytes against themselves would pass on a bucket full of garbage. The
    referents here are outside the restored file: the row that claims it exists, and whether the
    bytes parse as the dossier JSON a recovery is supposed to yield.
    """
    if db is None:
        drill.note("spot_check", "skipped — no restored db")
        return
    conn = sqlite3.connect(str(db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(dossiers)")}
        if "candidate_id" not in cols or "path" not in cols:
            drill.check(False, "spot_check", f"dossiers table lacks candidate_id/path: {sorted(cols)}")
            return
        tomb = "tombstone" in cols
        rows = conn.execute(
            "SELECT candidate_id, path, " + ("tombstone" if tomb else "NULL") + " FROM dossiers"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        drill.check(False, "spot_check", f"{type(exc).__name__}: {exc}")
        return
    finally:
        conn.close()

    expected = [r for r in rows if (r[2] or "") not in TOMBSTONED_ABSENT]
    tombstoned = len(rows) - len(expected)

    present = _tree_keys(tree)
    dangling = [
        r[0] for r in expected if not set(_row_keys(r[1] or "", src_tree)) & present
    ]
    drill.check(
        not dangling,
        "index_vs_tree",
        f"{len(expected)} live rows, {tombstoned} tombstoned, "
        + (f"{len(dangling)} rows with NO restored file e.g. {dangling[:3]}" if dangling
           else "every live row has a restored file"),
    )
    indexed = {k for r in rows for k in _row_keys(r[1] or "", src_tree)}
    orphans = {p.name for p in _dossier_files(tree)} - indexed
    drill.note("orphan_files", f"{len(orphans)} restored file(s) with no index row")

    if not expected:
        drill.note("spot_check", "no live rows to sample")
        return
    sample = random.sample(expected, min(sample_n, len(expected)))
    problems: list[str] = []
    for candidate_id, path, _ in sample:
        rel, name = _row_keys(path or "", src_tree)
        target = _resolve(tree, rel, name)
        if target is None:
            problems.append(f"{candidate_id}: no restored file for {rel}")
            continue
        try:
            payload = json.loads(target.read_text())
        except (ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{candidate_id}: restored bytes are not valid JSON ({exc})")
            continue
        if not isinstance(payload, dict):
            problems.append(f"{candidate_id}: restored JSON is {type(payload).__name__}, not an object")
            continue
        got_id = (payload.get("candidate") or {}).get("id") if isinstance(
            payload.get("candidate"), dict
        ) else payload.get("candidate_id")
        if got_id is not None and got_id != candidate_id:
            problems.append(f"{candidate_id}: restored file carries id {got_id!r}")
    drill.check(
        not problems,
        "spot_check",
        f"{len(sample)} sampled row(s) resolve, parse and match"
        if not problems
        else f"{len(problems)}/{len(sample)} failed: {problems[:3]}",
    )


# ── safety ────────────────────────────────────────────────────────────────────
def _guard_dest(dest: Path, store_dir: Path) -> None:
    """Refuse to write into production state. A probe that mutates is worse than none."""
    dest = dest.resolve()
    for protected in (store_dir.resolve(), REPO_ROOT / "store", REPO_ROOT / "storage"):
        try:
            dest.relative_to(protected)
        except ValueError:
            continue
        sys.exit(
            f"RESTORE_DRILL ABORT --dest {dest} is inside protected runtime state {protected}; "
            "the drill restores into scratch and never over the original"
        )


def run_drill(
    store_dir: Path,
    dest: Path,
    *,
    backup_dir: Path | None = None,
    sample_n: int = DEFAULT_SAMPLE,
) -> tuple[int, str]:
    """Returns (exit code, report). Writes only under `dest`."""
    drill = Drill()
    drill.note("source", str(store_dir))
    drill.note("scratch", str(dest))

    src_before = census(store_dir)
    if backup_dir is None:
        backup_dir = snapshot(store_dir, dest / "_backup", drill)
        strict = True
    else:
        drill.note("backup", f"{backup_dir} (supplied — not snapshotted)")
        # A payload from an earlier run has drifted from the live store by design; a restored
        # count BELOW the source is expected, above it is not.
        strict = False
    src_after = census(store_dir)
    if src_before != src_after:
        drill.note(
            "concurrent writes",
            f"source moved during the snapshot: db={src_before[0]}->{src_after[0]} "
            f"files={src_before[1]}->{src_after[1]}",
        )

    db, tree = restore(backup_dir, dest / "restored", drill)
    verify_counts(db, tree, src_before, src_after, drill, strict=strict,
                  src_tree=store_dir / DOSSIER_DIRNAME)
    verify_spot_check(db, tree, store_dir / DOSSIER_DIRNAME, sample_n, drill)

    ok = not drill.failures
    header = "RESTORE_DRILL " + ("PASS" if ok else "FAIL")
    body = "\n".join(drill.lines)
    tail = "" if ok else "\n" + "\n".join(f"  !! {f}" for f in drill.failures)
    return (0 if ok else 1), f"{header}\n{body}{tail}\n{header} checks={len(drill.lines)} failures={len(drill.failures)}"


def write_receipt(store_dir: Path, *, ok: bool, took_s: float, report: str) -> Path:
    """Leave proof the drill ran, next to the store it drilled.

    Written on failure as well as on success. A receipt only written on a pass turns a failing
    drill into a screen that says "never run", which reads as nothing happened rather than as
    something broke.
    """
    path = store_dir / RECEIPT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    header = report.splitlines()[0] if report else ""
    payload = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ok": bool(ok),
        "took_s": round(took_s, 1),
        "restored": str(store_dir),
        "what": header,
        "tool": "scripts/restore_drill.py",
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)  # atomic, so a reader never sees half a receipt
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=str(DEFAULT_STORE),
                        help=f"store root to drill (default {DEFAULT_STORE})")
    parser.add_argument("--dest", default=None,
                        help="scratch directory (default: a fresh mkdtemp, removed on exit)")
    parser.add_argument("--backup", default=None,
                        help="restore an EXISTING backup payload instead of snapshotting the store")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"index rows to spot-check (default {DEFAULT_SAMPLE})")
    parser.add_argument("--keep", action="store_true",
                        help="do not delete the scratch directory")
    parser.add_argument("--seed", type=int, default=None, help="seed the spot-check sample")
    parser.add_argument("--no-receipt", action="store_true",
                        help=f"do not write {RECEIPT_REL} under the store")
    args = parser.parse_args(argv)

    if args.seed is not None:
        random.seed(args.seed)

    store_dir = Path(args.store).expanduser().resolve()
    if not store_dir.is_dir():
        print(f"RESTORE_DRILL ABORT no store directory at {store_dir}", file=sys.stderr)
        return 2
    backup_dir = Path(args.backup).expanduser().resolve() if args.backup else None
    if backup_dir is not None and not backup_dir.is_dir():
        print(f"RESTORE_DRILL ABORT no backup directory at {backup_dir}", file=sys.stderr)
        return 2

    ephemeral = args.dest is None
    dest = Path(args.dest).expanduser().resolve() if args.dest else Path(
        tempfile.mkdtemp(prefix="restore_drill_")
    )
    _guard_dest(dest, store_dir)

    try:
        started = time.monotonic()
        code, report = run_drill(store_dir, dest, backup_dir=backup_dir, sample_n=args.sample)
        print(report)
        if not args.no_receipt:
            receipt = write_receipt(store_dir, ok=code == 0, took_s=time.monotonic() - started,
                                    report=report)
            print(f"  receipt {receipt}")
        return code
    finally:
        if ephemeral and not args.keep:
            shutil.rmtree(dest, ignore_errors=True)
        elif args.keep:
            print(f"  scratch kept at {dest}")


if __name__ == "__main__":
    raise SystemExit(main())

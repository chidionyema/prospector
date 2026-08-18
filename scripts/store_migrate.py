#!/usr/bin/env python3
"""Move the engine's store between hosts, and prove it arrived.

The engine's state is a directory. Moving the engine to a server means moving that directory,
and the whole risk of the migration is concentrated in one question: did all of it arrive, and
is the catalogue still a database when it gets there?

Three commands, deliberately separate so the dangerous one is never the default:

    store_migrate.py plan                 # what would move, how big, how many rows
    store_migrate.py pack OUT.tar.gz      # build the payload + a manifest of sha256s
    store_migrate.py verify DIR           # check an unpacked tree against that manifest

`pack` and `verify` are two ends of the same wire and share one manifest format, so the same
command proves the copy in either direction: laptop to Fly volume at cutover, Fly volume back to
laptop for the failback drill. `scripts/restore_drill.py` proves the R2 backup is restorable;
this proves a HOST MOVE is complete. They are different questions and neither answers the other.

WHAT IS NOT COPIED, and why each is safe to drop:

  `_cache/`      retrieval cache. 172 MB, regenerates on demand, and a stale cache on a new host
                 is worse than no cache — it can answer a live grounding call with a fetch made
                 on a different day.
  `*.bak`        hand-made sqlite copies from past migrations. History, not state.
  `.write_probe` the container entrypoint's own probe file.

Everything else moves, INCLUDING the parts the R2 backup does not carry: `scheduler/` (the PAUSE
switch and the tick audit trail), `listings/`, `pricing/`, `inflight/` (orphan recovery), and
`ops/`. `backup_store.py` covers dossiers, the ledger and the db, because those are the ones that
cannot be rebuilt. A HOST MOVE is a stricter requirement: the engine must wake up on the new box
in the state it went to sleep in, and a missing `scheduler/PAUSE` means it wakes up generating.

THE FENCE. `pack` refuses to run while the scheduler or consumer is alive, because both append
to `store/prospector.jsonl` and a copy taken mid-append yields a truncated final line — a ledger
whose last row is half a JSON object, on the file the daily spend cap is computed from. That is
EDGE-1 in `docs/ENGINE_MIGRATION_PROGRAM.md` reached from the other side: not two engines running
at once, but one engine running during the copy. Stop them first; `--force` exists for a drill
against a store nothing is writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

MANIFEST_NAME = "store_migrate_manifest.json"

# Directory names skipped wherever they appear, and suffixes skipped on any file.
SKIP_DIRS = {"_cache"}
SKIP_SUFFIXES = (".bak",)
SKIP_NAMES = {".write_probe", ".DS_Store", MANIFEST_NAME}

# The launchd labels that hold the store open for writing. Checked by name against the process
# table rather than by `launchctl list`, because a label can be loaded and its process dead, and
# it is the PROCESS that tears a file mid-copy.
WRITER_HINTS = (
    "prospector.scheduler.run_scheduled",
    "prospector.run",
)


def store_root() -> Path:
    """The store this command operates on. Env first, exactly as the engine resolves it."""
    env = os.environ.get("PROSPECTOR_STORE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "store").resolve()


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if path.name in SKIP_NAMES:
        return True
    return path.name.endswith(SKIP_SUFFIXES)


def walk(root: Path) -> list[Path]:
    """Every file that moves, sorted, so two runs on the same tree produce the same manifest.

    `rglob` yields a name; by the time anything stats it the engine may have moved or deleted
    it. Measured on the first run of this script against the live store: it died on
    `dossiers/5897d00920315892.defer.json`, which the daemon renamed between the listing and the
    stat. `plan` has to survive that — it is the command you run BEFORE stopping the engine, to
    decide whether stopping it is worth it. `pack` does not rely on this tolerance; it refuses
    to run at all while a writer is alive.
    """
    out = []
    for path in root.rglob("*"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if _skip(path, root):
                continue
            path.stat()
        except (OSError, ValueError):
            continue
        out.append(path)
    return sorted(out)


def _size(path: Path) -> int:
    """Size, or 0 for a file that vanished between the walk and here. See `walk`."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def live_writers() -> list[str]:
    """Processes currently able to append to the store. Empty list means it is safe to copy."""
    try:
        ps = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True, text=True,
                            timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        # Cannot tell, so do not claim it is safe. The caller sees this as a blocked copy.
        return ["<could not read the process table>"]
    found = []
    for line in ps.splitlines():
        if any(hint in line for hint in WRITER_HINTS) and "store_migrate" not in line:
            found.append(line.strip()[:120])
    return found


def census(root: Path) -> dict:
    """The counts that make a copy checkable without hashing anything.

    Deliberately counts things the engine cares about rather than bytes alone: a copy can match
    on total size and still be missing every dossier, if one large file arrived and many small
    ones did not.
    """
    files = walk(root)
    db = root / "prospector.db"
    ledger = root / "prospector.jsonl"
    out = {
        "files": len(files),
        "bytes": sum(_size(f) for f in files),
        "dossiers": sum(1 for f in files if f.parent.name == "dossiers"),
        "listings": sum(1 for f in files if f.parent.name == "listings"),
        "ledger_lines": 0,
        "db_tables": 0,
        "db_integrity": "absent",
        "scheduler_flags": sorted(
            p.name for p in (root / "scheduler").glob("*")
            if p.is_file() and p.name.isupper()
        ),
    }
    if ledger.exists():
        with ledger.open("rb") as fh:
            out["ledger_lines"] = sum(1 for _ in fh)
    if db.exists():
        # `PRAGMA integrity_check` is the point of this whole function. A sqlite file that copied
        # byte-perfect is still only a file; the question a migration has to answer is whether
        # the engine can open it and read its own pages back on the new host.
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            out["db_integrity"] = con.execute("PRAGMA integrity_check").fetchone()[0]
            out["db_tables"] = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            con.close()
    return out


def cmd_plan(root: Path) -> int:
    c = census(root)
    print(f"STORE_MIGRATE PLAN source={root}")
    print(f"  files            {c['files']:,}")
    print(f"  bytes            {c['bytes']:,} ({c['bytes'] / 2**30:.2f} GiB)")
    print(f"  dossiers         {c['dossiers']:,}")
    print(f"  listings         {c['listings']:,}")
    print(f"  ledger lines     {c['ledger_lines']:,}")
    print(f"  db tables        {c['db_tables']} integrity={c['db_integrity']}")
    print(f"  scheduler flags  {c['scheduler_flags'] or 'none'}")
    skipped = sum(_size(f) for f in root.rglob("*")
                  if f.is_file() and not f.is_symlink() and _skip(f, root))
    print(f"  skipped          {skipped:,} bytes of cache and .bak")
    writers = live_writers()
    if writers:
        print(f"  WRITERS LIVE     {len(writers)} — `pack` will refuse:")
        for w in writers:
            print(f"                   {w}")
    else:
        print("  writers          none — safe to pack")
    return 0


def cmd_pack(root: Path, out: Path, force: bool) -> int:
    writers = live_writers()
    if writers and not force:
        print("STORE_MIGRATE ABORT the store is being written to right now:", file=sys.stderr)
        for w in writers:
            print(f"  {w}", file=sys.stderr)
        print("  Stop the scheduler and consumer first. A copy taken mid-append truncates the",
              file=sys.stderr)
        print("  last line of prospector.jsonl, which is the file the spend cap is read from.",
              file=sys.stderr)
        print("  `--force` is for a drill against a store nothing is writing.", file=sys.stderr)
        return 2

    files = walk(root)
    manifest = {
        "source": str(root),
        "census": census(root),
        "files": {str(f.relative_to(root)): {"bytes": _size(f), "sha256": sha256(f)}
                  for f in files},
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="store_migrate_"))
    try:
        mpath = tmp / MANIFEST_NAME
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        # `w:gz` and not `w:xz`: the payload is mostly JSON lines and gzip already takes the bulk
        # of it, while xz on a 500 MB tree costs minutes for a fraction more. A cutover window is
        # the wrong place to spend that.
        with tarfile.open(out, "w:gz") as tar:
            tar.add(mpath, arcname=MANIFEST_NAME)
            for f in files:
                tar.add(f, arcname=str(f.relative_to(root)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    size = out.stat().st_size
    c = manifest["census"]
    print(f"STORE_MIGRATE PACK PASS out={out} bytes={size:,} "
          f"files={c['files']:,} dossiers={c['dossiers']:,} "
          f"ledger_lines={c['ledger_lines']:,} db_integrity={c['db_integrity']}")
    print(f"  unpack with: mkdir -p DEST && tar -xzf {out.name} -C DEST")
    print("  then prove it with: store_migrate.py verify DEST")
    return 0


def cmd_verify(dest: Path, sample: int) -> int:
    """Check an unpacked tree against the manifest that travelled inside it.

    Three checks with an outside referent, and one that is deliberately NOT here: comparing the
    destination to itself. Re-hashing what was just written and finding it matches what was just
    written proves the disk works, not that the right bytes arrived.
    """
    mpath = dest / MANIFEST_NAME
    if not mpath.is_file():
        print(f"STORE_MIGRATE VERIFY FAIL no {MANIFEST_NAME} in {dest} — this tree did not "
              f"come from `pack`", file=sys.stderr)
        return 2
    manifest = json.loads(mpath.read_text())
    expected = manifest["files"]

    missing = [rel for rel in expected if not (dest / rel).is_file()]
    extra = [str(p.relative_to(dest)) for p in walk(dest) if str(p.relative_to(dest))
             not in expected]

    # Size on every file — cheap, and catches a truncated transfer, which is the failure a
    # partial copy actually produces. Hashes on a sample, because hashing 500 MB during a
    # cutover window buys less than the ledger and db checks below.
    wrong_size = []
    for rel, meta in expected.items():
        path = dest / rel
        if path.is_file() and path.stat().st_size != meta["bytes"]:
            wrong_size.append(rel)

    import random
    names = sorted(rel for rel in expected if (dest / rel).is_file())
    picked = names if sample <= 0 or sample >= len(names) else random.sample(names, sample)
    wrong_hash = [rel for rel in picked if sha256(dest / rel) != expected[rel]["sha256"]]

    got = census(dest)
    want = manifest["census"]
    drifted = {k: (want[k], got[k]) for k in ("files", "dossiers", "listings", "ledger_lines",
                                              "db_tables", "scheduler_flags")
               if want[k] != got[k]}

    problems = []
    if missing:
        problems.append(f"{len(missing)} missing (first: {missing[:3]})")
    if wrong_size:
        problems.append(f"{len(wrong_size)} wrong size (first: {wrong_size[:3]})")
    if wrong_hash:
        problems.append(f"{len(wrong_hash)} wrong sha256 (first: {wrong_hash[:3]})")
    if got["db_integrity"] != want["db_integrity"]:
        problems.append(f"db integrity {want['db_integrity']!r} -> {got['db_integrity']!r}")
    for key, (w, g) in drifted.items():
        problems.append(f"{key} {w} -> {g}")

    if problems:
        print(f"STORE_MIGRATE VERIFY FAIL dest={dest}", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    print(f"STORE_MIGRATE VERIFY PASS dest={dest} files={got['files']:,} "
          f"dossiers={got['dossiers']:,} ledger_lines={got['ledger_lines']:,} "
          f"hashed={len(picked)}/{len(names)} db_integrity={got['db_integrity']}"
          + (f" extra_files={len(extra)}" if extra else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # --store is accepted on BOTH sides of the subcommand. As a global option only, `pack OUT
    # --store DIR` failed with "unrecognized arguments: --store", which is a true message and a
    # useless one: the option exists, it is simply in the wrong position. That killed the 02:33
    # cutover in phase 5, after the engine had already been stopped. Declaring it in a parent
    # parser makes both orders work, so no caller can get the position wrong again.
    # SUPPRESS, not None. A subparser writes its own defaults into the SAME namespace, so a
    # plain `default=None` here would silently overwrite a --store given before the subcommand
    # with None. SUPPRESS means "if it was not typed, do not touch the attribute at all".
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", default=argparse.SUPPRESS,
                        help="store root (default: PROSPECTOR_STORE_DIR)")
    ap.add_argument("--store", default=None, help="store root (default: PROSPECTOR_STORE_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", parents=[common],
                   help="what would move, and whether it is safe to move it now")
    p = sub.add_parser("pack", parents=[common], help="build the payload and its manifest")
    p.add_argument("out", help="output .tar.gz")
    p.add_argument("--force", action="store_true",
                   help="pack even though something is writing the store (drills only)")
    v = sub.add_parser("verify", parents=[common],
                       help="check an unpacked tree against its manifest")
    v.add_argument("dest", help="directory the payload was unpacked into")
    v.add_argument("--sample", type=int, default=200,
                   help="files to re-hash; 0 hashes every file (default 200)")
    args = ap.parse_args(argv)

    if args.cmd == "verify":
        dest = Path(args.dest).expanduser().resolve()
        if not dest.is_dir():
            print(f"STORE_MIGRATE ABORT no directory at {dest}", file=sys.stderr)
            return 2
        return cmd_verify(dest, args.sample)

    root = Path(args.store).expanduser().resolve() if args.store else store_root()
    if not root.is_dir():
        print(f"STORE_MIGRATE ABORT no store at {root}", file=sys.stderr)
        return 2
    if args.cmd == "plan":
        return cmd_plan(root)
    return cmd_pack(root, Path(args.out).expanduser().resolve(), args.force)


if __name__ == "__main__":
    sys.exit(main())

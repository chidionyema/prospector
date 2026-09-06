#!/usr/bin/env python3
"""Prove the Postgres shadow holds exactly what SQLite holds.

Weeks 1-2 of the engine rewrite (docs/ENGINE_RUST_REWRITE_SPEC.md, section 5) put a
Postgres shadow beside the live SQLite store. A shadow is only worth the trouble if a
command can say it agrees, so this is that command.

WHY IT SHELLS OUT TO psql. The engine's virtualenv has no Postgres driver and the point
of a shadow is to be cheap. Adding psycopg to prospector's dependency set to run a check
that exists to de-risk a rewrite is the wrong trade, so this talks to Postgres the way a
DBA would -- through psql, over a command prefix you pass in. That prefix is a container
exec locally and a plain `psql "$DATABASE_URL"` against Fly, and nothing in this file
changes between the two.

WHY THE FLOAT COMPARISON IS ON BITS, NOT ON VALUES. `composite`, `dense_reward`,
`adversarial_confidence` and `lease_until` are binary64 on both sides. Two doubles that
print the same can differ in the last bit, and a parity check that cannot see that bit is
a parity check that will pass on the day the rewrite starts drifting. Postgres emits
`float8send`, which is the IEEE754 bytes; Python packs the same eight bytes with `struct`.
Equal hex, or it is not parity.

  --init    apply migrations/0001_dossiers.sql to the shadow
  --sync    copy every dossier from SQLite into the shadow
  --check   compare the two row by row, column by column; exit 0 only on total agreement
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "migrations" / "0001_dossiers.sql"

# The default is the local colima container. Docker Desktop was measured using enough
# memory that the founder asked for it gone, so the shadow runs on colima and this default
# matches what `--init` expects to find.
DEFAULT_PSQL = "docker exec -i pg-shadow psql -U shadow -d shadow"


def parse_schema(sql: str) -> list[tuple[str, str]]:
    """Read the column list out of the migration, so the migration stays the one source.

    A column list duplicated in Python is a column list that goes stale the first time
    anyone adds a field, and the check would then pass while silently ignoring it.
    """
    body = re.search(r"CREATE TABLE[^(]*\((.*?)\n\);", sql, re.S)
    if not body:
        raise SystemExit(f"no CREATE TABLE found in {MIGRATION}")
    cols: list[tuple[str, str]] = []
    for line in body.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        parts = line.rstrip(",").split()
        if len(parts) < 2:
            continue
        name = parts[0]
        if name.upper() in ("PRIMARY", "CONSTRAINT", "UNIQUE", "FOREIGN"):
            continue
        rest = " ".join(parts[1:]).upper()
        if "DOUBLE PRECISION" in rest:
            kind = "float"
        elif rest.startswith("INTEGER") or rest.startswith("BIGINT"):
            kind = "int"
        else:
            kind = "text"
        cols.append((name, kind))
    return cols


def run_psql(psql_cmd: str, sql: str) -> str:
    """One psql round trip. Non-zero exit is fatal -- an unreachable shadow is a failure.

    A check that treats "cannot connect" as "nothing to compare" would report parity on a
    machine with no Postgres at all, which is the exact lie this file exists to prevent.
    """
    proc = subprocess.run(
        shlex.split(psql_cmd) + ["-v", "ON_ERROR_STOP=1", "-X", "-q", "-A", "-t"],
        input=sql,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"psql failed (exit {proc.returncode}): {psql_cmd}")
    return proc.stdout


def sqlite_rows(db: Path, cols: list[tuple[str, str]]) -> dict[str, dict]:
    """Every dossier from SQLite, keyed by candidate_id, coerced to the shadow's types.

    SQLite columns are dynamically typed: a REAL column will hand back an int if an int
    was written to it. Coercing here means the comparison is against what Postgres can
    actually hold, not against what SQLite happened to store it as.
    """
    if not db.exists():
        raise SystemExit(f"no SQLite store at {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    names = [c for c, _ in cols]
    try:
        cur = conn.execute(f"SELECT {', '.join(names)} FROM dossiers")
        out: dict[str, dict] = {}
        for row in cur:
            rec = {}
            for name, kind in cols:
                v = row[name]
                if v is None:
                    rec[name] = None
                elif kind == "float":
                    rec[name] = struct.pack(">d", float(v)).hex()
                elif kind == "int":
                    rec[name] = int(v)
                else:
                    rec[name] = str(v)
            out[rec["candidate_id"]] = rec
        return out
    finally:
        conn.close()


def pg_rows(psql_cmd: str, cols: list[tuple[str, str]]) -> dict[str, dict]:
    """The same rows from the shadow, in the same shape, so a dict compare is the answer.

    JSON rather than psql's own column output because JSON keeps NULL and the empty string
    apart. `-A -t` prints both as an empty field, and `path` is a column where that
    difference is the difference between a written dossier and a missing one.
    """
    fields = []
    for name, kind in cols:
        if kind == "float":
            fields.append(f"'{name}', encode(float8send({name}), 'hex')")
        else:
            fields.append(f"'{name}', {name}")
    sql = (
        "SELECT coalesce(json_agg(json_build_object("
        + ", ".join(fields)
        + ")), '[]'::json) FROM dossiers;"
    )
    raw = run_psql(psql_cmd, sql).strip()
    rows = json.loads(raw) if raw else []
    out = {}
    for r in rows:
        for name, kind in cols:
            if r[name] is not None and kind == "float":
                # float8send never emits NULL for a non-null column, but be explicit that
                # the hex is the comparison key on both sides.
                r[name] = str(r[name])
        out[r["candidate_id"]] = r
    return out


def copy_in(psql_cmd: str, cols: list[tuple[str, str]], rows: dict[str, dict]) -> int:
    """COPY the whole table in one stream. INSERT-per-row costs a round trip per dossier.

    Postgres text COPY, so the escaping rules are its own and documented: backslash, tab,
    carriage return and newline are escaped, and \\N is NULL. A float goes over as Python's
    repr, which is the shortest string that round-trips to the same bits.
    """
    names = [c for c, _ in cols]
    by_name = dict(cols)
    lines = [f"COPY dossiers ({', '.join(names)}) FROM STDIN;"]
    for rec in rows.values():
        fields = []
        for name in names:
            v = rec[name]
            if v is None:
                fields.append(r"\N")
            elif by_name[name] == "float":
                fields.append(repr(struct.unpack(">d", bytes.fromhex(v))[0]))
            elif by_name[name] == "int":
                fields.append(str(v))
            else:
                fields.append(
                    v.replace("\\", "\\\\")
                    .replace("\t", "\\t")
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                )
        lines.append("\t".join(fields))
    lines.append(r"\.")
    run_psql(psql_cmd, "\n".join(lines) + "\n")
    return len(rows)


def report(sqlite_data: dict, pg_data: dict, cols: list[tuple[str, str]]) -> int:
    """Print every disagreement, then the verdict. Exit code is the verdict."""
    only_sqlite = sorted(set(sqlite_data) - set(pg_data))
    only_pg = sorted(set(pg_data) - set(sqlite_data))
    mismatches: list[str] = []
    for cid in sorted(set(sqlite_data) & set(pg_data)):
        a, b = sqlite_data[cid], pg_data[cid]
        for name, _ in cols:
            if a[name] != b[name]:
                mismatches.append(f"  {cid} {name}: sqlite={a[name]!r} pg={b[name]!r}")

    print(f"sqlite rows: {len(sqlite_data)}")
    print(f"shadow rows: {len(pg_data)}")
    for cid in only_sqlite[:20]:
        print(f"  missing from shadow: {cid}")
    if len(only_sqlite) > 20:
        print(f"  ... and {len(only_sqlite) - 20} more missing from shadow")
    for cid in only_pg[:20]:
        print(f"  in shadow only: {cid}")
    if len(only_pg) > 20:
        print(f"  ... and {len(only_pg) - 20} more in shadow only")
    for line in mismatches[:40]:
        print(line)
    if len(mismatches) > 40:
        print(f"  ... and {len(mismatches) - 40} more column mismatches")

    bad = len(only_sqlite) + len(only_pg) + len(mismatches)
    if bad:
        print(f"PARITY FAILED: {bad} disagreement(s)")
        return 1
    print(f"PARITY OK: {len(sqlite_data)} dossier(s) agree on all {len(cols)} columns")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psql", default=DEFAULT_PSQL, help="command prefix that runs psql")
    ap.add_argument(
        "--store",
        default=str(Path.home() / ".prospector" / "prospector.db"),
        help="the SQLite store to shadow",
    )
    ap.add_argument("--init", action="store_true", help="apply the migration")
    ap.add_argument("--sync", action="store_true", help="copy SQLite into the shadow")
    ap.add_argument("--check", action="store_true", help="compare, exit non-zero on drift")
    args = ap.parse_args()

    if not (args.init or args.sync or args.check):
        ap.error("pick at least one of --init, --sync, --check")

    cols = parse_schema(MIGRATION.read_text())

    if args.init:
        run_psql(args.psql, MIGRATION.read_text())
        print(f"shadow initialised: dossiers, {len(cols)} columns")

    if args.sync:
        rows = sqlite_rows(Path(args.store), cols)
        run_psql(args.psql, "TRUNCATE dossiers;")
        n = copy_in(args.psql, cols, rows)
        print(f"synced {n} dossier(s) into the shadow")

    if args.check:
        return report(sqlite_rows(Path(args.store), cols), pg_rows(args.psql, cols), cols)
    return 0


if __name__ == "__main__":
    sys.exit(main())

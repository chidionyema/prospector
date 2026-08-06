#!/usr/bin/env python3
"""Lift `candidate.tags["audience"]` out of the dossier JSONs and into the SQLite index.

Generation has stamped the audience persona on nearly every dossier since the audience
rotation landed (generate.py:552), but the index had no column for it until now, so the
only way to ask "which persona actually converts?" was to open ~1.4k JSON files. The new
`dossiers.audience` column closes that, and this backfills the rows written before it.

This is NOT the same kind of operation as tools/backfill_market.py. That one INFERS a value
("every pre-cutover dossier ran the UK-baked prompts, so 'uk' is a recorded fact") and
rewrites the dossier JSON to match. This one infers nothing and writes nothing to disk: it
copies a value the dossier already records into the index beside it. A row whose JSON has no
audience stays empty, because "generation did not stamp one" is itself the finding — 26 of
the 1436 dossiers on disk are in that state, and papering over them would hide it.

The `--apply` path still demands a backup. A single UPDATE across every historical row is a
bulk mutation of the audit trail whether or not each individual value is copied verbatim.

Usage:
    python -m tools.backfill_audience                   # dry run (default)
    python -m tools.backfill_audience --apply           # perform it
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]


def _audience_from_json(path: Path) -> Optional[str]:
    """The persona this dossier records, or None if the file is missing/unreadable/unstamped.

    Normalisation is kept byte-identical to `Candidate.audience` (models.py) on purpose: if
    this stripped or cased differently, backfilled rows and freshly-saved rows would land in
    different GROUP BY buckets for the same persona, which is precisely the per-persona
    question the column exists to answer.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cand = data.get("candidate")
    if not isinstance(cand, dict):
        return None
    tags = cand.get("tags")
    if not isinstance(tags, dict):
        return None
    value = str(tags.get("audience") or "").strip().lower()
    return value or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store-dir", default=str(REPO_ROOT / "store"),
                    help="Store directory (default: <repo>/store)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform the backfill (default is a dry run)")
    args = ap.parse_args()

    store_dir = Path(args.store_dir)
    db_path = store_dir / "prospector.db"
    backup = store_dir / "prospector.db.pre-audience.bak"

    if not db_path.exists():
        print(f"FATAL: no catalogue at {db_path}", file=sys.stderr)
        return 2
    if args.apply and not backup.exists():
        print(f"FATAL: refusing to mutate {db_path.name} with no backup at {backup}.\n"
              f"  Run: cp {db_path} {backup}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
    if "audience" not in cols:
        print("FATAL: the `audience` column does not exist yet. Run the engine once so "
              "store.Store._init_db() applies the additive migration.", file=sys.stderr)
        return 2

    rows = conn.execute(
        "SELECT candidate_id, title, path FROM dossiers "
        "WHERE audience IS NULL OR audience = '' ORDER BY created_at"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]

    resolved: list[tuple[str, str]] = []
    no_file = 0
    unstamped = 0
    for row in rows:
        path = Path(row["path"] or "")
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            # Known population: the index carries rows whose dossier JSON was never written
            # or has since been removed (see the tombstone note in store.py). Counted, not
            # guessed at — there is nowhere to read a persona from.
            no_file += 1
            continue
        value = _audience_from_json(path)
        if value is None:
            unstamped += 1
            continue
        resolved.append((row["candidate_id"], value))

    print(f"catalogue: {db_path}  ({total} rows)")
    print(f"empty:     {len(rows)} row(s) with no audience in the index")
    print(f"resolved:  {len(resolved)} from the dossier JSON on disk")
    print(f"skipped:   {no_file} with no dossier file, {unstamped} whose JSON has no persona")

    if resolved:
        spread = Counter(v for _, v in resolved)
        print("\npersona spread of the rows to be stamped:")
        for name, count in spread.most_common():
            print(f"  {name:<24} {count}")

    if not resolved:
        print("\nnothing to do.")
        return 0

    if not args.apply:
        print("\nDRY RUN — no changes written. Re-run with --apply to perform it.")
        return 0

    conn.executemany(
        "UPDATE dossiers SET audience = ? WHERE candidate_id = ?",
        [(value, cid) for cid, value in resolved],
    )
    conn.commit()
    stamped = conn.execute(
        "SELECT COUNT(*) FROM dossiers WHERE COALESCE(audience, '') != ''"
    ).fetchone()[0]
    conn.close()

    print(f"\napplied: {len(resolved)} row(s) stamped; "
          f"{stamped} of {total} rows now carry a persona. No dossier JSON was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

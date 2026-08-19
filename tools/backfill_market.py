#!/usr/bin/env python3
"""Stamp pre-Epic-D dossiers with the market they were actually generated for.

Every dossier written before the market dimension existed was produced by the UK-baked
prompts (`prompts/query_gen.md`, `verdict.md`, `generate_system.md`) against the UK
authority list. Labelling those rows `uk` is therefore a recorded fact, not a guess —
but it is still a bulk mutation of the audit trail, so it is founder-gated: dry-run by
default, refuses to run without a database backup, and prints exactly what it will do.

Rows created ON or AFTER the cutover are left alone: from that point the engine stamps
the market itself, and an empty value there means something went wrong that a backfill
must not paper over.

Usage:
    python -m tools.backfill_market                     # dry run (default)
    python -m tools.backfill_market --apply             # perform it
    python -m tools.backfill_market --market uk --cutover 2026-07-30T00:00:00Z
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402

DEFAULT_CUTOVER = "2026-07-30T00:00:00Z"


def _rows_to_backfill(conn: sqlite3.Connection, cutover: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT candidate_id, title, path, created_at FROM dossiers "
        "WHERE (market IS NULL OR market = '') AND COALESCE(created_at, '') < ? "
        "ORDER BY created_at",
        (cutover,),
    ).fetchall()


def _patch_dossier_json(path: Path, market: str) -> bool:
    """Rewrite the dossier's candidate.market atomically. Returns True if changed.

    Atomic write (temp then rename) matches store.save() so a kill mid-run can never
    leave a half-written dossier where a whole one used to be.
    """
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    cand = data.get("candidate")
    if not isinstance(cand, dict) or (cand.get("market") or ""):
        return False
    cand["market"] = market
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", default="uk", help="Market code to stamp (default: uk)")
    ap.add_argument("--cutover", default=DEFAULT_CUTOVER,
                    help=f"Only rows created before this ISO timestamp (default: {DEFAULT_CUTOVER})")
    ap.add_argument("--store-dir", default=str(store_root()),
                    help="Store directory (default: <repo>/store)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually perform the backfill (default is a dry run)")
    args = ap.parse_args()

    store_dir = Path(args.store_dir)
    db_path = store_dir / "prospector.db"
    backup = store_dir / "prospector.db.pre-market.bak"

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
    if "market" not in cols:
        print("FATAL: the `market` column does not exist yet. Run the engine once so "
              "store.Store._init_db() applies the additive migration.", file=sys.stderr)
        return 2

    rows = _rows_to_backfill(conn, args.cutover)
    total = conn.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]

    print(f"catalogue: {db_path}  ({total} dossiers)")
    print(f"cutover:   rows created before {args.cutover}")
    print(f"target:    market = {args.market!r}")
    print(f"matched:   {len(rows)} row(s) with no market")
    print("\nwhy this is a fact and not a guess: every pre-cutover dossier was generated "
          "and vetted by the UK-baked prompts against the UK authority list, so 'uk' is "
          "the market those runs actually used.\n")

    if not rows:
        print("nothing to do.")
        return 0

    for row in rows[:5]:
        print(f"  {row['candidate_id']}  {(row['title'] or '')[:58]}")
    if len(rows) > 5:
        print(f"  … and {len(rows) - 5} more")

    if not args.apply:
        print("\nDRY RUN — no changes written. Re-run with --apply to perform it.")
        return 0

    patched = 0
    for row in rows:
        if _patch_dossier_json(Path(row["path"]), args.market):
            patched += 1
    conn.execute(
        "UPDATE dossiers SET market = ? "
        "WHERE (market IS NULL OR market = '') AND COALESCE(created_at, '') < ?",
        (args.market, args.cutover))
    conn.commit()
    conn.close()

    print(f"\napplied: {len(rows)} index row(s) stamped {args.market!r}; "
          f"{patched} dossier JSON file(s) rewritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

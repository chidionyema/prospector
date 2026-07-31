#!/usr/bin/env python3
"""
Sync published pack bundles into the Store.Api local content store.

The engine writes deliverable bundles to ``publish/bundles/<id>/prospector_pack_<short>.zip``.
``LocalContentStorage`` (dev) serves downloads from ``Store.Api/content_store/<ContentKey>``, where
each pack's ``ContentKey`` is ``packs/<id>/<sha256>.zip``. Without this copy a paid download 404s,
because the bytes never land where the API reads them. (In production the engine bridge uploads to
R2 at provisioning; this script is the dev-equivalent and a safety net for a freshly cloned repo.)

It is content-addressed and idempotent: the source bundle's sha256 must equal the hash embedded in
the ContentKey or the copy is refused (a mismatch means the bundle was rebuilt and the pack must be
re-provisioned, not silently shipped). Re-running copies only what is missing or changed.

Usage:
    python3 store_platform/scripts/sync_content_store.py [--listed-only]

Exit status is non-zero if any *listed* pack could not be synced (missing or mismatched bundle),
so it is safe to gate a deploy on this script.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "store_platform" / "src" / "Store.Api"
DB_PATH = API_DIR / "store.db"
DEST_ROOT = API_DIR / "content_store"
BUNDLES_DIR = REPO_ROOT / "publish" / "bundles"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listed-only",
        action="store_true",
        help="Only sync packs with IsListed=1 (what a buyer can actually reach).",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"FATAL: store.db not found at {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    where = "WHERE ContentKey IS NOT NULL AND ContentKey != ''"
    if args.listed_only:
        where += " AND IsListed = 1"
    rows = conn.execute(
        f"SELECT Id, IsListed, ContentKey FROM Packs {where} ORDER BY IsListed DESC, Id"
    ).fetchall()
    conn.close()

    copied = skipped = missing = mismatch = 0
    failed_listed = False

    for pack_id, is_listed, content_key in rows:
        # ContentKey == packs/<id_long>/<sha256>.zip
        parts = content_key.split("/")
        if len(parts) != 3 or parts[0] != "packs":
            print(f"  ?? {pack_id[:8]}  unexpected ContentKey '{content_key}' — skipped")
            if is_listed:
                failed_listed = True
            continue
        id_long, filename = parts[1], parts[2]
        expected_hash = filename.removesuffix(".zip")

        src_dir = BUNDLES_DIR / id_long
        candidates = sorted(src_dir.glob("*.zip")) if src_dir.is_dir() else []
        if not candidates:
            tag = "LISTED" if is_listed else "unlisted"
            print(f"  -- {pack_id[:8]}  [{tag}] no bundle in {src_dir.relative_to(REPO_ROOT)} — MISSING")
            missing += 1
            if is_listed:
                failed_listed = True
            continue

        src = candidates[0]
        actual_hash = sha256(src)
        if actual_hash != expected_hash:
            tag = "LISTED" if is_listed else "unlisted"
            print(
                f"  !! {pack_id[:8]}  [{tag}] hash mismatch (bundle rebuilt?) — MISMATCH, "
                f"re-provision needed\n       expected {expected_hash[:16]}… got {actual_hash[:16]}…"
            )
            mismatch += 1
            if is_listed:
                failed_listed = True
            continue

        dest = DEST_ROOT / content_key
        if dest.exists() and sha256(dest) == expected_hash:
            skipped += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        copied += 1
        print(f"  ok {pack_id[:8]}  -> {dest.relative_to(API_DIR)}")

    print(
        f"\nDone. copied={copied} already-present={skipped} "
        f"missing={missing} mismatch={mismatch} (of {len(rows)} packs)"
    )
    if failed_listed:
        print("FAIL: one or more LISTED packs are not downloadable. Fix before deploy.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

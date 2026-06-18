#!/usr/bin/env python3
"""
Sync published pack bundles into Cloudflare R2 (the content store the Store.Api actually serves
from when R2 is configured).

This is the R2 counterpart of sync_content_store.py. The engine bridge normally uploads each
deliverable to R2 at provisioning (bridge.py step 3.5, R2Uploader); this script is the standalone
catch-up / verify pass — useful when packs were listed without their bundle reaching R2, or to
confirm before a deploy that every listed pack is downloadable.

Content-addressed and idempotent: the R2 object key is packs/<id>/<sha256>.zip. The local bundle's
sha256 must equal the hash in the key or the upload is refused. An object already present with the
right size is left untouched.

Reads R2 credentials from the repo .env (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY /
R2_BUCKET), matching R2ContentStorage (.NET) and R2Uploader (bridge.py).

Usage:
    python3 store_platform/scripts/sync_r2_content.py [--listed-only] [--dry-run]

Exit status is non-zero if any *listed* pack could not be made downloadable.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "store_platform" / "src" / "Store.Api"
DB_PATH = API_DIR / "store.db"
BUNDLES_DIR = REPO_ROOT / "publish" / "bundles"
ENV_PATH = REPO_ROOT / ".env"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listed-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Report only; upload nothing.")
    args = parser.parse_args()

    load_env(ENV_PATH)
    account = os.environ.get("R2_ACCOUNT_ID")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET")
    if not all([account, access, secret, bucket]):
        print("FATAL: R2 credentials incomplete in .env (need R2_ACCOUNT_ID/ACCESS_KEY_ID/"
              "SECRET_ACCESS_KEY/BUCKET).", file=sys.stderr)
        return 2

    try:
        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import ClientError
    except ImportError:
        print("FATAL: boto3 not installed (pip install boto3).", file=sys.stderr)
        return 2

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=BotoConfig(signature_version="s3v4", region_name="auto"),
    )

    conn = sqlite3.connect(DB_PATH)
    where = "WHERE ContentKey IS NOT NULL AND ContentKey != ''"
    if args.listed_only:
        where += " AND IsListed = 1"
    rows = conn.execute(
        f"SELECT Id, IsListed, ContentKey FROM Packs {where} ORDER BY IsListed DESC, Id"
    ).fetchall()
    conn.close()

    uploaded = present = missing = mismatch = 0
    failed_listed = False

    for pack_id, is_listed, content_key in rows:
        parts = content_key.split("/")
        if len(parts) != 3 or parts[0] != "packs":
            print(f"  ?? {pack_id[:8]}  non-pack ContentKey '{content_key}' — skipped")
            continue
        id_long, filename = parts[1], parts[2]
        expected_hash = filename.removesuffix(".zip")
        tag = "LISTED" if is_listed else "unlisted"

        src_dir = BUNDLES_DIR / id_long
        candidates = sorted(src_dir.glob("*.zip")) if src_dir.is_dir() else []
        if not candidates:
            print(f"  -- {pack_id[:8]}  [{tag}] no local bundle in publish/bundles/{id_long} — MISSING")
            missing += 1
            failed_listed |= bool(is_listed)
            continue

        src = candidates[0]
        local_size = src.stat().st_size
        if sha256(src) != expected_hash:
            print(f"  !! {pack_id[:8]}  [{tag}] local hash != key hash — re-provision needed")
            mismatch += 1
            failed_listed |= bool(is_listed)
            continue

        # Already in R2 with the right size?
        try:
            head = client.head_object(Bucket=bucket, Key=content_key)
            if head["ContentLength"] == local_size:
                present += 1
                print(f"  ok {pack_id[:8]}  [{tag}] already in R2")
                continue
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                print(f"  !! {pack_id[:8]}  [{tag}] head_object error: {e} — skipped")
                failed_listed |= bool(is_listed)
                continue

        if args.dry_run:
            print(f"  >> {pack_id[:8]}  [{tag}] WOULD UPLOAD {content_key}")
            uploaded += 1
            continue

        try:
            client.upload_file(str(src), bucket, content_key,
                               ExtraArgs={"ContentType": "application/zip"})
            uploaded += 1
            print(f"  ++ {pack_id[:8]}  [{tag}] uploaded {content_key}")
        except Exception as e:  # noqa: BLE001
            print(f"  !! {pack_id[:8]}  [{tag}] upload failed: {e}")
            failed_listed |= bool(is_listed)

    verb = "would-upload" if args.dry_run else "uploaded"
    print(f"\nDone. {verb}={uploaded} already-present={present} "
          f"missing={missing} mismatch={mismatch} (of {len(rows)} packs)")
    if failed_listed:
        print("FAIL: one or more LISTED packs are not downloadable from R2.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

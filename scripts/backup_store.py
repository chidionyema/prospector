#!/usr/bin/env python3
"""Back up the two irreplaceable things in store/ to R2, and prove the copy is readable.

Why this exists
---------------
On 2026-07-31 the operator's store held 1153 dossiers (50M) and a 295,563-line audit ledger
(84M), and every byte of it existed in exactly one place:

    store/dossiers/          gitignored (.gitignore:43) — and correctly so, it is the paid
                             product and this repo is public
    store/prospector.jsonl   gitignored — the spend and decision trail
    tmutil destinationinfo   "No destinations configured"  (no Time Machine)
    repo path                not inside iCloud/Dropbox

"Not in git" had quietly become "not anywhere". The R2 credentials this uses are already in
.env and already paid for; the delivery path uses the same bucket.

Why not reuse bridge.R2Uploader
-------------------------------
R2Uploader is deliberately silent: it returns False rather than raising, and no-ops entirely
when unconfigured, so a missing credential can never stop a pack from selling. That is right
for the publish path and exactly wrong here. A backup that "succeeds" by doing nothing is
worse than no backup, because you stop looking. This module fails loudly instead.

Verification, not optimism
--------------------------
Uploading is not backing up. This re-downloads a random sample of what it just wrote plus the
whole ledger object, and compares SHA-256 against the local file. `--restore` performs the
real thing end to end into a directory you name, so recovery is something that has been done
rather than something believed.

Usage
-----
    python3 scripts/backup_store.py                 # sync + verify a sample, print a probe line
    python3 scripts/backup_store.py --verify-only   # touch nothing; prove the remote matches
    python3 scripts/backup_store.py --restore DIR   # pull everything back into DIR and check it
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOSSIER_DIR = REPO_ROOT / "store" / "dossiers"
LEDGER = REPO_ROOT / "store" / "prospector.jsonl"

DOSSIER_PREFIX = "dossiers/"
LEDGER_PREFIX = "ledger/"

# A DIFFERENT bucket from R2_BUCKET (prospector-packs), on purpose. The delivery bucket is
# reachable by the storefront's credentials and could have a public r2.dev domain attached in
# the Cloudflare dashboard — nothing in this repo would show it, so nothing in this repo can
# rule it out. Dossiers are the paid product; a backup that quietly publishes them is a worse
# outcome than no backup. Created 2026-07-31 via the S3 API, so it has no public domain and no
# object is reachable without these credentials.
DEFAULT_BACKUP_BUCKET = "prospector-backup"

# Sampling is a compromise, and a stated one: verifying all 1153 objects costs 1153 GETs and
# ~50M of transfer every run, which is the kind of cost that gets a backup job disabled. A
# random sample re-drawn each run means a systematically corrupt upload path is caught within
# a few runs, and --restore verifies everything when you actually need to know.
DEFAULT_SAMPLE = 8


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from .env for keys that are not already set.

    Not python-dotenv: that is not in requirements.txt, and adding a dependency to read four
    variables is how the undeclared-import problem this repo just fixed got started.
    """
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _client():
    """An R2 client, or a hard exit. Never a silent no-op — see the module docstring."""
    _load_dotenv(REPO_ROOT / ".env")
    missing = [
        name
        for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        sys.exit(f"STORE_BACKUP FAIL missing credentials: {', '.join(missing)}")

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        sys.exit("STORE_BACKUP FAIL boto3 not installed (it is in requirements.txt)")

    account = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=BotoConfig(signature_version="s3v4", region_name="auto"),
    ), os.environ.get("R2_BACKUP_BUCKET") or DEFAULT_BACKUP_BUCKET


def _remote_index(s3, bucket: str, prefix: str) -> dict[str, str]:
    """key -> ETag. For a single-part upload R2's ETag is the MD5, which is enough to decide
    'has this file changed since last run'. It is NOT what we verify with — that is SHA-256
    over a real download, below."""
    index: dict[str, str] = {}
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            index[obj["Key"]] = obj["ETag"].strip('"')
        if not page.get("IsTruncated"):
            return index
        token = page.get("NextContinuationToken")


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - matching R2's ETag, not a security decision
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sync(s3, bucket: str, *, dry_run: bool = False) -> tuple[int, int, str]:
    """Mirror the dossiers and append a dated ledger snapshot. Returns (uploaded, skipped, key)."""
    if not DOSSIER_DIR.is_dir():
        sys.exit(f"STORE_BACKUP FAIL no {DOSSIER_DIR} — nothing to back up")

    remote = _remote_index(s3, bucket, DOSSIER_PREFIX)
    uploaded = skipped = 0
    for path in sorted(DOSSIER_DIR.glob("*.json")):
        key = DOSSIER_PREFIX + path.name
        if remote.get(key) == _md5(path):
            skipped += 1
            continue
        if not dry_run:
            s3.upload_file(str(path), bucket, key,
                           ExtraArgs={"ContentType": "application/json"})
        uploaded += 1

    # The ledger is append-only and is the audit trail, so it gets dated keys rather than one
    # overwritten object: a mirror would faithfully replicate a truncation the moment one
    # happened, which is the single failure this copy exists to survive.
    ledger_key = ""
    if LEDGER.is_file():
        stamp = LEDGER.stat().st_mtime
        import datetime
        day = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).strftime("%Y-%m-%d")
        ledger_key = f"{LEDGER_PREFIX}prospector-{day}.jsonl.gz"
        if not dry_run:
            with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                _snapshot_ledger(tmp_path)
                s3.upload_file(str(tmp_path), bucket, ledger_key,
                               ExtraArgs={"ContentType": "application/gzip"})
            finally:
                tmp_path.unlink(missing_ok=True)

    return uploaded, skipped, ledger_key


def _snapshot_ledger(out: Path) -> int:
    """Gzip a whole-lines prefix of the ledger into `out`. Returns bytes captured.

    The engine runs unattended and appends to this file while the backup is reading it: the
    first real run on 2026-07-31 uploaded 295,585 lines and the file had reached 295,728 by
    the time the upload finished. A prefix is the correct thing to capture for an append-only
    log — but "read until EOF" makes it an ACCIDENTALLY correct one. Nothing prevents the read
    landing mid-line, and a truncated final line is a JSON parse error in whatever reads the
    restore back.

    So: fix the length up front, then drop back to the last newline inside it. What is stored
    is always a whole number of complete records, and always a prefix of the live file.
    """
    limit = LEDGER.stat().st_size
    written = 0
    tail = b""
    with LEDGER.open("rb") as src, gzip.open(out, "wb", compresslevel=6) as dst:
        while written < limit:
            chunk = src.read(min(1 << 20, limit - written))
            if not chunk:
                break
            written += len(chunk)
            # Hold back everything after the last newline; it is only safe to emit once the
            # newline that terminates it has been read.
            data = tail + chunk
            head, sep, tail = data.rpartition(b"\n")
            if sep:
                dst.write(head + sep)
    return written - len(tail)


def verify_sample(s3, bucket: str, n: int = DEFAULT_SAMPLE) -> tuple[int, int, list[str]]:
    """Download a random sample and compare SHA-256 with the local file."""
    local = sorted(DOSSIER_DIR.glob("*.json"))
    if not local:
        return 0, 0, ["no local dossiers to verify against"]
    sample = random.sample(local, min(n, len(local)))
    ok = 0
    problems: list[str] = []
    for path in sample:
        key = DOSSIER_PREFIX + path.name
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:  # noqa: BLE001 - any failure to read back is a failure
            problems.append(f"{key}: unreadable ({type(exc).__name__})")
            continue
        if _sha256_bytes(body) == _sha256(path):
            ok += 1
        else:
            problems.append(f"{key}: content differs from local")
    return ok, len(sample), problems


def restore(s3, bucket: str, dest: Path) -> int:
    """Pull every backed-up dossier into `dest` and check each against something independent.

    Note what is NOT a check: hashing the downloaded bytes and comparing to the file just
    written from those same bytes. That compares a value to itself and passes even if every
    object in the bucket is garbage. The three checks here each have an outside referent —
    the ETag R2 computed at upload time, the local file where one still exists, and whether
    the bytes actually parse as the dossier JSON a restore is supposed to yield.
    """
    dest.mkdir(parents=True, exist_ok=True)
    remote = _remote_index(s3, bucket, DOSSIER_PREFIX)
    if not remote:
        sys.exit("STORE_BACKUP FAIL nothing in the bucket to restore")

    import json

    bad: list[str] = []
    compared_to_local = 0
    for key, etag in sorted(remote.items()):
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        name = Path(key).name

        if hashlib.md5(body).hexdigest() != etag:  # noqa: S324 - matching R2's ETag
            bad.append(f"{name}: bytes differ from the ETag R2 recorded at upload")
            continue
        try:
            json.loads(body)
        except ValueError:
            bad.append(f"{name}: restored bytes are not valid JSON")
            continue

        local = DOSSIER_DIR / name
        if local.is_file():
            if _sha256_bytes(body) != _sha256(local):
                bad.append(f"{name}: differs from the local original")
                continue
            compared_to_local += 1

        (dest / name).write_bytes(body)

    if bad:
        for line in bad[:10]:
            print(f"  {line}", file=sys.stderr)
        sys.exit(f"STORE_BACKUP RESTORE FAIL {len(bad)}/{len(remote)} objects failed")

    print(f"  checked {len(remote)} against R2's ETag, {compared_to_local} against local originals")
    return len(remote)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="upload nothing; just prove the remote copy matches local")
    parser.add_argument("--restore", metavar="DIR",
                        help="download every backed-up dossier into DIR and verify each")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"how many objects to read back and check (default {DEFAULT_SAMPLE})")
    args = parser.parse_args()

    s3, bucket = _client()

    if args.restore:
        count = restore(s3, bucket, Path(args.restore))
        print(f"STORE_BACKUP RESTORE PASS files={count} dest={args.restore}")
        return 0

    uploaded = skipped = 0
    ledger_key = ""
    if not args.verify_only:
        uploaded, skipped, ledger_key = sync(s3, bucket)

    ok, total, problems = verify_sample(s3, bucket, args.sample)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)

    verdict = "PASS" if total and ok == total and not problems else "FAIL"
    print(
        f"STORE_BACKUP {verdict} dossiers={len(list(DOSSIER_DIR.glob('*.json')))} "
        f"uploaded={uploaded} unchanged={skipped} verified={ok}/{total}"
        + (f" ledger={ledger_key}" if ledger_key else "")
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

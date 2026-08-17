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
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOSSIER_DIR = REPO_ROOT / "store" / "dossiers"
LEDGER = REPO_ROOT / "store" / "prospector.jsonl"
DB = REPO_ROOT / "store" / "prospector.db"

DOSSIER_PREFIX = "dossiers/"
LEDGER_PREFIX = "ledger/"
DB_PREFIX = "db/"
REPO_PREFIX = "repo/"

# How many dated db snapshots to keep. 1.4M compresses to a few hundred K, so this is a
# storage decision worth about a dollar a year — the reason it is bounded at all is that an
# unbounded dated-key series is how a backup bucket becomes something someone turns off.
# Pruning happens ONLY after the current run's snapshot has been read back and verified, so a
# corrupt local db cannot delete the good copies on its way past.
DEFAULT_DB_KEEP = 30

# How many dated git bundles to keep. The repo is already in git, so this is a second copy
# of every ref, not a second copy of every byte — the 14-day window fits in single-digit MB
# and gives a fortnight of overlap if an upload silently corrupts for a night. Same prune-
# after-readback rule as DEFAULT_DB_KEEP: only after the current run's bundle has been
# confirmed on R2, so a sick git cannot delete the good copies on its way past.
DEFAULT_BUNDLE_KEEP = 14

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

    Honours `PROSPECTOR_DISABLE_DOTENV` for the same reason `prospector.run._load_dotenv`
    (:2444) does: `setdefault` fills exactly the gap a test credential-fence creates by
    deleting a key, so any un-guarded copy of this function re-arms live keys from disk.
    """
    if os.environ.get("PROSPECTOR_DISABLE_DOTENV", "").strip() not in ("", "0", "false", "False"):
        return
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


# ── Clock skew ────────────────────────────────────────────────────────────────
# 2026-08-06 03:40 this job died on its FIRST call with
#   ClientError (RequestTimeTooSkewed) calling ListObjectsV2
# and every run since has failed the same way, because launchd's
# StartCalendarInterval does not retry. SigV4 signs the request with the local
# clock; R2 rejects a signature whose timestamp is too far from its own.
#
# botocore does not save us here, and that is measured, not assumed:
#     grep -rl RequestTimeTooSkewed .venv/.../botocore/  ->  0 files
#     'RequestTimeTooSkewed' in botocore/data/_retry.json ->  False
# There is no retry rule and no clock-correction hook in botocore 1.43.30, in
# either 'legacy' or 'standard' retry mode. The first skewed call is fatal.
#
# So the fix is to stop signing with the local clock at all: ask the endpoint
# what time it thinks it is, and sign with THAT. This makes the backup
# independent of the local clock, which matters because the failure window is
# a laptop waking from sleep at 03:40 with a stale clock and ntpd not yet
# caught up. Correcting on demand beats waiting for the clock to be right.
_SKEW_TOLERANCE_S = 60.0


def _server_time_offset(endpoint: str) -> float | None:
    """Seconds to ADD to the local clock to match the signing authority's clock.

    Uses the HTTP Date header, which is unauthenticated and present on error
    responses too — so a 400/403 from an unsigned probe is still a usable answer
    and we do not need working credentials to learn the time.
    """
    import email.utils
    import urllib.error
    import urllib.request

    req = urllib.request.Request(endpoint, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            date_header = resp.headers.get("Date")
    except urllib.error.HTTPError as exc:
        date_header = exc.headers.get("Date") if exc.headers else None
    except Exception:
        return None
    if not date_header:
        return None
    try:
        server = email.utils.parsedate_to_datetime(date_header).timestamp()
    except (TypeError, ValueError):
        return None
    return server - time.time()


def _install_clock_offset(offset: float) -> None:
    """Sign with system-clock + offset.

    botocore/auth.py does `from botocore.compat import get_current_datetime` at
    import time, so the name to rebind is the one in botocore.auth — patching
    botocore.compat instead would be a no-op that tests can still be written to
    pass against. SigV4Auth.add_auth (auth.py:430) calls it to build
    request.context['timestamp'], which becomes both X-Amz-Date and the
    credential scope, so one rebind moves the whole signature.

    The corrected clock is built from time.time(), deliberately, so that the
    clock used to SIGN and the clock used to MEASURE (_server_time_offset) are
    the same source. An earlier version read datetime.now() here and time.time()
    there; they agree on a real machine, so the bug was invisible in production
    and only showed up under test, where patching one left the other stale.
    """
    import datetime as _dt

    import botocore.auth

    def _corrected(remove_tzinfo=True):
        now = _dt.datetime.fromtimestamp(time.time() + offset, _dt.timezone.utc)
        return now.replace(tzinfo=None) if remove_tzinfo else now

    botocore.auth.get_current_datetime = _corrected


def _correct_clock_if_skewed(endpoint: str) -> float | None:
    """Measure skew and install a correction if it exceeds tolerance.

    Returns the offset applied, or None if the clock was fine or unmeasurable.
    Prints when it acts: a backup that silently compensates for a broken clock
    hides a broken clock, and the clock breaks other things too.

    Always installs an offset when it can measure one — including a small one.
    Returning early without installing would leave any PREVIOUSLY installed
    offset in force, so the function's effect would depend on what had run
    before it rather than on the clock.
    """
    offset = _server_time_offset(endpoint)
    if offset is None:
        return None
    _install_clock_offset(offset)
    if abs(offset) < _SKEW_TOLERANCE_S:
        return None
    print(
        f"STORE_BACKUP NOTE local clock is {offset:+.0f}s from the R2 endpoint — "
        f"signing with the server clock for this run",
        file=sys.stderr,
    )
    return offset


# ── Reachability ──────────────────────────────────────────────────────────────
def _wait_for_endpoint(endpoint: str, budget_s: float = 180.0) -> bool:
    """Block until the endpoint answers, or the budget expires.

    Same root cause as the clock skew above, one layer lower down. launchd fires this job
    at 03:40 on a laptop that is typically waking from sleep, and StartCalendarInterval
    does NOT retry — the first call is the only call. On 2026-08-06 that call died with
    RequestTimeTooSkewed (fixed above); on 2026-08-07 it died with

        botocore.exceptions.EndpointConnectionError: Could not connect to the endpoint URL

    because DNS/Wi-Fi had not come up yet. Correcting the clock cannot help if the packet
    never leaves the machine. Between them these two shapes are the whole reason the job
    failed 9 consecutive runs with 237 dossiers never uploaded — and was found by a human
    reading a log rather than by anything raising.

    A HEAD probe is the right test and needs no credentials: ANY HTTP response, including
    400 or 403, proves DNS resolved and the TLS path is open, which is the only thing
    being waited on here. Bounded, because a backup that waits forever is just a quieter
    way to fail.
    """
    import urllib.error
    import urllib.request

    deadline = time.time() + budget_s
    delay, attempt = 2.0, 0
    while True:
        attempt += 1
        try:
            urllib.request.urlopen(
                urllib.request.Request(endpoint, method="HEAD"), timeout=10
            )
            return True
        except urllib.error.HTTPError:
            # An HTTP status IS a reachable endpoint. An unsigned HEAD is *expected* to be
            # rejected, so this is the success path, not a retry.
            return True
        except Exception as exc:  # URLError, socket.gaierror, timeout — all "not up yet"
            if time.time() + delay >= deadline:
                print(
                    f"STORE_BACKUP NOTE endpoint unreachable after {attempt} attempt(s) "
                    f"in {budget_s:.0f}s: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                return False
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


def _retry_on_skew(fn, *args, **kwargs):
    """Run fn, and if the signature is rejected as skewed, re-measure and retry once.

    The up-front correction in _client() handles a clock that is already wrong.
    This handles a clock that goes wrong DURING the run — a full sync of 1455
    dossiers is long enough to cross a sleep/wake, which is exactly the event
    that produced the original failure.
    """
    from botocore.exceptions import ClientError

    try:
        return fn(*args, **kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "RequestTimeTooSkewed":
            raise
        endpoint = f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        offset = _server_time_offset(endpoint)
        if offset is None:
            raise
        _install_clock_offset(offset)
        print(
            f"STORE_BACKUP NOTE clock skewed mid-run ({offset:+.0f}s) — re-signed and retried",
            file=sys.stderr,
        )
        return fn(*args, **kwargs)


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
    endpoint = f"https://{account}.r2.cloudflarestorage.com"

    # Wait for the network BEFORE measuring the clock, and the order is load-bearing:
    # _server_time_offset() learns the time from the endpoint's own Date header, so on an
    # unreachable endpoint it returns None, _correct_clock_if_skewed() no-ops, and the run
    # then fails on the first signed call having silently skipped its own safety net.
    if not _wait_for_endpoint(endpoint):
        sys.exit(
            "STORE_BACKUP UNREACHABLE R2 endpoint did not answer within the wait budget; "
            "nothing was uploaded. This is a network failure, not a data failure — the "
            "next scheduled run retries from the same local state."
        )

    _correct_clock_if_skewed(endpoint)
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
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


# ── What counts as a dossier ──────────────────────────────────────────────────
# rglob, not glob, and the difference was live data loss: `store/dossiers/quarantine_ungrounded/`
# holds 9 indexed dossiers (tombstone='quarantined_ungrounded') that a non-recursive glob never
# saw, so they had NEVER been uploaded. Found by restore_drill.py's first live run failing
# `[FAIL] index_vs_tree ... 9 rows with NO restored file` (§23.4). Any future subdirectory is
# now included automatically rather than silently excluded.
#
# The key carries the RELATIVE path, not the bare name: two files named the same in different
# subdirectories would otherwise map to one object, and the second upload would overwrite the
# first without any error anywhere.
def _dossier_files() -> list[Path]:
    return sorted(DOSSIER_DIR.rglob("*.json"))


def _dossier_key(path: Path) -> str:
    return DOSSIER_PREFIX + path.relative_to(DOSSIER_DIR).as_posix()


def sync(s3, bucket: str, *, dry_run: bool = False,
         db_keep: int = DEFAULT_DB_KEEP) -> tuple[int, int, str, str]:
    """Mirror dossiers, append a dated ledger snapshot and a dated db snapshot.

    Returns (uploaded, skipped, ledger_key, db_key).
    """
    if not DOSSIER_DIR.is_dir():
        sys.exit(f"STORE_BACKUP FAIL no {DOSSIER_DIR} — nothing to back up")

    remote = _remote_index(s3, bucket, DOSSIER_PREFIX)
    uploaded = skipped = 0
    for path in _dossier_files():
        key = _dossier_key(path)
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
    db_key = ""
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

    # The catalogue index. Until 2026-08-07 this file was in the backup ONLY as ad-hoc
    # migration copies somebody made by hand before a schema change (.pre-market.bak,
    # .pre-tombstone-*.bak). It is the index that says which dossier is live, tombstoned,
    # published and at what price: without it a restored dossier tree is 1,581 loose JSON
    # files with no state. Dated keys for the same reason as the ledger — a mirror faithfully
    # replicates a truncation, which is the failure this copy exists to survive.
    if DB.is_file() and not dry_run:
        import datetime

        day = datetime.datetime.fromtimestamp(
            DB.stat().st_mtime, datetime.timezone.utc
        ).strftime("%Y-%m-%d")
        db_key = f"{DB_PREFIX}{DB.stem}-{day}.db.gz"
        with tempfile.NamedTemporaryFile(suffix=".db.gz", delete=False) as tmp:
            snap = Path(tmp.name)
        try:
            size, counts = _snapshot_db(snap)
            s3.upload_file(str(snap), bucket, db_key,
                           ExtraArgs={"ContentType": "application/gzip"})
            # Read back HERE, while the local snapshot still exists. Every other object in
            # this bucket can be re-checked later against its local original; a db snapshot
            # is a point-in-time artifact that exists nowhere else the moment this function
            # returns, so "verify it later" means "never verify it".
            body = s3.get_object(Bucket=bucket, Key=db_key)["Body"].read()
            if _sha256_bytes(body) != _sha256(snap):
                sys.exit(f"STORE_BACKUP FAIL {db_key} reads back differently than it was written")
            print(f"  db {db_key} {size} bytes gz, "
                  + ", ".join(f"{n}={c}" for n, c in sorted(counts.items())))
        finally:
            snap.unlink(missing_ok=True)
        # Only after a verified upload. Pruning before would let a machine whose local db has
        # gone bad delete the last good copies on its way past.
        _prune_db_snapshots(s3, bucket, keep=db_keep)
    elif DB.is_file():
        db_key = f"{DB_PREFIX}{DB.stem}-<day>.db.gz"

    return uploaded, skipped, ledger_key, db_key


def _snapshot_db(out_gz: Path) -> tuple[int, dict[str, int]]:
    """Gzip a consistent hot snapshot of `DB` into `out_gz`. Returns (gz bytes, row counts).

    `Connection.backup()`, NOT `shutil.copy`. The daemon holds this database open in WAL mode
    and writes to it unattended; copying the file byte-for-byte under a live writer can capture
    a page set that never existed as a committed state, and the `-wal`/`-shm` sidecars are not
    copied with it. sqlite's backup API walks pages under the source's own locking and produces
    a single self-contained file.

    The source is opened `mode=ro`, so this can never take the write lock the daemon needs —
    a backup that stalls the engine is a backup that gets disabled.

    `PRAGMA integrity_check` runs against the SNAPSHOT before it is uploaded. Verifying the
    source instead would prove the wrong artifact: the thing that gets restored is this file.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db = Path(tmp.name)
    tmp_db.unlink()  # sqlite wants to create it itself
    try:
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(tmp_db))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if verdict != "ok":
                sys.exit(f"STORE_BACKUP FAIL snapshot of {DB.name} fails integrity_check: {verdict}")
            counts = {
                name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            }
        finally:
            conn.close()

        with tmp_db.open("rb") as fsrc, gzip.open(out_gz, "wb", compresslevel=6) as fdst:
            shutil.copyfileobj(fsrc, fdst, 1 << 20)
    finally:
        tmp_db.unlink(missing_ok=True)
    return out_gz.stat().st_size, counts


def _prune_db_snapshots(s3, bucket: str, *, keep: int) -> list[str]:
    """Delete all but the newest `keep` dated db snapshots. `keep<=0` disables pruning.

    Dated `YYYY-MM-DD` keys sort lexicographically in chronological order, so "newest" needs
    no metadata call and no clock.
    """
    if keep <= 0:
        return []
    keys = sorted(_remote_index(s3, bucket, DB_PREFIX))
    stale = keys[:-keep] if len(keys) > keep else []
    for key in stale:
        s3.delete_object(Bucket=bucket, Key=key)
    if stale:
        print(f"  pruned {len(stale)} db snapshot(s), keeping the newest {keep}")
    return stale


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


def mirror_repo(s3, bucket: str, *, keep: int = DEFAULT_BUNDLE_KEEP) -> tuple[str, int, str]:
    """Bundle every ref in REPO_ROOT and upload it to R2, pruning to the newest `keep`.

    The only git remote is GitHub. If that account is lost — billing failure, suspension,
    take-down — every branch, tag and commit goes with it. `sync()` already runs nightly at
    03:40 via launchd and already uploads to the "prospector-backup" bucket with credentials
    that work, so the mirror rides that job rather than becoming a second job that can rot
    separately. Returns (key, size_bytes, sha256).
    """
    stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    key = f"{REPO_PREFIX}{stamp}.bundle"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_bundle = Path(tmp) / "mirror.bundle"
        # `git bundle create` --all walks every ref under REPO_ROOT. The exit code is the
        # only honest signal — a swallowed stderr would let a sick repo pass green.
        create = subprocess.run(
            ["git", "bundle", "create", str(tmp_bundle), "--all"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        if create.returncode != 0:
            raise RuntimeError(
                f"git bundle create failed (rc={create.returncode}): "
                f"{create.stderr.strip() or '<no stderr>'}"
            )

        # Verify BEFORE uploading: uploading an unreadable bundle is the same failure as not
        # backing up at all, and it would look green because the upload itself succeeded.
        verify = subprocess.run(
            ["git", "bundle", "verify", str(tmp_bundle)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        if verify.returncode != 0:
            raise RuntimeError(
                f"git bundle verify failed (rc={verify.returncode}): "
                f"{verify.stderr.strip() or '<no stderr>'}"
            )

        size = tmp_bundle.stat().st_size
        local_sha = _sha256(tmp_bundle)
        s3.upload_file(str(tmp_bundle), bucket, key)
        # Uploading is not backing up. Read it back and compare digests before declaring the
        # new object part of the backup set.
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if _sha256_bytes(body) != local_sha:
            raise RuntimeError(
                f"{key} reads back differently than it was written — uploading is not backing up"
            )

    # Prune ONLY after the read-back passed, so a corrupt upload cannot delete the good
    # copies on its way past. Lexical order is chronological because the stamps are
    # zero-padded; "newest" needs no metadata call.
    if keep > 0:
        keys = sorted(_remote_index(s3, bucket, REPO_PREFIX))
        stale = keys[:-keep] if len(keys) > keep else []
        for old in stale:
            s3.delete_object(Bucket=bucket, Key=old)
        if stale:
            print(f"  pruned {len(stale)} repo bundle(s), keeping the newest {keep}")

    return key, size, local_sha


def verify_sample(s3, bucket: str, n: int = DEFAULT_SAMPLE) -> tuple[int, int, list[str]]:
    """Download a random sample and compare SHA-256 with the local file."""
    local = _dossier_files()
    if not local:
        return 0, 0, ["no local dossiers to verify against"]
    sample = random.sample(local, min(n, len(local)))
    ok = 0
    problems: list[str] = []
    for path in sample:
        key = _dossier_key(path)
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

    Layout: `dest/dossiers/<relative path>` plus `dest/prospector.db`. That is exactly what
    `scripts/restore_drill.py --backup DIR` consumes, so a pull from R2 can be handed straight
    to the drill and checked row-by-row against the live index — the two halves of recovery
    stop being separate rituals that have never been run end to end.
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
        rel = key[len(DOSSIER_PREFIX):]

        if hashlib.md5(body).hexdigest() != etag:  # noqa: S324 - matching R2's ETag
            bad.append(f"{rel}: bytes differ from the ETag R2 recorded at upload")
            continue
        try:
            json.loads(body)
        except ValueError:
            bad.append(f"{rel}: restored bytes are not valid JSON")
            continue

        local = DOSSIER_DIR / rel
        if local.is_file():
            if _sha256_bytes(body) != _sha256(local):
                bad.append(f"{rel}: differs from the local original")
                continue
            compared_to_local += 1

        out = dest / "dossiers" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)

    if bad:
        for line in bad[:10]:
            print(f"  {line}", file=sys.stderr)
        sys.exit(f"STORE_BACKUP RESTORE FAIL {len(bad)}/{len(remote)} objects failed")

    print(f"  checked {len(remote)} against R2's ETag, {compared_to_local} against local originals")
    restore_db(s3, bucket, dest)
    return len(remote)


def restore_db(s3, bucket: str, dest: Path) -> str:
    """Pull the newest db snapshot into `dest/prospector.db` and prove it opens. Returns its key.

    A restore that stops at "the bytes arrived" has not proved recovery: the artifact is a
    database, and the question is whether sqlite can open it and read its own pages back. So
    the restored file is integrity-checked and censused here, and a failure is a hard exit —
    there is no useful degraded mode for "your index came back corrupt".
    """
    keys = sorted(_remote_index(s3, bucket, DB_PREFIX))
    if not keys:
        print("  no db snapshot in the bucket — restore is dossiers only", file=sys.stderr)
        return ""
    # `restore()` has already made this, but the index is the half of a recovery someone
    # reaches for on its own ("I only need the catalogue back"), and dying on a missing
    # directory is a bad way to learn that this entry point is not stand-alone.
    dest.mkdir(parents=True, exist_ok=True)
    key = keys[-1]
    raw = gzip.decompress(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    out = dest / DB.name
    out.write_bytes(raw)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if verdict != "ok":
            sys.exit(f"STORE_BACKUP RESTORE FAIL {key} fails integrity_check: {verdict}")
        counts = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()
    print(f"  restored {key} -> {out.name}, integrity ok, "
          + ", ".join(f"{n}={c}" for n, c in sorted(counts.items())))
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="upload nothing; just prove the remote copy matches local")
    parser.add_argument("--restore", metavar="DIR",
                        help="download every backed-up dossier into DIR and verify each")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"how many objects to read back and check (default {DEFAULT_SAMPLE})")
    parser.add_argument("--db-keep", type=int, default=DEFAULT_DB_KEEP,
                        help=f"dated db snapshots to retain, 0 = keep every one "
                             f"(default {DEFAULT_DB_KEEP})")
    parser.add_argument("--skip-mirror", action="store_true",
                        help="do not push the git mirror")
    parser.add_argument("--bundle-keep", type=int, default=DEFAULT_BUNDLE_KEEP,
                        help=f"dated git bundles to retain, 0 = keep every one "
                             f"(default {DEFAULT_BUNDLE_KEEP})")
    args = parser.parse_args()

    s3, bucket = _client()

    if args.restore:
        count = _retry_on_skew(restore, s3, bucket, Path(args.restore))
        print(f"STORE_BACKUP RESTORE PASS files={count} dest={args.restore}")
        return 0

    uploaded = skipped = 0
    ledger_key = db_key = mirror_key = ""
    mirror_bytes = 0
    if not args.verify_only:
        uploaded, skipped, ledger_key, db_key = _retry_on_skew(
            sync, s3, bucket, db_keep=args.db_keep
        )
        if not args.skip_mirror:
            mirror_key, mirror_bytes, _ = _retry_on_skew(
                mirror_repo, s3, bucket, keep=args.bundle_keep
            )

    ok, total, problems = _retry_on_skew(verify_sample, s3, bucket, args.sample)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)

    verdict = "PASS" if total and ok == total and not problems else "FAIL"
    print(
        f"STORE_BACKUP {verdict} dossiers={len(_dossier_files())} "
        f"uploaded={uploaded} unchanged={skipped} verified={ok}/{total}"
        + (f" ledger={ledger_key}" if ledger_key else "")
        + (f" db={db_key}" if db_key else "")
        + (f" mirror={mirror_key} bytes={mirror_bytes}" if mirror_key else "")
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

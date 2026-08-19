"""Offsite backup — prove there is a second copy of the data you cannot rebuild.

Generic engine. It knows nothing about this business: every host, path, bucket and interval
comes from the declaration file (default `ops/config/offsite_backup.yaml`). See
`docs/OPS_AUTOMATION_PRINCIPLES.md` for the contract this implements.

What it is for. Hosting providers take snapshots, and a snapshot is not a backup: it lives in
the same account as the thing it protects, it has a retention window, and nobody has ever
restored it. This automation copies declared sources out of that account into object storage
you control, verifies the copy is readable before it counts, and — the part that matters on a
normal day — answers "is there a fresh copy right now?" as a measurement rather than a belief.

Interface (the standard shape, `OPS_AUTOMATION_PRINCIPLES.md` R2):

    python -m ops.automations.offsite_backup                 # read-only: how old is each copy?
    python -m ops.automations.offsite_backup --json          # what the console calls
    python -m ops.automations.offsite_backup --fix           # take a backup now
    python -m ops.automations.offsite_backup --config PATH   # a different declaration

Exit codes: 0 every source has a fresh copy, 1 at least one is stale or missing, 2 could not
establish (no declaration, no credentials, storage unreachable, clock too skewed to sign).

Read-only is the default because the monitor is the thing that runs every hour; `--fix` costs
a transfer and needs the host CLI to be logged in. Nothing here ever writes to the source.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the declaration format is YAML by design
    yaml = None  # type: ignore[assignment]

AUTOMATION = "offsite_backup"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2

DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_KEEP = 30
DEFAULT_FETCH_TIMEOUT_S = 300.0

# A signed request whose timestamp is far from the server's is rejected as a bad signature,
# which reads as a credentials failure. Measured once already on this machine
# (memory: local-clock-skew-fakes-presign-403), so the skew is checked before blaming the keys.
CLOCK_SKEW_TOLERANCE_S = 60.0

_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


class CannotEstablish(Exception):
    """The check could not run. Reported as `unknown`, never as clean."""


@dataclass
class Source:
    """One thing that must exist in two places."""

    name: str
    key: str
    fetch: list[str]
    why: str = ""
    verify: str = "nonempty"
    keep: int = DEFAULT_KEEP
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS


@dataclass
class Declaration:
    """The business facts. Everything startup-specific lives here, never in the code."""

    storage: dict[str, Any] = field(default_factory=dict)
    sources: list[Source] = field(default_factory=list)


def load_dotenv(path: Path) -> None:
    """Fill unset variables from a `.env` beside the repo. Existing environment always wins,
    so a scheduled run and a shell run read the same values. Without this the automation
    works by hand and fails under launchd, which is the half that matters."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def _expand(value: str) -> str:
    """`${NAME}` becomes the environment variable NAME. Missing means unknown, not empty:
    an empty endpoint or bucket would otherwise send the backup to a plausible-looking
    nowhere and report success."""
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        got = os.environ.get(name)
        if not got:
            raise CannotEstablish(f"the declaration refers to ${{{name}}}, which is not set")
        return got

    return _ENV_REF.sub(_sub, value)


def load_declaration(path: Path) -> Declaration:
    if yaml is None:
        raise CannotEstablish("PyYAML is not installed, so the declaration cannot be read")
    if not path.is_file():
        raise CannotEstablish(f"declaration not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CannotEstablish(f"declaration is not valid YAML: {exc}") from exc

    storage = raw.get("storage") or {}
    if not isinstance(storage, dict) or not storage.get("bucket"):
        raise CannotEstablish(f"declaration has no `storage.bucket`: {path}")

    entries = raw.get("sources") or []
    if not isinstance(entries, list) or not entries:
        raise CannotEstablish(f"declaration lists no sources: {path}")

    default_age = float(raw.get("max_age_hours") or DEFAULT_MAX_AGE_HOURS)
    sources: list[Source] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("key"):
            raise CannotEstablish(f"every source needs `name:` and `key:`: {entry!r}")
        fetch = entry.get("fetch") or []
        if not isinstance(fetch, list) or not fetch:
            raise CannotEstablish(
                f"source {entry['name']} needs a `fetch:` command as a list of arguments"
            )
        sources.append(
            Source(
                name=str(entry["name"]),
                key=str(entry["key"]),
                fetch=[str(part) for part in fetch],
                why=str(entry.get("why") or ""),
                verify=str(entry.get("verify") or "nonempty"),
                keep=int(entry.get("keep") or DEFAULT_KEEP),
                max_age_hours=float(entry.get("max_age_hours") or default_age),
            )
        )

    return Declaration(storage=storage, sources=sources)


def _endpoint_clock_offset(endpoint: str) -> float | None:
    """Seconds the local clock is ahead of the storage endpoint, from its own Date header.
    None when the endpoint does not answer — the caller treats that as unreachable, never
    as "no skew"."""
    # An unauthenticated probe of an S3 endpoint is SUPPOSED to be refused — R2 answers 400.
    # A refusal still carries the server's Date header, and answering at all is what proves
    # the host is reachable. Treating any non-200 as "did not answer" turns a healthy
    # endpoint into an outage, which is how a working backup reports itself broken.
    try:
        request = urllib.request.Request(endpoint, method="HEAD")
        with urllib.request.urlopen(request, timeout=15) as response:
            served = response.headers.get("Date")
    except urllib.error.HTTPError as refused:
        served = refused.headers.get("Date")
    except Exception as exc:  # noqa: BLE001 - unreachable, DNS failure, timeout
        raise CannotEstablish(f"storage endpoint did not answer: {exc}") from exc
    if not served:
        return None
    parsed = email.utils.parsedate_to_datetime(served)
    return time.time() - parsed.timestamp()


def storage_client(storage: dict[str, Any]) -> tuple[Any, str, str]:
    """An S3-compatible client, or CannotEstablish. Never a silent no-op."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as exc:
        raise CannotEstablish("boto3 is not installed (it is in requirements.txt)") from exc

    access_env = storage.get("access_key_env") or "AWS_ACCESS_KEY_ID"
    secret_env = storage.get("secret_key_env") or "AWS_SECRET_ACCESS_KEY"
    missing = [name for name in (access_env, secret_env) if not os.environ.get(name)]
    if missing:
        # Names only. A credential value must never reach stdout, which is served to the
        # console over HTTP (`OPS_AUTOMATION_PRINCIPLES.md` R7).
        raise CannotEstablish(f"missing credentials: {', '.join(missing)}")

    endpoint = _expand(str(storage.get("endpoint") or ""))
    if not endpoint:
        raise CannotEstablish("the declaration has no `storage.endpoint`")

    offset = _endpoint_clock_offset(endpoint)
    if offset is not None and abs(offset) > CLOCK_SKEW_TOLERANCE_S:
        raise CannotEstablish(
            f"local clock is {offset:+.0f}s from the storage endpoint; signed requests will "
            "be rejected as bad signatures. Fix the clock, not the keys."
        )

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ[access_env],
        aws_secret_access_key=os.environ[secret_env],
        config=BotoConfig(signature_version="s3v4", region_name=storage.get("region") or "auto"),
    )
    return client, str(storage["bucket"]), str(storage.get("prefix") or "")


def _list_copies(client: Any, bucket: str, prefix: str) -> list[dict[str, Any]]:
    """Every stored copy under a prefix, newest last. Raises CannotEstablish rather than
    returning [] on a storage failure: an empty list means "no backup", which is the loudest
    possible finding, and an outage must never be able to produce it."""
    try:
        paginator = client.get_paginator("list_objects_v2")
        objects: list[dict[str, Any]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects.extend(page.get("Contents") or [])
    except Exception as exc:  # noqa: BLE001 - any storage failure is "cannot establish"
        raise CannotEstablish(f"could not list {bucket}/{prefix}: {exc}") from exc
    return sorted(objects, key=lambda obj: obj["LastModified"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_copy(path: Path, kind: str) -> None:
    """Prove the fetched file is usable BEFORE it is allowed to count as a backup.
    A copy that has never been opened is a file, not a backup."""
    if not path.exists() or path.stat().st_size == 0:
        raise CannotEstablish(f"fetched nothing: {path} is missing or empty")
    if kind == "nonempty":
        return
    if kind == "sqlite":
        # sqlite3.connect() opens lazily and succeeds on a file of pure garbage. The first
        # statement is what actually reads the header, so the guard has to wrap the QUERY;
        # wrapping only the connect lets a torn copy escape as a raw DatabaseError, and a
        # traceback is not one of this automation's three answers.
        connection = None
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            verdict = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise CannotEstablish(f"the copy does not open as SQLite: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        if not verdict or verdict[0] != "ok":
            raise CannotEstablish(
                f"the copy failed PRAGMA integrity_check: {verdict[0] if verdict else 'no result'}"
            )
        return
    if kind == "tgz":
        # `nonempty` graded the key ring until 2026-08-19, and a byte count is not a verdict.
        # A download that stopped halfway and a gzip stream that ends mid-member are both
        # larger than zero bytes, so both were recorded as that night's backup. Opening the
        # archive and reading its index is what proves it can be unpacked on the day a
        # restore needs it.
        try:
            with tarfile.open(path, "r:*") as archive:
                members = archive.getnames()
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise CannotEstablish(f"the copy does not open as a tar archive: {exc}") from exc
        if not members:
            raise CannotEstablish(f"the archive opened but holds no members: {path.name}")
        return
    raise CannotEstablish(f"unknown verify kind `{kind}` on {path.name}")


def _dated_key(prefix: str, source: Source, stamp: str) -> str:
    stem, dot, suffix = source.key.rpartition(".")
    dated = f"{stem}-{stamp}.{suffix}" if dot else f"{source.key}-{stamp}"
    return f"{prefix}{dated}"


def take_backup(client: Any, bucket: str, prefix: str, source: Source,
                *, timeout_s: float = DEFAULT_FETCH_TIMEOUT_S) -> dict[str, Any]:
    """Fetch, verify, upload, prune. Returns the receipt."""
    with tempfile.TemporaryDirectory(prefix="offsite-") as scratch:
        dest = Path(scratch) / Path(source.key).name
        # `_expand` here as well as on the storage block: the money-database fetch carries
        # `X-Internal-Key: ${STORE_INTERNAL_API_KEY}` and, unexpanded, curl would have sent the
        # eighteen literal characters of the variable name. The API answers 401, `--fail` turns
        # that into a non-zero exit, and the night reads as a fetch failure rather than as a
        # missing secret. `_expand` raises when the variable is unset, which is the honest answer.
        command = [_expand(part).replace("{dest}", str(dest)) for part in source.fetch]
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_s, cwd=scratch
            )
        except subprocess.TimeoutExpired as exc:
            raise CannotEstablish(
                f"{source.name}: fetch did not finish within {timeout_s:.0f}s"
            ) from exc
        except FileNotFoundError as exc:
            raise CannotEstablish(f"{source.name}: fetch command not found: {command[0]}") from exc
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
            raise CannotEstablish(
                f"{source.name}: fetch exited {done.returncode}: {' | '.join(tail)}"
            )

        # Some host CLIs write into the working directory under the source's own name rather
        # than honouring a destination path. Accept that instead of reporting a false failure.
        if not dest.exists():
            produced = [p for p in Path(scratch).iterdir() if p.is_file()]
            if len(produced) != 1:
                raise CannotEstablish(
                    f"{source.name}: fetch produced {len(produced)} files, expected 1"
                )
            shutil.move(str(produced[0]), dest)

        verify_copy(dest, source.verify)
        size = dest.stat().st_size
        digest = _sha256(dest)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        key = _dated_key(prefix, source, stamp)
        try:
            client.upload_file(str(dest), bucket, key,
                               ExtraArgs={"Metadata": {"sha256": digest}})
        except Exception as exc:  # noqa: BLE001
            raise CannotEstablish(f"{source.name}: upload failed: {exc}") from exc

    pruned = _prune(client, bucket, prefix, source)
    return {
        "source": source.name,
        "key": key,
        "bytes": size,
        "sha256": digest,
        "verified": source.verify,
        "pruned": pruned,
    }


def _prune(client: Any, bucket: str, prefix: str, source: Source) -> list[str]:
    """Keep the newest `keep` copies. An unbounded dated series is how a backup bucket
    becomes a bill, and a bill is how a backup gets turned off."""
    copies = _list_copies(client, bucket, _source_prefix(prefix, source))
    doomed = copies[: max(0, len(copies) - source.keep)]
    removed: list[str] = []
    for obj in doomed:
        try:
            client.delete_object(Bucket=bucket, Key=obj["Key"])
            removed.append(obj["Key"])
        except Exception:  # noqa: BLE001 - a failed prune is not a failed backup
            continue
    return removed


def _source_prefix(prefix: str, source: Source) -> str:
    stem, dot, _ = source.key.rpartition(".")
    return f"{prefix}{stem}-" if dot else f"{prefix}{source.key}-"


def check(client: Any, bucket: str, prefix: str, sources: list[Source]) -> list[dict[str, Any]]:
    """Read-only. How old is the newest copy of each source?"""
    now = datetime.now(timezone.utc)
    report: list[dict[str, Any]] = []
    for source in sources:
        copies = _list_copies(client, bucket, _source_prefix(prefix, source))
        if not copies:
            report.append({
                "where": f"{bucket}/{_source_prefix(prefix, source)}*",
                "what": f"{source.name}: no offsite copy exists at all",
                "source": source.name, "age_hours": None, "fresh": False,
            })
            continue
        newest = copies[-1]
        # Clamped at zero. A copy taken seconds ago can time-stamp a hair ahead of the local
        # clock, and "-0.0h old" reads like a bug in the thing the founder is trusting.
        age_h = max(0.0, (now - newest["LastModified"]).total_seconds() / 3600.0)
        fresh = age_h <= source.max_age_hours
        entry = {
            "where": f"{bucket}/{newest['Key']}",
            "source": source.name,
            "age_hours": round(age_h, 2),
            "bytes": newest.get("Size"),
            "copies": len(copies),
            "fresh": fresh,
        }
        if not fresh:
            entry["what"] = (
                f"{source.name}: newest copy is {age_h:.1f}h old, older than the declared "
                f"{source.max_age_hours:.0f}h"
            )
        report.append(entry)
    return report


def run(config_path: Path, *, fix: bool = False) -> dict[str, Any]:
    ran_at = datetime.now(timezone.utc).isoformat()
    probe = f"python -m ops.automations.{AUTOMATION} --config {config_path}"
    result: dict[str, Any] = {
        "automation": AUTOMATION, "ran_at": ran_at, "probe": probe,
        "checked": 0, "findings": [],
    }
    try:
        decl = load_declaration(config_path)
        load_dotenv(config_path.resolve().parents[2] / ".env")
        client, bucket, prefix = storage_client(decl.storage)
        if fix:
            result["backups"] = [
                take_backup(client, bucket, prefix, source) for source in decl.sources
            ]
        report = check(client, bucket, prefix, decl.sources)
    except CannotEstablish as exc:
        result.update({"status": "unknown", "reason": str(exc)})
        return result

    result.update({
        "status": "ok" if all(item["fresh"] for item in report) else "findings",
        "checked": len(report),
        "sources": report,
        "findings": [
            {"where": item["where"], "what": item["what"]}
            for item in report if not item["fresh"]
        ],
    })
    return result


def _default_config() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(), capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip()) / "ops" / "config" / f"{AUTOMATION}.yaml"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path("ops") / "config" / f"{AUTOMATION}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fix", action="store_true", help="take a backup now")
    parser.add_argument("--config", type=Path, default=None, help="declaration file")
    args = parser.parse_args(argv)

    result = run(args.config or _default_config(), fix=args.fix)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif result["status"] == "unknown":
        print(f"UNKNOWN: {result['reason']}")
    else:
        for item in result.get("backups") or []:
            print(f"BACKED UP {item['source']} -> {item['key']} "
                  f"({item['bytes']:,} bytes, {item['verified']} verified)")
        for item in result["sources"]:
            age = "never" if item["age_hours"] is None else f"{item['age_hours']:.1f}h old"
            print(f"{'OK  ' if item['fresh'] else 'STALE'} {item['source']}: {age}")
        if result["status"] == "findings":
            print("\nRun with --fix to take a backup now, or see docs/RUNBOOKS.md#offsite-backup.")

    return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

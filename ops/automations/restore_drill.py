"""Prove the estate can be recovered FROM the backup bucket, not merely written to it.

WHY THIS IS A SEPARATE PROGRAM. `offsite_backup.py` verifies every copy before uploading it, and
that is a real check, but it grades the local file in the process that produced it. It answers "did
we make a good copy". It cannot answer the only question a disaster asks: **can a machine that has
never seen the original get the data back out and open it.** Those fail differently. A bucket
policy change, a wrong prefix, a rotated credential, a multipart upload that recorded a size and
stored nothing, a lifecycle rule quietly expiring objects - every one of them leaves the backup job
green and the restore impossible.

LAW 19 states the rule this program exists to satisfy: a dependency whose exit has never been
drilled is not portable, it is a hope. Cloudflare R2 is where the whole estate's second copy lives.
This is the command that turns the hope into a measurement, and its exit status is the answer.

WHAT IT DOES. For every prefix the declaration knows about - the `sources:` this repo takes, and
the `watch:` entries other jobs write - it downloads the NEWEST object and opens it:

  - the declared `verify:` kind, using the backup engine's own `verify_copy`, so the restore side
    and the backup side can never drift apart into two different opinions of "usable";
  - `.bundle` files are cloned with `git clone --bare`, which is the only check that reads the
    pack. `git bundle verify` reads the header and the prerequisites and nothing else: measured
    2026-08-23, it accepted a bundle truncated to 300 bytes. A guard that passes a truncated
    backup is worse than no guard, because it makes the backup look drilled;
  - `.age` files are decrypted with the private key and their assignments counted.

NO SECRET VALUE IS EVER PRINTED (LAW 21). The decrypted store is counted and dropped. What reaches
stdout is a count.

  .venv/bin/python -m ops.automations.restore_drill            # drill everything
  .venv/bin/python -m ops.automations.restore_drill --only secret-store,architect-code
  .venv/bin/python -m ops.automations.restore_drill --json     # for the board

Exit 0 means every prefix drilled came back and opened. Exit 1 means at least one did not, and the
line naming it is the finding.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ops.automations.offsite_backup import (
    CannotEstablish,
    _list_copies,
    _source_prefix,
    load_declaration,
    load_dotenv,
    storage_client,
    verify_copy,
)

# `Path(os.environ.get(NAME, "")) or default` is a trap and it fired on the first run: Path("")
# is Path("."), which is truthy, so the fallback never happens and the drill reports "no age key
# at .". Test the string, then build the Path.
AGE_KEY = Path(
    os.environ.get("PROSPECTOR_AGE_KEY") or Path.home() / ".config/prospector/age-key.txt"
)


def _open_bundle(path: Path) -> str:
    """Clone the bundle into a throwaway bare repo and count what came back.

    `git clone` is the check and `git bundle verify` is not, for the reason in the module
    docstring. The clone also gives us the tip subject, which is the cheapest way for a human to
    see at a glance that the backup is of the repository they think it is.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.git"
        done = subprocess.run(
            ["git", "clone", "--bare", "--quiet", str(path), str(probe)],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise CannotEstablish(
                f"the bundle would not clone: {done.stderr.strip().splitlines()[-1:] or ['no output']}"
            )
        refs = subprocess.run(
            ["git", "-C", str(probe), "show-ref"], capture_output=True, text=True
        ).stdout.splitlines()
        if not refs:
            raise CannotEstablish("the bundle cloned to zero refs, so it carries no history")
        tip = subprocess.run(
            ["git", "-C", str(probe), "log", "-1", "--format=%h %s"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{len(refs)} refs, tip {tip[:60]}"


def _open_age(path: Path) -> str:
    """Decrypt and count. The plaintext is dropped in this function and never returned."""
    if not AGE_KEY.is_file():
        raise CannotEstablish(
            f"no age key at {AGE_KEY}, so the encrypted store cannot be opened. On a new machine "
            "this is the one value that must come from the password manager first."
        )
    done = subprocess.run(
        ["age", "-d", "-i", str(AGE_KEY), str(path)], capture_output=True
    )
    if done.returncode != 0:
        raise CannotEstablish("age refused to decrypt it with the key on this machine")
    count = sum(
        1
        for line in done.stdout.decode("utf-8", "replace").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    del done
    if count == 0:
        raise CannotEstablish("it decrypted to zero assignments, so it holds no secrets")
    return f"decrypted to {count} secrets"


def drill_one(client: Any, bucket: str, prefix: str, name: str, kind: str) -> dict[str, Any]:
    """Download the newest object under one prefix and open it. Never raises."""
    row: dict[str, Any] = {"name": name, "prefix": prefix, "ok": False}
    try:
        copies = _list_copies(client, bucket, prefix)
        if not copies:
            row["detail"] = "the bucket holds nothing under this prefix"
            return row
        newest = copies[-1]
        row["key"] = newest["Key"]
        row["bytes"] = int(newest["Size"])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / Path(newest["Key"]).name
            client.download_file(bucket, newest["Key"], str(dest))
            got = dest.stat().st_size
            if got != row["bytes"]:
                # The listing is metadata and the download is the object. They disagree when a
                # multipart upload recorded a size it never stored.
                row["detail"] = f"R2 listed {row['bytes']} bytes and served {got}"
                return row
            notes = []
            if kind:
                verify_copy(dest, kind)
                notes.append(f"{kind} verified")
            if dest.suffix == ".bundle":
                notes.append(_open_bundle(dest))
            elif dest.suffix == ".age":
                notes.append(_open_age(dest))
            row["ok"] = True
            row["detail"] = ", ".join(notes) or "downloaded and non-empty"
    except CannotEstablish as exc:
        row["detail"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - any failure to restore is the finding
        row["detail"] = f"{type(exc).__name__}: {exc}"
    return row


def run(config_path: Path, *, only: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(config_path.resolve().parents[2] / ".env")
    decl = load_declaration(config_path)
    client, bucket, prefix = storage_client(decl.storage)

    targets: list[tuple[str, str, str]] = [
        (s.name, _source_prefix(prefix, s), s.verify) for s in decl.sources
    ]
    # The `watch:` entries are prefixes other jobs write. They are graded here too, because a
    # backup this repo does not take is exactly as load-bearing in a disaster as one it does.
    targets += [(w.name, w.prefix, "") for w in decl.watched]
    if only:
        targets = [t for t in targets if t[0] in only]
        unknown = only - {t[0] for t in targets}
        if unknown:
            raise CannotEstablish(f"no such source: {', '.join(sorted(unknown))}")

    rows = [drill_one(client, bucket, pre, name, kind) for name, pre, kind in targets]
    return {
        "bucket": bucket,
        "drilled": len(rows),
        "failed": sum(1 for r in rows if not r["ok"]),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--only", default="", help="comma-separated source names")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = args.config or Path(__file__).resolve().parents[2] / "ops/config/offsite_backup.yaml"
    try:
        result = run(config, only={p for p in args.only.split(",") if p} or None)
    except CannotEstablish as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"CANNOT DRILL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result["rows"]:
            mark = "PASS" if row["ok"] else "FAIL"
            size = f" ({row['bytes']:,} bytes)" if "bytes" in row else ""
            print(f"{mark} {row['name']:<22}{size} {row['detail']}")
        print(
            f"\n{result['drilled'] - result['failed']}/{result['drilled']} prefixes restored "
            f"from {result['bucket']}."
        )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

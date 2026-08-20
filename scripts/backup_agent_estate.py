#!/usr/bin/env python3
"""Pack the agent estate — ~/.claude — into one archive, without shipping credentials with it.

WHY THIS EXISTS
---------------
Everything else on this laptop has a backup job. The agent estate did not. Memory files, hooks,
skills, the founder-directive archive, the state probes and every checkpoint existed in exactly
one copy, on one disk, with no second copy anywhere. That is the whole institutional memory of
how this estate is worked: the rules, the traps that cost time, the reasons behind decisions.
Losing the disk loses all of it and none of it is in git.

WHY IT IS AN ALLOW-LIST
-----------------------
`~/.claude` is 7.2 GB, and almost none of that is worth keeping: 5.9 GB of session transcripts,
1.2 GB of telemetry, caches, plugin checkouts, shell snapshots. The part that cannot be rebuilt
is 15 MB. A deny-list has to be updated every time the CLI grows a new directory, and the update
is remembered by nobody; an allow-list only ever fails by leaving something OUT, which is the
safe direction. What it currently takes is `ROOTS` below.

WHY IT SCANS
------------
Measured 2026-08-20, on the allow-listed set only:

  * `projects/-Users-chidionyema/checkpoints/prod-jwt-2026-08-01.pem` — a PRIVATE KEY, sitting in
    a checkpoints directory.
  * `directives/-Users-chidionyema-Documents-code-prospector.jsonl` line 2866 — a 93-character
    GitHub fine-grained token, pasted into chat once and archived forever by the directive
    capture.

Neither was put there deliberately, and both would have been uploaded to object storage by any
backup that simply tarred the allow-list. `~/.hermes/.gitignore` already carries the verdict on
the alternative: a list of FILENAME patterns is the wrong control, written after 26 live keys
reached a GitHub remote through it. So this reads the bytes.

Two controls, each aimed at what it can actually handle:

  * A file that IS key material is excluded whole. Redacting `-----BEGIN PRIVATE KEY-----` out of
    a .pem leaves the key body behind, so the only safe treatment of the file is not to take it.
  * A credential embedded in a file that is otherwise worth keeping is REDACTED in place. The
    directive archive is 5.8 MB of founder history; dropping the file to avoid one pasted token
    would cost far more than it saves, and that token has to be rotated regardless.

Every exclusion and every redaction is recorded in `AGENT_ESTATE_MANIFEST.json` at the root of
the archive, by path, line and shape class — never by value. A restore reads the manifest and
knows exactly what it does not have.

Exit code 0 when the archive was written, whether or not anything was redacted: a backup that
refuses to run because it found a secret leaves the estate with NO copy, which is the failure it
exists to prevent. The redaction count goes to stderr, so it lands in the launchd log and in the
Fly receipt, and the manifest carries it into the archive itself.

    scripts/backup_agent_estate.py --check           # what would be taken, excluded, redacted
    scripts/backup_agent_estate.py --out estate.tgz  # write it
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
ESTATE = HOME / ".claude"

#: What is worth keeping, relative to ~/.claude. A `*` matches one path segment.
#:
#: `projects/*/memory` and `projects/*/checkpoints` and NOT `projects/*` — the sibling of those
#: two directories is the session transcripts, which are 5.9 GB and rebuild nothing.
ROOTS = (
    "CLAUDE.md",
    "settings.json",
    "settings.local.json",
    "scripts",
    "skills",
    "plans",
    "directives",
    "projects/*/memory",
    "projects/*/checkpoints",
    "projects/*/.state-probe",
)

#: Files that ARE credentials. Excluded whole, because there is no useful redaction of a key.
KEY_MATERIAL = (
    ".credentials.json",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.der",
    "id_rsa*", "id_ecdsa*", "id_ed25519*",
    "*.env", ".env*",
)

#: Credential SHAPES, not names. A shape survives being renamed, pasted into prose, or embedded
#: in a JSON line, which is how both of the measured hits got where they are.
SHAPES = (
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("aws-access-key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("fly-token", re.compile(r"FlyV1 [A-Za-z0-9_.\-]{30,}")),
    ("stripe-secret", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("json-web-token", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+")),
)

MANIFEST_NAME = "AGENT_ESTATE_MANIFEST.json"


def selected_files(estate: Path | None = None,
                   roots: tuple[str, ...] | None = None) -> list[Path]:
    """Every regular file under the allow-list, sorted, deduplicated.

    Symlinks are followed for their NAME only and never archived as links: a link pointing out of
    the estate would otherwise pull an arbitrary file into the archive, which defeats the point of
    an allow-list.

    The defaults resolve at CALL time, not at import time. A `estate: Path = ESTATE` default binds
    the module constant once and then ignores every later change to it, so the function would read
    the caller's real home directory while the caller believed it was pointed somewhere else."""
    estate = estate if estate is not None else ESTATE
    roots = roots if roots is not None else ROOTS
    found: dict[Path, None] = {}
    for root in roots:
        for match in sorted(estate.glob(root)):
            # An allow-listed root that is ITSELF a link can point anywhere on the disk. Skipped
            # rather than resolved: the allow-list is meant to bound what leaves this machine.
            if match.is_symlink():
                continue
            if match.is_file():
                found.setdefault(match, None)
            elif match.is_dir():
                for path in sorted(match.rglob("*")):
                    if path.is_symlink() or not path.is_file():
                        continue
                    found.setdefault(path, None)
    return list(found)


def is_key_material(path: Path, patterns: tuple[str, ...] | None = None) -> bool:
    from fnmatch import fnmatch

    return any(fnmatch(path.name, p) for p in (patterns if patterns is not None else KEY_MATERIAL))


def find_shapes(text: str) -> list[dict[str, object]]:
    """Every credential shape in `text`, as {shape, line, chars}. Never returns the value."""
    hits: list[dict[str, object]] = []
    for name, pattern in SHAPES:
        for match in pattern.finditer(text):
            hits.append({
                "shape": name,
                "line": text.count("\n", 0, match.start()) + 1,
                "chars": len(match.group(0)),
            })
    return sorted(hits, key=lambda h: (h["line"], h["shape"]))


def redact(text: str) -> tuple[str, list[dict[str, object]]]:
    """Replace every credential shape with a marker of the same intent, not the same length.

    The marker names the shape so a restore can tell what is missing, and carries no part of the
    original — not a prefix, not a length-preserving mask, both of which narrow a brute force."""
    hits = find_shapes(text)
    if not hits:
        return text, []
    for name, pattern in SHAPES:
        text = pattern.sub(f"[REDACTED {name} — backup_agent_estate.py]", text)
    return text, hits


def build(out: Path | None, *, estate: Path | None = None,
          home: Path | None = None) -> dict[str, object]:
    """Walk the allow-list, apply both controls, write the archive when `out` is given."""
    estate = estate if estate is not None else ESTATE
    home = home if home is not None else HOME
    files = selected_files(estate)
    manifest: dict[str, object] = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "estate": str(estate),
        "roots": list(ROOTS),
        "tool": "scripts/backup_agent_estate.py",
        "files": 0,
        "bytes": 0,
        "excluded": [],
        "redacted": [],
        "unscanned_binary": [],
    }
    excluded: list[dict[str, str]] = manifest["excluded"]        # type: ignore[assignment]
    redacted: list[dict[str, object]] = manifest["redacted"]     # type: ignore[assignment]
    unscanned: list[str] = manifest["unscanned_binary"]          # type: ignore[assignment]

    tar = tarfile.open(out, "w:gz") if out else None
    try:
        for path in files:
            rel = path.relative_to(home)
            if is_key_material(path):
                excluded.append({
                    "path": str(rel),
                    "why": "the file is key material; there is no safe redaction of a key",
                })
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # Not scannable as text. Kept, and named, so the manifest does not imply that
                # every archived byte was read.
                unscanned.append(str(rel))
                payload = raw
            else:
                cleaned, hits = redact(text)
                if hits:
                    redacted.append({"path": str(rel), "hits": hits})
                payload = cleaned.encode("utf-8")

            manifest["files"] = int(manifest["files"]) + 1          # type: ignore[arg-type]
            manifest["bytes"] = int(manifest["bytes"]) + len(payload)  # type: ignore[arg-type]
            if tar is not None:
                info = tarfile.TarInfo(name=str(rel))
                info.size = len(payload)
                info.mtime = int(path.stat().st_mtime)
                info.mode = 0o600
                tar.addfile(info, io.BytesIO(payload))

        if tar is not None:
            blob = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            info = tarfile.TarInfo(name=MANIFEST_NAME)
            info.size = len(blob)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(blob))
    finally:
        if tar is not None:
            tar.close()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the archive here (.tgz)")
    parser.add_argument("--check", action="store_true",
                        help="report what would be taken, excluded and redacted; write nothing")
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON")
    args = parser.parse_args(argv)

    if not args.out and not args.check:
        parser.error("give --out PATH to write an archive, or --check to report")
    if not ESTATE.is_dir():
        print(f"no agent estate at {ESTATE}", file=sys.stderr)
        return 2

    manifest = build(None if args.check else args.out)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        mib = int(manifest["bytes"]) / 1048576  # type: ignore[arg-type]
        where = "would take" if args.check else "took"
        print(f"{where} {manifest['files']} files, {mib:.1f} MiB from {ESTATE}")

    # stderr, so it reaches the launchd log and the Fly receipt even in --json mode.
    for item in manifest["excluded"]:                             # type: ignore[union-attr]
        print(f"EXCLUDED {item['path']}: {item['why']}", file=sys.stderr)
    for item in manifest["redacted"]:                             # type: ignore[union-attr]
        shapes = ", ".join(f"{h['shape']} line {h['line']}" for h in item["hits"])
        print(f"REDACTED {item['path']}: {shapes}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

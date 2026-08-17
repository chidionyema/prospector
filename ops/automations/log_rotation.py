"""Log rotation — keep the logs small enough to be read, and old enough to be useful.

Generic engine. It knows nothing about this business: every path, size limit and retention
count comes from the declaration file (default `ops/config/log_rotation.yaml`). See
`docs/OPS_AUTOMATION_PRINCIPLES.md` for the contract this implements.

What it is for. An unrotated log is not just disk. It is a wrong answer waiting to be given.
On 2026-08-16 a `grep -c` over a 25 MB `launchd.err.log` counted 97 provider failures and read
as "97 today". The real number for today was 8; the other 89 were ten days old and most of them
named a provider chain that no longer exists. The log had never rotated, so a lifetime count
looked like a daily one, and the wrong number reached a planning document as a blocker.

Interface (the standard shape, `OPS_AUTOMATION_PRINCIPLES.md` R2):

    python -m ops.automations.log_rotation                 # read-only, human output
    python -m ops.automations.log_rotation --json          # what the console calls
    python -m ops.automations.log_rotation --fix           # rotate what is over its limit
    python -m ops.automations.log_rotation --config PATH   # a different declaration

Exit codes: 0 clean, 1 findings (something is over its limit), 2 could not establish.

How it rotates, and why it matters. It copies the content out, compresses it, then truncates
the original IN PLACE. It does not rename. A daemon holds the log open by file descriptor, and
renaming a file does not move that descriptor: the daemon keeps writing to the renamed file
forever, the fresh log stays empty, and the next reader sees a silent process. launchd's own
stdout redirection has exactly this property, and every writer in this estate is under launchd.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the declaration format is YAML by design
    yaml = None  # type: ignore[assignment]

AUTOMATION = "log_rotation"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2

DEFAULT_MAX_MB = 10.0
DEFAULT_KEEP = 5
BYTES_PER_MB = 1024 * 1024


class CannotEstablish(Exception):
    """The check could not run. Reported as `unknown`, never as clean."""


@dataclass
class Target:
    path: str
    why: str = ""
    max_mb: float = DEFAULT_MAX_MB
    keep: int = DEFAULT_KEEP


@dataclass
class Declaration:
    targets: list[Target] = field(default_factory=list)


def load_declaration(path: Path) -> Declaration:
    if yaml is None:
        raise CannotEstablish("PyYAML is not installed, so the declaration cannot be read")
    if not path.is_file():
        raise CannotEstablish(f"declaration not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CannotEstablish(f"declaration is not valid YAML: {exc}") from exc

    default_max = float(raw.get("max_mb") or DEFAULT_MAX_MB)
    default_keep = int(raw.get("keep") or DEFAULT_KEEP)

    entries = raw.get("targets") or []
    if not isinstance(entries, list) or not entries:
        raise CannotEstablish(f"declaration lists no targets: {path}")

    targets: list[Target] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("path"):
            raise CannotEstablish(f"every target needs a `path:` key: {entry!r}")
        targets.append(
            Target(
                path=str(entry["path"]),
                why=str(entry.get("why") or ""),
                max_mb=float(entry.get("max_mb") or default_max),
                keep=int(entry.get("keep") or default_keep),
            )
        )
    return Declaration(targets=targets)


def repo_root(start: Path) -> Path:
    """The git root. Asked of git, never assembled from `.git` as a path: in a worktree
    `.git` is a FILE containing a gitdir pointer."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise CannotEstablish(f"not a git repository (or git is unavailable): {start}") from exc
    return Path(out.stdout.strip())


def resolve(target: Target, root: Path) -> list[Path]:
    """A target may name one file or a glob. Absolute paths are honoured as written, so this
    engine works for /var/log in a startup that keeps its logs outside the repo."""
    pattern = target.path
    if pattern.startswith("/"):
        base, rel = Path("/"), pattern.lstrip("/")
    else:
        base, rel = root, pattern
    if any(ch in rel for ch in "*?["):
        return sorted(p for p in base.glob(rel) if p.is_file())
    single = base / rel
    return [single] if single.is_file() else []


def _archives(path: Path) -> list[Path]:
    """Rotated copies of this log. The key is timestamped, so name order is time order."""
    return sorted(path.parent.glob(f"{path.name}.*.gz"))


def rotate(path: Path, keep: int) -> dict[str, Any]:
    """Compress the content out, truncate in place, prune to `keep` archives.

    Copy-truncate, not rename — see the module docstring. The residual race is small and
    named rather than hidden: bytes appended between the copy and the truncate would be lost,
    so the tail is re-read and written back after truncating instead of being dropped.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = path.with_name(f"{path.name}.{stamp}.gz")

    copied = path.stat().st_size
    with path.open("rb") as source, gzip.open(archive, "wb") as sink:
        shutil.copyfileobj(source, sink, length=1024 * 1024)

    with path.open("r+b") as handle:
        handle.seek(copied)
        tail = handle.read()
        handle.seek(0)
        handle.truncate(0)
        if tail:
            handle.write(tail)

    pruned = []
    archives = _archives(path)
    for stale in archives[:-keep] if keep > 0 else archives:
        stale.unlink()
        pruned.append(stale.name)

    return {
        "path": str(path),
        "archive": archive.name,
        "bytes_rotated": copied,
        "bytes_kept_live": len(tail),
        "pruned": pruned,
    }


def check(decl: Declaration, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read-only. Returns (every file looked at, the ones over their limit)."""
    looked: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for target in decl.targets:
        paths = resolve(target, root)
        if not paths:
            looked.append({
                "where": target.path,
                "exists": False,
                "megabytes": 0.0,
                "limit_mb": target.max_mb,
                "over": False,
            })
            continue
        for path in paths:
            megabytes = path.stat().st_size / BYTES_PER_MB
            over = megabytes > target.max_mb
            entry = {
                "where": str(path),
                "exists": True,
                "megabytes": round(megabytes, 1),
                "limit_mb": target.max_mb,
                "archives": len(_archives(path)),
                "over": over,
            }
            looked.append(entry)
            if over:
                findings.append({
                    "where": str(path),
                    "what": f"{megabytes:.1f} MB, limit {target.max_mb:.0f} MB"
                            f"{' — ' + target.why if target.why else ''}",
                    "megabytes": round(megabytes, 1),
                    "limit_mb": target.max_mb,
                    "keep": target.keep,
                })
    return looked, findings


def run(config_path: Path, start: Path, *, fix: bool = False) -> dict[str, Any]:
    ran_at = datetime.now(timezone.utc).isoformat()
    probe = f"python -m ops.automations.{AUTOMATION} --config {config_path}"
    result: dict[str, Any] = {
        "automation": AUTOMATION,
        "ran_at": ran_at,
        "probe": probe,
        "checked": 0,
        "findings": [],
    }

    try:
        decl = load_declaration(config_path)
        root = repo_root(start)
        looked, findings = check(decl, root)

        if fix and findings:
            keep_by_path = {f["where"]: f["keep"] for f in findings}
            rotated = [rotate(Path(where), keep) for where, keep in keep_by_path.items()]
            result["rotated"] = rotated
            looked, findings = check(decl, root)
    except CannotEstablish as exc:
        result.update(status="unknown", reason=str(exc))
        return result

    result.update(
        status="findings" if findings else "ok",
        checked=len(looked),
        files=looked,
        findings=findings,
    )
    return result


def _default_config(start: Path) -> Path:
    try:
        return repo_root(start) / "ops" / "config" / f"{AUTOMATION}.yaml"
    except CannotEstablish:
        return Path("ops") / "config" / f"{AUTOMATION}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fix", action="store_true", help="rotate what is over its limit")
    parser.add_argument("--config", type=Path, default=None, help="declaration file")
    args = parser.parse_args(argv)

    start = Path.cwd()
    config_path = args.config or _default_config(start)
    result = run(config_path, start, fix=args.fix)

    if args.json:
        print(json.dumps(result, indent=2))
        return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]

    if result["status"] == "unknown":
        print(f"UNKNOWN: {result['reason']}")
        return EXIT_UNKNOWN

    for entry in result.get("rotated", []):
        print(f"ROTATED {entry['path']} -> {entry['archive']} "
              f"({entry['bytes_rotated']:,} bytes"
              f"{', pruned ' + str(len(entry['pruned'])) if entry['pruned'] else ''})")

    for entry in result.get("files", []):
        if not entry["exists"]:
            print(f"ABSENT  {entry['where']} (declared, not on disk)")
        elif entry["over"]:
            print(f"OVER    {entry['where']}: {entry['megabytes']} MB "
                  f"(limit {entry['limit_mb']:.0f})")
        else:
            print(f"OK      {entry['where']}: {entry['megabytes']} MB "
                  f"(limit {entry['limit_mb']:.0f})")

    if result["findings"]:
        print(f"\n{len(result['findings'])} log(s) over the limit. "
              f"Rotate with --fix. An unrotated log makes a lifetime count read as today's.")
    return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

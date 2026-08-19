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
import os
import shutil
import subprocess
import time
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

# A prune that would delete more than this in one run stops and says so instead. The cap is
# not a blanket over a correct declaration — it is the tripwire for an INCORRECT one, where a
# glob is broader than its author believed. Raising it is a deliberate edit with a reason
# beside it, which is the only moment anybody re-reads the glob.
DEFAULT_MAX_DELETE = 20_000


def _expand(pattern: str) -> str:
    """`~` and `$VAR` in a declared path.

    `$PROSPECTOR_STORE_DIR` matters more than it looks. A relative `store/*.log` resolves
    against the process's working directory, and the scheduled job runs from the LIVE
    checkout while the canonical store lives in the developer one — so the declaration
    silently matched an empty directory and the job's own log grew unbounded. That is the
    same defect CLAUDE.md records for four constants derived from `__file__`: a store path
    that follows the CODE instead of the store.
    """
    return os.path.expanduser(os.path.expandvars(pattern))


def _assert_expanded(pattern: str, expanded: str) -> None:
    """A `$VAR` that did not expand is left LITERAL by expandvars, so the glob quietly
    matches nothing and the target reports ABSENT — a policy that is off, reported as a
    policy that has nothing to do. Refuse instead."""
    if "$" in expanded:
        raise CannotEstablish(
            f"declared path {pattern!r} contains an environment variable that is not set "
            f"in this process; it would silently match nothing")


class CannotEstablish(Exception):
    """The check could not run. Reported as `unknown`, never as clean."""


@dataclass
class Target:
    path: str
    why: str = ""
    max_mb: float = DEFAULT_MAX_MB
    keep: int = DEFAULT_KEEP


@dataclass
class PruneTarget:
    """A directory of many files, pruned by AGE — not one file rotated by size.

    Rotation cannot express ~/.hermes/cron/output: 32,427 files and 195 MB on 2026-08-19, not
    one of them individually large. Truncating a file in place is the wrong verb there; the
    right verb is deleting the old ones. Same declaration, same report-first discipline, a
    different shape of target.
    """
    path: str
    why: str = ""
    older_than_days: float = 0.0
    keep_newest: int = 0
    max_delete: int = DEFAULT_MAX_DELETE
    exclude: list[str] = field(default_factory=list)


@dataclass
class Declaration:
    targets: list[Target] = field(default_factory=list)
    prunes: list[PruneTarget] = field(default_factory=list)


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
    prunes: list[PruneTarget] = []
    for entry in raw.get("prune") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            raise CannotEstablish(f"every prune target needs a `path:` key: {entry!r}")
        days = float(entry.get("older_than_days") or 0)
        newest = int(entry.get("keep_newest") or 0)
        if days <= 0 and newest <= 0:
            # A prune with neither bound is a delete-everything, and a declaration that can
            # express one will eventually contain one. There is no default for this on purpose.
            raise CannotEstablish(
                f"prune target {entry['path']!r} declares neither `older_than_days:` nor "
                f"`keep_newest:`; refusing to treat that as 'delete everything'")
        prunes.append(
            PruneTarget(
                path=str(entry["path"]),
                why=str(entry.get("why") or ""),
                older_than_days=days,
                keep_newest=newest,
                max_delete=int(entry.get("max_delete") or DEFAULT_MAX_DELETE),
                exclude=[str(x) for x in (entry.get("exclude") or [])],
            )
        )
    return Declaration(targets=targets, prunes=prunes)


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
    pattern = _expand(target.path)
    _assert_expanded(target.path, pattern)
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


def _bound(entry: dict[str, Any]) -> str:
    """The retention rule in words, so a report says which bound is doing the work."""
    parts = []
    if entry.get("older_than_days"):
        parts.append(f"{entry['older_than_days']:g}d")
    if entry.get("keep_newest"):
        parts.append(f"keep newest {entry['keep_newest']}")
    return " + ".join(parts) or "no bound"


def resolve_prune(target: PruneTarget, root: Path) -> list[Path]:
    """Every regular file the target names. Three structural fences, none of them optional:

    files only        — a directory is never deleted, so a wrong glob cannot take a tree.
    no symlinks       — following one would delete a file that lives somewhere the
                        declaration never named, which is how a bounded sweep escapes.
    no `.git` segment — a glob that reaches into a repo's object store destroys history
                        silently, and it looks exactly like deleting old files.
    """
    pattern = _expand(target.path)
    _assert_expanded(target.path, pattern)
    if pattern.startswith("/"):
        base, rel = Path("/"), pattern.lstrip("/")
    else:
        base, rel = root, pattern
    found = base.glob(rel) if any(ch in rel for ch in "*?[") else [base / rel]
    out: list[Path] = []
    for path in found:
        if ".git" in path.parts:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if any(path.match(pat) for pat in target.exclude):
            continue
        out.append(path)
    return sorted(out)


def check_prune(decl: Declaration, root: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Read-only. One entry per prune target: what is there, and what is old enough to go."""
    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    for target in decl.prunes:
        paths = resolve_prune(target, root)
        # Two bounds, and when both are declared a file must fail BOTH to be deleted. The
        # conjunction is the safe reading: `older_than_days: 30, keep_newest: 5` means "thirty
        # days of history, and never fewer than five copies whatever the dates say".
        doomed = list(paths)
        if target.older_than_days > 0:
            cutoff = now - target.older_than_days * 86400
            doomed = [p for p in doomed if p.stat().st_mtime < cutoff]
        if target.keep_newest > 0:
            newest = sorted(paths, key=lambda p: p.stat().st_mtime)[-target.keep_newest:]
            doomed = [p for p in doomed if p not in newest]
        freeable = sum(p.stat().st_size for p in doomed)
        entry: dict[str, Any] = {
            "where": target.path,
            "why": target.why,
            "older_than_days": target.older_than_days,
            "keep_newest": target.keep_newest,
            "files": len(paths),
            "doomed": len(doomed),
            "freeable_mb": round(freeable / BYTES_PER_MB, 1),
            "paths": [str(p) for p in doomed],
            "over_cap": len(doomed) > target.max_delete,
            "max_delete": target.max_delete,
        }
        out.append(entry)
    return out


def prune(entry: dict[str, Any]) -> dict[str, Any]:
    """Delete what check_prune found. Returns a receipt: what went, and what would not."""
    if entry["over_cap"]:
        # Refusing is the whole point of the cap. Deleting "most of it" and reporting success
        # would leave a half-applied policy nobody can reason about.
        return {"where": entry["where"], "deleted": 0, "bytes_freed": 0,
                "refused": f"{entry['doomed']} files exceeds max_delete "
                           f"{entry['max_delete']}; widen it deliberately or narrow the glob"}
    deleted = 0
    freed = 0
    failed: list[str] = []
    for raw in entry["paths"]:
        path = Path(raw)
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError as exc:                     # a file that vanished under us is not a fault
            failed.append(f"{path}: {exc.strerror}")
            continue
        deleted += 1
        freed += size
    return {"where": entry["where"], "deleted": deleted, "bytes_freed": freed,
            "failed": failed}


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
        # A developer running this by hand has no PROSPECTOR_STORE_DIR; the scheduled job
        # does, and it points at the canonical store rather than at whatever checkout the
        # process happens to run from. Defaulting it here keeps both honest: the declaration
        # names the store, and a bare "python -m ops.automations.log_rotation" still works.
        os.environ.setdefault("PROSPECTOR_STORE_DIR", str(root / "store"))
        looked, findings = check(decl, root)

        if fix and findings:
            keep_by_path = {f["where"]: f["keep"] for f in findings}
            rotated = [rotate(Path(where), keep) for where, keep in keep_by_path.items()]
            result["rotated"] = rotated
            looked, findings = check(decl, root)

        prunes = check_prune(decl, root)
        if fix and any(e["doomed"] for e in prunes):
            result["pruned"] = [prune(e) for e in prunes if e["doomed"]]
            prunes = check_prune(decl, root)
    except CannotEstablish as exc:
        result.update(status="unknown", reason=str(exc))
        return result

    # Prune entries join `findings` rather than sitting in a second list of their own, so
    # every consumer already reading this automation's findings — ops_status, the console,
    # the estate probe — sees them without being taught a new shape.
    for entry in prunes:
        if entry["doomed"]:
            findings.append({
                "where": entry["where"],
                "what": f"{entry['doomed']} file(s) past {_bound(entry)}, "
                        f"{entry['freeable_mb']} MB"
                        + (" — OVER max_delete, refusing" if entry["over_cap"] else "")
                        + (" — " + entry["why"].strip().splitlines()[0] if entry["why"] else ""),
                "doomed": entry["doomed"],
                "freeable_mb": entry["freeable_mb"],
            })

    result.update(
        status="findings" if findings else "ok",
        checked=len(looked) + sum(e["files"] for e in prunes),
        files=looked,
        prune=[{k: v for k, v in e.items() if k != "paths"} for e in prunes],
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
    parser.add_argument("--fix", action="store_true",
                        help="rotate what is over its limit and prune what is past its age")
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

    for entry in result.get("pruned", []):
        if entry.get("refused"):
            print(f"REFUSED {entry['where']}: {entry['refused']}")
        else:
            print(f"PRUNED  {entry['where']}: {entry['deleted']:,} file(s), "
                  f"{entry['bytes_freed'] / BYTES_PER_MB:.1f} MB freed")

    for entry in result.get("prune", []):
        verdict = "OVER-CAP" if entry["over_cap"] else ("OLD " if entry["doomed"] else "OK  ")
        print(f"{verdict:<8}{entry['where']}: {entry['files']:,} file(s), "
              f"{entry['doomed']:,} past {_bound(entry)} "
              f"({entry['freeable_mb']} MB)")

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
        freeable = sum(f.get("freeable_mb", 0) for f in result["findings"])
        print(f"\n{len(result['findings'])} finding(s). Apply with --fix. An unrotated log "
              f"makes a lifetime count read as today's, and an unpruned directory is a disk "
              f"bill nobody reads."
              + (f" {freeable:.1f} MB would be freed." if freeable else ""))
    return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

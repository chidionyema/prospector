"""Retired terms — stop a deleted dependency coming back.

Generic engine. It knows nothing about this business: every term, path and reason comes from
the declaration file (default `ops/config/retired_terms.yaml`). See
`docs/OPS_AUTOMATION_PRINCIPLES.md` for the contract this implements.

What it is for. When a dependency, provider or brand is removed, the name does not vanish with
the code. It survives in config defaults, legal copy, operator runbooks, comments and test
fixtures, and any single leftover is enough to send a buyer or a reader somewhere wrong. That
is a grep-shaped defect, so this is a grep with a memory: history is allow-listed with a
written reason, and anything new fails.

Interface (the standard shape, `OPS_AUTOMATION_PRINCIPLES.md` R2):

    python -m ops.automations.retired_terms                 # read-only, human output
    python -m ops.automations.retired_terms --json          # what the console calls
    python -m ops.automations.retired_terms --config PATH   # a different declaration

Exit codes: 0 clean, 1 findings, 2 could not establish (missing config, not a git repo).
There is no `--fix`: deciding what a retired name should become is a judgement about the
replacement, not a mechanical edit, so this automation reports and a person edits.
"""

from __future__ import annotations

import argparse
import json
import re
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

AUTOMATION = "retired_terms"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2

# Binary and log-shaped files. Scanning them finds nothing a human can act on and costs the
# whole runtime of the check.
DEFAULT_SKIP_SUFFIXES = (
    ".jsonl", ".gz", ".zip", ".tar", ".db", ".sqlite",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".woff", ".woff2", ".ttf", ".eot", ".lock",
)


@dataclass
class Finding:
    where: str
    what: str
    term: str

    def as_dict(self) -> dict[str, str]:
        return {"where": self.where, "what": self.what, "term": self.term}


@dataclass
class Declaration:
    """The business facts. Everything startup-specific lives here, never in the code."""

    terms: list[dict[str, Any]] = field(default_factory=list)
    skip_suffixes: tuple[str, ...] = DEFAULT_SKIP_SUFFIXES
    root: Path | None = None


class CannotEstablish(Exception):
    """The check could not run. Reported as `unknown`, never as clean."""


def load_declaration(path: Path) -> Declaration:
    if yaml is None:
        raise CannotEstablish("PyYAML is not installed, so the declaration cannot be read")
    if not path.is_file():
        raise CannotEstablish(f"declaration not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CannotEstablish(f"declaration is not valid YAML: {exc}") from exc

    terms = raw.get("terms") or []
    if not isinstance(terms, list) or not terms:
        raise CannotEstablish(f"declaration lists no terms: {path}")
    for entry in terms:
        if not isinstance(entry, dict) or not entry.get("term"):
            raise CannotEstablish(f"every term needs a `term:` key: {entry!r}")

    skip = raw.get("skip_suffixes")
    return Declaration(
        terms=terms,
        skip_suffixes=tuple(skip) if skip else DEFAULT_SKIP_SUFFIXES,
    )


def repo_root(start: Path) -> Path:
    """The git root. Asked of git, never assembled from `.git` as a path: in a worktree
    `.git` is a FILE containing a gitdir pointer, so anything treating it as a directory
    reports the wrong answer in exactly the checkout we do merges in."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise CannotEstablish(f"not a git repository (or git is unavailable): {start}") from exc
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def scan(decl: Declaration, root: Path) -> tuple[list[Finding], int]:
    """Read-only. Returns the findings and how many files were actually read."""
    compiled = [
        (
            entry["term"],
            re.compile(entry["term"], re.IGNORECASE) if entry.get("regex")
            else re.compile(re.escape(entry["term"]), re.IGNORECASE),
            tuple(entry.get("allow") or ()),
        )
        for entry in decl.terms
    ]

    findings: list[Finding] = []
    checked = 0
    for rel in tracked_files(root):
        if rel.endswith(decl.skip_suffixes):
            continue
        applicable = [
            (term, pattern)
            for term, pattern, allow in compiled
            if not any(rel.startswith(prefix) for prefix in allow)
        ]
        if not applicable:
            continue

        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        checked += 1

        for lineno, line in enumerate(text.splitlines(), 1):
            for term, pattern in applicable:
                if pattern.search(line):
                    findings.append(
                        Finding(where=f"{rel}:{lineno}", what=line.strip()[:120], term=term)
                    )
                    break
    return findings, checked


def run(config_path: Path, start: Path) -> dict[str, Any]:
    ran_at = datetime.now(timezone.utc).isoformat()
    probe = f"python -m ops.automations.{AUTOMATION} --config {config_path}"
    try:
        decl = load_declaration(config_path)
        root = repo_root(start)
        findings, checked = scan(decl, root)
    except CannotEstablish as exc:
        return {
            "automation": AUTOMATION,
            "status": "unknown",
            "reason": str(exc),
            "checked": 0,
            "findings": [],
            "ran_at": ran_at,
            "probe": probe,
        }

    return {
        "automation": AUTOMATION,
        "status": "findings" if findings else "ok",
        "checked": checked,
        "terms": [entry["term"] for entry in decl.terms],
        "findings": [f.as_dict() for f in findings],
        "ran_at": ran_at,
        "probe": probe,
    }


def _default_config(start: Path) -> Path:
    try:
        return repo_root(start) / "ops" / "config" / f"{AUTOMATION}.yaml"
    except CannotEstablish:
        return Path("ops") / "config" / f"{AUTOMATION}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--config", type=Path, default=None, help="declaration file")
    args = parser.parse_args(argv)

    start = Path.cwd()
    config_path = args.config or _default_config(start)
    result = run(config_path, start)

    if args.json:
        print(json.dumps(result, indent=2))
    elif result["status"] == "unknown":
        print(f"UNKNOWN: {result['reason']}")
    elif result["status"] == "ok":
        print(f"OK: {result['checked']} files, no retired term found "
              f"({', '.join(result['terms'])}).")
    else:
        print(f"FINDINGS: {len(result['findings'])} line(s) name a retired term.")
        for item in result["findings"]:
            print(f"  {item['where']}  [{item['term']}]  {item['what']}")
        print("\nEach line is either a real leftover to remove, or history that belongs in the "
              f"`allow:` list in {config_path} with a written reason.")

    return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compile .claudeignore into the Read() deny rules Claude Code actually enforces.

Why this exists
---------------
A bare `.claudeignore` does nothing. Measured 2026-08-19 against the Claude Code
2.1.235 binary: the string "claudeignore" appears 0 times, ".gitignore" appears 95.
What does gate a file read is a `Read(<glob>)` entry in `permissions.deny` — the
binary's own words are "deny reading within the sandbox. Merged with paths from
Read(".

An ignore file nothing reads is the same defect class as a permission rule the tool
silently rejects (memory `claude-write-deny-rules-are-silently-inert`): a hole in the
cage that reads as a redundancy. So `.claudeignore` is the source of truth a human
edits, and this script is what makes it real.

Report mode is the default. `--fix` writes.

    python3 scripts/claudeignore_sync.py          # report; exit 1 if drifted
    python3 scripts/claudeignore_sync.py --fix    # write the deny rules

settings.json is read ONCE at process start, so a write applies at the next launch
and never to the running session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IGNORE_FILE = REPO / ".claudeignore"
SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json"))
# What this script wrote last time. Without it a --fix could never retract a rule,
# because nothing would distinguish a generated entry from a hand-written one.
MANIFEST = SETTINGS.parent / ".claudeignore-generated.json"


def read_patterns(path: Path) -> list[str]:
    """Every non-comment, non-blank line, in file order, de-duplicated."""
    if not path.is_file():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def rules_for(patterns: list[str]) -> list[str]:
    return [f"Read({p})" for p in patterns]


def load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"FAIL  {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="write the deny rules into settings.json")
    args = ap.parse_args()

    patterns = read_patterns(IGNORE_FILE)
    if not patterns:
        print(f"FAIL  {IGNORE_FILE} is missing or has no patterns")
        return 2
    wanted = rules_for(patterns)

    settings = load_json(SETTINGS, {})
    perms = settings.setdefault("permissions", {})
    deny = list(perms.get("deny", []))
    previous = set(load_json(MANIFEST, []))

    # Anything a human put in deny by hand is kept verbatim and in place.
    hand_written = [r for r in deny if r not in previous]
    merged = hand_written + [r for r in wanted if r not in hand_written]

    if merged == deny:
        print(f"OK    {len(wanted)} Read() deny rules in sync with {IGNORE_FILE.name}")
        return 0

    added = [r for r in merged if r not in deny]
    removed = [r for r in deny if r not in merged]
    print(f"DRIFT {len(added)} to add, {len(removed)} to remove ({SETTINGS})")
    for r in added[:10]:
        print(f"  + {r}")
    for r in removed[:10]:
        print(f"  - {r}")
    if len(added) > 10 or len(removed) > 10:
        print(f"  ... {len(added) + len(removed) - 20} more")

    if not args.fix:
        print("report only; re-run with --fix to write")
        return 1

    perms["deny"] = merged
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    MANIFEST.write_text(json.dumps(wanted, indent=2) + "\n")
    print(f"WROTE {len(merged)} deny rules to {SETTINGS}")
    print("settings.json is read once at process start — this applies at the NEXT launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

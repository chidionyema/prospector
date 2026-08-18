#!/usr/bin/env python3
"""What is in this repo, what refers to what, and what nothing refers to at all.

WHY THIS EXISTS. Founder, 2026-08-18: "our repo is a mess also, no one knows what gets used and
what is dead code, dead file, dead doc." That is not a feeling, it is a measurement nobody had
taken. This takes it.

WHAT IT DOES. It reads every git-tracked file once, builds an index of who mentions whom, and
prints the files nothing mentions. It is READ ONLY. There is no --fix and there should not be
one: "nothing refers to this" is a lead, not a verdict, and the deletion decision is a person's.

HOW A FILE COUNTS AS REFERENCED. Any other tracked file that contains

  * its repo-relative path            docs/RUNBOOKS.md
  * its bare filename                 RUNBOOKS.md
  * for Python, its import path       prospector.pack_linter  /  from .pack_linter import
  * for Python, its module stem       pack_linter

The last one is deliberately generous. A stem match produces false NEGATIVES for deadness (a
live-looking file that is actually dead), never false positives. That is the right way round: a
census that over-reports dead code gets ignored after the first wrong entry.

WHAT IT DELIBERATELY DOES NOT DO. It does not run the code, so it cannot see a module reached
only by `importlib`, a getattr, or a string in a database. Those are exactly the paths
`dynamic-import-hides-callers-from-grep` records. Anything in the ENTRYPOINTS set below is
excluded for that reason: a launchd plist, a CI workflow, a console button or a docs runbook
naming a script is a real caller even when no import exists.

USAGE
    .venv/bin/python scripts/estate_census.py               # the summary
    .venv/bin/python scripts/estate_census.py --json        # the full receipt
    .venv/bin/python scripts/estate_census.py --bucket docs # one bucket in detail
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Directories whose contents are vendored, generated or runtime state. Their files are still
#: read as REFERRERS (a plist naming a script is a real caller) but are never CANDIDATES.
NOT_CANDIDATES = (
    "store/", "storage/", "graphify-out/", "node_modules/", ".next/", "dist/",
    "store_platform/src/Store.Catalog/Migrations/",  # EF generates these; nothing imports them
)

#: Extensions worth reading. Anything else is treated as a binary and skipped.
TEXTUAL = {
    ".py", ".md", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cs", ".yaml", ".yml", ".json",
    ".sh", ".toml", ".ini", ".cfg", ".txt", ".sql", ".html", ".css", ".plist", ".env",
}

#: A file matching one of these is an ENTRY POINT: something outside the repo invokes it, so
#: "nothing imports it" says nothing about whether it is alive.
ENTRYPOINT_PATTERNS = (
    re.compile(r"^\.github/"),
    re.compile(r"^ops/launchd/"),
    re.compile(r"^tests?/"),
    re.compile(r"conftest\.py$"),
    re.compile(r"^README\.md$"),
    re.compile(r"^CLAUDE\.md$"),
    re.compile(r"^config\.yaml$"),
    re.compile(r"/__init__\.py$"),
    re.compile(r"^store_platform/src/[^/]+/Program\.cs$"),
)


def buckets(path: str) -> str:
    """Which pile a file belongs to. The piles are the ones the founder named."""
    if path.startswith("docs/personas/"):
        return "persona docs"
    if path.endswith(".md"):
        return "docs"
    if path.startswith("tools/"):
        return "tools"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith("ops/"):
        return "ops"
    if path.startswith("prospector/"):
        return "engine"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("store_platform/"):
        return "store platform"
    return "other"


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def is_candidate(path: str) -> bool:
    if any(path.startswith(p) for p in NOT_CANDIDATES):
        return False
    return Path(path).suffix in TEXTUAL


def is_entrypoint(path: str) -> bool:
    return any(p.search(path) for p in ENTRYPOINT_PATTERNS)


def needles(path: str) -> list[str]:
    """Every string that, appearing in another file, means "this file is used"."""
    p = Path(path)
    out = [path, p.name]
    if p.suffix == ".py":
        stem = p.stem
        out.append(stem)
        # prospector/ops/runs.py -> prospector.ops.runs
        out.append(".".join(p.with_suffix("").parts))
    if p.suffix in {".ts", ".tsx"}:
        out.append(p.stem)
    return [n for n in dict.fromkeys(out) if len(n) > 3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the full receipt as JSON")
    ap.add_argument("--bucket", help="show every unreferenced file in one bucket")
    args = ap.parse_args()

    files = tracked()
    texts: dict[str, str] = {}
    for f in files:
        if Path(f).suffix not in TEXTUAL:
            continue
        try:
            texts[f] = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

    candidates = [f for f in files if is_candidate(f)]
    # One pass per candidate over every OTHER file's text is O(n^2) on 1700 files, which is
    # tolerable (seconds) and far simpler than an inverted index that would need a tokenizer
    # agreeing with four languages' import syntax.
    refs: dict[str, int] = {}
    referrers: dict[str, list[str]] = {}
    for cand in candidates:
        ns = needles(cand)
        who: list[str] = []
        for other, text in texts.items():
            if other == cand:
                continue
            if any(n in text for n in ns):
                who.append(other)
        refs[cand] = len(who)
        referrers[cand] = who

    dead: dict[str, list[str]] = defaultdict(list)
    only_tests: dict[str, list[str]] = defaultdict(list)
    for cand in candidates:
        if is_entrypoint(cand):
            continue
        who = referrers[cand]
        if not who:
            dead[buckets(cand)].append(cand)
        elif all(w.startswith(("tests/", "store_platform/src/Store.Tests/")) for w in who):
            only_tests[buckets(cand)].append(cand)

    order = ["engine", "tools", "scripts", "ops", "docs", "persona docs", "store platform",
             "tests", "other"]
    totals = defaultdict(int)
    for f in candidates:
        totals[buckets(f)] += 1

    if args.json:
        json.dump(
            {
                "tracked": len(files),
                "candidates": len(candidates),
                "by_bucket": dict(totals),
                "unreferenced": {k: sorted(v) for k, v in dead.items()},
                "referenced_only_by_tests": {k: sorted(v) for k, v in only_tests.items()},
            },
            sys.stdout,
            indent=2,
        )
        print()
        return 0

    if args.bucket:
        b = args.bucket
        print(f"UNREFERENCED in {b!r} ({len(dead.get(b, []))}):")
        for f in sorted(dead.get(b, [])):
            print(f"  {f}")
        print(f"\nREFERENCED ONLY BY TESTS in {b!r} ({len(only_tests.get(b, []))}):")
        for f in sorted(only_tests.get(b, [])):
            print(f"  {f}")
        return 0

    print(f"estate census — {len(files)} tracked files, {len(candidates)} eligible for the check")
    print()
    print(f"{'bucket':<16}{'files':>7}{'nothing refers':>16}{'tests only':>13}")
    print("-" * 52)
    for b in order:
        if not totals.get(b):
            continue
        print(f"{b:<16}{totals[b]:>7}{len(dead.get(b, [])):>16}{len(only_tests.get(b, [])):>13}")
    print("-" * 52)
    print(f"{'TOTAL':<16}{len(candidates):>7}"
          f"{sum(len(v) for v in dead.values()):>16}"
          f"{sum(len(v) for v in only_tests.values()):>13}")
    print()
    print("'nothing refers' means no other tracked file contains this file's path, name, or")
    print("import path. It is a LEAD. Entry points (CI, launchd, tests, README) are excluded.")
    print("Run with --bucket <name> for the list, or --json for the whole receipt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

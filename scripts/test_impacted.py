#!/usr/bin/env python3
"""Run only the tests that can see your change.

The full suite is 3689 tests and about 324s on this machine at `-n auto`
(pytest.ini:34). Editing one file and paying all of it is the most common waste
in the local loop, and it is what the founder called out on 2026-08-17.

This script builds an import graph of the repo, walks it BACKWARDS from the files
you changed, and prints the test files that can reach them. Report mode is the
default; `--run` executes pytest on the selection.

    scripts/test_impacted.py                 # working tree vs HEAD, report only
    scripts/test_impacted.py --run           # and run them
    scripts/test_impacted.py --staged --run  # what a commit would test
    scripts/test_impacted.py --base main     # everything on this branch

It FAILS OPEN. Anything it cannot reason about — a changed conftest, pytest.ini,
config.yaml, a prompt file, a non-Python file it has no rule for — selects the
whole suite rather than a subset. A test selector that silently under-selects is
worse than no selector: it reports green for code it never ran.
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A change to any of these invalidates the whole selection, so we run everything.
# conftest.py is here rather than in the import graph because pytest loads it by
# path, not by import, so no test file names it and the graph would miss it.
RUN_EVERYTHING = (
    "pytest.ini",
    "config.yaml",
    "requirements.txt",
    "pyproject.toml",
)
RUN_EVERYTHING_PREFIX = (
    "prompts/",
    "fixtures/",
)


def sh(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def repo_py_files() -> list[Path]:
    out = sh("git", "ls-files", "-z", "*.py")
    return [ROOT / p for p in out.split("\0") if p]


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(path: Path) -> set[str]:
    """Dotted names this file imports. Text, not resolution — the caller matches
    them against the repo's own module names, so stdlib and site-packages fall
    out for free."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — resolve against this file's package
                pkg = module_name(path).split(".")
                pkg = pkg[: len(pkg) - node.level + 1] if node.level > 1 else pkg[:-1]
                base = ".".join(pkg)
                node_mod = f"{base}.{node.module}" if node.module else base
            else:
                node_mod = node.module or ""
            if node_mod:
                names.add(node_mod)
                for a in node.names:
                    names.add(f"{node_mod}.{a.name}")
    return names


def build_reverse_graph(files: list[Path]) -> dict[str, set[Path]]:
    """module dotted name -> files that import it (directly)."""
    known = {module_name(f): f for f in files}
    rev: dict[str, set[Path]] = defaultdict(set)
    for f in files:
        for name in imports_of(f):
            # `prospector.ops.runs.load` should credit `prospector.ops.runs`, so
            # walk the name back until it matches a real module.
            parts = name.split(".")
            while parts:
                cand = ".".join(parts)
                if cand in known:
                    rev[cand].add(f)
                    break
                parts.pop()
    return rev


def changed_files(args: argparse.Namespace) -> list[str]:
    if args.base:
        out = sh("git", "diff", "--name-only", f"{args.base}...HEAD")
    elif args.staged:
        out = sh("git", "diff", "--name-only", "--cached")
    else:
        out = sh("git", "diff", "--name-only", "HEAD")
        out += sh("git", "ls-files", "--others", "--exclude-standard")
    return sorted({line for line in out.splitlines() if line.strip()})


def all_test_files() -> list[str]:
    out = sh("git", "ls-files", "tests")
    return sorted(
        p for p in out.splitlines() if Path(p).name.startswith("test_") and p.endswith(".py")
    )


def select(changed: list[str]) -> tuple[list[str], str]:
    """Returns (test files to run, reason). An empty reason means a real selection."""
    if not changed:
        return [], "nothing changed"

    for c in changed:
        if c in RUN_EVERYTHING or any(c.startswith(p) for p in RUN_EVERYTHING_PREFIX):
            return all_test_files(), f"{c} invalidates the whole selection"
        if Path(c).name == "conftest.py":
            return all_test_files(), f"{c} is loaded by path, not imported"

    changed_py = [c for c in changed if c.endswith(".py")]
    changed_other = [c for c in changed if not c.endswith(".py")]
    if changed_other and not changed_py:
        # Data, docs or web files with no rule here. Docs alone need no python
        # tests, but this script cannot tell docs from a fixture the suite reads.
        non_doc = [c for c in changed_other if not c.endswith((".md", ".txt"))]
        if non_doc:
            return all_test_files(), f"no import rule for {non_doc[0]}"
        return [], "documentation only"

    files = repo_py_files()
    rev = build_reverse_graph(files)
    by_path = {str(f.relative_to(ROOT)): f for f in files}

    seen: set[Path] = set()
    queue: deque[Path] = deque()
    for c in changed_py:
        f = by_path.get(c)
        if f is None:  # a new file git has not tracked yet
            f = ROOT / c
            if not f.exists():
                continue
        if f not in seen:
            seen.add(f)
            queue.append(f)

    while queue:
        f = queue.popleft()
        for importer in rev.get(module_name(f), ()):
            if importer not in seen:
                seen.add(importer)
                queue.append(importer)

    tests = sorted(
        str(f.relative_to(ROOT))
        for f in seen
        if f.name.startswith("test_") and str(f.relative_to(ROOT)).startswith("tests/")
    )
    if changed_other:
        docs_only = all(c.endswith((".md", ".txt")) for c in changed_other)
        if not docs_only:
            return all_test_files(), f"no import rule for {changed_other[0]}"
    return tests, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staged", action="store_true", help="what a commit would test")
    ap.add_argument("--base", help="compare against this ref (e.g. main)")
    ap.add_argument("--run", action="store_true", help="run pytest, not just report")
    ap.add_argument("pytest_args", nargs="*", help="extra args passed to pytest")
    args = ap.parse_args()

    changed = changed_files(args)
    tests, reason = select(changed)
    total = len(all_test_files())

    print(f"changed files: {len(changed)}")
    for c in changed[:20]:
        print(f"  {c}")
    if len(changed) > 20:
        print(f"  ... and {len(changed) - 20} more")

    if reason and not tests:
        print(f"\nno tests to run — {reason}")
        return 0
    if reason:
        print(f"\nrunning ALL {len(tests)} test files — {reason}")
    else:
        pct = 100 * len(tests) / total if total else 0
        print(f"\n{len(tests)} of {total} test files impacted ({pct:.0f}%)")
        for t in tests[:40]:
            print(f"  {t}")
        if len(tests) > 40:
            print(f"  ... and {len(tests) - 40} more")

    if not args.run:
        print("\nreport only. add --run to execute.")
        return 0
    if not tests:
        return 0

    cmd = [sys.executable, "-m", "pytest", "-q", *tests, *args.pytest_args]
    print(f"\n$ {' '.join(cmd[:4])} ... ({len(tests)} files)")
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())

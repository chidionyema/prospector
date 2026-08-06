#!/usr/bin/env python3
"""Graphify estate scoreboard — READ-ONLY.

Implements the freshness contract in docs/GRAPHIFY_ENFORCEMENT_SPEC.md §4.1 and reports
R2 (universal), R3 (never stale) and R8 (not tracked in git) for every git repo under the
estate root.

    FRESH  := graph.json exists AND mtime >= HEAD committer time
              AND no tracked source file is newer than it
    STALE  := graph exists but fails that
    ABSENT := no graph at all

RULES THIS SCRIPT OBEYS (each is a rule the estate learned the hard way):
  * It never writes. Not a mkdir, not a lock. A probe that mutates is worse than none.
  * It reports the number it measured, never a judgement about it.
  * Exit 0 only when ABSENT, STALE and TRACKED are all zero. Anything else exits 1, so it
    can gate a hook without a human reading the table.

Usage:
    graphify_sweep.py                 # full table
    graphify_sweep.py --brief         # one line, for injection into a session
    graphify_sweep.py --root DIR      # override the estate root
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ESTATE_ROOT = os.path.expanduser("~/Documents/code")

# Extensions graphify extracts from. Deliberately excludes .json: store/ and storage/ are
# tracked *runtime state* that the daemon rewrites constantly, and counting them would make
# every graph permanently stale for reasons that have nothing to do with the code.
SOURCE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cs", ".go", ".rs", ".java", ".rb",
    ".sh", ".md", ".yaml", ".yml", ".sql", ".html", ".css", ".scss",
}
EXCLUDE_PREFIX = ("graphify-out/", "node_modules/", "store/", "storage/", ".venv/", "venv/")

SKIP_MARKER = ".graphify-skip"  # opt-out file, per spec decision S1


def git(repo: str, *args: str) -> str | None:
    """Run a git command in repo; None if it fails. Never raises."""
    try:
        out = subprocess.run(
            ("git", "-C", repo) + args,
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def discover(root: str) -> list[str]:
    """Every git repo one level under root. Enumerated at run time — never a hardcoded
    list — so a repo created tomorrow is covered without editing this file (spec G-DISCOVER)."""
    repos = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return repos
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        # In a worktree .git is a FILE containing `gitdir:`, so test existence, not isdir.
        if os.path.exists(os.path.join(path, ".git")):
            repos.append(path)
    return repos


def newest_source_mtime(repo: str) -> tuple[float, str | None]:
    """(mtime, path) of the newest tracked source file. (0.0, None) if none found."""
    listing = git(repo, "ls-files", "-z")
    if listing is None:
        return 0.0, None
    best, best_path = 0.0, None
    for rel in listing.split("\0"):
        if not rel or rel.startswith(EXCLUDE_PREFIX):
            continue
        if os.path.splitext(rel)[1] not in SOURCE_EXT:
            continue
        try:
            m = os.stat(os.path.join(repo, rel)).st_mtime
        except OSError:
            continue  # deleted-but-tracked; not evidence of anything
        if m > best:
            best, best_path = m, rel
    return best, best_path


def head_time(repo: str) -> float:
    out = git(repo, "log", "-1", "--format=%ct")
    if not out or not out.strip().isdigit():
        return 0.0
    return float(out.strip())


def assess(repo: str) -> dict:
    name = os.path.basename(repo)
    row = {"name": name, "repo": repo, "state": "ABSENT", "age_days": None,
           "reason": "", "tracked": 0, "ignored": False, "skipped": False}

    if os.path.exists(os.path.join(repo, SKIP_MARKER)):
        row["state"] = "SKIP"
        row["skipped"] = True
        return row

    tracked = git(repo, "ls-files", "graphify-out")
    row["tracked"] = len([x for x in (tracked or "").splitlines() if x])
    try:
        with open(os.path.join(repo, ".gitignore")) as fh:
            row["ignored"] = any("graphify" in line for line in fh)
    except OSError:
        row["ignored"] = False

    graph = os.path.join(repo, "graphify-out", "graph.json")
    try:
        gm = os.stat(graph).st_mtime
    except OSError:
        row["reason"] = "no graphify-out/graph.json"
        return row

    row["age_days"] = (time.time() - gm) / 86400.0
    ht = head_time(repo)
    nm, np_ = newest_source_mtime(repo)

    if ht and gm < ht:
        row["state"] = "STALE"
        row["reason"] = f"older than HEAD by {(ht - gm) / 86400:.1f}d"
    elif nm and gm < nm:
        row["state"] = "STALE"
        row["reason"] = f"older than {np_}"
    else:
        row["state"] = "FRESH"
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ESTATE_ROOT)
    ap.add_argument("--brief", action="store_true",
                    help="one line, for injection into a session")
    args = ap.parse_args()

    rows = [assess(r) for r in discover(args.root)]
    absent = sum(1 for r in rows if r["state"] == "ABSENT")
    stale = sum(1 for r in rows if r["state"] == "STALE")
    fresh = sum(1 for r in rows if r["state"] == "FRESH")
    tracked = sum(r["tracked"] for r in rows)
    ok = absent == 0 and stale == 0 and tracked == 0

    if args.brief:
        mark = "OK" if ok else "ACTION NEEDED"
        print(f"[graphify] {mark} — fresh {fresh} / stale {stale} / absent {absent} "
              f"/ git-tracked graph files {tracked} (of {len(rows)} repos)")
        return 0 if ok else 1

    print(f"── GRAPHIFY ESTATE SWEEP ── {time.strftime('%Y-%m-%d %H:%M')} — root {args.root}")
    print(f"{'REPO':<24}{'STATE':<8}{'AGE(d)':>8}  {'TRACKED':>7} {'IGN':>4}  REASON")
    for r in sorted(rows, key=lambda x: (x["state"] != "STALE", x["state"] != "ABSENT", x["name"])):
        age = f"{r['age_days']:.1f}" if r["age_days"] is not None else "-"
        ign = "yes" if r["ignored"] else "NO"
        print(f"{r['name'][:23]:<24}{r['state']:<8}{age:>8}  {r['tracked']:>7} {ign:>4}  {r['reason']}")
    print("──")
    print(f"repos {len(rows)}   FRESH {fresh}   STALE {stale}   ABSENT {absent}   "
          f"graph files tracked in git {tracked}")
    print(f"VERDICT: {'✅ spec R2/R3/R8 satisfied' if ok else '❌ see docs/GRAPHIFY_ENFORCEMENT_SPEC.md'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

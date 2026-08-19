#!/usr/bin/env python3
"""Keep the shared developer checkout on origin/main, so no session is briefed from stale rules.

WHY THIS EXISTS. Measured 2026-08-19: /Users/chidionyema/Documents/code/prospector was 64 commits
behind origin/main with 0 commits ahead. That checkout is the harness's primary working directory,
so its CLAUDE.md is what gets injected as project instructions into EVERY session started there.
Sessions were being briefed from rules 64 commits old while production ran main. The same drift
had already been written down twice -- memory `read-docs-on-origin-main-not-the-shared-checkout`
recorded it at ~75 commits behind -- and writing it down a third time would have changed nothing.

Founder, 2026-08-19: "i dont wat recurring issues arrrrrrrrghhhhhhh this is why we always stuck in
naintenane node". So this is the machine that stops it recurring, not another note.

WHY IT IS SAFE TO FAST-FORWARD A CHECKOUT SOMEBODY ELSE MIGHT BE IN

Three fences, and all three must pass:

  1. NOTHING IS LOST. Uncommitted work is snapshotted to a remote branch first, by
     scripts/worktree_snapshot.py, which does not touch the tree it copies. If the snapshot
     fails, this refuses to move.
  2. NOTHING IS ORPHANED. It refuses when the checkout has commits origin/main does not have.
     Fast-forwarding then would strand them, and that is worktree_census.py's problem, not this
     one.
  3. NOBODY IS TYPING. It refuses when a tracked file was modified in the last QUIET_MINUTES.
     A checkout being edited right now is a session at work, and yanking the tree under it is
     the meddling this whole family of tools exists to avoid.

It moves HEAD with `checkout -f --detach`, never `clean`. Untracked files -- a half-written
script, a scratch note -- are left exactly where they are.

REPORT ONLY by default.

USAGE
    .venv/bin/python scripts/checkout_currency.py           # how stale is it
    .venv/bin/python scripts/checkout_currency.py --fix     # snapshot, then fast-forward
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# A checkout touched more recently than this has somebody in it.
QUIET_MINUTES = 20

RUNTIME = ("store/", "storage/", "graphify-out/", ".popdd/", ".backfill-logs/", "signals/")


def git(repo: Path, *args: str, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       timeout=timeout, check=False)
    return p.returncode, (p.stdout or p.stderr).strip()


def tracked_edits(repo: Path) -> list[str]:
    """Modified tracked files that are somebody's work, not what pytest wrote to store/."""
    _, out = git(repo, "status", "--porcelain", "--untracked-files=no")
    rows = []
    for ln in out.splitlines():
        # Split, never slice a fixed column: git()'s .strip() has already eaten the first line's
        # leading status space. tests/unit/test_porcelain_is_never_sliced_by_column.py enforces it.
        parts = ln.strip().split(maxsplit=1)
        if len(parts) == 2 and not parts[1].startswith(RUNTIME):
            rows.append(parts[1].split(" -> ")[-1])
    return rows


def minutes_since_touched(repo: Path, rels: list[str]) -> float:
    newest = 0.0
    for rel in rels:
        try:
            newest = max(newest, (repo / rel).stat().st_mtime)
        except OSError:
            pass
    return (time.time() - newest) / 60 if newest else 1e9


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true", help="snapshot, then fast-forward")
    ap.add_argument("--repo", default="", help="checkout to grade (default: this one)")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent.parent
    _, common = git(here, "rev-parse", "--git-common-dir")
    # In a worktree `.git` is a FILE, and --git-common-dir points at the main checkout's .git.
    # Its parent is the shared checkout, which is the only one this script is about.
    repo = Path(args.repo) if args.repo else Path(common).resolve().parent

    code, _ = git(repo, "fetch", "-q", "origin", "main")
    if code != 0:
        print(f"BLOCKED: cannot fetch origin/main in {repo}")
        return 1

    _, behind = git(repo, "rev-list", "--count", "HEAD..origin/main")
    _, ahead = git(repo, "rev-list", "--count", "origin/main..HEAD")
    behind_n, ahead_n = int(behind or 0), int(ahead or 0)
    edits = tracked_edits(repo)
    quiet = minutes_since_touched(repo, edits)

    print(f"checkout {repo}")
    print(f"  behind origin/main : {behind_n}")
    print(f"  ahead of it        : {ahead_n}")
    print(f"  tracked edits      : {len(edits)}")
    print(f"  last touched       : {quiet:.0f} min ago" if quiet < 1e8 else
          "  last touched       : never")

    if behind_n == 0:
        print("\nCurrent. Every session started here reads main's CLAUDE.md.")
        return 0

    print(f"\nSTALE. Sessions started here are briefed from CLAUDE.md {behind_n} commits old.")

    if ahead_n:
        print(f"REFUSING: {ahead_n} commit(s) here are on no remote. Fast-forwarding would "
              f"strand them.\n  .venv/bin/python scripts/worktree_census.py")
        return 1
    if quiet < QUIET_MINUTES:
        print(f"REFUSING: touched {quiet:.0f} min ago, so somebody is working here. "
              f"Try again after {QUIET_MINUTES} min of quiet.")
        return 1
    if not args.fix:
        print("\nReport only. Run again with --fix to snapshot the uncommitted work and "
              "fast-forward.")
        return 1

    if edits:
        print(f"\nSnapshotting {len(edits)} uncommitted file(s) first...")
        snap = subprocess.run(
            [sys.executable, str(here / "scripts" / "worktree_snapshot.py"), "--push"],
            capture_output=True, text=True, timeout=900, check=False)
        print(snap.stdout.strip() or snap.stderr.strip())
        if snap.returncode != 0:
            print("BLOCKED: the snapshot failed, so nothing is being discarded.")
            return 1

    code, out = git(repo, "checkout", "-f", "--detach", "origin/main")
    if code != 0:
        print(f"BLOCKED: {out}")
        return 1
    _, head = git(repo, "rev-parse", "--short", "HEAD")
    print(f"\nFast-forwarded {behind_n} commits to {head}. Untracked files were left alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

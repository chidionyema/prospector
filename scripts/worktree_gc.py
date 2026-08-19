#!/usr/bin/env python3
"""Which worktrees are safe to delete? Report by default, --fix removes them.

WHY THIS EXISTS. Founder, 2026-08-18: "worktrees not cleaned up etc". Measured the same day:
26 worktrees existed in this checkout. Each one is a tree a session can edit by mistake, and a
branch that looks alive when its work has already merged. docs/WAYS_OF_WORKING.md W23.

SAFE TO REMOVE means all three, never fewer:
  1. it is not the worktree you are standing in
  2. it has no uncommitted work (store/ and storage/ are runtime state, ignored here)
  3. nothing would be lost: either its HEAD is an ancestor of origin/main, or its branch is
     the head of a MERGED pull request

THE SECOND HALF OF RULE 3 IS THE LOAD-BEARING ONE. This repo squash-merges, so a merged
branch's commits never become ancestors of origin/main -- the squash is a new commit with a
new sha. Ancestry alone therefore reports every merged branch as unfinished work, forever.
Measured 2026-08-19: 35 worktrees, "SAFE TO REMOVE (0)", while `fix/session-check-script-exists`
at 1a90fb41 had merged as PR #367 twenty minutes earlier. A gc that can never mark anything
safe is why 35 accumulated.

Anything failing one of those is KEPT and the reason is printed. A worktree holding unmerged
commits is somebody's unfinished work, and this script will never delete it.

USAGE
    .venv/bin/python scripts/worktree_gc.py           # report only
    .venv/bin/python scripts/worktree_gc.py --fix     # remove the ones marked safe
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd or ROOT,
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def worktrees() -> list[dict]:
    _, out = git(["worktree", "list", "--porcelain"])
    trees, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                trees.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val or True
    if cur:
        trees.append(cur)
    return trees


def merged_branches() -> tuple[set[str], str | None]:
    """Branch names whose pull request is MERGED, in ONE call.

    Asked per worktree this would be 35 round trips to GitHub. Asked once it is one, so the
    whole check costs about a second. Returns the set and, when the call fails, the reason --
    the caller degrades to sha-ancestry rather than guessing that nothing is merged.
    """
    try:
        p = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "300",
             "--json", "headRefName", "--jq", ".[].headRefName"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return set(), f"{type(exc).__name__}"
    if p.returncode != 0:
        return set(), (p.stderr.strip().splitlines() or ["gh failed"])[0]
    return {ln.strip() for ln in p.stdout.splitlines() if ln.strip()}, None


def dirty(path: Path) -> list[str]:
    code, out = git(["status", "--porcelain"], cwd=path)
    if code != 0:
        return ["git status failed"]
    paths = []
    for ln in out.splitlines():
        parts = ln.strip().split(maxsplit=1)
        if len(parts) == 2 and not parts[1].startswith(("store/", "storage/")):
            paths.append(parts[1])
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true", help="remove the worktrees marked safe")
    ap.add_argument("--all-sessions", action="store_true",
                    help="also consider worktrees owned by another agent session")
    args = ap.parse_args()

    git(["worktree", "prune"])
    here = Path.cwd().resolve()
    # A scratchpad path carries the owning session id: /private/tmp/claude-*/<slug>/<session>/...
    # Another session's tree may be clean and merged and still be in active use, and pulling the
    # ground out from under a running session is exactly the "another session's work" exception in
    # docs/WAYS_OF_WORKING.md W14. Skip those unless asked, rather than trusting a judgement call.
    mine = ""
    for part in here.parts:
        if len(part) == 36 and part.count("-") == 4:
            mine = part
            break

    def other_session(path: Path) -> str:
        for part in path.parts:
            if len(part) == 36 and part.count("-") == 4 and part != mine:
                return part
        return ""

    main_tree = worktrees()[0].get("worktree") if worktrees() else None

    safe, keep = [], []
    merged, gh_error = merged_branches()
    if gh_error:
        print(f"note: could not list merged PRs ({gh_error}); "
              "falling back to sha-ancestry, which misses every squash-merged branch\n")

    for wt in worktrees():
        path = Path(str(wt.get("worktree")))
        head = str(wt.get("HEAD", ""))[:8]
        branch = str(wt.get("branch", "detached")).replace("refs/heads/", "")
        if str(path) == main_tree:
            keep.append((path, branch, head, "the main checkout"))
            continue
        if here == path.resolve() or here.is_relative_to(path.resolve()):
            keep.append((path, branch, head, "you are standing in it"))
            continue
        owner = other_session(path)
        if owner and not args.all_sessions:
            keep.append((path, branch, head,
                         f"owned by session {owner[:8]}; --all-sessions to include"))
            continue
        if not path.exists():
            keep.append((path, branch, head, "path is gone; run git worktree prune"))
            continue
        d = dirty(path)
        if d:
            keep.append((path, branch, head, f"{len(d)} uncommitted file(s), first {d[0]}"))
            continue
        code, _ = git(["merge-base", "--is-ancestor", str(wt.get("HEAD")), "origin/main"])
        if code != 0 and branch not in merged:
            why = "holds commits not in origin/main"
            if gh_error:
                why += f" (could not ask GitHub whether it merged: {gh_error})"
            keep.append((path, branch, head, why))
            continue
        safe.append((path, branch, head))

    print(f"worktree gc — {len(safe) + len(keep)} worktrees\n")
    print(f"SAFE TO REMOVE ({len(safe)}): clean, merged into origin/main, not in use")
    for path, branch, head in safe:
        print(f"  {head}  {branch:<40} {path}")
    print()
    print(f"KEEP ({len(keep)}):")
    for path, branch, head, why in keep:
        print(f"  {head}  {branch:<40} {why}")
    print()

    if not args.fix:
        print("report only. To remove the safe ones:")
        print("  .venv/bin/python scripts/worktree_gc.py --fix")
        return 0

    removed = 0
    for path, branch, _ in safe:
        code, _ = git(["worktree", "remove", str(path)])
        if code != 0:
            code, _ = git(["worktree", "remove", "--force", str(path)])
        if code == 0:
            removed += 1
            print(f"removed {path}")
            if branch != "detached":
                git(["branch", "-d", branch])
        else:
            print(f"FAILED to remove {path}")
    print(f"\nremoved {removed} of {len(safe)}")
    return 0 if removed == len(safe) else 1


if __name__ == "__main__":
    raise SystemExit(main())

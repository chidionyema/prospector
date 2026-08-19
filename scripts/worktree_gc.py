#!/usr/bin/env python3
"""Which worktrees are safe to delete, and which have drifted from main? Report by default.

DIVERGENCE, added 2026-08-19. Founder: "need to address branch and worktree divergence from main
branch, need constant refresh". The cost is measured rather than hypothetical: two developer
checkouts sat 60 commits behind origin/main, and the CLAUDE.md the agent harness injects comes
from whichever one a session was started in. An agent read a pre-Fly copy, graded this Mac's
launchd jobs as the production process table, and reported an outage while the engine was ruling
verdicts in lhr. A branch that drifts is not just harder to merge; it briefs every session that
opens in it with an older estate.

--refresh fast-forwards only. A worktree with no local commits is moved to origin/main, which
cannot conflict and cannot lose work. A branch that HAS local commits is reported with its exact
rebase command and never touched: rebasing another session's unfinished work automatically is how
work disappears.

WHY THIS EXISTS. Founder, 2026-08-18: "worktrees not cleaned up etc". Measured the same day:
26 worktrees existed in this checkout. Each one is a tree a session can edit by mistake, and a
branch that looks alive when its work has already merged. docs/WAYS_OF_WORKING.md W23.

SAFE TO REMOVE means all three, never fewer:
  1. it is not the worktree you are standing in
  2. it has no uncommitted work (store/ and storage/ are runtime state, ignored here)
  3. its HEAD is already an ancestor of origin/main, so nothing would be lost

Anything failing one of those is KEPT and the reason is printed. A worktree holding unmerged
commits is somebody's unfinished work, and this script will never delete it.

USAGE
    .venv/bin/python scripts/worktree_gc.py           # report only
    .venv/bin/python scripts/worktree_gc.py --fix     # remove the ones marked safe
"""
from __future__ import annotations

import argparse
import json
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


def divergence(path: Path) -> tuple[int, int]:
    """(behind, ahead) against origin/main. (-1, -1) when it cannot be measured."""
    code, out = git(["rev-list", "--left-right", "--count", "origin/main...HEAD"], cwd=path)
    if code != 0 or not out:
        return -1, -1
    parts = out.split()
    if len(parts) != 2 or not all(x.isdigit() for x in parts):
        return -1, -1
    return int(parts[0]), int(parts[1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true", help="remove the worktrees marked safe")
    ap.add_argument("--refresh", action="store_true",
                    help="fetch origin/main, then fast-forward every worktree that has no local "
                         "commits; branches with local commits are reported, never rebased")
    ap.add_argument("--json", action="store_true", help="machine-readable report, for the audit")
    ap.add_argument("--all-sessions", action="store_true",
                    help="also consider worktrees owned by another agent session")
    args = ap.parse_args()

    git(["worktree", "prune"])
    # Every number below is "as of the last fetch". Under --refresh, make that now.
    if args.refresh:
        git(["fetch", "--quiet", "origin", "main"])
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
        if code != 0:
            keep.append((path, branch, head, "holds commits not in origin/main"))
            continue
        safe.append((path, branch, head))

    # Divergence is measured for the KEEP set only. The SAFE set is already an ancestor of
    # origin/main by definition, and it is on its way out.
    drift = []
    for path, branch, head, why in keep:
        if not path.exists():
            continue
        behind, ahead = divergence(path)
        if behind > 0:
            drift.append({"path": str(path), "branch": branch, "head": head,
                          "behind": behind, "ahead": ahead,
                          "clean": not dirty(path),
                          "action": ("fast-forward" if ahead == 0 else "rebase")})

    if args.json:
        print(json.dumps({
            "safe": [{"path": str(p_), "branch": b, "head": h} for p_, b, h in safe],
            "keep": [{"path": str(p_), "branch": b, "head": h, "why": w} for p_, b, h, w in keep],
            "drift": drift,
        }, indent=2))
        return 0

    print(f"worktree gc — {len(safe) + len(keep)} worktrees\n")
    print(f"SAFE TO REMOVE ({len(safe)}): clean, merged into origin/main, not in use")
    for path, branch, head in safe:
        print(f"  {head}  {branch:<40} {path}")
    print()
    print(f"KEEP ({len(keep)}):")
    for path, branch, head, why in keep:
        print(f"  {head}  {branch:<40} {why}")
    print()
    print(f"BEHIND origin/main ({len(drift)}):")
    for d in drift:
        state = "clean" if d["clean"] else "DIRTY"
        print(f"  {d['head']}  {d['branch']:<40} {d['behind']} behind, {d['ahead']} ahead, "
              f"{state}, needs {d['action']}")
    print()

    if args.refresh:
        moved, stuck = 0, 0
        for d in drift:
            # Fast-forward only, and only a clean tree. A branch carrying local commits needs a
            # rebase, which can conflict and can lose work, and it may belong to a session that is
            # using it right now. Print the command and let its owner run it.
            if d["action"] != "fast-forward" or not d["clean"]:
                stuck += 1
                print(f"  SKIPPED {d['branch']}: {d['ahead']} local commit(s), "
                      f"{'clean' if d['clean'] else 'uncommitted work'} — run it yourself:")
                print(f"          git -C {d['path']} rebase origin/main")
                continue
            code, _ = git(["merge", "--ff-only", "origin/main"], cwd=Path(d["path"]))
            if code == 0:
                moved += 1
                print(f"  fast-forwarded {d['branch']} to origin/main")
            else:
                stuck += 1
                print(f"  FAILED to fast-forward {d['branch']}")
        print(f"\nrefreshed {moved}, left alone {stuck}")
        return 0

    if not args.fix:
        print("report only. To remove the safe ones, or to close the gap to main:")
        print("  .venv/bin/python scripts/worktree_gc.py --fix")
        print("  .venv/bin/python scripts/worktree_gc.py --refresh")
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

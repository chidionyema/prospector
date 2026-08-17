#!/usr/bin/env python3
"""Which branches carry work that has not landed, and which are safe to delete? Read-only.

WHY THIS EXISTS
---------------
On 2026-08-17 the repo held 58 local branches and 43 open worktrees. Asked how much of that was
real unmerged work, three probes gave three different answers and two of them were lies:

  * `git rev-list --count origin/main..<branch>` counts COMMITS. This repo squash-merges, which
    writes one new commit with a new sha, so a fully landed branch keeps a non-zero count
    forever. It said 61.
  * `git cherry origin/main <branch>` compares PATCH IDS, and is defeated by squash for the same
    reason: the squash commit's patch-id matches none of the originals, so every commit on a
    landed branch reads `+` forever. It said 46. Also wrong.
  * `git merge-tree --write-tree origin/main <branch>` performs the merge in memory and hands
    back the resulting tree. If that tree equals main's own tree, merging the branch changes
    nothing — the work is in. That is not a heuristic, it is the merge.

The corrected figures: 15 landed, 7 carrying real change, 36 conflicting.

The second lesson is about deleting. `git branch -D` refuses any branch a worktree has checked
out, so a delete list that ignores worktrees fails on most of its entries. This prints the
worktree that holds each landed branch and the exact two commands to release it, in order.

`age_days` is what makes the number readable: a branch untouched for a week is a decision, a
branch from this morning is work in flight.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

#: Branch prefixes that exist to reconcile the repo with itself rather than to carry a feature
#: or a fix. Reported separately because the cure differs: real work needs a pull request,
#: scratch needs deleting once its content is upstream.
SCRATCH_PREFIXES = ("merge/", "salvage/", "converge/", "integrate/", "capture/",
                    "backup/", "worktree-agent-", "pr/", "wip/", "tmp/")

LANDED, CARRIES, CONFLICT = "landed", "carries", "conflict"


def sh(*cmd: str, timeout: int = 120) -> tuple[int, str]:
    """Exit code AND stdout. Both matter here — `merge-tree` signals conflict by exit code."""
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return out.returncode, out.stdout.strip()


def is_scratch(branch: str) -> bool:
    if branch.startswith(SCRATCH_PREFIXES):
        return True
    # `pr250`, `resolve269` — a session naming a branch after the thing it was fighting.
    return branch[:2] == "pr" and branch[2:].isdigit() or branch.startswith("resolve")


def pr_state_by_branch() -> dict[str, str] | None:
    """head branch -> newest PR state, over EVERY pull request, not just the open ones.

    `--state all` is load-bearing. Querying only open PRs once produced the claim that 20
    branches were "work nobody ever proposed"; against all states, 17 of those 20 had a MERGED
    pull request. Returns None on failure so the caller can print "unknown" rather than
    reporting every branch in the repo as abandoned.
    """
    code, raw = sh("gh", "pr", "list", "--state", "all", "--limit", "500",
                   "--json", "number,headRefName,state")
    if code != 0 or not raw:
        return None
    try:
        rows = json.loads(raw)
    except ValueError:
        return None
    # Highest PR number wins: the newest proposal for that branch is the current one.
    best: dict[str, tuple[int, str]] = {}
    for r in rows:
        head, num = r["headRefName"], int(r["number"])
        if head not in best or num > best[head][0]:
            best[head] = (num, r["state"])
    return {h: s for h, (_, s) in best.items()}


def worktree_by_branch() -> dict[str, str]:
    """branch -> the worktree path holding it. `git branch -D` refuses everything in here."""
    _, raw = sh("git", "worktree", "list", "--porcelain")
    held, path = {}, None
    for line in raw.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
        elif line.startswith("branch ") and path:
            held[line.split(" ", 1)[1].removeprefix("refs/heads/")] = path
    return held


def dirt(path: str) -> int:
    """Uncommitted paths in a worktree. NOT proof of work in progress — in this repo `store/`
    and `storage/` are tracked runtime state that pytest writes to on every run."""
    code, raw = sh("git", "-C", path, "status", "--porcelain")
    return len(raw.splitlines()) if code == 0 else -1


def classify(base_tree: str, base: str, branch: str) -> tuple[str, str]:
    """The exact test. Returns (state, resulting tree or "")."""
    code, raw = sh("git", "merge-tree", "--write-tree", base, branch)
    if code != 0:
        return CONFLICT, ""
    tree = raw.splitlines()[0].strip() if raw else ""
    return (LANDED if tree == base_tree else CARRIES), tree


def survey(base: str = "origin/main") -> tuple[list[dict], bool]:
    code, base_tree = sh("git", "rev-parse", f"{base}^{{tree}}")
    if code != 0 or not base_tree:
        raise SystemExit(f"cannot resolve {base}^{{tree}} — is the remote fetched?")

    prs = pr_state_by_branch()
    held = worktree_by_branch()
    now = time.time()
    rows = []
    for branch in sh("git", "for-each-ref", "--format=%(refname:short)",
                     "refs/heads")[1].splitlines():
        branch = branch.strip()
        if not branch or branch == "main":
            continue
        state, _ = classify(base_tree, base, branch)
        _, ts = sh("git", "log", "-1", "--format=%ct", branch)
        wt = held.get(branch, "")
        rows.append({
            "branch": branch,
            "state": state,
            "age_days": round((now - int(ts)) / 86400, 1) if ts.isdigit() else -1,
            "pr": (prs.get(branch, "none") if prs is not None else "unknown"),
            "worktree": wt,
            "dirty": dirt(wt) if wt else 0,
            "scratch": is_scratch(branch),
            "subject": sh("git", "log", "-1", "--format=%s", branch)[1][:56],
        })
    return sorted(rows, key=lambda r: (r["state"], -r["age_days"])), prs is not None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--json", action="store_true", help="machine-readable, for the console")
    args = ap.parse_args()

    rows, prs_known = survey(args.base)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    landed = [r for r in rows if r["state"] == LANDED]
    carries = [r for r in rows if r["state"] == CARRIES]
    conflict = [r for r in rows if r["state"] == CONFLICT]
    # Only a CARRYING branch can be abandoned work. A landed one is finished, and a conflicting
    # one still needs a decision whatever its PR says.
    abandoned = [r for r in carries if r["pr"] in ("none", "CLOSED")]

    print(f"{len(rows)} local branches, measured against {args.base} with "
          f"`git merge-tree --write-tree`")
    print(f"  landed   (merging changes nothing, safe to delete): {len(landed)}")
    print(f"  carries  (real change, merges cleanly):             {len(carries)}")
    print(f"  conflict (needs a human):                           {len(conflict)}")
    if not prs_known:
        print("  ! pull-request state UNKNOWN — `gh pr list` failed, so nothing below is "
              "called abandoned")

    if abandoned:
        print("\ncarries work with no open pull request:")
        for r in abandoned:
            print(f"  {r['age_days']:>5}d  {r['branch']:<48} {r['subject']}")

    if landed:
        # Never emit a line that would remove the tree this survey is running in. The command
        # would be refused for dirt anyway, but printing it invites a `--force` that deletes
        # the caller's own uncommitted work.
        _, here = sh("git", "rev-parse", "--show-toplevel")
        print("\nlanded — release the worktree FIRST, `git branch -D` refuses a held branch:")
        for r in landed:
            if r["worktree"] == here:
                print(f"  # {r['branch']}: held by THIS worktree ({here}) — delete it from "
                      f"somewhere else")
                continue
            if r["worktree"]:
                note = f"  # {r['dirty']} uncommitted" if r["dirty"] else ""
                print(f"  git worktree remove {r['worktree']}{note}")
            print(f"  git branch -D {r['branch']}")

    # Exit 1 when work carries with no proposal: the number that must trend to zero. A probe
    # that always exits 0 trains the reader to stop looking at it. Conflicting branches do not
    # trip it — they are a triage queue, not a leak.
    return 1 if abandoned else 0


if __name__ == "__main__":
    sys.exit(main())

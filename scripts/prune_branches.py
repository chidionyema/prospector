#!/usr/bin/env python3
"""Retire branches whose content is already in main, and worktrees that are gone.

Read-only by default. `--fix` is a second, explicit run.

WHY THIS IS A SCRIPT. `docs/BRANCH_CLEANUP_2026-08-09.md` did this by hand: 15 branches deleted,
the rule written down, a receipt kept. Eight days later there were 82 local branches and 71
registered worktrees again. A one-off act does not hold; a command you can run does.

THE DELETION RULE, AND WHY IT IS NOT COMMIT COUNTS.

    A branch is retired when `git merge-tree --write-tree main <branch>` produces a tree
    byte-identical to main's -- merging it would change no file.

That rule is not a preference. The 2026-08-09 cleanup measured the alternatives and both
overstate unmerged work: `ship/money-rail-ops` reported 7 commits not in main and a three-dot
diff called it "14 files, 975 insertions", yet its merged tree equalled main's exactly. Rebasing
and squash-merging both give the commits new patch-ids, so `git cherry` and `rev-list --count`
see work that has already landed. The merged TREE is the only measure that sees through it.

Nothing here names a branch. A rule that knows one branch's name dies with that branch.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

#: The branch every long-lived checkout is meant to sit on. Read from the remote, so a stale
#: local copy cannot make a merged branch look unmerged.
UPSTREAM = "origin/main"

#: Never deleted, whatever the tree says.
PROTECTED = frozenset({"main", "master"})

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Worktrees that are never removed no matter what state they are in: the shared developer
#: checkout and the checkout production runs from. Both are long-lived by design.
PROTECTED_WORKTREES = frozenset({
    "/Users/chidionyema/Documents/code/prospector",
    "/Users/chidionyema/Documents/code/prospector-live",
})


def git(*args: str, check: bool = False) -> str:
    """Run git in the repo and return stdout. Returns "" on failure unless check is set."""
    p = subprocess.run(("git", "-C", str(REPO_ROOT)) + args,
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        if check:
            raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
        return ""
    return p.stdout


def branches() -> list[tuple[str, str, str]]:
    """(name, tip sha, last commit date) for every local branch, newest last."""
    out = git("for-each-ref", "--sort=committerdate",
              "--format=%(refname:short)\t%(objectname:short)\t%(committerdate:short)",
              "refs/heads")
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def checked_out() -> dict[str, str]:
    """branch -> worktree path, for every branch a live worktree currently has checked out.

    A branch checked out somewhere cannot be deleted by git anyway, but reporting it as
    "would delete" and then failing is worse than not offering.
    """
    live: dict[str, str] = {}
    path = ""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch "):
            live[line[len("branch refs/heads/"):]] = path
    return live


def merged_tree_equals_upstream(branch: str, upstream_tree: str) -> bool:
    """True when merging `branch` into upstream would change no file.

    `merge-tree --write-tree` prints the merged tree's sha on its first line, or conflict
    information on a non-zero exit. A conflict is decisive proof of unmerged content, so a
    failure here means "keep", never "delete".
    """
    p = subprocess.run(("git", "-C", str(REPO_ROOT), "merge-tree", "--write-tree",
                        UPSTREAM, branch), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return False
    first = p.stdout.splitlines()[0].strip() if p.stdout.strip() else ""
    return bool(first) and first == upstream_tree


def worktree_is_idle(path: str) -> bool:
    """True when a worktree holds nothing that would be lost by removing it.

    This is the check that makes the script able to retire anything at all. The first report run
    found 0 retired branches and 15 "merged, but checked out at ..." -- every merged branch was
    being held alive by a worktree nobody was using. Deleting the branch is impossible while a
    worktree has it, so the worktree has to go first, and only if it is genuinely idle:

      - the directory still exists (a missing one is handled by `git worktree prune`)
      - `git status --porcelain` is empty, so no uncommitted or untracked work is in it

    Untracked counts. `store/` and `storage/` are runtime state pytest writes to, so a worktree
    that has been tested in is never silently removed.
    """
    if not Path(path).is_dir():
        return False
    p = subprocess.run(("git", "-C", path, "status", "--porcelain"),
                       capture_output=True, text=True, timeout=120)
    return p.returncode == 0 and not p.stdout.strip()


def stale_worktrees() -> list[str]:
    """Registered worktrees whose directory is no longer on disk."""
    gone, path = [], ""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.strip() == "prunable" or line.startswith("prunable "):
            gone.append(path)
    return gone


def write_receipt(retired: list[tuple[str, str, str]], upstream_sha: str) -> Path:
    """Record every tip sha, so nothing here is unrecoverable.

    Same format as the 2026-08-09 cleanup, because the restore instructions are the point: the
    objects survive in the repo, and a table of tips is all you need to bring one back.
    """
    today = dt.date.today().isoformat()
    path = REPO_ROOT / "docs" / f"BRANCH_CLEANUP_{today}.md"
    lines = [
        f"# Branch cleanup — {today}",
        "",
        "Restore any branch with: `git branch <name> <sha>` then `git push origin <name>`.",
        "Nothing here is lost: every tip SHA is recorded, and the objects survive in the repo.",
        "",
        f"Deletion rule: `git merge-tree --write-tree {UPSTREAM} <branch>` yielded a tree",
        "**byte-identical to main's** — merging it would change no file. Commit COUNTS and",
        "`git cherry` patch-ids both overstate this; rebased and squash-merged commits get new",
        "patch-ids while the content has already landed.",
        "",
        f"Written by `scripts/prune_branches.py --fix`. {UPSTREAM} at time of cleanup:",
        f"`{upstream_sha}`",
        "",
        "## Deleted — merged tree identical to main",
        "",
        "| branch | tip | last commit |",
        "|---|---|---|",
    ]
    lines += [f"| `{n}` | `{sha}` | {when} |" for n, sha, when in retired]
    lines.append("")
    path.write_text("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true",
                    help="delete the retired branches and prune stale worktrees")
    args = ap.parse_args()

    git("fetch", "origin", "main", "--quiet")
    upstream_tree = git("rev-parse", f"{UPSTREAM}^{{tree}}", check=True).strip()
    upstream_sha = git("rev-parse", UPSTREAM, check=True).strip()

    live = checked_out()
    retired: list[tuple[str, str, str]] = []
    kept: list[tuple[str, str, str, str]] = []
    release: list[str] = []  # idle worktrees standing between a merged branch and its deletion

    for name, sha, when in branches():
        if name in PROTECTED:
            continue
        if merged_tree_equals_upstream(name, upstream_tree):
            path = live.get(name)
            if path is None:
                retired.append((name, sha, when))
            elif path in PROTECTED_WORKTREES:
                kept.append((name, sha, when, f"merged, but it is the branch of {path}"))
            elif worktree_is_idle(path):
                release.append(path)
                retired.append((name, sha, when))
            else:
                kept.append((name, sha, when, f"merged, but {path} has uncommitted work"))
        else:
            files = git("diff", "--name-only", f"{UPSTREAM}...{name}").count("\n")
            kept.append((name, sha, when, f"{files} file(s) not in main"))

    gone = stale_worktrees()

    print(f"{UPSTREAM} at {upstream_sha[:12]}")
    print(f"\nRETIRED — merged tree identical to main ({len(retired)}):")
    for name, sha, when in retired:
        print(f"  {sha}  {when}  {name}")
    print(f"\nKEPT ({len(kept)}):")
    for name, sha, when, why in kept:
        print(f"  {sha}  {when}  {name}  — {why}")
    print(f"\nIDLE WORKTREES — merged branch, nothing uncommitted ({len(release)}):")
    for path in release:
        print(f"  {path}")
    print(f"\nSTALE WORKTREES — directory gone ({len(gone)}):")
    for path in gone:
        print(f"  {path}")

    if not args.fix:
        print("\nreport only. Re-run with --fix to remove the idle worktrees, delete the "
              "retired branches and prune the stale registrations.")
        return 0

    # Worktrees first: git refuses to delete a branch a worktree has checked out.
    for path in release:
        out = subprocess.run(("git", "-C", str(REPO_ROOT), "worktree", "remove", path),
                             capture_output=True, text=True, timeout=300)
        print(f"  removed worktree {path}" if out.returncode == 0
              else f"  FAILED to remove {path}: {out.stderr.strip()}")
    if retired:
        receipt = write_receipt(retired, upstream_sha)
        print(f"\nreceipt: {receipt.relative_to(REPO_ROOT)}")
        for name, _sha, _when in retired:
            p = subprocess.run(("git", "-C", str(REPO_ROOT), "branch", "-D", name),
                               capture_output=True, text=True, timeout=120)
            print(f"  deleted {name}" if p.returncode == 0
                  else f"  FAILED to delete {name}: {p.stderr.strip()}")
    if gone:
        git("worktree", "prune")
        print(f"  pruned {len(gone)} stale worktree registration(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

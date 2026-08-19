#!/usr/bin/env python3
"""Copy every dirty worktree's uncommitted state onto a remote branch, touching no working tree.

WHY THIS EXISTS. `scripts/worktree_census.py` answers "does any worktree hold commits no remote
has", and `git push <sha>:refs/heads/<name>` rescues those from the shared object store without
checking anything out. Measured 2026-08-19: that left 14 worktrees holding UNCOMMITTED changes,
one of them 888 files. A push cannot reach those, and committing another session's dirty tree is
meddling -- so the work sat on one laptop's disk with nothing watching it.

This is the missing half. It never commits on a session's behalf and never touches their branch:

    GIT_INDEX_FILE=<temp>  git read-tree HEAD     their index is not the one being written
                           git add -A             reads the working tree, writes only blobs
                           git write-tree         a tree object
    git commit-tree                               a commit whose parent is their HEAD

The other session's `.git/index`, HEAD, branch and files are all exactly as they were. What comes
out is a commit sha that can be pushed like any other, so a dirty tree becomes recoverable
without asking its owner to stop what they are doing.

SECRETS ARE EXCLUDED BY PATHSPEC, not by trusting .gitignore. A worktree pinned 113 commits back
carries the .gitignore of THAT commit: measured on wt-converge, `.env` was untracked-and-listed
there because the ignore rule for it landed on main afterwards. An exclusion that lives in the
tree being snapshotted is an exclusion the tree can be too old to have.

REPORT ONLY by default. `--push` is a second, explicit run.

USAGE
    .venv/bin/python scripts/worktree_snapshot.py            # what would be captured
    .venv/bin/python scripts/worktree_snapshot.py --push     # capture it
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Never snapshot these, whatever the worktree's own .gitignore says at its commit.
SECRETS = [".env", ".env.local", ".env.production", ".lux", "deploy/secrets.env"]

# Tracked runtime state that pytest writes to. Capturing it would make every snapshot enormous
# and say nothing about anyone's work.
RUNTIME = ["store", "storage", "graphify-out", ".popdd", ".backfill-logs", "signals"]

EXCLUDE = SECRETS + RUNTIME


def git(args: list[str], cwd: Path, env: dict | None = None, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, check=False,
                       env={**os.environ, **(env or {})})
    return p.returncode, (p.stdout or p.stderr).strip()


def branch_name(wt: Path) -> str:
    """A worktree BASENAME is not unique. Two trees called wt-converge live on this disk, one
    under a session scratchpad and one under ~/Documents/code, and pushing both produced
    `dst ref refs/heads/snapshot/2026-08-19/wt-converge receives from more than one src` --
    which failed the WHOLE push, so twelve good snapshots were lost to two colliding names.
    The session id disambiguates, and it is also the thing you want to know when you find the
    branch later."""
    session = next((part[:8] for part in wt.parts
                    if len(part) == 36 and part.count("-") == 4), "shared")
    return f"{wt.name}-{session}"


def worktrees(repo: Path) -> list[Path]:
    _, out = git(["worktree", "list", "--porcelain"], repo)
    return [Path(ln.split(" ", 1)[1]) for ln in out.splitlines() if ln.startswith("worktree ")]


def dirty_paths(wt: Path) -> list[str]:
    """Uncommitted files that are somebody's work, not runtime state and not a secret."""
    code, out = git(["status", "--porcelain"], wt)
    if code != 0:
        return []
    skip = tuple(f"{x}/" for x in EXCLUDE) + tuple(EXCLUDE)
    rows = []
    for ln in out.splitlines():
        # NEVER slice a fixed column off porcelain output. git() strips the whole payload, so the
        # FIRST line has already lost its leading status space and a [3:] slice eats a character
        # of the path -- this printed "tore/runtime.json" for store/runtime.json the first time
        # it ran, exactly as scripts/session_check.py records having done. Split instead.
        parts = ln.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        rel = parts[1].split(" -> ")[-1].strip().strip('"')
        if rel and not rel.startswith(skip):
            rows.append(rel)
    return rows


def snapshot(wt: Path) -> tuple[str, str]:
    """(commit sha, error). Writes objects; touches no index, no HEAD, no file in the worktree."""
    code, head = git(["rev-parse", "HEAD"], wt)
    if code != 0:
        return "", "no HEAD"
    if not dirty_paths(wt):
        return "", "identical to HEAD once secrets and runtime state are excluded"
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        code, err = git(["read-tree", head], wt, env)
        if code != 0:
            return "", f"read-tree: {err}"
        # Stage everything first, then take the exclusions back OUT of the temp index.
        #
        # The obvious spelling -- `git add -A -- . ':!.env' ...` -- does not work. Measured
        # 2026-08-19 on six worktrees: any explicit pathspec makes git check whether the
        # pathspec reached an ignored path and abort with "The following paths are ignored by
        # one of your .gitignore files: .lux, graphify-out". A bare `-A` never asks that
        # question. So stage bare, then unstage.
        code, err = git(["add", "-A"], wt, env)
        if code != 0:
            return "", f"add: {err}"
        # --cached is what makes this safe: it edits the (temporary) index and never the
        # working tree. Without it this would DELETE another session's files.
        for path in EXCLUDE:
            # Two different operations, and using either one for both is a bug. A path HEAD
            # already tracks (store/, signals/) must go back to its HEAD content, or the
            # snapshot records deleting it -- which made a clean worktree look like work.
            # A path HEAD does not track (.env, .lux) has to leave the index entirely.
            tracked, _ = git(["rev-parse", "--verify", "-q", f"HEAD:{path}"], wt)
            op = (["restore", "--staged", "--source=HEAD", "--", path] if tracked == 0
                  else ["rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", path])
            git(op, wt, env)
        code, tree = git(["write-tree"], wt, env)
        if code != 0:
            return "", f"write-tree: {err}"
    _, head_tree = git(["rev-parse", f"{head}^{{tree}}"], wt)
    if tree == head_tree:
        return "", "identical to HEAD once secrets and runtime state are excluded"
    msg = (f"snapshot of uncommitted work in {wt.name}\n\n"
           f"Written by scripts/worktree_snapshot.py. Nobody committed this; it is a copy taken\n"
           f"so the worktree can be discarded without losing anything. Parent is that worktree's\n"
           f"HEAD at the time, which may be well behind main.\n")
    code, sha = git(["commit-tree", tree, "-p", head, "-m", msg], wt)
    return (sha, "") if code == 0 else ("", f"commit-tree: {sha}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--push", action="store_true", help="push the snapshots (default: report only)")
    ap.add_argument("--prefix", default="", help="branch prefix, default snapshot/<today>")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    _, today = git(["log", "-1", "--format=%cs"], repo)
    prefix = args.prefix or f"snapshot/{today}"

    refspecs, rows = [], []
    for wt in worktrees(repo):
        if not wt.exists():
            continue
        files = dirty_paths(wt)
        if not files:
            continue
        sha, err = snapshot(wt)
        rows.append((wt, len(files), sha, err))
        if sha:
            refspecs.append(f"{sha}:refs/heads/{prefix}/{branch_name(wt)}")

    if not rows:
        print("No worktree holds uncommitted work. Nothing to snapshot.")
        return 0

    print(f"{'worktree':<28} {'files':>6}  snapshot")
    for wt, n, sha, err in rows:
        print(f"{wt.name[:28]:<28} {n:>6}  {sha[:12] if sha else 'SKIPPED: ' + err}")
    print()

    if not args.push:
        print(f"Report only. {len(refspecs)} snapshot commit(s) written to the object store and "
              f"NOT pushed.\nRun again with --push to put them on origin under {prefix}/.")
        return 0

    # ONE push. Thirteen pushes is thirteen round trips for one outcome.
    code, out = git(["push", "origin", *refspecs], repo, timeout=900)
    print(out)
    if code != 0:
        return 1
    print(f"\nPushed {len(refspecs)} snapshot(s) under {prefix}/. Every dirty worktree above can "
          f"now be discarded\nwithout losing work: git -C <worktree> checkout -- . && git clean -fd")
    return 0


if __name__ == "__main__":
    sys.exit(main())

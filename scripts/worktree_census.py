#!/usr/bin/env python3
"""Every worktree on this machine, and whether the work in it exists anywhere else.

THE PROBLEM CLASS: work that lives in one place with nothing watching it. The dead-branch push
guard covers one moment in that class — a push that lands on a name nobody is looking at. This
covers the other one, which nothing covered: a worktree holding commits that are on no remote at
all. If the disk goes, so do they.

Measured on 2026-08-19, before this existed: 35 worktrees, 13 of them holding commits that no
remote ref contained — 34, 27, 23, 22, 20, 13, 8, 6, 5 commits and more. None of it was visible
without asking each tree by hand.

WHY THIS DOES NOT REFRESH ANYTHING. Founder, 2026-08-19: "are worktrees auto refreshed when main
has an update?" They are not, and making them so would be the wrong fix. A worktree belongs to a
session that cannot see the others, 12 of the 35 had uncommitted changes (one with 888 files), and
rebasing a branch whose commits exist nowhere else is exactly how those commits are lost. So this
reports and refuses nothing. Report mode before fix mode.

Staleness is reported too, because it has one real cost: the POPDD gate runs `ruff` REPO-WIDE, so a
worktree on an old base fails on files it never touched. That argues for rebasing a tree when you
next use it, not on a timer.

    python3 scripts/worktree_census.py                # the table
    python3 scripts/worktree_census.py --strict       # exit 1 if any work exists only on disk
    python3 scripts/worktree_census.py --json         # for the console and for session_check
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE = "origin/main"


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=60, check=False,
    )
    return proc.returncode, proc.stdout.strip()


def worktree_paths(repo: Path) -> list[Path]:
    """Every worktree git knows about, including the main checkout."""
    code, out = _git(["worktree", "list", "--porcelain"], cwd=repo)
    if code != 0:
        return []
    return [Path(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")]


def survey(path: Path, base: str = BASE) -> dict:
    """One worktree, judged. `only_here` is the field that matters.

    A missing directory is reported rather than skipped: git still lists a worktree whose folder
    was deleted, and that is its own kind of lost work.
    """
    if not path.is_dir():
        return {"path": str(path), "branch": "", "missing": True, "dirty": 0,
                "ahead": 0, "behind": 0, "only_here": False, "remote_ref": ""}

    _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    _, sha = _git(["rev-parse", "HEAD"], cwd=path)
    _, status = _git(["status", "--porcelain"], cwd=path)
    dirty = len([ln for ln in status.splitlines() if ln.strip()])

    ahead = behind = 0
    code, counts = _git(["rev-list", "--left-right", "--count", f"{base}...HEAD"], cwd=path)
    if code == 0 and counts:
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])

    # "On a remote" is containment, not a branch name. A branch renamed locally, or a detached
    # HEAD, still counts as safe when some remote ref contains the commit.
    remote_ref = ""
    if ahead > 0 and sha:
        code, refs = _git(["branch", "-r", "--contains", sha], cwd=path)
        if code == 0:
            first = [ln.strip() for ln in refs.splitlines() if ln.strip() and "->" not in ln]
            remote_ref = first[0] if first else ""

    return {
        "path": str(path), "branch": branch, "missing": False, "dirty": dirty,
        "ahead": ahead, "behind": behind, "remote_ref": remote_ref,
        "only_here": ahead > 0 and not remote_ref,
    }


def census(repo: Path, base: str = BASE) -> list[dict]:
    """Riskiest first: work that exists only here, then dirty trees, then the stale ones."""
    rows = [survey(p, base) for p in worktree_paths(repo)]
    rows.sort(key=lambda r: (not r["only_here"], -r["dirty"], -r["behind"]))
    return rows


def render(rows: list[dict]) -> str:
    lost = [r for r in rows if r["only_here"]]
    dirty = [r for r in rows if r["dirty"]]
    lines = [
        f"{len(rows)} worktrees. {len(lost)} hold commits that exist on NO remote. "
        f"{len(dirty)} have uncommitted changes.",
        "",
        f"{'worktree':<32} {'branch':<34} {'dirty':>5} {'ahead':>6} {'behind':>7}  where else",
    ]
    for r in rows:
        if r["missing"]:
            lines.append(f"{Path(r['path']).name:<32} {'(folder is gone)':<34}")
            continue
        where = "ONLY HERE" if r["only_here"] else (r["remote_ref"] or "-")
        lines.append(
            f"{Path(r['path']).name:<32} {r['branch'][:34]:<34} {r['dirty']:>5} "
            f"{r['ahead']:>6} {r['behind']:>7}  {where}"
        )
    if lost:
        lines += ["", "Work that exists only on this disk. Push it, or decide it is dead:"]
        for r in lost:
            lines.append(f"    git -C {r['path']} push -u origin HEAD:<a-fresh-name>   # {r['ahead']} commits")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="any path inside the repository")
    ap.add_argument("--base", default=BASE, help=f"the ref staleness is measured against ({BASE})")
    ap.add_argument("--json", action="store_true", help="machine-readable, for the console")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a worktree holds commits no remote has")
    args = ap.parse_args(argv)

    rows = census(Path(args.repo).resolve(), args.base)
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    # Report mode is the default and exits 0 even when it finds something. A probe that fails the
    # build by existing gets deleted rather than fixed.
    return 1 if args.strict and any(r["only_here"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())

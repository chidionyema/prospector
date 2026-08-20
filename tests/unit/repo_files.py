"""One way for a test to ask what files this repo has: git, not a directory walk.

`Path.rglob` cannot prune. It descends into every directory and yields every match, and a
filter on its OUTPUT runs after the walk has already paid for them. In this checkout the walk
crosses `store_platform/**/node_modules` (78,359 entries), `store/` (3,202) and, on the
founder's laptop, an in-tree `.venv` (10,783 `*.py` alone).

Measured 2026-08-20 in a CI-shaped worktree: `ROOT.rglob("*.py")` takes 2.53s and yields 786
paths; `git ls-files` takes 0.04s and yields 1,981. Same answer, 60x cheaper. Measured
2026-08-17 in `test_dotenv_fence.py`, whose docstring is the origin of this module: its one
walking test was the slowest in the whole suite at 116s, against 542s for all 4,180 tests.

That fix was applied to that one file and the other twenty-three call sites kept walking. This
module is the fix in a place they can all reach, and `test_no_test_walks_the_repo_by_hand.py`
is what stops the twenty-fourth being written.

`--cached --others --exclude-standard` is tracked files plus untracked ones git would not
ignore, so a source file is graded the moment it is written, and everything a skip list used to
remove is already gitignored.
"""
from __future__ import annotations

import fnmatch
import subprocess
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Only used when git cannot answer (a tarball, a stripped container). Kept in sync with nothing:
# a walk is the fallback, and being a little wrong there costs a slow test, not a wrong verdict.
_WALK_SKIP = (".venv", "node_modules", ".claude/worktrees", ".git", "store", "storage",
              "graphify-out", ".next", "dist", "build", "__pycache__", "bin", "obj")


@lru_cache(maxsize=None)
def repo_files(pattern: str = "*") -> tuple[Path, ...]:
    """Every file in this repo matching `pattern`, as absolute paths, sorted.

    `pattern` is a git pathspec glob, matched against the whole path the way `git ls-files`
    matches it: "*.py" reaches every depth, and so does "actions.runner.*".

    Cached for the life of the process. An xdist worker runs hundreds of test files and asks
    this the same question in each of them; git is asked once.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", pattern],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
        paths = sorted(REPO / rel for rel in out.split("\0") if rel)
        if paths:
            return tuple(paths)
    except (OSError, subprocess.SubprocessError):
        pass
    return tuple(sorted(_walk(pattern)))


def repo_python_files() -> tuple[Path, ...]:
    """The Python sources this repo owns."""
    return repo_files("*.py")


def _walk(pattern: str) -> list[Path]:
    """The fallback. Accept the cost; there is no git to ask."""
    walked = []
    for p in REPO.rglob(pattern):
        rel = p.relative_to(REPO).as_posix()
        if any(rel.startswith(s) or f"/{s}/" in f"/{rel}" for s in _WALK_SKIP):
            continue
        if p.is_file():
            walked.append(p)
    return walked


def repo_files_named(name_glob: str) -> tuple[Path, ...]:
    """Every repo file whose BASENAME matches `name_glob`, sorted.

    This is what `rglob("actions.runner.*")` means and what a git pathspec does not: git
    matches the glob against the whole path, so `actions.runner.*` matches only at the repo
    root, while rglob matches the name at any depth. Filtering the cached full listing here
    keeps rglob's meaning and still asks git exactly once.
    """
    return tuple(p for p in repo_files() if fnmatch.fnmatch(p.name, name_glob))

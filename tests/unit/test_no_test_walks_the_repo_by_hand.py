"""Nothing in this repo may walk the whole tree from its root. Ask git instead.

THE COST, measured. `Path.rglob` cannot prune: it descends every directory and the filter runs
on its OUTPUT, after the walk has already been paid for. This checkout holds 78,359 entries
under `store_platform/**/node_modules` alone, plus `store/`, `graphify-out/`, and on the
founder's laptop an in-tree `.venv`. Measured 2026-08-17, one walking test was the slowest in
the whole suite at 116s against 542s for all 4,180 tests. Measured 2026-08-20 in a CI-shaped
worktree, `git ls-files` answers the same question 60x faster.

WHY THIS TEST EXISTS AND NOT JUST A DOCSTRING. The fix was found on 2026-08-17 and written into
`test_dotenv_fence.py`, where it stayed. Three other files kept walking for three more days and
cost the python job about 12s a run, because a trap that is documented in one file is not
guarded anywhere. This is the mechanism, so the next one fails instead of merging.

WHAT IS AND IS NOT AN OFFENCE. Walking a SUBDIRECTORY is fine and stays allowed: `prospector/`
and `tests/` are small and hold no vendored state. The offence is walking from the repo ROOT,
which is detected structurally -- `Path(__file__).resolve().parents[n]` denotes the root
exactly when `n` equals the file's own depth below it -- rather than by matching the text
`parents[2]`, which would miss the same walk written from a different depth.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_files import REPO, repo_files  # noqa: E402

# What actually descends the whole tree. `rglob` and `walk` always do. `glob` does only when its
# pattern contains `**`: `ROOT.glob("store/ops/restore_drill*")` reads one directory and is not
# this defect. `iterdir()` is a single level and is not either -- it is not listed at all.
#
# That distinction was not guessed. The first version of this test listed `glob` and `iterdir`
# unconditionally and immediately failed on `scripts/ops_status.py:199`, which is correct code.
ALWAYS_RECURSIVE = {"rglob", "walk"}

# The one place a root walk is correct: the fallback inside the helper that exists to replace
# every other one. It runs only when git cannot answer at all (a tarball, a stripped container).
ALLOWED = {"tests/unit/repo_files.py"}


def _root_bound_names(tree: ast.Module, depth: int) -> set[str]:
    """Module-level names bound to the REPO ROOT itself, not to a subdirectory of it."""
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        # `parents[n] / "sub"` is scoped, so it is not a root binding.
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div):
            continue
        src = ast.unparse(value)
        if "__file__" not in src or "parents[" not in src:
            continue
        index = src.split("parents[")[1].split("]")[0]
        if index.isdigit() and int(index) == depth:
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _offences(source: str, depth: int) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    roots = _root_bound_names(tree, depth)
    if not roots:
        return []
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in roots):
            continue
        if node.func.attr in ALWAYS_RECURSIVE:
            found.append((node.lineno, ast.unparse(node)[:80]))
        elif node.func.attr == "glob" and _pattern_is_recursive(node):
            found.append((node.lineno, ast.unparse(node)[:80]))
    return found


def _pattern_is_recursive(call: ast.Call) -> bool:
    """`glob("**/x")` descends the whole tree; `glob("store/ops/x*")` reads one directory.

    A non-literal pattern is treated as recursive: it cannot be read here, and a guard that
    waves through what it cannot see is the fail-open shape this estate keeps paying for.
    """
    if not call.args:
        return False
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return "**" in first.value
    return True


def test_the_detector_catches_a_root_walk_written_any_way():
    """Anti-vacuity, and the reason this is not a regex.

    A guard that finds nothing passes whether it works or not, and the last AST guard this
    estate wrote was pinned to one expression and let twenty offenders through. So the
    detector is run here against source it MUST flag and source it must NOT.
    """
    caught = 'R = Path(__file__).resolve().parents[2]\nx = R.rglob("*.py")\n'
    assert _offences(caught, depth=2), "the detector no longer catches a plain root walk"

    # The same walk written from a different depth. A text match on `parents[2]` would miss it.
    deeper = 'R = Path(__file__).resolve().parents[4]\nx = R.rglob("*.py")\n'
    assert _offences(deeper, depth=4), "the detector is pinned to one depth"

    # `walk` is the same offence spelled differently.
    walked = 'R = Path(__file__).resolve().parents[2]\nx = R.walk()\n'
    assert _offences(walked, depth=2), "the detector only understands rglob"

    # So is a recursive glob, including one whose pattern cannot be read here.
    starstar = 'R = Path(__file__).resolve().parents[2]\nx = R.glob("**/*.py")\n'
    assert _offences(starstar, depth=2), "a `**` glob descends the whole tree too"
    computed = 'R = Path(__file__).resolve().parents[2]\nx = R.glob(pattern)\n'
    assert _offences(computed, depth=2), "an unreadable pattern must not be waved through"

    for allowed, why in [
        ('R = Path(__file__).resolve().parents[2] / "prospector"\nx = R.rglob("*.py")\n',
         "walking a subdirectory is cheap and stays legal"),
        ('R = Path(__file__).resolve().parents[1]\nx = R.rglob("*.py")\n',
         "parents[1] from a depth-2 file is a subdirectory, not the root"),
        ('R = Path(__file__).resolve().parents[2]\nx = R.glob("store/ops/drill*")\n',
         "a glob with a literal prefix reads one directory; scripts/ops_status.py does this"),
        ('R = Path(__file__).resolve().parents[2]\nx = R.iterdir()\n',
         "iterdir is a single level, not a walk"),
    ]:
        assert not _offences(allowed, depth=2), why


def test_nothing_walks_the_repo_from_its_root():
    offenders = []
    for path in repo_files("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            hits = _offences(source, depth=len(Path(rel).parts) - 1)
        except SyntaxError:
            continue  # a fixture of deliberately broken source is not a root walk
        offenders += [f"{rel}:{line}  {src}" for line, src in hits]

    assert not offenders, (
        "These walk the whole repo from its root. The walk cannot prune, so it pays for "
        "node_modules, store/ and .venv before the filter rejects them. Use "
        "`tests/unit/repo_files.py` (repo_files / repo_python_files / repo_files_named), "
        "which asks git and is 60x faster for the same answer:\n  " + "\n  ".join(offenders))


def test_there_are_sources_to_grade():
    """The scan above is vacuous if the file list collapses."""
    assert len(repo_files("*.py")) > 500, "the source list collapsed; the scan is now vacuous"

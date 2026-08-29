"""A source file git ignores is a file CI never compiles and never runs.

Written 2026-08-19. `store_platform/src/Store.Tests/Build/BuildFileTests.cs` was written,
reviewed and left on disk for an hour before anyone noticed `git status` did not list it.
`.gitignore:9` says `build/`, git is configured `core.ignorecase=true` on this Mac, and so a
directory called `Build/` full of C# was invisible. The tests inside it would have gone to a
review that could not see them and to a CI run that could not compile them.

That is the same defect class as a module nothing imports, only quieter: nothing is red, the
work is simply absent. The fix was to name the directory `BuildFiles/`. The guard is here.

Measured when written: zero source files across the whole tree were ignored, so this went in
green rather than with an allow-list. If it ever fails, the answer is almost always to rename
the directory, not to widen the exclusions below.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Extensions that are compiled or executed by some gate in this repo.
SOURCE_SUFFIXES = {".py", ".cs", ".ts", ".tsx"}

#: Directories that hold build output, vendored packages or a virtualenv. Everything under
#: these is SUPPOSED to be ignored, and none of it is ours to compile.
GENERATED_DIRS = {
    "node_modules", "bin", "obj", ".next", ".venv", "venv",
    "dist", "out", "coverage", "graphify-out", "__pycache__",
}


def _ignored_source_files() -> list[str]:
    """Every file git is ignoring that looks like source we wrote."""
    proc = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr[:400]

    out = []
    for line in proc.stdout.splitlines():
        path = Path(line)
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        if GENERATED_DIRS.intersection(path.parts):
            continue
        out.append(line)
    return sorted(out)


def test_git_ignores_no_source_file_we_wrote():
    ignored = _ignored_source_files()
    assert not ignored, (
        "git is ignoring source files, so no reviewer and no CI job can see them:\n  "
        + "\n  ".join(ignored[:20])
        + "\nRename the directory rather than widening GENERATED_DIRS in this test."
    )


def test_the_guard_can_actually_see_an_ignored_file(tmp_path):
    """The check above passes on an empty list too, so prove the list is not always empty.

    A guard that iterates nothing reports green forever. This one plants a `.cs` file inside a
    directory `.gitignore` matches and asserts it is found, which is exactly the situation that
    went unnoticed.
    """
    proc = subprocess.run(["git", "check-ignore", "-q", "build/"],
                          cwd=ROOT, capture_output=True, timeout=30, check=False)
    if proc.returncode != 0:
        pytest.skip("`build/` is no longer in .gitignore; the original trap is gone")

    planted = ROOT / "build" / "PlantedByTest.cs"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("// planted by test_no_source_file_is_gitignored\n", encoding="utf-8")
    try:
        assert "build/PlantedByTest.cs" in _ignored_source_files()
    finally:
        planted.unlink()
        try:
            planted.parent.rmdir()
        except OSError:
            pass          # the directory pre-existed; leave it alone

"""No module may name the store with a path relative to the process working directory.

WHY THIS EXISTS. `tests/unit/test_no_store_path_is_derived_from_file.py` closed one syntax:
a store path built from `__file__`, so it follows the CODE. This closes the other one:

    paths = glob.glob("store/dossiers/*.json")

That is relative to whatever directory the process was launched from. `deploy/engine/Dockerfile`
sets `WORKDIR /app` (:55) and copies the repo there (:68), so under the engine that name resolves
to `/app/store` — a directory inside the image layer, which every deploy replaces. The state is on
the mounted volume the whole time, and the reader sees an empty directory and reports zero.

WHY IT IS A SEPARATE FILE. The two are different failures with different fixes and different
correct exceptions, and merging them would make one allow-list excuse both. `INC-2026-08-18` swept
for siblings with a regex, found two of forty, and wrote down the class: a sweep can only find the
instances that share the syntax of the one that was noticed. The `__file__` guard then repeated it
one level up — it walks the AST, but only for the `ROOT / "store"` shape it had seen. Neither
guard could see the working-directory form, so eleven of them were on disk with both green.

WHAT IT LOOKS AT. A string literal whose FIRST path segment is `store` or `storage`, passed as the
first argument to a call that turns a string into a filesystem path. That narrowness is the point:
`tmp_path / "store"` is correct and common, `parts[0] == "store"` is a comparison, and a guard that
flagged either would need an allow-list long enough to hide a real one.
"""
from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".venv", "node_modules", "store", "storage", ".git", "graphify-out",
             "__pycache__", ".pytest_cache", "scratchpad"}
SEGMENTS = {"store", "storage"}

#: Calls whose first positional argument is a path. Bare names only — an ATTRIBUTE call such as
#: `ROOT.glob("store/...")` is not working-directory relative, it is relative to `ROOT`, and that
#: shape belongs to the `__file__` guard instead.
PATH_BUILTINS = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "open"}

#: Module-level functions that take a path first. Written dotted so a method of the same name on
#: some object (`obj.join`, `obj.walk`) cannot be mistaken for one of these.
PATH_FUNCTIONS = {
    "glob.glob", "glob.iglob",
    "os.path.join", "os.path.exists", "os.path.isdir", "os.path.isfile", "os.path.abspath",
    "os.listdir", "os.makedirs", "os.mkdir", "os.remove", "os.unlink", "os.walk", "os.scandir",
    "os.stat", "os.chdir",
    "shutil.rmtree", "shutil.copy", "shutil.copy2", "shutil.copytree", "shutil.move",
}

# path -> why naming the store relative to the working directory is correct here.
ALLOWED = {
    "tests/unit/test_adaptive_persona.py":
        "A dummy attribute on a mock store object. Nothing opens it, globs it or writes to it; "
        "the test never touches a filesystem at all, so there is no directory to get wrong.",
}


def _dotted(node: ast.AST) -> str | None:
    """`os.path.join` for the attribute chain, or None if it is not a plain dotted name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _names_the_store(value: object) -> bool:
    """True for a relative path string whose first segment is `store` or `storage`.

    Whitespace disqualifies it: prose that happens to start with the word is not a path, and
    `store_platform/...` is a different first segment, so the segment test excludes it without
    needing an exception.
    """
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return False
    pure = PurePosixPath(value)
    return not pure.is_absolute() and bool(pure.parts) and pure.parts[0] in SEGMENTS


def _offenders(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        named = (isinstance(func, ast.Name) and func.id in PATH_BUILTINS) or \
                (_dotted(func) in PATH_FUNCTIONS)
        if not named:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and _names_the_store(first.value):
            hits.append((node.lineno, ast.unparse(node)[:120]))
    return hits


def _sources() -> list[Path]:
    return [p for p in sorted(REPO.rglob("*.py"))
            if not any(part in SKIP_DIRS for part in p.relative_to(REPO).parts)]


def test_there_are_sources_to_grade():
    """Anti-vacuity. A walk that finds no files passes every assertion below."""
    assert len(_sources()) > 500, "the source walk collapsed; every check below is now vacuous"


def test_no_store_path_is_relative_to_the_working_directory():
    bad = []
    for p in _sources():
        rel = p.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        for line, src in _offenders(p):
            bad.append(f"{rel}:{line}  {src}")
    assert not bad, (
        "These name the store relative to the process working directory, so they read the "
        "directory the shell happened to be in. Under the engine that is /app/store, which every "
        "deploy erases. Use prospector.config.store_root(). If one is genuinely correct, add it "
        "to ALLOWED with the reason:\n  " + "\n  ".join(bad))


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_every_allowed_file_exists_and_still_needs_its_exemption(rel: str):
    """An allow-list that outlives its entries stops being a decision and becomes debris."""
    p = REPO / rel
    assert p.exists(), f"{rel} is on the allow-list and does not exist"
    assert _offenders(p), (
        f"{rel} no longer names a working-directory store path. Remove it from ALLOWED, or the "
        f"next one written in that file is exempt.")


def test_every_exemption_carries_a_reason():
    for rel, why in ALLOWED.items():
        assert len(why) > 40, f"{rel} is exempt for a reason too short to be one: {why!r}"


@pytest.mark.parametrize("src", [
    'from pathlib import Path\nD = Path("store/dossiers")\n',
    'import glob\nps = glob.glob("store/dossiers/*.json")\n',
    'import os\np = os.path.join("store", "dossiers")\n',
    'f = open("store/prospector.jsonl")\n',
    'import shutil\nshutil.rmtree("storage/tmp")\n',
])
def test_the_shapes_this_is_supposed_to_catch(tmp_path: Path, src: str):
    """Each of these was on disk on 2026-08-19 with both store guards green."""
    p = tmp_path / "x.py"
    p.write_text(src)
    assert _offenders(p), f"missed a working-directory store path:\n{src}"


@pytest.mark.parametrize("src", [
    'D = tmp_path / "store" / "dossiers"',                      # the normal correct form
    'if p.parts[0] == "store": pass',                           # a comparison, not a path
    'IGNORES = ["store/", "storage/"]',                         # a pattern list
    'D = Path("store_platform/src/Store.Web")',                 # a different first segment
    'D = ROOT.glob("store/ops/*")',                             # relative to ROOT, not the cwd
    'D = Path("/data/store/dossiers")',                         # already absolute
    'note = "store the receipt next to the pack"',              # prose
])
def test_the_shapes_this_must_not_flag(tmp_path: Path, src: str):
    """A guard that fires on the correct form gets an allow-list long enough to hide a real one."""
    p = tmp_path / "y.py"
    p.write_text(src + "\n")
    assert not _offenders(p), f"false positive on:\n{src}"

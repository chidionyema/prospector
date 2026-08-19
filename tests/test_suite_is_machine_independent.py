"""The suite must give the same answer on every machine.

This exists because on 2026-07-31 CI failed four times in a row, on four separate pushes, for
what turned out to be one root cause wearing four faces: the repo's idea of "true" had become
entangled with the state of one laptop.

    assert 0 >= 300              tests asserting on store/dossiers/, which is gitignored
                                 (.gitignore:43) — 1153 files here, 0 in any clone
    FileNotFoundError            a hardcoded ".venv/bin/python", relative to whatever cwd
                                 pytest was launched from, absent in CI entirely
    ModuleNotFoundError          stripe / ddgs / exa_py imported lazily inside functions,
                                 installed on the dev machine, declared nowhere
    10 x CA1873, 0 locally       AnalysisLevel=latest-recommended, so the rule set came from
                                 whichever .NET SDK the machine happened to have

Each was fixed individually. Fixing them individually is the maintenance overhead — the same
class of fault comes back with the next test anyone writes, and it comes back as a red CI run
on someone else's push. These checks make the class of fault fail HERE, on the machine that
introduced it, with a message that names the actual problem.

They are deliberately about the test suite itself, not about product code.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = sorted(p for p in (REPO_ROOT / "tests").rglob("test_*.py"))

# Data the repo deliberately does not ship. A test that reads any of these is asserting on
# whoever's laptop it runs on. See .gitignore:43.
UNSHIPPED = ("store/dossiers", "store/prospector.jsonl", "store/listings")

# The token alone is not the fault; OPENING it is. A test may pass "store/prospector.jsonl" to a
# function that only classifies the string -- `doc_lint._resolve` decides whether a doc's path
# reference is valid, `live_checkout._code_changes` decides whether a porcelain line is code --
# and neither one touches the disk. Flagging those taught nothing and cost two red CI runs on
# 2026-08-17. So the line must ALSO perform a filesystem operation.
#
# This is not a hole. A test that assigns the path on one line and opens it on the next was never
# caught by the substring check either, because the `open(p)` line carries no token. The rule is
# the same width it always was, minus the false positives.
_READS_DISK = re.compile(
    r"\b(open|read_text|read_bytes|readlines|Path|glob|rglob|iterdir|listdir|scandir|walk"
    r"|exists|is_file|is_dir|stat|load|loads|read_csv|connect)\s*\("
)


def _relevant(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Line numbers occupied by docstrings.

    A docstring that describes a test ("drops a local store/listings receipt") is prose about
    the behaviour, not a path the test opens. Flagging it would train people to reword
    documentation to appease a checker, which is the opposite of the point. `#` comments are
    stripped separately at the call site.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def test_no_test_reads_the_operators_own_store():
    """A test may CREATE a store under tmp_path; it may not read the real one.

    tmp_path is how you test store-reading behaviour portably — build the store the test
    needs, then assert on it. Reading store/dossiers/ instead tests the machine.
    """
    offenders: list[str] = []
    for path in TEST_FILES:
        if path.name == Path(__file__).name:
            continue
        source = path.read_text(encoding="utf-8")
        prose = _docstring_lines(ast.parse(source, filename=str(path)))
        for lineno, line in enumerate(source.splitlines(), 1):
            if lineno in prose:
                continue
            code = line.split("#")[0]
            if not any(u in code for u in UNSHIPPED) or "tmp_path" in code:
                continue
            if not _READS_DISK.search(code):
                continue
            offenders.append(f"{_relevant(path)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "These read data that is gitignored, so they assert on one machine's state and fail "
        "on every clone:\n  " + "\n  ".join(offenders)
        + "\n\nBuild the data the test needs under tmp_path. If the check is genuinely about "
          "the operator's real store, it belongs in scripts/store_audit.py, which is run "
          "where that store exists."
    )


def test_no_test_hardcodes_an_interpreter_path():
    """`.venv/bin/python` is not the interpreter running the suite in CI, or anywhere the
    venv is named differently, or when pytest is launched from another directory. The
    interpreter that is always right is sys.executable."""
    offenders: list[str] = []
    pattern = re.compile(r"""['"][^'"]*(?:\.venv|venv)/bin/python""")
    for path in TEST_FILES:
        if path.name == Path(__file__).name:
            continue
        source = path.read_text(encoding="utf-8")
        # Skip docstrings, for the reason `_docstring_lines` already gives: prose that QUOTES a
        # bad interpreter path is documentation of the bug, not the bug. Four files whose whole
        # subject was the `/app/...` failure tripped this guard on 2026-08-18. The receipt for a
        # string defect is the string, so the guard reads code and leaves prose alone.
        prose = _docstring_lines(ast.parse(source, filename=str(path)))
        for lineno, line in enumerate(source.splitlines(), 1):
            if lineno in prose:
                continue
            if pattern.search(line.split("#")[0]):
                offenders.append(f"{_relevant(path)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Hardcoded interpreter paths — use sys.executable, which is this interpreter on "
        "every machine including CI:\n  " + "\n  ".join(offenders)
    )


def _declared_requirements() -> set[str]:
    names: set[str] = set()
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!\[; ]", line, 1)[0].strip().lower()
        if name:
            names.add(name.replace("-", "_"))
    return names


# Distribution name != import name. Only the cases this repo actually has.
IMPORT_TO_DISTRIBUTION = {
    "yaml": "pyyaml",
    "google": "google_genai",
    "dotenv": "python_dotenv",
    "pythonjsonlogger": "python_json_logger",
    "exa_py": "exa_py",
    "fpdf": "fpdf2",
}

# Imported by modules that requirements.txt deliberately excludes — see its closing note on
# the LUX packages, which were pinned to absolute file:/// paths and made the file
# uninstallable anywhere else. Nothing under prospector/ imports them.
KNOWN_OPTIONAL = {"lux_popdd", "lux_spec", "lux_spec_cli", "streamlit_autorefresh"}

# Installed by a package requirements.txt DOES declare, so it cannot be absent while its
# parent is present. `pip show boto3` -> "Requires: botocore, jmespath, s3transfer".
# Deliberately a short explicit list, not "anything pip can see": the whole failure this
# guards against is treating whatever happens to be installed as though it were declared.
KNOWN_TRANSITIVE = {"botocore": "boto3", "jmespath": "boto3", "s3transfer": "boto3"}


def _third_party_imports(tree: ast.AST) -> set[str]:
    """Every module imported ANYWHERE in the file, including inside functions — except those
    imported inside a try/except, which have declared a fallback.

    Walking the whole tree, not just module level, is the entire point: `stripe` was imported
    inside the function that prices a pack (prospector/bridge.py:911), so nothing failed at
    boot and the process died at the first attempt to take money. A lazy import hides an
    undeclared dependency until the feature is first used, which for the money rail is the
    worst possible moment to find out.

    A try/except-guarded import is a different thing and is allowed: the author has written
    what happens when it is absent, so absence is a designed state rather than a crash.
    prospector/retrieval.py:52 imports nltk that way and falls back to no stemming.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(inner))

    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize(
    "source", sorted((REPO_ROOT / "prospector").rglob("*.py")),
    ids=lambda p: str(p.relative_to(REPO_ROOT / "prospector")),
)
def test_every_import_in_the_engine_is_declared(source):
    """Every third-party module prospector/ imports must be in requirements.txt."""
    import sys
    stdlib = sys.stdlib_module_names
    declared = _declared_requirements()

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    undeclared = []
    for module in sorted(_third_party_imports(tree)):
        if module in stdlib or module == "prospector" or module.startswith("_"):
            continue
        key = IMPORT_TO_DISTRIBUTION.get(module, module).lower().replace("-", "_")
        if key in KNOWN_OPTIONAL or key in declared:
            continue
        parent = KNOWN_TRANSITIVE.get(key)
        if parent and parent in declared:
            continue
        # Local modules of this repo, imported without the package prefix.
        if (REPO_ROOT / f"{module}.py").exists() or (REPO_ROOT / module).is_dir():
            continue
        undeclared.append(module)

    assert not undeclared, (
        f"{_relevant(source)} imports {undeclared} but requirements.txt does not declare "
        f"them. On this machine they are installed; on a clean install the process starts "
        f"fine and dies at the first call that reaches them."
    )


# --------------------------------------------------------------------------- #
# Added 2026-08-19, after CI went red on two guards that were green here.
#
# The console tool catalogue gained its first row outside this checkout — the Hermes self-check
# at `~/.hermes/scripts/hermes_selfcheck.py`. Two guards asserted every catalogued tool is on
# disk. That file is on the laptop and is not on a runner, so the suite passed here and failed
# there, on a push that had not touched either guard.
#
# The individual fix was to scope both guards to what the repo ships. THIS is the mechanism, and
# the difference matters: scoping fixes the two guards we know about, and the same fault returns
# with the next test anyone writes against the catalogue. A scrubbed HOME reproduces a runner on
# the machine that introduced the fault, which is what this file is for.
# --------------------------------------------------------------------------- #
def test_the_console_tool_catalogue_does_not_change_answer_with_HOME(monkeypatch, tmp_path):
    """Every row the repo SHIPS must exist whoever's HOME is set, and rows it does not ship must
    move with HOME rather than being silently hung off the repo root.

    The second half is the bug underneath the red CI run: `root / "~/.hermes/..."` yields
    `<repo>/~/.hermes/...`, a path that exists nowhere, so the console reported the tool missing
    and refused to run it. That one is invisible to a guard that only counts what exists.
    """
    from prospector.ops import console_api as api

    root = api._repo_root()
    monkeypatch.setenv("HOME", str(tmp_path))

    for tool in api.TOOLS:
        resolved = api._tool_on_disk(root, tool["path"])
        if str(resolved).startswith(str(root)):
            assert resolved.exists(), (
                f"{tool['id']} names {tool['path']}, which this repo ships, and it is not here"
            )
        else:
            assert resolved.is_absolute() and "~" not in str(resolved), (
                f"{tool['id']}: {tool['path']} resolved to {resolved} — an out-of-repo tool "
                "must expand against HOME, never join to the repo root"
            )
            assert str(resolved).startswith(str(tmp_path)), (
                f"{tool['id']} resolved to {resolved}, which ignored HOME — so whether this "
                "button works depends on which machine reads the catalogue"
            )

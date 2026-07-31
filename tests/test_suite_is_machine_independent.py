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
            if any(u in code for u in UNSHIPPED) and "tmp_path" not in code:
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
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
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

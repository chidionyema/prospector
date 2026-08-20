"""No module may work out where the store is from where its own source file sits.

WHY THIS EXISTS. Production moved off this checkout on 2026-08-17 onto a dedicated one pinned to
`origin/main`, with `PROSPECTOR_STORE_DIR` set so the state would stay put. Four constants moved
with the CODE anyway, because each was derived from `__file__`, and live state was split across
two directories for twenty minutes: the ledger in one, the dead-provider marks in the other.

`INC-2026-08-18-store-resolver` recorded that and swept for siblings with
`rg -n 'def store_root|Path\\(__file__\\).*store'`. It found two. This file found forty, because
that regex only matches the ONE-LINE form, and almost every real offender is written in two steps:

    ROOT = Path(__file__).resolve().parents[1]
    ...
    DOSSIERS = ROOT / "store" / "dossiers"

A regex over one line cannot see a name bound on another. That is why the count was wrong, and it
is why this check is an AST walk instead: it tracks the names, so it sees both forms and any
future third one.

The allow-list below is the whole exception surface, and every entry carries the reason it is
allowed. Adding to it is a decision; arriving on it by accident is not possible.
"""
from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

import pytest
from repo_files import REPO, repo_python_files  # noqa: E402

SKIP_DIRS = {".venv", "node_modules", "store", "storage", ".git", "graphify-out",
             "__pycache__", ".pytest_cache", "scratchpad"}
SEGMENTS = {"store", "storage"}

# path -> why deriving this one from __file__ is correct.
ALLOWED = {
    "prospector/config.py":
        "This IS the resolver. Its fallback is the definition of 'no PROSPECTOR_STORE_DIR set'.",
    "scripts/incident.py":
        "A shim used when the prospector package cannot be imported, which is exactly when the "
        "incident tool is most needed. It resolves the env var first, identically.",
    "scripts/store_migrate.py":
        "The migration tool imports nothing from prospector on purpose: it has to run when the "
        "package is broken or half-moved. Env first, same order as the engine.",
    "scripts/restore_drill.py":
        "A safety guard, not a store path. It refuses to write into the configured store AND the "
        "repo-local one, so naming both is the point.",
    "prospector/pipeline/middleware.py":
        "storage/durable_ledger.md is a tracked repo artifact, not runtime state. It belongs to "
        "the checkout and must move with the code.",
    "tests/unit/test_ledger_fence.py":
        "Grades the repo ledger above, so it must resolve it the same way.",
    "tests/unit/test_paths.py":
        "Asserts the fallback behaviour itself. It has to name the fallback to test it.",
    "tests/unit/test_market_threading.py":
        "Copies the developer's own catalogue as an optional fixture and skips when absent. It "
        "wants THIS checkout's store, not production's.",
    "tests/integration/test_golden_promotion_cli.py":
        "A fence asserting the repo store is left untouched by a --store-dir run. It names the "
        "repo store in order to prove nothing was written there.",
    "run_v2.py":
        "storage/durable_ledger.md again: a tracked repo artifact, not runtime state, so it "
        "belongs to the checkout and must move with the code. Same reason as middleware.py above.",
    "tests/invariants/test_audit_isolation.py":
        "A fence proving the suite left THIS checkout's audit trail alone. store_root() under "
        "pytest points at a temp directory, so resolving it that way would prove nothing.",
    "tests/ops/cc/test_ephemeral_jobs.py":
        "The same kind of fence, on the repo-local control-centre jobs file: the assertion is "
        "that launching a job in a temp dir did not write the checkout's production copy.",
}


def _is_dunder_file(node: ast.AST) -> bool:
    """`__file__`, and also `some_module.__file__`.

    The attribute form is not a curiosity: `tests/invariants/test_audit_isolation.py:22` is
    `Path(A.__file__).resolve().parent.parent`, and reading only the bare name left that file
    unseen by this check for as long as it has existed.
    """
    return ((isinstance(node, ast.Name) and node.id == "__file__")
            or (isinstance(node, ast.Attribute) and node.attr == "__file__"))


def _file_derived_names(tree: ast.Module) -> set[str]:
    """Module-level names bound to any expression that mentions __file__."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            _is_dunder_file(n) for n in ast.walk(node.value)
        ):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _parameter_names(tree: ast.Module) -> set[str]:
    """Every name bound as a function parameter anywhere in the file.

    A parameter is bound by the CALLER, so a module-level name that happens to match it says
    nothing about what it holds. Without this, one `root = Path(__file__)...` inside any function
    made the name `root` file-derived for the whole file, and
    `tests/unit/test_console_tools_run.py:359` — `def _tree(root: Path)`, always called with
    `tmp_path` — was reported as an offender. A guard that fires on correct code earns an
    allow-list long enough to hide a real one.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            out.update(arg.arg for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs])
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
    return out


def _mentions(node: ast.AST, names: set[str]) -> bool:
    return any(_is_dunder_file(n) or (isinstance(n, ast.Name) and n.id in names)
               for n in ast.walk(node))


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _starts_with_a_store_segment(value: object) -> bool:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return False
    pure = PurePosixPath(value)
    return not pure.is_absolute() and bool(pure.parts) and pure.parts[0] in SEGMENTS


def _offenders(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    names = _file_derived_names(tree) - _parameter_names(tree)
    hits = []
    for node in ast.walk(tree):
        # ROOT / "store" / "dossiers"
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant)
                and node.right.value in SEGMENTS
                and _mentions(node.left, names)):
            hits.append((node.lineno, ast.unparse(node)))
            continue
        if not isinstance(node, ast.Call) or not node.args:
            continue
        # os.path.join(os.path.dirname(__file__), "store", "dossiers")
        if _dotted(node.func) == "os.path.join":
            if (any(isinstance(a, ast.Constant) and a.value in SEGMENTS for a in node.args)
                    and any(_mentions(a, names) for a in node.args)):
                hits.append((node.lineno, ast.unparse(node)[:120]))
            continue
        # ROOT.glob("store/ops/restore_drill*")
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr in {"glob", "rglob", "joinpath"}
                and isinstance(node.args[0], ast.Constant)
                and _starts_with_a_store_segment(node.args[0].value)
                and _mentions(node.func.value, names)):
            hits.append((node.lineno, ast.unparse(node)[:120]))
    return hits


def _sources() -> tuple[Path, ...]:
    """Ask git rather than walking the tree; see `repo_files.py` for why."""
    return repo_python_files()


def test_there_are_sources_to_grade():
    """Anti-vacuity. A walk that finds no files passes every assertion below."""
    assert len(_sources()) > 500, "the source walk collapsed; every check below is now vacuous"


def test_no_store_path_is_derived_from_the_source_files_location():
    bad = []
    for p in _sources():
        rel = p.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        for line, src in _offenders(p):
            bad.append(f"{rel}:{line}  {src}")
    assert not bad, (
        "These derive a store path from __file__, so they follow the CODE and not the state. "
        "Use prospector.config.store_root(). If one is genuinely correct, add it to ALLOWED "
        "with the reason:\n  " + "\n  ".join(bad))


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_every_allowed_file_exists_and_still_needs_its_exemption(rel: str):
    """An allow-list that outlives its entries stops being a decision and becomes debris. A file
    that no longer derives a store path must be removed from it, or the next real offender at
    that path is waved through."""
    p = REPO / rel
    assert p.exists(), f"{rel} is on the allow-list and does not exist"
    assert _offenders(p), (
        f"{rel} no longer derives a store path from __file__. Remove it from ALLOWED, or the "
        f"next one written in that file will be exempt.")


def test_every_exemption_carries_a_reason():
    for rel, why in ALLOWED.items():
        assert len(why) > 40, f"{rel} is exempt for a reason too short to be one: {why!r}"


@pytest.mark.parametrize("src", [
    # the two-step form the original regex could not see
    "ROOT = Path(__file__).resolve().parents[1]\nD = ROOT / 'store' / 'dossiers'\n",
    # os.path.join, which the AST walk could not see either: tools/backfill_pack_currency.py:56
    "import os\nD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'store', 'dossiers')\n",
    # a glob off a file-derived root: scripts/ops_status.py:199
    "ROOT = Path(__file__).resolve().parents[1]\nhits = sorted(ROOT.glob('store/ops/restore_drill*'))\n",
    # __file__ read off a module rather than the current one
    "import prospector.audit as A\nR = Path(A.__file__).resolve().parent.parent\nD = R / 'store'\n",
])
def test_the_shapes_this_is_supposed_to_catch(tmp_path: Path, src: str):
    """Each of these was on disk on 2026-08-19 while this check was green. A guard pinned to the
    one syntax it was written for repeats the mistake it exists to close."""
    p = tmp_path / "z.py"
    p.write_text("from pathlib import Path\n" + src)
    assert _offenders(p), f"missed a file-derived store path:\n{src}"


def test_the_two_step_form_is_what_this_catches():
    """The regex in INC-2026-08-18-store-resolver could not see this shape, which is why it
    counted two out of forty. If this check ever regresses to a single-line match, this fails."""
    src = "import sys\nfrom pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\nD = ROOT / 'store' / 'dossiers'\n"
    tree = ast.parse(src)
    names = _file_derived_names(tree)
    assert names == {"ROOT"}
    assert any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
               and isinstance(n.right, ast.Constant) and n.right.value == "store"
               and _mentions(n.left, names) for n in ast.walk(tree))

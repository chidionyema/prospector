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
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
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
}


def _file_derived_names(tree: ast.Module) -> set[str]:
    """Module-level names bound to any expression that mentions __file__."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(n, ast.Name) and n.id == "__file__" for n in ast.walk(node.value)
        ):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _mentions(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and (n.id == "__file__" or n.id in names)
               for n in ast.walk(node))


def _offenders(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    names = _file_derived_names(tree)
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant)
                and node.right.value in SEGMENTS
                and _mentions(node.left, names)):
            hits.append((node.lineno, ast.unparse(node)))
    return hits


def _sources() -> list[Path]:
    return [p for p in sorted(REPO.rglob("*.py"))
            if not any(part in SKIP_DIRS for part in p.relative_to(REPO).parts)]


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

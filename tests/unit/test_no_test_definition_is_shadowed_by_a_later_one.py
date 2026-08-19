"""A duplicated `def` in a test file deletes a test and nothing fails.

This exists because of a merge resolution I got wrong on 2026-08-19. Resolving a conflict as
"both sides append independent blocks, keep both" is safe only when the two sides really do ADD
independent things. When both sides REDEFINE the same name, keeping both silently drops the first
definition. TypeScript refuses that outright -- the same mistake in
`store_platform/src/Ops.Console/tests/pages.test.ts` was `TS1109` and reddened CI. Python does not:
the second `def test_x` simply replaces the first, the file imports cleanly, pytest collects one
test where there were two, and the count goes down with nothing to read.

So the guard is here rather than in a code review note. It walks the AST, which means it sees a
shadowed definition however far apart the two copies are and whatever sits between them -- a
line-based scan cannot.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]


def _duplicate_definitions(tree: ast.Module) -> list[tuple[str, str, int]]:
    """Every name defined more than once in the same body, with the line of the LOSING copy."""
    found: list[tuple[str, str, int]] = []

    def scan(body: list[ast.stmt], where: str) -> None:
        seen: dict[str, int] = {}
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in seen:
                    found.append((where, node.name, seen[node.name]))
                seen[node.name] = node.lineno

    scan(tree.body, "module")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            scan(node.body, node.name)

    return found


def test_no_test_file_defines_the_same_name_twice() -> None:
    offenders: list[str] = []
    scanned = 0
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # a deliberately broken fixture; other guards own that
            continue
        scanned += 1
        for where, name, lineno in _duplicate_definitions(tree):
            scope = "" if where == "module" else f"{where}."
            offenders.append(
                f"{path.relative_to(TESTS_ROOT.parent)}:{lineno} defines {scope}{name}, "
                "and a later definition in the same body replaces it"
            )

    assert scanned > 300, (
        f"the scan found only {scanned} test files; it is not looking where it thinks"
    )
    assert not offenders, (
        "a definition here is shadowed by a later one with the same name, so the first is dead "
        "code that pytest never runs. This is what a bad 'keep both sides' merge resolution looks "
        "like in Python:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_can_actually_see_a_shadowed_definition(tmp_path: Path) -> None:
    """Mutation proof: the check above is worthless if it cannot fail."""
    src = "def test_one():\n    pass\n\n\ndef helper():\n    pass\n\n\ndef test_one():\n    pass\n"
    dups = _duplicate_definitions(ast.parse(src))
    assert dups == [("module", "test_one", 1)], dups

    nested = "class TestThing:\n    def test_a(self):\n        pass\n\n    def test_a(self):\n        pass\n"
    assert _duplicate_definitions(ast.parse(nested)) == [("TestThing", "test_a", 2)]

    # And it must NOT fire on the same name in two different bodies, which is legal and common.
    ok = "class A:\n    def test_a(self):\n        pass\n\n\nclass B:\n    def test_a(self):\n        pass\n"
    assert _duplicate_definitions(ast.parse(ok)) == []

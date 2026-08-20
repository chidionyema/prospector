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

2026-08-20 widened it past `tests/`, because the same resolution cost the same day twice. Rebasing
#508 onto main kept both sides of `scripts/launchd_plists.py`, so `disabled_labels()` was defined
at :185 (fail open, from #345) and again at :384 (fail unknown, mine). Python took the later one
and `test_launchd_broken_program_paths.py` went red on a runner with no launchctl. The sweep that
found it then found one more, sitting on main since #206: `prospector/dossier.py` defined
`_mapping` at :418 with a nine-line docstring explaining why stored PASS dossiers were
unrenderable, and again at :539 with none. Same behaviour, so nothing was broken -- but every
caller ran the copy with no reasoning attached, and a reader who found :418 was reading dead code.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]


#: Decorators whose whole job is to attach another implementation to a name that already exists.
#: A `@x.setter` or a `@overload` is not a merge accident, and flagging one turns the guard into
#: noise the first time it meets ordinary Python.
_INTENTIONAL = {"overload", "setter", "getter", "deleter", "register"}


def _redefinition_is_the_point(node: ast.stmt) -> bool:
    for deco in getattr(node, "decorator_list", []):
        target = deco.func if isinstance(deco, ast.Call) else deco
        if getattr(target, "attr", getattr(target, "id", "")) in _INTENTIONAL:
            return True
    return False


def _duplicate_definitions(tree: ast.Module) -> list[tuple[str, str, int]]:
    """Every name defined more than once in the same body, with the line of the LOSING copy."""
    found: list[tuple[str, str, int]] = []

    def scan(body: list[ast.stmt], where: str) -> None:
        seen: dict[str, int] = {}
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _redefinition_is_the_point(node):
                    continue
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


#: Every tree that ships. `store_platform/` is C# and TypeScript, which refuse this at compile
#: time (TS1109), and `store/` is runtime state rather than source.
_CODE_ROOTS = ("prospector", "scripts", "tools", "publish", "ops")


def test_no_shipping_module_defines_the_same_name_twice() -> None:
    """The same check, on the code the business runs.

    A shadowed `def` in a test deletes a test. A shadowed `def` in a module deletes an
    implementation, and the one that survives is whichever the file happens to end with.
    """
    repo = TESTS_ROOT.parent
    offenders: list[str] = []
    scanned = 0
    for root in _CODE_ROOTS:
        for path in sorted((repo / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # a fixture that is meant to be unparseable
                continue
            scanned += 1
            for where, name, lineno in _duplicate_definitions(tree):
                scope = "" if where == "module" else f"{where}."
                offenders.append(
                    f"{path.relative_to(repo)}:{lineno} defines {scope}{name}, and a later "
                    "definition in the same body replaces it"
                )

    assert scanned > 200, (
        f"the scan found only {scanned} modules; it is not looking where it thinks"
    )
    assert not offenders, (
        "a definition here is shadowed by a later one with the same name, so the first is dead "
        "code no caller can reach. Two implementations of one thing is worse than none: each "
        "reads as correct on its own, and which one runs is decided by file order.\n  "
        + "\n  ".join(offenders)
    )


def test_a_decorator_that_redefines_on_purpose_is_not_an_offender() -> None:
    """Mutation proof for the exemption: it must exempt exactly these, and nothing else."""
    prop = ("class A:\n"
            "    @property\n"
            "    def x(self):\n        return 1\n\n"
            "    @x.setter\n"
            "    def x(self, v):\n        pass\n")
    assert _duplicate_definitions(ast.parse(prop)) == []

    over = ("from typing import overload\n\n"
            "@overload\n"
            "def f(a: int) -> int: ...\n\n"
            "def f(a):\n    return a\n")
    assert _duplicate_definitions(ast.parse(over)) == []

    # An undecorated pair is still an offender, and a decorator NOT on the list does not excuse one.
    plain = "import functools\n\n@functools.cache\ndef f():\n    pass\n\ndef f():\n    pass\n"
    assert _duplicate_definitions(ast.parse(plain)) == [("module", "f", 4)]  # the def line, not the decorator

"""Engine code must spawn children with the interpreter it is already running under.

WHAT BROKE. `tools/recover_stranded_passes.py` is the daemon's repair pass: it re-lints every
PASS that is not on the shelf and runs the cheapest command that can move it. It built the
interpreter for those child commands out of the checkout layout:

    PY = str(REPO / ".venv" / "bin" / "python")

That is a developer-machine assumption. Production moved into a container on 2026-08-18, where
there is no `.venv` at all, so EVERY repair route died before running a single command:

    FileNotFoundError: [Errno 2] No such file or directory: '/app/.venv/bin/python'

The repair pass kept running every cycle, kept writing ledger rows, and healed nothing. Fifty-
nine finished PASSes sat off the shelf and the founder was the one who noticed.

THE CLASS OF FAILURE. This is the interpreter twin of the store-path trap already recorded in
CLAUDE.md: "a store path derived from `__file__` follows the CODE, not the store." Anything
derived from where the source happens to sit breaks the moment the source moves, and it breaks
silently, because the code that would have reported the problem is the code that did not run.
`sys.executable` is the same answer on a laptop, in a venv, in CI and in a container.

WHAT THIS TEST PINS. No module under prospector/ or tools/ may name a virtualenv as a path
COMPONENT. Display strings are exempt on purpose -- the ops console prints
".venv/bin/python -m prospector.run vet" as a copyable hint for a human at a terminal in this
checkout, which is correct and is not an interpreter this process will ever exec. The
difference is mechanical: a path being BUILT joins a bare ".venv" component, a string being
PRINTED contains a slash.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: Runtime code. scripts/ is excluded: those are operator entry points that a human invokes in
#: this checkout, and their usage text naming .venv/bin/python is the correct instruction.
RUNTIME_DIRS = ("prospector", "tools")
#: A path component, not a sentence. "venv" alone is how `Path(x) / ".venv" / "bin"` is spelled;
#: ".venv/bin/python" with its slashes is how a help string is spelled.
COMPONENTS = {".venv", "venv", "virtualenv"}


def _docstring_ids(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
           and isinstance(body[0].value.value, str):
            out.add(id(body[0].value))
    return out


def test_no_runtime_module_builds_an_interpreter_path_from_the_checkout():
    offenders: list[str] = []
    for name in RUNTIME_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            docs = _docstring_ids(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docs or node.value not in COMPONENTS:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} -> {node.value!r}")
    assert not offenders, (
        "a virtualenv named as a path component means an interpreter is being built from the "
        "checkout layout, which does not exist in the container production runs in. Use "
        "sys.executable.\n  " + "\n  ".join(offenders)
    )


def test_the_repair_pass_reuses_the_running_interpreter():
    """The specific regression, asserted against the value the child actually receives."""
    sys.path.insert(0, str(ROOT))
    from tools import recover_stranded_passes as R

    assert R.PY == sys.executable, (
        "the repair pass would exec a different interpreter than the one running it; on "
        "2026-08-18 that was /app/.venv/bin/python inside a container with no venv, and every "
        "repair route raised FileNotFoundError before doing any work"
    )


def test_every_route_command_starts_with_that_interpreter():
    sys.path.insert(0, str(ROOT))
    from tools import recover_stranded_passes as R

    seen = 0
    for route in ("audit", "rebundle", "regenerate", "copy", "citations", "currency", "publish"):
        cmd = R._cmd(route, "deadbeefdeadbeef", True)
        if cmd is None:
            continue                      # a route that cannot run unattended is not a finding
        seen += 1
        assert cmd[0] == sys.executable, f"route {route} execs {cmd[0]!r}"
    assert seen >= 6, f"only {seen} routes returned a command; the route table changed shape"

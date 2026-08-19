"""Every source file must open by saying what it is for.

Founder directive 2026-08-19: "every code or script file should have a short summary before the
code, helps agents and humans to know what things do". An agent that has to read a whole module to
learn its purpose reads it every session, and pays for it every session.

The rule is mechanical so it cannot rot: a Python file needs a module docstring, a shell script
needs a comment line near the top. Both are checked here rather than in a linter because the
estate's linter config is shared with other repos and this is our rule, not theirs.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Directories that hold code we did not write, or state rather than source. `store/` and `storage/`
# are tracked runtime state; the rest are vendored or generated.
SKIP = {".git", ".venv", "node_modules", "store", "storage", "graphify-out",
        "bin", "obj", "__pycache__", ".next", "dist", "build"}


def _sources(suffix: str) -> list[Path]:
    return [p for p in ROOT.rglob(f"*{suffix}")
            if not any(part in SKIP for part in p.relative_to(ROOT).parts)]


def test_every_python_file_opens_with_a_docstring():
    """A module with no docstring is a module whose purpose is only in its author's head."""
    missing = []
    for path in _sources(".py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue  # a fixture of deliberately broken source is not a missing docstring
        if not ast.get_docstring(tree):
            missing.append(str(path.relative_to(ROOT)))
    assert not missing, (
        "these Python files start with code instead of a sentence saying what they do:\n  "
        + "\n  ".join(sorted(missing)))


def test_every_shell_script_opens_with_a_comment():
    """Same rule, expressed the way shell expresses it: a comment above the first command."""
    missing = []
    for path in _sources(".sh"):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        head = [ln.strip() for ln in lines[:8] if ln.strip()]
        # Skip the shebang and `set -euo pipefail`; what we want is a human sentence before work.
        prose = [ln for ln in head
                 if ln.startswith("#") and not ln.startswith("#!") and len(ln) > 3]
        if not prose:
            missing.append(str(path.relative_to(ROOT)))
    assert not missing, (
        "these shell scripts start with commands instead of a comment saying what they do:\n  "
        + "\n  ".join(sorted(missing)))

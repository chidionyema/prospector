"""`git status --porcelain` output must never be sliced at a fixed column.

WHY THIS EXISTS. This is the third time. `git status --porcelain` prints "XY path", so `line[3:]`
looks right -- and it is, until the payload has been stripped. Every helper in this estate ends
`subprocess.run(...).stdout.strip()`, which removes the leading space of the FIRST line only. The
first path then loses a character and everything else is fine, so the bug hides behind nine
correct rows.

    scripts/session_check.py  printed "LAUDE.md" for CLAUDE.md
    scripts/live_checkout.py  hit the same thing on an unstaged change
    scripts/worktree_snapshot.py  printed "tore/runtime.json" for store/runtime.json on
                                  2026-08-19, in a file written by someone who had read the
                                  comment in session_check.py describing the trap

A comment is not a guard. Founder, 2026-08-19: "need to get better dont repat nistakes". So this
is the mechanical form: split on whitespace, never slice.

    parts = line.strip().split(maxsplit=1)
    rel = parts[1] if len(parts) == 2 else ""
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Only `[3:]` on a plain name. Deliberately narrow: `[:2]` catches innocent list slicing, and a
# guard that cries wolf gets deleted, which is worse than not having one.
COLUMN_SLICE = re.compile(r"\b\w+\[3:\]")


def _code(path: Path) -> str:
    """Comments and docstrings DESCRIBE the trap; only code falls into it. Three files carry the
    string `[3:]` inside an explanation of this very bug."""
    out, in_doc = [], False
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if s.count('"""') == 1 or s.count("'''") == 1:
            in_doc = not in_doc
            continue
        if in_doc or s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
            continue
        out.append(ln.split("  #")[0])
    return "\n".join(out)


def porcelain_readers() -> list[Path]:
    roots = [ROOT / "scripts", ROOT / "prospector", ROOT / "tools"]
    return sorted(p for r in roots if r.is_dir() for p in r.rglob("*.py")
                  if "--porcelain" in p.read_text())


def test_there_are_porcelain_readers_to_check():
    """Without this, a path change makes every assertion below vacuously true."""
    assert len(porcelain_readers()) >= 5


@pytest.mark.parametrize("path", porcelain_readers(), ids=lambda p: p.name)
def test_no_fixed_column_slice(path: Path):
    hits = [ln for ln in _code(path).splitlines() if COLUMN_SLICE.search(ln)]
    assert not hits, (
        f"{path.relative_to(ROOT)} slices porcelain output at a fixed column: {hits}. "
        f"stdout.strip() has already eaten the first line's status space, so this drops a "
        f"character from the first path. Use line.strip().split(maxsplit=1) instead.")


def test_the_detector_fires_on_the_defect(tmp_path: Path):
    """The paired negative. A checker nobody has watched fail is a checker that passes because it
    never looks."""
    bad = tmp_path / "bad.py"
    bad.write_text('out = run(["git", "status", "--porcelain"])\n'
                   'for line in out.splitlines():\n'
                   '    rel = line[3:]\n')
    assert [ln for ln in _code(bad).splitlines() if COLUMN_SLICE.search(ln)]


def test_the_detector_ignores_the_same_text_in_a_comment(tmp_path: Path):
    """The three files that document this trap must not be reported as committing it."""
    ok = tmp_path / "ok.py"
    ok.write_text('# a [3:] slice eats a character of the path\n'
                  'out = run(["git", "status", "--porcelain"])\n'
                  'rel = line.strip().split(maxsplit=1)[1]\n')
    assert not [ln for ln in _code(ok).splitlines() if COLUMN_SLICE.search(ln)]


def test_the_detector_ignores_the_same_text_in_a_docstring(tmp_path: Path):
    ok = tmp_path / "doc.py"
    ok.write_text('def f():\n'
                  '    """`line[3:]` then read the wrong column. --porcelain"""\n'
                  '    return 1\n')
    assert not [ln for ln in _code(ok).splitlines() if COLUMN_SLICE.search(ln)]

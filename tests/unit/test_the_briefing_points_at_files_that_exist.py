"""`CLAUDE.md` is the only document every session is briefed from. Its pointers must resolve.

WHAT HAPPENED. 2026-08-19. Every false alarm of that day came from reading a SHAPE -- a count, a
colour, a status letter, an exit code -- as if it were the CONTENT it points at. The answer was
`docs/CI_DEBUG_RUNBOOK.md`, and a doc only works if the next session is told it exists. The telling
happens in one place: the "Read these, do not re-derive them" table in `CLAUDE.md`, which is
injected into every session started in this repo.

WHY A TEST AND NOT A NOTE. That table is not checked by anything. `scripts/doc_lint.py` names
`CLAUDE.md` in `HISTORICAL_FILES` (line 49) and so skips its path checks entirely -- deliberately,
because the file carries dated history that names files which have since gone. The consequence is
that the one file every agent reads can point at a doc that does not exist, and nothing fails. A
briefing that sends a session to a missing path costs that session the time it takes to work out
that the map is wrong, and it costs it again in the next session, and the one after.

So this test checks the TABLE ONLY, not the prose. The table is the part that is a promise.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
RUNBOOK = "docs/CI_DEBUG_RUNBOOK.md"

#: A row of the pointer table: `| `path` | what it answers |`
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.M)


def _pointer_table() -> str:
    """The 'Read these' section only. Prose elsewhere may name files that are gone; this may not."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.find("## Read these, do not re-derive them")
    assert start >= 0, (
        "CLAUDE.md no longer has a '## Read these, do not re-derive them' section. That table is "
        "how a new session learns which docs exist; without it every session re-derives the estate."
    )
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else len(text)]


def test_every_doc_the_briefing_names_is_on_disk():
    """A row pointing at a missing file sends every future session to a path that is not there."""
    missing = []
    for raw in _ROW.findall(_pointer_table()):
        path = raw.strip()
        if path.startswith("~") or path.startswith("http"):
            continue          # estate files outside this repo; a different checkout is not rot
        if not (REPO_ROOT / path).exists():
            missing.append(path)
    assert not missing, (
        "CLAUDE.md's pointer table names files that do not exist, so every session is briefed "
        "with a broken map:\n  " + "\n  ".join(missing)
    )


def test_the_table_is_not_empty():
    """A regex that silently matches nothing would make the test above pass forever."""
    rows = _ROW.findall(_pointer_table())
    assert len(rows) >= 5, (
        f"only {len(rows)} pointer rows parsed out of CLAUDE.md. Either the table was gutted or "
        f"its formatting changed and this test stopped checking anything."
    )


def test_the_red_runbook_is_reachable_from_the_briefing():
    """The runbook's whole value is being read BEFORE the four hours, not after them.

    It is a doc, so nothing can force a session to read it. The nearest mechanism is that the
    briefing every session already receives names it. Drop the row and the reach is gone with no
    other symptom, which is exactly the kind of silent loss this estate keeps paying for.
    """
    assert (REPO_ROOT / RUNBOOK).exists(), f"{RUNBOOK} is gone"
    assert RUNBOOK in _pointer_table(), (
        f"{RUNBOOK} is no longer in CLAUDE.md's pointer table. It is the file that says 'open the "
        f"job log before you act on a red', and a session that is not told about it will not find "
        f"it while something is on fire."
    )

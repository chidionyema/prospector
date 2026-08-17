"""No merge-conflict marker may be committed.

Written 2026-08-17, after `docs/LAUNCH_OPS_PROGRAM.md` reached `origin/main` carrying a whole
unresolved conflict block at lines 494-497. Nothing caught it: it is valid Markdown, the doc
linter grades path claims rather than syntax, and no test read the file. It sat on main until
someone happened to read that part of the ledger.

The markers are built from single characters here so this file cannot flag itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The three markers `git merge` writes, as anchored regexes. The separator is seven `=` ALONE on
#: the line: two shell scripts draw banner rules out of longer runs of `=`, and those are not
#: conflicts. The other two markers are seven characters then a space, then the ref name.
MARKER_PATTERNS = ("^<{7} ", "^={7}$", "^>{7} ")


def test_no_tracked_file_carries_a_conflict_marker():
    pattern = "|".join(MARKER_PATTERNS)
    p = subprocess.run(
        ("git", "-C", str(REPO), "grep", "-n", "-I", "-E", pattern, "--",
         ".", f":(exclude){Path(__file__).relative_to(REPO)}"),
        capture_output=True, text=True, timeout=120)

    # git grep exits 1 when nothing matched, which is the passing case.
    assert p.returncode in (0, 1), f"git grep failed: {p.stderr.strip()}"
    hits = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert not hits, (
        "these tracked files carry an unresolved merge conflict. Resolve them; a conflict block "
        "is valid Markdown and valid-looking code, so nothing else will tell you:\n  "
        + "\n  ".join(hits[:40]))

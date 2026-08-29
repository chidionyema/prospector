"""`docs/ESTATE_MAP.md` cites code by `file:line`. Nothing checked those lines until now.

Three independent audits graded that document against live state on 2026-08-20. Nine findings.
FIVE of them were line numbers that had drifted while the prose stayed true -- `verify.py:365`
for a symbol that had moved to :580, `run.py:2687` for one at :2735, and three more. A reader
following a stale citation lands in unrelated code and concludes the document is lying about
something bigger than a line number.

That failure is mechanical, so it is guardable. This test reads every citation in the map,
finds the identifiers named beside it, and asserts at least one of them is still within a few
lines of where the map says it is.

It deliberately does NOT grade prose. A citation with no identifier beside it is COUNTED and
reported, never silently passed -- see `test_coverage_is_reported`, which exists so that a
future edit cannot quietly drop this guard to zero checks while still going green.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP = REPO_ROOT / "docs" / "ESTATE_MAP.md"

# `prospector/run.py:2735`, `verify.py:580`, `deploy/targets/fly.sh:4`
CITATION = re.compile(r"`([\w./-]+\.(?:py|sh|ts|tsx|cs|yml|yaml|json|md)):(\d+)`")
BACKTICKED = re.compile(r"`([^`]+)`")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")

# How far a symbol may have moved before this test calls it drift. Small on purpose: a
# citation is a pointer, and a pointer that is four lines out is already misleading.
WINDOW = 3


def _identifiers_near(lines, i):
    """Identifier-looking tokens in backticks on the citing line and the one after it.

    Two lines because the map wraps: "`verify.py:580` and `verify.py:682`\\nset
    `retrieval_failed=True` on any verdict call that raises" puts the pointer and the symbol
    it points at on either side of a line break.
    """
    out = set()
    for line in lines[i : i + 2]:
        for chunk in BACKTICKED.findall(line):
            if CITATION.fullmatch("`" + chunk + "`"):
                continue  # the citation itself is not the symbol it points at
            out.update(IDENTIFIER.findall(chunk))
    # Path segments and prose words that are never symbols in the source.
    return {t for t in out if t not in {"prospector", "deploy", "targets", "docs", "True", "False", "None"}}


def _citations():
    lines = MAP.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        for path, lineno in CITATION.findall(line):
            yield i + 1, path, int(lineno), _identifiers_near(lines, i)


def test_every_cited_file_exists():
    missing = [
        f"ESTATE_MAP.md:{doc_line} cites {path}, which is not in the tree"
        for doc_line, path, _, _ in _citations()
        if not (REPO_ROOT / path).exists()
    ]
    assert not missing, "\n".join(missing)


def test_every_cited_line_is_inside_its_file():
    short = []
    for doc_line, path, lineno, _ in _citations():
        f = REPO_ROOT / path
        if not f.exists():
            continue
        n = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        if lineno > n:
            short.append(f"ESTATE_MAP.md:{doc_line} cites {path}:{lineno}, but that file has {n} lines")
    assert not short, "\n".join(short)


def test_every_cited_symbol_is_still_where_the_map_says():
    """The five 2026-08-20 findings were all this shape, and all five would have failed here."""
    drifted = []
    for doc_line, path, lineno, names in _citations():
        f = REPO_ROOT / path
        if not names or not f.exists():
            continue
        src = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if lineno > len(src):
            continue  # the previous test owns that failure
        lo, hi = max(0, lineno - 1 - WINDOW), min(len(src), lineno + WINDOW)
        window = "\n".join(src[lo:hi])
        if not any(n in window for n in names):
            drifted.append(
                f"ESTATE_MAP.md:{doc_line} points at {path}:{lineno} for "
                f"{sorted(names)}, and none of them is within {WINDOW} lines of there"
            )
    assert not drifted, "\n".join(drifted)


def test_coverage_is_reported():
    """A guard that silently checks nothing is worse than no guard: it reads as covered.

    So the count is asserted, not just computed. If a future edit removes the citations, or
    reformats them out of the regex's reach, this fails and says so instead of going green on
    an empty set.
    """
    cites = list(_citations())
    checkable = [c for c in cites if c[3]]
    # Both numbers were MEASURED on 2026-08-20, not chosen: the map carries exactly 6
    # `file:line` citations and all 6 name a symbol beside them. They are a ratchet. Adding
    # citations is free; removing one fails here and says so, which is the point -- the
    # cheapest way to make this guard useless is to stop writing the citations it grades.
    # Lower these deliberately, in a commit that says why, or not at all.
    assert len(cites) >= 6, (
        f"only {len(cites)} citations parsed out of the map, was 6 on 2026-08-20 -- either a "
        "citation was removed or the `path:line` format changed out of this regex's reach"
    )
    assert len(checkable) >= 6, (
        f"{len(cites)} citations found but only {len(checkable)} name a symbol this test can "
        "verify; the rest are pointers nothing grades"
    )


def test_every_repo_path_named_in_the_map_exists():
    """A map that names a deleted file sends the reader looking for it.

    Only RELATIVE paths with a directory part are graded. The map also names absolute paths
    that live on other machines -- `/srv/prospector/data/engine.env` on a remote box,
    `/app/GIT_SHA` inside a container image -- and those are not this checkout's to have.
    """
    # Strip fenced blocks BEFORE pairing backticks. A ``` fence is three backticks, so a
    # document with an odd number of fence characters ahead of a span makes every later
    # `span` pair with the wrong neighbour -- which is not a theory: this test was written
    # without the strip, and a deliberately-planted `prospector/does_not_exist.py` was
    # invisible to it while the rest of the file graded fine.
    text = re.sub(r"```.*?```", "", MAP.read_text(encoding="utf-8"), flags=re.S)
    missing = []
    for chunk in set(BACKTICKED.findall(text)):
        candidate = chunk.split(":", 1)[0].strip()
        if candidate.startswith(("/", "~", "http")) or "/" not in candidate:
            continue
        # `store/` and `storage/` are RUNTIME state, pinned by PROSPECTOR_STORE_DIR to a
        # directory outside every checkout. A dossier the map cites as evidence is a real
        # file on the live box and will never be in this tree, so grading it here would
        # assert something the repo cannot satisfy -- and a test that can only fail is a
        # test the next agent deletes. Whether the LIVE store still holds it is a different
        # question, and not one a checkout can answer.
        if candidate.startswith(("store/", "storage/")):
            continue
        if " " in candidate or not re.search(r"\.(py|sh|ts|tsx|cs|yml|yaml|json|md)$", candidate):
            continue
        if not (REPO_ROOT / candidate).exists():
            missing.append(candidate)
    assert not missing, "named in ESTATE_MAP.md but not in the tree: " + ", ".join(sorted(missing))

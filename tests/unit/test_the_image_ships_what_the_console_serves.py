"""The image must contain the files the console serves out of it.

2026-08-20: the founder clicked the ops console's Docs tab and nothing happened. It was not a
stale deploy and it was not the page. `.dockerignore` excluded `docs/`, so `COPY . /app` shipped
none of it, and on prospector-engine:

    $ python -m prospector.ops.console_api read docs
    "data": {"root": "/app/docs", "sections": [], "count": 0,
             "note": "there is no docs/ directory in this checkout"}

Nothing failed. The backend diagnosed itself correctly, the page rendered the diagnosis as an
empty screen, and every check in the estate stayed green. That is the class this file closes:
**a screen served from the container, reading a path the image does not carry.** The exclusion
was written when documentation genuinely was runtime dead weight; the console grew a Docs tab
and a Share tab on 2026-08-19 and nobody went back to the build context.

The check runs against `.dockerignore` rather than against a built image on purpose. Building
the image takes minutes and needs a daemon; reading the file that decides what goes into it
takes milliseconds and fails on the machine that introduced the fault.
"""
from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

#: Repo paths a console read view resolves under, and the view that reads them. A path here is
#: served to an operator out of the RUNNING CONTAINER, so excluding it from the image turns the
#: screen that serves it into an empty page rather than an error.
SERVED: dict[str, str] = {
    "docs": (
        "prospector/ops/docs_view.py:41 resolves `repo_root / 'docs'` for the /docs tab, and "
        "prospector/ops/incidents_view.py:84 reads docs/incidents for the /incidents tab"
    ),
    "specs": (
        "prospector/ops/share.py serves any tracked file, and in the container its allow-list "
        "is a walk of the image itself because .git is excluded -- so a spec absent from the "
        "image cannot be shared at all"
    ),
    "scripts": (
        "prospector/ops/incidents_view.py:49 runs scripts/incident.py, which is where the "
        "judgement about a record lives, so the page and the CI gate cannot disagree"
    ),
    "ops": (
        "prospector/ops/automations_view.py:57 globs ops/automations/*.py and ops/config/*.yaml "
        "to discover every automation for the /processes tab"
    ),
    ".github/workflows": (
        "scripts/deploy_status.py:55 resolves `ROOT / '.github/workflows'` and parses each deploy "
        "workflow's `paths:` filter -- that function IS the /deploys tab, so with the directory "
        "absent every deployable renders UNKNOWN and the deploy and rollback buttons read as "
        "missing features"
    ),
}


def _patterns() -> list[str]:
    """The exclusion patterns in `.dockerignore`, comments and negations dropped.

    A `!` line re-includes, which can only ever help a served path, so ignoring those keeps the
    check on the strict side: it can report an exclusion that docker would undo, and it can
    never miss one.
    """
    out: list[str] = []
    for raw in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        out.append(line)
    return out


def matching_pattern(rel: str, patterns: list[str]) -> str | None:
    """The first pattern that keeps `rel` out of the build context, or None.

    A pattern excludes a path when it matches the path itself or any directory above it --
    `docs/` excludes `docs/decisions/0002.md`. `fnmatch` lets `*` cross a `/`, which docker does
    not, so this errs towards reporting an exclusion. Erring that way is safe here: the tests
    below assert a path is NOT excluded, so an over-eager matcher fails loudly and never waves
    a missing directory through.
    """
    parts = rel.strip("/").split("/")
    ancestry = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if not pat:
            continue
        if pat.startswith("**/"):
            tail = pat[3:]
            if any(fnmatch(a.split("/")[-1], tail) or fnmatch(a, tail) for a in ancestry):
                return pattern
        elif any(fnmatch(a, pat) for a in ancestry):
            return pattern
    return None


@pytest.mark.parametrize("rel", sorted(SERVED))
def test_a_path_the_console_serves_is_in_the_image(rel: str):
    hit = matching_pattern(rel, _patterns())
    assert hit is None, (
        f".dockerignore excludes {rel!r} by the pattern {hit!r}, but the console serves it out "
        f"of the container:\n  {SERVED[rel]}\n\n"
        "The screen will not error. It will render empty, which is how this went unnoticed "
        "from 2026-08-19 until the founder clicked the tab. Either un-exclude the path or "
        "delete the view that reads it."
    )


@pytest.mark.parametrize("rel", sorted(SERVED))
def test_a_path_the_console_serves_is_tracked_in_git(rel: str):
    """An untracked path reaches the image but no clone, so a fresh checkout serves nothing."""
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", rel],
        capture_output=True, text=True, check=True,
    ).stdout
    assert listed.strip("\0"), f"{rel!r} is served by the console and tracked by nothing"


@pytest.mark.parametrize("reason", SERVED.values())
def test_every_served_path_names_the_view_that_reads_it(reason: str):
    """A bare entry cannot be reviewed, and cannot be removed by anyone who did not add it."""
    assert len(reason) > 60, f"too short to be a reason: {reason!r}"


@pytest.mark.parametrize(("pattern", "rel", "excluded"), [
    ("docs/", "docs", True),                         # the shape that caused the incident
    ("docs/", "docs/decisions/0002.md", True),       # ... and everything under it
    ("docs/design/", "docs", False),                 # the narrowed form that replaced it
    ("docs/design/", "docs/design/diff/a.png", True),
    ("docs/design/", "docs/decisions/0002.md", False),
    ("**/node_modules/", "a/b/node_modules", True),  # any depth
    ("**/node_modules/", "specs", False),
    ("store/", "specs", False),
    ("*.log", "scripts", False),
    (".github/", ".github/workflows", True),         # the 2026-08-20 shape
    (".github/", ".github/workflows/ci.yml", True),
    (".github/", "scripts", False),
])
def test_the_matcher_can_fail(pattern: str, rel: str, excluded: bool):
    """A matcher that never matches would pass every test above while proving nothing."""
    hit = matching_pattern(rel, [pattern])
    assert (hit is not None) is excluded, f"{pattern!r} vs {rel!r}: got {hit!r}"


def test_the_incident_pattern_is_gone_from_dockerignore():
    """The literal line this incident was caused by, named so a revert is loud rather than quiet."""
    patterns = _patterns()
    assert "docs/" not in patterns and "specs/" not in patterns, (
        "docs/ or specs/ is excluded from the build context again. On 2026-08-20 that made the "
        "console's Docs tab render an empty screen with no error for a day."
    )
    assert ".github/" not in patterns, (
        ".github/ is excluded from the build context again. On 2026-08-20 that left /app with no "
        "workflow files, so the console's Deploys tab reported every service as UNKNOWN and "
        "accused the repo of deleting workflows that were on main the whole time."
    )

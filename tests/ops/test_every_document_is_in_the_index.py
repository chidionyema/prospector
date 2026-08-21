"""No document in this repo may be invisible from the ops console.

THE MEASUREMENT THAT PRODUCED THIS FILE. 2026-08-21, on `origin/main`: **298 tracked document
files, 113 visible on the /docs page and 185 invisible.** The founder's words were "no docs are
nissed out". Three mechanical causes, none of them a decision anyone made — the index root was
`docs/`, the collector never recursed, and the suffix allow-list was `(.md, .json)`.

WHY A TEST AND NOT A NOTE. Each of those three limits was correct when it was written and became
a hole when the estate grew past it. A note in a doc does not fail when someone adds
`tools/experiments/` or writes a `.txt`; this does. The page cannot quietly go back to listing a
third of the estate's writing.

WHAT IT ALLOWS. Exactly one exemption, and it is not a list maintained here: a path the share
deny-list refuses. The index and the share fence draw from one population on purpose, so
"invisible" and "unshareable" are the same set by construction. If you need to exempt something
else, that is a change to `share.DENY_GLOBS`, where it is reviewed as a fence change.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from prospector.ops import share
from prospector.ops.docs_view import docs_index

REPO_ROOT = Path(__file__).resolve().parents[2]

#: What counts as a document, DELIBERATELY DUPLICATED rather than imported from `docs_view`.
#:
#: This is the difference between a guard and a mirror. If this test asked `docs_view._is_listed`
#: what a document is, then narrowing that function would narrow both sides of the comparison and
#: the test would keep passing while the page lost coverage — which is exactly the failure being
#: guarded (the old allow-list was `(.md, .json)` and dropped every `.html` and `.txt`). The list
#: below is the requirement; the module's list is the implementation, and they are compared.
DOCUMENT_SUFFIXES = (".md", ".html", ".txt", ".pdf")


def _is_document(path: str) -> bool:
    """A document by the REQUIREMENT, not by whatever the module currently believes."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    suffix = name[dot:].lower() if dot > 0 else ""
    if suffix in DOCUMENT_SUFFIXES:
        return True
    # JSON is a data format everywhere except docs/, where the incident records live.
    return suffix == ".json" and path.startswith("docs/")


@pytest.fixture(scope="module")
def tracked_documents() -> list[str]:
    """Every document git tracks here.

    `_git_tracked` returns None when git cannot answer — in the engine image `.git/` is absent by
    design, so None is the normal production answer and skipping is honest. An EMPTY list is not:
    a worktree whose gitdir has gone missing answers `git ls-files` with nothing and exit 0, and
    every guard that asks git then grades an empty repo and passes. That is a failure, not a skip.
    """
    tracked = share._git_tracked(REPO_ROOT)
    if tracked is None:
        pytest.skip("git cannot answer in this checkout, so there is nothing to compare against")
    assert tracked, (
        "git answered with zero tracked files. This checkout's gitdir is probably missing — "
        "`git ls-files` prints nothing AND exits 0, so this guard would otherwise pass by "
        "grading an empty repo."
    )
    return [p for p in tracked if _is_document(p)]


def test_every_tracked_document_is_reachable_from_the_console(tracked_documents):
    index = docs_index(REPO_ROOT)
    listed = {d["name"] for section in index["sections"] for d in section["docs"]}

    missing = sorted(
        path for path in tracked_documents
        if path not in listed and not share.is_denied(path)
    )
    assert not missing, (
        f"{len(missing)} tracked document(s) cannot be seen from the ops console. The founder's "
        f"requirement is 'no docs are nissed out'. Either the index lost coverage, or these "
        f"belong on share.DENY_GLOBS with a reason:\n  " + "\n  ".join(missing[:40])
    )


def test_the_index_is_not_serving_anything_the_share_fence_refuses(tracked_documents):
    """The fence is the reason a repo-wide index is safe. It must hold in both directions."""
    index = docs_index(REPO_ROOT)
    leaked = sorted(
        d["name"] for section in index["sections"] for d in section["docs"]
        if share.is_denied(d["name"])
    )
    assert not leaked, f"the docs index is listing denied paths: {leaked[:20]}"


def test_the_index_covers_more_than_the_docs_directory(tracked_documents):
    """The specific regression this file exists for: a root that quietly narrows back to docs/.

    Asserted as a property rather than a count, because a count goes stale and then gets edited
    down to whatever the code now produces, which is how a guard stops guarding.
    """
    index = docs_index(REPO_ROOT)
    listed = {d["name"] for section in index["sections"] for d in section["docs"]}
    outside = {name for name in listed if not name.startswith("docs/")}
    assert outside, "the index lists nothing outside docs/ — the root has narrowed again"
    nested = {name for name in listed if name.count("/") >= 2}
    assert nested, "the index lists nothing nested two levels deep — recursion has been lost"


def test_every_listed_document_says_whether_it_can_be_rendered(tracked_documents):
    """A listed entry that errors on click is worse than an absent one.

    `.pdf` is listed and not rendered. The flag is how the console knows the difference, so a
    format added to the index without one would be a row that fails when an operator clicks it.
    """
    index = docs_index(REPO_ROOT)
    for section in index["sections"]:
        for doc in section["docs"]:
            assert "readable" in doc, f"{doc['name']} does not say whether it can be rendered"

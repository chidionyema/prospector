"""The rule: a document this engine generates is in the portal, with no code change.

THE FOUNDER'S WORDS, 2026-08-21: "every single dic generatd should be there without having o ake
cod change" -- and, when asked what done looked like, "that is the cceptance criteria".

WHAT WAS BROKEN. Every document the engine generates at runtime is written under `store/`, and
`store/*` is on the share deny-list, so the docs portal listed none of them. Measured that day:
both scheduler documents sitting on disk, one written twenty minutes earlier, and `is_denied`
refused both. On top of that the portal listed a checkout and the deployed image differently --
`git ls-files` in a checkout, a filesystem walk in the image, which has no `.git/` -- so a
generated document was visible in production and invisible where anyone would look for it.

THE TWO SURFACES ARE NOT ONE SURFACE, and this file grades both. `/docs` is behind a console
session. `/s/<token>` is not, and `public` in `share.py` decides the CLOCK and nothing else, so
there was no content tier at all until `link_denied` was written. A generated document renders
LIVE RUNTIME STATE -- `render_batch_diagnostics` writes candidate titles and spend figures into
`DIAGNOSTICS_LATEST.txt` -- and no suffix rule can pin what today's body says. So the carve puts
these documents in the founder's console and the link fence keeps them off a sessionless link.

WHAT THIS FILE GUARDS, and what it cannot. It cannot prove a browser draws anything. What it can
prove is that the fence still lets generated documents through, that the carve which lets them
through has not widened into the business data sitting next to them, that none of them can be
handed to an outsider, and that a NEW generator writing to a refused path fails here rather than
being discovered by the founder months later.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from prospector.config import REPO_ROOT
from prospector.ops import docs_view, share

sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))

from repo_files import repo_files  # noqa: E402

#: Every runtime document writer this repo has, found 2026-08-21 by reading the write sites. The
#: list is here so `test_no_document_path_in_the_source_is_one_the_portal_cannot_show` fails
#: loudly when someone adds a third one somewhere the portal cannot reach -- which is the exact
#: defect this file exists for.
GENERATED_TODAY = (
    "store/scheduler/DIAGNOSTICS_LATEST.txt",  # prospector/diagnostics.py
    "store/scheduler/ALERT.txt",  # prospector/scheduler/alerts.py
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A tiny tree with one generated document and one ordinary one."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "store" / "scheduler").mkdir(parents=True)
    (root / "store" / "dossiers").mkdir(parents=True)
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "docs" / "GUIDE.md").write_text("# guide\n", encoding="utf-8")
    (root / "store" / "scheduler" / "ALERT.txt").write_text("backlog\n", encoding="utf-8")
    (root / "store" / "dossiers" / "acme.md").write_text("# acme\n", encoding="utf-8")
    return root


@pytest.fixture()
def ops(tmp_path: Path) -> Path:
    d = tmp_path / "store-ops"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- #
# The console surface: every generated document is there, with no code change
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", GENERATED_TODAY)
def test_every_generated_document_is_shareable(rel: str) -> None:
    """The acceptance criteria, one row per generated document."""
    assert share.is_denied(rel) == "", f"the portal cannot show {rel}"
    assert docs_view._is_listed(rel), f"{rel} is shareable but the index would not list it"


def test_a_new_generated_document_needs_no_code_change() -> None:
    """A file nobody has ever named, written into a carved directory, is shareable on sight."""
    for d in share.GENERATED_DOC_DIRS:
        for suffix in share.GENERATED_DOC_SUFFIXES:
            rel = f"{d}a-report-nobody-has-added-to-any-list{suffix}"
            assert share.is_denied(rel) == "", rel
        # At depth too, because a generator that starts dating its output must not need an edit.
        assert share.is_denied(f"{d}2026-08-21/nested/report.md") == ""


def test_the_carve_does_not_reach_the_business_data_beside_it() -> None:
    """`store/` also holds dossiers, runs and listings. None of them may be shared."""
    for rel in (
        "store/dossiers/acme-ltd.md",
        "store/runs/2026-08-21/summary.md",
        "store/listings/pack-14.html",
        "store/markets/uk/probe/notes.txt",
        "store/launch/test-card-proof.md",
        "storage/durable_ledger.md",
    ):
        assert share.is_denied(rel) != "", f"{rel} became shareable"


@pytest.mark.parametrize("pattern", [p for p in share.DENY_GLOBS if p not in share._CARVEABLE])
def test_the_carve_never_overrules_a_secret(pattern: str) -> None:
    """A key, a database or a dotenv inside a carved directory stays refused.

    The safety argument is an ORDERING one: every secret pattern sits earlier in `DENY_GLOBS`
    than the two directory patterns, so `is_denied` returns the secret first and the carve is
    never consulted. This test is what stops someone reordering the tuple.
    """
    stem = pattern.replace("*", "x").replace("?", "x").lstrip(".")
    if not stem or "/" in stem:
        pytest.skip(f"{pattern} is a directory rule, not a filename")
    for d in share.GENERATED_DOC_DIRS:
        assert share.is_denied(f"{d}{stem}") != "", f"{d}{stem} slipped through the carve"


def test_the_fence_refuses_what_is_in_a_carved_directory_and_is_not_a_document() -> None:
    """The carve is a directory rule narrowed by a suffix, and the suffix is doing real work.

    Graded against the REAL tree rather than an invented one, because the first version of this
    test asserted the carved directories hold documents and nothing else, and that premise was
    false the day it was written. Measured 2026-08-21, `store/scheduler/` also held
    `alerts.jsonl`, `launchd-held.log`, `process-audit.{err,out}.log`, `alert_state.json`,
    `spend_scan.cache.json` and an `audit/` subdirectory -- about 700KB of operational logs
    beside the two documents.

    So the claim being pinned is the one that is true: everything in there without a document
    suffix is still refused. If that ever stops holding, a log file has become shareable.
    """
    # A constructed control first, so this test always grades something. The real tree is the
    # second angle and it is the one that notices a change; without the control, a machine with
    # no carved directory on disk would skip and report green.
    for d in share.GENERATED_DOC_DIRS:
        for name in ("alerts.jsonl", "launchd-held.log", "alert_state.json", "audit/tick.jsonl"):
            assert share.is_denied(f"{d}{name}") != "", f"{d}{name} became shareable"

    leaked: list[str] = []
    for d in share.GENERATED_DOC_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if path.suffix.lower() in share.GENERATED_DOC_SUFFIXES:
                continue
            if share.is_denied(rel) == "":
                leaked.append(rel)
    assert not leaked, "a non-document in a carved directory became shareable: " + ", ".join(
        sorted(leaked)[:10]
    )


def test_a_checkout_lists_generated_documents_the_same_way_the_image_does(tmp_path: Path) -> None:
    """The split that made this look like a code-change problem.

    `git ls-files` cannot see a generated file, because generated means untracked. The deployed
    image has no `.git/` and walks instead, so production saw these documents and a checkout did
    not. Same tree, same file on disk, two answers.
    """
    (tmp_path / "store" / "scheduler").mkdir(parents=True)
    (tmp_path / "store" / "scheduler" / "ALERT.txt").write_text("generated\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "TRACKED.md").write_text("# tracked\n", encoding="utf-8")

    walked = share.shareable_files(tmp_path)
    assert "store/scheduler/ALERT.txt" in walked, "the walk lost a generated document"

    # Now make git answer, with the generated file deliberately untracked.
    import subprocess

    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "docs/TRACKED.md"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "t"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True)

    tracked = share.shareable_files(tmp_path)
    assert "docs/TRACKED.md" in tracked
    assert "store/scheduler/ALERT.txt" in tracked, (
        "a checkout hid a generated document the image would have shown"
    )


# --------------------------------------------------------------------------- #
# The link surface: the founder sees them, an outsider never does
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", GENERATED_TODAY)
def test_a_generated_document_is_in_the_console_and_never_on_a_link(rel: str) -> None:
    """The whole point of there being two fences instead of one.

    A `/s/<token>` link is read with no session by whoever holds the token. These documents
    render live runtime state, so what they contain on any given day is not something a path can
    tell you. Console yes, link no, and that split is what this asserts.
    """
    assert share.is_denied(rel) == "", f"the console lost {rel}"
    assert share.link_denied(rel) != "", f"{rel} can be handed to an outsider"


def test_the_link_fence_leaves_an_ordinary_document_alone() -> None:
    """It must narrow the carve and nothing else, or it is a second deny-list."""
    for rel in ("README.md", "docs/GUIDE.md", "docs/architecture/ENGINE_END_TO_END.html"):
        assert share.link_denied(rel) == "", f"{rel} stopped being linkable"


def test_the_link_fence_still_names_the_deny_pattern() -> None:
    """A refusal with no reason is the kind of message that gets a fence removed.

    `link_denied` answers the narrower question and must not lose the wider answer on the way:
    when the deny-list is what refused, the operator still gets the pattern back.
    """
    assert share.link_denied(".env") == share.is_denied(".env") != ""
    assert share.link_denied("store/dossiers/acme.md") == "store/*"


def test_mint_refuses_a_generated_document(repo: Path, ops: Path) -> None:
    """Minting IS the act of putting a path behind a sessionless link."""
    with pytest.raises(ValueError):
        share.mint(ops, repo, scope="file", target="store/scheduler/ALERT.txt")
    with pytest.raises(ValueError):
        share.mint(ops, repo, scope="tree", target="store/scheduler")
    # And the ordinary document beside it still mints, or the fence has eaten the feature.
    assert share.mint(ops, repo, scope="file", target="docs/GUIDE.md")["token"]


def test_a_repo_link_never_lists_a_generated_document(repo: Path, ops: Path) -> None:
    """The index is recomputed on every read, so this is the path a whole-repo link takes."""
    out = share.mint(ops, repo, scope="repo", target="")
    index = share.open_share(ops, repo, out["token"])
    assert "docs/GUIDE.md" in index["files"]
    assert "store/scheduler/ALERT.txt" not in index["files"]


def test_a_repo_link_cannot_read_a_generated_document_by_name(repo: Path, ops: Path) -> None:
    """Not listing it is presentation. Refusing to serve it is the fence."""
    out = share.mint(ops, repo, scope="repo", target="")
    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"], "store/scheduler/ALERT.txt")


def test_the_mint_picker_never_offers_what_mint_refuses(repo: Path) -> None:
    """The picker and the action must agree, always.

    `_read_repo_files` in `console_api.py` is what the operator picks a target from. It used to
    call `shareable_files`, which answers the wider console question, so the carve would have put
    files in that picker that `mint` then refused -- a list that lies, which is the founder's
    "the whole thing isnt user friendly" in a new place.
    """
    linkable = share.linkable_files(repo)
    shareable = share.shareable_files(repo)
    assert set(linkable) <= set(shareable), "linkable_files invented a file"
    assert not [f for f in linkable if share.link_denied(f)], "the picker offers a refused file"
    assert "docs/GUIDE.md" in linkable
    assert "store/scheduler/ALERT.txt" in shareable
    assert "store/scheduler/ALERT.txt" not in linkable


# --------------------------------------------------------------------------- #
# The guard for the next generator nobody has written yet
# --------------------------------------------------------------------------- #
#: Document-shaped paths under `store/` that are NOT portal documents, each with the reason it
#: is exempt. The point of the list is that it is short and that adding to it is a decision
#: somebody has to type, rather than a silent miss in a scan.
NOT_A_PORTAL_DOCUMENT = {
    # A golden fixture a test compares against, copied by hand (`specs/multi-market-dimension.md`
    # line 159) and deliberately tracked (`scripts/ops_status.py::STORE_KEEP`). Nothing generates
    # it at runtime, and a test input is not something the founder asked to read in the portal.
    "store/markets/_baseline/golden-pre-market.txt": "tracked golden test input, not engine output",
    # The three launch proofs. They were in the first cut of the carve and are deliberately out
    # of it: they are not written at runtime (generated once in June and committed), they are
    # TRACKED so `.dockerignore` keeps them out of the image while `git ls-files` still lists
    # them on a laptop, and `test-card-proof.md:40` carries a live grant token -- a bearer
    # credential for `/orders/{token}`. Reasons in full at `share.GENERATED_DOC_DIRS`.
    "store/launch/checkout-proof.md": "committed launch proof, not in the image, not runtime output",
    "store/launch/test-card-proof.md": "committed launch proof; line 40 carries a live grant token",
    "store/launch/storefront-proof.md": "committed launch proof, not in the image, not runtime output",
}


def test_no_document_path_in_the_source_is_one_the_portal_cannot_show() -> None:
    """Scan the source for document paths under `store/` and check the fence allows each one.

    This is the guard for the defect itself: someone adds a third generator, points it at a
    directory nobody carved, and the founder discovers months later that his document is not in
    the portal. Here it fails on the commit that adds it.

    It is a source scan and it is honest about that. It finds LITERAL paths, so a writer that
    assembles its path at runtime is invisible to it, and it finds references as well as writes,
    which is why the exemption list above exists. What it catches is the shape both known writers
    use, which is the shape the third will use too.
    """
    literal = re.compile(r"""["'](store/[A-Za-z0-9_\-./]+\.(?:md|html?|txt))["']""", re.IGNORECASE)
    offenders: list[str] = []
    for py in repo_files("*.py"):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("tests/"):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for hit in literal.findall(text):
            if hit not in NOT_A_PORTAL_DOCUMENT and share.is_denied(hit):
                offenders.append(f"{rel} names {hit}")
    assert not offenders, (
        "a document is written where the portal can never show it. Put it under one of "
        f"{share.GENERATED_DOC_DIRS}, or carve its directory in prospector/ops/share.py, or add "
        "it to NOT_A_PORTAL_DOCUMENT above with the reason: " + "; ".join(sorted(offenders))
    )


def test_no_exemption_outlives_the_reason_for_it() -> None:
    """An exemption list rots into a way of passing. Each entry must still be refused today.

    If the fence starts allowing one of these, the entry suppresses nothing and is a lie about
    why the scan is quiet.
    """
    stale = [
        rel for rel in NOT_A_PORTAL_DOCUMENT if share.is_denied(rel) == ""
    ]
    assert not stale, (
        "the portal can show these now, so delete their NOT_A_PORTAL_DOCUMENT entries: "
        + ", ".join(sorted(stale))
    )

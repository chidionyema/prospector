"""The docs read view turns an HTTP query string into a filesystem path.

That is the first read view in the console to do so, and it is the whole reason this file exists.
Everything else here — the index, the title extraction, the truncation — is convenience. The
containment tests are the product.

The founder asked twice on 2026-08-19 whether docs were reachable from ops. Shipping "yes" in an
afternoon is only acceptable if the door it opens is the one we meant to open.

2026-08-21: the index root widened from `docs/` to the whole repo, because 185 of 298 documents
were invisible from the console. Containment alone no longer makes that safe — `.env` sits inside
the repo — so `share.is_denied` is the second half of the door and is exercised here. Document
names are now repo-relative (`docs/GUIDE.md`); the old docs-relative form still resolves, and
that is a test rather than a footnote because every link minted before that date uses it.
"""
from __future__ import annotations

import pytest

from prospector.ops.docs_view import doc_view, docs_index


@pytest.fixture()
def repo(tmp_path):
    """A miniature repo: a docs tree, and a secret beside it that must stay unreachable."""
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "docs" / "incidents").mkdir(parents=True)
    (tmp_path / "docs" / "GUIDE.md").write_text("# The Guide\n\nbody text\n")
    (tmp_path / "docs" / "decisions" / "0001-a.md").write_text("# Decision one\n\nchose a thing\n")
    (tmp_path / "docs" / "incidents" / "INC-1.json").write_text('{"title": "something broke"}')
    (tmp_path / ".env").write_text("STRIPE_SECRET_KEY=sk_live_dont_read_me\n")
    return tmp_path


# --------------------------------------------------------------------------------------------
# Containment. Each of these is a way out of the tree that a string comparison would have missed.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("escape", [
    "../.env",
    "../../.env",
    "decisions/../../.env",
    "./../.env",
    "/etc/passwd",
    "../../../../../../etc/passwd",
])
def test_a_name_cannot_climb_out_of_docs(repo, escape):
    """`..` and absolute paths both resolve outside the root and must be refused.

    `/etc/passwd` matters as much as `../.env`: `root / "/etc/passwd"` in pathlib DISCARDS the
    root and yields the absolute path, so an absolute name is an escape even though it contains
    no `..` at all. The leading slash is stripped before joining for exactly this reason."""
    with pytest.raises(ValueError):
        doc_view(repo, escape)


def test_a_symlink_pointing_out_of_the_tree_is_refused(repo):
    """Resolution happens BEFORE the containment check, so a link cannot smuggle a path past it.
    A check on the raw string would pass this: the name has no `..` in it at all."""
    (repo / "docs" / "innocent.md").symlink_to(repo / ".env")
    with pytest.raises(ValueError):
        doc_view(repo, "innocent.md")


def test_a_key_file_under_docs_is_refused_by_the_deny_list(repo):
    """The share deny-list is the fence that makes a repo-wide root safe.

    Before 2026-08-21 this was refused by the suffix allow-list alone. It is now refused earlier
    and for a better reason — the same rule that refuses it a share link — and the message names
    the pattern, because "not readable" with no reason is what gets a fence deleted.
    """
    (repo / "docs" / "agent.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    with pytest.raises(ValueError, match=r"deny-list"):
        doc_view(repo, "docs/agent.pem")


def test_the_env_file_beside_docs_is_refused_even_though_it_is_inside_the_root(repo):
    """The whole point of the second fence. `.env` is contained by the repo root, so containment
    passes and only the deny-list stops it."""
    with pytest.raises(ValueError, match=r"deny-list"):
        doc_view(repo, ".env")


def test_only_document_formats_are_served(repo):
    """The suffix allow-list is the backstop for a file the deny-list does not know about."""
    (repo / "docs" / "binary.bin").write_text("nope")
    with pytest.raises(ValueError, match="readable here"):
        doc_view(repo, "docs/binary.bin")


def test_an_empty_or_null_name_is_refused_not_defaulted(repo):
    """A blank name must not quietly become "the first doc" or "the docs directory"."""
    for bad in ("", "   ", "\x00.md"):
        with pytest.raises(ValueError):
            doc_view(repo, bad)


def test_a_missing_doc_says_so_rather_than_returning_empty(repo):
    with pytest.raises(ValueError, match="does not exist"):
        doc_view(repo, "NOPE.md")


def test_a_link_minted_before_the_root_widened_still_opens(repo):
    """`?open=decisions/0001-a.md` is the form every link and bookmark carries from before
    2026-08-21, and the Incidents page still builds it. A bookmark that silently 404s is the same
    "built and unreachable" failure this module exists to fix."""
    legacy = doc_view(repo, "decisions/0001-a.md")
    current = doc_view(repo, "docs/decisions/0001-a.md")
    assert legacy["name"] == current["name"] == "docs/decisions/0001-a.md"


# --------------------------------------------------------------------------------------------
# The view itself
# --------------------------------------------------------------------------------------------

def test_the_index_groups_decisions_and_incidents_and_finds_every_doc(repo):
    idx = docs_index(repo)
    labels = [s["label"] for s in idx["sections"]]
    assert any("Decisions" in x for x in labels)
    assert any("Incidents" in x for x in labels)
    names = {d["name"] for s in idx["sections"] for d in s["docs"]}
    assert names == {"docs/GUIDE.md", "docs/decisions/0001-a.md", "docs/incidents/INC-1.json"}
    assert idx["count"] == 3


def test_a_doc_is_listed_under_its_own_heading_not_its_filename(repo):
    idx = docs_index(repo)
    titles = {d["name"]: d["title"] for s in idx["sections"] for d in s["docs"]}
    assert titles["docs/decisions/0001-a.md"] == "Decision one"
    # No `# heading` to find, so the path is the honest fallback rather than a dropped row.
    assert titles["docs/incidents/INC-1.json"] == "docs/incidents/INC-1.json"


def test_no_document_is_listed_twice(repo):
    """`decisions/` and `incidents/` are read before the unprefixed section, which reads the docs
    root. Without the `seen` set the root pass would list nothing extra here — but the moment a
    fourth section is added that overlaps, a doc would appear under two headings."""
    idx = docs_index(repo)
    names = [d["name"] for s in idx["sections"] for d in s["docs"]]
    assert len(names) == len(set(names))


def test_reading_a_doc_returns_its_text(repo):
    got = doc_view(repo, "docs/decisions/0001-a.md")
    assert got["title"] == "Decision one"
    assert "chose a thing" in got["text"]
    assert got["truncated"] is False


def test_a_long_doc_is_truncated_and_says_so(repo):
    """A silently shortened document is a document that lies. The flag is the point."""
    (repo / "docs" / "BIG.md").write_text("# Big\n" + ("x" * 5000))
    got = doc_view(repo, "docs/BIG.md", max_bytes=100)
    assert got["truncated"] is True
    assert len(got["text"]) <= 100
    assert got["bytes"] > 100


def test_a_checkout_with_no_documents_says_so_instead_of_raising(tmp_path):
    """The console renders whatever this returns. An exception here is a blank panel with no
    explanation, which is the failure mode the Note exists to avoid."""
    idx = docs_index(tmp_path)
    assert idx["sections"] == []
    assert idx["count"] == 0
    assert "no readable documents" in idx["note"]


def test_documents_outside_docs_are_indexed_and_grouped_by_their_tree(repo):
    """The 2026-08-21 requirement, at fixture scale: 146 of the 185 invisible documents were
    invisible for no reason other than sitting outside `docs/`."""
    (repo / "README.md").write_text("# The readme\n")
    (repo / "tools").mkdir()
    (repo / "tools" / "NOTES.md").write_text("# Tool notes\n")
    (repo / "docs" / "design").mkdir()
    (repo / "docs" / "design" / "page.html").write_text("<title>A mockup</title>")

    idx = docs_index(repo)
    entries = {d["name"]: d for s in idx["sections"] for d in s["docs"]}
    assert "README.md" in entries
    assert "tools/NOTES.md" in entries
    assert "docs/design/page.html" in entries
    assert entries["README.md"]["category"] == "Repo root"
    assert entries["tools/NOTES.md"]["category"] == "tools"
    assert entries["docs/design/page.html"]["category"] == "docs/design"
    # An HTML document is listed under its own <title>, not its path.
    assert entries["docs/design/page.html"]["title"] == "A mockup"


def test_a_binary_document_is_listed_but_not_rendered(repo):
    """Listed, because a silent exception is the defect this rewrite closes. Not rendered,
    because dumping bytes into a browser is a download surface rather than a page."""
    (repo / "docs" / "spec.pdf").write_bytes(b"%PDF-1.4\n%binary\n")
    idx = docs_index(repo)
    entries = {d["name"]: d for s in idx["sections"] for d in s["docs"]}
    assert "docs/spec.pdf" in entries
    assert entries["docs/spec.pdf"]["readable"] is False
    assert entries["docs/GUIDE.md"]["readable"] is True

"""The share fence.

This module hands repository files to people with no account, so the tests here are the fence
rather than a description of it. They are written to fail on the ways a share endpoint actually
leaks: a path that escapes the root, a credential file named directly, a token that outlives its
expiry, a scope that does not hold, and an index that quietly includes something the file view
would have refused.

Every refusal is asserted by BEHAVIOUR, never by reading the deny-list back. A test that asserts
`".env" in DENY_GLOBS` passes when the list is right and also passes when the matcher that reads
the list is broken, which is the shape of guard this estate has been bitten by before.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from prospector.ops import share


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A tiny repo with one of everything the fence has an opinion about."""
    root = tmp_path / "repo"
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / "prospector").mkdir()
    (root / ".lux" / "keys").mkdir(parents=True)
    (root / "store").mkdir()

    (root / "README.md").write_text("# readme\n")
    (root / "docs" / "GUIDE.md").write_text("# guide\n")
    (root / "docs" / "decisions" / "0002.md").write_text("# adr\n")
    (root / "prospector" / "run.py").write_text("x = 1\n")
    (root / ".env").write_text("SECRET_TOKEN=hunter2\n")
    (root / ".lux" / "keys" / "agent.pem").write_text("PRIVATE KEY MATERIAL\n")
    (root / "store" / "prospector.jsonl").write_text('{"cost": 1}\n')
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    return root


@pytest.fixture()
def ops(tmp_path: Path) -> Path:
    d = tmp_path / "store-ops"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- #
# The deny-list, by behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", [
    ".env",
    ".env.local",
    ".env.production",
    "deploy/.env",
    ".lux/keys/agent.pem",
    "certs/server.key",
    "store/prospector.jsonl",
    "store/dossiers/abc/def.json",
    "storage/anything",
    "node_modules/left-pad/index.js",
    "store_platform/src/Ops.Console/node_modules/x/y.js",
    ".git/config",
    ".venv/bin/python",
    "graphify-out/graph.json",
    "prospector.db",
    "keys/id_rsa",
    "config/secrets.yaml",
])
def test_a_secret_or_state_path_is_never_shareable(rel):
    """The named path must be refused, and the refusal must SAY which rule refused it.

    Two assertions rather than one, because a matcher that returns a truthy constant would pass
    the first on its own.
    """
    reason = share.is_denied(rel)
    assert reason, f"{rel} was shareable"
    assert reason in share.DENY_GLOBS or reason == "not a path"


@pytest.mark.parametrize("rel", [
    "README.md",
    "docs/GUIDE.md",
    "docs/decisions/0002-engine-runtime-and-engineering-standards.md",
    "prospector/run.py",
    "store_platform/src/Ops.Console/src/pages/index.tsx",
    "config.yaml",
    ".github/workflows/ci.yml",
])
def test_ordinary_repo_files_stay_shareable(rel):
    """The fence must not be so wide it eats the feature. `config.yaml` in particular: it is the
    engine's whole configuration and is exactly what an external reviewer needs to read."""
    assert share.is_denied(rel) == "", f"{rel} was refused"


def test_the_listing_never_contains_a_denied_path(repo):
    """The index and the file view must agree. An index that lists something the file view then
    refuses is how an operator learns a fence exists by tripping over it, and an index that lists
    something the file view would SERVE is the leak itself."""
    files = share.shareable_files(repo)
    assert "README.md" in files and "docs/GUIDE.md" in files
    for bad in (".env", ".lux/keys/agent.pem", "store/prospector.jsonl"):
        assert bad not in files, f"{bad} was listed"
    assert all(share.is_denied(f) == "" for f in files)


def test_the_walk_is_used_when_git_cannot_answer(repo):
    """In the engine image `.git/` is excluded by `.dockerignore`, so this IS production.

    The fixture repo has no `.git`, so it exercises the same path the container does.
    """
    assert share.allow_list_source(repo) == "tree walk + deny-list"
    assert "README.md" in share.shareable_files(repo)


# --------------------------------------------------------------------------- #
# Minting
# --------------------------------------------------------------------------- #
def test_a_mint_returns_the_token_once_and_stores_only_its_hash(ops, repo):
    out = share.mint(ops, repo, scope="file", target="README.md", days=1)
    token = out["token"]
    assert token and out["path"] == f"/s/{token}"

    on_disk = json.loads((ops / "shares.json").read_text())["shares"]
    assert len(on_disk) == 1
    row = on_disk[0]
    assert token not in json.dumps(row), "the raw token was written to disk"
    assert row["token_sha256"] and row["token_sha256"] != token

    listed = share.list_shares(ops)["shares"]
    assert all("token_sha256" not in r and "token" not in r for r in listed), \
        "the console listing carried key material"


@pytest.mark.parametrize("target", [".env", ".lux/keys/agent.pem", "store/prospector.jsonl"])
def test_a_secret_cannot_be_minted_even_when_named_directly(ops, repo, target):
    """The read-time check would also catch this. Refusing at mint time is what gives the
    operator an error they can act on instead of a link that silently never works."""
    with pytest.raises(ValueError) as exc:
        share.mint(ops, repo, scope="file", target=target)
    assert "never be shared" in str(exc.value)


@pytest.mark.parametrize("days", [0, -1, 100, 10_000])
def test_an_expiry_outside_the_bounds_is_refused(ops, repo, days):
    """No unbounded link. A link with no expiry is a credential nobody remembers issuing."""
    with pytest.raises(ValueError):
        share.mint(ops, repo, scope="file", target="README.md", days=days)


def test_a_share_of_a_directory_that_is_not_there_is_refused(ops, repo):
    with pytest.raises(ValueError):
        share.mint(ops, repo, scope="tree", target="docs/nope")
    with pytest.raises(ValueError):
        share.mint(ops, repo, scope="file", target="docs")


# --------------------------------------------------------------------------- #
# Serving
# --------------------------------------------------------------------------- #
def test_a_file_link_serves_that_file_and_nothing_else(ops, repo):
    out = share.mint(ops, repo, scope="file", target="docs/GUIDE.md")
    got = share.open_share(ops, repo, out["token"])
    assert got["kind"] == "file" and got["name"] == "docs/GUIDE.md"
    assert got["text"] == "# guide\n"

    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"], "README.md")


def test_a_tree_link_covers_everything_below_it_and_stops_at_the_edge(ops, repo):
    """The seamless half. One link, and the reader navigates."""
    out = share.mint(ops, repo, scope="tree", target="docs")
    index = share.open_share(ops, repo, out["token"])
    assert index["kind"] == "index"
    assert set(index["files"]) == {"docs/GUIDE.md", "docs/decisions/0002.md"}

    assert share.open_share(ops, repo, out["token"], "docs/decisions/0002.md")["text"] == "# adr\n"
    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"], "README.md")


def test_a_repo_link_lists_everything_shareable_and_no_secret(ops, repo):
    out = share.mint(ops, repo, scope="repo", target="")
    index = share.open_share(ops, repo, out["token"])
    assert "README.md" in index["files"] and "prospector/run.py" in index["files"]
    assert ".env" not in index["files"]
    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"], ".env")


@pytest.mark.parametrize("escape", [
    "../outside.txt",
    "../../etc/passwd",
    "docs/../../etc/passwd",
    "/etc/passwd",
    "./../.env",
])
def test_a_path_that_escapes_the_repo_is_refused(ops, repo, escape, tmp_path):
    """`root / "/etc/passwd"` in pathlib DISCARDS the root and yields the absolute path, so an
    absolute name is an escape even though it contains no `..` at all. That is why containment is
    checked after resolution rather than by looking for `..` in the string."""
    (tmp_path / "outside.txt").write_text("not yours\n")
    out = share.mint(ops, repo, scope="repo", target="")
    with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
        share.open_share(ops, repo, out["token"], escape)


def test_a_symlink_pointing_out_of_the_repo_is_refused(ops, repo, tmp_path):
    """A string check on `..` passes this. Resolution first is what catches it."""
    (tmp_path / "outside.txt").write_text("not yours\n")
    (repo / "docs" / "sneaky.md").symlink_to(tmp_path / "outside.txt")
    out = share.mint(ops, repo, scope="repo", target="")
    with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
        share.open_share(ops, repo, out["token"], "docs/sneaky.md")


def test_an_expired_link_stops_working(ops, repo, monkeypatch):
    out = share.mint(ops, repo, scope="file", target="README.md", days=1)
    assert share.open_share(ops, repo, out["token"])["kind"] == "file"

    monkeypatch.setattr(share, "_now", lambda: time.time() + 2 * 86_400)
    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"])


def test_a_revoked_link_stops_working_immediately(ops, repo):
    out = share.mint(ops, repo, scope="file", target="README.md")
    assert share.open_share(ops, repo, out["token"])["kind"] == "file"

    share.revoke(ops, out["id"])
    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"])

    again = share.revoke(ops, out["id"])
    assert again["already"] is True, "revoking twice must be safe, not an error the operator sees"


def test_an_unknown_token_and_a_revoked_token_look_identical_from_outside(ops, repo):
    """Otherwise the endpoint is a way to test guesses: 'revoked' tells an attacker the token was
    real."""
    out = share.mint(ops, repo, scope="file", target="README.md")
    share.revoke(ops, out["id"])

    with pytest.raises(PermissionError) as revoked:
        share.open_share(ops, repo, out["token"])
    with pytest.raises(PermissionError) as unknown:
        share.open_share(ops, repo, "a-token-that-was-never-minted")
    assert str(revoked.value) == str(unknown.value)


def test_a_file_that_becomes_a_secret_after_the_link_was_minted_is_refused(ops, repo):
    """The read-time check is why this exists. A link handed out last week must not survive the
    day a credential lands under a path that was ordinary when it was minted."""
    out = share.mint(ops, repo, scope="tree", target="docs")
    (repo / "docs" / "prod.env").write_text("SECRET=1\n")

    with pytest.raises(PermissionError):
        share.open_share(ops, repo, out["token"], "docs/prod.env")
    assert "docs/prod.env" not in share.open_share(ops, repo, out["token"])["files"]


def test_a_binary_file_is_listed_and_not_rendered(ops, repo):
    """A share view that dumps bytes into a browser is a download surface."""
    out = share.mint(ops, repo, scope="file", target="logo.png")
    got = share.open_share(ops, repo, out["token"])
    assert got["kind"] == "binary" and "text" not in got
    assert got["bytes"] > 0


def test_every_anonymous_read_leaves_a_trail(ops, repo):
    """"What did they actually see?" is the first question asked after a link goes out."""
    out = share.mint(ops, repo, scope="tree", target="docs")
    share.open_share(ops, repo, out["token"], viewer="1.2.3.4")
    share.open_share(ops, repo, out["token"], "docs/GUIDE.md", viewer="1.2.3.4")

    lines = [json.loads(x) for x in (ops / "share_reads.jsonl").read_text().splitlines()]
    assert [line["path"] for line in lines] == ["(index)", "docs/GUIDE.md"]
    assert all(line["viewer"] == "1.2.3.4" for line in lines)

    row = [r for r in share.list_shares(ops)["shares"] if r["id"] == out["id"]][0]
    assert row["reads"] == 2 and row["last_read_at"]


# ---------------------------------------------------------------------------
# The repo view, and the claim that it keeps itself current
#
# The founder asked for "a final doc with a view of all files in repo, and think auto updating
# also". There is no document. The index IS the view, and it is recomputed from the working tree
# on every read, which is a stronger promise than a generated file with a refresh job behind it:
# there is no job to stop and no artefact to go stale.
#
# That property is worth exactly as much as the test that proves it, so it is asserted below by
# adding and deleting files AFTER the link was minted, not described in a docstring.
# ---------------------------------------------------------------------------


def test_the_repo_view_groups_files_by_folder_with_sizes(ops, repo):
    """A flat list of every path is a wall, not a view. Folders, counts and bytes are what make it
    readable by someone who has never seen the tree."""
    minted = share.mint(ops, repo, scope="repo", target="", days=7, note="", actor="t")
    view = share.open_share(ops, repo, minted["token"])

    assert view["kind"] == "index"
    paths = [f["path"] for f in view["folders"]]
    assert paths == sorted(paths), "folders are ordered, so the same repo reads the same way twice"
    assert "docs" in paths and "docs/decisions" in paths

    docs = next(f for f in view["folders"] if f["path"] == "docs")
    assert docs["count"] == 1
    assert docs["files"][0]["label"] == "GUIDE.md"
    assert docs["files"][0]["name"] == "docs/GUIDE.md"
    assert docs["bytes"] > 0

    # The totals are the sum of what is shown, not a second, independently-computed number that
    # could disagree with the list under it.
    assert view["total_bytes"] == sum(f["bytes"] for f in view["folders"])
    assert view["count"] == sum(f["count"] for f in view["folders"])
    assert view["source"] in ("git ls-files", "tree walk + deny-list")


def test_the_repo_view_still_hides_secrets_when_grouped(ops, repo):
    """The grouping is a rendering of `shareable_files`, so it inherits the deny-list. This exists
    because a second code path that lists files is a second place a credential can escape."""
    minted = share.mint(ops, repo, scope="repo", target="", days=7, note="", actor="t")
    view = share.open_share(ops, repo, minted["token"])

    shown = [f["name"] for folder in view["folders"] for f in folder["files"]]
    assert shown, "the view is not empty, so the assertions below mean something"
    assert ".env" not in shown
    assert ".lux/keys/agent.pem" not in shown
    assert not [s for s in shown if s.startswith("store/")]
    assert set(shown) == set(view["files"])


def test_the_view_reflects_the_tree_at_read_time_not_at_mint_time(ops, repo):
    """THE AUTO-UPDATING CLAIM, ASSERTED.

    A file written after the link was minted appears on the next read, and a file deleted after
    the link was minted disappears. If this ever fails, the page has become a snapshot and the
    founder is handing out a document that quietly rots.
    """
    minted = share.mint(ops, repo, scope="repo", target="", days=7, note="", actor="t")
    before = share.open_share(ops, repo, minted["token"])
    assert "docs/NEW.md" not in before["files"]

    (repo / "docs" / "NEW.md").write_text("written after the link was handed over\n")
    after = share.open_share(ops, repo, minted["token"])
    assert "docs/NEW.md" in after["files"]
    assert after["count"] == before["count"] + 1
    assert "NEW.md" in [
        f["label"] for folder in after["folders"] if folder["path"] == "docs" for f in folder["files"]
    ]

    (repo / "docs" / "NEW.md").unlink()
    (repo / "docs" / "GUIDE.md").unlink()
    gone = share.open_share(ops, repo, minted["token"])
    assert "docs/GUIDE.md" not in gone["files"]
    assert gone["count"] == before["count"] - 1


def test_a_file_that_vanishes_mid_read_is_skipped_not_fatal(ops, repo, monkeypatch):
    """This runs against a live working tree while builds and checkouts move files. A view that
    500s because one path disappeared between the listing and the stat would be down exactly when
    the repo is busiest."""
    monkeypatch.setattr(
        share, "shareable_files", lambda root: ["README.md", "docs/GHOST.md"]
    )
    minted = share.mint(ops, repo, scope="repo", target="", days=7, note="", actor="t")
    view = share.open_share(ops, repo, minted["token"])
    shown = [f["name"] for folder in view["folders"] for f in folder["files"]]
    assert shown == ["README.md"]


def test_the_revision_is_empty_rather_than_invented_when_git_cannot_answer(ops, repo):
    """The tmp repo has no `.git`, which is also the state inside the engine image. An empty
    revision is honest; a made-up stamp would be a version number that means nothing."""
    minted = share.mint(ops, repo, scope="repo", target="", days=7, note="", actor="t")
    view = share.open_share(ops, repo, minted["token"])
    assert view["revision"] == ""
    assert view["generated_at"] > 0

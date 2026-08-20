"""The agent-estate packer, proved on the state that actually exists on disk.

WHAT THIS IS GUARDING (measured 2026-08-20)
-------------------------------------------
`~/.claude` had no backup at all, and the reason it is not simply tarred is that the allow-listed
part of it held two credentials nobody put there on purpose:

  * a private key in `projects/-Users-chidionyema/checkpoints/prod-jwt-2026-08-01.pem`
  * a 93-character GitHub token in the founder-directive archive, pasted into chat once

A backup that ships those to object storage has turned a missing second copy into a second copy
of the secrets. `~/.hermes/.gitignore` records what happens when the control is a list of
filename patterns instead: 26 live keys reached a GitHub remote through it.

The decisive test below is `test_the_secret_is_absent_from_the_archive_bytes`. Everything else
grades the manifest, and a manifest is a claim about the archive, not the archive.
"""

from __future__ import annotations

import importlib.util
import json
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "backup_agent_estate", REPO / "scripts" / "backup_agent_estate.py")
packer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(packer)

# Assembled from fragments so this file is not itself a credential the scan would flag.
FAKE_TOKEN = "github_pat_" + "1A" * 30
FAKE_KEY_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ" + "C" * 40


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """A miniature ~/.claude with one of everything that matters."""
    home = tmp_path / "home"
    root = home / ".claude"
    (root / "projects" / "proj" / "memory").mkdir(parents=True)
    (root / "projects" / "proj" / "checkpoints").mkdir(parents=True)
    (root / "scripts").mkdir()

    (root / "CLAUDE.md").write_text("how to work here\n", encoding="utf-8")
    (root / "projects" / "proj" / "memory" / "a-trap.md").write_text("a trap\n", encoding="utf-8")
    (root / "projects" / "proj" / "checkpoints" / "prod.pem").write_text(
        f"-----BEGIN PRIVATE KEY-----\n{FAKE_KEY_BODY}\n-----END PRIVATE KEY-----\n",
        encoding="utf-8")
    (root / "directives" ).mkdir()
    (root / "directives" / "chat.jsonl").write_text(
        '{"text": "here is the token ' + FAKE_TOKEN + ' use it"}\n', encoding="utf-8")

    # The 5.9 GB that must never be selected: session transcripts, telemetry, caches.
    (root / "projects" / "proj" / "session-abc.jsonl").write_text("x" * 5000, encoding="utf-8")
    (root / "telemetry").mkdir()
    (root / "telemetry" / "big.log").write_text("y" * 5000, encoding="utf-8")

    monkeypatch.setattr(packer, "HOME", home)
    monkeypatch.setattr(packer, "ESTATE", root)
    return root


# --- the allow-list ---------------------------------------------------------------------------


def test_the_transcripts_and_telemetry_are_never_selected(estate):
    selected = {str(p.relative_to(estate)) for p in packer.selected_files(estate)}
    assert "CLAUDE.md" in selected
    assert "projects/proj/memory/a-trap.md" in selected
    assert not [s for s in selected if s.startswith("telemetry/")]
    assert "projects/proj/session-abc.jsonl" not in selected, (
        "session transcripts are 5.9 GB and rebuild nothing; the allow-list must not reach them"
    )


def test_a_symlink_out_of_the_estate_is_not_followed(estate, tmp_path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("not ours\n", encoding="utf-8")
    (estate / "scripts" / "escape.txt").symlink_to(outside)

    selected = packer.selected_files(estate)
    assert not [p for p in selected if p.name == "escape.txt"], (
        "an allow-list that follows links out of the estate is not an allow-list"
    )


def test_an_allow_listed_root_that_is_itself_a_link_is_skipped(estate, tmp_path):
    """Two symlink checks, and they guard different things.

    This one is the ROOT: `skills` replaced by a link to somewhere else on the disk. The check
    inside the walk only ever sees paths below a root it already accepted, so it cannot catch
    this, and a test that only covers the inner one reports green while the outer is deleted.
    """
    elsewhere = tmp_path / "not-the-estate"
    (elsewhere / "deep").mkdir(parents=True)
    (elsewhere / "deep" / "private.txt").write_text("not ours\n", encoding="utf-8")
    (estate / "skills").symlink_to(elsewhere)

    selected = packer.selected_files(estate)
    assert not [p for p in selected if "private.txt" in p.name]


def test_a_kept_file_comes_back_byte_identical(estate, tmp_path):
    """The restore claim. A backup nobody has opened is a belief, not a backup.

    Extracting into a fresh home must reproduce the estate's own layout, so the documented restore
    is `tar -xzf claude.tgz -C ~` and nothing else.
    """
    out = tmp_path / "estate.tgz"
    packer.build(out)
    restored = tmp_path / "restored-home"
    restored.mkdir()
    with tarfile.open(out, "r:gz") as tar:
        tar.extractall(restored, filter="data")

    for rel in ("CLAUDE.md", "projects/proj/memory/a-trap.md"):
        original = estate / rel
        copy = restored / ".claude" / rel
        assert copy.exists(), f"{rel} did not survive the round trip"
        assert copy.read_bytes() == original.read_bytes()


# --- the two controls -------------------------------------------------------------------------


def test_key_material_is_excluded_whole(estate):
    manifest = packer.build(None)
    excluded = {item["path"] for item in manifest["excluded"]}
    assert any(p.endswith("prod.pem") for p in excluded)
    assert not [r for r in manifest["redacted"] if r["path"].endswith("prod.pem")], (
        "redacting the BEGIN line out of a .pem leaves the key body behind"
    )


def test_an_embedded_credential_is_redacted_not_dropped(estate):
    manifest = packer.build(None)
    redacted = {item["path"]: item for item in manifest["redacted"]}
    hit = next(v for k, v in redacted.items() if k.endswith("chat.jsonl"))
    assert hit["hits"][0]["shape"] == "github-token"
    assert not [e for e in manifest["excluded"] if e["path"].endswith("chat.jsonl")], (
        "the directive archive is 5.8 MB of founder history; one pasted token must not cost it"
    )


def test_the_secret_is_absent_from_the_archive_bytes(estate, tmp_path):
    """The only test here that grades the archive rather than the claim about it."""
    out = tmp_path / "estate.tgz"
    packer.build(out)

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        blob = b"".join(
            tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()
        )

    assert FAKE_TOKEN.encode() not in blob, "the token reached the archive"
    assert FAKE_KEY_BODY.encode() not in blob, "the private key reached the archive"
    assert not [n for n in names if n.endswith("prod.pem")]
    assert any(n.endswith("CLAUDE.md") for n in names), "the archive is empty of real content"


def test_the_manifest_records_both_and_carries_no_value(estate, tmp_path):
    out = tmp_path / "estate.tgz"
    packer.build(out)
    with tarfile.open(out, "r:gz") as tar:
        manifest = json.loads(tar.extractfile(packer.MANIFEST_NAME).read())

    assert manifest["excluded"] and manifest["redacted"]
    text = json.dumps(manifest)
    assert FAKE_TOKEN not in text and FAKE_KEY_BODY not in text, (
        "a manifest that quotes the secret has moved it, not removed it"
    )
    for entry in manifest["redacted"]:
        for hit in entry["hits"]:
            assert set(hit) == {"shape", "line", "chars"}


def test_a_redaction_marker_does_not_leak_a_prefix_or_a_length(estate):
    text, hits = packer.redact(f"key={FAKE_TOKEN} end")
    assert hits and FAKE_TOKEN not in text
    assert "github_pat_" not in text, "a preserved prefix narrows a brute force"
    assert len(text) != len(f"key={FAKE_TOKEN} end"), "a length-preserving mask leaks the length"


# --- against the estate that actually exists ----------------------------------------------------


@pytest.mark.skipif(not (Path.home() / ".claude").is_dir(),
                    reason="no agent estate on this host (a CI runner)")
def test_the_real_estate_yields_files_and_nothing_outside_it():
    """Anti-vacuity. A packer that selects nothing passes every control test above.

    No count is asserted: the estate grows every day, and a test that pins today's number is a
    test that fails for being right.
    """
    root = Path.home() / ".claude"
    selected = packer.selected_files(root)
    assert selected, "the allow-list matched nothing in the real estate"
    for path in selected:
        assert root in path.parents or path.parent == root

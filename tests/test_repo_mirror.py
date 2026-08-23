"""The git mirror must end up being a usable off-site copy, not just a green upload.

The repo has exactly one remote (GitHub). A bundle upload to the same nightly R2 backup
job makes the off-site copy ride the path that already runs, with the credentials that
already work — so the cost of the safety net is one extra `git bundle create` per night,
not a second scheduled job that can rot on its own.

WHY THESE TESTS DRIVE REAL GIT. They used to patch `subprocess.run` with a fake that
answered whatever the test wired in, and that is exactly how the defect of 2026-08-18
survived five nights. The fake said the bundle verified because the test told it to. Only
git can say whether git can read a file, so `REPO_ROOT` is pointed at a real throwaway
repository and every git call in `mirror_repo` runs for real. S3 is still a fake, because
the bucket is not what these tests are about.

What can go wrong, and the test that holds the line
---------------------------------------------------
- The source is a SHALLOW clone: every bundle it produces is unrestorable and nothing
  downstream can tell. `mirror_repo` refuses before taking one.
- The bundle is damaged in a way `git bundle create` did not catch: the pre-flight clone
  catches it, and the upload never happens. `git bundle verify` does NOT catch it, and
  one of the tests below measures that directly.
- The upload reaches R2 but the read-back disagrees with the local file: a green upload is
  not a green backup. `mirror_repo` raises, hard.
- Pruning runs on the wrong day: only the newest `keep` survive, and only after the read-
  back passed.

The live end-to-end proof is `ops/automations/restore_drill.py` against the real bucket,
not here.
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
import backup_store as bs  # noqa: E402


class FakeS3:
    """Records every call so tests can assert on shape, not on byte equality."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    def upload_file(self, filename, Bucket, Key, ExtraArgs=None):  # noqa: N803
        self.upload_calls.append((filename, Key))
        self.objects[Key] = Path(filename).read_bytes()

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.delete_calls.append(Key)
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=1000, ContinuationToken=None):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k, "ETag": '"x"'} for k in keys], "IsTruncated": False}


#: Identity for the throwaway repositories. A CI runner has no global git identity, so a
#: commit without these fails with "Please tell me who you are" and the test blames the
#: code under test for a missing config file.
_IDENT = [
    "-c", "user.email=drill@example.invalid",
    "-c", "user.name=Drill",
    "-c", "commit.gpgsign=false",
]


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *_IDENT, *args], cwd=cwd, capture_output=True, text=True, check=True,
    )


def _repo_with_history(root: Path, commits: int = 3) -> Path:
    """A real git repository with a real branch and `commits` real commits."""
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "--quiet", "--initial-branch=main", ".", cwd=root)
    for i in range(commits):
        (root / f"f{i}.txt").write_text(f"line {i}\n")
        _git("add", f"f{i}.txt", cwd=root)
        _git("commit", "--quiet", "-m", f"commit {i}", cwd=root)
    return root


@pytest.fixture
def real_repo(tmp_path, monkeypatch) -> Path:
    """Point `mirror_repo` at a real, complete repository."""
    root = _repo_with_history(tmp_path / "source")
    monkeypatch.setattr(bs, "REPO_ROOT", root)
    return root


# ── Pre-flight: the source itself must be restorable ─────────────────────────
def test_incident_a_shallow_source_is_refused_before_a_bundle_is_taken(tmp_path, monkeypatch):
    """Incident 2026-08-18: five nights of bundles that no clone could read.

    `prospector-live` became a shallow clone on 2026-08-18 16:56 and the nightly mirror
    kept running from it. `git bundle create --all` walks to the graft boundary and stops.
    It declares no prerequisites, because as far as it knows the boundary commits are
    roots, so the bundle looks self-contained — and `git fsck` on the source stays green
    the whole time, correctly, because a shallow repository IS internally consistent. The
    damage exists only in the consumer.

    This asserts the rule, not the message: a shallow source produces no upload at all.
    """
    origin = _repo_with_history(tmp_path / "origin", commits=4)
    shallow = tmp_path / "shallow"
    _git("clone", "--quiet", "--depth", "1", f"file://{origin}", str(shallow), cwd=tmp_path)
    assert (shallow / ".git" / "shallow").exists(), "the fixture must actually be shallow"

    monkeypatch.setattr(bs, "REPO_ROOT", shallow)
    s3 = FakeS3()

    with pytest.raises(RuntimeError, match="shallow"):
        bs.mirror_repo(s3, "bucket")

    assert s3.upload_calls == [], "a shallow source must not produce an upload"
    assert s3.objects == {}, "and the bucket must be left holding only the older good copies"


def test_incident_a_damaged_bundle_is_never_uploaded_though_bundle_verify_accepts_it(
    real_repo, tmp_path, monkeypatch,
):
    """Incident 2026-08-18, second half: the guard that passed fourteen broken backups.

    The old pre-flight was `git bundle verify`. It reads the bundle header and asks whether
    THIS repository already holds the prerequisites the header names; it never reads the
    pack. The two assertions below are the whole finding, measured rather than described:
    verify exits 0 on a bundle truncated to 300 bytes, and a clone of that same file fails.

    A guard that passes a broken backup is worse than no guard, because it makes the backup
    look drilled.
    """
    real_run = subprocess.run

    def truncating_run(args, **kwargs):
        """Real git throughout, except the bundle is damaged the moment it is written.

        Truncation stands in for every way a bundle can be unreadable — a short write, a
        full disk, the shallow graft boundary. What matters is that git is the one asked.
        """
        result = real_run(args, **kwargs)
        if isinstance(args, list) and args[:3] == ["git", "bundle", "create"]:
            path = Path(args[3])
            if path.exists():
                with open(path, "r+b") as fh:
                    fh.truncate(300)
        return result

    monkeypatch.setattr(bs.subprocess, "run", truncating_run)
    s3 = FakeS3()

    with pytest.raises(RuntimeError, match="cannot be cloned|zero refs"):
        bs.mirror_repo(s3, "bucket")

    assert s3.upload_calls == [], "an unrestorable bundle must not be uploaded"
    assert s3.objects == {}, "and the fake bucket must therefore be empty"

    # The other half of the finding: the guard this replaced would have waved that file
    # through. Rebuild the same damaged bundle and ask both questions of it directly.
    damaged = tmp_path / "damaged.bundle"
    real_run(["git", "bundle", "create", str(damaged), "--all"],
             cwd=real_repo, capture_output=True, text=True, check=True)
    with open(damaged, "r+b") as fh:
        fh.truncate(300)
    verify = real_run(["git", "bundle", "verify", str(damaged)],
                      cwd=real_repo, capture_output=True, text=True, check=False)
    clone = real_run(["git", "clone", "--bare", "--quiet", str(damaged), str(tmp_path / "probe")],
                     capture_output=True, text=True, check=False)
    assert verify.returncode == 0, (
        "the point of this test is that `git bundle verify` accepts this file; if git has "
        "started rejecting it, the comment above needs re-measuring, not the code"
    )
    assert clone.returncode != 0, "and that a clone — what a restore actually does — does not"


# ── Read-back: uploading is not backing up ────────────────────────────────────
def test_a_readback_mismatch_raises(real_repo, monkeypatch):
    """Defect caught: a green upload whose read-back disagrees with the local file.

    An upload path that drops bytes, mangles the body, or signs a different payload would
    pass a naive "upload_file succeeded" check. The read-back is the actual proof; if the
    digest comes back wrong, mirror_repo raises here rather than letting the next nightly
    run inherit a corrupted object as the latest good copy.
    """
    s3 = FakeS3()

    def _corrupted_get_object(Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(b"NOT THE SAME BYTES AT ALL")}

    monkeypatch.setattr(s3, "get_object", _corrupted_get_object)

    with pytest.raises(RuntimeError, match="reads back differently"):
        bs.mirror_repo(s3, "bucket")

    assert len(s3.upload_calls) == 1, "the upload itself happened — the read-back is what failed"


def test_prune_does_not_run_when_the_readback_failed(real_repo, monkeypatch):
    """Defect caught: pruning on the failure path would delete good copies to make room
    for a corrupted new one.

    Prune is gated on a verified read-back, not on "we wrote something". This test pins
    that ordering so a refactor that moves the prune earlier cannot pass silently.
    """
    s3 = FakeS3()

    def _corrupted_get_object(Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(b"NOT THE SAME BYTES")}

    monkeypatch.setattr(s3, "get_object", _corrupted_get_object)

    with pytest.raises(RuntimeError):
        bs.mirror_repo(s3, "bucket")

    assert s3.delete_calls == [], "pruning must not run before a verified read-back"


# ── Retention: the dated-key series is bounded ───────────────────────────────
def test_prune_keeps_the_newest_n_and_deletes_the_rest(real_repo, monkeypatch):
    """Defect caught: an unbounded dated-key series is how a backup bucket becomes
    something someone turns off.

    Twenty existing keys plus the one mirror_repo just wrote (same stamp as the latest of
    the twenty, so the upload overwrites rather than appends) leaves twenty objects to
    prune. With `keep=14`, the oldest six are deleted and the newest fourteen survive —
    measured against the same `sorted()` order `_remote_index` produces, not against a
    re-implemented counter.
    """
    s3 = FakeS3()

    # Pin the UTC stamp so the test does not depend on the wall clock — and so we can
    # pre-populate the bucket with a key the run will overwrite rather than append to.
    fixed = time.struct_time((2026, 9, 1, 0, 0, 0, 0, 244, 0))
    monkeypatch.setattr(bs.time, "gmtime", lambda secs=None: fixed)
    fixed_stamp = time.strftime("%Y-%m-%dT%H%M%SZ", fixed)

    # 19 chronologically-earlier keys plus the run's own key (already in the bucket so
    # upload_file overwrites it) = 20 total. Sorted lexically, the last 14 survive and
    # the first 6 are deleted.
    keys = [f"repo/2026-08-{i:02d}T000000Z.bundle" for i in range(1, 20)]
    keys.append(f"repo/{fixed_stamp}.bundle")
    for k in keys:
        s3.objects[k] = b"x"
    assert len(s3.objects) == 20

    key, _, _ = bs.mirror_repo(s3, "bucket", keep=14)

    assert key == f"repo/{fixed_stamp}.bundle"
    assert len(s3.objects) == 14, "the newest 14 must survive"
    assert len(s3.delete_calls) == 6, "the oldest 6 must be deleted"
    assert sorted(s3.objects.keys()) == sorted(keys)[-14:], (
        "and the survivors must be the newest 14 in lexical order"
    )

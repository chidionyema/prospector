"""The git mirror must end up being a usable off-site copy, not just a green upload.

The repo has exactly one remote (GitHub). A bundle upload to the same nightly R2 backup
job makes the off-site copy ride the path that already runs, with the credentials that
already work — so the cost of the safety net is one extra `git bundle create` per night,
not a second scheduled job that can rot on its own.

What can go wrong, and the test that holds the line
---------------------------------------------------
- `git bundle create` exits non-zero on a sick repo: mirror_repo propagates the stderr.
- The bundle file is corrupt in a way `git bundle create` did not catch: `git bundle verify`
  catches it, and the upload never happens.
- The upload reaches R2 but the read-back disagrees with the local file: a green upload is
  not a green backup. mirror_repo raises, hard.
- Pruning runs on the wrong day: only the newest `keep` survive, and only after the read-
  back passed.

Tests are offline: a hand-written fake S3 records calls, and `subprocess.run` is patched so
no real git is invoked. The live end-to-end proof is the launchd-scheduled nightly run, not
here.
"""
from __future__ import annotations

import io
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


class _Result:
    """Mimics the duck-typed surface mirror_repo reads off a subprocess.run result."""

    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class FakeRun:
    """Mimics subprocess.run for the bundle create/verify calls in mirror_repo.

    `create` writes a placeholder bundle so the sha matches what we upload. `verify` returns
    whatever returncode the test wires in — mirror_repo must raise before uploading when
    verify fails, so the upload path is gated on the integrity check, not on the upload
    call itself succeeding.
    """

    def __init__(self, verify_rc: int = 0, verify_stderr: str = "") -> None:
        self.verify_rc = verify_rc
        self.verify_stderr = verify_stderr
        self.create_calls: list[list[str]] = []
        self.verify_calls: list[list[str]] = []

    def __call__(self, args, *, cwd=None, capture_output=None, text=None, check=None, **kwargs):
        cmd = args if isinstance(args, list) else [args]
        # `git bundle create <path> --all` and `git bundle verify <path>`. The verb is the THIRD
        # word: cmd[1] is "bundle" for both, so reading it there matches neither branch, the fake
        # writes no file, and every test dies on a FileNotFoundError that blames mirror_repo.
        subcmd = cmd[2] if len(cmd) > 2 else ""
        if subcmd == "create":
            target = Path(cmd[3])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"FAKE BUNDLE\n")
            self.create_calls.append(cmd)
            return _Result(returncode=0, stderr="")
        if subcmd == "verify":
            self.verify_calls.append(cmd)
            return _Result(returncode=self.verify_rc, stderr=self.verify_stderr)
        return _Result(returncode=0, stderr="")


# ── Pre-flight: bundle integrity must be proven before the upload ─────────────
def test_a_bundle_that_git_refuses_to_verify_is_never_uploaded(monkeypatch):
    """Defect caught: an unreadable bundle that uploads green is worse than no upload.

    `git bundle create` returning 0 does not prove the resulting file is a valid bundle —
    a corrupted refs file can slip past. `git bundle verify` is the actual check. If it
    fails, the upload must not happen, because a corrupt object on R2 reads exactly like
    a healthy one on the dashboard.
    """
    s3 = FakeS3()
    fake = FakeRun(verify_rc=1, verify_stderr="could not read bundle")
    monkeypatch.setattr(bs.subprocess, "run", fake)

    with pytest.raises(RuntimeError, match="bundle verify"):
        bs.mirror_repo(s3, "bucket")

    assert s3.upload_calls == [], "an unverified bundle must not be uploaded"
    assert s3.objects == {}, "and the fake bucket must therefore be empty"


# ── Read-back: uploading is not backing up ────────────────────────────────────
def test_a_readback_mismatch_raises(monkeypatch):
    """Defect caught: a green upload whose read-back disagrees with the local file.

    An upload path that drops bytes, mangles the body, or signs a different payload would
    pass a naive "upload_file succeeded" check. The read-back is the actual proof; if the
    digest comes back wrong, mirror_repo raises here rather than letting the next nightly
    run inherit a corrupted object as the latest good copy.
    """
    s3 = FakeS3()
    fake = FakeRun(verify_rc=0)
    monkeypatch.setattr(bs.subprocess, "run", fake)

    def _corrupted_get_object(Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(b"NOT THE SAME BYTES AT ALL")}

    monkeypatch.setattr(s3, "get_object", _corrupted_get_object)

    with pytest.raises(RuntimeError, match="reads back differently"):
        bs.mirror_repo(s3, "bucket")

    assert len(s3.upload_calls) == 1, "the upload itself happened — the read-back is what failed"


def test_prune_does_not_run_when_the_readback_failed(monkeypatch):
    """Defect caught: pruning on the failure path would delete good copies to make room
    for a corrupted new one.

    Prune is gated on a verified read-back, not on "we wrote something". This test pins
    that ordering so a refactor that moves the prune earlier cannot pass silently.
    """
    s3 = FakeS3()
    fake = FakeRun(verify_rc=0)
    monkeypatch.setattr(bs.subprocess, "run", fake)

    def _corrupted_get_object(Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(b"NOT THE SAME BYTES")}

    monkeypatch.setattr(s3, "get_object", _corrupted_get_object)

    with pytest.raises(RuntimeError):
        bs.mirror_repo(s3, "bucket")

    assert s3.delete_calls == [], "pruning must not run before a verified read-back"


# ── Retention: the dated-key series is bounded ───────────────────────────────
def test_prune_keeps_the_newest_n_and_deletes_the_rest(monkeypatch):
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

    fake = FakeRun(verify_rc=0)
    monkeypatch.setattr(bs.subprocess, "run", fake)

    key, _, _ = bs.mirror_repo(s3, "bucket", keep=14)

    assert key == f"repo/{fixed_stamp}.bundle"
    assert len(s3.objects) == 14, "the newest 14 must survive"
    assert len(s3.delete_calls) == 6, "the oldest 6 must be deleted"
    assert sorted(s3.objects.keys()) == sorted(keys)[-14:], (
        "and the survivors must be the newest 14 in lexical order"
    )

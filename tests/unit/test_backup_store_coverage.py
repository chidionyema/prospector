"""What the backup actually covers, and whether the copy is restorable.

Two P0 gaps from COMMERCIAL_READINESS_PROGRAM §23.4, both proved by the first live run of
`scripts/restore_drill.py` rather than by reading the code:

  Gap 1  `store/prospector.db` — the index that says which dossier is live, tombstoned,
         published and at what price — had no scheduled backup at all. A restored dossier
         tree without it is 1,581 loose JSON files with no state.
  Gap 2  `sync()` enumerated dossiers with a NON-recursive `DOSSIER_DIR.glob("*.json")`, so
         the 9 files under `store/dossiers/quarantine_ungrounded/` had never been uploaded.

`test_a_non_recursive_glob_misses_the_quarantine_subdirectory` reproduces gap 2 against the
same tree the fix walks, so the recursion is measured rather than asserted.

No network: `sync`, `verify_sample`, `restore` and `restore_db` all take the client as an
argument, so a dict-backed fake exercises the real code paths end to end. `_client()` (the
only part that touches R2) is not under test here — `tests/test_backup_clock_skew.py` covers
its signing behaviour.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import backup_store as bs  # noqa: E402


class FakeS3:
    """Enough of the S3 surface for sync/verify/restore, with real bytes."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=1000, ContinuationToken=None):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {
            "Contents": [
                {"Key": k, "ETag": '"%s"' % hashlib.md5(self.objects[k]).hexdigest()}  # noqa: S324
                for k in keys
            ],
            "IsTruncated": False,
        }

    def upload_file(self, filename, Bucket, Key, ExtraArgs=None):  # noqa: N803
        self.objects[Key] = Path(filename).read_bytes()

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)
        self.deleted.append(Key)


def _make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE candidates (id TEXT PRIMARY KEY, state TEXT)")
        conn.execute("CREATE TABLE listings (id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO candidates VALUES (?, ?)",
            [(f"c{i}", "published" if i % 2 else "tombstoned") for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fake store: two top-level dossiers, one in a subdirectory, a ledger and a db."""
    dossiers = tmp_path / "dossiers"
    (dossiers / "quarantine_ungrounded").mkdir(parents=True)
    (dossiers / "aaa.pass.json").write_text(json.dumps({"id": "aaa"}), encoding="utf-8")
    (dossiers / "bbb.kill.json").write_text(json.dumps({"id": "bbb"}), encoding="utf-8")
    (dossiers / "quarantine_ungrounded" / "ccc.kill.json").write_text(
        json.dumps({"id": "ccc", "tombstone": "quarantined_ungrounded"}), encoding="utf-8"
    )
    ledger = tmp_path / "prospector.jsonl"
    ledger.write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")
    db = tmp_path / "prospector.db"
    _make_db(db)

    monkeypatch.setattr(bs, "DOSSIER_DIR", dossiers)
    monkeypatch.setattr(bs, "LEDGER", ledger)
    monkeypatch.setattr(bs, "DB", db)
    return tmp_path


# ── Gap 2: coverage of the dossier tree ───────────────────────────────────────
def test_a_non_recursive_glob_misses_the_quarantine_subdirectory(store):
    """The defect, on the same tree the fix walks. 1 file is the entire delta in miniature."""
    old = sorted(p.name for p in (store / "dossiers").glob("*.json"))
    new = sorted(p.name for p in bs._dossier_files())
    assert old == ["aaa.pass.json", "bbb.kill.json"]
    assert new == ["aaa.pass.json", "bbb.kill.json", "ccc.kill.json"]


def test_sync_uploads_nested_dossiers_under_their_relative_path(store):
    s3 = FakeS3()
    uploaded, skipped, ledger_key, db_key = bs.sync(s3, "b")

    assert {k for k in s3.objects if k.startswith("dossiers/")} == {
        "dossiers/aaa.pass.json",
        "dossiers/bbb.kill.json",
        "dossiers/quarantine_ungrounded/ccc.kill.json",
    }
    assert (uploaded, skipped) == (3, 0)
    assert ledger_key.startswith("ledger/prospector-") and ledger_key.endswith(".jsonl.gz")
    assert db_key.startswith("db/prospector-") and db_key.endswith(".db.gz")


def test_the_key_keeps_subdirectories_apart(store):
    """Two dossiers with the same NAME in different directories must be two objects.

    Keying on `path.name` would silently overwrite one with the other — no error anywhere,
    and the loss is invisible until a restore comes up a file short.
    """
    (store / "dossiers" / "quarantine_ungrounded" / "aaa.pass.json").write_text(
        json.dumps({"id": "aaa-quarantined"}), encoding="utf-8"
    )
    s3 = FakeS3()
    bs.sync(s3, "b")

    assert json.loads(s3.objects["dossiers/aaa.pass.json"])["id"] == "aaa"
    assert json.loads(
        s3.objects["dossiers/quarantine_ungrounded/aaa.pass.json"]
    )["id"] == "aaa-quarantined"


def test_a_second_sync_uploads_nothing_and_a_changed_file_is_re_uploaded(store):
    s3 = FakeS3()
    bs.sync(s3, "b")
    uploaded, skipped, _, _ = bs.sync(s3, "b")
    assert (uploaded, skipped) == (0, 3)

    (store / "dossiers" / "quarantine_ungrounded" / "ccc.kill.json").write_text(
        json.dumps({"id": "ccc", "tombstone": "changed"}), encoding="utf-8"
    )
    uploaded, skipped, _, _ = bs.sync(s3, "b")
    assert (uploaded, skipped) == (1, 2)


def test_verify_sample_reads_back_the_nested_file_too(store):
    s3 = FakeS3()
    bs.sync(s3, "b")
    ok, total, problems = bs.verify_sample(s3, "b", n=99)
    assert (ok, total, problems) == (3, 3, [])


def test_verify_sample_reports_a_corrupted_object(store):
    s3 = FakeS3()
    bs.sync(s3, "b")
    s3.objects["dossiers/quarantine_ungrounded/ccc.kill.json"] = b'{"id": "tampered"}'
    ok, total, problems = bs.verify_sample(s3, "b", n=99)
    assert ok == 2 and total == 3
    assert problems == ["dossiers/quarantine_ungrounded/ccc.kill.json: content differs from local"]


def test_dry_run_uploads_nothing_but_still_counts_what_would_go(store):
    s3 = FakeS3()
    uploaded, skipped, _, _ = bs.sync(s3, "b", dry_run=True)
    assert (uploaded, skipped) == (3, 0)
    assert s3.objects == {}


# ── Gap 1: the database ───────────────────────────────────────────────────────
def test_the_db_snapshot_is_a_real_database_not_a_gzipped_file_copy(store):
    s3 = FakeS3()
    _, _, _, db_key = bs.sync(s3, "b")
    raw = gzip.decompress(s3.objects[db_key])
    assert raw[:16] == b"SQLite format 3\x00"


def test_snapshot_censuses_the_tables_and_leaves_the_source_writable(store):
    """The source is opened `mode=ro`, so a backup can never take the daemon's write lock."""
    out = store / "snap.db.gz"
    size, counts = bs._snapshot_db(out)
    assert size > 0
    assert counts == {"candidates": 3, "listings": 0}

    conn = sqlite3.connect(str(store / "prospector.db"))
    try:
        conn.execute("INSERT INTO candidates VALUES ('after', 'x')")
        conn.commit()
    finally:
        conn.close()


def test_restore_rebuilds_the_subdirectory_and_the_db(store, tmp_path, capsys):
    s3 = FakeS3()
    bs.sync(s3, "b")
    dest = tmp_path / "restored"
    count = bs.restore(s3, "b", dest)

    assert count == 3
    # Exactly the layout scripts/restore_drill.py --backup DIR consumes.
    assert (dest / "dossiers" / "aaa.pass.json").is_file()
    assert (dest / "dossiers" / "quarantine_ungrounded" / "ccc.kill.json").is_file()
    assert (dest / "prospector.db").is_file()

    conn = sqlite3.connect(str(dest / "prospector.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 3
    finally:
        conn.close()
    assert "integrity ok" in capsys.readouterr().out


def test_restore_of_a_corrupted_db_snapshot_fails_loudly(store, tmp_path):
    """A restore whose only check is "the bytes arrived" has not proved recovery."""
    s3 = FakeS3()
    _, _, _, db_key = bs.sync(s3, "b")
    raw = bytearray(gzip.decompress(s3.objects[db_key]))
    raw[4096:4196] = b"\xff" * 100          # scribble over a page, keep the header valid
    s3.objects[db_key] = gzip.compress(bytes(raw))

    with pytest.raises((SystemExit, sqlite3.DatabaseError)):
        bs.restore_db(s3, "b", tmp_path / "restored")


def test_restore_without_a_db_snapshot_still_restores_dossiers(store, tmp_path, capsys):
    s3 = FakeS3()
    bs.sync(s3, "b")
    for key in [k for k in s3.objects if k.startswith("db/")]:
        del s3.objects[key]
    assert bs.restore(s3, "b", tmp_path / "restored") == 3
    assert "no db snapshot in the bucket" in capsys.readouterr().err


def test_restore_rejects_an_object_that_does_not_parse(store, tmp_path):
    s3 = FakeS3()
    bs.sync(s3, "b")
    s3.objects["dossiers/aaa.pass.json"] = b"not json"
    with pytest.raises(SystemExit) as exc:
        bs.restore(s3, "b", tmp_path / "restored")
    assert "RESTORE FAIL" in str(exc.value)


# ── Retention ─────────────────────────────────────────────────────────────────
def test_prune_keeps_the_newest_n_dated_snapshots(store):
    s3 = FakeS3()
    for day in ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]:
        s3.objects[f"db/prospector-{day}.db.gz"] = b"x"
    stale = bs._prune_db_snapshots(s3, "b", keep=2)
    assert stale == ["db/prospector-2026-08-01.db.gz", "db/prospector-2026-08-02.db.gz"]
    assert sorted(s3.objects) == [
        "db/prospector-2026-08-03.db.gz",
        "db/prospector-2026-08-04.db.gz",
    ]


def test_prune_is_a_no_op_below_the_threshold_and_when_disabled(store):
    s3 = FakeS3()
    for day in ["2026-08-01", "2026-08-02"]:
        s3.objects[f"db/prospector-{day}.db.gz"] = b"x"
    assert bs._prune_db_snapshots(s3, "b", keep=5) == []
    assert bs._prune_db_snapshots(s3, "b", keep=0) == []
    assert len(s3.objects) == 2


def test_pruning_never_touches_the_ledger_or_the_dossiers(store):
    s3 = FakeS3()
    bs.sync(s3, "b")
    for day in ["2026-07-01", "2026-07-02"]:
        s3.objects[f"db/prospector-{day}.db.gz"] = b"x"
    bs._prune_db_snapshots(s3, "b", keep=1)
    assert [k for k in s3.deleted if not k.startswith("db/")] == []
    assert len([k for k in s3.objects if k.startswith("dossiers/")]) == 3
    assert len([k for k in s3.objects if k.startswith("ledger/")]) == 1


def test_sync_prunes_only_after_the_snapshot_reads_back_clean(store, monkeypatch):
    """Pruning before verification would let a machine whose local db has gone bad delete
    the last good copies on its way past."""
    s3 = FakeS3()
    for day in ["2026-07-01", "2026-07-02", "2026-07-03"]:
        s3.objects[f"db/prospector-{day}.db.gz"] = b"x"

    def _boom(out_gz):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(bs, "_snapshot_db", _boom)
    with pytest.raises(sqlite3.DatabaseError):
        bs.sync(s3, "b")
    assert s3.deleted == []
    assert len([k for k in s3.objects if k.startswith("db/")]) == 3


# ── The ledger prefix rule, still holding ─────────────────────────────────────
def test_ledger_snapshot_stops_at_the_last_complete_record(store):
    (store / "prospector.jsonl").write_bytes(b'{"n": 1}\n{"n": 2}\n{"n": 3, "unfinis')
    out = store / "led.gz"
    captured = bs._snapshot_ledger(out)
    assert gzip.decompress(out.read_bytes()) == b'{"n": 1}\n{"n": 2}\n'
    assert captured == len(b'{"n": 1}\n{"n": 2}\n')

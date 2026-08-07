"""R4 — the restore drill must PASS on a good backup and FAIL on a broken one.

The interesting assertion is the second one. A verifier that only ever runs against healthy input
is indistinguishable from `return True`, which is exactly the failure mode R4 exists to close:
`backup_store.py` had zero verification and nobody noticed, because nothing ever restored.

Everything here builds a synthetic store in `tmp_path`. No production path is read or written, no
network, no LLM calls.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import restore_drill  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────────
def _make_store(root: Path, *, live: int = 6, tombstoned: int = 2) -> Path:
    """A store root shaped like the real one: a dossiers/ tree and a SQLite index over it."""
    store = root / "store"
    dossiers = store / "dossiers"
    dossiers.mkdir(parents=True)
    conn = sqlite3.connect(str(store / "prospector.db"))
    try:
        conn.execute(
            "CREATE TABLE dossiers (candidate_id TEXT PRIMARY KEY, title TEXT, decision TEXT, "
            "path TEXT, tombstone TEXT)"
        )
        for i in range(live):
            cid = f"live{i:04d}"
            path = dossiers / f"{cid}.json"
            path.write_text(json.dumps({"candidate": {"id": cid, "title": f"t{i}"},
                                        "decision": "pass"}))
            conn.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)",
                         (cid, f"t{i}", "pass", str(path), None))
        for i in range(tombstoned):
            # Rows the index keeps after the file went away — expected absent, never a failure.
            cid = f"gone{i:04d}"
            conn.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)",
                         (cid, f"g{i}", "kill", str(dossiers / f"{cid}.kill.json"),
                          "dossier_missing"))
        conn.commit()
    finally:
        conn.close()
    return store


def _add_quarantined(store: Path, n: int = 3) -> None:
    """Dossiers that live in a SUBDIRECTORY of the tree, as `quarantine_ungrounded/` really does."""
    sub = store / "dossiers" / "quarantine_ungrounded"
    sub.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(store / "prospector.db"))
    try:
        for i in range(n):
            cid = f"quar{i:04d}"
            path = sub / f"{cid}.pass.json"
            path.write_text(json.dumps({"candidate": {"id": cid}, "decision": "pass"}))
            conn.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)",
                         (cid, f"q{i}", "pass", str(path), "quarantined_ungrounded"))
        conn.commit()
    finally:
        conn.close()


def _drill(store: Path, dest: Path, **kw) -> tuple[int, str]:
    return restore_drill.run_drill(store, dest, sample_n=kw.pop("sample_n", 12), **kw)


# ── the good path ─────────────────────────────────────────────────────────────
def test_drill_passes_on_a_good_backup(tmp_path):
    store = _make_store(tmp_path)
    code, report = _drill(store, tmp_path / "scratch")
    assert code == 0, report
    assert "RESTORE_DRILL PASS" in report
    assert "[FAIL]" not in report
    # The counts it asserts are the real ones, not a vacuous zero. Column padding is cosmetic,
    # so the assertion normalises whitespace rather than encoding the current field widths.
    flat = " ".join(report.split())
    assert "rows:dossiers restored=8 source=8" in flat
    assert "dossier_files restored=6 source=6" in flat
    assert "failures=0" in report


def test_drill_restores_into_scratch_and_leaves_the_source_alone(tmp_path):
    store = _make_store(tmp_path)
    before = {p.name: p.read_bytes() for p in sorted((store / "dossiers").glob("*.json"))}
    db_before = (store / "prospector.db").read_bytes()

    dest = tmp_path / "scratch"
    code, report = _drill(store, dest)
    assert code == 0, report

    after = {p.name: p.read_bytes() for p in sorted((store / "dossiers").glob("*.json"))}
    assert after == before
    assert (store / "prospector.db").read_bytes() == db_before
    # and the restore really landed somewhere else
    assert (dest / "restored" / "prospector.db").is_file()
    assert len(list((dest / "restored" / "dossiers").glob("*.json"))) == 6


def test_source_db_is_opened_read_only(tmp_path):
    """The live daemon writes to prospector.db; the drill must not take a write lock on it."""
    store = _make_store(tmp_path)
    conn = restore_drill._connect_ro(store / "prospector.db")
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO dossiers VALUES ('x','x','pass','/x',NULL)")
    finally:
        conn.close()


def test_dest_inside_store_is_refused(tmp_path):
    store = _make_store(tmp_path)
    with pytest.raises(SystemExit) as exc:
        restore_drill._guard_dest(store / "dossiers" / "scratch", store)
    assert "protected runtime state" in str(exc.value)


def test_drill_covers_dossiers_in_subdirectories(tmp_path):
    """Regression: the first live run FAILED on the 9 rows under `quarantine_ungrounded/`.

    A non-recursive `*.json` glob does not see them, so they were neither snapshotted nor found in
    the restored tree — a drill that skipped them would have reported a clean restore of a tree it
    had silently truncated. `backup_store.py` still has the non-recursive glob.
    """
    store = _make_store(tmp_path)
    _add_quarantined(store, n=3)

    dest = tmp_path / "scratch"
    code, report = _drill(store, dest, sample_n=99)
    assert code == 0, report
    restored_sub = dest / "restored" / "dossiers" / "quarantine_ungrounded"
    assert sorted(p.name for p in restored_sub.glob("*.json")) == [
        "quar0000.pass.json", "quar0001.pass.json", "quar0002.pass.json"
    ]
    assert "dossier_files restored=9 source=9" in " ".join(report.split())


def test_drill_fails_if_the_subdirectory_is_dropped_from_the_backup(tmp_path):
    """The exact shape of `backup_store.py`'s gap: a top-level-only mirror of the tree."""
    store = _make_store(tmp_path)
    _add_quarantined(store, n=3)

    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())
    for p in (store / "dossiers").glob("*.json"):  # deliberately NOT rglob
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "index_vs_tree" in report
    assert "rows with NO restored file" in report


# ── the broken paths ──────────────────────────────────────────────────────────
def test_drill_fails_on_a_truncated_db(tmp_path):
    """Truncation is the canonical corruption: the file still opens, then reads garbage."""
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    raw = (store / "prospector.db").read_bytes()
    (backup / "prospector.db").write_bytes(raw[: len(raw) // 2])

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "RESTORE_DRILL FAIL" in report
    assert "db_integrity" in report


def test_drill_fails_on_a_corrupt_dossier(tmp_path):
    """Bytes that are not the JSON a recovery is supposed to yield."""
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())
    for p in sorted((backup / "dossiers").glob("*.json")):
        p.write_text("{ this is not json")

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "not valid JSON" in report


def test_drill_fails_when_dossiers_are_missing_from_the_backup(tmp_path):
    """The half-uploaded backup: the index promises rows the tree cannot produce."""
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    kept = sorted((store / "dossiers").glob("*.json"))[:2]
    for p in kept:
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "index_vs_tree" in report
    assert "rows with NO restored file" in report


def test_drill_fails_when_the_backup_has_no_db_at_all(tmp_path):
    """`backup_store.py` mirrors dossiers and the ledger and has never copied prospector.db."""
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "db_present" in report


def test_drill_fails_when_the_backup_has_more_rows_than_the_source(tmp_path):
    """Extra INDEX ROWS mean the payload is not this store's backup.

    Extra FILES do not — see `test_a_supplied_payload_may_keep_files_the_source_deleted`. The
    two used to share one count assertion; they are different facts and only one of them is a
    failure.
    """
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())
    conn = sqlite3.connect(str(backup / "prospector.db"))
    try:
        for i in range(5):
            cid = f"extra{i}"
            path = backup / "dossiers" / f"{cid}.json"
            path.write_text(json.dumps({"candidate": {"id": cid}, "decision": "pass"}))
            conn.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)",
                         (cid, "x", "pass", str(path), None))
        conn.commit()
    finally:
        conn.close()

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "MISMATCH" in report


def test_spot_check_catches_a_swapped_dossier(tmp_path):
    """Right filename, wrong contents — the case a filename-only census cannot see."""
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())
    for p in sorted((backup / "dossiers").glob("*.json")):
        p.write_text(json.dumps({"candidate": {"id": "SOMEONE-ELSE"}, "decision": "pass"}))

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup, sample_n=6)
    assert code != 0, report
    assert "SOMEONE-ELSE" in report


# ── a supplied payload is cumulative ──────────────────────────────────────────
def test_a_supplied_payload_may_keep_files_the_source_deleted(tmp_path):
    """An R2 pull holds dossiers the live store no longer has, and that is the point.

    `backup_store.sync` never deletes: a mirror that removes what the source removed cannot
    survive an accidental deletion, which is the failure the bucket exists for. Measured on the
    live bucket 2026-08-07: 1701 restored objects against 1588 live files. Failing on that would
    have made the drill red forever on a healthy backup, and a check that is always red is a
    check nobody reads.
    """
    store = _make_store(tmp_path)
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())
    for i in range(4):  # dossiers deleted from the store since the backup was written
        (backup / "dossiers" / f"deleted{i}.json").write_text(
            json.dumps({"candidate": {"id": f"deleted{i}"}, "decision": "kill"})
        )

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code == 0, report
    flat = " ".join(report.split())
    assert "dossier_coverage 6 live source file(s), all present in the restore" in flat
    assert "retained_history 10 restored vs 6 live — 4 object(s)" in flat


def test_coverage_catches_a_live_file_the_index_does_not_know_about(tmp_path):
    """The check earns its place only if it can fail where the others cannot.

    A source dossier with no index row is invisible to `index_vs_tree` — that check walks rows,
    not files. Drop it from the payload and every other check stays green while the file is
    simply not recoverable.
    """
    store = _make_store(tmp_path)
    (store / "dossiers" / "unindexed.json").write_text(
        json.dumps({"candidate": {"id": "unindexed"}, "decision": "pass"})
    )
    backup = tmp_path / "backup"
    (backup / "dossiers").mkdir(parents=True)
    for p in (store / "dossiers").glob("*.json"):
        if p.name != "unindexed.json":
            (backup / "dossiers" / p.name).write_bytes(p.read_bytes())
    (backup / "prospector.db").write_bytes((store / "prospector.db").read_bytes())

    code, report = _drill(store, tmp_path / "scratch", backup_dir=backup)
    assert code != 0, report
    assert "dossier_coverage" in report
    assert "unindexed.json" in report
    assert "[PASS] index_vs_tree" in report      # the check that cannot see this


# ── exit codes and CLI wiring ─────────────────────────────────────────────────
def test_cli_exit_zero_on_pass(tmp_path, capsys):
    store = _make_store(tmp_path)
    code = restore_drill.main(["--store", str(store), "--dest", str(tmp_path / "scratch"),
                               "--seed", "1"])
    assert code == 0
    assert "RESTORE_DRILL PASS" in capsys.readouterr().out


def test_cli_exit_two_when_the_store_does_not_exist(tmp_path):
    assert restore_drill.main(["--store", str(tmp_path / "nope")]) == 2


def test_cli_ephemeral_scratch_is_removed(tmp_path, capsys):
    """A drill that leaves scratch dirs behind is a disk leak on a scheduled job."""
    store = _make_store(tmp_path)
    made: list[str] = []
    real_mkdtemp = restore_drill.tempfile.mkdtemp

    def _spy(*a, **kw):
        path = real_mkdtemp(*a, **{**kw, "dir": str(tmp_path)})
        made.append(path)
        return path

    restore_drill.tempfile.mkdtemp = _spy
    try:
        code = restore_drill.main(["--store", str(store)])
    finally:
        restore_drill.tempfile.mkdtemp = real_mkdtemp
    assert code == 0, capsys.readouterr().out
    assert made and not Path(made[0]).exists()

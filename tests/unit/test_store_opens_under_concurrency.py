"""Opening the catalogue must survive another connection already holding it open.

The defect this pins, found 2026-08-15: `Store._connect` ran `PRAGMA journal_mode=WAL` on every
connection, unconditionally. SQLite documents that a journal-mode change while another connection
has the database open "returns SQLITE_BUSY immediately without invoking the busy handler" — so the
`timeout=10.0` on the connect, which exists for exactly this class of contention, does not cover
the one statement that needs it. A second opener raised

    sqlite3.OperationalError: database is locked

out of `_connect`, therefore out of `Store.__init__`, therefore out of `import prospector.api`
(api.py builds a module-level `Store`). It surfaced as a TEST HARNESS failure — four xdist workers
importing `tests/integration/test_api.py` at once, two collecting it and two not, and xdist
aborting the run with "Different tests were collected between gw2 and gw3" — which is why it is
worth a test that names the real cause. The daemon, the CLI and the API all open this database, so
the failure was never confined to the suite.

Two things make this test discriminate rather than merely pass, and both were got wrong first:

  * The contention is set up EXPLICITLY, with an open read transaction, not by racing threads. A
    race reproduces the bug only sometimes and would be a flaky test of a flaky bug.
  * The database is put back into `delete` journal mode first. Against a WAL database the pragma
    is a no-op that never contends, so the same test passes on the broken code — vacuous, and the
    exact failure mode that lets a regression test report green while guarding nothing.

What is NOT asserted, because SQLite cannot do it: writing while a reader holds a rollback-journal
database. `_init_db` on a database with no schema yet must create tables, and that blocks on the
reader no matter how the pragma is handled. So the fixture seeds the schema first; what is being
measured is the CONNECTION opening, which is what the pragma broke.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from prospector.store import Store


def _cfg(root: Path) -> SimpleNamespace:
    """The only thing `Store.__init__` reads is `store_dir`; the rest it merely keeps."""
    return SimpleNamespace(store_dir=root)


def _seeded_store_in_delete_mode(root: Path) -> Path:
    """A fully-migrated catalogue whose file is in `delete` journal mode.

    Seeded by the real constructor so the schema is whatever `_init_db` actually creates — writing
    the DDL out here by hand would be a second definition of the schema, drifting on the first
    migration. The mode is then converted back, which is what makes the pragma contend.
    """
    Store(_cfg(root))
    db = root / "prospector.db"
    conn = sqlite3.connect(str(db), timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()
    finally:
        conn.close()
    return db


def test_opening_a_contended_catalogue_does_not_raise(tmp_path: Path):
    root = tmp_path / "store"
    db = _seeded_store_in_delete_mode(root)

    holder = sqlite3.connect(str(db), timeout=10.0)
    try:
        holder.execute("BEGIN")
        holder.execute("SELECT name FROM sqlite_master").fetchall()   # holds the file open
        mode = holder.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() != "wal", (
            "guards the test itself: against a WAL database the pragma is a no-op and this "
            "passes on the broken code"
        )
        Store(_cfg(root))            # the assertion IS that this does not raise
    finally:
        holder.rollback()
        holder.close()


def test_the_catalogue_opened_under_contention_is_usable(tmp_path: Path):
    """Not merely "did not raise": the store it returns has to work.

    Tolerating the pragma failure would be worth nothing if what came back were a half-built
    object, so this reads the index through the connection the constructor is responsible for.
    """
    root = tmp_path / "store"
    db = _seeded_store_in_delete_mode(root)

    holder = sqlite3.connect(str(db), timeout=10.0)
    try:
        holder.execute("BEGIN")
        holder.execute("SELECT name FROM sqlite_master").fetchall()
        store = Store(_cfg(root))
        assert store.db == db
        with sqlite3.connect(str(store.db), timeout=10.0) as check:
            tables = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "dossiers" in tables
    finally:
        holder.rollback()
        holder.close()


def test_an_uncontended_open_still_converts_the_file_to_wal(tmp_path: Path):
    """The fix must not have quietly cost us WAL, which is why the pragma is there at all.

    Skipping the conversion when it is already WAL is the optimisation; skipping it always would
    be a silent downgrade of every writer in the estate, and nothing else in the suite would
    notice.
    """
    root = tmp_path / "store"
    store = Store(_cfg(root))
    with sqlite3.connect(str(store.db), timeout=10.0) as check:
        assert str(check.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"


def test_a_genuinely_unopenable_database_still_raises(tmp_path: Path):
    """The narrowing, pinned: the handler must not become a general "ignore sqlite errors".

    A directory where the database file belongs cannot be opened by any connection. If that starts
    passing, the `except sqlite3.OperationalError` around the pragma has grown to cover the connect
    itself, and `Store(...)` would hand back an object with no database behind it.
    """
    root = tmp_path / "store"
    root.mkdir(parents=True)
    (root / "prospector.db").mkdir()
    with pytest.raises(sqlite3.OperationalError):
        Store(_cfg(root))


def test_a_lost_migration_race_is_not_an_error(tmp_path: Path):
    """Two openers that both saw the column missing must both succeed.

    The second CI failure of this shape (2026-08-15), one commit after the WAL one and in the
    same import: `sqlite3.OperationalError: duplicate column name: tombstone` out of
    `Store.__init__`, out of `import prospector.api`, reported by xdist as "Different tests were
    collected between gw3 and gw1". `_init_db` reads PRAGMA table_info and THEN alters, so two
    processes that read before either wrote both try to add the same column.

    Passing a stale `cols` to a table that already has everything reproduces the loser's exact
    situation deterministically — the race's observable condition, without racing. Threads would
    reproduce it only sometimes, which is a flaky test of a flaky bug.
    """
    store = Store(_cfg(tmp_path / "store"))
    with sqlite3.connect(str(store.db), timeout=10.0) as conn:
        store._add_missing_columns(conn, cols=set())     # every ALTER is a duplicate


def test_a_migration_that_is_not_a_duplicate_still_raises(tmp_path: Path):
    """The narrowing, pinned: the handler must not become "ignore schema errors".

    If this starts passing, a real DDL failure — a typo, a dropped table — is being swallowed,
    and the next migration fails silently instead of loudly.
    """
    store = Store(_cfg(tmp_path / "store"))
    with sqlite3.connect(str(store.db), timeout=10.0) as conn:
        conn.execute("DROP TABLE dossiers")
        with pytest.raises(sqlite3.OperationalError):
            store._add_missing_columns(conn, cols=set())

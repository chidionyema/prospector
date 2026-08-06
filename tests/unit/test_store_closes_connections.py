"""`with sqlite3.Connection` is a TRANSACTION manager, not a resource manager.

Every SQLite-backed store in this package was written as::

    def _connect(self):            # returns a bare connection
        ...
        return conn

    with self._connect() as conn:  # reads like a resource manager; is not one
        ...

`sqlite3.Connection.__exit__` commits or rolls back and deliberately leaves the connection
OPEN. So every call leaked two descriptors — the database and its WAL — for the lifetime of
the process. Measured on the live store 2026-08-06: 200 `Store.has_dossier()` calls leaked
201 fds, monotonic, never reclaimed.

It survived for as long as it did because every caller was O(1) per run, so the leak stayed
under any limit. The backlog brake's per-row survey (`run.drain_survey`) is the first
O(backlog) caller, and with ~340 rows it crossed launchd's 256-fd default **four seconds
after the daemon started**:

    12:10:53Z INFO  Daemon starting: interval=7200s
    12:10:57Z ERROR Failed to write heartbeat: [Errno 24] Too many open files
    12:10:57Z CRITICAL Generation suppressed: backlog brake: the drainable backlog could
              not be counted, so the brake cannot prove it is safe to generate

Note the shape of that failure: the fd exhaustion did not present as a database error. It
presented as a *heartbeat write* failing and the brake refusing to generate — two subsystems
that had nothing to do with the leak, one of which is the daemon's liveness signal. The
brake behaved correctly (it cannot prove safety, so it does not generate) and the watchdog
was simultaneously blinded. A descriptor leak anywhere is therefore a liveness bug
everywhere, which is why this is guarded per-store rather than per-caller.

The tests below assert the property (connections are closed) rather than the call count, so
they keep biting no matter how many sites are added, and they walk EVERY sqlite-backed store
in the package — the same defect was live in all three files, and a guard written only where
the symptom appeared is how the siblings survive.
"""
from __future__ import annotations

import os
import sqlite3
import types

import pytest

from prospector.metrics_store import MetricsStore
from prospector.self_modify import SelfModificationLog
from prospector.store import Store


def _still_open(fn):
    """Run `fn`, return the sqlite connections it opened that are STILL usable afterwards.

    Portable and deterministic: a closed connection raises `sqlite3.ProgrammingError` on
    use, so "did you close it" is a question we can ask directly instead of inferring it
    from an fd count that other parts of the process also move.
    """
    opened = []
    real = sqlite3.connect

    def tracking(*a, **kw):
        conn = real(*a, **kw)
        opened.append(conn)
        return conn

    sqlite3.connect = tracking
    try:
        fn()
    finally:
        sqlite3.connect = real

    leaked = []
    for conn in opened:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue  # closed, as it should be
        leaked.append(conn)
        conn.close()
    return leaked


def _store(tmp_path):
    return Store(types.SimpleNamespace(store_dir=tmp_path))


# ----------------------------------------------------------------------------------------
# The property, per store
# ----------------------------------------------------------------------------------------

def test_a_store_read_closes_its_connection(tmp_path):
    store = _store(tmp_path)
    leaked = _still_open(lambda: store.all(decision="defer"))
    assert leaked == [], (
        "a plain read left a connection open — `with conn:` ended the transaction and kept "
        "the socket. Every read in the process accumulates two fds this way.")


def test_a_store_write_closes_its_connection(tmp_path):
    store = _store(tmp_path)
    with store._connect() as conn:
        conn.execute("INSERT INTO dossiers (candidate_id, decision) VALUES ('w1','defer')")
    leaked = _still_open(lambda: store.all())
    assert leaked == []


def test_the_per_row_survey_does_not_leak_a_descriptor_per_row(tmp_path):
    """The exact prod failure: an O(backlog) caller of an O(1)-safe leak.

    340 rows x 2 fds is past launchd's 256-fd default before the first tick finishes, and
    the first casualty is the heartbeat, not the database.
    """
    store = _store(tmp_path)
    leaked = _still_open(lambda: [store.has_dossier(f"c{i}") for i in range(250)])
    assert leaked == [], (
        f"{len(leaked)} of 250 per-row calls left a connection open; at two fds each that is "
        "[Errno 24] inside one brake survey")


@pytest.mark.skipif(not os.path.isdir("/dev/fd"), reason="needs /dev/fd to count descriptors")
def test_the_descriptor_count_is_flat_across_a_full_survey(tmp_path):
    """The property test above proves the connections are closed; this proves the OS agrees.

    Belt and braces on purpose: the failure we shipped was an OS-level limit, and a mocked
    `sqlite3.connect` cannot exhaust one. Pre-fix this grew by ~2 per call (measured: 200
    calls -> 201 fds).
    """
    store = _store(tmp_path)
    store.has_dossier("warm")            # pay any one-off import/WAL cost before measuring
    before = len(os.listdir("/dev/fd"))
    for i in range(250):
        store.has_dossier(f"c{i}")
    growth = len(os.listdir("/dev/fd")) - before
    assert growth <= 2, (
        f"250 calls grew the descriptor table by {growth}; the pre-fix rate was ~2 per call, "
        "which is [Errno 24] on a 340-row backlog under launchd's 256-fd default")


def test_every_sqlite_backed_store_in_the_package_closes(tmp_path):
    """Walk the siblings. `store.py` was where the symptom appeared; `metrics_store.py` and
    `self_modify.py` carried the identical `return conn` shape, and construction alone runs
    `_init_db` through `_connect`, so this bites without needing each class's read API."""
    cases = {
        "Store": lambda: Store(types.SimpleNamespace(store_dir=tmp_path / "s")),
        "MetricsStore": lambda: MetricsStore(tmp_path / "m" / "metrics.db"),
        "SelfModificationLog": lambda: SelfModificationLog(tmp_path / "l" / "mods.db"),
    }
    leaks = {name: len(_still_open(make)) for name, make in cases.items()}
    assert leaks == {"Store": 0, "MetricsStore": 0, "SelfModificationLog": 0}, (
        f"these stores leak a connection on construction alone: {leaks}")


# ----------------------------------------------------------------------------------------
# ...without changing what the call sites already relied on
# ----------------------------------------------------------------------------------------

def test_a_write_still_commits(tmp_path):
    """The fix wraps the original `with conn:` rather than replacing it, because ten call
    sites already depend on commit-on-exit. If closing had been bolted on in place of the
    transaction manager, every write would silently roll back."""
    store = _store(tmp_path)
    with store._connect() as conn:
        conn.execute("INSERT INTO dossiers (candidate_id, decision) VALUES ('committed','defer')")

    reopened = _store(tmp_path)
    with reopened._connect() as conn:
        row = conn.execute(
            "SELECT candidate_id FROM dossiers WHERE candidate_id='committed'").fetchone()
    assert row is not None, "the write did not survive the block; commit-on-exit was lost"


def test_an_exception_still_rolls_back_and_still_closes(tmp_path):
    store = _store(tmp_path)

    def boom():
        with store._connect() as conn:
            conn.execute("INSERT INTO dossiers (candidate_id, decision) VALUES ('rb','defer')")
            raise RuntimeError("mid-transaction failure")

    with pytest.raises(RuntimeError):
        boom()

    with store._connect() as conn:
        row = conn.execute("SELECT candidate_id FROM dossiers WHERE candidate_id='rb'").fetchone()
    assert row is None, "rollback-on-exception was lost"


def test_an_exception_closes_the_connection_too(tmp_path):
    """`finally: conn.close()` sits OUTSIDE the transaction manager. A close that only ran on
    the happy path would leak exactly on the paths that repeat — a flapping moat re-vets the
    same rows, so the failing path is the hot one."""
    store = _store(tmp_path)

    def boom():
        try:
            with store._connect() as conn:
                conn.execute("SELECT 1")
                raise RuntimeError("mid-transaction failure")
        except RuntimeError:
            pass

    assert _still_open(boom) == [], "the connection survived an exception inside the block"

"""A backlog row is a queue entry, and exactly one worker may hold it.

Selecting work has always been a plain SELECT (`run.drainable()`), and nothing marked a row as
taken. That was safe for exactly one reason: one serialized tick ever ran. It stops being safe
the moment vetting is a continuously-running consumer, a second daemon, or an operator running
`vet --resume` by hand while the daemon ticks — which this repo treats as routine.

Two workers on one row is not merely wasted money. `store.save` writes through a FIXED temp path
and then sweeps the other decision's JSON, so concurrent saves of one candidate_id can interleave
and delete each other's file; and if both rule PASS, both enter a publish path whose Stripe mint
is a check-then-act with no lock of its own.

`drain_state` cannot close this: it is an attempt COUNTER, recording that a row was worked after
the fact. It has no way to stop a second worker from starting.

These tests pin the compare-and-swap, and — the part a single-threaded test would miss — that it
holds under genuine concurrency.
"""
from __future__ import annotations

import threading
import time
import types

import pytest

from prospector.store import Store


def _store(tmp_path) -> Store:
    return Store(types.SimpleNamespace(store_dir=tmp_path))


def _row(store: Store, cid: str) -> None:
    """Insert a bare index row. The lease is a property of the ROW, not of a dossier, so these
    tests deliberately do not write dossier JSON — a lease must work before any work is done."""
    import sqlite3
    conn = sqlite3.connect(str(store.db))
    with conn:
        conn.execute(
            "INSERT INTO dossiers (candidate_id, title, decision) VALUES (?, ?, ?)",
            (cid, f"title-{cid}", "defer"))
    conn.close()


def test_a_second_owner_cannot_take_a_held_row(tmp_path):
    store = _store(tmp_path)
    _row(store, "c1")

    assert store.claim("c1", "worker-a", 60) is True
    assert store.claim("c1", "worker-b", 60) is False, (
        "two workers holding one row is the whole failure this exists to prevent")


def test_an_owner_may_retake_its_own_row_because_a_long_vet_must_renew(tmp_path):
    """A drain row measured 4127s on 2026-08-15. A lease shorter than the work it covers must be
    extendable in place, or the worker's own row expires underneath it mid-vet — which hands a
    LIVE row to a second worker and manufactures exactly the double-work being prevented, most
    often on the slowest and most expensive rows."""
    store = _store(tmp_path)
    _row(store, "c1")

    assert store.claim("c1", "worker-a", 1) is True
    assert store.claim("c1", "worker-a", 3600) is True, "an owner must be able to renew"
    # And the renewal actually moved the wall: the short TTL has now expired in wall-clock terms,
    # but the row is still held, so a stranger is still refused.
    time.sleep(1.1)
    assert store.claim("c1", "worker-b", 60) is False


def test_an_expired_lease_frees_the_row_with_nobody_cleaning_up(tmp_path):
    """Expiry IS the release. Nothing sweeps stale leases, deliberately: a worker SIGKILLed
    mid-vet returns its row to the queue by doing nothing at all, and no reaper process can
    itself be the thing that dies."""
    store = _store(tmp_path)
    _row(store, "c1")

    assert store.claim("c1", "worker-a", 0.05) is True
    time.sleep(0.2)
    assert store.claim("c1", "worker-b", 60) is True, (
        "a crashed worker must not park a row forever")


def test_a_stale_owner_cannot_release_the_new_holders_lease(tmp_path):
    """The dangerous ordering: A's lease expires, B legitimately takes the row, and A — still
    running, unaware — finishes and releases. If release were not scoped to the owner, A's
    cleanup would free a row B is actively vetting, and a third worker could start on it."""
    store = _store(tmp_path)
    _row(store, "c1")

    assert store.claim("c1", "worker-a", 0.05) is True
    time.sleep(0.2)
    assert store.claim("c1", "worker-b", 60) is True

    assert store.release("c1", "worker-a") is False, "A no longer holds it and must not free it"
    assert store.claim("c1", "worker-c", 60) is False, "B's lease must have survived A's release"
    assert store.release("c1", "worker-b") is True


def test_release_returns_the_row_immediately(tmp_path):
    store = _store(tmp_path)
    _row(store, "c1")

    assert store.claim("c1", "worker-a", 3600) is True
    assert store.release("c1", "worker-a") is True
    assert store.claim("c1", "worker-b", 60) is True, (
        "a clean finish must not park the row for the rest of a worst-case TTL")


def test_claiming_a_row_that_does_not_exist_is_false_not_an_error(tmp_path):
    """A queue can be handed an id whose row was tombstoned or removed between selection and
    claim. That is a miss, not a crash, and it must not take the pass down with it."""
    store = _store(tmp_path)
    assert store.claim("nonexistent", "worker-a", 60) is False


def test_exactly_one_of_sixteen_concurrent_workers_wins(tmp_path):
    """THE TEST THE SINGLE-THREADED ONES CANNOT REPLACE. A check-then-act passes every
    sequential assertion above and still loses the race: the window is between the read and the
    write, and only real contention opens it. Sixteen threads is the measured clean MiniMax
    width, i.e. the real fan-out a consumer will have.
    """
    store = _store(tmp_path)
    _row(store, "hot")

    wins: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(16)

    def worker(n: int) -> None:
        start.wait()  # release all sixteen at once, or they simply queue politely
        if store.claim("hot", f"worker-{n}", 60):
            with lock:
                wins.append(f"worker-{n}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(wins) == 1, f"exactly one worker may hold a row; {len(wins)} did: {wins}"


def test_leased_reports_what_is_in_flight_and_forgets_expired_ones(tmp_path):
    store = _store(tmp_path)
    _row(store, "live")
    _row(store, "stale")
    _row(store, "free")

    store.claim("live", "worker-a", 3600)
    store.claim("stale", "worker-b", 0.05)
    time.sleep(0.2)

    ids = {r["candidate_id"] for r in store.leased()}
    assert ids == {"live"}, (
        "an expired lease is not in flight; reporting it as such would show an operator work "
        "that nobody is doing")


def test_the_lease_is_not_subtracted_from_the_backlog(tmp_path):
    """One definition of backlog, or the brake deadlocks.

    `drainable()` feeds BOTH the drain and the scheduler's generation brake. A row being worked
    has not left the backlog — it has no verdict yet. Hiding leased rows from that count would
    make the brake read the queue as shorter than it is and release a generation freeze on work
    that has not landed, which is the same class of bug as counting rows nothing can ever move.
    """
    import inspect

    from prospector import run as run_mod

    store = _store(tmp_path)
    _row(store, "c1")
    # `drainable` also excludes rows with no dossier JSON on disk, so ask the narrower question
    # this test owns: taking a lease must not change what selection returns.
    before = len(store.all(decision="defer"))
    store.claim("c1", "worker-a", 3600)
    after = len(store.all(decision="defer"))
    assert before == after == 1

    # And the selection path must not learn about leases behind this test's back. Checked on
    # IDENTIFIERS in the source, not on prose — a substring search over the docstring matches
    # the word "releases" and would pass on a function that had never heard of a lease.
    src = inspect.getsource(run_mod.drain_survey)
    for token in ("lease_until", "lease_owner", ".claim(", ".leased("):
        assert token not in src, (
            f"drain_survey now filters on {token}; the scheduler's generation brake counts this "
            f"same population, so narrowing one side leaves the brake waiting on rows the other "
            f"side has hidden from it")


@pytest.mark.parametrize("ttl", [0.0, -1.0])
def test_a_nonpositive_ttl_leaves_the_row_immediately_free(tmp_path, ttl):
    """Not a config anyone should set, but a lease that is already expired on arrival must
    behave as unheld rather than as held-forever. The failure direction matters: 'held forever
    by a TTL typo' stalls the queue silently."""
    store = _store(tmp_path)
    _row(store, "c1")

    store.claim("c1", "worker-a", ttl)
    assert store.claim("c1", "worker-b", 60) is True

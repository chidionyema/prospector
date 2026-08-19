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

import os
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


def test_a_bounded_pass_does_not_spend_its_slice_on_rows_someone_else_holds(tmp_path):
    """The starvation this filter exists to stop, measured on the live store 2026-08-16.

    `_revet` already claims each row and skips it when the claim fails, which is correct and is
    not enough. The pass takes its slice from a DETERMINISTIC rank sort, so a held row sits at
    the front of the queue on every pass. The consumer logged

        {"attempted": 24, "resumed": 0, "backlog": 317}

    every ten seconds for 25 minutes, judging nothing. All 24 leases belonged to four SIGKILLed
    processes and `schedule.lease_ttl_s` is 7200, so four dead workers froze the whole queue for
    up to two hours.
    """
    from prospector.run import _drop_leased

    store = _store(tmp_path)
    for cid in ("a", "b", "c", "d"):
        _row(store, cid)
    store.claim("a", "dead-worker", 3600)
    store.claim("b", "dead-worker", 3600)

    pending = [{"candidate_id": c} for c in ("a", "b", "c", "d")]
    kept, dropped = _drop_leased(pending, store)

    assert [r["candidate_id"] for r in kept] == ["c", "d"]
    assert dropped == 2
    # A two-row slice must now be two WORKABLE rows, not two collisions.
    assert len(kept[:2]) == 2


def test_an_expired_lease_does_not_hold_a_row_out_of_the_pass(tmp_path):
    """Expiry is the crash-recovery path. If this filter honoured a dead lease, it would park
    the row for the full TTL instead of the claim re-taking it immediately."""
    from prospector.run import _drop_leased

    store = _store(tmp_path)
    _row(store, "a")
    store.claim("a", "dead-worker", 0.05)
    time.sleep(0.2)

    kept, dropped = _drop_leased([{"candidate_id": "a"}], store)
    assert [r["candidate_id"] for r in kept] == ["a"] and dropped == 0


def test_the_filter_preserves_the_priority_order_it_was_given(tmp_path):
    """The caller has already ranked by population and age. Removing rows must not reorder the
    survivors, or a bounded pass silently stops working the highest-value population first."""
    from prospector.run import _drop_leased

    store = _store(tmp_path)
    for cid in ("p1", "p2", "p3", "p4"):
        _row(store, cid)
    store.claim("p2", "other", 3600)

    kept, _ = _drop_leased([{"candidate_id": c} for c in ("p1", "p2", "p3", "p4")], store)
    assert [r["candidate_id"] for r in kept] == ["p1", "p3", "p4"]


def test_a_store_that_cannot_answer_never_ends_the_pass(tmp_path):
    """A diagnostic-grade read must not be able to break the drain. Worst case is the behaviour
    that existed before the filter: every row offered, collisions discovered by the claim."""
    from prospector.run import _drop_leased

    class _Broken:
        def leased(self):
            raise RuntimeError("db locked")

    rows = [{"candidate_id": "a"}]
    assert _drop_leased(rows, _Broken()) == (rows, 0)


def test_a_dead_workers_lease_is_reclaimed_instead_of_waiting_out_the_ttl(tmp_path):
    """`lease_ttl_s` is 7200, sized off the worst measured vet so a LIVE worker is never expired
    mid-vet. Applied to a worker that is gone, that same number parks the row for two hours. The
    consumer is SIGKILLed routinely (it ignores SIGTERM mid-wave), so on 2026-08-16 four dead
    processes held the 24 best rows and the queue judged nothing."""
    from prospector.run import _drop_leased

    store = _store(tmp_path)
    _row(store, "a")
    _row(store, "b")
    # Pid 0 is never a real process here, and `os.kill(0, 0)` would signal the whole process
    # group — so the owner is a pid that has certainly exited instead.
    import subprocess
    p = subprocess.Popen(["true"])
    p.wait()
    dead_owner = f"{p.pid}:deadbeef"
    store.claim("a", dead_owner, 7200)
    store.claim("b", f"{os.getpid()}:alive", 7200)

    kept, dropped = _drop_leased([{"candidate_id": "a"}, {"candidate_id": "b"}], store)

    assert [r["candidate_id"] for r in kept] == ["a"], (
        "the dead worker's row must come back; the live worker's must not")
    assert dropped == 1
    # RELEASED, not merely ignored: `store.claim` still honours an unexpired lease, so a row the
    # filter waved through without releasing would come back as _LEASE_HELD and waste the slot.
    assert store.claim("a", "next-worker", 60) is True


def test_an_unparsable_or_foreign_owner_is_treated_as_alive(tmp_path):
    """Unsure means alive. A false 'gone' puts two workers on one row, which is the double
    publish the lease exists to prevent; a false 'alive' costs one row a wait."""
    from prospector.run import _owner_is_gone

    assert _owner_is_gone("not-a-pid:abc") is False
    assert _owner_is_gone("") is False
    assert _owner_is_gone(f"{os.getpid()}:abc") is False


# ---------------------------------------------------------------------------------------------
# A PID IS ONLY MEANINGFUL ON THE MACHINE THAT MINTED IT.
#
# Owners were `pid:uuid`, and `_owner_is_gone` asked `os.kill(pid, 0)` about them. That is a
# question about OUR process table, and it was correct for exactly as long as the docstring's
# stated premise held: "every worker in this system runs on this machine — the engine is local by
# design." The engine moved to Fly on 2026-08-18 and task #60 is to run more than one instance,
# which retires that premise. Two machines pick pids from separate spaces, so machine B asking
# about machine A's pid usually gets ProcessLookupError, calls a live worker gone, reclaims the
# row and puts two workers on one candidate — the double publish the lease exists to prevent.
#
# These tests pin the host segment. They are the reason multi-instance is safe to attempt at all,
# so they must fail if anyone drops the host back out of the owner string.
# ---------------------------------------------------------------------------------------------

def test_a_live_worker_on_another_machine_is_never_declared_gone():
    """The cross-machine double-publish: `os.kill` is not asked at all about a foreign host.

    Documents the rule; it is NOT the test that would have stopped the defect. Fed a three-part
    owner, the pre-fix parser took `host` as the pid, found it non-numeric and returned False, so
    this passed before the fix too. The bug was in the MINT, not the parse — the owner had no host
    to check. `test_every_lease_owner_carries_the_host_that_minted_it` is the load-bearing one,
    and it does fail on the old `pid:uuid` format. Verified rather than assumed, 2026-08-19."""
    from prospector.run import _owner_is_gone

    # A pid that certainly does not exist HERE, owned by a host that is not this one. Before the
    # host segment this returned True and the row was reclaimed under a working worker.
    assert _owner_is_gone("some-other-fly-machine:999999:abc") is False
    # And the reverse: a pid that IS alive here, but minted elsewhere, is still not ours to judge.
    assert _owner_is_gone(f"some-other-fly-machine:{os.getpid()}:abc") is False


def test_a_dead_worker_on_this_machine_is_still_reclaimed():
    """The host check must not cost us the 2026-08-16 fix. Same host, exited pid, still gone."""
    import subprocess

    from prospector.run import _host_id, _owner_is_gone

    p = subprocess.Popen(["true"])
    p.wait()
    assert _owner_is_gone(f"{_host_id()}:{p.pid}:deadbeef") is True


def test_every_lease_owner_carries_the_host_that_minted_it():
    """Both mint sites go through one function, so a new caller cannot reintroduce `pid:uuid`."""
    from prospector.run import _host_id, _mint_lease_owner

    owner = _mint_lease_owner()
    parts = owner.split(":")
    assert len(parts) == 3, f"expected host:pid:uuid, got {owner!r}"
    assert parts[0] == _host_id()
    assert parts[1] == str(os.getpid())
    assert _mint_lease_owner() != owner, "the uuid makes it per-invocation, not per-process"


def test_the_host_id_is_never_empty(monkeypatch):
    """An empty host segment would parse as a legacy `pid:uuid` owner and silently re-open the
    cross-machine hole, which is the one failure mode that must not degrade quietly."""
    from prospector import audit as audit_mod
    from prospector import run as run_mod

    monkeypatch.setenv("FLY_MACHINE_ID", "80d34da6636478")
    assert run_mod._host_id() == "80d34da6636478"

    monkeypatch.delenv("FLY_MACHINE_ID", raising=False)
    # Patched on `audit`, not on `run`: there is ONE definition of the host and `run._host_id`
    # delegates to it, so the lease and the consumer heartbeat cannot answer differently.
    monkeypatch.setattr(audit_mod.socket, "gethostname", lambda: "")
    assert run_mod._host_id() == "unknown"


def test_a_legacy_owner_minted_before_the_host_segment_still_reclaims(tmp_path):
    """Rows already in the store carry `pid:uuid`. They must keep the old behaviour rather than
    read as foreign-and-alive, or the dead-worker reclaim regresses for one whole `lease_ttl_s`
    on exactly the rows most likely to be stuck. They age out and stop appearing."""
    import subprocess

    from prospector.run import _owner_is_gone

    p = subprocess.Popen(["true"])
    p.wait()
    assert _owner_is_gone(f"{p.pid}:deadbeef") is True

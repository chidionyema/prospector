"""R2 — per-candidate claim lock: mutual exclusion, expiry, and isolation.

The load-bearing tests here are the two CONCURRENCY ones. An assertion about a single-threaded
`claim()` call proves nothing about a lock: the defect R2 exists to fix is a backlog drain and a
manual `vet --resume` running as separate processes and both picking up the same candidate. So
this file contends for real — 8 threads and 6 SUBPROCESSES on one id — and asserts exactly one
winner, both on a free lock and on the harder case of an expired one (where a naive
"unlink then create" implementation lets every worker win).

Every test points the lock directory at `tmp_path`. Nothing here may touch store/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from prospector import claim_lock
from prospector.claim_lock import DEFAULT_STALE_AFTER_S, ClaimLock

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lock(tmp_path) -> ClaimLock:
    return ClaimLock(tmp_path / "claims", stale_after_s=DEFAULT_STALE_AFTER_S)


# ---------------------------------------------------------------------------
# Basic exclusivity contract
# ---------------------------------------------------------------------------

def test_second_caller_for_same_key_gets_false_and_does_not_block(lock):
    assert lock.claim("cand-1", "revet") is True
    t0 = time.monotonic()
    assert lock.claim("cand-1", "revet") is False
    # "Never blocks" is part of the contract: a drain that waits on a lock stops draining.
    assert time.monotonic() - t0 < 0.5


def test_release_frees_the_claim(lock):
    assert lock.claim("cand-1") is True
    lock.release("cand-1")
    assert lock.claim("cand-1") is True


def test_a_different_id_or_purpose_is_a_different_claim(lock):
    assert lock.claim("cand-1", "revet") is True
    assert lock.claim("cand-2", "revet") is True
    assert lock.claim("cand-1", "publish") is True


def test_context_manager_releases_even_on_exception(lock):
    with pytest.raises(RuntimeError):
        with lock.claiming("cand-1") as got:
            assert got is True
            raise RuntimeError("re-vet blew up")
    assert lock.claim("cand-1") is True, "an exception must not leak the claim"


def test_context_manager_yields_false_when_held_and_does_not_release_it(lock):
    assert lock.claim("cand-1") is True
    other = ClaimLock(lock.dir)
    with other.claiming("cand-1") as got:
        assert got is False
    # The loser must not have unlinked the winner's lock on its way out.
    assert other.claim("cand-1") is False


# ---------------------------------------------------------------------------
# Concurrency — the tests that actually prove the lock
# ---------------------------------------------------------------------------

def test_exactly_one_of_eight_threads_wins(tmp_path):
    d = tmp_path / "claims"
    barrier = threading.Barrier(8)
    wins: list[int] = []
    lk = threading.Lock()

    def worker(i: int) -> None:
        own = ClaimLock(d)          # separate instances: no shared in-process state
        barrier.wait()
        if own.claim("contended", "revet"):
            with lk:
                wins.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(wins) == 1, f"expected exactly 1 winner, got {wins}"


def test_exactly_one_of_eight_threads_wins_when_stealing_an_expired_lock(tmp_path):
    """The hard case. A naive expiry ("if stale: unlink; create") lets EVERY contender win,
    because they all unlink and all re-create. Mutual exclusion has to survive the moment a
    peer crashed, which is the only moment expiry ever runs."""
    d = tmp_path / "claims"
    dead = ClaimLock(d, stale_after_s=1.0, clock=lambda: 1000.0)
    assert dead.claim("contended", "revet") is True     # holder "crashes" here

    barrier = threading.Barrier(8)
    wins: list[int] = []
    lk = threading.Lock()

    def worker(i: int) -> None:
        # Same wall clock, 10 000s later: the lock above is long expired for all 8 of them.
        own = ClaimLock(d, stale_after_s=1.0, clock=lambda: 11000.0)
        barrier.wait()
        if own.claim("contended", "revet"):
            with lk:
                wins.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(wins) == 1, f"expected exactly 1 winner stealing a stale lock, got {wins}"


_CHILD = """
import sys, time
sys.path.insert(0, {repo!r})
from pathlib import Path
from prospector.claim_lock import ClaimLock
d, start = sys.argv[1], float(sys.argv[2])
lock = ClaimLock(Path(d))
while time.time() < start:
    time.sleep(0.002)
print("WIN" if lock.claim("contended", "revet") else "LOSE", flush=True)
"""


def test_exactly_one_of_six_processes_wins(tmp_path):
    """Cross-PROCESS exclusion — the actual R2 scenario (daemon drain vs `vet --resume`).

    Threads share one interpreter, so they cannot rule out an implementation that happens to
    be protected by the GIL or by a process-local set. Six independent interpreters can."""
    d = tmp_path / "claims"
    script = _CHILD.format(repo=str(REPO_ROOT))
    start = time.time() + 1.5
    procs = [subprocess.Popen([sys.executable, "-c", script, str(d), str(start)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(6)]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=90)
        assert p.returncode == 0, f"child failed: {err[-400:]}"
        outs.append(out.strip())
    assert outs.count("WIN") == 1, f"expected exactly 1 winner across processes, got {outs}"
    assert outs.count("LOSE") == 5


# ---------------------------------------------------------------------------
# Crash safety / expiry
# ---------------------------------------------------------------------------

def test_a_lock_older_than_stale_after_s_expires(tmp_path):
    now = [1000.0]
    dead = ClaimLock(tmp_path / "claims", stale_after_s=60.0, clock=lambda: now[0])
    assert dead.claim("cand-1") is True
    live = ClaimLock(tmp_path / "claims", stale_after_s=60.0, clock=lambda: now[0])
    assert live.claim("cand-1") is False        # still fresh
    now[0] = 1000.0 + 61.0
    assert live.claim("cand-1") is True, "a crashed holder's lock must expire, not deadlock"


def test_a_fresh_lock_is_never_stolen(tmp_path):
    now = [1000.0]
    a = ClaimLock(tmp_path / "claims", stale_after_s=3600.0, clock=lambda: now[0])
    assert a.claim("cand-1") is True
    now[0] += 3599.0
    b = ClaimLock(tmp_path / "claims", stale_after_s=3600.0, clock=lambda: now[0])
    assert b.claim("cand-1") is False


def test_release_refuses_to_unlink_a_lock_that_was_stolen_from_us(tmp_path):
    """After our claim expired and another worker took it, our late `release()` must not
    remove THEIR lock — that would hand the candidate to a third worker while it is live."""
    now = [1000.0]
    a = ClaimLock(tmp_path / "claims", stale_after_s=10.0, clock=lambda: now[0])
    assert a.claim("cand-1") is True
    now[0] += 100.0
    b = ClaimLock(tmp_path / "claims", stale_after_s=10.0, clock=lambda: now[0])
    assert b.claim("cand-1") is True             # stole it, legitimately
    a.release("cand-1")                          # the crashed-then-resumed original
    assert b.holder("cand-1") is not None, "the live holder's lock was unlinked by a stale peer"


def test_a_stale_steal_guard_cannot_deadlock_the_steal(tmp_path):
    """A worker that dies between creating the steal guard and removing it must not wedge the
    lock forever — the `backlog-brake-can-deadlock-on-orphans` shape."""
    d = tmp_path / "claims"
    now = [1000.0]
    dead = ClaimLock(d, stale_after_s=10.0, clock=lambda: now[0])
    assert dead.claim("cand-1") is True
    path = dead.path_for("cand-1")
    guard = path.with_name(path.name + ".steal")
    guard.write_text(json.dumps({"ts": now[0], "pid": 1}), encoding="utf-8")
    now[0] += 10_000.0                            # both the lock and the guard are ancient
    live = ClaimLock(d, stale_after_s=10.0, clock=lambda: now[0])
    assert live.claim("cand-1") is True
    assert not guard.exists()


def test_holder_records_pid_and_purpose(lock):
    assert lock.claim("cand-1", "revet") is True
    h = lock.holder("cand-1", "revet")
    assert h is not None
    assert h["purpose"] == "revet" and h["candidate_id"] == "cand-1" and h["pid"] > 0


# ---------------------------------------------------------------------------
# Config plumbing — enabled by default, resolved LAZILY, never in the live store
# ---------------------------------------------------------------------------

def test_enabled_defaults_true_on_a_config_with_no_claim_lock_block():
    assert claim_lock.enabled(SimpleNamespace()) is True
    assert claim_lock.stale_after_s(SimpleNamespace()) == DEFAULT_STALE_AFTER_S


def test_disabled_config_lets_every_caller_through(tmp_path):
    cfg = SimpleNamespace(store_dir=tmp_path, claim_lock={"enabled": False})
    assert claim_lock.for_config(cfg) is None
    with claim_lock.claiming("cand-1", cfg=cfg) as a, claim_lock.claiming("cand-1", cfg=cfg) as b:
        assert a is True and b is True, "disabled must mean pre-rail behaviour, not a hard stop"


def test_lock_dir_defaults_under_store_dir_and_is_created_lazily(tmp_path):
    cfg = SimpleNamespace(store_dir=tmp_path)
    assert claim_lock.lock_dir(cfg) == tmp_path / "claims"
    # Resolving the path must not create anything: the directory appears on the first CLAIM,
    # which is what keeps a production path from being touched at import/collection time.
    assert not (tmp_path / "claims").exists()
    lk = claim_lock.for_config(cfg)
    assert lk is not None and lk.claim("cand-1") is True
    assert (tmp_path / "claims").is_dir()


def test_explicit_dir_overrides_store_dir(tmp_path):
    cfg = SimpleNamespace(store_dir=tmp_path / "store",
                          claim_lock={"dir": str(tmp_path / "elsewhere")})
    assert claim_lock.lock_dir(cfg) == tmp_path / "elsewhere"


def test_a_cfg_with_no_store_dir_raises_rather_than_guessing():
    """`scheduler/paths.py`'s policy, for the same reason: a cwd-relative default resolves to
    the LIVE store under pytest."""
    with pytest.raises(ValueError, match="store_dir"):
        claim_lock.lock_dir(SimpleNamespace())


def test_stale_after_s_is_read_from_config(tmp_path):
    cfg = SimpleNamespace(store_dir=tmp_path, claim_lock={"stale_after_s": 7})
    assert claim_lock.stale_after_s(cfg) == 7.0
    cfg_bad = SimpleNamespace(store_dir=tmp_path, claim_lock={"stale_after_s": "nonsense"})
    assert claim_lock.stale_after_s(cfg_bad) == DEFAULT_STALE_AFTER_S


# ---------------------------------------------------------------------------
# The kill_decay wire-in (R2's actual consumer)
# ---------------------------------------------------------------------------

def _write_kill(store: Path, cid: str, days_ago: int) -> None:
    import datetime as dt
    (store / "dossiers").mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    (store / "dossiers" / f"{cid}.kill.json").write_text(json.dumps({
        "candidate_id": cid, "verdict": "KILL", "killed_at": ts.isoformat(),
        "domain": "logistics"}), encoding="utf-8")


def test_decay_walker_skips_a_candidate_another_worker_already_claimed(tmp_path):
    from prospector.kill_decay import REVET_PURPOSE, iter_revet_claims

    store = tmp_path / "store"
    for cid, age in (("aaa", 200), ("bbb", 300), ("ccc", 400)):
        _write_kill(store, cid, age)
    cfg = SimpleNamespace(store_dir=store)

    # A concurrent drain is already re-vetting "bbb".
    drain = claim_lock.for_config(cfg)
    assert drain is not None and drain.claim("bbb", REVET_PURPOSE) is True

    seen = list(iter_revet_claims(store, cfg, half_life_days=30, revisit_below=0.5))
    assert "bbb" not in seen, "the walker paid for a re-vet the drain is already running"
    assert sorted(seen) == ["aaa", "ccc"]


def test_decay_walker_releases_each_claim_as_it_moves_on(tmp_path):
    from prospector.kill_decay import REVET_PURPOSE, iter_revet_claims

    store = tmp_path / "store"
    _write_kill(store, "aaa", 200)
    _write_kill(store, "bbb", 300)
    cfg = SimpleNamespace(store_dir=store)
    probe = claim_lock.for_config(cfg)
    assert probe is not None

    held: list[bool] = []
    for cid in iter_revet_claims(store, cfg):
        held.append(probe.claim(cid, REVET_PURPOSE))   # must be False WHILE it is being worked
    assert held == [False, False]
    # …and free again once the walk is over.
    assert probe.claim("aaa", REVET_PURPOSE) is True


def test_decay_walker_releases_the_claim_when_the_body_raises(tmp_path):
    from prospector.kill_decay import REVET_PURPOSE, iter_revet_claims

    store = tmp_path / "store"
    _write_kill(store, "aaa", 200)
    cfg = SimpleNamespace(store_dir=store)
    walk = iter_revet_claims(store, cfg)
    with pytest.raises(RuntimeError):
        for _cid in walk:
            raise RuntimeError("re-vet exploded")
    walk.close()
    probe = claim_lock.for_config(cfg)
    assert probe is not None and probe.claim("aaa", REVET_PURPOSE) is True


def test_recent_kills_are_not_re_vetted(tmp_path):
    from prospector.kill_decay import decayed_kill_ids

    store = tmp_path / "store"
    _write_kill(store, "fresh", 1)
    _write_kill(store, "old", 400)
    ids = decayed_kill_ids(store, half_life_days=30, revisit_below=0.5)
    assert ids == ["old"]

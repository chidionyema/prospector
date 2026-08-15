"""An unreadable claim file must not read as an unheld one.

THE DEFECT. `ClaimLock._age` returned `None` for BOTH "the lock file does not exist" and "the
lock file exists and could not be read" (EACCES, EIO, a path that is not a regular file).
`_is_stale` answers True for `None` — correct for absence, because retrying the O_EXCL create is
the right next move — so an unreadable lock held by a LIVE peer was judged an expired corpse.

That is the fail-open direction in the one module whose entire job is that exactly one caller
machine-wide wins (`claim_lock.py` module docstring; `health._claim_probe` is the caller that
pays for a second winner). Two winners means one re-vet paid for twice.

The distinction pinned here is `_age`: absent → `None`, present-but-unreadable →
`_AGE_UNREADABLE`, which are different values and produce different `_is_stale` answers.
A test that only checked "an old lock is stealable" would have passed before and after.
"""
from __future__ import annotations

import logging

import pytest

from prospector.claim_lock import _AGE_UNREADABLE, ClaimLock


def _unreadable_lock_at(lock: ClaimLock, cid: str):
    """Make the lock path EXIST but be unopenable as a file.

    A directory is used rather than `chmod 000` so the test means the same thing when the suite
    runs as root, where mode bits are not enforced. `Path.read_text` raises `IsADirectoryError`,
    which is an `OSError` — the exact class the handler under test absorbs.
    """
    p = lock.path_for(cid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()
    return p


def test_absent_and_unreadable_are_different_ages(tmp_path):
    lock = ClaimLock(tmp_path, stale_after_s=1.0, clock=lambda: 1_000.0)
    path = lock.path_for("cand-1")

    # Absent: no lock at all. None, and "stale" is the right answer because the caller retries
    # the create rather than unlinking anything.
    assert lock._age(path) is None
    assert lock._is_stale(path) is True

    # Present but unreadable. This is the case that used to be indistinguishable from absence.
    _unreadable_lock_at(lock, "cand-1")
    assert lock._age(path) == _AGE_UNREADABLE
    assert lock._age(path) is not None, "an unreadable lock must not report as an absent one"
    assert lock._is_stale(path) is False, "an unreadable lock must not be judged a corpse"


def test_an_unreadable_lock_is_never_stealable_however_old_the_clock(tmp_path):
    """Even a clock far past `stale_after_s` must not turn an unreadable lock into a free one."""
    lock = ClaimLock(tmp_path, stale_after_s=1.0, clock=lambda: 1e12)
    _unreadable_lock_at(lock, "cand-2")
    assert lock._is_stale(lock.path_for("cand-2")) is False
    assert lock.claim("cand-2") is False


def test_an_unreadable_lock_is_reported_at_error(tmp_path, caplog):
    lock = ClaimLock(tmp_path, stale_after_s=1.0, clock=lambda: 1_000.0)
    _unreadable_lock_at(lock, "cand-3")
    with caplog.at_level(logging.ERROR, logger="prospector.claim_lock"):
        lock._age(lock.path_for("cand-3"))
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], \
        "a lock we cannot read is a fact about the filesystem an operator must see"


def test_a_holder_we_cannot_read_is_not_silently_reported_unheld(tmp_path, caplog):
    """`holder()` still answers None — it decides nothing — but the two Nones now differ in the log."""
    lock = ClaimLock(tmp_path, stale_after_s=60.0, clock=lambda: 1_000.0)

    with caplog.at_level(logging.ERROR, logger="prospector.claim_lock"):
        assert lock.holder("never-claimed") is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], \
        "a lock nobody ever took is an ordinary None and must stay silent"

    caplog.clear()
    _unreadable_lock_at(lock, "cand-4")
    with caplog.at_level(logging.ERROR, logger="prospector.claim_lock"):
        assert lock.holder("cand-4") is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_release_that_cannot_verify_the_token_says_so(tmp_path, caplog):
    """Failing to release holds the key for the full expiry; that must not be silent."""
    lock = ClaimLock(tmp_path, stale_after_s=60.0, clock=lambda: 1_000.0)
    assert lock.claim("cand-5") is True
    path = lock.path_for("cand-5")
    path.unlink()
    path.mkdir()                          # present, unreadable: cannot prove the claim is ours

    with caplog.at_level(logging.ERROR, logger="prospector.claim_lock"):
        lock.release("cand-5")
    assert path.is_dir(), "an unverifiable claim must NOT be unlinked"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("cid", ["a", "b"])
def test_the_happy_path_is_unchanged(tmp_path, cid):
    lock = ClaimLock(tmp_path, stale_after_s=60.0, clock=lambda: 1_000.0)
    assert lock.claim(cid) is True
    assert lock.claim(cid) is False
    lock.release(cid)
    assert lock.claim(cid) is True

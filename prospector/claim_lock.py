"""Per-candidate claim lock (register item R2).

WHY THIS EXISTS
---------------
Three code paths re-vet a backlogged candidate: the scheduler's automatic drain
(`scheduler/run_scheduled.py::_drain_pass`), a manual `vet --resume`, and the decay walker
(`kill_decay.py`). Nothing stopped two of them picking up the SAME candidate id at the same
time, so the same re-vet was paid for twice — twice the subscription CLI calls, two dossier
writes racing on one path, and (worse) two rows in the drain ledger for one candidate.

The idiom is deliberately the same one `health.py:130-153` (`_claim_probe`) already proves in
this repo: exactly one caller machine-wide wins a slot, decided by an atomic filesystem
operation rather than by a lock held in one process's memory. `_claim_probe` uses a compare-
and-write inside a single small JSON file; that works because the probe slot is per-PROVIDER
(a handful of names). A claim is per-CANDIDATE (thousands of ids, taken and released
constantly), so one shared file would serialise every worker on one rewrite. The exclusive
primitive here is therefore the directory entry itself: `os.open(O_CREAT | O_EXCL)`, which the
kernel makes atomic — the same guarantee, one file per claim.

DESIGN CONSTRAINTS, each of which is a scar in this codebase
------------------------------------------------------------
* **Never blocks.** `claim()` returns False immediately when someone else holds it. A drain
  that waits on a lock is a drain that stops draining.
* **Crash-safe.** A lock whose holder died must expire (`stale_after_s`). A lock that outlives
  a crashed process forever is a deadlock, and this repo already carries
  `backlog-brake-can-deadlock-on-orphans` as exactly that scar. There is no unlock-on-exit
  mechanism the OS gives us for free here (macOS has no `flock(1)`/`setsid(1)`), so expiry is
  the only recovery path and it must be automatic.
* **Lazily resolved paths.** The lock directory is computed at CALL time from `cfg`, never
  bound at import. Four separate incidents in this repo (the audit log, the durable ledger,
  the price stores, the cockpit home card) all had the same shape: a module bound a directory
  at import, so pytest wrote into production state.
* **Released on exception.** `claiming()` is a context manager; a re-vet that raises still
  frees the candidate for the next worker.

STEALING A STALE LOCK IS ITSELF A RACE, and is handled explicitly. If two workers both see an
expired lock, both unlink it and both re-create it, they BOTH win — mutual exclusion silently
gone in exactly the situation (a crashed peer) where it matters most. So expiry runs under a
second O_EXCL "steal" file: only the worker that creates `<lock>.steal` may remove the stale
lock, and the winner of the subsequent O_EXCL create is still the single holder. The steal
file carries its own timestamp so a worker that dies mid-steal cannot deadlock the steal.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

#: Default expiry. Long enough that a slow but LIVE re-vet is never stolen from (a full vet is
#: minutes, not an hour), short enough that a crashed worker's candidate re-enters the drain
#: the same day. Overridable via `claim_lock.stale_after_s`.
DEFAULT_STALE_AFTER_S = 3600.0

#: The only purpose in use today. It is part of the key, not a comment: a future "publish" or
#: "backfill" claim on the same candidate must not collide with a re-vet claim.
DEFAULT_PURPOSE = "revet"

_STEAL_SUFFIX = ".steal"
#: A steal is a handful of syscalls. Anything older than this is a worker that died holding it.
_STEAL_STALE_S = 60.0

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: `_age` for a lock file that EXISTS but could not be read. It is deliberately NOT `None`
#: (which `_is_stale` reads as "absent — retry the create") and deliberately not a large age
#: (which reads as "expired — steal it"). An unreadable lock must be assumed LIVE, so it dates
#: as freshly taken and expiry declines to touch it. Before this, an EACCES/EIO on a HELD lock
#: returned exactly what an absent lock returns, i.e. it read as permission to steal — the
#: fail-open direction in the one module whose whole job is that exactly one caller wins.
_AGE_UNREADABLE = 0.0


# --------------------------------------------------------------------------------------
# Config accessors — read `cfg.claim_lock`, tolerate its absence, resolve LAZILY
# --------------------------------------------------------------------------------------

def _settings(cfg) -> dict:
    """The `claim_lock` config block as a plain dict, or {} when the config has none.

    Read through `getattr` with a default rather than a typed field so this module works
    against a `Config` that predates the block, and against the `SimpleNamespace` doubles the
    scheduler tests build."""
    raw = getattr(cfg, "claim_lock", {}) or {}
    if isinstance(raw, dict):
        return raw
    return {k: getattr(raw, k) for k in ("enabled", "dir", "stale_after_s") if hasattr(raw, k)}


def enabled(cfg) -> bool:
    """True unless explicitly switched off. Default TRUE: this is a correctness rail — paying
    twice for one re-vet is a defect in every configuration — not an experiment."""
    return bool(_settings(cfg).get("enabled", True))


def stale_after_s(cfg) -> float:
    try:
        v = float(_settings(cfg).get("stale_after_s", DEFAULT_STALE_AFTER_S) or 0)
    except (TypeError, ValueError):
        return DEFAULT_STALE_AFTER_S
    return v if v > 0 else DEFAULT_STALE_AFTER_S


def lock_dir(cfg) -> Path:
    """Where claim files live: `claim_lock.dir`, else `<store.dir>/claims`.

    Resolved on every call, never cached at import — see the module docstring. `store_dir` is
    taken from the cfg (which honours PROSPECTOR_STORE_DIR) and there is deliberately NO
    cwd-relative fallback, for the reason `scheduler/paths.py` documents at length: a default
    of "store" resolves to the LIVE store under pytest."""
    configured = str(_settings(cfg).get("dir", "") or "").strip()
    if configured:
        return Path(configured)
    root = getattr(cfg, "store_dir", None)
    if root is None:
        raise ValueError(
            f"{type(cfg).__name__} has no store_dir and claim_lock.dir is unset; refusing to "
            "guess. A cwd-relative default resolves to the LIVE store under pytest. Tests must "
            "pass claim_lock={'dir': str(tmp_path)} or store_dir=tmp_path."
        )
    return Path(root) / "claims"


# --------------------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------------------

class ClaimLock:
    """Exclusive, non-blocking, self-expiring claims on `(candidate_id, purpose)` pairs.

    `clock` is injectable so expiry is testable without sleeping. It is a WALL clock (like
    `health.py`'s) rather than a monotonic one, because the holders are separate processes and
    only wall time is comparable across them."""

    def __init__(self, directory: Path, *, stale_after_s: float = DEFAULT_STALE_AFTER_S,
                 clock=time.time):
        self._dir = Path(directory)
        self._stale_after_s = float(stale_after_s) if stale_after_s and stale_after_s > 0 \
            else DEFAULT_STALE_AFTER_S
        self._clock = clock
        #: token per held key, so `release` can refuse to unlink a lock that was stolen from us
        #: after our own claim expired. Releasing someone else's claim is the same defect as
        #: never releasing our own, in the opposite direction.
        self._tokens: dict[tuple[str, str], str] = {}

    @property
    def dir(self) -> Path:
        return self._dir

    def path_for(self, candidate_id: str, purpose: str = DEFAULT_PURPOSE) -> Path:
        """One file per (id, purpose). The name is readable for a human debugging a stuck
        drain AND disambiguated by a digest of the raw key, so two ids that sanitise to the
        same slug still get different files."""
        key = f"{purpose}\x00{candidate_id}"
        slug = _SAFE.sub("-", f"{purpose}__{candidate_id}").strip("-")[:96] or "claim"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        return self._dir / f"{slug}.{digest}.lock"

    # -- acquisition ---------------------------------------------------------------

    def claim(self, candidate_id: str, purpose: str = DEFAULT_PURPOSE) -> bool:
        """Take the claim, or return False IMMEDIATELY if another worker holds it.

        Never blocks and never raises on contention. The only writes are one O_EXCL create
        (and, when an expired lock is in the way, one steal-guarded unlink)."""
        path = self.path_for(candidate_id, purpose)
        if self._create(path, candidate_id, purpose):
            return True
        if not self._is_stale(path):
            return False
        if not self._expire(path):
            # Someone else is stealing it right now; they will win. Do not queue behind them.
            return False
        return self._create(path, candidate_id, purpose)

    def release(self, candidate_id: str, purpose: str = DEFAULT_PURPOSE) -> None:
        """Drop a claim we hold. Silently does nothing if the file is gone or is no longer
        ours (our claim expired and another worker legitimately stole it)."""
        key = (candidate_id, purpose)
        token = self._tokens.pop(key, None)
        path = self.path_for(candidate_id, purpose)
        if token is not None:
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return                    # already gone: released, or legitimately stolen
            except (OSError, ValueError) as exc:
                # PRESENT but unreadable, so we cannot prove the claim is still ours and must not
                # unlink it. The consequence is real and was invisible: this key stays locked
                # until `stale_after_s` expires it (an hour by default), so the drain skips the
                # same candidate every pass. Silence made that indistinguishable from a release.
                logger.error(
                    "claim_lock: cannot verify the holder of %s, so the claim is NOT released and "
                    "the candidate stays locked until it expires (%.0fs): %s",
                    path, self._stale_after_s, exc)
                return
            if holder.get("token") != token:
                return
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.error(
                "claim_lock: could not unlink %s; the claim is held until it expires (%.0fs): %s",
                path, self._stale_after_s, exc)

    def holder(self, candidate_id: str, purpose: str = DEFAULT_PURPOSE) -> Optional[dict]:
        """The recorded holder of a live claim (pid/host/ts/token), or None. Diagnostics only —
        `claim()` is the decision, this is the explanation."""
        path = self.path_for(candidate_id, purpose)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None                   # nobody holds it: the honest answer
        except (OSError, ValueError) as exc:
            # A lock that exists and cannot be read is reported here as "unheld", which it may
            # well not be. That is the safe direction for a diagnostic (this never decides
            # anything — `claim()` does) but it is a LIE with a confident face if it is silent.
            logger.error("claim_lock: %s exists but is unreadable; reporting it as unheld, which "
                         "it may not be: %s", path, exc)
            return None
        return data if not self._stale_record(data, path) else None

    @contextmanager
    def claiming(self, candidate_id: str,
                 purpose: str = DEFAULT_PURPOSE) -> Iterator[bool]:
        """`with lock.claiming(cid) as got:` — released on the way out, INCLUDING on exception.

        Yields the boolean rather than raising on contention: "someone else has it" is an
        ordinary, expected outcome for a drain, not an error."""
        got = self.claim(candidate_id, purpose)
        try:
            yield got
        finally:
            if got:
                self.release(candidate_id, purpose)

    # -- internals -----------------------------------------------------------------

    def _create(self, path: Path, candidate_id: str, purpose: str) -> bool:
        """The exclusive primitive. O_CREAT|O_EXCL is atomic on any single POSIX filesystem,
        which is the whole basis of mutual exclusion here."""
        token = uuid.uuid4().hex
        record = {"token": token, "pid": os.getpid(), "host": socket.gethostname(),
                  "ts": self._clock(), "candidate_id": candidate_id, "purpose": purpose}
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        except OSError:
            # An unwritable lock dir must not silently disable the rail by returning True, and
            # must not crash a drain either. Refusing the claim is the safe direction: the
            # candidate is skipped this pass rather than re-vetted twice.
            return False
        try:
            os.write(fd, json.dumps(record).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._tokens[(candidate_id, purpose)] = token
        return True

    def _age(self, path: Path) -> Optional[float]:
        """Seconds since the lock was taken, or None if it does not exist.

        Prefers the `ts` written INSIDE the file over the inode mtime: the injected clock has
        to govern expiry for expiry to be testable, and a file copied/rsynced between trees
        keeps its content but not necessarily its mtime.

        ABSENT AND UNREADABLE ARE DIFFERENT ANSWERS. Both used to return None, and None means
        "stale" to `_is_stale` — so an EACCES/EIO on a lock a peer was actively holding read as
        an expired corpse. See `_AGE_UNREADABLE`."""
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.error("claim_lock: %s exists but is unreadable; dating it as freshly held "
                         "rather than stealable: %s", path, exc)
            return _AGE_UNREADABLE
        try:
            ts = float(json.loads(raw).get("ts", 0) or 0)
        except (ValueError, AttributeError, TypeError):
            ts = 0.0
        if ts <= 0:
            try:
                ts = path.stat().st_mtime
            except FileNotFoundError:
                return None
            except OSError as exc:
                logger.error("claim_lock: cannot stat %s to date it; treating it as freshly held "
                             "rather than stealable: %s", path, exc)
                return _AGE_UNREADABLE
        return self._clock() - ts

    def _stale_record(self, data: dict, path: Path) -> bool:
        try:
            ts = float(data.get("ts", 0) or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts <= 0:
            try:
                ts = path.stat().st_mtime
            except OSError:
                return True
        return (self._clock() - ts) > self._stale_after_s

    def _is_stale(self, path: Path) -> bool:
        """True if the lock is expired OR already gone (either way, retrying the create is
        the right next move)."""
        age = self._age(path)
        if age is None:
            return True
        return age > self._stale_after_s

    def _unlink_corpse(self, path: Path) -> bool:
        """Remove a lock already judged dead. True if the path is now clear to re-create."""
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def _expire(self, path: Path) -> bool:
        """Remove an expired lock under a steal guard. True if it is now safe to re-create.

        Without the guard, two workers seeing the same expired lock would both unlink and both
        create, and mutual exclusion would be lost exactly when a peer has crashed. The guard
        is itself an O_EXCL create, so at most one worker is in this critical section; it
        re-checks staleness INSIDE the section, so a lock re-taken between the outer check and
        here is not stolen from its live new holder."""
        steal = path.with_name(path.name + _STEAL_SUFFIX)
        steal_age = self._age(steal)
        if steal_age is not None and steal_age > _STEAL_STALE_S:
            try:
                steal.unlink()           # a worker died mid-steal; the steal must not deadlock
            except OSError:
                pass
        try:
            fd = os.open(str(steal), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except (FileExistsError, OSError):
            return False
        try:
            os.write(fd, json.dumps({"ts": self._clock(), "pid": os.getpid()}).encode("utf-8"))
        finally:
            os.close(fd)
        try:
            # ABSENT IS NOT STALE, AND THIS IS WHERE MUTUAL EXCLUSION WAS LOST.
            #
            # `_is_stale` answers True for a file that does not exist, which is right for the
            # caller in `claim()` (retrying the create is the correct next move) and WRONG here,
            # because this branch does not retry a create -- it unlinks. So a steal that arrived
            # while the path was momentarily empty read "stale", then unlinked whatever a peer
            # had created in the microseconds since, and BOTH threads went on to hold the claim:
            #
            #   T1  _expire: path absent -> "stale"
            #   T2  _create: O_EXCL succeeds, T2 now holds the claim
            #   T1  unlink() -- deletes T2's LIVE lock
            #   T1  _create: O_EXCL succeeds, T1 also holds the claim
            #
            # Reproduced 2 times in 400 under CPU load (2026-08-08), and it is the failure CI
            # kept surfacing on slower runners while a quiet laptop passed 5 of 5. The half-open
            # probe in `health.py` is the caller that pays for it: two winners means two callers
            # re-probe one dead brain, which is the exact double-spend the lock exists to stop.
            #
            # There is nothing to expire on an empty path. Return True and let the O_EXCL create
            # in `_create` arbitrate, which is the only thing that can arbitrate it.
            try:
                raw = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return True
            except OSError:
                return False

            try:
                record = json.loads(raw)
                if not isinstance(record, dict):
                    raise ValueError("lock record is not an object")
            except ValueError:
                # Unparseable, but PRESENT: either a peer's create caught mid-write (fresh, and
                # `_is_stale` already declines to steal it because the mtime fallback dates it to
                # real wall time) or a genuinely corrupt corpse. Keep the old mtime-based
                # judgement so a corrupt lock still expires rather than deadlocking the key
                # forever, and accept that it carries no token to verify against.
                if not self._is_stale(path):
                    return False
                return self._unlink_corpse(path)

            if not self._stale_record(record, path):
                return False             # re-taken while we were acquiring the guard

            # Only ever remove the exact corpse just judged stale. Re-read and compare the token
            # so that a lock legitimately released and re-taken between the judgement and the
            # unlink is not destroyed under its new, live holder.
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return True
            except (OSError, ValueError):
                return False
            if not isinstance(current, dict) or current.get("token") != record.get("token"):
                return False
            return self._unlink_corpse(path)
        finally:
            try:
                steal.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------------------
# Config-driven convenience API
# --------------------------------------------------------------------------------------

def for_config(cfg) -> Optional[ClaimLock]:
    """A ClaimLock built from `cfg`, or None when `claim_lock.enabled` is false.

    Built fresh per call: the lock holds no state that must be shared in-process (the OS holds
    it), and constructing it lazily is what keeps the directory out of import time."""
    if not enabled(cfg):
        return None
    return ClaimLock(lock_dir(cfg), stale_after_s=stale_after_s(cfg))


def claim(candidate_id: str, purpose: str = DEFAULT_PURPOSE, *, cfg=None) -> bool:
    """Module-level claim. Returns True when the rail is switched off — "disabled" must mean
    "behaves as it did before this rail existed", never "nothing may proceed"."""
    lock = for_config(cfg) if cfg is not None else None
    if lock is None:
        return True
    return lock.claim(candidate_id, purpose)


@contextmanager
def claiming(candidate_id: str, purpose: str = DEFAULT_PURPOSE, *, cfg=None) -> Iterator[bool]:
    """Config-driven context manager. Yields True (unconditionally) when disabled."""
    lock = for_config(cfg) if cfg is not None else None
    if lock is None:
        yield True
        return
    with lock.claiming(candidate_id, purpose) as got:
        yield got

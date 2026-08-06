"""Machine-wide concurrency governor for CLI subprocess brains (cursor / claude).

Why this exists
---------------
`cursor_cli.py` and `claude_cli.py` each bounded their subprocess fan-out with a
module-level `threading.Semaphore`. A `threading.Semaphore` bounds threads inside ONE
process; it cannot see subprocesses spawned by a different Python process. Prospector
routinely runs several pipelines at once — on 2026-07-31 the machine held four
concurrently:

    14926   prospector.run generate --candidates 5
    89119   prospector.run generate --candidates 5 --lane side_hustle --publish
    46516   prospector.scheduler.run_scheduled --daemon
    28570   tools/backfill_missing_listings.sh

Each was configured to `claude_concurrency: 2` and each believed it was holding the line
at 2, so the real ceiling was ~8. The cost is measurable, not theoretical: uncontended
exa search runs 2.1-4.2s and cursor_cli p50 is 41.7s (n=317), while claude_cli grounding
under that contention showed 98.5s mean / 264.3s max. Oversubscription is also what
produced the two failure signatures we kept chasing:

  * `claude cli slot acquire timed out after 45s (grounding queue saturated)` — the tail
    of job 20260730T212901866, which died at 1731s.
  * `cursor cli exhausted after 2 attempts` at exactly the 120s timeout, which returns an
    empty artifact and holds the pack back on `completeness gate: FAIL -> ["marketing
    'listing_page' is missing or empty"]`.

Both are queueing symptoms, so raising timeouts only moves them around. The fix is to
make the ceiling real across processes.

How
---
N lock files under a single machine-global directory, each held with `fcntl.flock(LOCK_EX
| LOCK_NB)`. Holding a slot file IS holding a slot, for every process on the machine.
flock is released by the kernel when the fd closes or the process dies, so a crashed or
SIGKILLed pipeline cannot leak a slot — there is no stale-lock reaper to get wrong.

Why the slot directory is NOT in the repo
-----------------------------------------
The first cut anchored the slot root to the checkout containing this file
(`os.path.dirname(__file__)/../store/.cli_slots`), which reintroduced the exact bug it was
written to kill — one directory per checkout instead of one per machine. Git worktrees are
full checkouts, and on 2026-07-31 this machine held seven, five of them carrying their own
copy of this module. Measured, not reasoned: two governors built with `n=1` from two
different worktrees BOTH acquired.

    slot root A: /Users/.../prospector/store/.cli_slots/proof
    slot root B: /Users/.../prospector-waitlist-worktree/store/.cli_slots/proof
    A.acquire(1s) -> True
    B.acquire(1s) -> True      # a real ceiling of 1 must refuse the second

So the effective ceiling was `n × checkouts`, and with `claude_concurrency: 8` that is up
to 40 concurrent CLI subprocesses on 12 cores — which is how a 16GB box reached load 592
with 18.49% CPU idle (i.e. blocked on page faults, not computing). Anchoring outside every
checkout is what makes the word "machine-wide" true, and it keeps being true for worktrees
that do not exist yet — nobody has to remember anything.

The public surface is deliberately identical to `threading.Semaphore` (`acquire(timeout=)`
/ `release()`) so both call sites stay drop-in.

Degradation: if the lock directory cannot be created or `fcntl` is unavailable (Windows),
this silently falls back to an in-process `threading.Semaphore` — i.e. exactly today's
behaviour. Never fail a run because the governor could not be set up.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time

try:
    import fcntl  # POSIX only
except ImportError:  # pragma: no cover — Windows
    fcntl = None  # type: ignore[assignment]

# Poll interval while waiting for a slot. flock(LOCK_NB) gives no "wait until free"
# primitive across files, so we spin. 0.25s keeps the busy-wait cost negligible against
# calls whose p50 is ~41s while staying responsive enough not to add real latency.
_POLL_S = 0.25


def _slot_root(name: str) -> str | None:
    """Directory holding this governor's slot files, or None if unusable.

    Deliberately independent of `__file__` and of cwd: every prospector process on this
    machine must resolve the same path, whichever checkout or worktree it was started
    from. See the module docstring for the measurement that forced this.
    """
    if fcntl is None:
        return None
    # PROSPECTOR_CLI_SLOTS is the escape hatch: tests that need a private ceiling point it
    # at a tmpdir, and it is also the way to deliberately isolate a run from the machine's
    # shared budget. Unset — the normal case — every process lands in the same home dir.
    #
    # It is a DIRECTORY, and it must be absolute. The name reads like a count, and on
    # 2026-08-05 a session set `PROSPECTOR_CLI_SLOTS=1` meaning "one slot": `_slot_root`
    # then resolved `1/cursor` against the cwd, created it inside the checkout, and returned
    # it — silently handing that process a private pool. That is the per-checkout ceiling
    # this module exists to kill (see the module docstring), reached through the front door.
    # A relative value is therefore refused, not honoured: the run falls back to the shared
    # home directory, which is the safe direction to fail.
    override = os.environ.get("PROSPECTOR_CLI_SLOTS")
    if override and not os.path.isabs(override):
        logging.getLogger(__name__).warning(
            "PROSPECTOR_CLI_SLOTS=%r is not an absolute path; it is a slot DIRECTORY, not a "
            "slot count. Ignoring it and using the machine-wide ceiling.",
            override,
        )
        override = None
    bases = [override] if override else []
    bases.append(os.path.join(os.path.expanduser("~"), ".prospector", "cli_slots"))
    # Last resort only. $TMPDIR is per-user on macOS but is also periodically swept, and a
    # swept slot directory silently widens the ceiling rather than failing loudly.
    bases.append(os.path.join(tempfile.gettempdir(), "prospector_cli_slots"))
    for base in bases:
        try:
            path = os.path.join(base, name)
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue
    return None


class CrossProcessSemaphore:
    """A counting semaphore whose count is enforced across processes, not just threads.

    Drop-in for `threading.Semaphore`: `acquire(timeout=...) -> bool` and `release()`.
    """

    def __init__(self, n: int, name: str) -> None:
        self._name = name
        self._n = max(1, int(n))
        self._root = _slot_root(name)
        self._local = threading.local()
        # Fallback path: behaves exactly as the old in-process governor did.
        self._fallback = threading.Semaphore(self._n) if self._root is None else None

    @property
    def limit(self) -> int:
        return self._n

    def _held(self) -> list:
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def _try_slot(self) -> object | None:
        """Attempt to claim any free slot file. Returns an open fd, or None."""
        for i in range(self._n):
            path = os.path.join(self._root or "", f"slot_{i}.lock")
            try:
                fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)  # someone else holds this slot
                continue
            return fd
        return None

    def acquire(self, timeout: float | None = None) -> bool:
        if self._fallback is not None:
            return self._fallback.acquire(timeout=timeout)
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while True:
            fd = self._try_slot()
            if fd is not None:
                self._held().append(fd)
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_S)

    def release(self) -> None:
        if self._fallback is not None:
            self._fallback.release()
            return
        stack = self._held()
        if not stack:
            return  # release without acquire — mirror Semaphore's forgiveness, don't crash
        fd = stack.pop()
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def make_governor(n: int, name: str) -> CrossProcessSemaphore:
    """Build a governor named `name` (one namespace per CLI brand) with `n` slots."""
    return CrossProcessSemaphore(n, name)

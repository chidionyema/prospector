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
    import pwd  # POSIX only
except ImportError:  # pragma: no cover - Windows
    pwd = None  # type: ignore[assignment]

try:
    import fcntl  # POSIX only
except ImportError:  # pragma: no cover — Windows
    fcntl = None  # type: ignore[assignment]

# Poll interval while waiting for a slot. flock(LOCK_NB) gives no "wait until free"
# primitive across files, so we spin. 0.25s keeps the busy-wait cost negligible against
# calls whose p50 is ~41s while staying responsive enough not to add real latency.
_POLL_S = 0.25


# Brands whose ceiling is a FOUNDER DIRECTIVE rather than a tuned default. For these the
# environment cannot move the slot directory, so no process can hand itself a private pool.
# See `_slot_root` for the arithmetic this closes.
PINNED_BRANDS = frozenset({"claude"})


def _pinned_home() -> str:
    """This user's home directory, read from the passwd database, not from $HOME.

    `os.path.expanduser("~")` returns $HOME when it is set, so a process that exports
    `HOME=/tmp/mine` gets its own `~/.prospector/cli_slots` and a private ceiling — the same
    hole `PROSPECTOR_CLI_SLOTS` opened, through a different door. The passwd entry is fixed
    for the uid and no environment variable changes it.
    """
    if pwd is not None:
        try:
            return pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            pass
    return os.path.expanduser("~")


def _slot_root(name: str, root: str | None = None) -> str | None:
    """Directory holding this governor's slot files, or None if unusable.

    Deliberately independent of `__file__` and of cwd: every prospector process on this
    machine must resolve the same path, whichever checkout or worktree it was started
    from. See the module docstring for the measurement that forced this.

    `root`, when given, is an EXPLICIT private slot directory. It exists for tests that must
    not compete with a live daemon for the real budget (see
    `tests/faults/test_grounding_contention.py`). It is an argument rather than an
    environment variable on purpose: setting it takes a code change that a reviewer sees,
    and no running process can grant itself one by exporting a name.
    """
    if fcntl is None:
        return None
    pinned = name in PINNED_BRANDS
    bases: list[str] = []
    if root:
        bases.append(root)
    else:
        # PROSPECTOR_CLI_SLOTS points the slot directory somewhere else. It stays available
        # for the unpinned brands, where a private ceiling is a preference.
        #
        # It is a DIRECTORY, and it must be absolute. The name reads like a count, and on
        # 2026-08-05 a session set `PROSPECTOR_CLI_SLOTS=1` meaning "one slot": `_slot_root`
        # then resolved `1/cursor` against the cwd, created it inside the checkout, and
        # returned it — silently handing that process a private pool. That is the
        # per-checkout ceiling this module exists to kill (see the module docstring),
        # reached through the front door. A relative value is therefore refused, not
        # honoured: the run falls back to the shared home directory, which is the safe
        # direction to fail.
        #
        # For a PINNED brand it is refused outright, absolute or not. `claude_cli._clamped`
        # bounds the WIDTH of one governor at MAX_CLAUDE_CLI = 1; it never bounded the
        # NUMBER of governors. A process that pointed this variable at its own directory got
        # a private pool of 1 on top of the machine-wide 1, so two claude CLI subprocesses
        # ran and no guard fired. Measured by walking into it on 2026-08-21, the day after
        # the founder set the ceiling at one. The ceiling is only real if the ADDRESS of the
        # slot directory is fixed as well as its size.
        override = os.environ.get("PROSPECTOR_CLI_SLOTS")
        if override and pinned:
            logging.getLogger(__name__).warning(
                "PROSPECTOR_CLI_SLOTS=%r ignored for the %r governor. Its ceiling is a "
                "founder directive (2026-08-20, \"1 claude cli, not 4\"), so the slot "
                "directory is fixed as well as the slot count. Pass root= to "
                "make_governor if you are a test that needs a private pool. "
                "See prospector/cli_governor.py PINNED_BRANDS.",
                override, name,
            )
            override = None
        elif override and not os.path.isabs(override):
            logging.getLogger(__name__).warning(
                "PROSPECTOR_CLI_SLOTS=%r is not an absolute path; it is a slot DIRECTORY, "
                "not a slot count. Ignoring it and using the machine-wide ceiling.",
                override,
            )
            override = None
        if override:
            bases.append(override)
    home = _pinned_home() if pinned else os.path.expanduser("~")
    bases.append(os.path.join(home, ".prospector", "cli_slots"))
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

    def __init__(self, n: int, name: str, root: str | None = None) -> None:
        self._name = name
        self._n = max(1, int(n))
        self._root = _slot_root(name, root)
        self._local = threading.local()
        # Fallback path: behaves exactly as the old in-process governor did.
        self._fallback = threading.Semaphore(self._n) if self._root is None else None
        # Index bookkeeping for the fallback only. The flock path gets its index for free —
        # the slot FILE the holder won IS the index, enforced by the kernel.
        self._fb_lock = threading.Lock()
        self._fb_free = list(range(self._n))

    @property
    def limit(self) -> int:
        return self._n

    def _held(self) -> list:
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def current_slot(self) -> int | None:
        """Index of the slot this thread is currently holding, or None if it holds none.

        Callers use this to derive per-slot resources that must not be shared between
        concurrent holders — see `claude_cli._attempt_claude_cli`, which binds the CLI's
        working directory to it. The guarantee is exactly the one `acquire` already makes and
        no weaker: while this returns `i`, no other thread OR process on the machine can be
        inside `acquire` holding `i`, because `slot_i.lock` is held `LOCK_EX`. That is why
        this needs no lock of its own and cannot go stale — the kernel drops the flock when
        the fd closes or the process dies.
        """
        stack = self._held()
        return stack[-1][1] if stack else None

    def _try_slot(self) -> tuple[object, int] | None:
        """Attempt to claim any free slot file. Returns (open fd, slot index), or None."""
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
            return fd, i
        return None

    def acquire(self, timeout: float | None = None) -> bool:
        if self._fallback is not None:
            if not self._fallback.acquire(timeout=timeout):
                return False
            with self._fb_lock:
                # Empty only if release() was called without acquire (see below); fall back to
                # 0 rather than raise, mirroring Semaphore's forgiveness.
                idx = self._fb_free.pop() if self._fb_free else 0
            self._held().append((None, idx))
            return True
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while True:
            claimed = self._try_slot()
            if claimed is not None:
                self._held().append(claimed)
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_S)

    def release(self) -> None:
        if self._fallback is not None:
            stack = self._held()
            if stack:
                _, idx = stack.pop()
                with self._fb_lock:
                    self._fb_free.append(idx)
            self._fallback.release()
            return
        stack = self._held()
        if not stack:
            return  # release without acquire — mirror Semaphore's forgiveness, don't crash
        fd, _idx = stack.pop()
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def make_governor(n: int, name: str, root: str | None = None) -> CrossProcessSemaphore:
    """Build a governor named `name` (one namespace per CLI brand) with `n` slots.

    `root` is an explicit private slot directory for tests that must not compete with a
    live daemon. Production code never passes it; see `_slot_root`.
    """
    return CrossProcessSemaphore(n, name, root)

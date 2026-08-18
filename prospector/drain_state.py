"""Per-row bookkeeping for the re-vet drain: how many times a backlogged row has been re-vetted
and NOT left the backlog.

WHY THIS FILE EXISTS. `schedule.backlog_cap` (`scheduler/run_scheduled._generation_suppressed`)
freezes generation while the drainable backlog is at or above the cap, and releases itself the
moment the count falls back under — no human, no PAUSE file. That self-release only works if
every counted row is a row a drain pass can actually move. A row that gets re-vetted and comes
back still-drainable is counted forever, so the freeze it holds up never lifts; and because the
drain takes OLDEST FIRST, those rows are re-selected ahead of the rows that WOULD resolve, every
tick, spending the whole bound to make no progress. That is a generation freeze waiting on a
number that cannot fall.

Two populations behave that way:

  * ORPHANS — an index row with no dossier JSON behind it. Unworkable on the first look, so
    there is nothing to count: `run.drain_survey` excludes them structurally. Measured on the
    live store 2026-08-06: 46 of 406, with a leading unbroken run of 45 (2026-06-14..06-21).
  * STALLED — the population this file counts. The row loads, gets a full moat re-vet, and the
    verdict leaves it drainable (DEFER, or provisional again). Nothing bounded that repetition.

The counter is a JSON sidecar, NOT a `dossiers` column, because `Store.save()` is
`INSERT OR REPLACE` over an explicit column list — the same mechanism documented on
`Store.tombstone` as clearing a mark on re-save. A re-vet writes a dossier, so a column would be
reset by the very event it exists to count.

GIVING UP IS VISIBLE AND REVERSIBLE. Every caller that excludes rows reports the count (into the
drain summary, so it reaches `ticks.jsonl` and the state probe) and names this ledger's path;
`rm` the file to give every row its full budget back. A cap the operator can neither see nor undo
would be exactly the silent truncation CLAUDE.md forbids.

WHAT DOES NOT COUNT. Only a completed re-vet with a verdict increments, and only when the verdict
was ruled on evidence. Three outage paths are excluded:

  * a blind moat, which returns before the pool is even built (`run._cmd_resume`'s preflight);
  * a `ProviderExhaustedError`, which breaks the loop before any attempt is recorded;
  * a COMPLETED re-vet whose DEFER was caused by infrastructure — `infrastructure_defer` below.

The third was missing until 2026-08-18, and it was not an edge case: it was every DEFER this
pipeline can produce. `verify._run_checks` sets `DEFER_GATE` in exactly two places, `verify.py`
1105 (the vet time budget ran out before the check ran) and 1151 (`retrieval_failed`), and both
mark the affected checks `retrieval_failed=True`. There is no such thing here as a DEFER on the
merits. So the branch that was supposed to retire "rows this pipeline cannot rule on" was in fact
retiring rows our own outages had touched five times.

Measured on the Fly engine 2026-08-18: `251 stalled (>= 5 unresolved re-vets)`, logged once a
minute beside `No backlogged candidate the drain can work on`. The drain had nothing left to do
while the catalogue still held 251 rows waiting on a verdict.

The vet-budget path makes the point sharpest. That clock is a property of the TICK, not of the
candidate. A row picked up late in five drain passes was retired without one real ruling against
it, on the strength of five stopwatches.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .telemetry import logger

#: Completed re-vets one row may absorb before it stops being counted as backlog. 5, because a
#: normal tick's drain bound is 3: a row that has had five full moat re-vets and is still
#: unresolved is not waiting on a transient outage (those never reach the counter — see the
#: module docstring), it is a row this pipeline cannot rule on.
DEFAULT_MAX_ATTEMPTS = 5

_LEDGER_NAME = "drain_attempts.json"


def ledger_path(store_dir) -> Path:
    """Where the ledger lives: `<store>/scheduler/drain_attempts.json`."""
    return Path(str(store_dir)) / "scheduler" / _LEDGER_NAME


def max_attempts(cfg) -> int:
    """`schedule.max_resume_attempts` — 0, a bad value, or no config disables the cap entirely.

    Tolerates `cfg is None` so a caller with no Config to hand (the CLI's own test doubles, and
    `_cmd_resume`'s `cfg=None` call sites) drains uncapped rather than crashing. Off is the
    historical behaviour, so the failure direction is "keep working every row forever", never
    "silently abandon rows because a config read went wrong".
    """
    if cfg is None:
        return 0
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        raw = schedule.get("max_resume_attempts", DEFAULT_MAX_ATTEMPTS)
    else:
        raw = getattr(schedule, "max_resume_attempts", DEFAULT_MAX_ATTEMPTS)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        # ERROR, not warning: 0 is also a LEGITIMATE configured value ("cap off"), so the caller
        # (`run.py:1868`) cannot tell a deliberate 0 from a garbled one. The log line is the only
        # thing that distinguishes them, so it must be at the level an operator actually reads.
        logger.error("schedule.max_resume_attempts=%r is not an integer — cap disabled", raw)
        return 0


def revet_provisional_kills(cfg) -> bool:
    """`schedule.revet_provisional_kills` — may a provisional KILL consume drain budget?

    THE THIRD UNMOVABLE POPULATION, and the only one that is unmovable by ECONOMICS rather than
    by mechanics. An orphan cannot be loaded and a stalled row will not resolve; a provisional
    KILL re-vets perfectly well. It just cannot produce anything, because the publish gate
    (`run.py`'s `decision == PASS and not provisional`) is never reached by a row whose decision
    is KILL. Confirming a kill with a trusted brain flips `provisional=1 -> 0` on a dead row and
    changes nothing that can ever be sold.

    Measured on the live store 2026-08-06, which is why the shipped config sets this False:
      * drainable population 318 = 161 provisional KILL + 152 DEFER + 5 provisional DEFER;
        provisional PASSes remaining: 0. So 51% of the backlog was rows in this class.
      * yield of every drain recorded in ticks.jsonl: 39 attempted -> 1 pass, 33 kills, 2 defers.
        The drain-only tick at 12:23:06Z: 15 attempted -> 15 kills, 0 passes.
      * cost of that tick: the subscription meter sat flat at $438.6810 across the three guard
        samples before it (12:11/12:16/12:21) and flat at $467.3271 across the six after it
        (13:00..13:11), so ~$28.65 for 15 rows, ~$1.91/row, for zero publishable output. None of
        it visible to `spend.daily_cap_usd`, which counts metered API dollars only
        (`metered_usd: 0.0` on that same tick).
      * and it was not running ALONGSIDE generation but INSTEAD of it: `backlog_cap: 100` against
        334 drainable meant `batch_size: 0`. Generation was stopped to re-confirm dead rows.

    The default here is True — the historical behaviour — so every existing caller and test keeps
    it, and turning the exclusion on is one line of config the founder can revert. Excluding the
    rows does NOT delete or tombstone them: they stay in the catalogue with their cited kill
    reason, and `vet --resume --only provisional-kill` still reaches every one of them on demand.
    """
    if cfg is None:
        return True
    schedule = getattr(cfg, "schedule", None) or {}
    if isinstance(schedule, dict):
        raw = schedule.get("revet_provisional_kills", True)
    else:
        raw = getattr(schedule, "revet_provisional_kills", True)
    if raw is None:
        return True
    return bool(raw)


def infrastructure_defer(dossier) -> bool:
    """Did OUR outage produce this DEFER, rather than the candidate's own weakness?

    A DEFER whose checks carry `retrieval_failed` was not ruled on evidence. `verify.py` raises
    that flag for a failed verdict call, for searches that all errored, and for the vet time
    budget running out before a check ran — none of which is a fact about the idea. Counting one
    of those against a row's re-vet budget spends the budget on our own downtime and then retires
    the row for it.

    Deliberately reads `checks` defensively. This is bookkeeping, and bookkeeping must never be
    able to stop a drain: an unexpected dossier shape answers False (count it, keep the old
    behaviour) rather than raising.
    """
    checks = getattr(dossier, "checks", None) or []
    try:
        return any(bool(getattr(c, "retrieval_failed", False)) for c in checks)
    except TypeError:
        return False


def load(store_dir) -> dict[str, int]:
    """The attempt ledger as `{candidate_id: completed_unresolved_revets}`.

    `{}` on a missing or corrupt file, never an exception: bookkeeping must not be able to stop a
    drain. A torn write therefore gives every row its budget back — the direction that keeps
    working rows, not the one that abandons them.
    """
    p = ledger_path(store_dir)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}                         # no ledger yet: nothing has been tried. A real value.
    except (OSError, ValueError) as exc:
        # `{}` here is INDISTINGUISHABLE from the line above, and every caller reads it as "every
        # row has its full budget". That is the safe direction (keep working rows, never abandon
        # them) so it stays — but silently resetting the counter re-engages the generation freeze
        # that "gate on the rate, not the stock" exists to avoid, so it is an ERROR, not a note.
        logger.error("Drain attempt ledger unreadable (%s) — treating every row as untried: %s",
                     exc, p)
        return {}
    if not isinstance(raw, dict):
        logger.error("Drain attempt ledger is not an object — ignoring it, so every row reads as "
                     "untried: %s", p)
        return {}
    out: dict[str, int] = {}
    for cid, n in raw.items():
        try:
            out[str(cid)] = max(0, int(n))
        except (TypeError, ValueError):
            continue
    return out


def _write(store_dir, data: dict[str, int]) -> None:
    """Write via a temp file + `os.replace`, so a drain killed mid-write (SIGKILL from the
    watchdog, a launchd stop) cannot leave a truncated ledger that reads as "nothing tried"."""
    p = ledger_path(store_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=0), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as exc:
        # The increment is LOST, but `record_unresolved` still returns the in-memory total, so
        # `run.py:2050-2055` goes on to tell the operator the row has been excluded and to `rm`
        # the ledger to retry it — about a count that was never persisted. Nothing here can make
        # that decision recoverable, so the requirement is that it is loud.
        logger.error("Could not write drain attempt ledger %s — this attempt is NOT recorded and "
                     "the row keeps its old count: %s", p, exc)


class _LedgerLock:
    """An advisory cross-PROCESS lock around the ledger's read-modify-write.

    `record_unresolved` was `load() -> +1 -> _write()` with no mutex. Each write is
    crash-atomic on its own, which is not the same property: two processes that read `3`
    concurrently both write `4`, and one attempt vanishes. Both callers are real and
    concurrent — the daemon's automatic drain and a manual `vet --resume` against the same
    store, a pairing CLAUDE.md calls operationally realistic ("this checkout is often shared
    by two concurrent sessions").

    A lost increment means a genuinely stuck row needs more than `max_resume_attempts` real
    attempts before it is excluded from the backlog count, quietly re-engaging the very
    generation freeze the "gate on the rate, not the stock" directive exists to avoid.

    `threading.Lock` cannot fix this (one lock object per process) — the same defect the
    audit found in `health._claim_probe`. `fcntl.flock` is per-OPEN-FILE and kernel-held, so
    it works across processes. Degrades to a no-op rather than raising if the platform or the
    filesystem has no flock: the pre-existing racy behaviour is the floor, never a crash.
    """

    def __init__(self, store_dir):
        self._path = ledger_path(store_dir).with_suffix(".lock")
        self._fh = None

    def __enter__(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a+")
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except (OSError, ImportError, AttributeError) as exc:
            # The `with` body then runs UNLOCKED — the lost-increment race this class exists to
            # close is back, and the only trace was a debug line nobody reads. Degrading to the
            # pre-existing racy behaviour is still right (a bookkeeping mutex must not be able to
            # crash a drain), but a rail that has silently switched itself off is the exact shape
            # of defect this repo keeps paying for.
            logger.error("Drain ledger lock unavailable (%s); the attempt counter's "
                         "read-modify-write is running UNLOCKED and may lose increments", exc)
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fh is None:
            return
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError, AttributeError):
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None


def record_unresolved(store_dir, candidate_id: str) -> int:
    """Count one completed re-vet that left `candidate_id` in the backlog. Returns the new total.

    The load/increment/write runs under `_LedgerLock` — see its docstring for why a
    crash-atomic write alone does not make this safe.
    """
    cid = str(candidate_id or "")
    if not cid:
        return 0
    with _LedgerLock(store_dir):
        data = load(store_dir)
        data[cid] = data.get(cid, 0) + 1
        _write(store_dir, data)
        return data[cid]


def forget(store_dir, candidate_id: str) -> None:
    """Drop a row's history once a re-vet resolved it.

    A resolved row leaves the backlog on its own, so its counter is dead weight — but if a later
    re-save ever puts it back (a fresh DEFER, a new provisional ruling), it must start from a
    full budget rather than inherit a spent one from months earlier.
    """
    cid = str(candidate_id or "")
    if not cid:
        return
    data = load(store_dir)
    if data.pop(cid, None) is not None:
        _write(store_dir, data)


def attempts_for(store_dir, candidate_id: str) -> int:
    """How many completed unresolved re-vets this row has absorbed."""
    return load(store_dir).get(str(candidate_id or ""), 0)

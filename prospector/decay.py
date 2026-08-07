"""Decay loop (Part 7).
Re-verifies published dossiers when they exceed their SLA (reverify_due_at).

WHY THIS EXISTS AT ALL (root cause, 2026-08-06)
-----------------------------------------------
Gates tighten over time; already-published dossiers are not re-judged when they do.
`moat_ungrounded` (lane-aware PASS gate) landed 2026-06-28 in 73ae976, and every PASS
minted before it kept its ruling forever. Audited 2026-08-06 over `store/dossiers/*.pass.json`:
5 of 83 live PASSes fail today's gate, and ALL 5 were created on or before 2026-06-28 —
zero minted after it fail. The gate works; nothing ever re-applied it.

The reason nothing re-applied it is that THIS MODULE HAD NO PRODUCTION CALLER. `run_decay_loop`
was imported by exactly one thing, `tests/sim/test_decay.py`, so `reverify_due_at` was a
write-only field in production (29 of 83 passes were past their SLA with nothing coming for
them). The rail existed, was tested, and never ran. See `scheduler/run_scheduled.py::_decay_pass`
for the caller that closes this.

AN OUTAGE MUST NEVER DELIST (the defect that made wiring this dangerous)
-----------------------------------------------------------------------
This loop used to call `vet_candidate(..., store=store)` and treat every non-PASS as a
delisting. Both halves were wrong, and the persistence half was the dangerous one:
`Store.save` writes `{cid}.{decision}.json` AND deletes the stale-decision file
(`store.py:178-182`). So a re-vet that DEFERRED — the ruling the engine returns when the moat
is down or retrieval failed, i.e. precisely "we could not look" — would write `{cid}.defer.json`,
DELETE `{cid}.pass.json`, and re-point the index row to `defer`. A single provider outage would
have permanently delisted live, sellable packs and destroyed the dossiers behind them.

That is the same class CLAUDE.md already fences elsewhere ("an exception is never evidence;
a failed call DEFERS" — `verify.py:365`/`:693`): a DEFER is the absence of a ruling, never a
negative one. So the re-vet now runs with `store=None` and this loop decides what is durable:
only a DECISIVE outcome (PASS or KILL) is persisted. A DEFER leaves the live PASS exactly as it
was — file, index row and all — and is retried on a later sweep.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from . import paths
from .config import Config
from .errors import ProviderExhaustedError
from .jsonl_atomic import append_jsonl
from .models import Decision
from .operator import Operator
from .retrieval import SearchProvider
from .run import vet_candidate
from .store import Store
from .telemetry import logger, set_context, track_latency

#: Outcomes this loop is willing to write over a live PASS. A DEFER is deliberately absent:
#: it means the re-vet could not reach a ruling, which is not grounds to change one.
_DECISIVE = frozenset({Decision.PASS, Decision.KILL})

# store.save() rewrites the ENGINE's own bookkeeping (.pass.json -> .kill.json) but never touches
# the storefront: found 2026-08-06 when 4 candidates re-vetted to KILL kept selling live on
# mumchimp.com because store/listings/{cid}.json and Store.Api's IsListed both outlive the kill
# with nothing to tell them otherwise. Manually unlisted that day (fly ssh + sqlite3, no admin
# endpoint exists yet); the 5 stale receipts live under LISTINGS_ARCHIVE_DIR.
#
# This loop still does not call Store.Api directly — it has no Fly/network credentials, and a
# money-rail write does not belong inside an unattended re-vet sweep. It archives the local
# receipt and durably queues the unlist instead; `tools/unlist_killed.py` drains the queue. A
# queue nobody drains is exactly the "no production caller" bug this module's own docstring
# describes, so the drain script ships in the same change as the write.
#
# These are FUNCTIONS, not the `Path("store/listings")` constants they replace, and the reason
# is in `prospector/paths.py`: a cwd-relative literal evaluated at import writes real listing
# state into whatever directory the process happened to start in, and is bound before any test
# fence can redirect it. Resolve at the point of use.
def _listings_dir() -> Path:
    return paths.store_path("listings")


def _listings_archive_dir() -> Path:
    return paths.store_path("listings_archive")


def _pending_unlist() -> Path:
    return paths.store_path("scheduler", "pending_unlist.jsonl")


def _queue_unlist(cid: str, title: str, gate: str, now: datetime.datetime) -> bool:
    """Archive a killed candidate's listing receipt and queue its Store.Api unlist.

    Returns False (no-op) when the candidate was never published — most kills aren't live
    listings, and only a published one needs unlisting. Returns True once the receipt is
    archived and the queue entry is written, so the caller can log loudly: a live pack just
    lost its ground and is still sellable until `tools/unlist_killed.py` runs.
    """
    listing_path = _listings_dir() / f"{cid}.json"
    if not listing_path.exists():
        return False

    archive_dir = _listings_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    listing_path.rename(archive_dir / listing_path.name)

    # R3: single O_APPEND write + fsync. This queue is drained by a SEPARATE process
    # (`tools/unlist_killed.py`), so a torn row here is a live pack that stays sellable.
    append_jsonl(_pending_unlist(), {
        "candidate_id": cid,
        "title": title,
        "gate_fired": gate,
        "queued_at": now.isoformat(timespec="seconds"),
    })
    return True


@track_latency(name="run_decay_loop")
def run_decay_loop(
    store: Store,
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    now: Optional[datetime.datetime] = None,
    limit: Optional[int] = None,
) -> dict[str, int]:
    """Re-verify PASS dossiers past their SLA. Never delists on an inconclusive re-vet.

    `limit` bounds how many due dossiers one sweep may re-vet, so a scheduler tick can spend a
    fixed budget instead of re-vetting the whole overdue population in one pass. None = no bound.

    Returns counts: total_due (how many were past SLA and in scope), revetted, refreshed
    (still PASS), delisted (now a grounded KILL), deferred (inconclusive, left untouched),
    plus `stopped_early` when the moat went down mid-sweep.
    """
    set_context(phase="decay_loop")
    logger.info("Starting decay loop re-verification")

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    all_pass = store.all(decision=Decision.PASS.value)

    refreshed = 0
    delisted = 0
    deferred = 0
    revetted = 0
    total_due = 0
    stopped_early = ""

    for row in all_pass:
        cid = row["candidate_id"]
        due_str = row["reverify_due_at"]
        if not due_str:
            continue

        try:
            due_dt = datetime.datetime.fromisoformat(due_str)
        except (TypeError, ValueError):
            # A malformed SLA stamp is a data bug, not a licence to re-vet on every sweep.
            logger.warning("Unparseable reverify_due_at %r", due_str, extra={"candidate_id": cid})
            continue
        if now < due_dt:
            continue

        total_due += 1
        if limit is not None and revetted >= limit:
            # Counted as due (so the caller can see the remaining backlog) but not worked.
            continue

        set_context(candidate_id=cid)
        logger.info(f"Re-verifying due dossier: {row['title']!r}", extra={"candidate_id": cid})

        d_dict = store.get(cid)
        if not d_dict:
            logger.warning(f"Dossier record missing for {cid}")
            continue

        from .models import Candidate
        cand = Candidate.from_dict(d_dict["candidate"])

        # store=None: this loop, not vet_candidate, decides what survives contact with the
        # catalogue. See the module docstring — persisting a DEFER would delete the .pass.json.
        try:
            new_dossier = vet_candidate(cand, op, search, cfg, store=None)
        except ProviderExhaustedError as exc:
            # The moat is down. Every remaining row would DEFER for the same reason, so paying
            # for them proves nothing. Stop the sweep and leave the catalogue exactly as it is;
            # the next tick picks up where this one stopped (these rows are still past SLA).
            stopped_early = f"{type(exc).__name__}: {exc}"
            logger.warning("Decay sweep stopped early — moat exhausted: %s", stopped_early,
                           extra={"candidate_id": cid})
            break

        revetted += 1

        if new_dossier.decision not in _DECISIVE:
            # DEFER: we could not look. Not evidence, so it changes nothing — the live PASS keeps
            # its file, its index row and its (still-past) SLA date, and is retried next sweep.
            deferred += 1
            logger.info("Re-vet inconclusive (%s) — PASS left live, will retry.",
                        new_dossier.gate_fired, extra={"candidate_id": cid})
            continue

        store.save(new_dossier)

        if new_dossier.decision == Decision.PASS:
            refreshed += 1
            logger.info("Dossier still valid. Date refreshed.", extra={"candidate_id": cid})
        else:
            delisted += 1
            was_published = _queue_unlist(cid, row["title"], new_dossier.gate_fired, now)
            logger.info(f"Dossier FAILED: {new_dossier.gate_fired}. Delisted.",
                        extra={"candidate_id": cid, "gate": new_dossier.gate_fired,
                               "was_published": was_published})
            if was_published:
                # logger.info/.warning do not reach launchd.err.log (daemon log drops
                # non-CRITICAL) — this is revenue-affecting, so it must not depend on that path.
                logger.critical(
                    "LIVE PACK KILLED ON RE-VET, still sellable until unlisted: %r (%s, gate=%s). "
                    "Run tools/unlist_killed.py.",
                    row["title"], cid, new_dossier.gate_fired,
                    extra={"candidate_id": cid, "gate": new_dossier.gate_fired},
                )
            # store.save() handled the delisting in the index by setting decision=KILL
            # and updating the path to .kill.json

    out = {
        "total_due": total_due,
        "revetted": revetted,
        "refreshed": refreshed,
        "delisted": delisted,
        "deferred": deferred,
    }
    if stopped_early:
        out["stopped_early"] = stopped_early
    logger.info("Decay loop complete", extra=out)
    return out

"""Append-only audit log for search and verify events.

Why this exists: web_calls=0 in DIAGNOSTICS_LATEST.txt was a broken metric
(2026-06-24 — no provider incremented it). We are done guessing. Every search call
and every verify invocation writes a structured row here so the trail is replayable.

Properties:
- Append-only: rows are never rewritten or deleted.
- Thread-safe: a Lock guards writes.
- Per-UTC-day files: store/scheduler/audit/<YYYY-MM-DD>.jsonl by default.
- Environment-overridable: PROSPECTOR_AUDIT_DIR changes the directory.

Schema (every row has these fields):
  ts        : ISO8601 UTC timestamp
  event     : one of "search" | "fallback_resolved" | "verify_search" | "verify_failed"
  run_id    : 12 hex chars, minted once per process — the daemon, a backfill and a manual CLI
              run all append to the same day-file, and until 2026-08-06 nothing said which was
              which. Group by this before drawing any conclusion from a day-file.
  pid       : os.getpid() at import. Cheap cross-check against ps/lsof; NOT a substitute for
              run_id, since pids are recycled and two runs a week apart can share one.
  seq       : monotonic counter within the process, from 1. Orders a run's rows even when the
              clock does not — see the 1970-stamped rows described below.
  ... event-specific fields ...

Schema for event="search":
  provider      : "fixture" | "gemini" | "brave" | "exa" | "deepseek" | "minimax" |
                  "openrouter" | "claude_cli" | "cache"
  query         : truncated to 200 chars
  k             : int
  max_chars     : int
  returned_n    : int — number of Source objects returned
  latency_ms    : int — wall-clock duration of the .search() call
  status        : "ok" | "empty" | "error"
  error         : truncated to 200 chars (only on status="error")
  cache_hit     : bool (only when provider="cache")
  invoked_from  : str — caller's name (best-effort; may be empty)

Schema for event="fallback_resolved":
  actual_provider : which provider answered
  tried           : list of providers tried in order
  status          : "ok" | "empty" | "error"

Schema for event="verify_search":
  check               : check name (e.g. "pain_reality")
  candidate_id        : SHA id
  queries             : list of query strings actually sent
  queries_n           : int
  n_failed            : int — how many queries errored
  passages_n          : int — unique passages after dedup
  retrieval_failed    : bool — true if every query errored
  short_circuit_empty : bool — true if zero passages (success path, empty)
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Anchored to this file, not to the cwd. The default used to be the RELATIVE string
# "store/scheduler/audit", so the audit trail followed whoever launched the process rather
# than the checkout that owns the code: importing prospector from another project wrote
# that project's own store/scheduler/audit/. Proven 2026-08-05: importing this module with
# cwd set to an empty scratch directory created store/scheduler/audit/<today>.jsonl there
# and wrote the row into it, and `~/Documents/code/sentinel-loop/store/scheduler/audit/`
# holds 10KB of real prospector rows from 2026-06-26. (The two prospector worktrees also
# carry audit trees, but those are git CHECKOUTS of the 27 tracked day-files — not evidence
# of this bug. Checked before citing them.) Rows going somewhere no one reads is worse than
# no audit log at all: the trail LOOKS intact from wherever you happen to be standing.
#
# THE MISSING DAYS, measured 2026-08-06 (this is what the day-files can and cannot tell you).
#
#   store/scheduler/audit/2026-07-31.jsonl : 1586 rows, first 00:04:27Z, LAST 02:48:37Z
#   store/scheduler/audit/2026-08-01.jsonl : does not exist
#   store/scheduler/audit/2026-08-02.jsonl : 5 rows, first 19:55:04Z
#   store/prospector.jsonl over the same span: 19,620 rows (07-31) and 23,236 rows (08-01)
#   store/prospector.db dossiers created 08-01: 77 kill + 24 pass + 1 defer = 102
#
# So the engine ruled 102 candidates, 24 of them PASS (which cannot happen without retrieval —
# verdict-from-retrieval-only), while the audit sink recorded nothing.
#
# The blackout is WIDER than the missing day-file suggests, and re-measuring it is what narrows
# the cause (2026-08-06, `store/prospector.db` + this tree):
#
#     last row before  : 2026-07-31T02:48:37Z   (07-31.jsonl, 1586 rows, none after 02:48)
#     first row after  : 2026-08-04T13:17:09Z   (632 rows that day)
#     ~82 hours dark, not the ~41 of 08-01 alone. Rulings across it: 07-31 96, 08-01 102,
#     08-02 28 — 623 checks on 08-01 ALONE, every one carrying `queries` and 3 `sources`.
#
# Two mechanisms were candidates. The surviving evidence rules one of them OUT:
#
#   1. The cwd-relative default. Until 93812d0 (2026-08-05 23:55) the fallback was the RELATIVE
#      string "store/scheduler/audit", so a run launched from any other directory wrote its
#      trail there. Fixed — that is the `__file__` anchor below. WEAK for this window: all four
#      plists set WorkingDirectory to this checkout, and the daemon printed its 08-01 batches
#      into THIS checkout's store/scheduler/launchd.err.log (912 lines stamped 2026-08-01).
#   2. The silent swallow — an unwritable sink. KILLED for the 08-02 portion. The five surviving
#      rows in the middle of the blackout carry `"run_id":"89502-20260801T041916Z"`: one process,
#      pid 89502, started 2026-08-01T04:19Z, still writing `moat_preflight` rows into THIS
#      directory at 2026-08-02T20:16Z. That same process ruled the 08-02 batches, and generation
#      and verification run in it — there is no ProcessPoolExecutor, multiprocessing or
#      subprocess anywhere in run_scheduled.py / generate.py / verify.py / run.py. A sink that
#      accepts one row and drops the next 165 from the same process is not a broken sink.
#
# Which leaves the call path, not the sink: on 08-01/08-02 the `search` and `verify_search` calls
# in retrieval.py and verify.py did not run, while checks still came back with sources. Not
# proven, and now unprovable from what survives — the rows that would say so are the missing
# ones. The `_dropped` counter below still earns its place (it separates a failing sink from an
# idle one, which nothing did before), but it would NOT have caught this: nothing raised.
#
# HAZARD, separate and live: the day-files are git-TRACKED, and this working tree has 92
# `checkout: moving` entries in its reflog. `origin/main` carries audit days only through
# 2026-07-31, so `git checkout main` here deletes 2026-08-02..05.jsonl from the working tree —
# a gap indistinguishable from the one above. Untracking the trail is a founder call (it is also
# the committed evidence), so this is recorded, not silently changed.
#
# 2026-07-25 is NOT one of these. `store/prospector.db` has ZERO dossiers created that day, so
# an absent day-file is the correct output, not a dropped one. Same for 07-23/24/26/27, whose
# 193-386 byte files hold exactly one row each: the daemon's "startup sanity check" search, and
# nothing after it. Absence of a day-file is not evidence of loss — check the index first.
#
# Unlike cli_governor's slot root — which is deliberately cwd- AND __file__-independent
# because that ceiling must bind across every checkout on the machine — the audit log is
# per-checkout data, so the checkout that owns the code is exactly the right anchor.
_AUDIT_DIR = Path(
    os.environ.get("PROSPECTOR_AUDIT_DIR")
    or Path(__file__).resolve().parent.parent / "store" / "scheduler" / "audit"
)
_LOCK = threading.Lock()

logger = logging.getLogger(__name__)

# ATTRIBUTION. Rows used to carry no process identity at all, so a day-file was an interleaving
# of the daemon, any backfill, and every manual CLI run, with no way to pull one apart from the
# others. That is not a theoretical cost: reading this log as if it were one run produced a
# confidently wrong verdict twice in one session on 2026-07-31.
#
# `run_id` is minted at import, which is once per process, so it also survives a clock that
# lies: the 1970-stamped rows in this very tree (store/scheduler/audit/1970-01-01.jsonl, 13 rows
# of real network work at "00:02" of an epoch clock, plus 8,779 matching ledger rows and 110
# tick rows) are orderable by run and by `seq` even though their timestamps are worthless.
_RUN_ID = uuid.uuid4().hex[:12]
_PID = os.getpid()
_seq = itertools.count(1)


def run_id() -> str:
    """This process's audit run id. Stable for the life of the process."""
    return _RUN_ID


# Rows the sink threw away. `audit()` must never raise — observability cannot be allowed to kill
# a grounded run mid-verdict — but silence must not be free either. The first failure logs at
# ERROR with the reason; the rest only increment, so a broken disk cannot turn into a log flood.
_dropped = 0
_drop_reason = ""


def dropped_rows() -> tuple[int, str]:
    """(rows the sink discarded this process, the first reason). Read by diagnostics."""
    return _dropped, _drop_reason


def _today_path() -> Path:
    """Today's audit file, creating the directory on first write.

    The mkdir is here rather than at module scope on purpose: an *import* must not touch
    the filesystem. The old import-time mkdir meant every tool that merely imported this
    module — including read-only reporting and state probes — left a directory behind.
    """
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _AUDIT_DIR / f"{today}.jsonl"


def audit(event: str, **fields: Any) -> None:
    """Append one structured event to today's audit file.

    Never raises. A broken audit must not break the pipeline — but it does not fail silently
    either; see `_dropped`.
    """
    global _dropped, _drop_reason
    try:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
            # Identity LAST, after the splat, so a caller cannot shadow it — an audit row whose
            # run_id came out of its own payload is worse than one with no run_id at all. The
            # obvious spelling puts these before **fields and reads as if it protects them; it
            # does the exact opposite, and the first run of tests/invariants/
            # test_audit_attribution.py caught it written that way.
            "run_id": _RUN_ID,
            "pid": _PID,
            "seq": next(_seq),
        }
        line = json.dumps(row, separators=(",", ":"), default=str)
        with _LOCK:
            with _today_path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 — see docstring
        # Audit is observability, not a control path: still swallowed. But counted, and said
        # out loud once — an audit gap that looks exactly like an idle engine cost the 82 hours
        # from 2026-07-31T02:48Z to 2026-08-04T13:17Z, which can no longer be reconstructed.
        with _LOCK:
            _dropped += 1
            first = _dropped == 1
            if first:
                _drop_reason = f"{type(exc).__name__}: {exc}"[:200]
        if first:
            logger.error("AUDIT SINK FAILING — rows are being discarded (dir=%s): %s. "
                         "Further failures counted silently; read audit.dropped_rows().",
                         _AUDIT_DIR, _drop_reason)
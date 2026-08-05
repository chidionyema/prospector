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

import json
import os
import threading
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
# NOT explained by this bug, and still open: store/scheduler/audit/2026-08-01.jsonl was
# never written despite 101 grounded rulings that day, and all four com.prospector.*
# launchd plists set WorkingDirectory to this repo — so the daemon's relative path always
# resolved correctly. Something else drops audit days (2026-07-25 is missing too, and
# 07-23/24/26/27 are 193-386 bytes). Audit rows carry no pid or run_id, so the log cannot
# be attributed to a run; adding one is the check that would settle it.
#
# Unlike cli_governor's slot root — which is deliberately cwd- AND __file__-independent
# because that ceiling must bind across every checkout on the machine — the audit log is
# per-checkout data, so the checkout that owns the code is exactly the right anchor.
_AUDIT_DIR = Path(
    os.environ.get("PROSPECTOR_AUDIT_DIR")
    or Path(__file__).resolve().parent.parent / "store" / "scheduler" / "audit"
)
_LOCK = threading.Lock()


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

    Never raises. A broken audit must not break the pipeline.
    """
    try:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(row, separators=(",", ":"), default=str)
        with _LOCK:
            with _today_path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Audit is observability, not a control path. Swallow.
        pass
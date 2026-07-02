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

_AUDIT_DIR = Path(os.environ.get("PROSPECTOR_AUDIT_DIR", "store/scheduler/audit"))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.Lock()


def _today_path() -> Path:
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
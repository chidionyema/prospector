#!/usr/bin/env python3
"""Drain store/scheduler/pending_unlist.jsonl — unlist packs the engine has since killed.

Why this exists
----------------
`decay.py::_queue_unlist` writes an entry here the moment a re-vet turns a published PASS into
a KILL. It cannot call Store.Api itself (no credentials belong inside an unattended re-vet
sweep), so the queue is inert until something drains it. Found and fixed manually 2026-08-06:
4 candidates were re-vetted to KILL and kept selling live on mumchimp.com because nothing
closed this loop. A queue with no drain caller is the exact "no production caller" bug
decay.py's own docstring describes — do not let this script become the next one.

How it actuates, and why it changed (2026-08-09)
------------------------------------------------
It used to shell out to `fly ssh console -C 'sqlite3 /data/store.db "UPDATE Packs …"'`. That
broke silently in production: the running image no longer ships the `sqlite3` CLI, so every
drain died with `exec: "sqlite3": executable file not found in $PATH`. Measured that day —
8 entries queued, 6 of them still IsListed=1 and taking money, some since 2026-08-08. An
actuator that depends on a debugging binary happening to exist inside someone else's container
is not an actuator.

The API now has a purpose-built door: `PATCH /internal/catalog/{id}/listing`
(`store_platform/src/Store.Api/Program.cs:815`), key-gated on `X-Internal-Key`, requiring a
`reason`, and able to reach ONLY the listing bit. Read its comment before reaching for
`POST /internal/catalog` instead: that route is an upsert which assigns ProviderProductId,
ProviderPriceId and DossierRef unconditionally, so withdrawing a pack that way would null its
Stripe ids — a moderation action destroying the money rail.

Safe in one direction only, which is the direction it runs: every request sends
`isListed: false`. This script can never list a pack and never charges anyone, so the cost of
running it too often is a wasted round trip while the cost of not running it is a KILLed pack
taking money. It is idempotent — unlisting an already-unlisted pack is a 200 — and it never
invents state: anything the API rejects stays queued for the next run.

Usage:
    python3 tools/unlist_killed.py            # process the whole queue
    python3 tools/unlist_killed.py --dry-run  # print what would be unlisted, touch nothing

Needs STORE_INTERNAL_API_KEY (from the environment or .env). STORE_API_URL overrides the
target, defaulting to production.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from prospector import paths  # noqa: E402
from prospector.jsonl_atomic import append_jsonl, consume_jsonl, read_jsonl  # noqa: E402
from prospector.run import _load_dotenv  # noqa: E402

DEFAULT_API_URL = "https://api.mumchimp.com"
_TIMEOUT_S = 25


def _queue() -> Path:
    return paths.store_path("scheduler", "pending_unlist.jsonl")


def _done() -> Path:
    return paths.store_path("scheduler", "pending_unlist.done.jsonl")


def _read_queue() -> list[dict]:
    """Non-destructive read. The queue is only emptied after the unlist actually succeeded."""
    return [e for e in read_jsonl(_queue()) if isinstance(e, dict)]


def _commit(processed: list[dict]) -> int:
    """Move `processed` into the done log and take them out of the queue. Returns how many.

    The old code did `QUEUE.write_text("")`. That is a lost update: `decay._queue_unlist`
    appends to this file from the unattended re-vet sweep, and every entry it added between
    `_read_queue()` above and the truncation here was deleted unprocessed — a killed pack left
    sellable, with no trace that anything was dropped. The whole point of this queue is that a
    re-vetted KILL cannot stay in the catalogue.

    `consume_jsonl` takes the file's contents under the same lock the appender holds, so
    nothing can land in the window. Anything it returns that we did NOT just process arrived
    during the API round-trip and is put straight back.
    """
    if not processed:
        return 0
    done = _done()
    done.parent.mkdir(parents=True, exist_ok=True)
    for entry in processed:
        append_jsonl(done, entry)

    seen = {json.dumps(e, sort_keys=True, default=str) for e in processed}
    drained = consume_jsonl(_queue())
    requeued = [e for e in drained if json.dumps(e, sort_keys=True, default=str) not in seen]
    for entry in requeued:
        append_jsonl(_queue(), entry)
    if requeued:
        print(f"  {len(requeued)} entry(s) arrived while unlisting; left queued for the next run")
    return len(processed)


def _reason(entry: dict) -> str:
    """The API rejects an empty reason on purpose — an unexplained delisting reads as a bug.

    An explicit `reason` is passed through VERBATIM. The queue used to be written by exactly
    one producer (`decay.py::_queue_unlist`, always a re-vet KILL), so the phrasing was
    hardcoded; from 2026-08-14 `tools/retire_rotted_passes.py` also queues withdrawals, for
    citation rot on a pack that was never re-vetted at all. Stamping those "re-vet KILL" would
    put a false cause in the storefront's own moderation record — the one place the reason is
    read later.
    """
    explicit = entry.get("reason")
    when = entry.get("queued_at", "unknown date")
    if explicit:
        return f"{explicit} — queued {when}"
    gate = entry.get("gate_fired") or "re-vet KILL"
    return f"re-vet KILL ({gate}) — queued {when}"


def _unlist_one(session: requests.Session, api_url: str, key: str,
                entry: dict) -> tuple[bool, str]:
    """(processed, note). processed=True means this entry may leave the queue.

    A 404 counts as processed: the pack is not in the catalogue at all, so it cannot be
    selling, and leaving it queued forever would mask the next real failure behind noise.
    """
    cid = entry["candidate_id"]
    try:
        resp = session.patch(
            f"{api_url}/internal/catalog/{cid}/listing",
            headers={"X-Internal-Key": key, "Content-Type": "application/json"},
            json={"isListed": False, "reason": _reason(entry)},
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if resp.status_code == 404:
        return True, "not in catalogue (never published, or already removed)"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text.strip()[:200]}"

    # Verify from the response, not from the fact that the call returned. The endpoint echoes
    # the row it wrote, so a 200 whose body still says isListed=true is a failure we must see.
    try:
        body = resp.json()
    except ValueError:
        return False, f"HTTP 200 with unparseable body: {resp.text.strip()[:200]}"
    if body.get("isListed") is not False:
        return False, f"HTTP 200 but row still reads isListed={body.get('isListed')!r}"
    return True, "unlisted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-url", default=None,
                        help=f"Store.Api base URL (default $STORE_API_URL or {DEFAULT_API_URL})")
    args = parser.parse_args()

    entries = _read_queue()
    if not entries:
        print("pending_unlist.jsonl is empty or missing — nothing to do.")
        return 0

    ids = [e["candidate_id"] for e in entries]
    print(f"{len(ids)} queued candidate(s): {', '.join(ids)}")

    if args.dry_run:
        for e in entries:
            print(f"  would unlist {e['candidate_id']}  {e.get('title', '')!r}  "
                  f"(killed on {e.get('gate_fired', '?')})")
        return 0

    _load_dotenv()
    api_url = (args.api_url or os.environ.get("STORE_API_URL") or DEFAULT_API_URL).rstrip("/")
    key = os.environ.get("STORE_INTERNAL_API_KEY")
    if not key:
        # Fail closed and LOUD. Silently doing nothing is how the sqlite3 breakage survived.
        print("ERROR: STORE_INTERNAL_API_KEY unset — cannot unlist; killed pack(s) may still "
              "be selling. Queue left untouched.", file=sys.stderr)
        return 1

    processed: list[dict] = []
    failures: list[str] = []
    with requests.Session() as session:
        for entry in entries:
            ok, note = _unlist_one(session, api_url, key, entry)
            print(f"  {entry['candidate_id']}  {note}")
            if ok:
                processed.append(entry)
            else:
                failures.append(f"{entry['candidate_id']}: {note}")

    _commit(processed)
    print(f"unlisted {len(processed)}/{len(ids)} pack(s); moved to {_done()}")
    if failures:
        print(f"ERROR: {len(failures)} still queued and possibly still selling: "
              + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

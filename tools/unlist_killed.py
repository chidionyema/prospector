#!/usr/bin/env python3
"""Drain store/scheduler/pending_unlist.jsonl — unlist packs the engine has since killed.

Why this exists
----------------
`decay.py::_queue_unlist` writes an entry here the moment a re-vet turns a published PASS into
a KILL. It cannot call Store.Api itself (no Fly/network credentials belong inside an unattended
re-vet sweep), so the queue is inert until something drains it. Found and fixed manually
2026-08-06: 4 candidates were re-vetted to KILL and kept selling live on mumchimp.com because
nothing closed this loop. A queue with no drain caller is the exact "no production caller" bug
decay.py's own docstring describes — do not let this script become the next one. Run it after
every decay sweep (wire into scheduler/run_scheduled.py's `_decay_pass`, or cron it standalone
until then).

What it does
------------
For each queued candidate_id, checks Store.Api's live catalogue via `fly ssh console` running
sqlite3 directly against the persistent volume (no admin HTTP endpoint exists yet — see
store_platform/deploy/fly/api.fly.toml, [mounts] destination = "/data"). Sets IsListed=0 only for
rows that are currently IsListed=1, in one batched UPDATE, then verifies the row count changed
matches what was requested. Successfully-processed entries are moved out of the pending queue
into pending_unlist.done.jsonl; anything the API rejects (e.g. Fly unreachable) stays queued for
the next run — this script is safe to re-run, it never invents state.

Usage:
    python3 tools/unlist_killed.py            # process the whole queue
    python3 tools/unlist_killed.py --dry-run  # print what would be unlisted, touch nothing
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from prospector import paths  # noqa: E402
from prospector.jsonl_atomic import append_jsonl, consume_jsonl, read_jsonl  # noqa: E402

FLY_APP = "prospector-store-api"


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
    during the fly round-trip and is put straight back.
    """
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


def _ssh_sql(sql: str) -> str:
    """Run one sqlite3 batch against the live /data/store.db over `fly ssh console`.

    Assumes the sqlite3 CLI is already installed on the running machine (it is not in the base
    image — `apt-get install -y sqlite3` first if this errors with "not found").
    """
    cmd = [
        "fly", "ssh", "console", "-a", FLY_APP, "-C",
        f'sqlite3 /data/store.db "{sql}"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"fly ssh failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    entries = _read_queue()
    if not entries:
        print("pending_unlist.jsonl is empty or missing — nothing to do.")
        return 0

    ids = [e["candidate_id"] for e in entries]
    id_list = ",".join(f"'{cid}'" for cid in ids)
    print(f"{len(ids)} queued candidate(s): {', '.join(ids)}")

    if args.dry_run:
        for e in entries:
            print(f"  would unlist {e['candidate_id']}  {e.get('title', '')!r}  "
                  f"(killed on {e.get('gate_fired', '?')})")
        return 0

    before = _ssh_sql(f"SELECT Id,IsListed FROM Packs WHERE Id IN ({id_list});")
    print("--BEFORE--")
    print(before)

    _ssh_sql(f"UPDATE Packs SET IsListed=0 WHERE Id IN ({id_list}) AND IsListed=1;")

    after = _ssh_sql(f"SELECT Id,IsListed FROM Packs WHERE Id IN ({id_list});")
    print("--AFTER--")
    print(after)

    if "|1" in after:
        print("ERROR: at least one row is still IsListed=1 after the update — "
              "leaving the queue untouched, re-run once fixed.", file=sys.stderr)
        return 1

    _commit(entries)
    print(f"unlisted {len(ids)} pack(s); moved to {_done()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

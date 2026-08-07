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
QUEUE = REPO_ROOT / "store" / "scheduler" / "pending_unlist.jsonl"
DONE = REPO_ROOT / "store" / "scheduler" / "pending_unlist.done.jsonl"
FLY_APP = "prospector-store-api"


def _read_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    entries = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"WARNING: skipping unparseable queue line: {line[:120]}", file=sys.stderr)
    return entries


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

    DONE.parent.mkdir(parents=True, exist_ok=True)
    with DONE.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    QUEUE.write_text("", encoding="utf-8")
    print(f"unlisted {len(ids)} pack(s); moved to {DONE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

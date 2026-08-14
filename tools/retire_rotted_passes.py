#!/usr/bin/env python3
"""Retire PASSes whose cited evidence has rotted off the web.

WHY THIS EXISTS (founder ruling, 2026-08-14)
--------------------------------------------
Twelve passes sat off the shelf because the publish lint blocks on citation liveness and
their sources now 404. Two repair routes were considered and both were rejected:

  * Substitute a Wayback capture. Rejected: if a claim only survives in an archive, the
    idea is out of date. We sell "business ideas with the research already done" — research
    a buyer cannot follow to a live page today is not research, it is a citation of a ghost.
  * Delete the individual dead-sourced sentence and republish the rest. Rejected as
    unnecessary prose surgery on stock that is stale anyway.

The ruling is that the IDEA goes, not the claim. Link rot at this depth is the market
telling us the opportunity moved on.

WHAT THIS DOES
--------------
For each id: moves `store/dossiers/<id>.pass.json` (and its `.lint.json`) into
`store/dossiers/retired/`, deletes the SQLite index row, and appends a manifest entry to
`store/retired_passes.json` recording the title, the dead URLs and the lint record that
proved them dead.

Nothing is destroyed — the dossier JSON is preserved on disk, so a retirement can be
reversed by moving the file back and re-indexing. What changes is that the pack stops
counting as a pass awaiting the shelf and can never be picked up by a republish sweep.

USAGE
    python3 tools/retire_rotted_passes.py --dry-run     # show what would go
    python3 tools/retire_rotted_passes.py --apply
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospector import paths  # noqa: E402
from prospector.jsonl_atomic import append_jsonl  # noqa: E402

DOSSIERS = ROOT / "store" / "dossiers"
RETIRED_DIR = DOSSIERS / "retired"
MANIFEST = ROOT / "store" / "retired_passes.json"
DB = ROOT / "store" / "prospector.db"


def dead_urls(cid: str) -> list[str]:
    """The citation URLs the publish lint itself recorded as dead — never inferred."""
    path = DOSSIERS / f"{cid}.lint.json"
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [
        problem["detail"]
        for problem in report.get("problems", [])
        if problem.get("severity") == "error" and problem.get("check") == "citation_urls"
    ]


def title_of(cid: str) -> str:
    try:
        return json.loads((DOSSIERS / f"{cid}.pass.json").read_text())["candidate"]["title"]
    except (OSError, ValueError, KeyError):
        return "(unreadable)"


def queue_unlist(cid: str, title: str, reason: str, *, apply: bool) -> bool:
    """Archive the live listing receipt and queue the storefront withdrawal. True if it was live.

    A retirement that leaves the pack ON THE SHELF is worse than doing nothing: it deletes the
    engine's evidence trail while the pack keeps taking money. That is the exact defect
    `decay.py`'s docstring records — 4 candidates re-vetted to KILL kept selling on
    mumchimp.com because `store/listings/{cid}.json` and Store.Api's `IsListed` both outlive
    the engine's change of mind with nothing to tell them otherwise.

    This mirrors `decay.py::_queue_unlist` deliberately, including writing through
    `paths.store_path` rather than a cwd-relative literal: `tools/unlist_killed.py` READS the
    queue through the same helper, and a producer and a consumer resolving the same file two
    different ways is a queue that silently loses entries.

    It queues; it does not actuate. Draining is a separate credentialled step
    (`python3 tools/unlist_killed.py`), so the pack is still sellable until that runs.
    """
    listing = paths.store_path("listings") / f"{cid}.json"
    if not listing.exists():
        return False
    if not apply:
        return True

    archive = paths.store_path("listings_archive")
    archive.mkdir(parents=True, exist_ok=True)
    listing.rename(archive / listing.name)
    queue = paths.store_path("scheduler", "pending_unlist.jsonl")
    queue.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(queue, {
        "candidate_id": cid,
        "title": title,
        # Verbatim into the storefront's moderation record. These packs were never re-vetted
        # to KILL, so they must not be stamped as one (`unlist_killed.py::_reason`).
        "reason": f"withdrawn: {reason}",
        "queued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    })
    return True


def retire(cid: str, reason: str, *, apply: bool) -> dict:
    title = title_of(cid)
    entry = {
        "candidate_id": cid,
        "title": title,
        "reason": reason,
        "dead_citations": dead_urls(cid),
        "retired_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    # Queue the withdrawal BEFORE touching the dossier: if this half fails we still have the
    # pass on disk and in the index to retry from, whereas a retired-then-unqueued pack is
    # live stock with no local trace of why it should not be.
    entry["was_listed"] = queue_unlist(cid, title, reason, apply=apply)
    if not apply:
        return entry

    RETIRED_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("pass.json", "lint.json"):
        src = DOSSIERS / f"{cid}.{suffix}"
        if src.exists():
            os.replace(src, RETIRED_DIR / f"{cid}.{suffix}")

    # The index and the disk are two sources of truth; a file move alone leaves the row
    # behind and every count still sees the pass.
    with sqlite3.connect(str(DB), timeout=10.0) as conn:
        conn.execute("DELETE FROM dossiers WHERE candidate_id = ?", (cid,))
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reason", default="citation rot: cited sources dead, idea out of date")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()

    if not (args.apply or args.dry_run):
        print("refusing to guess: pass --dry-run or --apply", file=sys.stderr)
        return 2

    ids = args.ids or [
        p.name.split(".")[0]
        for p in sorted(DOSSIERS.glob("*.lint.json"))
        if dead_urls(p.name.split(".")[0]) and (DOSSIERS / f"{p.name.split('.')[0]}.pass.json").exists()
    ]
    if not ids:
        print("nothing to retire")
        return 0

    entries = [retire(cid, args.reason, apply=args.apply) for cid in ids]
    for e in entries:
        print(f"{'RETIRED' if args.apply else 'would retire'} {e['candidate_id']}  {e['title'][:58]}")
        if e["was_listed"]:
            print("        WAS LIVE ON THE SHELF — unlist queued")
        for d in e["dead_citations"]:
            print(f"        {d}")

    live = [e for e in entries if e["was_listed"]]
    if live:
        # Loud on purpose: the queue is inert until drained, so every one of these packs is
        # still sellable at this moment.
        print(f"\n!! {len(live)} pack(s) are STILL LIVE until you run:  python3 tools/unlist_killed.py")

    if args.apply:
        existing = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
        MANIFEST.write_text(json.dumps(existing + entries, indent=2))
        print(f"\nmanifest: {MANIFEST} ({len(existing) + len(entries)} total)")
    print(f"\n{len(entries)} pass(es) {'retired' if args.apply else 'would be retired'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

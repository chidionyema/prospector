"""One row per shelf decision, so "why is this pack not on the shelf" is a query.

WHY THIS EXISTS. Backlog B1, the top P0. `bridge.listing_gate` composes six independent fences
into ONE boolean and returns it. Five of the six log a sentence when they refuse and the content
one refused silently until 2026-08-18. Nothing counted any of them. `bridge.py:1543` then sends
`contentKey=None` for any unlisted pack, so from the store's side all six failures look identical.

The consequence is B2: 108 registered packs are off the shelf and finding out why is 108 hand
investigations. Founder, 2026-08-18: "if answering a question required someone to SSH into a box,
that is a defect, not an answer."

WHAT IT IS. An append-only JSONL trail in the STORE, one line per publish decision, carrying the
candidate id, whether it listed, and the NAMES of the fences that refused. It is an audit trail,
not state: nothing reads it to make a decision, so a lost or trimmed line can never change what
the engine does. That is deliberate and matches `health.EVENTS_PATH`.

WHY IT CANNOT RAISE. `record()` runs on the publish path. A ledger that can break a publish would
turn an observability feature into an outage, so every failure is swallowed and logged. A missing
row is a gap in a report; a raised exception is a pack that does not reach the shelf.

USAGE
    python -m prospector.listing_ledger            # counts by blocker
    python -m prospector.listing_ledger --json     # the receipt
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .config import store_root
from .jsonl_atomic import append_jsonl, iter_jsonl

logger = logging.getLogger("prospector.listing_ledger")

#: In the STORE, never beside the code. On the engine the code is at /app and the store is a
#: mounted volume at /data/store, so a `__file__`-derived path writes the trail somewhere the
#: console never reads and every deploy erases. See `a-cwd-relative-store-path-made-every-row-an-
#: orphan` and `config.store_root()`, the one resolver.
def ledger_path(store: Optional[Path] = None) -> Path:
    return (Path(store) if store else store_root()) / "ops" / "listing_decisions.jsonl"


def record(candidate_id: str, *, listed: bool, blockers: Sequence[str],
           store: Optional[Path] = None, clock=time.time) -> bool:
    """Append one decision. Returns True when the row landed, False when it did not.

    Never raises. See the module docstring: this runs on the publish path.
    """
    row = {
        "at": round(float(clock()), 3),
        "candidate_id": str(candidate_id),
        "listed": bool(listed),
        # Sorted so two runs of the same decision produce the same line, which makes a diff of
        # the trail mean something.
        "blockers": sorted(str(b) for b in blockers),
    }
    try:
        path = ledger_path(store)
        path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(path, row)
        return True
    except Exception as exc:  # noqa: BLE001 -- an audit trail must not break a publish
        logger.warning(
            "listing_ledger: could not record the shelf decision for %s: %s", candidate_id, exc,
            extra={"candidate_id": candidate_id})
        return False


def latest_per_pack(store: Optional[Path] = None) -> dict[str, dict]:
    """The most recent decision for each pack.

    Latest, not all: a pack republished after a fix has two rows saying opposite things, and the
    question "what is blocked NOW" is answered only by the last one. Ordering is file order,
    which is append order, because `append_jsonl` is one O_APPEND write per row.
    """
    out: dict[str, dict] = {}
    path = ledger_path(store)
    if not path.exists():
        return out
    for row in iter_jsonl(path):
        if isinstance(row, dict) and row.get("candidate_id"):
            out[str(row["candidate_id"])] = row
    return out


def counts_by_blocker(store: Optional[Path] = None) -> dict[str, Any]:
    """How many packs each fence is currently holding off the shelf."""
    latest = latest_per_pack(store)
    counter: Counter[str] = Counter()
    for row in latest.values():
        for name in row.get("blockers") or []:
            counter[str(name)] += 1
    unlisted = [r for r in latest.values() if not r.get("listed")]
    return {
        "path": str(ledger_path(store)),
        "decisions": len(latest),
        "listed": sum(1 for r in latest.values() if r.get("listed")),
        "unlisted": len(unlisted),
        # A pack that is off the shelf with no named blocker is the B1 defect surviving: the
        # decision was recorded but the reason was not. It must be visible, not averaged away.
        "unlisted_with_no_named_blocker": sum(1 for r in unlisted if not (r.get("blockers") or [])),
        "by_blocker": dict(counter.most_common()),
    }


def _print(report: dict[str, Any]) -> None:
    print(f"Shelf decisions recorded: {report['decisions']}  "
          f"({report['listed']} listed, {report['unlisted']} not)")
    print(f"  trail: {report['path']}")
    if not report["by_blocker"]:
        print("\nNo pack is held off the shelf by a named fence.")
    else:
        print("\nHeld off the shelf by:")
        for name, n in report["by_blocker"].items():
            print(f"  {n:>5}  {name}")
    if report["unlisted_with_no_named_blocker"]:
        print(f"\n{report['unlisted_with_no_named_blocker']} unlisted pack(s) carry NO named "
              f"blocker. That is the B1 defect, not a clean shelf.")


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Why each pack is or is not on the shelf.")
    ap.add_argument("--json", action="store_true", help="the full receipt")
    ap.add_argument("--store", default=None, help="store directory (default: PROSPECTOR_STORE_DIR)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    store = Path(args.store) if args.store else None
    report = counts_by_blocker(store)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    # Exit 0 either way. "Some packs are blocked" is the normal state of a working shelf, and a
    # report that exits non-zero on it would page every day and be muted within a week.
    return 0


if __name__ == "__main__":
    sys.exit(main())

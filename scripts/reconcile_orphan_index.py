#!/usr/bin/env python3
"""Reconcile index rows whose dossier JSON is not where the index says it is.

WHAT IS WRONG. On the live store 2026-08-06, 189 of 1594 rows in store/prospector.db point
at a path with no file behind it. All 189 were created between 2026-06-13T18:48 and
2026-06-21T04:43, with a clean cut at 2026-06-15T14:26:57 — everything earlier is gone,
almost everything later is present. Nothing in prospector/ deletes or moves dossiers
(`grep -rniE "unlink|rmtree|os.remove"` over dossier paths, and `grep -rn quarantine_ungrounded`,
both return nothing), so this was a manual event in June that is already over. It is not
leaking now.

It is still doing damage, in two ways:

  * 45 of the orphans are DEFERs. The bounded drain takes the OLDEST rows first, so it
    re-selected and re-skipped the same dead rows every tick, and the backlog the operator
    reads (406) counts 45 rows that can never drain.
  * 9 of the orphans are PASSes that were not deleted but MOVED, to
    store/dossiers/quarantine_ungrounded/ — quarantined for being ungrounded — without the
    index being told. The index still calls them PASS.

WHAT THIS DOES.

  MOVED (9, file still exists in quarantine_ungrounded/):
      re-point `path` at the real file, flip `decision` to 'kill', and tombstone them
      'quarantined_ungrounded'. Re-pointing alone would be worse than the bug: it would hand
      a readable, ungrounded dossier back to every consumer as a PASS.

  LOST (180, no file anywhere):
      tombstone 'dossier_missing'. Nothing else changes.

Nothing is deleted and no history is rewritten: `store.all()` still returns these rows, so
report/diagnostic counts are unchanged. Only the readers that ACT on rows (the resume drain,
generation exemplars) skip them.

USAGE. Dry-run prints the exact per-row delta and writes nothing:

    .venv/bin/python scripts/reconcile_orphan_index.py
    .venv/bin/python scripts/reconcile_orphan_index.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prospector.config import load_config          # noqa: E402
from prospector.store import Store                 # noqa: E402

QUARANTINE_DIRNAME = "quarantine_ungrounded"


def classify(store: Store, dossier_dir: Path) -> tuple[list[dict], list[dict]]:
    """Split orphaned rows into (moved, lost). A row is orphaned if `path` has no file."""
    quarantine = {p.name: p for p in (dossier_dir / QUARANTINE_DIRNAME).glob("*.json")}
    moved: list[dict] = []
    lost: list[dict] = []
    for row in store.all():
        if row.get("tombstone"):
            continue
        path = str(row.get("path") or "")
        if not path or Path(path).exists():
            continue
        found = quarantine.get(Path(path).name)
        if found is not None:
            row = dict(row)
            row["_new_path"] = str(found.resolve())
            moved.append(row)
        else:
            lost.append(row)
    return moved, lost


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default: dry-run, writes nothing)")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = Store(cfg)
    dossier_dir = cfg.store_dir / "dossiers"

    moved, lost = classify(store, dossier_dir)

    print(f"store: {store.db}")
    print(f"orphaned rows: {len(moved) + len(lost)}  "
          f"(moved-to-quarantine {len(moved)}, lost {len(lost)})\n")

    print(f"── MOVED → re-point + decision=kill + tombstone 'quarantined_ungrounded' "
          f"({len(moved)}) ──")
    for r in moved:
        print(f"  {r['candidate_id']}  {str(r.get('decision')):5s} -> kill   "
              f"comp={r.get('composite')}  {str(r.get('title'))[:44]}")
        print(f"      path: …/{Path(str(r['path'])).name} -> …/{QUARANTINE_DIRNAME}/"
              f"{Path(r['_new_path']).name}")

    print(f"\n── LOST → tombstone 'dossier_missing' ({len(lost)}) ──")
    by_decision = Counter((str(r.get("decision")), int(r.get("provisional") or 0))
                          for r in lost)
    for (dec, prov), n in sorted(by_decision.items()):
        print(f"  {n:4d}  decision={dec:5s} provisional={prov}")
    created = sorted(str(r.get("created_at") or "") for r in lost)
    if created:
        print(f"  created_at range: {created[0][:19]} .. {created[-1][:19]}")

    drain_freed = sum(1 for r in lost
                      if str(r.get("decision")) == "defer" or r.get("provisional"))
    print(f"\nbacklog rows that stop being re-selected by the drain: {drain_freed}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit these changes.")
        return 0

    n = 0
    for r in moved:
        n += bool(store.tombstone(r["candidate_id"], "quarantined_ungrounded",
                                  path=r["_new_path"], decision="kill"))
    for r in lost:
        n += bool(store.tombstone(r["candidate_id"], "dossier_missing"))
    print(f"\nAPPLIED — {n} row(s) updated.")

    still = classify(store, dossier_dir)
    print(f"re-scan: {len(still[0]) + len(still[1])} untombstoned orphan(s) remain "
          f"(expected 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

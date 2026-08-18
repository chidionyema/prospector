#!/usr/bin/env python3
"""Repair the TITLE of a stranded pack, which the copy sweep cannot do.

`tools/sweep_shelf_copy.py` rewrites one-liners. It says so itself, at the split in its
`main()`: "A row whose ONLY breach is its title is reported and skipped: rewriting the
one-liner cannot clear it." Its rewriter returns a `one_liner` key and nothing else
(`shelf_copy_repair.rewrite_one`), and its selection grades with `check_shelf_copy`, which
does not carry the title rules at all.

`tools/recover_stranded_passes.py` routed every `title` breach to that sweep anyway. The
sweep looked, printed `defective: 0`, and exited clean. The recovery ledger counted that as
a failed attempt, and after three identical failures it marked the pack `unrecoverable`. On
2026-08-18 that had happened to 60 rows in `store/ops/pack_recovery.jsonl` — packs the
engine had already PASSED, retired by a repair that could not see the defect.

This tool runs the repair the engine itself runs before it builds a pack:
`field_write.repair`, graded by `pack_linter.check_title`, proposed through the `retitle`
prompt. Nothing here is a second copy of any bar — the grader that decides whether a new
title is acceptable is the one the publish gate will apply.

    python tools/repair_stranded_shelf_lines.py              # report: what is breached
    python tools/repair_stranded_shelf_lines.py --fix        # repair and persist
    python tools/repair_stranded_shelf_lines.py --fix --only <id>

Report mode makes no model call. `--fix` writes the DB row and both dossier JSONs through
`sweep_shelf_copy.persist`, so a republish reads back what the shelf shows. It never touches
Stripe, R2 or the catalogue: re-gating and listing stay separate, explicit steps.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospector import field_write  # noqa: E402
from prospector.models import Candidate  # noqa: E402
from tools.sweep_shelf_copy import DOSSIERS, persist  # noqa: E402
from tools.verify_pass_shelf_coverage import _passes, _shelf_ids  # noqa: E402

#: The two buyer-facing lines the shelf shows. Title first: `rewrite_one` is handed the title
#: as context for the one-liner, and a breached title is poor context.
LINES = ("title", "one_liner")


def load_candidate(cid: str) -> Candidate | None:
    """The stored candidate, or None when the dossier cannot be read.

    A stranded pack has a `.pass.json` by definition — it PASSED, it just never listed. The
    `.json` fallback is for the rows written before the pass/kill split.
    """
    for path in (DOSSIERS / f"{cid}.pass.json", DOSSIERS / f"{cid}.json"):
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cand = doc.get("candidate")
        if isinstance(cand, dict):
            try:
                return Candidate.from_dict(cand)
            except Exception:      # noqa: BLE001 — a row that cannot load is reported, not fatal
                return None
    return None


def repair_one(cand: Candidate, op) -> tuple[dict[str, str], list[str]]:
    """Repair both lines. Returns (what changed, what is still breached)."""
    was = {name: (getattr(cand, name) or "") for name in LINES}
    field_write.repair_all(cand, *LINES, op=op)
    changed = {name: getattr(cand, name) or "" for name in LINES
               if (getattr(cand, name) or "") != was[name]}
    return changed, field_write.breaches(cand, *LINES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true", help="repair and persist (model calls)")
    ap.add_argument("--only", default="", help="comma-separated pack ids")
    ap.add_argument("--limit", type=int, default=0, help="stop after N packs (0 = all)")
    ap.add_argument("--jobs", type=int, default=4, help="repairs in flight")
    ap.add_argument("--listed", action="store_true",
                    help="work the packs already on the shelf instead of the stranded ones")
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    # The LIVE catalogue decides what is stranded, not `store/listings/*.json`.
    # `sweep_shelf_copy.live_rows` uses the local listing files, and its own comment records
    # what that costs: 26 of the 29 copy-blocked packs on 2026-08-17 had a listing file and
    # were still absent from the shelf, so the membership test hid exactly the packs the
    # caller wanted. This is the same pair `tools/recover_stranded_passes.py` selects on.
    ids = [cid for cid, _created in _passes(str(ROOT))]
    if only:
        ids = [cid for cid in ids if cid in only]
    else:
        shelf = _shelf_ids()
        ids = [cid for cid in ids if (cid in shelf) is bool(args.listed)]

    graded: list[tuple[str, Candidate, list[str]]] = []
    unreadable: list[str] = []
    for cid in ids:
        cand = load_candidate(cid)
        if cand is None:
            unreadable.append(cid)
            continue
        if (why := field_write.breaches(cand, *LINES)):
            graded.append((cid, cand, why))

    print(f"packs: {len(ids)}   breached: {len(graded)}   unreadable: {len(unreadable)}")
    if unreadable:
        print(f"  no readable dossier: {', '.join(unreadable[:10])}")

    todo = graded[:args.limit] if args.limit else graded
    if not args.fix:
        for cid, cand, why in todo:
            print(f"\n{cid}")
            print(f"  title: {cand.title!r}")
            for detail in why:
                print(f"   ! {detail}")
        if graded:
            print(f"\nreport only — re-run with --fix to repair {len(todo)} pack(s)")
        return 0

    if not todo:
        return 0

    # The cheap chain, and only the cheap chain: re-wording a shelf line rules no verdict, so
    # it never goes near a moat brain. The first tier that CONSTRUCTS wins, in the order
    # `run.py` uses, read from `config.yaml noncritical_operator`.
    from prospector.config import load_config
    from prospector.operator import _build_operator
    from prospector.run import _noncritical_order

    cfg = load_config()
    op = None
    for kind in _noncritical_order(cfg):
        try:
            op = _build_operator(kind, cfg, fast=True)
            print(f"repairing on: {kind}")
            break
        except RuntimeError:
            continue
    if op is None:
        print("no non-critical operator available — nothing repaired")
        return 1

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        done = list(pool.map(lambda r: (r, repair_one(r[1], op)), todo))

    fixed = 0
    for (cid, cand, before), (changed, still) in done:
        if not changed:
            print(f"\n{cid}  KEPT — {'; '.join(still) or 'no proposal accepted'}")
            continue
        # Persist only what the grader passed. `repair` never writes a value it has not
        # re-graded clean, so a field present in `changed` is a field that now grades clean.
        persist(cid, new_line=changed.get("one_liner"), new_title=changed.get("title"))
        fixed += 1
        print(f"\n{cid}  REPAIRED")
        for name, value in changed.items():
            print(f"  {name}: {value!r}")
        if still:
            print(f"  still breached: {'; '.join(still)}")

    print(f"\nrepaired: {fixed} of {len(todo)}")
    print("re-gate them with: python -m tools.publish_passes --dry-run "
          "store/dossiers/<id>.pass.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

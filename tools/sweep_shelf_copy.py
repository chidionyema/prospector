#!/usr/bin/env python3
"""Re-grade the copy that is ALREADY on the shelf, and rewrite what fails.

`pack_linter.check_shelf_copy` is a publish-time gate: it grades a pack once, on its way
out, and never again. So the rule that landed on 2026-08-13 cleaned every pack published
after it and left every pack published before it exactly as it was — 27 live lines written
to the service's end customer, still live on 2026-08-16 when the founder read them back to
us off the homepage. A gate cannot fix a shelf it only sees at the door; this walks the
shelf.

    python tools/sweep_shelf_copy.py                 # report: what is live and defective
    python tools/sweep_shelf_copy.py --fix           # rewrite the breaches, 8 in flight
    python tools/sweep_shelf_copy.py --fix --limit 5 # rewrite a few first
    python tools/sweep_shelf_copy.py --fix --jobs 4  # gentler on the provider
    python tools/sweep_shelf_copy.py --push --dry-run # what the LIVE shelf would change to
    STORE_INTERNAL_API_KEY=... python tools/sweep_shelf_copy.py --push

Rewrites are re-graded before they are accepted, so a model that fails to fix the line
leaves the old line alone rather than replacing one defect with another. The rewrite may
only RE-WORD: every figure, place and institution in the original must survive it, because
the one-liner is graded against the pack's own sources downstream and a new fact here is an
unsourced claim on a source-or-die storefront.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospector.config import store_root  # noqa: E402

# `config.store_root()`, never `ROOT`: a store path derived from `__file__` follows the CODE,
# so this tool read the store inside whichever checkout it was launched from. On 2026-08-17
# that wrote `sqlite3.OperationalError: unable to open database file` into
# `store/ops/pack_recovery.jsonl`, and the recovery tool counted it as a failed repair and
# marked two PASS packs unrecoverable over it.
_STORE = store_root()
DB = _STORE / "prospector.db"
LISTINGS = _STORE / "listings"
DOSSIERS = _STORE / "dossiers"

# The prompt, the grader and the fact-preservation guard moved to
# `prospector/shelf_copy_repair.py` on 2026-08-17 so the ENGINE can run the same repair
# before a pack is built, instead of this tool curing it on the shelf afterwards.
# The glossary expander followed on 2026-08-19, for the same reason and after the same
# defect: it lived here, so the publish path could not run it, and twenty packs stayed off
# the shelf for want of expansions that were already declared in config.yaml.
# One definition, two callers. They are re-exported below because this module's own tests
# import them from here.
from prospector.shelf_copy_repair import (  # noqa: E402
    SYSTEM,
    USER,
    RewriteUnavailable,
    _new_facts,
    breaches,
    expand_initialisms,
    expand_row,
    glossary,
    rewrite_one,
    voice_breaches,
)

__all__ = ["SYSTEM", "USER", "RewriteUnavailable", "_new_facts", "breaches",
           "expand_initialisms", "expand_row", "glossary", "rewrite_one", "voice_breaches"]

log = logging.getLogger(__name__)


def _rewrite_row(op, row) -> str | RewriteUnavailable | None:
    """One row's rewrite, with the outage caught HERE rather than inside `rewrite_one`.

    The sweep runs the rows in a thread pool, so a dead call on one line must not abort the
    other twenty-two. But `rewrite_one` is also the engine's rewriter, and there the raise is
    the only thing that tells an outage apart from "the brain refused this line" — swallowing
    it inside the shared function made a quota failure read as an unfixable candidate. So the
    catch lives at the caller that actually wants to continue.

    It RETURNS the exception rather than `None`. `None` is what a refusal looks like, and the
    summary prints a refused row as kept — finished work. An outage is not finished work, so it
    is reported as NOT ATTEMPTED and the sweep exits non-zero.
    """
    try:
        return rewrite_one(op, row[1], row[2])
    except RewriteUnavailable as exc:
        # swallow-ok: returned to the caller, which counts it, prints it and exits non-zero.
        # The line on the shelf is left exactly as it was.
        log.error("rewrite call failed for %s: %s", row[0], exc,
                  extra={"candidate_id": row[0], "error": str(exc), "rewrite_failed": True})
        print(f"    rewrite call failed for {row[0]}: {exc}")
        return exc


def listed_ids() -> set[str]:
    out = set()
    for p in LISTINGS.glob("*.json"):
        try:
            out.add(json.load(p.open()).get("candidate_id"))
        except Exception:
            continue
    return out - {None}


def live_rows(stranded: bool = False, only: set[str] | None = None):
    """The rows this sweep may rewrite. On the shelf by default.

    `stranded=True` inverts the membership test to the PASS packs that never listed.
    Their copy fails the same gate for the same reason, and on 2026-08-17 it was what held
    29 of the 44 stranded packs back — but they have no `store/listings/*.json`, so the
    default selection can never see the copy that is blocking them.
    """
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        live = listed_ids()
        rows = []
        for cid, title, one, created in con.execute(
                "SELECT candidate_id, title, one_liner, created_at FROM dossiers "
                "WHERE decision = 'pass'"):
            if only:
                # An explicit id list wins over the membership test. `listed_ids()` reads
                # local `store/listings/*.json`, which is NOT the shelf: 26 of the 29
                # copy-blocked packs on 2026-08-17 had a listing file and were still absent
                # from api.mumchimp.com/catalog, so the membership test hid exactly the
                # packs the caller named.
                if cid not in only:
                    continue
            elif (cid in live) is stranded:
                continue
            rows.append((cid, title or "", one or "", created or ""))
        return sorted(rows, key=lambda r: r[3])
    finally:
        con.close()


def persist(cid: str, new_line: str | None = None, new_title: str | None = None) -> None:
    """Both copies, or neither: the DB row is what the shelf reads, the dossier JSON is
    what a republish would read back. Leaving one behind is how the shelf silently reverts
    the next time the pack is republished."""
    sets = [(col, val) for col, val in (("one_liner", new_line), ("title", new_title))
            if val is not None]
    if not sets:
        return
    con = sqlite3.connect(DB)
    try:
        con.execute(f"UPDATE dossiers SET {', '.join(c + ' = ?' for c, _ in sets)} "
                    f"WHERE candidate_id = ?", [v for _, v in sets] + [cid])
        con.commit()
    finally:
        con.close()
    for path in (DOSSIERS / f"{cid}.pass.json", DOSSIERS / f"{cid}.json"):
        if not path.exists():
            continue
        doc = json.load(path.open())
        if isinstance(doc.get("candidate"), dict):
            for col, val in sets:
                doc["candidate"][col] = val
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def pull_live(api_url: str, dry: bool) -> int:
    """Copy the live wording back into our own record, where the two disagree.

    The shelf is ahead of us, not behind: `backfill_listing_copy` edits copy directly on the
    catalogue, so on 2026-08-16 the live rows were voice-clean while this DB still held 16
    titles addressed to the end customer and five carrying trade initialisms. That is not a
    cosmetic gap — `bridge._update_catalog` sources the title from the DOSSIER
    (`bridge.py:1514`), so the next republish of any of those packs would push the old
    wording back onto the shelf and undo a fix nobody remembers making. Pulling is the
    cheap direction: it costs no model call and cannot invent a fact, because every string
    it writes is already the one the buyer is reading."""
    import requests
    live = requests.get(f"{api_url}/catalog", timeout=30).json()
    live = live if isinstance(live, list) else live.get("items", [])
    by_id = {r.get("id"): r for r in live}

    pending = []
    for cid, title, one, _created in live_rows():
        row = by_id.get(cid)
        if row is None:
            continue
        lt = (row.get("title") or "").strip()
        lo = (row.get("oneLine") or "").strip()
        # Only where OUR copy is the defective one. A live line that breaches is the push
        # path's business, and pulling it in would launder a defect into our record.
        want_t = lt if lt and lt != title.strip() and breaches(title, "") and not breaches(lt, "") else None
        want_o = lo if lo and lo != one.strip() and voice_breaches(one) and not voice_breaches(lo) else None
        if want_t or want_o:
            pending.append((cid, want_t, want_o))

    print(f"live rows: {len(by_id)}   local rows the shelf has already fixed: {len(pending)}")
    for cid, want_t, want_o in pending:
        print(f"\n{cid}")
        if want_t:
            print(f"  title -> {want_t[:100]}")
        if want_o:
            print(f"  line  -> {want_o[:100]}")
        if not dry:
            persist(cid, new_line=want_o, new_title=want_t)
    if dry:
        print("\nDRY RUN — nothing written.")
    return 0


#: The rollback. Written BEFORE each live PATCH, one row per pack: once the live `oneLine`
#: is overwritten no GET projects the old one, so this file is the only copy of it.
PUSH_LOG = store_root() / "shelf_copy_log.jsonl"


def push_live(api_url: str, key: str, dry: bool) -> int:
    """Send the repaired lines to the shelf the buyer actually reads.

    `--fix` writes the local dossier and the local DB, and a reader of this tool could
    reasonably think that is the shelf. It is not: `store/prospector.db` is this engine's
    own record, and the live store serves `oneLine` from the catalogue row behind
    `/catalog` on the live store API. Sixteen lines were repaired on 2026-08-16 and every one of
    them was still live in its old wording afterwards.

    The door is `PATCH /internal/catalog/{id}/copy` — the narrow one, which reaches copy and
    nothing else — through `backfill_listing_copy.patch_copy`, so the money-bearing fields
    are asserted unmoved by the same definition the other copy tools use rather than a
    second one written here."""
    import requests
    sys.path.insert(0, str(ROOT / "tools"))
    from backfill_listing_copy import patch_copy  # noqa: E402  (same dir)

    live = requests.get(f"{api_url}/catalog", timeout=30).json()
    live = live if isinstance(live, list) else live.get("items", [])
    by_id = {r.get("id"): r for r in live}

    pending = []
    for cid, title, one, _created in live_rows():
        row = by_id.get(cid)
        if row is None or not one:
            continue
        if (row.get("oneLine") or "").strip() == one.strip():
            continue
        # Push only where the LIVE line is the defective one. Difference is not evidence of
        # improvement in either direction: `backfill_listing_copy` has already rewritten
        # copy directly on the shelf, so for 20-odd rows the live line is the NEWER one and
        # the local DB carries the wording it replaced — `ac755ca1473e57fa` is live as
        # "When a nursery closes mid term, this recovers the parent's prepaid fees…" against
        # a local "A fixed-fee transaction broker that, when a nursery…". Pushing on
        # difference alone would have reverted every one of them. The two conditions are
        # separate on purpose: the live line must be broken, and ours must be clean.
        if not voice_breaches(row.get("oneLine") or ""):
            continue
        if voice_breaches(one):
            continue
        pending.append((cid, row, one))

    print(f"live rows: {len(by_id)}   lines to push: {len(pending)}")
    pushed = 0
    for cid, row, new in pending:
        print(f"\n{cid}\n  live:  {(row.get('oneLine') or '')[:110]}\n  local: {new[:110]}")
        if dry:
            continue
        with PUSH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"pack_id": cid, "field": "oneLine",
                                 "before": row.get("oneLine") or "", "after": new}) + "\n")
        ok, problem = patch_copy(api_url, key, cid, {"oneLine": new}, row)
        print(f"  -> {'pushed' if ok else 'REFUSED: ' + problem}")
        pushed += bool(ok)
    if not dry:
        print(f"\npushed: {pushed} of {len(pending)}   rollback log: {PUSH_LOG}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="rewrite the breaching lines in place")
    ap.add_argument("--push", action="store_true",
                    help="send repaired lines to the LIVE catalogue (needs STORE_INTERNAL_API_KEY)")
    ap.add_argument("--dry-run", action="store_true", help="with --push: show the diff, send nothing")
    ap.add_argument("--pull", action="store_true",
                    help="copy live copy back into the local record where the shelf is ahead")
    ap.add_argument("--api-url", default=os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}")
    ap.add_argument("--limit", type=int, default=0, help="stop after N rewrites")
    ap.add_argument("--jobs", type=int, default=8,
                    help="rewrites in flight at once (default 8, the measured-clean MiniMax figure)")
    ap.add_argument("--stranded", action="store_true",
                    help="sweep the PASS packs that never listed instead of the live shelf")
    ap.add_argument("--only", default="",
                    help="comma-separated pack ids; restricts the selection to these")
    args = ap.parse_args()
    only = {c.strip() for c in args.only.split(",") if c.strip()}

    if args.pull:
        return pull_live(args.api_url, args.dry_run)
    if args.push:
        key = os.environ.get("STORE_INTERNAL_API_KEY", "")
        if not key and not args.dry_run:
            print("--push needs STORE_INTERNAL_API_KEY; refusing.", file=sys.stderr)
            return 2
        return push_live(args.api_url, key, args.dry_run)

    rows = live_rows(args.stranded, only)
    bad = [(cid, t, o, c, b) for cid, t, o, c in rows if (b := breaches(t, o))]
    # Split by what a rewrite can reach. A row whose ONLY breach is its title is reported
    # and skipped: rewriting the one-liner cannot clear it, and spending a call to find
    # that out — 44 rows' worth on the first run — is the whole cost of the sweep.
    fixable = [r for r in bad if voice_breaches(r[2])]

    # The free half, first: spelling out a term the operator has DECLARED costs no model
    # call and cannot invent a fact. On 2026-08-16 initialisms alone held 31 of the 33
    # defective rows, so this is the larger half of the sweep and the cheaper one.
    gloss = glossary()
    expandable, unresolved, rejected = [], {}, set()
    for cid, title, one, created, why in bad:
        new_t, new_o, unres, rej = expand_row(title, one, gloss)
        for run in unres:
            unresolved[run] = unresolved.get(run, 0) + 1
        rejected |= set(rej)
        if new_t or new_o:
            expandable.append((cid, title, one, created, new_t, new_o))

    print(f"live packs: {len(rows)}   defective: {len(bad)}   "
          f"one-liners a rewrite can fix: {len(fixable)}   "
          f"rows the glossary alone repairs: {len(expandable)}")
    if unresolved:
        print(f"\nterms this cannot spell out ({len(unresolved)}) — declare them in "
              f"config.yaml listing.initialism_glossary, or reword the copy:")
        for run, n in sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {run:<8} on {n} row(s)")
    if rejected:
        print(f"\nDECLARED BUT WRONG — the initials do not spell the run, so these were "
              f"dropped rather than published: {', '.join(sorted(rejected))}")
    if not bad:
        return 0

    if args.fix and expandable:
        print(f"\nspelling out declared terms on {len(expandable)} row(s) — no model call")
        for cid, title, one, created, new_t, new_o in expandable:
            print(f"\n{cid}  listed from {created[:10]}")
            if new_t:
                print(f"  title -> {new_t}")
            if new_o:
                print(f"  line  -> {new_o}")
            persist(cid, new_line=new_o, new_title=new_t)
        # The rows moved, so re-grade before spending anything on the half a model must do.
        rows = live_rows(args.stranded, only)
        bad = [(cid, t, o, c, b) for cid, t, o, c in rows if (b := breaches(t, o))]
        fixable = [r for r in bad if voice_breaches(r[2])]
        print(f"\nafter the glossary: defective {len(bad)}   "
              f"one-liners a rewrite can fix: {len(fixable)}")
        if not fixable:
            return 0

    op = None
    if args.fix:
        # The cheap chain, and only the cheap chain: rewording a line that is already
        # published rules nothing, so it never goes near a moat brain. `_build_operator`
        # raises for a tier that is not configured, so the first that CONSTRUCTS wins —
        # the same order `run.py` uses, read from `config.yaml noncritical_operator`.
        from prospector.config import load_config
        from prospector.operator import _build_operator
        from prospector.run import _noncritical_order
        cfg = load_config()
        for kind in _noncritical_order(cfg):
            try:
                op = _build_operator(kind, cfg, fast=True)
                print(f"rewriting on: {kind}")
                break
            except RuntimeError:
                continue
        if op is None:
            print("no non-critical operator available — nothing rewritten")
            return 1

    if not args.fix:
        proposed = {cid: (nt, no) for cid, _t, _o, _c, nt, no in expandable}
        for cid, title, one, created, why in bad:
            print(f"\n{cid}  listed from {created[:10]}")
            print(f"  OLD: {one}")
            for field, detail in why:
                print(f"   ! [{field}] {detail.split(':')[0]}")
            new_t, new_o = proposed.get(cid, (None, None))
            if new_t:
                print(f"   > glossary title: {new_t}")
            if new_o:
                print(f"   > glossary line:  {new_o}")
        return 0

    # In flight together. Each rewrite is one independent call about one line, sharing
    # nothing with the others, and the founder's first run measured ~40s of latency per
    # call — 23 rows serially is a quarter of an hour of waiting for work that is almost
    # entirely idle. The default matches `config.yaml minimax_concurrency`, the figure this
    # estate measured clean at 16/16 with no 429s; the writes stay serial below, because
    # SQLite is the one part of this that is not idle-waiting.
    todo = fixable[:args.limit] if args.limit else fixable
    print(f"\nrewriting {len(todo)} line(s), {args.jobs} in flight")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        done = list(pool.map(lambda r: (r, _rewrite_row(op, r)), todo))

    fixed = 0
    outages = 0
    for (cid, title, one, created, why), new in done:
        print(f"\n{cid}  listed from {created[:10]}")
        print(f"  OLD: {one}")
        if isinstance(new, RewriteUnavailable):
            outages += 1
            print(f"  NOT ATTEMPTED — {new}")
        elif new:
            persist(cid, new)
            fixed += 1
            print(f"  NEW: {new}")
        else:
            print("  (kept — see the refusal above)")
    print(f"\nrewritten: {fixed} of {len(todo)}")
    if outages:
        # Non-zero, so a scripted caller cannot mistake a run that never reached the brain
        # for a run that decided every line was fine.
        print(f"{outages} line(s) were never attempted — the rewrite call failed. Re-run.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

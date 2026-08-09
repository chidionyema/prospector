#!/usr/bin/env python3
"""Backfill `Source.archived_url` onto dossiers published before citation archiving existed.

Why this exists
---------------
`prospector/archive.py` mints a Wayback memento for every citation AT PUBLISH, so link rot
degrades a convenience rather than a claim. It shipped 2026-08-09 and only runs on the publish
path, which leaves every pack published before it with a live URL and no second pointer.
Measured on this store when the tool was written: 68 pass-dossiers, 2436 distinct source URLs,
`archived_url` populated on ZERO of them.

That backlog is not cosmetic. 10 of those 68 dossiers cite a URL that is now a hard 404, and
`pack_linter.check_urls` blocks a publish on a dead citation unless a memento stands in for it
(the `archived` argument, added the same day). So these packs are unlistable until the field
is populated, and the field can only be populated by asking the Internet Archive.

What it deliberately does NOT do
--------------------------------
It never re-renders a dossier through `models.Dossier`. A round-trip would silently drop any
key the current dataclasses do not model, and these files are the audit trail for verdicts
ruled by earlier versions of the engine. The JSON is edited in place, key by key: the ONLY
mutation is adding `archived_url` to a dict that already has a `url`. Everything else, including
key order, is preserved byte-for-byte by re-dumping with the same settings `models.to_json`
uses (`indent=2, ensure_ascii=False`).

Rate limiting is the normal case, not an error
-----------------------------------------------
The Internet Archive rate-limits anonymous callers on BOTH endpoints (measured 2026-08-09: a
plain `curl` of the availability API returned HTTP 429 mid-sweep). `archive.archive_urls`
treats a 429 as "not asked" rather than "not archived" and stops for the batch, so a run that
ends early is expected: re-run it later and it resumes from the shared cache. A sweep that
reports 0 recoverable is therefore only meaningful if it also reports 0 deferred.

Usage
-----
    python3 tools/backfill_archived_url.py --dry-run            # report only, no writes
    python3 tools/backfill_archived_url.py --dead-only --apply  # repair the blocked packs first
    python3 tools/backfill_archived_url.py --apply --limit 200  # widen the sweep
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector import archive  # noqa: E402

DOSSIER_GLOB = "*.pass.json"


def _source_dicts(node: Any) -> Iterator[Dict[str, Any]]:
    """Every dict in the tree carrying an http(s) `url` — i.e. a serialised `models.Source`."""
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith("http"):
            yield node
        for value in node.values():
            yield from _source_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _source_dicts(value)


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, doc: Dict[str, Any]) -> None:
    """Atomic, and byte-compatible with `store.save` (`models.Dossier.to_json`)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)


def _dead_urls(cache_path: Path) -> set[str]:
    """URLs the pack linter has positively confirmed 404/410, from its own probe cache.

    Read-only reuse of a cache the linter already paid for, so prioritising the blocked packs
    costs no extra network. `alt-alive` entries are excluded: those are OUR stored string being
    wrong, not the source being gone, and the linter already downgrades them.
    """
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return set()
    dead = set()
    for key, entry in cache.items():
        if not isinstance(entry, dict) or entry.get("status") not in (404, 410):
            continue
        if str(entry.get("note") or "").startswith("resolves without/with trailing slash"):
            continue
        url = key.split("|", 1)[1] if "|" in key else key
        if url.startswith("http"):
            dead.add(url)
    return dead


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default="store", help="store directory (default: store)")
    ap.add_argument("--apply", action="store_true",
                    help="write the dossiers; without it nothing is modified")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op form of the default")
    ap.add_argument("--dead-only", action="store_true",
                    help="only look up URLs the linter has confirmed dead (the blocked packs)")
    ap.add_argument("--limit", type=int, default=60,
                    help="max distinct URLs to look up this run (default: 60)")
    ap.add_argument("--save-new", action="store_true",
                    help="ask Save Page Now for URLs with no capture (slow, rate-limited)")
    args = ap.parse_args()

    if args.apply and args.dry_run:
        print("error: --apply and --dry-run are contradictory", file=sys.stderr)
        return 2
    apply = args.apply

    store = Path(args.store)
    dossier_dir = store / "dossiers"
    paths = sorted(dossier_dir.glob(DOSSIER_GLOB))
    if not paths:
        print(f"no {DOSSIER_GLOB} under {dossier_dir}", file=sys.stderr)
        return 1

    docs: List[Tuple[Path, Dict[str, Any]]] = [(p, _load(p)) for p in paths]

    wanted: List[str] = []
    already = 0
    seen: set[str] = set()
    dead = _dead_urls(store / "lint_url_cache.json") if args.dead_only else None
    for _, doc in docs:
        for src in _source_dicts(doc):
            url = src["url"]
            if src.get("archived_url"):
                already += 1
                continue
            if dead is not None and url not in dead:
                continue
            if url not in seen:
                seen.add(url)
                wanted.append(url)

    print(f"dossiers            : {len(docs)}")
    print(f"sources already set : {already}")
    print(f"candidate URLs      : {len(wanted)}"
          + (f"  (confirmed-dead only, {len(dead or ())} known dead)" if dead is not None else ""))
    if not wanted:
        print("nothing to do")
        return 0

    lookup = wanted[: args.limit]
    if len(wanted) > args.limit:
        print(f"looking up {len(lookup)} of {len(wanted)} this run (--limit)")

    mementos = archive.archive_urls(
        lookup,
        cache_path=store / "citation_archive.json",
        save_new=args.save_new,
        max_urls=len(lookup),
    )
    print(f"mementos found      : {len(mementos)} of {len(lookup)} asked")
    if not mementos:
        # Distinguishing these two is the whole point of the 429 handling in archive.py: a
        # rate-limited sweep says nothing about whether the URLs are archived.
        print("  (0 found — check the log above for a rate-limit warning before concluding "
              "these URLs have no capture)")

    touched_files = 0
    touched_srcs = 0
    for path, doc in docs:
        n = 0
        for src in _source_dicts(doc):
            memento = mementos.get(src["url"])
            if memento and not src.get("archived_url"):
                src["archived_url"] = memento
                n += 1
        if n:
            touched_files += 1
            touched_srcs += n
            print(f"  {'WRITE' if apply else 'would set'} {n:3d}  {path.name}")
            if apply:
                _save(path, doc)

    verb = "updated" if apply else "would update"
    print(f"\n{verb}: {touched_srcs} source(s) across {touched_files} dossier(s)")
    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

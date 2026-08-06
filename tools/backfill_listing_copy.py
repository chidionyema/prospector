#!/usr/bin/env python3
"""Replace the deterministic floor copy on live packs whose dossier has no listing_page.

WHY THIS EXISTS
---------------
Measured against the live catalogue on 2026-08-06: 45 of 61 live packs have no `listing_page`
artifact on their dossier, so `pack_floors.claim_safe_marketing` supplied their storefront copy —
headline = title verbatim (34/61), no card line at all (55/61), proof point = the first check
rationale bullet (28/61). That is truthful but it is not selling copy, and it is recoverable now
that `artifacts._salvage_listing` keeps the fields that pass claim-check instead of discarding a
whole listing because one field failed.

WHY IT DOES NOT REPUBLISH
-------------------------
`EngineBridge.publish_pass` is not a copy-update path. It re-runs `price_for` (bridge.py:515) and
mints a FRESH provider product and price on every call (bridge.py:563-576), and the API's
`POST /internal/catalog` upsert assigns ProviderProductId/ProviderPriceId unconditionally on
update (Program.cs:489-490) while only ever assigning PricePence on INSERT (Program.cs:461,468).
So republishing a live pack to change its words either

  * nulls the provider ids (omit them and `request.X ?? request.PaddleX` is null), which breaks
    FulfilmentService's `p.ProviderProductId == item.ProductId` lookup — the buyer pays and
    delivery never resolves; ProviderProductId is returned by no GET projection, so a backfill
    cannot even read it back to echo it; or
  * points the buy button at a price minted at today's ladder number while PricePence and
    MinBillablePence still hold the old one — charged at the new amount, refused by the
    fulfilment fence, with nothing in the catalogue row looking changed.

This tool therefore writes through `PATCH /internal/catalog/{id}/copy`, which reaches copy
columns and nothing else, and asserts price/provider invariance from the write's own response.

USAGE
-----
    # See what would change; calls the operator, writes nothing anywhere.
    .venv/bin/python tools/backfill_listing_copy.py --dry-run --limit 3

    # One pack, for eyes-on verification on the live storefront before the rest.
    STORE_INTERNAL_API_KEY=... .venv/bin/python tools/backfill_listing_copy.py \
        --apply --only c8fbb7aa12e1bf48

    # The rest.
    STORE_INTERNAL_API_KEY=... .venv/bin/python tools/backfill_listing_copy.py --apply

Generation costs roughly 8 minutes per pack against the Claude CLI while the daemon is running,
so a full 45-pack run is a multi-hour job. `--limit` and `--only` exist to make it resumable:
a pack whose dossier already carries a listing_page is skipped, so re-running continues rather
than regenerating.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from prospector import artifacts
from prospector.config import load_config
from prospector.operator import make_operator
from prospector.plain_text import plain_lines, to_plain_text

DEFAULT_API_URL = "https://api.mumchimp.com"
DOSSIER_GLOB = "store/dossiers/*.json"

# Below this there is not enough grounded material to write a listing from, and the honest
# outcome is to leave the deterministic floor in place. Matches the threshold the salvage
# measurement sampled on, so the measured rescue rate applies to the same population.
MIN_SUPPORTED_CLAIMS = 3

# The fields this tool sends. Deliberately a subset of CopyPatchRequest: `sampleExtract` is
# derived from the pack's build_spec at publish time (bridge.py:423) and is NOT part of the
# floor-copy defect, so it is omitted — and omitted means left alone.
COPY_FIELDS = (
    "cardLine", "headline", "subhead", "whatYouGet",
    "proofPoint", "whoPays", "effortTag", "timeToFirstRevenue",
)

# Read back from the PATCH response and required to be unchanged. A mismatch on any of these
# means the endpoint reached a field it must not reach; the run aborts rather than continues.
INVARIANTS = ("pricePence", "minBillablePence", "providerPriceId", "providerProductId", "contentKey")


def load_dossier_index() -> Dict[str, str]:
    """Map candidate id -> dossier path, skipping kill dossiers."""
    index: Dict[str, str] = {}
    for path in sorted(glob.glob(DOSSIER_GLOB)):
        if ".kill." in path:
            continue
        stem = os.path.basename(path)[: -len(".json")]
        index.setdefault(stem.split(".")[0], path)
    return index


def listing_of(dossier: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tags = (dossier.get("candidate") or {}).get("tags") or {}
    if not isinstance(tags, dict):
        return None
    for piece in tags.get("marketing") or []:
        if isinstance(piece, dict) and piece.get("type") == "listing_page":
            return piece
    return None


def catalog_payload(listing: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror bridge.py:413-422 exactly.

    Every string here is printed by the storefront with no markdown parser, so it goes through
    to_plain_text at this boundary — the same boundary and the same treatment the publish path
    applies. Diverging here would put a second, quietly different sanitiser on the catalogue.
    """
    return {
        # No [:n] slice: _card_line already enforces length by DROPPING an over-long line,
        # and a slice here would reintroduce the mid-clause cut that enforcement prevents.
        "cardLine": to_plain_text(listing.get("card_line"), collapse=True),
        "headline": to_plain_text(listing.get("headline"), collapse=True)[:140],
        "subhead": to_plain_text(listing.get("subhead"), collapse=True)[:280],
        "whatYouGet": plain_lines(listing.get("what_you_get"))[:5],
        "proofPoint": to_plain_text(listing.get("proof_point"), collapse=True),
        "whoPays": to_plain_text(listing.get("who_pays"), collapse=True),
        "effortTag": (listing.get("effort_tag") or "").strip(),
        "timeToFirstRevenue": to_plain_text(listing.get("time_to_first_revenue"), collapse=True),
    }


def persist_listing(path: str, listing: Dict[str, Any]) -> None:
    """Write the generated listing back onto the dossier, atomically.

    Re-read immediately before writing: the scheduler daemon is live and this file is shared
    state. Read-modify-write on a several-hour run is otherwise a silent clobber.
    """
    with open(path) as handle:
        current = json.load(handle)
    tags = (current.get("candidate") or {}).setdefault("tags", {})
    marketing = [m for m in (tags.get("marketing") or [])
                 if not (isinstance(m, dict) and m.get("type") == "listing_page")]
    marketing.append(listing)
    tags["marketing"] = marketing

    tmp = f"{path}.backfill.tmp"
    with open(tmp, "w") as handle:
        json.dump(current, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def supported_claims(dossier: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in (dossier.get("checks") or []) if c.get("verdict") == "supported"]


def generate_listing(quality, checker, dossier: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Draft a listing_page from the dossier's supported claims.

    Returns None only when the operator produced nothing that survived claim-check. The
    "too few claims to try" case is decided by the caller, because reporting a pack that was
    never attempted as one that failed would overstate how much of the catalogue is beyond
    recovery — the two need different follow-ups.
    """
    candidate = dossier.get("candidate") or {}
    supported = supported_claims(dossier)
    return artifacts._gen_one_content(
        quality, checker, json.dumps(candidate), json.dumps(supported), supported, "listing_page")


def patch_copy(api_url: str, key: str, pack_id: str,
               payload: Dict[str, Any], before: Dict[str, Any]) -> Tuple[bool, str]:
    """PATCH the copy and verify the money-bearing fields did not move.

    Verification reads the PATCH's own response rather than a follow-up GET: a second read could
    observe a different write, and the point of the assertion is that THIS write was safe.
    """
    response = requests.patch(
        f"{api_url}/internal/catalog/{pack_id}/copy",
        json=payload,
        headers={"X-Internal-Key": key, "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:200]}"

    after = response.json()

    for field in INVARIANTS:
        was, now = before.get(field), after.get(field)
        # `before` comes from /catalog, which does not project providerProductId or contentKey.
        # Absent means "nothing to compare", not "expected null" — but the response value must
        # still be present, because a null provider id is the exact damage being guarded against.
        if field not in before:
            if field in ("providerProductId", "providerPriceId") and not now:
                return False, f"{field} is {now!r} after the patch — pack is unfulfillable"
            continue
        if was != now:
            return False, f"{field} moved: {was!r} -> {now!r}"

    if after.get("isListed") is not True:
        return False, f"pack went unlisted (isListed={after.get('isListed')!r})"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="generate and print, write nothing (default)")
    mode.add_argument("--apply", action="store_true",
                      help="persist to the dossier and PATCH the live catalogue")
    parser.add_argument("--only", action="append", default=[],
                        help="restrict to these pack ids (repeatable)")
    parser.add_argument("--limit", type=int, default=0, help="stop after N packs (0 = no limit)")
    args = parser.parse_args()

    apply = args.apply
    internal_key = os.environ.get("STORE_INTERNAL_API_KEY")
    if apply and not internal_key:
        print("--apply needs STORE_INTERNAL_API_KEY; refusing.", file=sys.stderr)
        return 2

    response = requests.get(f"{args.api_url}/catalog", timeout=30)
    response.raise_for_status()
    live = {item["id"]: item for item in response.json()}
    print(f"live packs: {len(live)}")

    index = load_dossier_index()
    targets: List[Tuple[str, str, Dict[str, Any]]] = []
    no_dossier: List[str] = []
    for pack_id in live:
        if args.only and pack_id not in args.only:
            continue
        path = index.get(pack_id)
        if not path:
            no_dossier.append(pack_id)
            continue
        with open(path) as handle:
            dossier = json.load(handle)
        if listing_of(dossier) is not None:
            continue
        targets.append((pack_id, path, dossier))

    if no_dossier:
        print(f"WARNING: {len(no_dossier)} live pack(s) have no dossier on disk: "
              f"{', '.join(no_dossier[:5])}")
    if args.limit:
        targets = targets[: args.limit]

    print(f"packs lacking a listing_page: {len(targets)}")
    print(f"mode: {'APPLY (writes dossiers and the live catalogue)' if apply else 'DRY RUN'}\n")
    if not targets:
        return 0

    cfg = load_config()
    quality = make_operator(cfg, fast=False)
    checker = make_operator(cfg, fast=False)

    generated = patched = skipped = too_few = 0
    for n, (pack_id, path, dossier) in enumerate(targets, 1):
        started = time.time()
        title = str((dossier.get("candidate") or {}).get("title") or "")[:70]
        print(f"[{n}/{len(targets)}] {pack_id}  {title}")

        # Below this the operator has nothing to write truthful copy FROM, and asking it to
        # try is how ungrounded marketing gets written. Not attempted, and reported as such.
        claims = supported_claims(dossier)
        if len(claims) < MIN_SUPPORTED_CLAIMS:
            print(f"    not attempted — only {len(claims)} supported claim(s), "
                  f"need {MIN_SUPPORTED_CLAIMS}")
            too_few += 1
            continue

        try:
            listing = generate_listing(quality, checker, dossier)
        except Exception as exc:  # noqa: BLE001 - one bad pack must not end a multi-hour run
            print(f"    ERROR generating: {type(exc).__name__}: {exc}")
            skipped += 1
            continue

        if not listing:
            print(f"    unsalvageable — no verifiable field survived claim-check ({time.time() - started:.0f}s)")
            skipped += 1
            continue

        generated += 1
        payload = catalog_payload(listing)
        kept = [field for field in COPY_FIELDS if payload.get(field)]
        print(f"    generated in {time.time() - started:.0f}s; fields: {kept}")
        print(f"    cardLine: {payload['cardLine'] or '(empty)'}")
        print(f"    headline: {payload['headline'] or '(empty)'}")

        if not apply:
            continue

        persist_listing(path, listing)
        ok, problem = patch_copy(args.api_url, internal_key, pack_id, payload, live[pack_id])
        if not ok:
            # An invariance breach means the endpoint reached a money-bearing field. Stop the
            # whole run: whatever is wrong applies to every remaining pack too.
            print(f"    ABORT — invariance check failed on {pack_id}: {problem}", file=sys.stderr)
            print(f"    {patched} pack(s) patched before this point.", file=sys.stderr)
            return 1
        patched += 1
        print("    patched; price and provider ids unchanged")

    print(f"\n{'=' * 62}")
    print(f"targets               {len(targets)}")
    print(f"not attempted (<{MIN_SUPPORTED_CLAIMS} claims) {too_few}")
    print(f"generated             {generated}")
    print(f"unsalvageable/errored {skipped}")
    print(f"patched               {patched}" if apply else "patched               0 (dry run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

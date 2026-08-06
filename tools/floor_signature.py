"""Count the deterministic-floor signature across the LIVE catalogue.

The floor (`pack_floors.claim_safe_marketing`) is what a pack shows when no
`listing_page` artifact survived claim-check. Its tells, read from the live API only:

  headline == title      the floor sets headline to the candidate title verbatim
  cardLine empty         the floor has no card line to give
  proofPoint is a bullet the floor lifts the first supported check's rationale

Run before and after `tools/backfill_listing_copy.py`; the deltas are the measurement.

Two things this deliberately does NOT measure, because `GET /catalog` does not project
them: `subhead` and `timeToFirstRevenue`. They read as missing on every pack whether or
not they hold data — that is the projection, not data loss. Do not add them here without
first adding them to the catalog projection.

`headline == title` after a successful patch is EXPECTED, not a failure: when claim-check
drops the generated headline, `fill_from_floor` restores the title, which equals the floor
and is never less than it. Measured on n=20, the headline is the field claim-check drops
most often (survived in 4 of 9 rescues).

Usage:
    .venv/bin/python tools/floor_signature.py [api-url]
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = sys.argv[1] if len(sys.argv) > 1 else "https://api.mumchimp.com"


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main() -> int:
    packs = fetch(f"{API}/catalog")
    if isinstance(packs, dict):
        packs = packs.get("items") or packs.get("packs") or []

    live = [p for p in packs if p.get("isListed", True)]

    def blank(pack, field):
        return not (pack.get(field) or "").strip()

    headline_is_title = [
        p for p in live
        if (p.get("headline") or "").strip() == (p.get("title") or "").strip()
    ]
    no_headline = [p for p in live if blank(p, "headline")]
    no_card_line = [p for p in live if blank(p, "cardLine")]
    no_proof = [p for p in live if blank(p, "proofPoint")]

    print(f"live packs                  {len(live)}")
    print(f"headline == title           {len(headline_is_title)}")
    print(f"headline missing            {len(no_headline)}")
    print(f"cardLine missing            {len(no_card_line)}")
    print(f"proofPoint missing          {len(no_proof)}")
    print()
    print("ids still showing headline == title:")
    for p in headline_is_title:
        print("   ", p.get("id"), (p.get("title") or "")[:60])

    # A pack live with no headline at all is strictly worse than the floor and is the one
    # failure mode this script exists to catch. `fcf4a559f0ea0851` shipped that way once.
    if no_headline:
        print()
        print(f"DEFECT: {len(no_headline)} live pack(s) below the floor (no headline):")
        for p in no_headline:
            print("   ", p.get("id"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

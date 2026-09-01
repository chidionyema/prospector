"""BEFORE/AFTER for the live shelf under the L2 depth ladder. READ-ONLY: writes nothing,
calls no payment provider, PATCHes nothing. It exists so the repricing decision is taken
against measured numbers instead of an assertion about them.

    python -m tools.depth_reprice_preview

The prices are produced by the shipping `prospector.pricing.price_for` against the shipping
`config.yaml`, NOT by a reimplementation of the bands here. That matters: a preview that
re-derived the bands could agree with itself while disagreeing with what the engine would
actually publish, and the whole point of the table is to be trusted before an apply.

Applying it is a separate, deliberate act and must go through `PATCH
/internal/catalog/{id}/price` with a Reason (`tools/set_live_pack_price.py`), never a direct
DB write — a catalogue row and its Stripe Price object are minted together, and moving one
alone charges the buyer an amount the fulfilment fence then rejects.
"""
from __future__ import annotations

import json
import os
import urllib.request

from prospector.config import load_config
from prospector.models import Candidate
from prospector.pricing import price_for

CATALOGUE_URL = (os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}") + "/catalog"
# Cloudflare 1010s a bare urllib User-Agent (memory: cloudflare-blocks-urllib-user-agent).
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def main() -> int:
    req = urllib.request.Request(CATALOGUE_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode())
    cfg = load_config()

    out = []
    for row in rows:
        decision = price_for(
            Candidate(title=row["title"], one_liner=row.get("oneLine") or "",
                      ambition_tier="", market=row.get("market") or ""),
            None, cfg, source_count=row["sourceCount"])
        out.append((row["sourceCount"], row["pricePence"], decision.price_pence,
                    row["id"], row["title"][:46]))

    print(f"{'src':>4} {'now':>8} {'depth':>8} {'delta':>8}  title")
    for sc, now, new, _pid, title in sorted(out):
        mark = "  " if new == now else ("UP" if new > now else "DN")
        print(f"{sc:>4} {now/100:>8.2f} {new/100:>8.2f} {(new - now)/100:>+8.2f} {mark} {title}")

    now_total = sum(o[1] for o in out)
    new_total = sum(o[2] for o in out)
    moved = [o for o in out if o[1] != o[2]]
    print(f"\npacks: {len(out)}   unchanged: {len(out) - len(moved)}   "
          f"up: {sum(1 for o in moved if o[2] > o[1])}   "
          f"down: {sum(1 for o in moved if o[2] < o[1])}")
    print(f"list-price sum: £{now_total/100:,.2f} -> £{new_total/100:,.2f} "
          f"({(new_total - now_total)/100:+,.2f})")
    over = [o for o in out if o[1] > 9999]
    print(f"packs above the £99.99 cap today: {len(over)} "
          f"(£{sum(o[1] for o in over)/100:,.2f} -> £{sum(o[2] for o in over)/100:,.2f})")
    # The inversion count is tie-order dependent, so BOTH orderings are reported rather than
    # the flattering one: sorted by depth alone, and with ties broken by today's price.
    by_depth = sorted(out, key=lambda o: o[0])
    print("pairs where the deeper pack costs LESS — "
          f"now: {sum(1 for a, b in zip(by_depth, by_depth[1:]) if b[1] < a[1])} "
          f"(ties by price: {sum(1 for a, b in zip(sorted(out), sorted(out)[1:]) if b[1] < a[1])})"
          f"   under depth: {sum(1 for a, b in zip(by_depth, by_depth[1:]) if b[2] < a[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

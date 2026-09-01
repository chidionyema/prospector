"""Set a LIVE pack's price to an explicitly named rung, overriding the price-engine.

Why this exists
---------------
`tools/reprice_to_charm_rungs.py` deliberately has no authority to make a pricing
DECISION: it only moves a pack onto the charm rung within a pound of where it already
sits, and when the catalogue and Stripe disagree it defers to the price-engine's own
rationale record. That is the right default, and it is why it reconciled 7 of the 9
desynced packs on 2026-08-15 without anyone choosing a number.

It cannot serve the remaining case. On 2026-08-15 two live packs advertised £49.00 while
Stripe held £99.99 and £79.99, and the price-engine's rationale agreed with Stripe. The
founder's call was to honour the ADVERTISED price and cut the rail down to £49.99 —
overruling the engine's segmentation, which is a decision no automated reconciliation is
allowed to make. This tool is the audited door for that decision, so it does not get made
with a curl one-liner and no record of who chose the number or why.

What it does
------------
For each `--pack ID` at the same `--to PENCE`: mint a Stripe Price for that amount on the
pack's EXISTING product, then `PATCH /internal/catalog/{id}/price`, which moves
`MinBillablePence`/`MinBillableEffectiveAt` with it and writes a `PackPriceHistory` row in
the same transaction. Nothing else about the pack is touched — not content, not copy, not
facets, not listing state.

Note which direction the floor moves. Relative to the CATALOGUE row a cut-from-Stripe can
still be a rise (4900p -> 4999p is), and the endpoint reads the catalogue, so the old floor
is held for the checkout-session drain and a session minted before this runs still clears
`FulfilmentService`'s floor check. A session minted against the OLD, higher Stripe price
charges more than the new floor, which fulfilment permits — the failure mode the floor
exists for is a payment BELOW it.

Safety
------
- Dry run by default; `--apply` is required before anything is created or written.
- Refuses to write with a non-live Stripe key: a price minted with a test key does not
  exist to the deployed Store's live requestor, so the catalogue would claim a price
  checkout cannot bill (the 2026-07-31 incident).
- `--to` must be a rung declared in `config.yaml listing.pricing.rungs`. A free-typed
  number is how the shelf goes off-ladder again, and `prove_live.py` would fail the very
  next deploy on the repair.
- `--reason` is required and has no default. This tool exists precisely for the case where
  the engine's record disagrees, so the sentence explaining why a human overruled it IS
  the artifact; `PackPriceHistory.reason` is where it lands.
- The pack's current Stripe amount is read and PRINTED before the move, so the operator
  sees the cut they are authorising rather than the number they assumed.

Usage:
    python -m tools.set_live_pack_price --pack d6f72b9dc9a45c45 --pack d4ef1efc5328d8cf \\
        --to 4999 --reason "founder 2026-08-15: honour the advertised price"
    ... --apply     # mint + PATCH
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

import requests

from prospector.bridge import EngineBridge, StripeProvisioner
from prospector.config import load_config
from prospector.run import _load_dotenv

# Same precedence and the same hard fence as tools/reprice_to_charm_rungs.py.
LIVE_KEY_VARS = ("STRIPE_LIVE_API_KEY", "STRIPE_API_KEY")

ACTOR = "tools/set_live_pack_price.py"


def _live_provisioner() -> tuple[Optional[StripeProvisioner], str]:
    """Return a provisioner built from a LIVE Stripe key, or (None, reason)."""
    for var in LIVE_KEY_VARS:
        key = os.environ.get(var, "")
        if not key:
            continue
        if "_live_" not in key:
            continue
        return StripeProvisioner(key), var
    return None, "no live Stripe key found in " + " / ".join(LIVE_KEY_VARS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", action="append", required=True,
                    help="pack id to move (repeatable; every pack goes to the same --to)")
    ap.add_argument("--to", type=int, required=True,
                    help="target price in pence; must be a declared rung")
    ap.add_argument("--reason", required=True,
                    help="why a human is overriding the price-engine; stored in PackPriceHistory")
    ap.add_argument("--apply", action="store_true",
                    help="mint Stripe prices and write the catalogue")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds between writes; the Store API rate-limits its own callers")
    ap.add_argument("--api", default=os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}",
                    help="Store API base URL")
    args = ap.parse_args()

    _load_dotenv()
    cfg = load_config("config.yaml")
    bridge = EngineBridge(cfg)

    pricing = (getattr(cfg, "listing", {}) or {}).get("pricing", {}) or {}
    rungs = [int(r) for r in (pricing.get("rungs") or [])]
    ladder_version = pricing.get("ladder_version", "unknown")
    if not rungs:
        print("FATAL: config.yaml listing.pricing.rungs is empty; there is no rung to move onto.")
        return 2
    if args.to not in rungs:
        print(f"FATAL: {args.to}p is not a declared rung. rungs = {rungs}")
        print("       A price off the ladder fails prove_live.py on the next deploy.")
        return 2

    api = args.api.rstrip("/")
    print(f"Store API:       {api}")
    print(f"ladder_version:  {ladder_version}")
    print(f"target:          {args.to}p")
    print(f"reason:          {args.reason}")

    if bridge.active_provider != "stripe":
        print(f"FATAL: active_provider is {bridge.active_provider!r}, not 'stripe'. Refusing.")
        return 2

    prov, key_var = _live_provisioner()
    if prov is None:
        print(f"FATAL: {key_var}")
        return 2
    print(f"Stripe key:      {key_var} (live)")

    if args.apply and not bridge.internal_api_key:
        print("FATAL: STORE_INTERNAL_API_KEY unset; the catalogue write would 401.")
        return 2

    try:
        resp = requests.get(f"{api}/catalog", timeout=30)
        resp.raise_for_status()
        catalogue = {p.get("id"): p for p in resp.json()}
    except Exception as e:  # noqa: BLE001 - the reason belongs on the operator's screen
        print(f"FATAL: could not read {api}/catalog: {e}")
        return 2

    planned: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for pack_id in args.pack:
        p = catalogue.get(pack_id)
        if p is None:
            skipped.append((pack_id, "not in the live catalogue"))
            continue
        current = p.get("pricePence")
        price_id = p.get("providerPriceId") or ""
        if not isinstance(current, int):
            skipped.append((pack_id, f"pricePence is {current!r}, not an integer"))
            continue
        if not price_id or price_id.startswith("price_stub_"):
            skipped.append((pack_id, f"unusable providerPriceId {price_id!r} — see tools/reprice_live_packs.py"))
            continue
        existing = prov.describe_price(price_id)
        if existing is None:
            skipped.append((pack_id, f"Stripe could not resolve {price_id}"))
            continue
        if existing.amount_pence == args.to and current == args.to:
            skipped.append((pack_id, f"already {args.to}p on both the shelf and the rail"))
            continue
        planned.append({"id": pack_id, "current": current, "stripe": existing.amount_pence,
                        "product_id": existing.product_id, "currency": existing.currency,
                        "title": str(p.get("title") or "")[:44]})

    print(f"\n{'PACK':<18} {'SHELF':>7} {'RAIL':>7} {'TO':>7}  TITLE")
    for item in planned:
        print(f"{item['id']:<18} {item['current']:>7} {item['stripe']:>7} {args.to:>7}  {item['title']}")
    if skipped:
        print(f"\nSKIPPED ({len(skipped)}):")
        for pack_id, reason in skipped:
            print(f"  {pack_id:<18}  {reason}")

    print(f"\n{len(planned)} to move, {len(skipped)} skipped.")
    if not args.apply:
        print("Dry run — nothing created, nothing written. Re-run with --apply.")
        return 0
    if not planned:
        return 0

    headers = {"X-Internal-Key": bridge.internal_api_key}
    ok = 0
    failed: list[tuple[str, str]] = []
    for item in planned:
        pack_id, current = item["id"], item["current"]
        try:
            new_price_id = prov.create_price(product_id=item["product_id"], amount_pence=args.to,
                                             currency=item["currency"])
        except Exception as e:  # noqa: BLE001
            failed.append((pack_id, f"Stripe price mint failed: {e}"))
            continue
        payload = {
            "pricePence": args.to,
            "providerPriceId": new_price_id,
            "reason": (f"operator override {ladder_version}: shelf {current}p / rail "
                       f"{item['stripe']}p -> {args.to}p ({args.reason})"),
            "actor": ACTOR,
            "rationaleRef": ladder_version,
        }
        try:
            r = requests.patch(f"{api}/internal/catalog/{pack_id}/price", json=payload,
                               headers=headers, timeout=30)
        except Exception as e:  # noqa: BLE001
            failed.append((pack_id, f"PATCH raised: {e} (Stripe price {new_price_id} was minted and is now orphaned)"))
            continue
        if r.status_code != 200:
            failed.append((pack_id, f"PATCH {r.status_code}: {r.text[:200]} (Stripe price {new_price_id} orphaned)"))
            continue
        body = r.json()
        ok += 1
        print(f"  {pack_id} {current}p -> {body.get('pricePence')}p  floor {body.get('minBillablePence')}p "
              f"until {body.get('minBillableEffectiveAt')}  {new_price_id}")
        if args.sleep:
            time.sleep(args.sleep)

    print(f"\nApplied: {ok}/{len(planned)}")
    if failed:
        print(f"FAILED ({len(failed)}):")
        for pack_id, reason in failed:
            print(f"  {pack_id}  {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

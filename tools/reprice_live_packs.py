"""Re-price LIVE packs that were listed with an unbillable `price_stub_*` id.

Why this exists
---------------
`bridge.py` assigns `price_stub_{id}` as a *fallback* before provisioning, and only
overwrites it when a provisioner is available. Before 2026-07-31 `store_payments` was
unset, so `active_provider` defaulted to a rail we held no key for, so
`provisioner` was None, so the stub survived — and the pack listed anyway. The Store's
checkout builds a Stripe Checkout Session from `ProviderPriceId`, so those packs render
a buy button that returns HTTP 500. Verified live: stub pack -> 500, real-price pack ->
200 with a `cs_live_...` url.

`store_platform/scripts/reprovision_stripe.py` solves the same problem for the LOCAL
sqlite (`Store.Api/store.db`). It cannot fix production, which is served by the deployed
Store API off its own database. This tool targets the live Store API instead.

What it does NOT do
-------------------
Nothing to content. It never regenerates artifacts, never re-uploads to R2, and omits
`contentKey`/`contentHash` from the publish payload — the Store only overwrites those
when sent, so the existing deliverable and all storefront metadata survive untouched.
Pricing is the only thing it changes. Packs that already carry a real price id are
skipped, so a re-run can never disturb a working pack.

Safety
------
Read-only by default; `--apply` is required to create Stripe objects. Stripe creation is
idempotent on the pack id (`prospector-product-{pack_id}`), so a re-run after a partial
failure reuses the same product rather than minting duplicates.

Usage:
    python -m tools.reprice_live_packs            # dry run — show what would change
    python -m tools.reprice_live_packs --apply    # create Stripe objects + update catalog
"""
from __future__ import annotations

import argparse
import os
import sys

import requests

from prospector.bridge import EngineBridge, StripeProvisioner
from prospector.config import load_config
from prospector.run import _load_dotenv

STUB_PREFIX = "price_stub_"

# The deployed Store bills through `Stripe.LiveApiRequestor`, so a price minted with a
# TEST key does not exist as far as checkout is concerned — it fails with the SAME
# "No such price" 500 as the stub it replaced, while the catalog now claims it is priced.
# That happened on 2026-07-31 (pack c0fff95b45d53f4a) because `STRIPE_API_KEY` in .env is
# a test key; the live one is `STRIPE_LIVE_API_KEY`. Prefer the live var, and hard-refuse
# to write to the live catalog with anything that isn't a live key.
LIVE_KEY_VARS = ("STRIPE_LIVE_API_KEY", "STRIPE_API_KEY")


def _live_provisioner() -> tuple[StripeProvisioner | None, str]:
    """Return a provisioner built from a LIVE Stripe key, or (None, reason)."""
    for var in LIVE_KEY_VARS:
        key = os.environ.get(var, "")
        if not key:
            continue
        if "_live_" not in key:
            continue
        return StripeProvisioner(key), var
    return None, "no live Stripe key found in " + " / ".join(LIVE_KEY_VARS)


def _stub_packs(api: str) -> list[dict]:
    """Live packs whose price id cannot be billed against."""
    resp = requests.get(f"{api}/catalog", timeout=20)
    resp.raise_for_status()
    body = resp.json()
    items = body if isinstance(body, list) else body.get("items", body.get("packs", []))
    return [p for p in items if str(p.get("providerPriceId", "")).startswith(STUB_PREFIX)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually create Stripe objects and update the live catalog")
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these pack ids (default: every stub-priced pack)")
    args = ap.parse_args(argv)

    _load_dotenv()
    cfg = load_config()
    bridge = EngineBridge(cfg)

    # Fail loudly rather than half-repairing: a missing key here means every pack would be
    # "fixed" into the same broken state it started in.
    if bridge.active_provider != "stripe":
        print(f"ERROR: active_provider is {bridge.active_provider!r}, expected 'stripe'. "
              f"Set store_payments.active_provider in config.yaml.", file=sys.stderr)
        return 2
    # Deliberately NOT bridge.provisioner: that is built from STRIPE_API_KEY, which is the
    # test key here. Writing a test price into the live catalog is the exact failure this
    # tool exists to repair.
    prov, key_var = _live_provisioner()
    if prov is None:
        print(f"ERROR: {key_var}", file=sys.stderr)
        return 2
    if not bridge.internal_api_key:
        print("ERROR: STORE_INTERNAL_API_KEY unset; the catalog write would 401.",
              file=sys.stderr)
        return 2

    api = bridge.store_api_url
    if args.only:
        # Explicit ids bypass the stub filter: a pack can also be unbillable while holding a
        # real-LOOKING price id that was minted in test mode (see module docstring), and that
        # case is invisible to a prefix check.
        wanted = set(args.only)
        resp = requests.get(f"{api}/catalog", timeout=20)
        resp.raise_for_status()
        body = resp.json()
        allp = body if isinstance(body, list) else body.get("items", body.get("packs", []))
        packs = [p for p in allp if p.get("id") in wanted]
        missing = wanted - {p.get("id") for p in packs}
        if missing:
            print(f"WARNING: not in live catalog, skipping: {sorted(missing)}", file=sys.stderr)
    else:
        packs = _stub_packs(api)

    price_pence = int(cfg.listing.get("price_pence", 4900))
    print(f"Store API : {api}")
    print(f"Stripe key: {key_var} (live)")
    print(f"Stub packs: {len(packs)}   price: {price_pence}p   "
          f"mode: {'APPLY' if args.apply else 'DRY RUN'}\n")
    if not packs:
        print("Nothing to do — no listed pack carries a stub price id.")
        return 0

    fixed = failed = 0
    for p in packs:
        pack_id = p.get("id", "")
        title = p.get("title", "")
        print(f"=== {pack_id} :: {title[:70]}")
        print(f"    current: provider={p.get('paymentProvider')} price={p.get('providerPriceId')}")
        if not args.apply:
            print("    would: create Stripe product+price, set paymentProvider=stripe\n")
            continue

        try:
            product_id = prov.create_product(
                name=title,
                description=p.get("oneLine", "") or title,
                metadata={"pack_id": pack_id, "candidate_id": pack_id,
                          "dossier_ref": p.get("dossierRef", "") or f"dossier:{pack_id}"},
            )
            new_price_id = prov.create_price(product_id=product_id, amount_pence=price_pence)
        except Exception as e:
            print(f"    STRIPE FAILED: {e}\n", file=sys.stderr)
            failed += 1
            continue

        # contentKey/contentHash deliberately omitted — the Store preserves them when the
        # field is absent, and re-sending a stale value could point a live pack at the wrong
        # object. isListed still passes the server's own `&& ContentKey != null` guard.
        ok = bridge._update_catalog(
            id=pack_id,
            title=title,
            one_line=p.get("oneLine", "") or "",
            dossier_ref=p.get("dossierRef", "") or f"dossier:{pack_id}",
            payment_provider="stripe",
            provider_product_id=product_id,
            provider_price_id=new_price_id,
            is_listed=True,
        )
        if ok:
            print(f"    -> {new_price_id}  catalog updated\n")
            fixed += 1
        else:
            print("    CATALOG UPDATE FAILED (Stripe objects exist; re-run is idempotent)\n",
                  file=sys.stderr)
            failed += 1

    print(f"Repriced {fixed}/{len(packs)} (failed {failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

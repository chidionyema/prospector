#!/usr/bin/env python3
"""
Re-provision listed packs onto Stripe (create Product + one-time Price, point the Store DB at them).

The 11 launch packs were provisioned as Paddle with `price_stub_*` ids. The Stripe checkout endpoint
builds a Checkout Session with `Price = pack.ProviderPriceId`, so each pack needs a real Stripe price
id before it can take money. This is the existing-pack equivalent of bridge.py's StripeProvisioner
(which only runs at publish time). It mirrors that logic: Product(name=Title, metadata.pack_id),
Price(unit_amount=PricePence, currency=gbp), both with idempotency keys so a re-run never duplicates.

After creating the Stripe objects it updates store.db: ProviderProductId, ProviderPriceId,
PaymentProvider='stripe'. (The web buy button keys off the pack's PaymentProvider; the API checkout
endpoint keys off payments:active_provider — set both to stripe for a coherent flow.)

Reads STRIPE_API_KEY from the repo .env (gitignored). Test-mode keys create test objects only.

Usage:
    python3 store_platform/scripts/reprovision_stripe.py --dry-run     # show what would happen
    python3 store_platform/scripts/reprovision_stripe.py               # do it (listed packs)
    python3 store_platform/scripts/reprovision_stripe.py --force       # re-create even if already stripe
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "store_platform" / "src" / "Store.Api" / "store.db"
ENV_PATH = REPO_ROOT / ".env"
STRIPE_API = "https://api.stripe.com/v1"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def stripe_post(path: str, key: str, fields: list[tuple[str, str]], idem: str) -> dict:
    """POST application/x-www-form-urlencoded to Stripe. `fields` is a list of (k, v) to allow
    repeated keys like metadata[...]. Returns parsed JSON; raises on non-2xx with the Stripe error."""
    data = urllib.parse.urlencode(fields).encode()
    auth = base64.b64encode(f"{key}:".encode()).decode()
    req = urllib.request.Request(f"{STRIPE_API}/{path}", data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Idempotency-Key", idem)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = body
        raise RuntimeError(f"Stripe {path} failed ({e.code}): {msg}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Re-create Stripe objects even if the pack already has a non-stub stripe price.")
    parser.add_argument("--currency", default="gbp")
    args = parser.parse_args()

    load_env(ENV_PATH)
    key = os.environ.get("STRIPE_API_KEY") or os.environ.get("Stripe__ApiKey")
    if not key:
        print("FATAL: STRIPE_API_KEY not in .env", file=sys.stderr)
        return 2
    mode = "TEST" if key.startswith("sk_test_") else "LIVE"
    print(f"Stripe mode: {mode}\n")

    conn = sqlite3.connect(DB_PATH, timeout=15)
    rows = conn.execute(
        "SELECT Id, Title, PricePence, ProviderProductId, ProviderPriceId, PaymentProvider "
        "FROM Packs WHERE IsListed=1 ORDER BY Id"
    ).fetchall()

    done = skipped = failed = 0
    for pack_id, title, pence, prod_id, price_id, provider in rows:
        already = (provider == "stripe" and isinstance(price_id, str)
                   and price_id.startswith("price_") and not price_id.startswith("price_stub_"))
        if already and not args.force:
            print(f"  -- {pack_id[:8]}  already stripe ({price_id}) — skip")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  >> {pack_id[:8]}  WOULD create Stripe product+price "
                  f"({pence/100:.0f} {args.currency.upper()}) for: {title[:48]}")
            done += 1
            continue

        try:
            product = stripe_post(
                "products", key,
                [("name", title), ("metadata[pack_id]", pack_id)],
                idem=f"product-create-{pack_id}",
            )
            price = stripe_post(
                "prices", key,
                [("product", product["id"]), ("unit_amount", str(pence)),
                 ("currency", args.currency.lower()), ("metadata[pack_id]", pack_id)],
                idem=f"price-create-{pack_id}-{pence}-{args.currency.lower()}",
            )
        except RuntimeError as e:
            print(f"  !! {pack_id[:8]}  {e}")
            failed += 1
            continue

        for attempt in range(5):  # tolerate a transient lock from the running API
            try:
                conn.execute(
                    "UPDATE Packs SET ProviderProductId=?, ProviderPriceId=?, PaymentProvider='stripe' "
                    "WHERE Id=?",
                    (product["id"], price["id"], pack_id),
                )
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < 4:
                    time.sleep(0.5)
                    continue
                raise
        print(f"  ++ {pack_id[:8]}  {price['id']}  ({pence/100:.0f} {args.currency.upper()})  {title[:40]}")
        done += 1

    conn.close()
    verb = "would-provision" if args.dry_run else "provisioned"
    print(f"\nDone. {verb}={done} already-stripe={skipped} failed={failed} (of {len(rows)} listed)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

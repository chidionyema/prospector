#!/usr/bin/env python3
"""
Create (or refresh) the £1 delivery-probe pack: a real, honestly-priced, purchasable pack that
is hidden from the browse catalogue.

WHY THIS EXISTS
---------------
Fulfilment could not be proved end to end without spending £49. The 50p smoke price cannot do
it: FulfilmentService.cs:88 refuses to grant an entitlement when the amount paid is below the
pack's list price, and that fence is exactly what stops a repriced session minting free packs.
On 2026-07-31 a real 50p purchase left the account and delivered nothing for precisely this
reason. See store_platform/LIVE_RAIL_SMOKE_TEST.md.

The answer is NOT a bypass in the fence. A bypass would upgrade a leaked Store:InternalApiKey
from "can open 50p sessions" to "can take any pack for free". The answer is a pack whose real
price is £1, bought at its real price of £1, so every gate runs exactly as it does for a paying
customer -- entitlement grant, download link, refund revocation, all of it.

Hidden, not unlisted. `IsListed` is the sellability fence (Program.cs:206,
CheckoutEndpoints.cs:271): unlisted means unbuyable, so an "unlisted" probe pack could never be
purchased. `HiddenFromCatalogue` splits off only the browse half -- the pack is absent from
GET /catalog, the storefront grid, and the public stats, while staying a fully normal sale.
Nothing becomes buyable that was not buyable before.

WHAT IT TOUCHES
---------------
Live money rail and live object storage. It creates a Stripe product+price and uploads content.
Run it deliberately, and read the --dry-run output first.

Usage:
  create_probe_pack.py --content-file path/to/real.zip --dry-run
  create_probe_pack.py --content-file path/to/real.zip
  create_probe_pack.py --verify-only         # re-check an existing probe pack

Then buy it at https://<storefront>/pack/<PACK_ID>, confirm the download arrives, refund it in
the Stripe dashboard, and confirm the download 410s. That is GO_LIVE_RUNBOOK.md step 4, at £1
a run instead of £49, with no fence touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(os.environ.get("PROSPECTOR_ENV_PATH", Path(__file__).resolve().parents[2] / ".env"))
API_BASE = os.environ.get("STORE_API_BASE", "https://api.mumchimp.com").rstrip("/")
STRIPE_API = "https://api.stripe.com/v1"

# Fixed so the script is idempotent: re-running refreshes the same pack rather than littering the
# catalogue with probes. The id is deliberately self-describing -- anyone finding it in the
# database or in Stripe should know what it is without asking.
PACK_ID = "probe-delivery-1gbp"
PRICE_PENCE = 100
CURRENCY = "gbp"
TITLE = "Delivery probe (internal)"
ONE_LINE = "Internal end-to-end delivery check. Not for sale to the public."


def load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def http_json(url: str, method="GET", data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def stripe_post(path: str, key: str, form: dict, idempotency: str | None = None):
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency:
        headers["Idempotency-Key"] = idempotency
    return http_json(
        f"{STRIPE_API}/{path}", "POST",
        urllib.parse.urlencode(form).encode(), headers,
    )


def upload_content(content_file: Path, dry_run: bool) -> tuple[str, str]:
    """Upload the deliverable to R2 and return (content_key, sha256)."""
    raw = content_file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    # Same layout as sync_r2_content.py: packs/<pack id>/<sha256>.zip
    key = f"packs/{PACK_ID}/{digest}.zip"

    if dry_run:
        print(f"  [dry-run] would upload {len(raw):,} bytes -> r2://{key}")
        return key, digest

    account = os.environ.get("R2_ACCOUNT_ID")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET")
    if not all([account, access, secret, bucket]):
        sys.exit("FATAL: R2 credentials incomplete in .env "
                 "(need R2_ACCOUNT_ID/ACCESS_KEY_ID/SECRET_ACCESS_KEY/BUCKET).")

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        sys.exit("FATAL: boto3 not installed (pip install boto3).")

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=BotoConfig(signature_version="s3v4", region_name="auto"),
    )
    client.put_object(Bucket=bucket, Key=key, Body=raw, ContentType="application/zip")
    print(f"  uploaded {len(raw):,} bytes -> r2://{bucket}/{key}")
    return key, digest


def verify(api_base: str) -> int:
    """Read back what actually shipped. A 200 on publish proves nothing on its own."""
    failures = 0

    status, catalogue = http_json(f"{api_base}/catalog")
    if status != 200:
        print(f"  FAIL  GET /catalog -> {status}")
        return 1
    ids = [p.get("id") for p in catalogue]
    if PACK_ID in ids:
        print(f"  FAIL  {PACK_ID} IS in the public catalogue -- it must be hidden")
        failures += 1
    else:
        print(f"  ok    absent from the browse catalogue ({len(ids)} packs listed)")

    status, pack = http_json(f"{api_base}/catalog/{PACK_ID}")
    if status != 200:
        print(f"  FAIL  GET /catalog/{PACK_ID} -> {status}; without a pack page it cannot be bought")
        failures += 1
    else:
        price = pack.get("price")
        print(f"  ok    pack page resolves, price {price}")
        if price not in ("£1.00", "£1"):
            print(f"  FAIL  price reads {price!r}, expected £1.00 -- "
                  "a probe above £1 is a fence problem, below £1 will not fulfil")
            failures += 1

    status, stats = http_json(f"{api_base}/catalog/stats")
    if status == 200:
        print(f"  ok    stats listed={stats.get('listed')} registered={stats.get('registered')} "
              "(probe excluded from both)")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--content-file", type=Path,
                        help="The real deliverable ZIP this pack hands over.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen; create and upload nothing.")
    parser.add_argument("--verify-only", action="store_true",
                        help="Only read back the current state of the probe pack.")
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    for k, v in env.items():
        os.environ.setdefault(k, v)

    print(f"API base: {API_BASE}")

    if args.verify_only:
        print("\nVerifying:")
        return 1 if verify(API_BASE) else 0

    if not args.content_file:
        return parser.error("--content-file is required unless --verify-only")
    if not args.content_file.is_file():
        return parser.error(f"--content-file not found: {args.content_file}")

    stripe_key = os.environ.get("Stripe__ApiKey") or env.get("Stripe__ApiKey")
    internal_key = os.environ.get("STORE_INTERNAL_API_KEY") or env.get("STORE_INTERNAL_API_KEY")
    if not args.dry_run:
        if not stripe_key:
            sys.exit("FATAL: Stripe__ApiKey not set")
        if not internal_key:
            sys.exit("FATAL: STORE_INTERNAL_API_KEY not set")
    live = bool(stripe_key and stripe_key.startswith("sk_live_"))
    print(f"Stripe mode: {'LIVE' if live else 'test/unset'}")

    # Stripe's test and live modes are separate object namespaces: a price minted with a test
    # key does not exist to a live key. Publishing one to the live catalogue creates a pack the
    # API cannot bill -- CanBillPriceAsync (StripeProvider.cs:434) fails the PriceService lookup
    # and refuses to list it. That fails safe, but it still leaves a dead row and a stray Stripe
    # object, and the symptom ("published fine, pack never appears") points nowhere near the
    # cause. Refuse up front instead. `.env` at the repo root holds the TEST key; the live key
    # lives in .env.production, so this is a one-character-of-attention mistake to make.
    local_api = urllib.parse.urlparse(API_BASE).hostname in ("localhost", "127.0.0.1", "::1")
    if not args.dry_run and not live and not local_api:
        sys.exit(
            f"FATAL: refusing to publish a test-mode price to {API_BASE}.\n"
            "  Stripe__ApiKey is not an sk_live_ key, so the price this would mint does not\n"
            "  exist in live mode and the API could never bill it.\n"
            "  Point PROSPECTOR_ENV_PATH at an env file holding the live key, e.g.\n"
            "    PROSPECTOR_ENV_PATH=store_platform/.env.production \\\n"
            "      python3 store_platform/scripts/create_probe_pack.py --content-file <zip>"
        )

    print("\nContent:")
    content_key, content_hash = upload_content(args.content_file, args.dry_run)

    print("\nStripe:")
    if args.dry_run:
        print(f"  [dry-run] would create product {TITLE!r} and a {PRICE_PENCE}p {CURRENCY} price")
        product_id = price_id = "(dry-run)"
    else:
        # Idempotency keys are scoped per account, so a re-run returns the same objects rather
        # than accumulating duplicate £1 products in the dashboard.
        status, product = stripe_post("products", stripe_key,
                                      {"name": TITLE, "description": ONE_LINE},
                                      idempotency=f"probe-product-{PACK_ID}")
        if status != 200:
            sys.exit(f"FATAL: Stripe product creation failed ({status}): {product}")
        product_id = product["id"]

        status, price = stripe_post("prices", stripe_key,
                                    {"product": product_id,
                                     "unit_amount": PRICE_PENCE,
                                     "currency": CURRENCY},
                                    idempotency=f"probe-price-{PACK_ID}-{PRICE_PENCE}")
        if status != 200:
            sys.exit(f"FATAL: Stripe price creation failed ({status}): {price}")
        price_id = price["id"]
        print(f"  product {product_id}  price {price_id}  {PRICE_PENCE}p {CURRENCY}")

    payload = {
        "id": PACK_ID,
        "title": TITLE,
        "oneLine": ONE_LINE,
        "dossierRef": f"internal:{PACK_ID}",
        "paymentProvider": "stripe",
        "providerProductId": product_id,
        "providerPriceId": price_id,
        # Listed, because listed IS sellable -- and hidden, so it never reaches the shop window.
        "isListed": True,
        "hiddenFromCatalogue": True,
        "pricePence": PRICE_PENCE,
        "contentKey": content_key,
        "contentHash": content_hash,
    }

    print("\nPublish:")
    if args.dry_run:
        print("  [dry-run] POST /internal/catalog " + json.dumps(payload, indent=2))
        return 0

    status, resp = http_json(
        f"{API_BASE}/internal/catalog", "POST",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json", "X-Internal-Key": internal_key},
    )
    if status != 200:
        sys.exit(f"FATAL: publish failed ({status}): {resp}")
    # The publish response is the stored entity, but it is still the write side answering. The
    # read-back below is what actually proves the state.
    print(f"  published, isListed={resp.get('isListed')} hidden={resp.get('hiddenFromCatalogue')}")

    print("\nVerifying:")
    failures = verify(API_BASE)
    if failures:
        print(f"\n{failures} check(s) FAILED.")
        return 1

    print(f"\nProbe pack ready. Buy it at /pack/{PACK_ID} for £1, confirm the download arrives,")
    print("refund it, and confirm the download 410s. That is the full delivery proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

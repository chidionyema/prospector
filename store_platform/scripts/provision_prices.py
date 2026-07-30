#!/usr/bin/env python3
"""
Provision Stripe Product+Price for every LISTED pack in PRODUCTION and repoint the production
catalogue at them via POST /internal/catalog.

Why not scripts/reprovision_stripe.py: that writes to the LOCAL store.db
(store_platform/src/Store.Api/store.db, 13 packs). Production runs /data/store.db on the Fly
volume `store_data` (35 packs). Writing the local file would look like success and change nothing.

The republish payload is deliberately explicit. Program.cs:266-277 and :310 overwrite
Title/OneLine/DossierRef/PaymentProvider/ProviderProductId/ProviderPriceId/IsListed
UNCONDITIONALLY. Omitting PaymentProvider silently reverts the pack to "paddle"; omitting
IsListed DELISTS it. So every one of those is sent with its current value.

Fields NOT sent (Headline, ContentKey, financial snapshot, ...) are only applied when non-null
(Program.cs:280-306), so omitting them preserves what is already there.

Usage:
  provision_prices.py --dry-run
  provision_prices.py            # test-mode key from .env
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Both of these were hardcoded — the API base to the live store, and the env path to one
# developer's home directory. That meant this script could only ever be pointed at production
# from one machine: no staging dry-run, and a silent failure for anyone else. Resolve the repo
# root relative to this file instead, and take the API base from the environment.
ENV_PATH = Path(os.environ.get("PROSPECTOR_ENV_PATH", Path(__file__).resolve().parents[2] / ".env"))
API_BASE = os.environ.get("STORE_API_BASE", "https://api.mumchimp.com").rstrip("/")
STRIPE_API = "https://api.stripe.com/v1"
CURRENCY = "gbp"
# Bumped when a re-provision must create NEW Stripe objects rather than return the cached
# idempotent result (e.g. switching test -> live). Stripe idempotency keys are scoped per account.
IDEM_VERSION = os.environ.get("IDEM_VERSION", "v1")


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
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def stripe_post(path: str, key: str, fields: list[tuple[str, str]], idem: str):
    data = urllib.parse.urlencode(fields).encode()
    auth = base64.b64encode(f"{key}:".encode()).decode()
    status, body = http_json(
        f"{STRIPE_API}/{path}", "POST", data,
        {"Authorization": f"Basic {auth}",
         "Content-Type": "application/x-www-form-urlencoded",
         "Idempotency-Key": idem},
    )
    if status >= 300:
        msg = (body or {}).get("error", {}).get("message", body)
        raise RuntimeError(f"Stripe {path} failed ({status}): {msg}")
    return body


def pence_from_price(label: str) -> int:
    """'£49.00' -> 4900. Refuses anything it cannot parse exactly rather than guessing a price."""
    m = re.search(r"(\d+(?:\.\d{1,2})?)", label.replace(",", ""))
    if not m:
        raise ValueError(f"cannot parse price {label!r}")
    return int(round(float(m.group(1)) * 100))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stripe-key-var", default="STRIPE_API_KEY")
    args = ap.parse_args()

    env = load_env(ENV_PATH)
    skey = os.environ.get(args.stripe_key_var) or env.get(args.stripe_key_var)
    ikey = os.environ.get("STORE_INTERNAL_API_KEY") or env.get("STORE_INTERNAL_API_KEY")
    if not skey:
        print(f"FATAL: {args.stripe_key_var} not set", file=sys.stderr)
        return 1
    if not ikey:
        print("FATAL: STORE_INTERNAL_API_KEY not set", file=sys.stderr)
        return 1
    mode = "TEST" if skey.startswith("sk_test") else "LIVE"
    print(f"Stripe key mode: {mode}   idempotency version: {IDEM_VERSION}")

    status, listed = http_json(f"{API_BASE}/catalog")
    if status != 200:
        print(f"FATAL: /catalog returned {status}", file=sys.stderr)
        return 1
    items = listed if isinstance(listed, list) else listed.get("items", [])
    print(f"listed packs in production: {len(items)}\n")

    ok = failed = 0
    for i, row in enumerate(items, 1):
        pid = row["id"]
        st, d = http_json(f"{API_BASE}/catalog/{pid}")
        if st != 200:
            print(f"[{i:2}/{len(items)}] {pid} SKIP — detail fetch {st}")
            failed += 1
            continue
        title, one_line = d["title"], d["oneLine"]
        dossier, pence = d["dossierRef"], pence_from_price(d["price"])
        print(f"[{i:2}/{len(items)}] {pid}  {title[:44]:44} {pence/100:>7.2f} {CURRENCY.upper()}"
              f"  was={d.get('providerPriceId')}")
        if args.dry_run:
            continue
        try:
            prod = stripe_post("products", skey,
                               [("name", title), ("description", one_line[:500]),
                                ("metadata[pack_id]", pid)],
                               f"prod-{pid}-{IDEM_VERSION}")
            price = stripe_post("prices", skey,
                                [("product", prod["id"]), ("unit_amount", str(pence)),
                                 ("currency", CURRENCY), ("metadata[pack_id]", pid)],
                                f"price-{pid}-{pence}-{IDEM_VERSION}")
        except RuntimeError as e:
            print(f"            STRIPE FAILED: {e}")
            failed += 1
            continue

        payload = {
            "id": pid, "title": title, "oneLine": one_line, "dossierRef": dossier,
            "paymentProvider": "stripe",
            "providerProductId": prod["id"], "providerPriceId": price["id"],
            "isListed": True,          # omitting this DELISTS the pack (Program.cs:310)
        }
        st2, resp = http_json(f"{API_BASE}/internal/catalog", "POST",
                              json.dumps(payload).encode(),
                              {"Content-Type": "application/json", "X-Internal-Key": ikey})
        if st2 != 200:
            print(f"            PUBLISH FAILED {st2}: {str(resp)[:200]}")
            failed += 1
            continue
        print(f"            -> {price['id']}  (product {prod['id']})")
        ok += 1

    print(f"\nprovisioned ok: {ok}   failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

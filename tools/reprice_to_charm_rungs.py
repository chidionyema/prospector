"""Move LIVE packs onto the charm rungs of the L1 ladder (£49.00 -> £49.99).

Why this exists
---------------
`config.yaml listing.pricing.rungs` became the charm ladder
(`[1999, 2999, 4999, 7999, 9999, 14999, 19999]`, `ladder_version:
L1-ladder-2026-08-09-charm`) on 2026-08-09. That change only reaches packs published
AFTER it: `bridge.py:946-975` deliberately reuses the exact Stripe product and price an
on-sale pack is already sold with, because minting on every publish is what a provider
idempotency key only appears to prevent (Stripe's expires after 24h). So every pack
listed before the change kept its round rung, and the live shelf still reads £49.00.

Re-pricing a live pack is therefore not a config edit — it is a money-rail migration, and
it goes through the audited door: mint a new Stripe Price caller-side, then
`PATCH /internal/catalog/{id}/price`, which refuses anything Stripe cannot bill, moves
`MinBillablePence`/`MinBillableEffectiveAt` with the price, and writes a `PackPriceHistory`
row in the same transaction. Every move here is a RISE, which is exactly the direction
that sets the floor to `now + CheckoutSessionDrain`, so a checkout session minted at the
old price still clears `FulfilmentService`'s floor check
(`FulfilmentService.cs:110-126`) and the buyer is not charged-then-refused.

What it does NOT do
-------------------
Nothing to content, copy, facets or listing state. It never republishes. It touches one
Stripe object (a new Price on the pack's EXISTING product) and one catalogue field.

Safety
------
- Dry run by default; `--apply` is required before anything is created or written.
- Refuses to write unless the Stripe key is a LIVE key (`_live_` in the secret): a price
  minted with a test key does not exist to the deployed Store's live requestor, so the
  catalogue would claim a price checkout cannot bill. That is the 2026-07-31 incident.
- The target rung is DERIVED from `config.yaml`, never hardcoded: the charm rung for a
  price is the configured rung that is above it by less than a full pound. A price with no
  such rung is skipped and reported, never guessed at.
- Stripe is consulted as the source of truth before each move (`describe_price`): if the
  live Price does not carry the amount the catalogue claims, the pack is skipped loudly
  rather than migrated on top of an existing desync.
- `create_price` is idempotent on (product, amount, currency), so a re-run after a partial
  failure reuses the price it already minted instead of orphaning duplicates.

Usage:
    python -m tools.reprice_to_charm_rungs             # dry run over every live pack
    python -m tools.reprice_to_charm_rungs --apply     # mint + PATCH
    python -m tools.reprice_to_charm_rungs --limit 1 --apply   # one pack first
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

from prospector.bridge import EngineBridge, StripeProvisioner
from prospector.config import load_config, store_root
from prospector.run import _load_dotenv

# Same precedence and the same hard fence as tools/reprice_live_packs.py: prefer the
# explicitly-live var, and refuse to write to the live catalogue with anything else.
LIVE_KEY_VARS = ("STRIPE_LIVE_API_KEY", "STRIPE_API_KEY")

ACTOR = "tools/reprice_to_charm_rungs.py"

def _rationale_dir() -> Path:
    """Where the price rationale lands, from the one resolver, read on every call.

    This was the module constant `Path("store/pricing/rationale")`: relative to the process
    working directory, so it wrote beside whatever launched it rather than into the store.
    A module constant would also bind the answer at import, before a test can redirect it.
    INC-2026-08-18-store-resolver.
    """
    return store_root() / "pricing" / "rationale"


def engine_decision_pence(pack_id: str) -> tuple[Optional[int], str]:
    """What `price-engine` actually decided for this pack, from its own rationale record.

    `pricing.py` writes one of these per decision (`actor: price-engine`, `source:
    prospector/bridge.py`) carrying the rung, the segment that chose it and the ladder
    fingerprint. It is the only durable record of the decision that is independent of both
    the catalogue row and the Stripe object, which is exactly what a two-against-one
    reconciliation needs.
    """
    d = _rationale_dir() / pack_id
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        return None, f"no price rationale under {d}"
    latest = files[-1]  # names are ISO-8601 timestamps, so lexical order is chronological
    try:
        decision = json.loads(latest.read_text(encoding="utf-8")).get("decision") or {}
    except Exception as e:  # noqa: BLE001
        return None, f"unreadable rationale {latest.name}: {e}"
    pence = decision.get("price_pence")
    if not isinstance(pence, int):
        return None, f"rationale {latest.name} has no integer decision.price_pence"
    return pence, f"{latest.name} ({decision.get('rung', 'rung unrecorded')})"


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


def charm_rung(price_pence: int, rungs: list[int]) -> Optional[int]:
    """The configured rung this price should move to, or None if there isn't one.

    Derived, not tabulated: a charm rung sits strictly above the round price it replaces
    and by less than a whole pound (4900 -> 4999). Anything further away is a different
    price decision — a re-segmentation — and this tool has no authority to make it, so it
    returns None and the caller skips the pack with the reason printed.
    """
    candidates = [r for r in rungs if 0 < r - price_pence < 100]
    if not candidates:
        return None
    return min(candidates)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="mint Stripe prices and write the catalogue")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N eligible packs")
    ap.add_argument("--pack", action="append", default=[], help="only this pack id (repeatable)")
    ap.add_argument("--reconcile", action="store_true",
                    help="also fix packs where Stripe already disagrees with the catalogue, when the "
                         "price-engine's own rationale record independently agrees with Stripe")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds between writes; the Store API rate-limits its own callers")
    ap.add_argument("--api", default=os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}",
                    help="Store API base URL")
    args = ap.parse_args()

    _load_dotenv()
    cfg = load_config("config.yaml")
    bridge = EngineBridge(cfg)

    pricing = (getattr(cfg, "listing", {}) or {}).get("pricing", {}) or {}
    rungs = list(pricing.get("rungs") or [])
    ladder_version = pricing.get("ladder_version", "unknown")
    if not rungs:
        print("FATAL: config.yaml listing.pricing.rungs is empty; nothing to move packs onto.")
        return 2

    api = args.api.rstrip("/")
    print(f"Store API:       {api}")
    print(f"ladder_version:  {ladder_version}")
    print(f"rungs:           {rungs}")

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
        packs = resp.json()
    except Exception as e:  # noqa: BLE001 - the reason belongs on the operator's screen
        print(f"FATAL: could not read {api}/catalog: {e}")
        return 2
    if args.pack:
        wanted = set(args.pack)
        packs = [p for p in packs if p.get("id") in wanted]
    print(f"live packs:      {len(packs)}\n")

    planned: list[dict] = []                 # pack, target, product_id, currency, basis
    skipped: list[tuple[str, int, str]] = []  # id, price, reason

    for p in packs:
        pack_id = p.get("id", "?")
        current = p.get("pricePence")
        price_id = p.get("providerPriceId") or ""
        if not isinstance(current, int):
            skipped.append((pack_id, -1, f"pricePence is {current!r}, not an integer"))
            continue
        if not price_id or price_id.startswith("price_stub_"):
            skipped.append((pack_id, current, f"unusable providerPriceId {price_id!r} — see tools/reprice_live_packs.py"))
            continue
        existing = prov.describe_price(price_id)
        if existing is None:
            skipped.append((pack_id, current, f"Stripe could not resolve {price_id}"))
            continue

        if existing.amount_pence == current:
            # The ordinary case: catalogue and money rail agree, so only the rung moves.
            target = charm_rung(current, rungs)
            if target is None:
                reason = "already on a rung" if current in rungs else "no charm rung within £1 above it"
                skipped.append((pack_id, current, reason))
                continue
            basis = f"charm rung for {current}p"
        else:
            # The catalogue and the card disagree about what this pack costs. Which number is
            # right is NOT a judgement call to make here, and not a pricing decision either:
            # the price-engine wrote down what it decided, independently of both, so require
            # that third record to agree with the rail before touching anything. Two
            # independent records against one is a reconciliation; anything less is a guess,
            # and a guess on this rail either overcharges a buyer or strands a paid order.
            desync = (f"DESYNC: Stripe {price_id} charges {existing.amount_pence}p, "
                      f"catalogue says {current}p")
            if not args.reconcile:
                skipped.append((pack_id, current, desync + " — re-run with --reconcile"))
                continue
            decided, note = engine_decision_pence(pack_id)
            if decided is None:
                skipped.append((pack_id, current, f"{desync}; cannot reconcile: {note}"))
                continue
            if decided != existing.amount_pence:
                skipped.append((pack_id, current,
                                f"{desync}; price-engine decided {decided}p — three records, three "
                                f"answers, needs a human ({note})"))
                continue
            target = charm_rung(decided, rungs) or (decided if decided in rungs else None)
            if target is None:
                skipped.append((pack_id, current, f"{desync}; no charm rung for the decided {decided}p"))
                continue
            basis = f"reconcile to price-engine {decided}p, charm rung {target}p [{note}]"
        planned.append({"pack": p, "target": target, "product_id": existing.product_id,
                        "currency": existing.currency, "basis": basis})

    if args.limit:
        planned = planned[: args.limit]

    print(f"{'PACK':<18} {'FROM':>7} {'TO':>7}  BASIS / TITLE")
    for item in planned:
        p = item["pack"]
        detail = item["basis"] if item["basis"].startswith("reconcile") else str(p.get("title"))[:52]
        print(f"{p['id']:<18} {p['pricePence']:>7} {item['target']:>7}  {detail}")
    if skipped:
        print(f"\nSKIPPED ({len(skipped)}):")
        for pack_id, price, reason in skipped:
            print(f"  {pack_id:<18} {price:>7}  {reason}")

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
        p, target = item["pack"], item["target"]
        product_id, currency, basis = item["product_id"], item["currency"], item["basis"]
        pack_id = p["id"]
        current = p["pricePence"]
        try:
            new_price_id = prov.create_price(product_id=product_id, amount_pence=target, currency=currency)
        except Exception as e:  # noqa: BLE001
            failed.append((pack_id, f"Stripe price mint failed: {e}"))
            continue
        payload = {
            "pricePence": target,
            "providerPriceId": new_price_id,
            "reason": f"L1 charm ladder {ladder_version}: {current}p -> {target}p ({basis})",
            "actor": ACTOR,
            "rationaleRef": ladder_version,
        }
        try:
            r = requests.patch(f"{api}/internal/catalog/{pack_id}/price", json=payload, headers=headers, timeout=30)
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

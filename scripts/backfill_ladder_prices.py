#!/usr/bin/env python3
"""C1 — move the live catalogue off the flat £49 onto the L1 segment ladder.

This is the one act in the pricing work that mutates the production money rail, and it is
Claude-only by the founder fence for exactly that reason. Everything here is arranged so that
a failure stops the run rather than half-repricing the shelf.

Ordering, and why it is not the obvious one
-------------------------------------------
Per pack: mint the new Stripe Price FIRST, then PATCH the catalogue.

Stripe ``Price`` objects are immutable, so a change always mints a new id. Minting first means
the failure mode of a crash between the two steps is an orphaned Price object in Stripe that
nothing points at — inert, costs nothing, and the next run's idempotency key reuses it. The
reverse order fails as a catalogue row pointing at a price id that does not exist, which is a
listed pack that cannot take money.

The drain is the endpoint's problem, not ours (``Pack.EffectiveFloorPence``): a rise holds the
old floor for the checkout-session window, a cut applies immediately. That is why this script
does not care whether a given pack is going up or down.

Verification
------------
Every pack is verified by READ-BACK from the public ``/catalog``, never by the PATCH's status
code. A 200 proves the handler ran; it never proves the value landed
(``store-catalog-metadata-is-typed-columns``). A pack whose read-back disagrees aborts the run
before the next pack is touched.

Segment source
--------------
The catalogue row does not carry ``ambition_tier`` — it is a typed-column schema and the tier
was never one of the columns. The tier comes from the stored dossier under ``store/dossiers/``,
matched on ``candidate_id``. A pack with no dossier is skipped loudly, never guessed at.

Usage
-----
    .venv/bin/python scripts/backfill_ladder_prices.py            # dry run, no writes
    .venv/bin/python scripts/backfill_ladder_prices.py --apply    # writes
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import (
    load_config,  # noqa: E402
    store_root,  # noqa: E402
)
from prospector.models import Candidate, ScoreResult  # noqa: E402
from prospector.price_rationale import write_rationale  # noqa: E402
from prospector.pricing import price_for  # noqa: E402

STORE_API = os.environ.get("STORE_API_URL", "https://api.mumchimp.com")
ACTOR = "claude:C1-ladder-backfill"
SOURCE = "scripts/backfill_ladder_prices.py"


@lru_cache(maxsize=1)
def cfg() -> Any:
    """One Config for the whole run: the ladder that plans the moves must be the same
    object that is snapshotted onto each rationale record, or the record would describe a
    ladder the run never used."""
    return load_config()


def ladder_version() -> str:
    return str(((cfg().listing or {}).get("pricing") or {}).get("ladder_version")
               or "unversioned-ladder")


def _load_dotenv() -> None:
    """Read .env without a dependency. `grep -r` never opens it (it is gitignored, and grep
    here is ugrep --ignore-files), so this is also the only reliable way to see these keys.

    Honours `PROSPECTOR_DISABLE_DOTENV` for the same reason `prospector.run._load_dotenv`
    (:2444) does: `setdefault` fills exactly the gap a test credential-fence creates by
    deleting a key, so any un-guarded copy of this function re-arms live keys from disk."""
    if os.environ.get("PROSPECTOR_DISABLE_DOTENV", "").strip() not in ("", "0", "false", "False"):
        return
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_json(url: str, headers: Optional[dict] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def _pence(price_str: str) -> int:
    return int(round(float(str(price_str).replace("£", "").replace(",", "")) * 100))


def load_plan() -> tuple[list[dict], list[dict], list[str]]:
    """Return (moves, holds, unmatched_ids) computed from live state + the shipped ladder."""
    rungs = (cfg().listing or {}).get("pricing", {}).get("rungs")
    assert rungs, "ladder must be loaded — an empty ladder would silently hold every pack"

    packs = _get_json(f"{STORE_API}/catalog")

    dossiers: dict[str, dict] = {}
    for f in glob.glob(str(store_root() / "dossiers" / "*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        c = d.get("candidate") or {}
        cid = c.get("candidate_id") or d.get("candidate_id")
        if cid:
            dossiers[cid] = c

    moves, holds, unmatched = [], [], []
    for p in packs:
        c = dossiers.get(p["id"])
        if c is None:
            unmatched.append(p["id"])
            continue
        cand = Candidate(title=c.get("title", ""), one_liner=c.get("one_liner", ""),
                         ambition_tier=c.get("ambition_tier") or "",
                         market=c.get("market") or "")
        # No `anchors=`: C3's rung adjustment is off by default and this backfill must move
        # packs onto the declared ladder and nowhere else. Evidence-driven moves are a
        # separate decision, taken later, with their own citations in the Reason.
        dec = price_for(cand, ScoreResult(scores={}, justification={}), cfg())
        row = {
            "id": p["id"], "title": p["title"], "market": cand.market,
            "tier": cand.ambition_tier, "current_pence": _pence(p["price"]),
            "new_pence": dec.price_pence, "rung": dec.rung, "rationale": dec.rationale,
            "provider": p.get("paymentProvider"), "price_id": p.get("providerPriceId"),
            # The decision object itself, carried through to the D3 rationale record so the
            # record describes the same derivation this row was planned from — not a second
            # `price_for` call that could see a different config a moment later.
            "decision": dec,
        }
        (moves if row["new_pence"] != row["current_pence"] else holds).append(row)
    return moves, holds, unmatched


def preflight(moves: list[dict]) -> "Any":
    """Prove every precondition BEFORE the first write, and return the Stripe client.

    Each check exists because its failure mid-run leaves the shelf half-repriced:
      * a live-mode Stripe key, because the deployed Store cannot bill a test-mode price
        (`bridge.py._select_stripe_key` refuses the remote catalogue without one)
      * the internal API key, proven against a READ endpoint, not by attempting a write
      * every pack on `stripe` with a resolvable, live-mode Price whose Product we can mint on
    """
    _load_dotenv()

    key = os.environ.get("STRIPE_LIVE_API_KEY") or ""
    if "_live_" not in key:
        raise SystemExit("refusing to run: no STRIPE_LIVE_API_KEY — a test-mode price cannot "
                         "be billed by the live Store, and the endpoint would reject it")
    internal = os.environ.get("STORE_INTERNAL_API_KEY") or ""
    if not internal:
        raise SystemExit("refusing to run: no STORE_INTERNAL_API_KEY")

    import stripe
    stripe.api_key = key

    # Key probe on a read endpoint: a 401 here is a misconfiguration, and finding that out
    # from a PATCH would mean finding it out from a write.
    probe = moves[0]["id"]
    _get_json(f"{STORE_API}/internal/catalog/{probe}/content", {"X-Internal-Key": internal})
    print(f"  internal key OK (GET /internal/catalog/{probe[:12]}…/content -> 200)")

    for m in moves:
        if m["provider"] != "stripe":
            raise SystemExit(f"refusing to run: {m['id']} is on {m['provider']!r}, not stripe")
        if not m["price_id"]:
            raise SystemExit(f"refusing to run: {m['id']} has no providerPriceId")
        # Attribute access, not .get(): a stripe StripeObject raises AttributeError on .get,
        # so `price.get("livemode")` would blow up rather than defaulting — which is how the
        # first run of this script failed, in preflight, before any write. Good place for it.
        price = stripe.Price.retrieve(m["price_id"])
        if not price.livemode:
            raise SystemExit(f"refusing to run: {m['id']} points at a test-mode price")
        m["product_id"] = price.product
        if price.unit_amount != m["current_pence"]:
            raise SystemExit(
                f"refusing to run: {m['id']} catalogue says {m['current_pence']}p but its "
                f"Stripe price is {price.unit_amount}p — the two already disagree, and a "
                f"backfill on top of a drift would bury it")
    print(f"  {len(moves)} packs preflighted: live-mode stripe prices, products resolved, "
          f"catalogue and Stripe amounts agree")
    return stripe


def patch_reason(m: dict) -> str:
    """The one line a human reads on the price-history row."""
    return (f"{ladder_version()}: segment {m['tier'] or 'unclassified'}/"
            f"{m['market'] or 'unknown'} -> {m['rung']}. {m['rationale']}")


def build_patch_payload(m: dict, provider_price_id: str, rationale_ref: str) -> dict:
    """The PATCH body. Split out from `apply_one` so a test can assert that the
    `rationaleRef` it carries is exactly the record D3 wrote — the two are one claim, and
    a ref that points at nothing is indistinguishable from no ref at all."""
    return {
        "pricePence": m["new_pence"],
        "providerPriceId": provider_price_id,
        "actor": ACTOR,
        "reason": patch_reason(m),
        "rationaleRef": rationale_ref,
    }


def apply_one(stripe, m: dict, internal: str) -> None:
    """Mint, write the rationale record, PATCH, read back. Raises on any disagreement.

    The record is written BEFORE the PATCH on purpose: a record with no price change is a
    harmless orphan, whereas a price change whose `rationaleRef` points at a file that was
    never written is a live price nobody can account for.
    """
    new_price = stripe.Price.create(
        product=m["product_id"], unit_amount=m["new_pence"], currency="gbp",
        idempotency_key=f"c1-ladder-{m['id']}-{m['new_pence']}-gbp",
    )
    print(f"    minted {new_price.id} @ {m['new_pence']}p")

    ref = write_rationale(m["id"], m["decision"], cfg(),
                          actor=ACTOR, source=SOURCE, reason=patch_reason(m))
    print(f"    rationale {ref}")

    payload = build_patch_payload(m, new_price.id, ref)
    req = urllib.request.Request(
        f"{STORE_API}/internal/catalog/{m['id']}/price",
        data=json.dumps(payload).encode(), method="PATCH",
        headers={"Content-Type": "application/json", "X-Internal-Key": internal})
    with urllib.request.urlopen(req, timeout=45) as r:
        body = json.loads(r.read())
    print(f"    PATCH 200: price={body['pricePence']}p floor={body['minBillablePence']}p "
          f"until={body['minBillableEffectiveAt']}")

    # The read-back is the proof. A 200 proves the handler ran, never that the value landed.
    time.sleep(1.0)
    packs = _get_json(f"{STORE_API}/catalog")
    live = next((p for p in packs if p["id"] == m["id"]), None)
    if live is None:
        raise SystemExit(f"ABORT: {m['id']} vanished from /catalog after the write")
    got = _pence(live["price"])
    if got != m["new_pence"]:
        raise SystemExit(f"ABORT: {m['id']} read back {got}p, expected {m['new_pence']}p")
    if live.get("providerPriceId") != new_price.id:
        raise SystemExit(f"ABORT: {m['id']} read back price id {live.get('providerPriceId')}, "
                         f"expected {new_price.id}")
    print(f"    read-back OK: {live['price']} / {new_price.id}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="perform the writes (default is a dry run)")
    ap.add_argument("--only", default="", help="comma-separated pack ids to limit the run to")
    args = ap.parse_args()

    moves, holds, unmatched = load_plan()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        moves = [m for m in moves if m["id"] in wanted]

    print(f"live packs: {len(moves) + len(holds) + len(unmatched)}  "
          f"move: {len(moves)}  hold: {len(holds)}  no-dossier: {len(unmatched)}")
    if unmatched:
        print(f"  SKIPPED (no dossier, tier unknowable): {unmatched}")
    for m in sorted(moves, key=lambda r: r["new_pence"]):
        arrow = "CUT " if m["new_pence"] < m["current_pence"] else "RISE"
        print(f"  {arrow} {m['id'][:16]} {m['current_pence']:>6}p -> {m['new_pence']:>6}p  "
              f"[{m['tier'] or '-'}/{m['market'] or '-'}]  {m['title'][:48]}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
        return 0
    if not moves:
        print("\nnothing to do.")
        return 0

    stripe = preflight(moves)
    internal = os.environ["STORE_INTERNAL_API_KEY"]
    print(f"\napplying {len(moves)} price changes, one at a time, aborting on first mismatch\n")
    for i, m in enumerate(sorted(moves, key=lambda r: r["new_pence"]), 1):
        print(f"[{i}/{len(moves)}] {m['id'][:16]} {m['current_pence']}p -> {m['new_pence']}p "
              f"({m['title'][:44]})")
        apply_one(stripe, m, internal)
    print(f"\ndone: {len(moves)} packs repriced and read back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

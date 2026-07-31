#!/usr/bin/env python3
"""
Build the deliverable ZIP handed over by the £1 delivery-probe pack.

WHY THIS IS NOT A REAL PACK'S CONTENT
-------------------------------------
The obvious shortcut is to point the probe at an existing bundle from publish/bundles/. Don't.
The probe pack is HIDDEN, not unlisted -- hidden means absent from the browse catalogue while
staying fully purchasable, and `probe-delivery-1gbp` is a guessable URL. Shipping a £49 pack's
content behind a £1 price would mean anyone who guessed the id could buy the real thing for £1.

Nothing is lost by using purpose-made content. The delivery chain being proved -- R2 object ->
entitlement -> presigned URL -> download -> refund revokes it -- is entirely content-agnostic.
It needs a real object with real bytes and a correct sha256, which this produces. It does not
need the bytes to be saleable.

WHY IT IS DETERMINISTIC
-----------------------
ZIP archives embed mtimes, so zipping the same files twice normally yields different bytes,
a different sha256, and therefore a different R2 key (packs/<id>/<sha256>.zip). That would
break create_probe_pack.py's idempotency: every re-run would upload a new object and repoint
the pack's ContentHash. Fixing the timestamp and the compression makes the output byte-stable,
so re-running the probe is genuinely a no-op.

Usage:
  build_probe_content.py --out /tmp/probe-content.zip
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

# Fixed epoch for every entry. Any constant works; this one is the date the probe pack was
# designed, so the archive says when the format was set rather than when it was last zipped.
FIXED_DATE = (2026, 7, 31, 0, 0, 0)

README = """# Delivery probe pack

This is not a product. It is the payload of an internal £1 pack whose only job is to prove,
repeatably and for real money, that the delivery chain works end to end:

    checkout -> payment -> webhook -> Order -> Entitlement -> presigned R2 URL -> this file

If you are reading this after downloading it from a purchase, every link in that chain held.

## Why it costs £1 rather than 50p

A purchase below a pack's list price grants nothing. `FulfilmentService.cs` refuses to create
the entitlement when the amount paid is under `PricePence`, which is exactly what stops a
repriced checkout session from minting free packs. So a token 50p payment can never prove
delivery -- it proves render, card entry, charge, webhook and the Order row, then stops.

On 2026-07-31 a real 50p purchase was made against a £49 pack to test delivery. The money left
the account and no download ever arrived, for precisely this reason. The fence was right; the
test was wrong. This pack is the corrected test: a genuine £1 price, paid in full, so every
gate runs exactly as it does for a paying customer.

## Why it is hidden rather than unlisted

`IsListed` is the sellability fence, not a visibility flag -- an unlisted pack is refused at
checkout and has no pack page, so an "unlisted probe pack" could never be bought. Hiding is a
separate flag (`HiddenFromCatalogue`) that removes the pack from the browse catalogue and the
public counts while leaving it a completely normal sale.

## How to finish the proof

After the download works, refund the payment in the Stripe dashboard and re-request this file.
The link must fail with 410 Gone. A refund that leaves the download working is a revocation bug,
and it is the half of the chain that is easiest to leave untested.
"""

MANIFEST = """probe-delivery-1gbp
===================
price          100p GBP
visibility     hidden from catalogue, listed for sale
purpose        end-to-end delivery + revocation proof
built by       store_platform/scripts/build_probe_content.py
"""

FILES = {
    "README.md": README,
    "MANIFEST.txt": MANIFEST,
}


def build(out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in sorted(FILES.items()):
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, body)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="Path to write the ZIP to.")
    args = parser.parse_args()

    digest = build(args.out)
    size = args.out.stat().st_size
    print(f"{args.out}  {size:,} bytes  sha256={digest}")
    print(f"R2 key would be packs/probe-delivery-1gbp/{digest}.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

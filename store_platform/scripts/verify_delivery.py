#!/usr/bin/env python3
"""
Verify the half of the money rail that only a real purchase can reach.

Everything up to card entry is already provable without spending anything: the pack page
renders, and POST /packs/{id}/checkout returns a live Stripe session, which proves the price is
billable. What no automated check can reach is what happens AFTER the card clears:

    webhook -> Order -> Entitlement -> presigned R2 URL -> the actual bytes -> refund revokes it

That is the part that silently broke on 2026-07-31: the payment succeeded, fulfilment granted
nothing (underpaid line), and the API reported "pending" so the storefront blamed lag. This
script is the check that would have caught it in seconds instead of leaving it to a buyer.

Run it in two phases around the manual test:

  # 1. straight after paying (session id is on the success page / in the Stripe dashboard)
  verify_delivery.py --session cs_live_...

  # 2. after refunding that payment in the Stripe dashboard
  verify_delivery.py --session cs_live_... --expect revoked

Phase 1 saves the grant tokens to a state file, because once the refund lands the API stops
returning them (the order's items list is empty when nothing is active) -- so phase 2 would have
nothing left to test the 410 against.

NOTE ON THE DOWNLOAD CAP: /download/{token} mints a presigned URL and increments
DownloadCount every time it is called (DeliveryEndpoints.cs). The cap is small by design, so
this script deliberately fetches each link ONCE per phase.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

API_BASE = "https://api.mumchimp.com"
STATE_DIR = Path(__file__).resolve().parents[1] / ".delivery-proof"

# The probe pack's deliverable is byte-deterministic (build_probe_content.py), so the exact
# sha256 of what a buyer receives is known in advance. Anything else means the wrong object was
# served or it was corrupted in transit.
PROBE_PACK_ID = "probe-delivery-1gbp"
PROBE_SHA256 = "07bdffb51ce863dea7f170705f7ba0331bae11c839dbb33d283657167d104324"


class Result:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, msg: str) -> None:
        print(f"  ok    {msg}")

    def fail(self, msg: str) -> None:
        print(f"  FAIL  {msg}")
        self.failures.append(msg)

    def check(self, cond: bool, ok_msg: str, fail_msg: str) -> bool:
        self.ok(ok_msg) if cond else self.fail(fail_msg)
        return cond


def get(url: str, follow: bool = True, timeout: int = 30):
    """Return (status, body_bytes, location_header)."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = (urllib.request.build_opener()
              if follow else urllib.request.build_opener(NoRedirect))
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Location")


def state_path(session: str) -> Path:
    # Session ids are long and contain no path separators, but hash anyway so the filename is
    # bounded and the raw id does not end up on disk.
    return STATE_DIR / f"{hashlib.sha256(session.encode()).hexdigest()[:16]}.json"


def poll_order(session: str, timeout: int, res: Result) -> dict | None:
    """Poll until the status is terminal. 'pending' is the only non-terminal answer."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        status, body, _ = get(f"{API_BASE}/api/orders/by-session/{session}")
        if status != 200:
            res.fail(f"GET /api/orders/by-session -> HTTP {status}")
            return None
        data = json.loads(body)
        if data.get("status") != "pending":
            print(f"  ..    settled after {attempt} poll(s): status={data.get('status')!r}")
            return data
        time.sleep(2)
    res.fail(f"still 'pending' after {timeout}s — the webhook never arrived, or it errored. "
             "Check the Stripe dashboard's webhook delivery log for this event.")
    return None


def verify_bytes(url: str, res: Result) -> None:
    status, body, _ = get(url)
    if not res.check(status == 200, f"presigned URL served {len(body):,} bytes",
                     f"presigned URL -> HTTP {status}"):
        return

    digest = hashlib.sha256(body).hexdigest()
    res.check(digest == PROBE_SHA256,
              f"sha256 matches the published deliverable ({digest[:16]}…)",
              f"sha256 MISMATCH: got {digest}, expected {PROBE_SHA256}")

    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = zf.namelist()
            bad = zf.testzip()
        res.check(bad is None and "README.md" in names,
                  f"zip opens and is intact: {names}",
                  f"zip damaged (first bad entry {bad!r}) or missing README.md: {names}")
    except zipfile.BadZipFile as e:
        res.fail(f"delivered bytes are not a valid zip: {e}")


def phase_ready(session: str, timeout: int, res: Result) -> None:
    print("\nPhase 1 — the buyer's download")
    data = poll_order(session, timeout, res)
    if data is None:
        return

    status = data.get("status")
    if status == "unfulfilled":
        res.fail("PAID WITHOUT FULFILMENT — the payment succeeded and nothing was granted. "
                 "This is the 2026-07-31 failure exactly. The API logged "
                 "PAID-WITHOUT-FULFILMENT at Error with the order id; the usual cause is a "
                 "line paid below the pack's PricePence (FulfilmentService.cs:88).")
        return
    if status == "revoked":
        res.fail("entitlements exist but all are revoked — already refunded or disputed? "
                 "Run with --expect revoked if that was intentional.")
        return
    if not res.check(status == "ready", "order is ready", f"unexpected status {status!r}"):
        return

    items = data.get("items") or []
    if not res.check(bool(items), f"{len(items)} item(s) granted", "status ready but NO items"):
        return

    tokens = []
    for item in items:
        pack_id = item.get("packId")
        path = item.get("downloadPath", "")
        token = path.rsplit("/", 1)[-1]
        tokens.append({"packId": pack_id, "token": token})
        print(f"\n  pack {pack_id!r} — {item.get('packTitle')!r}")

        status, _, location = get(f"{API_BASE}{path}", follow=False)
        if not res.check(status in (301, 302, 307),
                         f"/download/… redirects (HTTP {status})",
                         f"/download/… -> HTTP {status}, expected a redirect to R2"):
            continue
        if not res.check(bool(location), "redirect carries a presigned URL",
                         "redirect had no Location header"):
            continue
        if pack_id == PROBE_PACK_ID:
            verify_bytes(location, res)
        else:
            res.ok(f"not the probe pack — skipping byte check for {pack_id}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(session).write_text(json.dumps({"tokens": tokens}, indent=2))
    print(f"\n  grant token(s) saved to {state_path(session)}")
    print("  Now refund the payment in the Stripe dashboard, then re-run with --expect revoked.")


def phase_revoked(session: str, timeout: int, res: Result) -> None:
    print("\nPhase 2 — refund must revoke access")
    sp = state_path(session)
    if not sp.exists():
        res.fail(f"no saved state at {sp} — run phase 1 (without --expect revoked) first, "
                 "before refunding. The API stops returning grant tokens once nothing is active.")
        return

    tokens = json.loads(sp.read_text())["tokens"]

    data = poll_order(session, timeout, res)
    if data is not None:
        res.check(data.get("status") == "revoked",
                  "order now reports 'revoked'",
                  f"order reports {data.get('status')!r}, expected 'revoked' — "
                  "the charge.refunded webhook may not have arrived")

    for entry in tokens:
        status, _, _ = get(f"{API_BASE}/download/{entry['token']}", follow=False)
        res.check(status == 410,
                  f"download for {entry['packId']} is 410 Gone",
                  f"download for {entry['packId']} -> HTTP {status}, expected 410. "
                  "A refunded buyer can still download — this is a revocation bug.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="Stripe checkout session id (cs_...).")
    parser.add_argument("--expect", choices=["ready", "revoked"], default="ready",
                        help="'ready' after paying (default); 'revoked' after refunding.")
    parser.add_argument("--timeout", type=int, default=90,
                        help="Seconds to wait for the webhook to settle (default 90).")
    args = parser.parse_args()

    print(f"API base: {API_BASE}")
    print(f"Session:  {args.session[:18]}…")

    res = Result()
    if args.expect == "ready":
        phase_ready(args.session, args.timeout, res)
    else:
        phase_revoked(args.session, args.timeout, res)

    print()
    if res.failures:
        print(f"{len(res.failures)} CHECK(S) FAILED:")
        for f in res.failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

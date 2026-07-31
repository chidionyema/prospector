#!/usr/bin/env python3
"""WS0.1 — drive the Stripe money-path end-to-end against a running Store.Api (TEST).

Deterministic runtime proof of the five launch gates in
specs/launch-hardening-execution.md §0.1. Each webhook event is constructed the way
Store.Api's StripeProvider expects, then signed with the *same* HMAC-SHA256 the Stripe
CLI/SDK use (the shared webhook secret) — so signature verification exercises the identical
code path a real Stripe-originated event would. This buys what a green build cannot: proof
that the real fulfilment -> DB -> presigned-download leg actually runs, including the
underpayment guard and refund revocation, against live R2.

Assumes Store.Api is already listening (see prove_money_path.sh, which boots it with a fresh
sqlite db + test keys). Writes a filled evidence report to store/launch/test-card-proof.md.

Required env: STRIPE_WEBHOOK_SECRET (same secret the API booted with), STORE_DB_PATH,
R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET.
Optional: API_BASE (default http://localhost:5291), STORE_INTERNAL_KEY, PROOF_FILE.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time

import boto3
import requests

API = os.environ.get("API_BASE", "http://localhost:5291")
SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
DB_PATH = os.environ["STORE_DB_PATH"]
INTERNAL_KEY = os.environ.get("STORE_INTERNAL_KEY", "dev-test-key-change-in-production")
PROOF_FILE = os.environ.get("PROOF_FILE", "store/launch/test-card-proof.md")

PACK_ID = "proof-money-path"
CONTENT_KEY = "proof/money-path-proof.txt"
PRICE = 4900
ARTIFACT = (
    b"PROSPECTOR MONEY-PATH PROOF ARTIFACT\n"
    b"If you can read this, the presigned R2 download leg works end to end.\n"
)

# Evidence captured per gate for the proof report.
EV: dict[str, str] = {}
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> bool:
    RESULTS.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {name}: {detail}", flush=True)
    return ok


def sign(body: str) -> str:
    ts = str(int(time.time()))
    payload = f"{ts}.{body}".encode()
    v1 = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def checkout_body(evt_id: str, pi: str, amount: int) -> str:
    obj = {
        "id": "cs_" + evt_id,
        "object": "checkout.session",
        "payment_intent": pi,
        "customer_details": {"email": "buyer@example.com", "address": {"country": "GB"}},
        "amount_total": amount,
        "currency": "gbp",
        "metadata": {"pack_id": PACK_ID},
    }
    evt = {
        "id": evt_id,
        "object": "event",
        "type": "checkout.session.completed",
        "request": None,
        "data": {"object": obj},
        "created": int(time.time()),
    }
    return json.dumps(evt, separators=(",", ":"))


def refund_body(evt_id: str, pi: str) -> str:
    obj = {
        "id": "ch_" + evt_id,
        "object": "charge",
        "payment_intent": pi,
        "amount_refunded": PRICE,
        "refunded": True,
    }
    evt = {
        "id": evt_id,
        "object": "event",
        "type": "charge.refunded",
        "request": None,
        "data": {"object": obj},
        "created": int(time.time()),
    }
    return json.dumps(evt, separators=(",", ":"))


def dispute_body(evt_id: str, pi: str) -> str:
    obj = {
        "id": "dp_" + evt_id,
        "object": "dispute",
        "charge": "ch_" + evt_id,
        "payment_intent": pi,
        "reason": "fraudulent",
        "status": "needs_response",
    }
    evt = {
        "id": evt_id,
        "object": "event",
        "type": "charge.dispute.created",
        "request": None,
        "data": {"object": obj},
        "created": int(time.time()),
    }
    return json.dumps(evt, separators=(",", ":"))


def post_webhook(body: str, signature: str | None = None) -> requests.Response:
    return requests.post(
        f"{API}/webhooks/stripe",
        data=body.encode(),
        headers={"Content-Type": "application/json",
                 "Stripe-Signature": signature if signature is not None else sign(body)},
        timeout=30,
    )


def purchase(evt_id: str, pi: str, amount: int = PRICE) -> str:
    """Drive a signed checkout.session.completed and return the granted entitlement token."""
    post_webhook(checkout_body(evt_id, pi, amount))
    rows = q("SELECT GrantToken FROM Entitlements WHERE PackId=? ORDER BY rowid DESC", (PACK_ID,))
    return rows[0]["GrantToken"] if rows else ""


def status_of(token: str) -> int | None:
    rows = q("SELECT Status FROM Entitlements WHERE GrantToken=?", (token,))
    return rows[0]["Status"] if rows else None


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _r2():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def setup() -> None:
    print("Setup: upload R2 artifact + seed listed pack", flush=True)
    _r2().put_object(Bucket=os.environ["R2_BUCKET"], Key=CONTENT_KEY, Body=ARTIFACT)

    r = requests.post(
        f"{API}/internal/catalog",
        headers={"X-Internal-Key": INTERNAL_KEY, "Content-Type": "application/json"},
        json={
            "id": PACK_ID,
            "title": "Money Path Proof Pack",
            "oneLine": "Internal end-to-end money-path proof fixture.",
            "dossierRef": "PROOF-WS0.1",
            "pricePence": PRICE,
            "paymentProvider": "stripe",
            "providerPriceId": "price_proof_fixture",
            "contentKey": CONTENT_KEY,
            "contentHash": hashlib.sha256(ARTIFACT).hexdigest(),
            "isListed": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    if not r.json().get("isListed"):
        raise SystemExit("seed failed: pack not listed (content key missing?)")


def gate1_2() -> str:
    print("Gate 1+2: signed checkout.session.completed -> Order Paid + Entitlement Active (idempotent)")
    body = checkout_body("evt_full_1", "pi_full_1", PRICE)
    r1 = post_webhook(body)
    record("gate1.signature-verified-200", r1.status_code == 200,
           f"POST /webhooks/stripe -> {r1.status_code} (not 503)")
    EV["g1_status"] = str(r1.status_code)

    r1b = post_webhook(body)  # exact replay, same event id
    orders = q("SELECT Id,Status,AmountPence FROM Orders WHERE ProviderTransactionId=?", ("pi_full_1",))
    ents = q("SELECT GrantToken,Status,ContentKey FROM Entitlements WHERE PackId=?", (PACK_ID,))
    record("gate2.order-paid", len(orders) == 1 and orders[0]["Status"] == 0,
           f"{len(orders)} Order row(s), Status={orders[0]['Status'] if orders else 'NONE'} (0=Paid)")
    record("gate2.entitlement-active", len(ents) == 1 and ents[0]["Status"] == 0,
           f"{len(ents)} Entitlement row(s), Status={ents[0]['Status'] if ents else 'NONE'} (0=Active)")
    record("gate2.idempotent-replay", r1b.status_code == 200 and len(orders) == 1 and len(ents) == 1,
           f"replay -> {r1b.status_code}, still {len(orders)} order / {len(ents)} entitlement")
    token = ents[0]["GrantToken"] if ents else ""
    EV["grant_token"] = token
    EV["order_row"] = str(dict(orders[0])) if orders else "NONE"
    EV["ent_row"] = str(dict(ents[0])) if ents else "NONE"
    return token


def gate3(token: str) -> None:
    print("Gate 3: presigned R2 download (X-Amz-Expires=300) + file fetch")
    rd = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30)
    loc = rd.headers.get("Location", "")
    is_redirect = rd.status_code in (301, 302, 303, 307, 308)
    host_ok = ".r2.cloudflarestorage.com" in loc
    ttl_ok = "X-Amz-Expires=300" in loc
    record("gate3.redirect-to-r2", is_redirect and host_ok,
           f"{rd.status_code} -> host {'*.r2.cloudflarestorage.com OK' if host_ok else loc[:60]}")
    record("gate3.ttl-300", ttl_ok, "X-Amz-Expires=300 present" if ttl_ok else "TTL marker missing")
    EV["download_url"] = loc.split("?")[0] + " ?<presigned, redacted>" if loc else "NONE"

    body_ok = False
    if is_redirect and loc:
        fetched = requests.get(loc, timeout=30)
        body_ok = fetched.status_code == 200 and fetched.content == ARTIFACT
    record("gate3.file-downloads", body_ok, "fetched object bytes match the uploaded artifact" if body_ok else "object did not download/match")

    ro = requests.get(f"{API}/orders/{token}", timeout=30)
    record("gate3.orders-page", ro.status_code == 200, f"GET /orders/{{token}} -> {ro.status_code}")


def gate4() -> None:
    print("Gate 4: underpayment guard refuses entitlement")
    before = q("SELECT COUNT(*) c FROM Entitlements WHERE PackId=? AND Status=0", (PACK_ID,))[0]["c"]
    body = checkout_body("evt_under_1", "pi_under_1", 100)  # 100p << 4900p
    r = post_webhook(body)
    after = q("SELECT COUNT(*) c FROM Entitlements WHERE PackId=? AND Status=0", (PACK_ID,))[0]["c"]
    record("gate4.webhook-200", r.status_code == 200, f"underpayment event -> {r.status_code}")
    record("gate4.no-grant", after == before,
           f"active entitlements {before} -> {after} (must be unchanged: underpayment grants nothing)")
    EV["underpay"] = f"100p paid vs {PRICE}p price; active entitlements stayed at {after}"


def gate5(token: str) -> None:
    print("Gate 5: charge.refunded -> entitlement Revoked + download 410")
    body = refund_body("evt_refund_1", "pi_full_1")
    r = post_webhook(body)
    record("gate5.webhook-200", r.status_code == 200, f"charge.refunded -> {r.status_code}")
    rows = q("SELECT Status FROM Entitlements WHERE GrantToken=?", (token,))
    revoked = bool(rows) and rows[0]["Status"] == 1
    record("gate5.entitlement-revoked", revoked,
           f"Status={rows[0]['Status'] if rows else 'NONE'} (1=Revoked)")
    rd = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30)
    record("gate5.download-410", rd.status_code == 410, f"GET /download/{{token}} -> {rd.status_code}")
    EV["refund"] = f"entitlement {token[:10]}... revoked; download now {rd.status_code}"


def gate6_invalid_signature() -> None:
    print("Gate 6: a forged/invalid signature is rejected and grants nothing")
    body = checkout_body("evt_forged_1", "pi_forged_1", PRICE)
    r = post_webhook(body, signature="t=1,v1=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    rejected = r.status_code != 200
    record("gate6.invalid-sig-rejected", rejected,
           f"forged Stripe-Signature -> {r.status_code} (must not be 200)")
    granted = q("SELECT COUNT(*) c FROM Orders WHERE ProviderTransactionId=?", ("pi_forged_1",))[0]["c"]
    record("gate6.no-order-from-forgery", granted == 0,
           f"orders created from forged event: {granted} (must be 0)")
    EV["forged"] = f"forged signature -> {r.status_code}, {granted} order(s) created"


def gate7_dispute() -> None:
    print("Gate 7: charge.dispute.created -> entitlement Revoked + download 410")
    token = purchase("evt_disp_1", "pi_disp_1")
    active = status_of(token) == 0
    record("gate7.setup-active", active and bool(token),
           f"fresh purchase entitlement Status={status_of(token)} (0=Active)")
    r = post_webhook(dispute_body("evt_disp_evt_1", "pi_disp_1"))
    record("gate7.webhook-200", r.status_code == 200, f"charge.dispute.created -> {r.status_code}")
    record("gate7.entitlement-revoked", status_of(token) == 1,
           f"Status={status_of(token)} (1=Revoked)")
    rd = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30)
    record("gate7.download-410", rd.status_code == 410, f"GET /download after dispute -> {rd.status_code}")
    EV["dispute"] = f"dispute revoked entitlement {token[:10]}...; download now {rd.status_code}"


def gate8_download_cap() -> None:
    cap = int(os.environ.get("DELIVERY_MAX_DOWNLOADS", "2"))
    print(f"Gate 8: download cap ({cap}) enforced -> 429 past the limit")
    token = purchase("evt_cap_1", "pi_cap_1")
    if not token:
        record("gate8.setup", False, "could not mint cap-test entitlement")
        return
    codes = []
    for _ in range(cap):
        codes.append(requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30).status_code)
    over = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30).status_code
    within_ok = all(c in (301, 302, 303, 307, 308) for c in codes)
    record("gate8.within-cap-redirects", within_ok,
           f"first {cap} downloads -> {codes} (all redirect)")
    record("gate8.over-cap-429", over == 429,
           f"download #{cap + 1} -> {over} (must be 429 Too Many Requests)")
    EV["cap"] = f"cap={cap}: first {cap} -> {codes}, next -> {over}"


def gate9_expiry() -> None:
    print("Gate 9: an expired entitlement (ExpiresAt in the past) -> download 410")
    token = purchase("evt_exp_1", "pi_exp_1")
    if not token:
        record("gate9.setup", False, "could not mint expiry-test entitlement")
        return
    before = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30).status_code
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("UPDATE Entitlements SET ExpiresAt=? WHERE GrantToken=?",
                    ("2000-01-01 00:00:00", token))
        con.commit()
    finally:
        con.close()
    after = requests.get(f"{API}/download/{token}", allow_redirects=False, timeout=30).status_code
    record("gate9.live-before-expiry", before in (301, 302, 303, 307, 308),
           f"before expiry -> {before} (downloadable)")
    record("gate9.410-after-expiry", after == 410,
           f"after ExpiresAt set to the past -> {after} (must be 410 Gone)")
    EV["expiry"] = f"download {before} (live) -> {after} (expired)"


def write_proof(all_pass: bool) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [f"- [{'x' if ok else ' '}] **{name}** — {detail}" for name, ok, detail in RESULTS]
    doc = f"""# Test-card money-path proof (WS0.1)

> Generated by `store_platform/scripts/prove_money_path.sh` against a running Store.Api on
> Stripe TEST keys + live R2. Events are signed with the shared webhook secret (the same
> HMAC-SHA256 Stripe uses), so signature verification runs the real code path.

**Date:** {stamp}
**Branch:** `launch-hardening-2026-06-18`
**API:** `{API}`
**Verdict:** {f"✅ ALL {len(RESULTS)} ASSERTIONS PASS" if all_pass else "❌ FAILURE — see gates below"}

## Gate results
{chr(10).join(lines)}

## Evidence
- **Gate 1** webhook status: `{EV.get('g1_status', '?')}` (signature-verified, not 503).
- **Gate 2** Order row: `{EV.get('order_row', '?')}`
- **Gate 2** Entitlement row: `{EV.get('ent_row', '?')}`
- **Gate 2** grant token: `{EV.get('grant_token', '?')}`
- **Gate 3** presigned download URL (query redacted): `{EV.get('download_url', '?')}`
- **Gate 4** underpayment: {EV.get('underpay', '?')}
- **Gate 5** refund: {EV.get('refund', '?')}
- **Gate 6** forged signature: {EV.get('forged', '?')}
- **Gate 7** dispute: {EV.get('dispute', '?')}
- **Gate 8** download cap: {EV.get('cap', '?')}
- **Gate 9** expiry: {EV.get('expiry', '?')}

## Method note
Gates 2–5 use deterministic signed-replay (controlled amount + payment_intent correlation)
because a real `checkout.session.completed` with controlled metadata cannot be produced
headlessly. The signature is computed with the live webhook secret, so verification is
identical to a Stripe-originated event. For a Stripe-*originated* signature spot-check, run
`stripe listen --api-key $STRIPE_TEST_SECRET_KEY --forward-to {API}/webhooks/stripe` and
`stripe trigger checkout.session.completed` alongside this harness.
"""
    os.makedirs(os.path.dirname(PROOF_FILE), exist_ok=True)
    with open(PROOF_FILE, "w") as f:
        f.write(doc)
    print(f"\nProof written to {PROOF_FILE}", flush=True)


def teardown() -> None:
    # The temp sqlite db is dropped by the wrapper; the R2 object is the only durable
    # artifact, so remove it best-effort to keep the bucket clean between runs.
    try:
        _r2().delete_object(Bucket=os.environ["R2_BUCKET"], Key=CONTENT_KEY)
    except Exception as exc:  # noqa: BLE001 - cleanup must never fail the proof
        print(f"  (teardown: could not delete R2 object: {exc})", flush=True)


def main() -> int:
    try:
        setup()
        token = gate1_2()
        if token:
            gate3(token)
        gate4()
        if token:
            gate5(token)
        gate6_invalid_signature()
        gate7_dispute()
        gate8_download_cap()
        gate9_expiry()
    finally:
        teardown()
    all_pass = all(ok for _, ok, _ in RESULTS)
    write_proof(all_pass)
    print(f"\n{'ALL GATES PASS' if all_pass else 'GATES FAILED'} "
          f"({sum(1 for _, ok, _ in RESULTS if ok)}/{len(RESULTS)})", flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

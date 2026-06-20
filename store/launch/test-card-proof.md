# Test-card money-path proof

> Fill this during a live Stripe TEST-mode run. Every cell is a gate.

**Date:** (fill)
**Branch:** `launch-hardening-2026-06-18`
**API:** `localhost:5291`
**Stripe CLI:** `stripe listen --forward-to localhost:5291/webhooks/stripe`

---

## Gate 1 — `checkout.session.completed` received and signature-verified

- [ ] Stripe CLI running and forwarding to localhost:5291
- [ ] Store API logs show `POST /webhooks/stripe` returning 200 (not 503)
- [ ] Paste the Stripe event ID: `evt_...`
- [ ] Paste the Store.Api log line showing the verified event:

```
(fill — should include the event type and amount)
```

---

## Gate 2 — Order + Entitlement created (one each, idempotent)

- [ ] `GET /orders/{token}` returns a page with the pack title (not 404)
- [ ] Store.db `Orders` table has exactly 1 row for this event (Paid)
- [ ] Store.db `Entitlements` table has exactly 1 row (Active)
- [ ] Replay: send the SAME webhook body again → 200, no duplicate Order/Entitlement
- [ ] Grant token: `(fill)`
- [ ] Pack ID: `(fill)`

Order row:
```
(fill — sqlite3 store.db "SELECT * FROM Orders WHERE ...")
```

Entitlement row:
```
(fill)
```

---

## Gate 3 — Download URL works (presigned, R2, 5-min TTL)

- [ ] `GET /download/{token}` redirects to an R2 URL
- [ ] URL host is `*.r2.cloudflarestorage.com`
- [ ] URL contains `X-Amz-Expires=300`
- [ ] The actual file downloads and opens (correct pack delivered)
- [ ] Paste the redirect URL (the presigned part expires in 5 min):

```
(fill)
```

- [ ] Screenshot of the `GET /orders/{token}` page showing the Download link

---

## Gate 4 — Underpayment guard fires

- [ ] Trigger `checkout.session.completed` with `amount_total` below the pack's `PricePence`
  (or a 100%-off coupon session)
- [ ] `/webhooks/stripe` returns 200
- [ ] Entitlement is NOT granted (no new Active row for this event)
- [ ] Screenshot/log showing the refused-underpayment log line:

```
(fill — should include "underpayment" or "amount mismatch")
```

---

## Gate 5 — Refund flips entitlement to Revoked

- [ ] Trigger `charge.refunded` for the original charge
- [ ] `/webhooks/stripe` returns 200
- [ ] Entitlement status flips from `Active` to `Revoked`
- [ ] `GET /download/{original_token}` returns 410 Gone
- [ ] `GET /orders/{original_token}` no longer shows a download link

---

## Sign-off

All five gates observed against a running TEST-mode instance.

**Signed:** (fill)
**Date/Time:** (fill)

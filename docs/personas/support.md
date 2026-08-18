# The platform for support

A customer says it did not arrive. Here is how you find out what happened and fix it.

## Know this before your first ticket

**There are no accounts.** A buyer has no login, no password, and no order history page. Their proof
of purchase is a token in a link. That shapes almost every ticket you will get:

- "I lost the link" is the most common failure, and it is not the customer's fault — there is nowhere
  for them to go and look it up.
- "It went to spam" has the same effect as "it never sent".
- A shared link works for whoever holds it. That is by design.

## The delivery path, so you know where it can break

1. Buyer pays on Stripe.
2. Stripe calls `/webhooks/{provider}` on the store API.
3. An entitlement is written. **Exactly one outbox row per entitlement** — that is the guard against
   double-sending and double-charging.
4. `/orders/{token}` shows the order; `/download/{token}` delivers the pack.

Break points, in the order they actually occur:

| Where | Symptom | What it means |
|---|---|---|
| Webhook never arrived | Paid, nothing delivered | Stripe has it; we do not. **Escalate immediately** — money taken, nothing given |
| Webhook arrived, entitlement written | Paid, link exists | Delivery or email problem. Recoverable |
| Buyer lost the link | "It never arrived" | The token exists. Re-send it |
| Link expired or token wrong | 404 or refused | Check the order by session id |

## The lookups

```
GET /api/orders/by-session/{sessionId}     # the Stripe session id from the receipt
GET /orders/{token}
GET /internal/catalog/{id}/price-history   # who moved a price and when
```

The ops console has `/money` and `/runs` screens for the same data. The console header badge tells
you whether you are looking at production — `prospector-engine · 80d34d · lhr` — or at somebody's
laptop, which will show `this laptop — NOT production` in red. **Check it before you tell a customer
anything.**

## Money questions

**Never change a price to resolve a ticket.** A price written straight to the catalogue drifts from
Stripe, and the buyer is then charged one number while the fulfilment fence checks another. The
console refuses `catalogue.set_price` for exactly this reason and names it. If a price genuinely must
change, it goes through `prospector/bridge.py`'s tools, which write both halves together.

**A duplicate charge is not always a duplicate.** Idempotency keys **expire** — they are not permanent
deduplication. A retry after expiry can produce a second charge that looks like a bug in the
customer's account and is a real, separate payment. Get the two session ids before concluding
anything.

**A checkout session that looks live may have expired.** A scan that ignored `status` once counted 168
expired sessions as live. Read the status field.

## What you can promise

- The pack is delivered immediately; there is no processing delay.
- Every claim in the pack cites a source the buyer can open. If a cited source has since gone offline,
  the passage was archived at verification time, so the claim can still be substantiated.
- Prices are in the buyer's currency by market. US buyers are billed in USD by decision.

## What to escalate rather than answer

- Paid, no entitlement. This is P0.
- Two charges for one purchase.
- Anything asking for deletion of their data — there is no self-service route and it is a manual
  database operation.
- Refund policy questions. **Verify what is actually published on the site** before quoting anything;
  do not improvise a policy.

## What is not built

No helpdesk integration, no ticket system, no customer-facing order lookup, no self-service re-send,
and no automated email beyond delivery. Every one of the lookups above is a request against an API or
a console screen.

**The highest-value support feature that does not exist is a self-service "re-send my link" page**,
because "I lost the link" is structurally the most likely ticket in an accountless product.

## What to read next

- [buyer.md](buyer.md) — the experience you are supporting.
- [ops.md](ops.md) — the console screens.
- [sre-on-call.md](sre-on-call.md) — when it is not one customer but all of them.

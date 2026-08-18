# Support

**What this is.** The complete map of what happens to a buyer after they pay, every place it can
break, and every lookup you can run to find out which one happened.

**Read this if** a customer has written in and you need to know what they bought, whether it was
delivered, and what you are allowed to do about it.

**The one-sentence answer.** A purchase creates an order and an entitlement keyed by an opaque
token; the token, not an account, is the customer's proof of purchase; and everything you can
check is a `python -m prospector.ops.console_api read ...` command or a console page.

---

## 1. Identity: what a customer actually has

### 1.1 The purchase is accountless. Accounts exist separately.

Both halves matter, and the second half is easy to miss.

**Accounts exist.** `store_platform/src/Store.Catalog/Domain/Identity/StoreUser.cs` extends
`IdentityUser<Guid>`. `Store.Api/Auth/AuthEndpoints.cs` maps a full set of routes:

| Route | Line |
|---|---|
| `POST /register` | `:142` |
| `POST /login` | `:148` |
| `POST /forgot-password` | `:154` |
| `POST /reset-password` | `:160` |
| `POST /verify-email` | `:169` |
| `POST /resend-verification` | `:176` |
| `POST /refresh` | `:182` |
| `POST /logout` | `:188` |
| `GET /me` | `:194` |
| `PUT /me` | `:202` |
| `POST /change-password` | `:218` |
| `GET /sessions` | `:224` |
| `DELETE /sessions/{familyId:guid}` | `:231` |

`Auth/AccountOrdersEndpoints.cs:25-30` maps `GET /v1/auth/me/orders`, and it requires
`EmailConfirmed`. The web side is `components/account/AuthPanel.tsx`.

**But the purchase does not use any of that.** From
`store_platform/src/Store.Web/src/components/.../BuyerIdentityNote.tsx`:

> An order carries an email address and no user id (`Order.BuyerEmail`; there is no UserId
> column), so the address recorded at the payment provider is the only link between a purchase
> and an account.

and:

> Guest checkout is a supported path, not a degraded one, neither checkout route requires
> authorization (`CheckoutEndpoints.cs:24,40`).

**What this means at the support desk:**

- A customer can have bought something and have no account. That is normal, not an error.
- A customer can have an account and buy again as a guest, with a different email. The two will
  not be linked.
- "Reset my password" is meaningless for someone who never registered. Ask first.
- The link between a purchase and an account is the **email string** recorded at Stripe. Nothing
  else.

### 1.2 What actually identifies an order

Three identifiers, in the order you are most likely to be given one:

| Identifier | Where the customer got it | Where it lives |
|---|---|---|
| **GrantToken** | The link in their email, or the success page | `Entitlement.GrantToken`, unique index at `StoreDbContext.cs:120` |
| **Checkout session id** | The `?session_id=` on the success page URL | Stripe; resolved by `GET /api/orders/by-session/{sessionId}` |
| **Email address** | They typed it at checkout | `Order.BuyerEmail` |

The GrantToken is described at `Store.Api/Endpoints/DeliveryEndpoints.cs:12-13`:

> Both are keyed on the opaque, non-enumerable grant token. A missing/unknown token returns a
> generic 404 (no oracle that distinguishes "never existed" from "revoked").

**That 404 design is deliberate and it will bite you.** If a customer says "my link says not
found", the API is refusing to tell *you* the difference too. You must look it up server-side.

### 1.3 The entitlement record

`store_platform/src/Store.Catalog/Domain/Entitlement.cs` fields:

`Id`, `OrderId`, `Order`, `PackId`, `BuyerEmail`, `GrantToken`, `Status`, `ContentKey`,
`ContentVersion`, `ExpiresAt`, `CreatedAt`, `DownloadCount`, `LastDownloadedAt`.

`ContentKey` is the version of the pack **they paid for**, snapshotted at purchase. See §5.4.

---

## 2. The delivery path, hop by hop

### 2.1 Path A — the buyer stays in the browser (the common case)

1. Buyer clicks buy. `components/checkout/PackBuyButton.tsx:141` renders the default label
   `'Buy this pack'`; `:176-193` is the render. Checkout is Stripe embedded
   (`components/checkout/EmbeddedCheckoutPanel.tsx`).
2. Buyer pays. Stripe redirects to `/orders/success?session_id=...`.
3. `pages/orders/success.tsx` (544 lines) begins polling. Its own comment at `:10-12`:
   > The buyer lands here the instant the payment provider redirects, which is normally BEFORE
   > the fulfilment webhook has been processed. So "not ready yet" is the expected first answer
   > and we poll rather than treat it as failure.
4. `POLL_INTERVAL_MS = 2000` (`:13`), `MAX_POLL_ATTEMPTS = 12` (`:18`). **~24 seconds total.**
   The comment at `:14-17` records why it was cut from 20 attempts: *"tuned for a webhook delay
   we have never actually observed, Stripe delivers effectively instantly after payment."*
5. Each poll hits `GET /api/orders/by-session/{sessionId}` →
   `DeliveryEndpoints.GetOrderBySession` (`:49-95`).
6. Meanwhile Stripe fires `checkout.session.completed` to `POST /webhooks/stripe`
   (`WebhookEndpoints.cs:13-15`, handled at `Payments/StripeProvider.cs:67`).
7. `Services/FulfilmentService.cs` creates the order and the entitlement, and enqueues one
   `PendingDelivery` row.
8. The poll now returns ready. The page shows a download button (`success.tsx:207-213`) pointing
   at `${API_BASE_URL}${firstItem.downloadPath}`.

**Six phases the page can end in** (`success.tsx:20`):

```
type Phase = 'resolving' | 'ready' | 'no-session' | 'timed-out' | 'unfulfilled' | 'revoked';
```

Copy for each is at `:423-429`, inside `ResolutionFallback` (`:399+`). The revoked line is
*"This order has been refunded, so its download is no longer active."*

`timed-out` and `unfulfilled` are the two that generate support tickets. `unfulfilled` and
`revoked` end the poll immediately rather than running out the 24 seconds (`:14-17`).

**The permanent link.** `success.tsx:215-230` shows the buyer their durable URL, with the copy
*"It is your permanent access link, it does not expire."* That link is `/orders/<GrantToken>`.
That claim is true of the **link**; the presigned download URL behind it lasts 5 minutes and is
re-minted on each click.

### 2.2 Path B — the buyer comes back later with their link

1. Buyer opens `/orders/<token>` — `pages/orders/[token].tsx`, 106 lines.
2. It calls `fetchOrder(token)` → `GET /api/orders/{token}` →
   `DeliveryEndpoints.GetOrderJson` (`:156-177`), which returns
   `{packId, packTitle, status, downloadPath}` or a 404 at `:161`.
3. The page maps `'not_found'` to the string **"Order not found."** That is all the customer sees.
4. Buyer clicks download → `GET /download/{token}` → `DeliveryEndpoints.Download` (`:204-266`).

### 2.3 `Download` — every branch, with its status code

This is the single most important function at the support desk. `DeliveryEndpoints.cs:204-266`,
in execution order:

| # | Condition | Line | Response | What the customer sees |
|---|---|---|---|---|
| 1 | No entitlement for that token | `:211-213` | **404** | Nothing works. Bad or fabricated link. |
| 2 | `Status != Active` | `:219-221` | **410 Gone** | Revoked — refunded or disputed. |
| 3 | `ExpiresAt <= UtcNow` | `:224-226` | **410 Gone** | Expired entitlement. |
| 4 | `DownloadCount >= maxDownloads` | `:231-236` | **429** | Cap hit. |
| 5 | No `ContentKey`, or storage not configured | `:248-255` | **503** | Paid, valid, undeliverable. **Our fault.** |
| 6 | Success | `:258-265` | **302** to presigned URL | The file downloads. |

**Branch 2's comment is worth reading**, `:216-218`:

> Authorize positively: only an Active entitlement may download. Checking "not Revoked" would
> silently honour any future non-Active status (e.g. Suspended, Pending) as deliverable.

**Branch 4, the download cap**, `:21-25`:

> P1-7 — per-entitlement download cap. A magic link that leaks (forwarded email, shared
> screenshot) must not become an unbounded mint of presigned URLs. The cap is deliberately
> generous so legitimate re-downloads across devices never hit it; beyond it the operator can
> re-issue. Overridable via `Delivery:MaxDownloadsPerEntitlement`.

`private const int DefaultMaxDownloads = 50;` (`:24`). Log line on hit:
`"Download cap ({Cap}) reached for entitlement {PackId}; refusing further mints."`

**Branch 5 is the one to escalate**, `:246-247`:

> Paid, valid entitlement, but content is missing or storage is down — this is a deliverability
> failure the operator must fix, never a buyer's fault.

Log line: `"Undeliverable download for entitlement {PackId}: contentKey={ContentKey},
storageConfigured={Configured}"`.

**The presigned URL TTL**, `:17-19`:

```csharp
// Presigned URLs are short-lived: long enough to fetch, short enough that a leaked
// link decays fast. The entitlement, not the URL, is the durable right.
private static readonly TimeSpan DownloadUrlTtl = TimeSpan.FromMinutes(5);
```

**Five minutes.** If a customer says "the download link expired", they probably copied the
redirect target rather than clicking the button again. Tell them to reopen `/orders/<token>`.

### 2.4 The email path

Email is **not** the primary delivery path any more. `DeliveryEndpoints.cs:37-41`:

> This exists because email was the ONLY delivery path: the success page told buyers to check
> their inbox, and an unconfigured mail sender failed silently, so a buyer could pay and have no
> route at all to what they bought. Email is now a convenience.

One `PendingDelivery` row per entitlement. `StoreDbContext.cs:61`:

```csharp
entity.HasIndex(e => e.EntitlementId).IsUnique();
```

with the comment: *"UNIQUE, and load-bearing: it is what makes enqueueing idempotent. A duplicate
webhook that somehow reached fulfilment twice would otherwise queue the same link twice, and the
database is the only thing that can see a concurrent insert."*

`PendingDelivery.SentAt` (`:47`) is *"The only definition of 'delivered'"*. It is indexed at
`StoreDbContext.cs:64`.

**Mail is configured non-fatally.** `Store.Api/Payments/MoneyRailConfigGate.cs:232-262`,
`ReportDeliveryConfig`, checks Mailjet `ApiKey`, `ApiSecret` and `FromEmail`. If any is missing it
**logs CRITICAL and the API still starts**. Every other guard in `StartAsync` (`:34-64`) is
fail-closed. Mail is the one that is not.

**Finding, and it is a live documentation bug.** `BuyerIdentityNote.tsx` says *"No fulfilment mail
is sent while the MAILJET_* secrets are unset (see orders/success.tsx:146-149)"*. That
cross-reference is dead:

```
$ rg -i "mailjet" store_platform/src/Store.Web/src/pages/orders/success.tsx
(no hits)
```

The only email references in `success.tsx` are `mailto:` links to `LEGAL.supportEmail` (`:385-386`,
`:491`, `:500`, `:526`). The real check is `MoneyRailConfigGate.ReportDeliveryConfig:232-262`. Fix
the comment; do not trust it.

---

## 3. Every lookup you can run

### 3.1 The console gateway

All reads go through one CLI (`prospector/ops/console_api.py:2427-2470`):

```
python -m prospector.ops.console_api {read|act|views|actions|run-tool} <name> \
    [--arg k=v] [--payload JSON] [--preview] [--confirm TOKEN]
```

`views` lists every read. `actions` lists every write plus the ones refused by name.

**24 read views**, registry at `console_api.py:1065-1090`:

`method`, `shelf`, `status`, `queue`, `providers`, `routing`, `spend`, `money`, `data`, `metrics`,
`runs`, `run`, `candidate`, `config`, `intents`, `tools`, `undo`, `catalogue`, `pack`, `orders`,
`order`, `sales`, `deliveries`, `disputes`. Plus `READS["job"]`, registered later at `:1933`.

The last five are the support surface.

### 3.2 The support lookups, in the order you will need them

**Find an order.**
```
python -m prospector.ops.console_api read orders --arg email=someone@example.com
```
`_read_orders` at `console_api.py:382`. Filters are declared in `prospector/ops/shop.py:36-48`
(`ORDER_FILTERS`).

**Read one order in full.**
```
python -m prospector.ops.console_api read order --arg order_id=<id>
```
`_read_order` at `:392`.

**Check delivery state.**
```
python -m prospector.ops.console_api read deliveries --arg state=abandoned
```
`_read_deliveries` at `:408`. Valid states, `shop.py:53`:

```python
DELIVERY_STATES = ("unsent", "pending", "failed", "abandoned", "sent", "all")
```

**`abandoned` is the state that means a human must act.** `shop.py` documents it: the drain
stopped at `Delivery:MaxAttempts`, leaving *"a buyer who paid, holds an entitlement, and will
never be sent their link by any automatic process."*

**Check refunds and disputes.**
```
python -m prospector.ops.console_api read disputes --arg days=90
```
`_read_disputes` at `:419`.

**Revenue.**
```
python -m prospector.ops.console_api read sales
```
`_read_sales` at `:402`.

**Three rules `shop.py` enforces on all of these**, from its module docstring: currencies are
never summed; an unreachable API is a *state*, not a datum; nothing recomputes what the API already
computed. So if a view shows "API unreachable", that is the answer, not a failure to answer.

### 3.3 The one write a support person makes: resend a delivery

```
python -m prospector.ops.console_api act deliveries.resend --preview --payload '{"id": 123}'
python -m prospector.ops.console_api act deliveries.resend --confirm <token> --payload '{"id": 123}'
```

`deliveries.resend` is one of thirteen actions in
`store_platform/src/Ops.Console/src/pages/api/ops/act/[action].ts:21-34`:

`pause.arm`, `pause.disarm`, `routing.set_moat_primary`, `config.set`, `config.restore`,
`catalogue.set_listing`, `shelf.repair_copy`, `shelf.publish_pending`, `shelf.regate`,
`daemon.restart`, `tools.run`, `tools.undo`, `deliveries.resend`.

**Every action is two-step.** Preview describes the change and issues a token. Nothing is written
until you confirm with that token. The token is validated in Python, in `console_api.dispatch`, not
in the TypeScript layer, so the fence cannot be bypassed by calling the API directly.

**What resend actually does** (`console_api.py`, roughly `:805-870`):

- It sends nothing itself. `DeliveryDrain` remains the only sender.
- It calls `POST /internal/ops/deliveries/{id}/resend`.
- One outbox row per entitlement, so a resend **cannot** create a second row. See §2.4.
- Clearing `SentAt` destroys the receipt of the first send, so the API returns `previousSentAt`
  and the action writes it into the intent receipt. The evidence survives.
- It returns **409** if the entitlement is revoked. You cannot resend a refunded order.
- The preview window is the most recent 200 rows, and it says so. If the delivery you want is
  older, you will not see it in the preview.

---

## 4. Money questions

### 4.1 Refunds

The path: Stripe fires `charge.refunded` (`StripeProvider.cs:105`) or `charge.dispute.created`
(`:115`) at `POST /webhooks/{provider}` (`WebhookEndpoints.cs:13-15`). `TryParseReversal`
(`StripeProvider.cs:100-126`) turns it into a `PaymentReversal` record:

```
(Provider, ReversalEventId, OriginalTransactionId, Kind)   // Kind is "refund" | "dispute"
```

`Services/FulfilmentService.cs:172-174` revokes **every** Active entitlement attached to the
original payment. `:194` sets `OrderStatus.Disputed` or `OrderStatus.Refunded`.

**Two idempotency properties**, from `WebhookEndpoints.cs:41` and `:124-127`: the handler dedupes
on the reversal event's own id, and revocation only ever flips entitlements that are currently
Active. Replaying the same webhook does nothing the second time.

**After a refund**, the customer's download returns **410 Gone** (branch 2 in §2.3) and the
success page shows *"This order has been refunded, so its download is no longer active."*

**The published promise.** `components/marketing/TrustGuaranteesRow.tsx:84-91` shows three
guarantees: "14-day money back", "Every claim sourced", "One-time payment, {price}". The 14 days
is the number the customer will quote at you.

### 4.2 Duplicate charges

Look for two `Order` rows with different `ProviderTransactionId`. The unique index at
`StoreDbContext.cs:106`:

```csharp
entity.HasIndex(e => new { e.PaymentProvider, e.ProviderTransactionId }).IsUnique();
```

means one Stripe transaction can only ever produce one order. **So a genuine duplicate charge is
two separate Stripe transactions** — the customer clicked buy twice, or an embedded checkout was
re-submitted. It is not a webhook replay; the database structurally prevents that.

Refund the second one at Stripe. The webhook revokes its entitlement automatically.

### 4.3 Idempotency keys expire — they are not deduplication

`Store.Api/Infrastructure/IdempotencyFilter.cs`:

| Property | Value | Line |
|---|---|---|
| Header | `Idempotency-Key` | `:13` |
| Max length | 200 chars | `:14` |
| TTL | `TimeSpan.FromHours(96)` | `:15` |
| Storage key | `Hash($"{scope}\|{method}\|{path}\|{clientKey}")` | `:38` |
| Journal write | | `:62` |
| Replay (returns the cached response) | | `:82`, `:145-149` |
| In progress | **409** | `:84-86` |
| Same key, different body | **422** | `:76-79` |

**Ninety-six hours.** After that the key is forgotten and the same request will execute again. An
idempotency key is a short-lived replay guard, not a permanent deduplication record. If someone
retries a four-day-old request with the same key, it runs.

The **422** case is the useful one at support: the client reused a key with a different payload.
That is a client bug, and the API refuses rather than guessing.

### 4.4 Expired checkout sessions

A Stripe checkout session that is never paid expires. `GetOrderBySession` (`:49-95`) will keep
answering `pending` for it, because the session is unguessable and the provider never confirms it
as paid. The buyer's page runs out its 12 polls and shows `timed-out`.

**`timed-out` does not mean the money is lost.** It means no entitlement existed within 24
seconds. Check Stripe for the session's status before telling the customer anything. A previously
recorded incident in this estate was a checkout-session scan that ignored `status` entirely and
reported 168 sessions as live when they had expired.

### 4.5 What the money rail refuses to start without

`MoneyRailConfigGate.StartAsync:34-64` runs nine guards. Eight are fail-closed:

1. internal API key
2. entitlements API key
3. required provider keys (`:39-54`)
4. `GuardWebhookSecretPlaceholder` (`:56`)
5. `GuardStripeApiKeyShape` (`:57`, impl `:76-117`)
6. `GuardStorefrontUrl` (`:58`, `:124-139`)
7. `GuardEmailWebBaseUrl` (`:59`, `:153-173`)
8. `GuardR2Config` (`:60`, `:194-222`) — all-or-nothing
9. `ReportDeliveryConfig` (`:61`, `:232-262`) — **non-fatal**, logs CRITICAL

If the API is up, guards 1-8 passed. Guard 9 may not have. That is exactly the "paid, no email"
scenario.

`MoneyRailStatus.Record(provider, mode, environment, decidedAtUtc)` (`MoneyRailStatus.cs:33-39`)
is what the ops console reads to show which rail is live and in which mode.

---

## 5. Failure symptom table

| Symptom | First thing to check | Likely cause | Fix |
|---|---|---|---|
| "My link says Order not found" | `read order --arg order_id=` / `read orders --arg email=` | Bad token, or the entitlement never existed | If no order exists, check Stripe — payment may never have completed |
| "Link worked yesterday, now says Gone" (410) | `read disputes --arg days=30` | Refund or dispute revoked it (`FulfilmentService.cs:172-174`) | Expected. Explain the refund. |
| "Download says too many requests" (429) | `Entitlement.DownloadCount` vs 50 | Cap hit (`DeliveryEndpoints.cs:231-236`) | Re-issue the entitlement. Ask whether the link was shared. |
| "Download fails with a server error" (503) | API logs for `Undeliverable download` | Missing `ContentKey` or R2 down | **Escalate.** Our fault, buyer is owed. |
| "I paid and got nothing" | `read deliveries --arg state=abandoned` | Drain gave up at `Delivery:MaxAttempts` | `act deliveries.resend` |
| "I paid and got no email" | API startup logs for the CRITICAL from `ReportDeliveryConfig` | Mailjet secrets unset — non-fatal, so the API started anyway | Give them `/orders/<token>` directly. Escalate the config. |
| Success page stuck, then timed out | Stripe session status | Session expired, or webhook never arrived | Check Stripe first. Do not assume a bug. |
| "Charged twice" | Two `ProviderTransactionId` values | Two real Stripe transactions | Refund one at Stripe. Webhook revokes automatically. |
| Storefront returns 503 to many visitors | `RateLimiting__PermitPerMinute` | The API rate-limits its own storefront. See §7.2. | Not a per-customer issue. Escalate. |
| "The pack I downloaded is different from the one on the site" | `Entitlement.ContentKey` | Correct behaviour — they own the version they paid for | Explain. See §5.4. |

### 5.4 Why a buyer's pack can differ from the live one

`DeliveryEndpoints.cs:242-245`:

> Serve the key snapshotted on the entitlement (what the buyer paid for). Fall back to the pack's
> current key only for legacy entitlements that predate snapshotting.

Bundle keys are content-addressed: `prospector/bridge.py:1446` mints
`packs/{candidate_id}/{content_hash}.zip`. Re-render a pack and its hash, and therefore its key,
changes. **Existing buyers keep the version they bought. This is deliberate.** It is not a bug and
it is not something to "fix" for a customer.

---

## 6. Invariants — what must stay true

| Invariant | Where enforced | What breaks if it goes |
|---|---|---|
| One `PendingDelivery` per entitlement | `StoreDbContext.cs:61`, unique | Duplicate emails; a resend could double-send |
| GrantToken is unique | `StoreDbContext.cs:120`, unique | Two buyers could collide on one download |
| One Stripe transaction, one order | `StoreDbContext.cs:106`, unique | Webhook replay creates duplicate orders |
| 404 never distinguishes revoked from never-existed | `DeliveryEndpoints.cs:12-13` | Token enumeration becomes possible |
| Only `Active` may download | `:216-221` | A future `Suspended` status silently becomes deliverable |
| `SentAt` is the only definition of delivered | `PendingDelivery.cs:47` | "Did we send it?" stops having an answer |
| Resend cannot destroy the first receipt | `console_api` returns `previousSentAt` | You lose the audit trail of the original send |
| Resend refuses a revoked entitlement | 409 in `deliveries.resend` | You re-deliver a refunded product |
| Every write is preview-then-confirm | `[action].ts` + `console_api.dispatch` | A mistyped payload takes effect immediately |
| Price is never written from the console | refused by name | The Stripe Price and the catalogue row drift; buyer is charged, fulfilment fence fails |

---

## 7. Two things support will meet that are not the customer's fault

### 7.1 The five-minute presigned URL

`DownloadUrlTtl = TimeSpan.FromMinutes(5)` (`:19`). The customer's `/orders/<token>` link is
permanent. The URL it redirects to is not. A customer who bookmarks the redirect target, or pastes
it into a download manager an hour later, gets a failure that looks like our bug and is not.

Script: *"That link is a temporary one-time address. Open your order page again and click download —
it will make a fresh one."*

### 7.2 The API rate-limits its own storefront

`Store.Api/Infrastructure/RateLimitPolicy.cs`. Three partitions: `/webhooks` has no limiter,
`/catalog/waitlist` is tight (`DefaultWaitlistPermitPerMinute = 5`), everything else is per-IP at
`DefaultPermitPerMinute = 120`.

The docstring names the blind spot:

> Known blind spot — the storefront is not "an IP" (measured 2026-08-06) … ALL SSR traffic for the
> whole site shares ONE partition. A pack page costs two calls (`fetchPackDetails` +
> `fetchCatalog`, `Store.Web pages/pack/[id].tsx:1083-1086`), so at the 120 default the storefront
> begins throttling itself at roughly 60 page views a minute — and the visitor is served a 503
> error page, because `pages/pack/[id].tsx:1112-1118` maps any non-404/410 to
> `res.statusCode = 503`.

Mitigated by the Fly secret `RateLimiting__PermitPerMinute=600`, which moves the ceiling to about
300 page views a minute. **The structural fix is not done.** If traffic spikes, visitors see 503
pages and it is not per-customer. Escalate immediately; do not troubleshoot individual reports.

---

## 8. What to escalate, and when

**Escalate immediately, do not attempt a fix:**

- Any **503** from `/download/` — a paid customer cannot be served. Log line to quote:
  `"Undeliverable download for entitlement {PackId}: contentKey={ContentKey},
  storageConfigured={Configured}"`.
- Multiple visitors reporting a 503 error page on the site — §7.2.
- Any suspicion the money rail is in the wrong mode — check `MoneyRailStatus` first, quote it.
- A CRITICAL in the API startup log from `ReportDeliveryConfig` — mail is down estate-wide.
- Any request to change a price. Refused by design; it is a `bridge.py` change and a deploy.

**Handle yourself:**

- Resending a delivery (`act deliveries.resend`, preview then confirm).
- Explaining a 410 after a refund.
- Explaining the 5-minute URL.
- Explaining a snapshotted `ContentKey`.
- Looking up any order, sale, delivery or dispute through the 24 read views.

**Never do:**

- Never clear `SentAt` by hand. The resend action preserves it as `previousSentAt`; a manual edit
  destroys the receipt.
- Never issue a GrantToken by hand. The unique index will accept it and nothing else will know it
  exists.
- Never confirm an action with a token you did not just generate from your own preview.

---

## 9. The numbers, measured this session

| Measurement | Value | Source |
|---|---|---|
| `DeliveryEndpoints.cs` | 272 lines | `wc -l` |
| `orders/success.tsx` | 544 lines | `wc -l` |
| `orders/[token].tsx` | 106 lines | `wc -l` |
| Poll window on the success page | 12 × 2000 ms ≈ 24 s | `:13`, `:18` |
| Presigned URL TTL | 5 minutes | `:19` |
| Download cap per entitlement | 50 | `:24` |
| Idempotency key TTL | 96 hours | `IdempotencyFilter.cs:15` |
| Read views in the console | 24 (+ `job`) | `console_api.py:1065-1090`, `:1933` |
| Write actions in the console | 13 | `[action].ts:21-34` |
| Delivery states | 6 | `shop.py:53` |
| Live catalogue rows | 74 | `curl -s https://api.mumchimp.com/catalog` |
| Default rate limit | 120/min per IP (600 in prod) | `RateLimitPolicy.cs` |

---

## 10. Open gaps and debt

| Gap | Evidence | Cost to close |
|---|---|---|
| Mail config is the only non-fatal guard | `MoneyRailConfigGate.cs:61`, `:232-262` | Making it fail-closed is a one-line change, but it would refuse to start the API in any environment without mail secrets. That is the reason it is not. |
| Storefront self-throttling is unfixed | `RateLimitPolicy.cs` docstring | Needs an SSR-aware partition key, not an IP. Currently papered over with a secret. |
| `BuyerIdentityNote.tsx` points at a dead line | `rg -i mailjet .../success.tsx` → no hits | One comment edit. Do it when next in the file. |
| Resend preview only shows 200 rows | `console_api.py` `deliveries.resend` | Older deliveries need a direct `read deliveries` first. Pagination is not built. |
| No support-facing view of a single entitlement | `READS` has `order`, not `entitlement` | The download branch you need to diagnose (`DownloadCount`, `ExpiresAt`, `ContentKey`) is not exposed as a read view. |

**HYPOTHESIS: some `abandoned` deliveries exist right now.** The check that would confirm or kill
it: `python -m prospector.ops.console_api read deliveries --arg state=abandoned`. I did not run it,
because it queries the live production API and this session was read-only on the repository, not on
production state.

---

## 11. Where to look next

- [buyer.md](buyer.md) — what the customer was told they were buying. Read it before you reply to
  one.
- [content-management.md](content-management.md) — why a pack's words are what they are, and why
  74 finished packs are not on sale.
- [growth-marketing.md](growth-marketing.md) — the catalogue and discovery surfaces.
- [../ESTATE_MAP.md](../ESTATE_MAP.md) — where each system in this document lives.

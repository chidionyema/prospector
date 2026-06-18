# Handover — Bridging the Gap to Launch (build-ready spec, edge-cases included)

**Date:** 2026-06-16
**Companion to:** `GO_LIVE_SPEC.md` (the assessment). This document is the **implementation handover**: what to build, the exact contracts to build against, and every edge case to handle.
**Audience:** the engineer/agent who will close the P0 money-and-delivery loop.
**Founder fence:** the **engine and any model-key-holding code stay local & Claude-reviewed**. Everything in this handover is the **hosted commerce/delivery layer** — it holds no LLM keys and cannot manufacture a PASS. Keep it that way.

---

## 0. The one-sentence gap

Today: *buyer pays → `SalesAudit` row written → **nothing**.* No entitlement, no content lookup, no delivery.
This handover builds the missing arc: **pay → entitle → deliver → re-download**, with the security, atomicity, and reconciliation an Money-rail needs.

---

## 1. Decisions to lock before coding (Phase 0)

These are cheap to decide and expensive to retrofit. Recommended answers given; founder signs off.

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | Local-only vs hosted | **Engine local & supervised; commerce/delivery hosted** (the split in `GO_LIVE_SPEC.md §2`) | Preserves founder fence + liability backstop; only the storefront needs uptime. |
| D2 | Payment provider | **Paddle only; remove the half-wired Stripe** (`stripe.ts`, `FundingPanel`) | Paddle is Merchant-of-Record → it handles VAT/sales-tax/invoicing. Two providers = double the edge cases. |
| D3 | Pack model for v1 | **Ship ONE pack (the £30 unit) only.** Shelve the 3-tier Scout/Operator/Founder model behind a flag. | Two live models exist and disagree (see §2). One product → one delivery path → launchable. Re-introduce tiers post-launch. |
| D4 | Where delivery + entitlement live | **In the .NET Store** (it already owns the webhook, sales audit, catalog) | Single hosted commerce brain. FastAPI (`api.py`) becomes dev/local read-only or is retired for v1. |
| D5 | Content storage | **Object storage (S3/Cloudflare R2) with private bucket + presigned GET** | The engine machine is local/ephemeral; the hosted Store must serve content without reaching back into the engine box. |
| D6 | Buyer identity | **Guest checkout + email magic-link re-download** (no password accounts for v1) | Paddle collects the email; magic links avoid building full auth now. |
| D7 | Schema evolution | **Adopt EF Core migrations now**, before adding tables | `EnsureCreated()` will NOT add new tables to an existing `store.db`. Migrations are required or prod data breaks. |

---

## 2. The monetization-model conflict (must resolve — D3)

Two incompatible shapes exist in the codebase **right now**:

- **Commerce path (.NET + Next.js):** one `Pack`, `PricePence = 3000` (£30), `bridge.py` POSTs `pricePence: 3000` hardcoded.
- **Content path (FastAPI + `store/listings/*.json` via `_write_listing`):** three tiers —
  `scout.price_cents=6000`, `operator.price_cents=18000`, `founder_investor.price_cents=60000` — and `packs.py::compose_packs` (orphaned) computes dynamic prices.

`api.py GET /v1/listings` returns the **scout** tier as the teaser; the Next.js store shows the **£30** Pack. **A buyer would see different prices/products depending on which surface they hit.**

**v1 resolution (D3):** the £30 single pack is the product of record. Either (a) make `_write_listing` emit a single pack matching the £30 unit, or (b) stop publishing the tiered `listings` JSON for v1 and have any content API read pack metadata from the Store. Pick one and delete/flag the other so there is exactly one source of truth for "what is for sale and at what price."

---

## 3. Current contracts (verbatim — build against these)

### 3.1 .NET Store (`store_platform/src/Store.Api`, `Store.Catalog`)
- **Endpoints** (`Program.cs`): `GET /catalog`, `GET /catalog/{id}`, `POST /internal/catalog` (upsert), `POST /webhooks/paddle`.
- **`PublishRequest`** (`Contracts/PublishRequest.cs`): `record PublishRequest(string Id, string Title, string OneLine, string DossierRef, string? PaddleProductId=null, string? PaddlePriceId=null, bool IsListed=false, long? PricePence=null)`.
- **`Pack`** (`Store.Catalog/Domain/Pack.cs`): `Id`(PK,string), `Title`(≤200), `OneLine`(≤500), `PricePence`(long), `PaddleProductId`(string?), `PaddlePriceId`(string?), `IsListed`(bool, indexed), `DossierRef`(string), `CreatedAt`(DateTime=UtcNow).
- **`SalesAudit`** (`Store.Catalog/Domain/SalesAudit.cs`): `Id`(PK,long auto), `PaddleTransactionId`(string, **unique**), `PaddleProductId`(string), `AmountPence`(long), `Currency`(string), `Country`(string), `OccurredAt`(DateTime).
- **`StoreDbContext`**: `DbSet<Pack> Packs`, `DbSet<SalesAudit> SalesAudits`; schema via `OnModelCreating` + **`EnsureCreatedAsync()`** at startup (NO migrations dir).
- **Webhook** (`Endpoints/WebhookEndpoints.cs`): handles **only** `transaction.completed`; verifies `Paddle-Signature` (`ts=…;h1=…`) via HMACSHA256 over `"{ts}:{rawBody}"`, ±5 min window, fixed-time compare; **fails closed** if `Paddle:WebhookSecret` unset (503). Idempotent via `AnyAsync(PaddleTransactionId)` → `ALREADY_PROCESSED`. Writes `SalesAudit` from `data.id`, `data.items[0].price.product_id`, `data.details.totals.total`, `data.currency_code`, `data.address.country_code`, `data.occurred_at`. **Does NOT**: verify the Pack exists, grant entitlement, deliver, email, or handle refunds.
- **Config**: connection `GetConnectionString("DefaultConnection") ?? "Data Source=store.db"`; binds `http://localhost:5291` / `https://localhost:7175`; `AllowedHosts: "*"`; no CORS middleware; `/internal/catalog` has **no auth**.

### 3.2 Python publish (`prospector/bridge.py`, `publish/publish.py`)
- `EngineBridge.publish_pass(dossier)` → builds bundle → (optional Paddle product/price) → POSTs `/internal/catalog`.
- **POST body**: `{"id","title","oneLine","dossierRef","paddleProductId","paddlePriceId","isListed","pricePence":3000}`.
- **Base URL**: `STORE_API_URL` (default `http://localhost:5291`), `STORE_INTERNAL_API_KEY` (**no default — bridge fails closed if unset**; verified server-side in fixed time at `POST /internal/catalog`).
- **Bundle** (`_create_bundle`): `publish/bundles/{candidate_id}/prospector_pack_{candidate_id[:8]}.zip` containing `01_Blueprint_BuildSpec.md`, `02_Marketing_Plan_GTM.md`, `03_Build_Launch_Kit.md`, `QA_Report.md`, `Marketing_Assets.md`.
- **Upload**: simulated only (`bridge.py:90-92`).
- `_write_listing` → `store/listings/{candidate_id}.json` (the 3-tier shape — see §2).

### 3.3 FastAPI (`prospector/api.py`)
- `get_entitlements(authorization)` → `["all"]` iff `authorization == "Bearer test-token"` else `[]`. `check_entitlement(candidate_id, entitlements)` → 403 unless `"all"` or `candidate_id` present.
- `GET /v1/listings` → teaser (id, verified_at, reverify_due_at, source_count, scout pack). `GET /v1/dossiers/{id}` → full dossier, gated.

### 3.4 Next.js (`store_platform/src/Store.Web`)
- `lib/api/client.ts`: `fetchCatalog(): Promise<Pack[]>`, `fetchPackDetails(id): Promise<PackDetails>`; `API_BASE_URL = NEXT_PUBLIC_API_URL || 'http://localhost:5000'` (⚠️ same port mismatch).
- `pages/pack/[id].tsx`: **"Buy Now" is a stub** — no handler, no Paddle.js. `pages/index.tsx`: public catalog, **no auth/session anywhere**.
- Paddle env: `NEXT_PUBLIC_PADDLE_ENVIRONMENT` (default `sandbox`), `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`. Stripe: `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` (to be removed, D2).
- `.env.example` is **missing** every store/payment var (`STORE_API_URL`, `STORE_INTERNAL_API_KEY`, `PADDLE_*`, `NEXT_PUBLIC_*`).

---

## 4. Target design (what "done" looks like)

```
[LOCAL, supervised]                         [HOSTED commerce — no model keys]
 engine PASS                                   .NET Store (public)
   │ publish_pass                               ├─ GET  /catalog, /catalog/{id}
   ├─ build bundle.zip                          ├─ POST /internal/catalog   (AUTH: internal key)   ← engine
   ├─ UPLOAD zip → object storage (R2/S3) ──►   │     stores ContentKey on Pack; IsListed=true ONLY after upload OK
   └─ POST /internal/catalog  (ContentKey, hash, version)
                                               ├─ POST /webhooks/paddle    (sig-verified, idempotent)
 buyer ──browse──► Next.js ──Paddle.js──►       │     transaction.completed → create Order + Entitlement
   checkout (overlay)                           │                          → email magic link
   success page  ◄── redirect ──               ├─ GET  /orders/{grantToken}            (magic-link landing)
   click Download ─────────────────────────►   └─ GET  /download/{grantToken}          → 302 presigned URL (short TTL)
                                                      (validates entitlement, not expired, pack content present)
```

New persisted entities (Store.Catalog): **`Order`** and **`Entitlement`** (and a `ContentKey`/`ContentHash`/`ContentVersion` on `Pack`). New events handled: `transaction.completed` (extend), `adjustment.created`/refund, `transaction.payment_failed` (log).

---

## 5. Workstreams (each: goal · contract · tasks · EDGE CASES · acceptance)

### W0 — Config & safety corrections (do first; unblocks everything)
**Tasks**
1. Fix port: set `STORE_API_URL`/`NEXT_PUBLIC_API_URL` to the real API origin; align the API bind port; document in `.env.example`.
2. **Authenticate `/internal/catalog`**: require a shared secret header (`X-Internal-Key`) compared in fixed time to `Store:InternalApiKey`; reject otherwise (the engine already sends `STORE_INTERNAL_API_KEY`). Fail closed if unset.
3. Adopt **EF migrations**: replace `EnsureCreatedAsync()` with `Database.MigrateAsync()`; generate the initial migration from the current schema; all new tables ship as migrations.
4. Lock **CORS** to the storefront origin (not `*`) on both APIs; keep webhook + `/internal/*` off CORS (server-to-server).
5. Add **all** missing vars to `.env.example` with comments (store URL, internal key, Paddle server key, Paddle webhook secret, `NEXT_PUBLIC_PADDLE_*`, object-storage creds/bucket).
**Edge cases**
- Existing `store.db` created by `EnsureCreated` has **no `__EFMigrationsHistory`** → first `Migrate()` will conflict. Provide a documented one-time baseline step (generate migration that matches current schema, then `migrations add` for the new tables).
- Internal key unset in prod → endpoint must 503/500 (fail closed), never silently accept.
**Acceptance:** engine publishes to the correct port with a valid internal key and is rejected without it; `Database.MigrateAsync()` brings a fresh DB and an existing DB to the same schema; CORS denies non-storefront origins.

### W1 — Buyer identity, Orders & Entitlements (data model)
**Goal:** record *who bought what* and gate delivery on it.
**New entities (Store.Catalog/Domain):**
```
Order            : Id(long PK), PaddleTransactionId(string, unique), BuyerEmail(string),
                   PackId(string FK→Pack.Id), AmountPence(long), Currency(string), Country(string),
                   Status(enum: Paid|Refunded|PartiallyRefunded|Disputed), CreatedAt(DateTime)
Entitlement      : Id(long PK), OrderId(long FK→Order.Id), PackId(string FK→Pack.Id),
                   BuyerEmail(string), GrantToken(string, unique, opaque, indexed),
                   Status(enum: Active|Revoked), ExpiresAt(DateTime?), CreatedAt(DateTime),
                   DownloadCount(int=0), LastDownloadedAt(DateTime?)
Pack (extend)    : + ContentKey(string?), + ContentHash(string?), + ContentVersion(int=1)
```
`GrantToken`: ≥128-bit CSPRNG, URL-safe, **non-enumerable**; it is the magic-link credential.
**Tasks:** entities + DbContext sets + indexes + migration; token generator (fixed-time compared on lookup).
**Edge cases**
- Same buyer buys the **same pack twice** → two Orders, two Entitlements (both valid); do not dedupe by pack.
- `BuyerEmail` missing/typo from Paddle → store what Paddle gives; magic link still works (token-based, not email-auth). Provide an ops path to re-send to a corrected email.
- GDPR delete request → soft-delete buyer PII (email) while keeping `SalesAudit` (financial record) and an anonymized Order.
**Acceptance:** creating an Order auto-creates an Active Entitlement with a unique non-guessable token; lookups are fixed-time.

### W2 — Content storage, upload & integrity (engine side, local)
**Goal:** the purchased ZIP is durably stored and addressable by the hosted Store.
**Tasks**
1. Replace the simulated upload (`bridge.py:90-92`) with a real upload to object storage; key e.g. `packs/{candidate_id}/v{version}/prospector_pack_{candidate_id[:8]}.zip`.
2. Compute SHA-256 of the zip; pass `ContentKey`, `ContentHash`, `ContentVersion` in the `/internal/catalog` body (extend `PublishRequest`).
3. **Ordering invariant:** the Store sets `IsListed = true` **only after** `ContentKey` is present and the object is confirmed uploaded. *Never list a pack that cannot be delivered.*
**Edge cases**
- Upload succeeds but `/internal/catalog` POST fails → retry POST; until it lands, pack stays unlisted (not sellable) — safe.
- `/internal/catalog` succeeds but upload failed → **must not happen**: upload first, then POST with the key; if upload fails, abort publish (log, leave unlisted).
- **Re-publish / re-vet** of same `candidate_id` with new content → increment `ContentVersion`, new key; existing entitlements must keep resolving to the **version they bought** (store version on the Entitlement at grant time, or keep old objects). Decide: *deliver-as-sold* (recommended) → never delete old versions while any entitlement references them.
- Bundle build fails (`_create_bundle` returns None — the path that threw the `refinement_history` error earlier) → abort publish, do not POST, alert.
- Object storage outage at publish → publish DEFERs the listing (don't half-publish); retry later.
**Acceptance:** a PASS results in a stored object + a Pack row carrying a matching `ContentHash`, and the Pack is listed only when both exist.

### W3 — Webhook → Order → Entitlement → delivery email (the core arc)
**Goal:** extend `HandleTransactionCompleted` from "write audit" to "fulfil."
**Tasks (inside the existing signature-verified, idempotent handler):**
1. After the existing `SalesAudit` write, **resolve the Pack** by `PaddleProductId` (or by `PaddlePriceId`).
2. Create `Order` (Status=Paid) + `Entitlement` (Active, token) in the **same DB transaction** as the audit write.
3. Enqueue/send the **magic-link email** (`/orders/{grantToken}`); email send is **outside** the DB transaction and is **retryable** (a failed email must not fail the webhook).
4. Return `PROCESSED`.
**Edge cases (exhaustive)**
- **Unknown `product_id`** (Pack deleted/never existed) → still record `SalesAudit` + `Order` with `PackId=null` and Status=Paid, return 200 (do NOT 4xx — the money is real), and **raise a high-priority "paid-without-fulfilment" alert**. A human reconciles.
- **`NO_ITEMS`** (0 items but paid) → same alert path; never silently 200-drop a paid event.
- **Multi-item transaction** (current code reads only `items[0]`) → loop all items; create an Order+Entitlement per purchased pack.
- **Duplicate webhook** → existing `ALREADY_PROCESSED` short-circuits BEFORE creating a second Order (keep the idempotency check first).
- **Out-of-order delivery** (refund arrives before completed, or completed re-sent after refund) → Order status is a state machine; a later `transaction.completed` for an already-Refunded txn must not re-activate entitlement.
- **DB write fails mid-handler** → return non-2xx so **Paddle retries**; ensure the audit+order+entitlement are one atomic transaction so a retry is clean (idempotency guard makes the retry a no-op once committed).
- **Timestamp skew >5 min on a legitimate Paddle retry** → Paddle signs each retry freshly, so ts is current; the ±5min check is on Paddle's send time, fine. Document that our clock must be NTP-synced or valid webhooks get rejected.
- **Email provider down** → entitlement still exists; buyer can be re-sent the link by ops; add a "resend" endpoint.
- **Currency ≠ GBP** → record actual currency; pricing display already £-centric — flag if a non-GBP total arrives (Paddle localizes; store the real numbers).
**Acceptance:** a sandbox `transaction.completed` produces SalesAudit + Order + Active Entitlement atomically, sends a magic-link email, and is fully idempotent under duplicate/retry; a paid event with an unknown product raises an alert and still records the sale.

### W4 — Delivery endpoints (gated download)
**Goal:** the buyer retrieves exactly what they bought, and nothing else.
**New endpoints (.NET Store):**
- `GET /orders/{grantToken}` → landing page data: pack title, purchase date, a download action. 404 (generic) if token unknown.
- `GET /download/{grantToken}` → validate Entitlement(Active, not expired, pack has `ContentKey`); 302 to a **short-TTL presigned GET** for the object; increment `DownloadCount`, set `LastDownloadedAt`.
**Edge cases**
- **Download before webhook processed** (buyer hits success page first) → token won't exist yet; success page polls/told "your link is emailed; allow a minute"; never 500.
- **Expired presigned URL** → buyer re-clicks; we mint a fresh one each request (URL TTL ≤ 5 min).
- **Token sharing / hotlinking** → presigned URL is short-lived; optionally cap `DownloadCount` (e.g., soft limit with ops override) — do not hard-block legitimate re-downloads.
- **Pack later unlisted/withdrawn** (re-vet stale) → existing entitlements **still deliver** (deliver-as-sold); only new sales stop.
- **`ContentKey` null** (sold before upload — should be impossible per W2 invariant, but guard anyway) → 503 + paid-without-fulfilment alert, never a 404 that looks like buyer error.
- **Revoked entitlement** (post-refund) → 410 Gone with a clear message.
- **Object missing in storage** despite key present → 503 + alert; do not expose internal error.
- **Concurrent downloads / large file** → presigned URL offloads bytes to object storage (no app streaming); safe.
**Acceptance:** valid token downloads the bought pack; unknown/expired/revoked tokens are denied with correct, non-leaky status codes; un-purchased packs are never retrievable.

### W5 — Live checkout in the storefront (Next.js)
**Goal:** turn the stub "Buy Now" into a real Paddle overlay checkout.
**Tasks**
1. Initialize Paddle.js with `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN` + environment; open overlay with the Pack's `PaddlePriceId` on click.
2. Pass a success redirect to the order-success page; rely on the **webhook** (not the client) as the source of truth for fulfilment.
3. Remove Stripe (D2): delete `stripe.ts`/`FundingPanel` wiring from the purchase path.
4. Sandbox→prod toggle via env; document the cutover.
**Edge cases**
- **Client closes overlay / network drop mid-pay** → no Order created (webhook never fires); UI shows "not completed," no entitlement leaked.
- **Client-side success but webhook delayed** → success page says "finalizing; link emailed shortly" (never assert delivery from the client).
- **Price/product drift** (Pack edited between page load and checkout) → Paddle uses the `PaddlePriceId`; ensure the displayed price matches the Paddle price (single source = Paddle for the charge).
- **Double-click Buy** → Paddle handles a single checkout session; ensure the button disables on open.
- **`PaddlePriceId` null on a listed pack** → pack must not be purchasable; hide/disable Buy and alert (publish bug).
**Acceptance:** a sandbox purchase completes in the overlay, the success page renders, and within seconds the magic-link email arrives and downloads the pack.

### W6 — Legal, disclaimers & grounding transparency
**Goal:** sell factual claims defensibly.
**Tasks**
1. Real, reviewed **ToS, Privacy, Refund** content in the existing `/terms`,`/privacy`,`/faq` shells; link from checkout.
2. Prominent **"informational only — not financial/professional advice"** disclaimer at point of sale and inside each pack (`QA_Report.md` footer).
3. **Surface grounding metadata** on every listing & pack page: `source_count`, `verified_at`, `reverify_due_at`, confidence — sourced from the dossier/listing (already produced by the engine).
4. Refund policy must reconcile with W7 refund handling (revoke entitlement on full refund).
**Edge cases**
- **Stale claim** (pack `reverify_due_at` passed) → show "verification expired; re-verifying" and optionally pull from sale; honor existing entitlements.
- **`unverifiable` checks** in a dossier → must be visibly labeled, never presented as supported (the engine already enforces source-or-die; surface it).
**Acceptance:** no paid claim renders without visible provenance + disclaimer; policy pages are real and linked from checkout.

### W7 — Refunds, disputes & reconciliation
**Goal:** money-out and exceptions are handled, not ignored.
**Tasks**
1. Handle Paddle **refund/adjustment** events (`adjustment.created` etc.) and **`transaction.payment_failed`** (log only): on full refund → Order.Status=Refunded, Entitlement.Status=Revoked; partial → PartiallyRefunded (keep access per policy); dispute/chargeback → Disputed + revoke.
2. Reconciliation report: Orders without Entitlements, paid-without-fulfilment alerts, entitlements with zero downloads after N days.
**Edge cases**
- **Refund for an unknown/again-missing Order** → create a reconciliation record; alert.
- **Chargeback then re-purchase** → new Order/Entitlement; old stays Revoked.
- **Refund webhook before the completed webhook** (ordering) → state machine tolerates; final state must be Refunded/Revoked.
**Acceptance:** a sandbox refund revokes the entitlement (download → 410) and updates Order status; reconciliation surfaces any paid-without-fulfilment case.

### W8 — Tests, CI & alerting (verification)
**Goal:** prove it works and keep it working.
**Tasks**
1. **Fix `tests/integration/test_api.py`** (`TestClient(app=...)` → `httpx.ASGITransport`/version pin); un-ignore it; prove the entitlement gate (positive + negative).
2. **CI pipeline** (GitHub Actions): run full Python suite + **golden set with a hard <100% discrimination block**, build/test the .NET solution (`Store.Tests`), build the Next.js app.
3. **E2E test** (sandbox): signal→PASS→publish→catalog→Paddle sandbox pay→webhook→entitlement→download; plus refund→revoke.
4. **Alerting:** "paid-without-fulfilment" (W3), webhook signature failures spike, object-storage errors, publish without `ContentKey`.
**Edge cases**
- Webhook tests must cover: bad signature, missing secret (503), duplicate (ALREADY_PROCESSED), unknown product, multi-item, 0-item, refund-before-complete.
- Migration test: apply migrations to a fresh DB **and** to a snapshot of the current `EnsureCreated` DB.
**Acceptance:** green CI gates every PR; the E2E test passes end-to-end in sandbox including the refund path; all webhook edge cases covered.

---

## 6. Consolidated edge-case catalogue (quick index)

**Money / webhook:** duplicate ✓idempotent; out-of-order refund/complete; unknown product (paid-without-fulfilment alert, still 200); 0-item paid; multi-item cart; bad/missing signature (fails closed); clock skew (NTP); DB failure → non-2xx for retry; non-GBP currency; payment_failed.
**Delivery:** download before webhook; expired presigned URL; token sharing/hotlink; pack unlisted after sale (deliver-as-sold); ContentKey null guard; revoked→410; object missing→503+alert; concurrent/large downloads.
**Publish/content:** upload-then-POST ordering invariant; never list undeliverable pack; re-vet/version (deliver-as-sold, keep old versions); bundle build failure (abort); provisional PASS must never publish; storage outage → defer.
**Identity:** guest checkout; email typo (token-based recovery + resend); same pack bought twice; GDPR delete (keep SalesAudit, drop PII).
**Config/infra:** port mismatch (5000 vs 5291); `/internal/catalog` auth; migrations vs EnsureCreated baseline; CORS lockdown; SQLite write-locking under webhook+catalog load (consider serialized writes or Postgres if volume grows); secrets in `.env.example`; no model keys on hosted side.
**Storefront:** overlay close/network drop; client-success vs webhook-truth; price drift (Paddle price is source of charge); double-click; null PaddlePriceId on listed pack; remove Stripe.
**Legal:** stale/expired verification; unverifiable claims labeled; disclaimer at point of sale + in pack.

---

## 7. Sequencing & dependencies

```
W0 (config/migrations/auth)  ──►  W1 (Order/Entitlement schema)  ──►  W3 (webhook fulfilment)  ──►  W4 (delivery)
        │                                                              ▲
        └──►  W2 (content upload + ordering invariant)  ──────────────┘
W5 (checkout)  depends on W4 (something to deliver) + live Paddle (D2)
W6 (legal)     parallel; gates launch
W7 (refunds)   after W3
W8 (CI/E2E)    continuous; E2E needs W2–W5
```

**Critical path to first real sale:** W0 → W1 → W2 → W3 → W4 → W5 (+ W6 legal, + live Paddle). W7/W8 harden it; CI/golden-gate (W8.2) should land early to protect the engine during all this churn.

---

## 8. Definition of Done (launch gate — mirrors `GO_LIVE_SPEC.md §10`)

- [ ] Live Paddle purchase → magic-link email → buyer downloads exactly the bought pack; un-purchased → denied.
- [ ] Webhook is signature-verified, idempotent, atomic (audit+order+entitlement), and every §6 money/webhook edge case is tested.
- [ ] No pack is ever listed without confirmed deliverable content (`ContentKey`+hash).
- [ ] Refund revokes entitlement (download→410); reconciliation surfaces paid-without-fulfilment.
- [ ] `/internal/catalog` authenticated; CORS locked; migrations applied to fresh + existing DB; secrets only in env, none on the hosted side that touch the model.
- [ ] ToS/Privacy/Refund live + "not advice" disclaimer + grounding metadata on every paid surface.
- [ ] `provisional` PASSes provably cannot publish.
- [ ] CI runs full suite + golden set (hard block <100%) + .NET + web build on every PR; E2E sandbox (incl. refund) passes.
- [ ] Runbook: moat outage, golden-set failure, config rollback, paid-without-fulfilment, refund/dispute.

---

## Appendix — open questions for the founder
1. Object-storage provider/account (R2 vs S3)? (D5)
2. Email provider for magic links (Postmark/SES/Resend)?
3. Confirm Paddle as sole MoR and remove Stripe? (D2)
4. v1 = single £30 pack, tiers deferred? (D3)
5. Hosting target for the .NET Store + Next.js (and is the engine box ever reachable, or strictly push-only)? (D1/D4)
6. Retire FastAPI `api.py` for v1, or keep as local-only dossier reader? (D4)

> Percentages and "current state" notes are grounded in a code walkthrough on 2026-06-16; verbatim contracts in §3 are quoted from source. The standard local test suite is **170 passing** (the 5 API tests in `tests/integration/test_api.py` do not currently collect — W8.1 fixes that).

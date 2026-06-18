# Deployment Runbook — Prospector Store

Executable, command-level steps to ship the storefront. For the build-ready architecture spec see
`HANDOVER_BRIDGE_TO_LAUNCH.md` / `GO_LIVE_SPEC.md`; this doc is the *go-live procedure* and reflects
the verified state on 2026-06-18.

---

## 0. Verified state (what already works — do not redo)

- **Catalogue + storefront**: 11 packs listed, served by `GET /catalog` (Store.Api). Web home,
  pack pages, search + sort, 404/500, order-confirmed all render. (`npm run build` clean.)
- **Inventory is real**: each listed pack is a ~45 KB bundle of 5 docs (Blueprint, GTM, Build Kit,
  QA Report, Marketing Assets). Not thin.
- **Content delivery works**: all 11 deliverables are in Cloudflare R2 (`R2_BUCKET=prospector-packs`),
  content-addressed at `packs/<id>/<sha256>.zip`. Verified:
  `./.venv-r2/bin/python store_platform/scripts/sync_r2_content.py --listed-only --dry-run`
  → `already-present=11 missing=0 mismatch=0`.
- **Stripe server code is implemented**: checkout, webhook, refunds (`StripeProvider`,
  `StripeProvisioner` in bridge.py).

## 1. The single blocker

All 11 packs are provisioned as **`PaymentProvider=paddle` with `price_stub_*` price ids**. With
stub prices the storefront falls back to "Notify me" — it cannot take money. Going live = supplying
Stripe credentials and **re-provisioning the 11 packs onto real Stripe prices**. Everything else is
done.

---

## 2. Pre-flight (all must pass before touching prod)

```bash
cd <repo>
# Content present in R2 for every listed pack (read-only):
./.venv-r2/bin/python store_platform/scripts/sync_r2_content.py --listed-only --dry-run   # expect missing=0 mismatch=0

# No stub prices should remain AFTER step 4; before launch this will (correctly) show 11:
sqlite3 store_platform/src/Store.Api/store.db \
  "SELECT count(*) AS stub_prices FROM Packs WHERE IsListed=1 AND ProviderPriceId LIKE 'price_stub_%';"

# Web + API build:
( cd store_platform/src/Store.Web && npm run build )            # Next.js
( cd store_platform/src/Store.Api && dotnet build -c Release )   # Store.Api
```

## 3. Step 1 — Secrets (FOUNDER — money path, stays on Claude/founder)

`.env` is gitignored; never commit secrets. Set these in the deploy environment (env vars or the
prod secret store), NOT in tracked appsettings.

**Store.Api** (config key → env override):

| Config key                  | Purpose                                  |
|-----------------------------|------------------------------------------|
| `Stripe:ApiKey`             | Stripe secret key (`sk_test_…`/`sk_live_…`) |
| `Stripe:WebhookSecret`      | Webhook signing secret (`whsec_…`)       |
| `payments:active_provider`  | set to `stripe`                          |
| `Store:InternalApiKey`      | engine → `/internal/catalog` auth        |
| `Store:EntitlementsApiKey`  | engine → entitlements auth               |
| `R2:*` (Account/AccessKey/SecretAccessKey/Bucket) | already set via `R2_*` env |
| Postmark server token       | delivery email (magic download link)     |

> ⚠️ `MoneyRailConfigGate` **fails API startup** if the active provider's keys are missing. So set
> `Stripe:ApiKey` + `Stripe:WebhookSecret` *before* flipping `payments:active_provider=stripe`.

**Store.Web** (build/runtime env):

| Env var                            | Purpose                          |
|------------------------------------|----------------------------------|
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | `pk_test_…`/`pk_live_…` (gates the buy button) |
| `NEXT_PUBLIC_API_URL`              | Store.Api base URL               |
| `NEXT_PUBLIC_SITE_URL`            | canonical site URL (SEO, redirects) |

## 4. Step 2 — Re-provision the 11 packs onto Stripe

The 11 existing packs were provisioned as Paddle, so they carry no Stripe price ids. There is **no
existing-pack re-provision CLI yet** — bridge.py's `StripeProvisioner` runs at publish time. A small
script is needed (≈30 lines): for each listed pack, create a Stripe product + one-time price (£49),
then update the Store DB (`ProviderProductId`, `ProviderPriceId`, `PaymentProvider='stripe'`) via the
authenticated `/internal/catalog` upsert. **Claude to write this once keys are in** (founder fence:
money path).

Verify after:

```bash
sqlite3 store_platform/src/Store.Api/store.db \
  "SELECT count(*) FROM Packs WHERE IsListed=1 AND (ProviderPriceId LIKE 'price_stub_%' OR PaymentProvider!='stripe');"
# expect 0
```

## 5. Step 3 — Stripe webhook

- Add a webhook endpoint in the Stripe dashboard → the Store.Api webhook route, events:
  `checkout.session.completed` (+ refund/dispute events for reconciliation).
- Put its signing secret into `Stripe:WebhookSecret`.
- Confirm the gate passes and the API boots.

## 6. Step 4 — Content delivery gate (already green; re-confirm in prod env)

```bash
./.venv-r2/bin/python store_platform/scripts/sync_r2_content.py --listed-only   # uploads any missing; expect missing=0
```

For a **local-only** dev box (no R2), use the local equivalent instead:
`python3 store_platform/scripts/sync_content_store.py --listed-only` (syncs into
`Store.Api/content_store/`, served by the dev `/dev-content` endpoint).

## 7. Step 5 — Smoke test (Stripe TEST mode, end to end)

1. Buy one pack with test card `4242 4242 4242 4242`.
2. Webhook fires → Order + Entitlement created.
3. Delivery email arrives (Postmark) with the magic download link.
4. Link downloads the zip; it opens and contains the 5 docs.
5. Confirm the order-confirmed page renders.

## 8. Step 6 — Cutover to LIVE

- Swap Stripe test keys → live keys (`Stripe:ApiKey`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`,
  webhook secret for the live endpoint).
- Re-run **Step 2** in live mode (test-mode price ids are not valid in live mode).
- Re-run the Step 7 smoke test with a real card; refund it via the Stripe dashboard to confirm the
  refund path.

## 9. Rollback

- Fastest safe rollback: set `payments:active_provider=paddle` (or unset Stripe keys) → the
  storefront reverts to "Notify me", no charges possible. Catalogue and content stay up.
- Per-pack: `UPDATE Packs SET IsListed=0 WHERE Id=…;` to pull a single pack.

## 10. Definition of done (launch gate)

- [ ] `payments:active_provider=stripe`, gate passes, API boots.
- [ ] `0` packs with `price_stub_%` or non-stripe provider among listed.
- [ ] R2 content gate green (`missing=0`).
- [ ] Test-mode purchase → email → download verified.
- [ ] Live-mode purchase + refund verified.
- [ ] `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` set in the web build.

## 11. Explicitly NOT in this launch (deferred, non-blocking)

- **Business admin UI** (orders/revenue, unlist/reprice, refund-from-app) — today: raw sqlite +
  Stripe dashboard. Acceptable for launch volume.
- **Category/lane/sector filters** — search + sort ship now; real filters need pack taxonomy
  (engine → bridge → API → web).
- **Existing-pack re-provision CLI** — needed for Step 2; build when keys land.

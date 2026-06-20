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

## 1. The single blocker — CLEARED 2026-06-19 (TEST mode)

~~All 11 packs are provisioned as `PaymentProvider=paddle` with `price_stub_*` price ids.~~
**RESOLVED in Stripe TEST mode:** user supplied test keys; all 11 packs re-provisioned onto real
Stripe test prices (£49 GBP) via `store_platform/scripts/reprovision_stripe.py`; `0` stubs remain;
API boots in stripe mode (gate passes) and mints real `cs_test_…` checkout sessions; web buy button
is live (`.env.local` has the publishable key). **Remaining before money is real: LIVE-mode cutover
(§8) + the webhook→entitlement→download leg verified with an actual test-card payment (§7).**

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
| `R2:*` (Account/AccessKey/SecretAccessKey/Bucket) | already set via `R2_*` env (bridged into Keystone.Storage `Storage:*` at startup; no ops change) |
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

Script now exists: **`store_platform/scripts/reprovision_stripe.py`** (stdlib only, idempotent —
Stripe idempotency keys + skip-if-already-stripe; `--dry-run`, `--force`). For each listed pack it
creates a Stripe Product + one-time Price (£49 GBP) and updates store.db
(`ProviderProductId`, `ProviderPriceId`, `PaymentProvider='stripe'`) directly. Reads `STRIPE_API_KEY`
from `.env`. Test keys → test objects; for live cutover (§8) re-run with live keys.

```bash
python3 store_platform/scripts/reprovision_stripe.py --dry-run   # preview
python3 store_platform/scripts/reprovision_stripe.py             # do it (TEST done 2026-06-19)
```

Verify after:

```bash
sqlite3 store_platform/src/Store.Api/store.db \
  "SELECT count(*) FROM Packs WHERE IsListed=1 AND (ProviderPriceId LIKE 'price_stub_%' OR PaymentProvider!='stripe');"
# expect 0
```

## 5. Step 3 — Stripe webhook

- **Route:** `POST /webhooks/stripe`. Events: `checkout.session.completed` (+ `charge.refunded`,
  `charge.dispute.created` for revoke-on-reversal).
- **Prod:** add the endpoint in the Stripe dashboard, put its signing secret into `Stripe:WebhookSecret`.
- **Local/TEST:** `stripe listen --api-key $STRIPE_API_KEY --forward-to localhost:5291/webhooks/stripe`.
  Its signing secret (`stripe listen --print-secret`) is already in `.env` as `Stripe__WebhookSecret`
  (`whsec_…`). Confirm the gate passes and the API boots (it does — verified 2026-06-19).

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

## 10b. Admin portal (Control Center) — access

The Streamlit Control Center edits config, launches runs, and shows cost data. It is gated by a
single operator password and bound to loopback. **Never bind it to `0.0.0.0` or expose it
publicly.**

```bash
export CONTROL_CENTER_PASSWORD='<a long random secret>'   # required; portal fails closed without it
scripts/run_control_center.sh                              # serves on 127.0.0.1:8601
```

Remote access is an SSH tunnel, not a public bind:

```bash
ssh -L 8601:localhost:8601 <host>     # then open http://localhost:8601 locally
```

Fail-closed behaviour: with no `CONTROL_CENTER_PASSWORD` set the portal renders only an error and
stops; a wrong password is rejected with a timing-safe compare and locks out after 5 attempts per
session.

## 10c. Always-on generation daemon

Generation runs continuously and unattended (founder decision, 2026-06-20). The automated backstop
replaces human supervision: a daily spend ceiling (`config.yaml` `spend.daily_cap_usd`, read from
`store/prospector.jsonl`) and a filesystem kill switch.

```bash
# One bounded batch (manual / cron-style):
python -m prospector.scheduler.run_scheduled --once
# Resident daemon (loops on --interval seconds, default 2h):
python -m prospector.scheduler.run_scheduled --daemon --interval 7200
# Guards only, no generation:
python -m prospector.scheduler.run_scheduled --once --dry-run
```

Resident install via launchd (`KeepAlive` restarts it if it dies):

```bash
cp deploy/com.prospector.scheduler.plist ~/Library/LaunchAgents/
launchctl load   ~/Library/LaunchAgents/com.prospector.scheduler.plist   # starts immediately
launchctl unload ~/Library/LaunchAgents/com.prospector.scheduler.plist   # stop
```

Kill switch (no unload needed — the daemon re-checks every cycle):

```bash
touch store/scheduler/PAUSE     # idle
rm    store/scheduler/PAUSE     # resume
```

Audit: ticks land in `store/scheduler/ticks.jsonl`; launchd stdio in `store/scheduler/launchd.*.log`.

**Caveat:** the moat (verify) needs the Claude/Gemini CLIs authenticated in the daemon's
environment. If they are not, generation DEFERs (it does not crash) and the work is recoverable
with `python -m prospector.run vet --resume`. Confirm CLI auth survives the launchd session before
relying on unattended PASSes.

## 11. Explicitly NOT in this launch (deferred, non-blocking)

- **Business admin UI** (orders/revenue, unlist/reprice, refund-from-app) — today: raw sqlite +
  Stripe dashboard. Acceptable for launch volume.
- **Category/lane/sector filters** — search + sort ship now; real filters need pack taxonomy
  (engine → bridge → API → web).
- **Existing-pack re-provision CLI** — needed for Step 2; build when keys land.

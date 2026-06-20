# Production deploy — storefront on Fly, engine local

This is the host-agnostic prod path for the £49-pack storefront. The artifacts (Dockerfiles +
`fly/*.toml`) target **Fly.io**, but the Dockerfiles are plain and run on any Docker host.

## Topology (decided 2026-06-20)

```
Your Mac (local, launchd):
  Prospector engine  ── generation + moat on your gemini_cli / claude_cli (subscription)
        │  PASS pack ── HTTPS POST /internal/catalog  (X-Internal-Key)
        ▼
Fly.io (public):
  prospector-store-api   Store.Api  :8080   volume store_data → /data/store.db
  prospector-store-web   Store.Web  :3000   NEXT_PUBLIC_API_URL baked to the API URL
Stripe webhook ── HTTPS ──▶ https://<api>.fly.dev/webhooks/stripe

Admin (control_center): NOT public. Stays local, or reach over `fly proxy` / WireGuard.
```

**Why the engine stays local:** its moat and artifact generation run on your locally
authenticated Gemini/Claude CLIs (the Claude Code subscription). That auth cannot move into a
Fly VM, and the operating rules pin the engine to "local or within your Claude Code
subscription." It publishes finished packs to the cloud storefront over the existing
`/internal/catalog` endpoint, so it never needs to be co-located.

---

## 0. Prerequisites

- `flyctl` installed and `fly auth login` done, in a Fly org you control.
- Live Stripe account (keys + a webhook endpoint you can register).
- Cloudflare R2 bucket + credentials (pack delivery).
- `store_platform/.env.production` filled in from `.env.production.example` (used both to derive
  the Fly secrets below and to run the local `go_live.sh` price reprovision).

## 1. One-time: create the apps + volume

```bash
cd store_platform

# API app (do not deploy yet — secrets first).
fly apps create prospector-store-api
# Persistent SQLite volume. SINGLE writer → one machine only, never scale the count.
fly volumes create store_data --app prospector-store-api --region lhr --size 1

# Web app.
fly apps create prospector-store-web
```

(Use your own app names; if you change them, update `deploy/fly/*.toml` and the web build arg.)

## 2. Set the API secrets

Everything secret or deploy-specific goes through `fly secrets` (never into git or the toml).
Map straight from `.env.production.example`:

```bash
fly secrets set --app prospector-store-api \
  Stripe__ApiKey="sk_live_..." \
  Stripe__WebhookSecret="whsec_..." \
  Store__InternalApiKey="$(openssl rand -hex 32)" \
  Store__EntitlementsApiKey="$(openssl rand -hex 32)" \
  STORE_ALLOWED_ORIGIN="https://prospector-store-web.fly.dev" \
  STORE_PUBLIC_URL="https://prospector-store-api.fly.dev" \
  R2_ACCOUNT_ID="..." \
  R2_ACCESS_KEY_ID="..." \
  R2_SECRET_ACCESS_KEY="..." \
  R2_BUCKET="..."
```

> Keep the two `Store__*` key values — the **local engine** uses the SAME values to authenticate
> to `/internal/catalog` and `/entitlements` (step 6). `MoneyRailConfigGate` is fail-closed: if
> any required secret is missing or a dev placeholder, the API refuses to boot.

## 3. Deploy the API

```bash
# from store_platform/ — build context must include local-feed/ + Store.Catalog
fly deploy --config deploy/fly/api.fly.toml
```

First boot runs EF `MigrateAsync` and creates an EMPTY schema on the volume. The catalogue is
seeded in step 5.

Smoke it:

```bash
curl -fsS https://prospector-store-api.fly.dev/catalog        # [] until seeded — should be 200
curl -fsS https://prospector-store-api.fly.dev/catalog/stats  # {"listed":0,"registered":0}
```

## 4. Deploy the web front end

`NEXT_PUBLIC_API_URL` is inlined at build time, so pass the real API URL as a build arg:

```bash
cd src/Store.Web
fly deploy --config ../../deploy/fly/web.fly.toml \
  --build-arg NEXT_PUBLIC_API_URL=https://prospector-store-api.fly.dev
```

Open `https://prospector-store-web.fly.dev` — the page renders but lists nothing until seeding.

## 5. Register the Stripe live webhook

In the Stripe dashboard (LIVE mode) add an endpoint:

- URL: `https://prospector-store-api.fly.dev/webhooks/stripe`
- Events: `checkout.session.completed`, `charge.refunded`, `charge.dispute.created`

Copy its signing secret and update the API secret if it differs from step 2:

```bash
fly secrets set --app prospector-store-api Stripe__WebhookSecret="whsec_..."
```

## 6. Seed the catalogue (engine → Fly, the chosen seam)

Packs reach the cloud storefront from your local engine over `/internal/catalog`. Reprovision
your packs onto **live** Stripe prices, then publish to the Fly API:

```bash
# Mint live prices on the local catalogue (writes price_... ids into store.db):
STRIPE_API_KEY="sk_live_..." .venv/bin/python store_platform/scripts/reprovision_stripe.py --force

# Publish to the deployed API (point the engine's publish target at the Fly URL + internal key).
# The publish step authenticates with the SAME Store__InternalApiKey set in step 2.
#   STORE_API_URL=https://prospector-store-api.fly.dev \
#   STORE_INTERNAL_KEY=<the Store__InternalApiKey value> \
#   <run the engine publish for each PASS pack>
```

Alternative (bulk first load): copy a prepared `store.db` straight onto the volume with
`fly ssh console` / `fly sftp`, then restart the machine. Publishing over the API is preferred —
it is the same path the always-on engine uses.

Re-check: `curl https://prospector-store-api.fly.dev/catalog/stats` should now show `listed > 0`.

## 7. Keep the engine running locally

The engine is the launchd daemon (unchanged by this deploy):

```bash
cp deploy/com.prospector.scheduler.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.prospector.scheduler.plist
```

Backstops still apply: `spend.daily_cap_usd` ($20) + the `store/scheduler/PAUSE` switch. Point
its publish target at the Fly API URL + internal key so new PASS packs flow to the storefront.

> Fix before loading: the plist `PATH` lacks `~/.local/bin`, where `claude` lives — add
> `/Users/chidionyema/.local/bin` so the full moat resolves under launchd (Gemini still works
> without it; a missing tier defers, never crashes).

## 8. Admin (control_center) — never public

`control_center` is designed for localhost + SSH tunnel ("never a public bind", per its own
code). Do **not** give it a public Fly service. Either keep it on your Mac, or if it must run on
Fly, deploy it with no `[http_service]` and reach it via `fly proxy` / WireGuard only.

---

## Verify before taking real money

1. `bash store_platform/scripts/prove_launch.sh` (money paths + non-payment API) and
   `bash store_platform/scripts/prove_web.sh` (UI) — these prove the **build**, locally.
2. Against the **deployed** API: `curl https://<api>.fly.dev/catalog` returns your packs.
3. One real low-value purchase on the live web app → confirm the download link works → refund
   it from the Stripe live dashboard and confirm the entitlement revokes. This is the only step
   that proves the deployed money path end to end.

## Updating later

- API code change: `fly deploy --config deploy/fly/api.fly.toml` (from `store_platform/`).
- Web change: re-run the step-4 command (the build arg must always be the live API URL).
- Rotate a secret: `fly secrets set --app prospector-store-api KEY=value` (triggers a restart).

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
  STORE_STOREFRONT_URL="https://prospector-store-web.fly.dev" \
  STORE_PUBLIC_URL="https://prospector-store-api.fly.dev" \
  MAILJET_API_KEY="..." \
  MAILJET_API_SECRET="..." \
  MAILJET_FROM_EMAIL="orders@your-verified-domain" \
  R2_ACCOUNT_ID="..." \
  R2_ACCESS_KEY_ID="..." \
  R2_SECRET_ACCESS_KEY="..." \
  R2_BUCKET="..."
```

> **The two URL secrets are different hosts on purpose.** `STORE_STOREFRONT_URL` is where a
> buyer is sent after paying — it must be the **web** app, because `/orders/success` and
> `/pack/{id}` are Next.js pages this API does not serve. `STORE_PUBLIC_URL` is this **API**,
> because the magic-link email points at the API's own `/orders/{token}` route. Setting the
> redirect to the API host sends every paying customer to a 404. `go_live.sh` now refuses to
> proceed if these two are equal, and the API logs `DELIVERY-DEGRADED` at boot if neither
> storefront value is present.

> **Mailjet is optional but you will feel its absence.** Without it the money rail still works
> and the success page still hands the buyer their download (it resolves the entitlement from
> the checkout session directly), but no confirmation email goes out, so a buyer who closes the
> tab has no way back to their purchase. The API logs `DELIVERY-DEGRADED` at boot when it is
> unset, and `FULFILMENT-EMAIL-SKIPPED` per order. The From address must be a Mailjet-verified
> sender on a verified domain, or Mailjet rejects the send.
>
> Mailjet authenticates with a key **pair**: `MAILJET_API_KEY` (public) is the Basic-auth
> username and `MAILJET_API_SECRET` (private) is the password. Setting one without the other
> reads as unconfigured by design — a half-set pair 401s on every send, and that failure is
> much harder to diagnose from the outside than "not configured".

> Keep the two `Store__*` key values — the **local engine** uses the SAME values to authenticate
> to `/internal/catalog` and `/entitlements` (step 6). `MoneyRailConfigGate` is fail-closed: if
> any required secret is missing or a dev placeholder, the API refuses to boot.

## 3. Deploy the API

> **HARD RULE — a dirty `store_platform/` tree aborts the deploy.** `fly deploy` builds the
> **working tree**, not `HEAD`. Any uncommitted edit — including one left by another session
> that you never saw — ships to production silently and cannot be rebuilt or rolled back from
> git, because it was never committed. This happened on 2026-07-30. Every `fly deploy` below is
> therefore prefixed with the guard; do not run one without it.
>
> ```bash
> bash scripts/predeploy_guard.sh   # exit 0 = clean; exit 1 = commit or stash first
> ```

```bash
# from store_platform/ — the `.` sets the build context (must include local-feed/ + Store.Catalog).
# Without the `.`, fly uses the config file's directory (deploy/fly/) as the context and the build
# fails. The dockerfile path inside the toml is config-dir-relative for the same reason.
bash scripts/predeploy_guard.sh && fly deploy . --config deploy/fly/api.fly.toml
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
bash scripts/predeploy_guard.sh   # same hard rule as step 3 — never skip it
cd src/Store.Web
# The `.` sets the build context to src/Store.Web (Next's self-contained build).
fly deploy . --config ../../deploy/fly/web.fly.toml \
  --build-arg NEXT_PUBLIC_API_URL=https://prospector-store-api.fly.dev
```

Open `https://prospector-store-web.fly.dev` — the page renders but lists nothing until seeding.

## 5. Register the Stripe live webhook

Run the script — it registers the endpoint over the Stripe API and writes the signing secret
into `.env.production` for you. The secret is never printed, so it does not end up in
scrollback or shell history.

```bash
bash store_platform/scripts/register_stripe_webhook.sh
```

It derives the URL from `STORE_PUBLIC_URL` (the API host — **not** the storefront) and
registers exactly the three events `StripeProvider` handles:
`checkout.session.completed` grants the entitlement, `charge.refunded` and
`charge.dispute.created` revoke it. Registering fewer means a refund silently leaves the buyer
with a working download link.

If an endpoint for that URL already exists the script stops and says so, because Stripe reveals
a signing secret only at creation and it cannot be read back. Re-run with `--recreate` to
delete and re-issue. Safe while no live traffic is flowing; mid-flight it drops any event
Stripe is retrying against the old endpoint.

Then push the captured secret to the API:

```bash
fly secrets set --app prospector-store-api Stripe__WebhookSecret="$(grep '^Stripe__WebhookSecret=' store_platform/.env.production | cut -d= -f2-)"
```

<details><summary>Doing it by hand in the dashboard instead</summary>

In the Stripe dashboard (LIVE mode) add an endpoint with the URL and the three events above,
copy its signing secret into `Stripe__WebhookSecret` in `.env.production`, then run the
`fly secrets set` command above.
</details>

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

- API code change: `bash scripts/predeploy_guard.sh && fly deploy . --config deploy/fly/api.fly.toml`
  (from `store_platform/`). The guard is not optional — see the hard rule in step 3.
- Web change: re-run the step-4 command (the build arg must always be the live API URL).
- Rotate a secret: `fly secrets set --app prospector-store-api KEY=value` (triggers a restart).

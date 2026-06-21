# Staging plan (parked — build AFTER the existing-env launch)

Founder decision 2026-06-21: for now the always-on generation daemon auto-publishes to the **one
existing environment** (`prospector-store-api.fly.dev`). A dedicated staging environment is
deferred. This file is the ready-to-execute plan for when we want it.

## Why a staging app later
The daemon publishes **unreviewed** PASSes autonomously. Today those land on the live prod store
(acceptable while the store is in Stripe **test** mode, pre-launch). Once real money flows
(WS0.2 live cutover), we do not want an autonomous process writing straight to the revenue store
with no gate. Staging gives the daemon a safe target; a human (or a promote step) moves vetted
packs prod-ward.

## Shape (decided: separate Fly app, mirror of prod)
- App: `prospector-store-api-staging` (config already written: `deploy/fly/api.staging.fly.toml`).
- Its own volume (`store_data` → `/data/store.db`), single machine (SQLite single-writer).
- Stripe **test** keys, its own `Store__InternalApiKey`, R2 (reuse `prospector-packs` bucket or a
  `prospector-packs-staging` bucket), staging `STORE_PUBLIC_URL` / `STORE_ALLOWED_ORIGIN`.

## Execute (when greenlit)
1. `fly apps create prospector-store-api-staging --org personal`
2. `fly volumes create store_data -a prospector-store-api-staging -r lhr -n 1 --yes`
3. Set secrets (`-a prospector-store-api-staging`): `Store__InternalApiKey` (fresh `openssl rand
   -hex 32`), `Stripe__ApiKey`/`Stripe__WebhookSecret` (test), `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID`
   `R2_SECRET_ACCESS_KEY` `R2_BUCKET`, `STORE_PUBLIC_URL` `STORE_ALLOWED_ORIGIN`.
4. `cd store_platform && fly deploy . --config deploy/fly/api.staging.fly.toml`
5. Verify: `curl https://prospector-store-api-staging.fly.dev/catalog/stats` → `{"listed":0,...}`.
6. Point daemon `.env` `STORE_API_URL` + `STORE_INTERNAL_API_KEY` at staging; restart daemon.
7. Add a **promote** step (script or admin action) that copies a reviewed staging pack to prod via
   prod `/internal/catalog` — this is the human gate the autonomous loop otherwise lacks.

## Cost
+1 `shared-cpu-1x` 512mb machine + 1GB volume (~a few $/mo). Tear down with `fly apps destroy`
when not in use.

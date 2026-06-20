# Go-Live Runbook — Stripe LIVE cutover (WS0.2)

The money path is already proven on Stripe TEST + live R2 (13/13 gates — see
`store/launch/test-card-proof.md`, re-runnable via `scripts/prove_money_path.sh`). This runbook
flips it to LIVE. Everything that can be automated is in `scripts/go_live.sh`; the steps below
are the irreducible human jobs (pasting secrets, a dashboard click, one real card).

## What only a human can do
1. Obtain the **live** Stripe secret key (`sk_live_…`) from the Stripe dashboard.
2. Register the **live webhook endpoint** in the dashboard (this yields the `whsec_…` secret).
3. Make **one real low-value purchase + refund** on the deployed storefront.

Everything else (validation, reprovisioning prices, proving the fail-closed boot gate) is automated.

## Steps

1. **Fill the environment.** Copy the template and paste live values:
   ```
   cp store_platform/.env.production.example store_platform/.env.production
   # edit store_platform/.env.production
   #   Stripe__ApiKey=sk_live_...
   #   Store__InternalApiKey / Store__EntitlementsApiKey  -> openssl rand -hex 32 (NOT the dev placeholders)
   #   R2_*  -> the production bucket credentials
   #   STORE_ALLOWED_ORIGIN / STORE_PUBLIC_URL -> the real domains
   ```
   Leave `Stripe__WebhookSecret` as a placeholder for now if you don't have it yet (step 3 fills it).

2. **Reprovision + prove the gate (one command).**
   ```
   bash store_platform/scripts/go_live.sh --dry-run   # optional: validate + preview, change nothing
   bash store_platform/scripts/go_live.sh             # reprovision LIVE prices + prove the boot gate
   ```
   This validates every secret is real and correctly shaped, points the catalogue packs at live
   Stripe prices, and boots Store.Api in `Production` to confirm `MoneyRailConfigGate` accepts the
   config (the gate refuses to start on a missing/placeholder secret, so a green boot is the proof).

3. **Deploy + register the webhook.** Deploy the API with `.env.production` exported in its
   environment. In the Stripe dashboard register the live endpoint:
   ```
   https://<your-api-domain>/webhooks/stripe
   events: checkout.session.completed, charge.refunded, charge.dispute.created
   ```
   Copy its signing secret into `Stripe__WebhookSecret`, redeploy, and re-run go_live.sh
   `--skip-reprovision` to re-prove the gate with the final secret.

4. **One real transaction.** Buy the cheapest pack on the live storefront with a real card, confirm
   the download link works, then refund it in the dashboard and confirm the download 410s (access
   revoked). To replay the full automated gate suite against live instead of doing it by hand:
   ```
   STRIPE_TEST_SECRET_KEY="$Stripe__ApiKey" bash store_platform/scripts/prove_money_path.sh
   ```

## Rollback
Set `payments__active_provider` back to `paddle` (or stop the deploy). No data migration is involved;
reprovisioning only updates `ProviderPriceId`/`ProviderProductId` on existing packs.

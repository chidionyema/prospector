# Storefront (Store.Api + Store.Web)

The £49-pack storefront: a .NET 9 minimal API (`src/Store.Api`), a Next.js front end
(`src/Store.Web`), an EF Core + SQLite catalogue (`store.db`), Stripe checkout, and
presigned Cloudflare R2 downloads. This README is the operator's guide to **launching it
locally** and **proving every money path** before going live.

## Prerequisites

Set these in your shell (TEST values are fine for everything except the final live cutover):

```bash
export STRIPE_TEST_SECRET_KEY=sk_test_...      # a real Stripe TEST secret key
export R2_ACCOUNT_ID=...        export R2_BUCKET=...
export R2_ACCESS_KEY_ID=...     export R2_SECRET_ACCESS_KEY=...
```

You also need the **Stripe CLI** (`stripe`) for the interactive test stack, plus `dotnet`
(.NET 9) and Node for the web app.

## Prove every money path — one command

```bash
bash store_platform/scripts/prove_launch.sh
```

This is the gate to run **before every launch and after any change** to checkout, webhook,
fulfilment, or delivery code. It boots its own throwaway API instances, proves all paths, and
exits non-zero if anything fails. Two phases:

- **Phase A — the buy button** (`prove_checkout.sh`): for **every listed pack** it calls the
  real `POST /packs/{id}/checkout` against a copy of the real catalogue with your real Stripe
  key, and asserts a real hosted Stripe Checkout Session comes back. Catches stale/invalid
  `ProviderPriceId` ("No such price") and checkout/tax misconfiguration.
- **Phase B — fulfilment + negative paths** (`prove_money_path.sh`): signed webhook → order →
  entitlement → presigned R2 download; idempotent replay; underpayment guard; refund and
  dispute revocation; forged-signature rejection (400); download cap (429); expiry (410).

Evidence reports are written to `store/launch/checkout-proof.md` and
`store/launch/test-card-proof.md`. To run just one leg:

```bash
bash store_platform/scripts/prove_checkout.sh      # buy button only
bash store_platform/scripts/prove_money_path.sh    # fulfilment + negatives only
```

## Launch the full stack for hands-on browser testing

```bash
bash store_platform/scripts/run_test_stack.sh      # start
bash store_platform/scripts/stop_test_stack.sh     # stop
```

`run_test_stack.sh` starts `stripe listen` (forwarding real test webhooks), Store.Api on
**:5291**, and Store.Web on **:3000**, then prints the URLs. Open http://localhost:3000, buy a
pack with test card **4242 4242 4242 4242** (any future expiry, any CVC/postcode), watch the
webhook fire (`tail -f store_platform/.test-stack/stripe.log`), and confirm the download link.
Refund from the Stripe **test** dashboard to exercise revocation. Logs + PIDs live in the
gitignored `store_platform/.test-stack/`.

> **Stripe Tax.** Checkout enables Stripe Tax by default. A test account with no head-office
> address rejects it, so the test stack sets `Stripe__AutomaticTax=false`. For live, either
> configure tax in the Stripe dashboard or keep that flag set to `false`. See the config key
> `Stripe:AutomaticTax` in `StripeProvider.cs`.

## Catalogue / Stripe prices

The catalogue's per-pack Stripe price IDs are stored in `store.db`. If checkout fails with
`No such price`, the stored prices don't exist in the Stripe account your key points at —
reprovision fresh prices for the current account:

```bash
STRIPE_API_KEY="$STRIPE_TEST_SECRET_KEY" .venv/bin/python store_platform/scripts/reprovision_stripe.py --dry-run
STRIPE_API_KEY="$STRIPE_TEST_SECRET_KEY" .venv/bin/python store_platform/scripts/reprovision_stripe.py --force
```

## Going live

See **[GO_LIVE_RUNBOOK.md](GO_LIVE_RUNBOOK.md)**. In short: fill `.env.production` (template:
`.env.production.example`), run `scripts/go_live.sh`, register the live webhook, then prove
every path against the live key with `STRIPE_TEST_SECRET_KEY="$Stripe__ApiKey"
bash store_platform/scripts/prove_launch.sh` and do one real card purchase + refund.

## Unit tests

```bash
dotnet test store_platform/src/Store.Tests/Store.Tests.csproj    # 61 tests: payments, fulfilment, config gate, provider parity
```

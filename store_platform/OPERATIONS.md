# Store operations — what to run when

**Start here.** Everything below is a command, not a description. If you want the short version:

```bash
store_platform/scripts/storeops status     # is anything wrong right now?
store_platform/scripts/storeops list       # what else can I run?
```

This page exists because on 2026-07-31 a paid-without-delivery incident was diagnosed by hand —
paging a thousand Stripe sessions for a session id — when `reconcile_orders.py` already did the
whole job and was already wired into `verify_store.sh`. The tooling was fine. Finding it wasn't.

---

## Symptom → command

| Symptom | Run this | Green means |
|---|---|---|
| "Is anything broken right now?" | `storeops status` | daemon state + store sellable + every buyer delivered |
| "Can a stranger safely pay us?" | `storeops health` | every production gate verified (DNS, email, webhook, checkout mints) |
| "Did a buyer pay and get nothing?" | `storeops reconcile` | every paid Stripe session resolves to a downloadable order |
| "Did THIS purchase work?" | `storeops delivery --session cs_live_…` | bytes delivered, sha256 correct, zip intact |
| "…and did the refund revoke it?" | `storeops delivery --session cs_live_… --expect revoked` | order revoked + download 410s |
| "Did I break the money paths?" | `storeops money` | all money paths proven offline, no prod keys |
| "Stop the daemon touching prod" | `storeops pause` / `storeops resume` | — |
| "Ship the API" | **read `deploy/PROD_DEPLOY.md`** | — |

Add `--brief` to any of them for one line of output — that is how the Telegram bot calls them.

---

## The three traps

These are not style points. Each one has already produced a wrong conclusion.

### 1. `.env`'s `STRIPE_API_KEY` is a TEST key

Deliberate — the default should not be able to move real money. The consequence is that **every
live operation needs the live key**, and the scripts don't tell you; they just refuse, or worse,
skip.

`verify_store.sh` reads `${STRIPE_API_KEY}` first (`verify_store.sh:47`). With the repo default
it **SKIPped the webhook-registration check and the paid-vs-delivered reconcile** — the two
checks that actually speak to whether a buyer gets what they paid for — and could still exit 0.

`storeops` passes `STRIPE_LIVE_API_KEY` through for you. If you call the underlying scripts
directly, you must do it yourself:

```bash
python3 store_platform/scripts/reconcile_orders.py --stripe-key-var STRIPE_LIVE_API_KEY
```

### 2. Exit 3 is not exit 1

`verify_store.sh` distinguishes:

- `0` — checked, good
- `1` — checked, **broken**
- `3` — **could not check** (SKIP)

A SKIP folded into a PASS is a probe that green-lights on missing evidence. Never collapse them,
and never report the first SKIP as the cause of a failure — name the `FAIL` line instead.

### 3. `fly deploy` ships the working tree, not `HEAD`

With several agents editing this repo at once, deploying from a dirty tree ships someone else's
half-finished work. `predeploy_guard.sh` refuses if `store_platform/` is dirty. The procedure —
deploy from a clean detached worktree — is in `deploy/PROD_DEPLOY.md`. `storeops deploy` runs the
guard and points you there; it deliberately does **not** deploy, and refuses outright under
`--brief` so a production deploy is never one tap from a phone.

---

## Reading a `reconcile` result

```
PASS  1 delivered (order + active entitlement)
EXCUSED  cs_live_…   2026-07-31 internal delivery test, not a customer…
FAIL  PAID-WITHOUT-DELIVERY  cs_live_…  49.00 GBP  buyer@example.com  (store said 'unfulfilled')
```

- **PASS** — an Order exists with at least one active entitlement. That is the buyer-visible
  definition of delivered (`DeliveryEndpoints.cs:71-92`).
- **EXCUSED** — listed in `data/reconcile-exceptions.json` with a written reason. Printed on
  every run on purpose: an excused failure is still someone who paid and got nothing, and the
  moment it goes silent it stops being reviewed. Audit with `--no-exceptions`.
- **FAIL** — a real buyer is owed something. Refund them or fix fulfilment; do **not** add them
  to the exceptions ledger. The ledger is for orders that were never customers.

Not failures by design: sessions paid within the grace window (webhook still in flight) and
refunded/disputed charges (revocation is correct behaviour, `FulfilmentService.cs:151-154`).

---

## From the phone

Hermes routes these as Telegram verbs (`~/.hermes/hermes-agent/gateway/operator_shell/store_ops.py`),
each one shelling out to `storeops --brief`:

| Say | Runs |
|---|---|
| `store` / `store status` | `storeops --brief status` |
| `store health` / `can we take money` / `are we sellable` | `storeops --brief health` |
| `reconcile` / `buyers` / `paid without delivery` | `storeops --brief reconcile` |
| `store money` | `storeops --brief money` |

Read-only only. **`deploy` is not routed** — shipping production is a terminal action.
There is no `pause store` either: `store/scheduler/PAUSE` already answers to `pause prospector`,
and one switch must not have two names.

---

## Everything else in `scripts/`

Rarer or destructive enough that you should read the file's docstring first. `storeops list`
prints this too.

| Script | What it does |
|---|---|
| `provision_prices.py` | mint Stripe Product+Price for every listed pack, repoint prod |
| `reprovision_stripe.py` | re-point an existing catalogue at new Stripe objects |
| `create_probe_pack.py` | create/refresh the £1 delivery-probe pack |
| `build_probe_content.py` | build that pack's byte-deterministic deliverable |
| `sync_r2_content.py` | push published bundles to R2 (the store's real content source) |
| `sync_content_store.py` | same, for the local dev content store |
| `backfill_facets.py` / `backfill_pack_telemetry.py` | backfill fields onto older packs |
| `run_test_stack.sh` / `stop_test_stack.sh` | full storefront in Stripe TEST mode, for clicking |
| `prove_money_path.sh` | money path on test keys + throwaway db |
| `prove_checkout.sh` | the buy-button leg specifically |
| `prove_storefront.sh` / `prove_web.sh` | non-payment API / rendered UI |
| `prove_publish_loop.sh` | full publish loop, zero prod secrets |
| `smoke_checkout.sh` | mint one checkout session against a running stack |
| `predeploy_guard.sh` | refuse to deploy from a dirty `store_platform/` tree |
| `deploy_web.sh` | ship the storefront (the API is `deploy/PROD_DEPLOY.md`) |
| `go_live.sh`, `register_stripe_webhook.sh`, `setup_domain.sh`, `switch_domain.sh` | one-time infra |
| `check-support-mailbox.sh` | can support@ actually receive mail |

The `prove_*.sh` wrappers each drive a `prove_*.py` of the same name; run the `.sh`.
`prove_launch.sh` runs the family together — that is what `storeops money` calls.

---

## Older runbooks

These predate the current setup and are kept for history. **Prefer this page.**

- `deploy/PROD_DEPLOY.md` — **current**, the real deploy procedure
- `README.md`, `DELIVERY.md`, `GO_LIVE_RUNBOOK.md`, `LIVE_RAIL_SMOKE_TEST.md`,
  `STORY_PRODUCTION_READY.md`, `ACCOUNTS_RESTORE_PLAN.md`, `deploy/STAGING_PLAN.md` —
  current, narrower scope
- `docs/archive/2026-06/` — `DEPLOYMENT.md`, `GO_LIVE_SPEC.md`, `HANDOVER.md`,
  `HANDOVER_BRIDGE_TO_LAUNCH.md`. **Moved out of the repo root, not merely banner-warned.**
  They describe 11 listed packs (live: 42) and a store not yet taking real money (live since
  2026-07-30) — following them means operating on a store that no longer exists. A doc that
  opens "Executable, command-level steps to ship the storefront" reads as authoritative no
  matter what warning sits above it, so the fix was to move it. See `docs/archive/README.md`.

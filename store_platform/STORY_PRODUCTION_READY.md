# One-shot story: "A stranger can safely give us £49"

**Written 2026-07-30, from a live audit. Every claim below is either backed by a command run
tonight (marked LIVE), a file:line citation (marked CODE), or flagged HYPOTHESIS.**

> **As a buyer who has never heard of us**, I can find a pack on mumchimp.com, pay £49 by card,
> get my files immediately on screen **and** in my inbox, come back to them next week, and if I
> ask for my money back the refund both repays me and revokes my access — **while the operator**
> can prove every one of those steps with a command, and git can rebuild the exact code that
> took my money.

This is one story because production-readiness is one property: the paid path works and is
provable. Everything below is an acceptance criterion of this single story.

---

## Context: what is ALREADY PROVEN — do not redo

| Fact | Evidence (2026-07-30) |
|---|---|
| Storefront live, 4/4 Playwright smoke vs prod | LIVE: `WEB_BASE_URL=https://mumchimp.com npx playwright test` → 4 passed |
| API live, 15 packs | LIVE: `curl https://api.mumchimp.com/catalog` → 200, 15 items; fly health check on `/catalog` passing |
| Live checkout session creation works | LIVE: `POST /packs/a2c9948e0cc21cad/checkout` returned a `cs_live_…` URL, £49.00 GBP |
| success/cancel URLs correct | LIVE: session shows `success_url=https://mumchimp.com/orders/success?pack=…&session_id={CHECKOUT_SESSION_ID}`, `cancel_url=https://mumchimp.com/pack/…` |
| Stripe webhook registered & enabled, live mode | LIVE (queried from inside the API machine): `https://api.mumchimp.com/webhooks/stripe`, status enabled, events exactly `checkout.session.completed, charge.refunded, charge.dispute.created` — matches the handler set in `StripeProvider.cs:59-105` |
| support@mumchimp.com can RECEIVE mail | LIVE: `dig +short MX mumchimp.com` → `5 smtp.google.com.` (local + 8.8.8.8); `check-support-mailbox.sh --live` → OK, all legal pages show the address |
| Money secrets present in prod | LIVE: `fly secrets list -a prospector-store-api` shows Stripe key (live-mode confirmed from machine env), WebhookSecret, R2 quartet, both internal keys, STORE_STOREFRONT_URL, STORE_ALLOWED_ORIGIN, STORE_PUBLIC_URL |
| Money config is fail-closed at startup | CODE: `MoneyRailConfigGate.cs:37-107` throws on missing/placeholder money keys in Production |
| Fulfilment never drops paid money; idempotent; content snapshotted | CODE: `FulfilmentService.cs:26-29, 39, 63-64, 82-92, 101` |
| Refund/dispute revocation solid and idempotent | CODE: `StripeProvider.cs:86-109`, `WebhookEndpoints.cs:116-149`, `FulfilmentService.cs:140-170` |
| Test rails green | LIVE: `dotnet test src/Store.Tests` → 73/73; web "suspended" state is by design (`web.fly.toml:22-24`, auto-stop/auto-start, verified serving) |

## Context: the headline gap

**No real purchase has ever completed in live mode.** LIVE: `/v1/checkout/sessions?limit=30`
shows every session `payment_status: unpaid`; `/v1/charges` is empty. The entire paid half of
the journey — webhook delivery, fulfilment, entitlement, R2 presigned download, refund
revocation — has never executed in production. Until AC-1 passes, "ready for production" is
a HYPOTHESIS.

---

## Acceptance criteria (each one ends in a command, not a sentence)

### AC-1 — The £49 round trip happens for real *(P0, the proof that matters)*
Perform one real live purchase of any pack with a real card, then refund it from the Stripe
dashboard. All of the following must hold:

- [ ] Charge appears `paid: true` in live Stripe; amount 4900 GBP; statement descriptor suffix MUMCHIMP.
- [ ] Success page shows the download **within 40 s** (it polls 20×2 s — `orders/success.tsx:43-63`; slower than that is a FAIL, the page dead-ends).
- [ ] The zip downloads via the presigned R2 URL and its contents match the catalogue promise (all four advertised assets present; note `Marketing_Assets.md` is currently a 3-word stub in every zip — founder decision pending, see Non-goals).
- [ ] Webhook deliveries for `checkout.session.completed` and (after refunding) `charge.refunded` show **200** in the Stripe dashboard, and the API log shows the fulfilment + `Reversal … revoked` lines (`WebhookEndpoints.cs:138-140`).
- [ ] After refund, the order page returns **410 Gone** (`DeliveryEndpoints.cs:181-189`).
- [ ] The tax line on checkout is correct (AutomaticTax defaults ON — `StripeProvider.cs:216`; session creation succeeded tonight so config is at least self-consistent, but the buyer-visible amount is only provable at payment).

Probe: `bash store_platform/scripts/prove_launch.sh` first (local), then the live purchase.
The receipt is the Stripe charge id + refund id, pasted into this file under "Sign-off".

### AC-2 — The buyer gets an email, not just a tab *(P0)*
Today `POSTMARK_SERVER_TOKEN` is **absent from fly secrets** (LIVE) and mumchimp.com has
**zero TXT records** (LIVE: `dig +short TXT mumchimp.com` empty) — so no fulfilment email
sends, and no sender domain can even be verified. Close a browser tab and the purchase is
recoverable only through support. Done means:

- [ ] Postmark server created; sender signature/domain `orders@mumchimp.com` verified — this requires adding the SPF + DKIM TXT records Postmark specifies to the GoDaddy zone (MX for Google receiving already exists; do not touch it).
- [ ] `fly secrets set POSTMARK_SERVER_TOKEN=… POSTMARK_FROM_EMAIL=orders@mumchimp.com -a prospector-store-api` and machine restarted.
- [ ] Startup log no longer prints `DELIVERY-DEGRADED` (`MoneyRailConfigGate.cs:82-90`).
- [ ] AC-1's test purchase receives the email with a working order link (this orders AC-2 before AC-1, or do a second £49 round trip).
- [ ] DMARC updated from the GoDaddy default (`rua=mailto:dmarc_rua@onsecureserver.net`, LIVE) to a policy we monitor.

### AC-3 — git can rebuild the code that takes money *(P0)*
Prod runs uncommitted code: the whole Mumchimp rebrand, all of `Store.Api/**` money-path
changes, and new files (`DeliveryUrls.cs`, its tests, 6 scripts, `ACCOUNTS_RESTORE_PLAN.md`)
exist only in this working tree (LIVE: `git status`). `fly deploy` builds the **working
tree**, so any other session's half-edits ship silently (this happened on 2026-07-30).

- [ ] Everything under `store_platform/` committed and pushed (money-path files are founder-fence: Claude commits, does not delegate).
- [ ] Probe passes: `git status --porcelain -- store_platform | wc -l` → `0`.
- [ ] The deploy runbook gains the hard rule: a dirty `store_platform` tree aborts a deploy.

### AC-4 — a paid-but-unfulfilled buyer sets off an alarm, not a log line *(P1)*
`PAID-WITHOUT-FULFILMENT` and `FULFILMENT-EMAIL-FAILED` are ERROR log lines nobody watches
(`WebhookEndpoints.cs:71-75, 210-220`); email sends are single-attempt. Done means:

- [ ] A daily reconcile probe: live Stripe paid sessions vs the Orders table; any paid-without-order or order-without-entitlement is a FAIL line (script + cron/launchd, pattern of `check-support-mailbox.sh`).
- [ ] The probe is wired into `verify_store.sh` (AC-7).

### AC-5 — the money rail fails closed, not quietly *(P1 — all CODE-cited, small diffs)*
- [ ] `Stripe:ApiKey` checked at startup by `MoneyRailConfigGate` incl. `sk_live_`/`sk_test_` shape — today it is read lazily at first checkout (`StripeProvider.cs:260-274`), so a bad key = buyer-facing 500.
- [ ] Production startup **fails** when both `STORE_STOREFRONT_URL` and `STORE_ALLOWED_ORIGIN` are unset (today: CRITICAL log, then redirects buyers to a 404 on the API host — `MoneyRailConfigGate.cs:95-106`, `Program.cs:420-425`).
- [ ] Webhook for an unregistered provider returns **503 + ERROR log**, not silent 404 (`WebhookEndpoints.cs:34-37`).
- [ ] `WebhookEvent` saved **before** `FulfilAsync` to close the dedup race window (`WebhookEndpoints.cs:94-111` vs `FulfilmentService.cs:114-129`).
- [ ] Partial R2 config fails startup instead of silently returning 503 downloads (`R2StorageBridge.cs:22-38`).
- [ ] All covered by new Store.Tests; suite stays green.

### AC-6 — the quality gates actually gate *(P1)*
- [ ] `scripts/check-conformance.mjs` exists (or is removed from the `verify` chain) — today `npm run verify` cannot pass (`package.json:14-15`).
- [ ] CI `nextjs` job runs typecheck + lint + Playwright e2e, not just `build` (`.github/workflows/ci.yml:101-127`).
- [ ] `provision_prices.py` API base comes from env, not the hardcoded `https://api.mumchimp.com` (`provision_prices.py:36`).
- [ ] `popdd_verify.py` records **failing test names**, not only counts (the 517/518 flake of 2026-07-29 is currently unattributable).
- [ ] `check-support-mailbox.sh` fails closed when probing a non-default domain without env set (`check-support-mailbox.sh:16-18`).

### AC-7 — "is the store production-ready?" is a command *(P1, the standing probe)*
- [ ] `store_platform/scripts/verify_store.sh`: read-only, prints PASS/FAIL for — web 200 + Playwright smoke, `/catalog` 200 with ≥1 pack, checkout session mints (`cs_live_`), webhook registered+enabled with the 3 events, MX present, SPF/DKIM present, Postmark configured (via startup-log or a `/internal` config-status check), `git status` clean on `store_platform`, reconcile (AC-4) clean. Exit 0 = sellable.
- [ ] Registered as this project's `.state-probe` so every session starts from verified state, per the estate rule.

## Non-goals of this story (tracked, deliberately out)
- Accounts/social login (`ACCOUNTS_RESTORE_PLAN.md`, ~6 days) — guest checkout is the model.
- The `Marketing_Assets.md` stub / product-vs-brief founder decision — content, not rail.
- Engine-side carryovers: `confidence_floor` → `kill_filter.is_hard_fail`; DiskCache `web_calls` on cache hits.
- Web cold starts (`min_machines_running = 0`) — accepted cost profile for now.

## Sign-off
Story is DONE when `verify_store.sh` exits 0 **and** the AC-1 receipt (charge id + refund id +
email screenshot) is pasted here. Until both, the honest status is NOT READY.

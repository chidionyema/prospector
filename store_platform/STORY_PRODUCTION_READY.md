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

- [x] `store_platform/scripts/reconcile_orders.py` — Stripe paid sessions vs `/api/orders/by-session/{id}`, which reports `ready` only when an Order exists **and** has an active entitlement (`DeliveryEndpoints.cs:71-92`), i.e. the buyer-visible definition of delivered. Two states are deliberately not failures: sessions inside `--grace-minutes` (default 15; the webhook is normally in flight for seconds, and alarming there would cry wolf on every real sale) and refunded/disputed charges (revocation is the intended outcome, `FulfilmentService.cs:151-154`). Refuses a TEST key against the live store unless `--allow-test-mode`: test sessions can never resolve there, so every row would read as a catastrophic outage that is really the wrong Stripe account. Proven on both paths — default exits 2, opt-in found a real `cs_test_a17jf1…` paid-without-delivery. Committed `6d2783f`.
- [x] Wired into `verify_store.sh` (AC-7) as check 9. **Not yet on a cron/launchd schedule** — deliberately: the only Stripe key on this machine is a test key, so a scheduled run would either be meaningless or need `--allow-test-mode` baked in, which is exactly the false-green this AC exists to prevent. Schedule it once the live key lands with AC-1.

### AC-5 — the money rail fails closed, not quietly *(P1 — all CODE-cited, small diffs)*
- [x] `Stripe:ApiKey` **shape** checked at startup by `GuardStripeApiKeyShape` (`MoneyRailConfigGate.cs:78`). Note the original premise was half-stale: *presence* was already enforced via `RequiredKeys` (`MoneyRailConfigGate.cs:34`); what was missing was the shape, so a present-but-malformed key still 500'd the first buyer. Accepts `sk_`/`rk_` × `live_`/`test_`. A test-mode key in Production logs `MONEY-RAIL-TEST-MODE` but does **not** throw — staging deliberately runs `ASPNETCORE_ENVIRONMENT=Production` with test secrets (`deploy/fly/api.staging.fly.toml:17-18`), so throwing would make staging unbootable.
- [x] Production startup **fails** when both `STORE_STOREFRONT_URL` and `STORE_ALLOWED_ORIGIN` are unset — `GuardStorefrontUrl` (`MoneyRailConfigGate.cs:117`). The old non-fatal `DELIVERY-DEGRADED` branch was removed, not left alongside.
- [x] Webhook for an unregistered provider returns **503 + `WEBHOOK-PROVIDER-UNKNOWN` ERROR log** — `UnknownProvider` (`WebhookEndpoints.cs:94`). 503 also makes the provider retry rather than treat the endpoint as permanently gone.
- [x] Partial R2 config fails startup — `GuardR2Config` (`MoneyRailConfigGate.cs:147`). All-four-or-none: none is legitimate (packs register UNLISTED, nothing sells undeliverably), partial is never intentional and leaves already-listed packs sellable while downloads 503.
- [x] Covered by 18 new `MoneyRailConfigGateTests`; suite **91/91** (was 73/73 — count grew by exactly the new tests).
- [x] ~~`WebhookEvent` saved **before** `FulfilAsync`~~ — **REJECTED, with reason.** This AC would make the rail *less* safe. Today `RegisterWebhookEventAsync` only *stages* the row (`WebhookEndpoints.cs:102` `Add()`, no save); the WebhookEvent, Entitlements, Order and SalesAudit all commit in the **single** `SaveChangesAsync` at `FulfilmentService.cs:114`, and unique indexes on `SalesAudit(PaymentProvider, ProviderTransactionId)` and `WebhookEvent(Provider, ProviderEventId)` (`StoreDbContextModelSnapshot.cs:281-282, 314-315`) make a concurrent duplicate lose the race and get caught at `FulfilmentService.cs:116-128`. So the race is already closed, atomically. Saving the event first would **split that transaction in two**: if `FulfilAsync` then threw (R2 down, DB error), the event would be permanently recorded as processed, Stripe's retry would hit `WebhookAlreadyProcessedAsync` (`WebhookEndpoints.cs:164`), return `ALREADY_PROCESSED` 200, and the buyer would *never* be fulfilled — turning a recoverable error into a permanent silent `PAID-WITHOUT-FULFILMENT`. Falsifiable check if this is ever revisited: stage the split, force `FulfilAsync` to throw, redeliver the webhook, observe 200 + zero entitlements.

### AC-6 — the quality gates actually gate *(P1 — MOSTLY DONE, one part deliberately deferred)*
- [x] `conformance` removed from the `verify` chain. `scripts/check-conformance.mjs` **never existed** — no file, and no commit in `git log --all` ever added one — so `npm run verify` had never once passed. Nothing defined what "conformance" meant here, so the honest fix was to drop it rather than invent a check.
- [x] `provision_prices.py` API base now `STORE_API_BASE` env with the live default (`provision_prices.py:36`). Also fixed alongside: `ENV_PATH` was hardcoded to one developer's home directory, so the script only worked on one machine — now resolved relative to the file, verified to land on the repo `.env`.
- [x] `popdd_verify.py` records failing test **names**. Added `-rf` to force pytest's short-summary section, parse `FAILED|ERROR <nodeid>`, record them in the signed receipt as `failedTests` and print them. Proven with a deliberately failing probe test: `FAILED tests/test_zz_popdd_parse_probe.py::test_deliberate_failure_for_parser_probe` (probe removed afterwards).
- [x] `check-support-mailbox.sh` fails closed: `SUPPORT_DOMAIN` set to a non-default domain with `SITE_URL` unset now exits 2 instead of reporting on one domain's DNS while asserting against `mumchimp.com`'s pages. Verified — exit 2 on override, exit 0 on the default path.
- [x] CI `nextjs` job runs **typecheck** + build (was build only), and Node bumped `20` → `22` to match `engines.node >=22` — CI had been building on an unsupported runtime.
- [x] Playwright e2e added as a **separate `e2e-live-smoke` job**, main/`workflow_dispatch` only, not the PR gate. Reason: the specs assert the home page lists ≥1 pack (`e2e/storefront.spec.ts:13`), which needs a real seeded `Store.Api` catalogue — a bare PR build has an empty catalogue and would fail for reasons unrelated to the diff.
- [ ] **`lint` NOT yet in the CI gate — deferred, with reason.** `npm run lint` is currently **9 errors / 5 warnings** (was 12 errors; the 3 `no-explicit-any` in `lib/api/client.ts` are fixed). The remaining errors sit in `pages/pack/[id].tsx` (5: two `no-explicit-any`, one `no-restricted-syntax` for a direct `fetch`, two `Cannot create components during render`), `pages/orders/success.tsx` (2: `setState` synchronously within an effect) and `components/ui/Dropdown.tsx` (2). Wiring lint in before fixing those makes CI permanently red, and fixing them means restructuring **the buy button and the post-payment delivery poller** — the two files a first real sale depends on — at a moment when **no live purchase has ever completed** (see the headline gap). `[id].tsx:96-99` records that key-gating this file once caused a silent sales outage. The correct order is AC-1 first, then this refactor against a known-good baseline. Falsifiable check that it is safe to proceed: a passing AC-1 receipt plus `e2e-live-smoke` green.

### AC-7 — "is the store production-ready?" is a command *(P1, the standing probe)*
- [x] `store_platform/scripts/verify_store.sh` (committed `6d2783f`): read-only, prints PASS/FAIL for — web 200 + Playwright smoke, `/catalog` 200 with ≥1 pack, checkout session mints (`cs_live_`), webhook registered+enabled with the 3 events, MX present, SPF/DKIM present, Postmark configured (via startup-log or a `/internal` config-status check), `git status` clean on `store_platform`, reconcile (AC-4) clean. Exit 0 = sellable.
  Two design points worth keeping: **SKIP is never folded into PASS** — a check that could not run is not a check that passed, so exit 3 means "unproven" and is distinct from exit 0 "sellable"; and the checkout gate asserts **`cs_live_`** specifically, because a `cs_test_` session looks identical to a buyer, takes fake cards, and pays us nothing, so "a Stripe URL came back" is not proof of a live rail. Negative-tested: a bad `FLY_API_APP` yields SKIP not FAIL, and an unreachable API says "not serving" rather than "no packs".
  **Current verdict — `NOT SELLABLE`, exit 1, 4 failures** (after `6d2783f` cleared the dirty-tree gate): no SPF, no DKIM at `pm._domainkey`, DMARC still on the GoDaddy default `rua`, `POSTMARK_SERVER_TOKEN` absent from fly secrets. All four are AC-2's founder-hands work. The money rail itself is green: mints `cs_live_`, `/catalog` serves 15 packs, MX present, Playwright smoke passes against the live site.
- [x] Registered in `~/.claude/projects/-Users-chidionyema/.state-probe` as a `STORE_MONEY_RAIL` line. Appended, not substituted — the existing MX/SPF/storefront/descriptor checks were left intact, and only the two cheap non-duplicative facts were added (`cs_live_` mint + `store_platform` clean), because that file is re-billed on every request of every session and blocks the prompt at SessionStart. Live output: `STORE_MONEY_RAIL PASS:mints_cs_live_  git_store_platform=clean`.

## Non-goals of this story (tracked, deliberately out)
- Accounts/social login (`ACCOUNTS_RESTORE_PLAN.md`, ~6 days) — guest checkout is the model.
- The `Marketing_Assets.md` stub / product-vs-brief founder decision — content, not rail.
- Engine-side carryovers: `confidence_floor` → `kill_filter.is_hard_fail`; DiskCache `web_calls` on cache hits.
- Web cold starts (`min_machines_running = 0`) — accepted cost profile for now.

## Sign-off
Story is DONE when `verify_store.sh` exits 0 **and** the AC-1 receipt (charge id + refund id +
email screenshot) is pasted here. Until both, the honest status is NOT READY.

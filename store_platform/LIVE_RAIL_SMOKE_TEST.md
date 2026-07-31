# Live-rail smoke test — proving the checkout overlay without paying list price

## Why this exists

Every layer of the live payment rail can be proven by an API call except one: **whether the
embedded checkout overlay actually paints against the live publishable key.**

Two failure modes hide there and neither shows up in a status code:

- `loadStripe()` accepts a malformed publishable key. It fails only once Elements paints —
  i.e. after a buyer has clicked buy. (This is not hypothetical: `STRIPE_LIVE_PUBLISHABLE_KEY`
  in `.env` carried a trailing `=` and returned `401 Invalid API Key` from Stripe, while
  looking correct to every part of our code. See the `stripe-key-validity-probe` note.)
- `resolveStripeCheckout` falls back to hosted checkout only when the session **request**
  fails. A session that is created fine but renders wrong gets no fallback at all.

So the proof has to be a human watching it paint on the live storefront — which at £49 a pack
is a bill for looking at a form. This mechanism makes that render cost 50p.

## How it works

`POST /packs/{id}/checkout` accepts an `X-Smoke-Test-Key` header. When it matches the
server-side `Store:InternalApiKey`, every checkout line is repriced to
`Stripe:SmokeTestPriceId` before the session is opened. `PackId` is untouched, so entitlement
and fulfilment still resolve the real pack — the test exercises delivery too, not just render.

| Piece | Where |
| --- | --- |
| Decision logic | `src/Store.Api/Payments/SmokeTestPricing.cs` |
| Wiring into the endpoint | `src/Store.Api/Endpoints/CheckoutEndpoints.cs:139`, `:159` |
| Unit tests (15) | `src/Store.Tests/Payments/SmokeTestPricingTests.cs` |
| Pre-opening the overlay from a URL | `src/Store.Web/src/lib/preopenedCheckout.ts` |
| Its unit tests (16) | `src/Store.Web/src/lib/__tests__/preopenedCheckout.test.ts` |
| Driver script | `scripts/smoke_checkout.sh` |

### Why a buyer cannot reach the cheap price

These are properties of the code, each verifiable at the cited line:

1. **A present-but-wrong key is an error, never a discount and never a silent full-price
   sale.** `SmokeTestPricing.cs:82` returns `Unauthorized` → the endpoint answers `401` and no
   session is created (`CheckoutEndpoints.cs:174`). Falling through to the listed price would
   bill £49 for a mistyped test key; refusing is the deliberate choice.
2. **An unconfigured deployment fails closed.** `string.IsNullOrWhiteSpace(expectedKey)` is
   tested *before* the comparison (`SmokeTestPricing.cs:82`), so empty-equals-empty can never
   read as a match.
3. **Constant-time comparison over SHA-256 of both sides** (`SmokeTestPricing.cs:112`).
   Hashing first matters: `CryptographicOperations.FixedTimeEquals` returns immediately on a
   length mismatch, which leaks the key length. Equal-length digests remove that.
4. **The key never reaches the browser.** `Store:InternalApiKey` appears nowhere in
   `src/Store.Web/src` — the client bundle cannot produce it.
5. **Repricing preserves `PackId`**, so a smoke purchase grants the genuine pack and the
   fulfilment path is exercised rather than bypassed.
6. **Absent header = ordinary sale.** `SmokeTestPricing.cs:74` returns `NotRequested` with the
   lines untouched.

There is no enabled/disabled state to leave switched on — the override is request-scoped.

## Live configuration

Created in the LIVE Stripe account (`acct` fragment `51TjzYHPMafoirYB`):

```
product  prod_UzAUPk2Mq9Trp0   "ZZ SMOKE TEST — do not sell (live-rail render check)"
price    price_1TzCA2PMafoirYBFAXrIUDUs   unit_amount=50  currency=gbp  livemode=True  active=True
```

Bound to the API as a Fly secret (verified deployed, digest `ccdeabec8ea26ea0`):

```
flyctl secrets list -a prospector-store-api
  Stripe__SmokeTestPriceId  │ ccdeabec8ea26ea0 │ Deployed
```

## Running it

```bash
bash store_platform/scripts/smoke_checkout.sh f71ad0c4cf8b5344   # or omit the id for the first listed pack
```

The script requests the repriced embedded session, **reads the amount back from Stripe with
the secret key** (so the figure printed is Stripe's, not this repo's claim about itself), and
prints a pack URL that opens the overlay on that session.

Failure map:
- `401` — local `STORE_INTERNAL_API_KEY` does not match the deployed `Store__InternalApiKey`.
- `503` — `Stripe__SmokeTestPriceId` is not set on the API app.

Encoding is load-bearing: a live client secret contains literal `%2F`, which a browser decodes
to `/`, handing Stripe a different string than it issued. The script percent-escapes it
(`urllib.parse.quote(cs, safe="")`) and `preopenedCheckoutUrl` does the same with
`encodeURIComponent`. Both are covered by the round-trip test.

## What has been proven (2026-07-31)

**Gate behaviour, read back from Stripe rather than from our own API:**

| Request | Result |
| --- | --- |
| no header | `amount_total=4900 gbp`, `livemode=true` — ordinary sale, correct price |
| wrong key | `HTTP 401`, no session created |
| valid key | `amount_total=50 gbp`, `livemode=true` |

Session metadata on the repriced session confirmed fulfilment still resolves the real pack:
`{"pack_id": "f71ad0c4cf8b5344", "pack_ids": "f71ad0c4cf8b5344", "price_ids": "price_1TzCA2PMafoirYBFAXrIUDUs"}`.

**Unit tests:**

```
dotnet test src/Store.Tests/Store.Tests.csproj --filter 'FullyQualifiedName~SmokeTestPricing'
  Passed!  - Failed: 0, Passed: 15, Total: 15

npx vitest run src/lib/__tests__/preopenedCheckout.test.ts
  Test Files  1 passed (1)      Tests  16 passed (16)
```

**The render itself** — the thing this whole mechanism exists for. Headless Chromium against
the live pre-opened URL:

```json
{"dialog": true,
 "dialogLabel": "Checkout for NailDesk COSHH – …ready-to-print COSHH pack",
 "iframes": ["embedded-checkout :: https://js.stripe.com/v3/embedded-checkout-inner-…",
             "embedded-checkout-modals :: …", "__privateStripeController… "]}
```

The overlay paints: £0.50, pack title in the header, Card / Klarna / Revolut Pay / Onelink.
That is the live publishable key driving a live session through Stripe Elements.

## What this does NOT prove

- **The line-item text a real buyer sees.** The overlay shows the smoke product name,
  "ZZ SMOKE TEST — do not sell (live-rail render check)". Correct for a test, but it means the
  buyer-facing line item is the one element not exercised.
- **A completed payment.** Nothing above submits a card. Charge, webhook, entitlement, and
  download still need one real 50p purchase + refund (`GO_LIVE_RUNBOOK.md` step 4).
- **Express Checkout (Apple Pay / Link).** Stripe's
  `elements-inner-express-checkout-*.html` iframe repeatedly `ERR_ABORTED`s in the probe.
  HYPOTHESIS: headless Chromium has no Apple Pay, so Stripe tears the frame down; card and the
  other methods rendered fine. Unverified. The check that settles it: open the URL in a real
  browser and see whether an express-pay button appears above the divider.

## The overlay errored in the founder's Chrome — diagnosed, not our code (2026-07-31)

The render proof above is from **headless Chromium with no extensions**. In the founder's
normal Chrome window the overlay *opened* (so `preopenedClientSecret`, the panel mount and
Stripe.js all worked) but Stripe's own iframe then showed:

> Something went wrong — You might be having a network connection problem, the link might be
> expired, or the payment provider cannot be reached at the moment.

That copy is **not ours**: `grep "payment provider cannot be reached" store_platform/src`
returns nothing. It is Stripe's error UI, rendered inside their frame.

What that message is *not*: the session was verified `status=open`, `payment_status=unpaid`,
`amount_total=50 gbp`, `livemode=true`, `expires_at 2026-08-01T09:19Z` at the moment of the
failure. Not expired, not consumed.

### Diagnosed: the founder's Chrome cannot reach `api.stripe.com`

The browser console named the cause, four times:

```
api.stripe.com/v1/payment_pages/cs_live_a1mT6XtCEEHX…/init:1
  Failed to load resource: net::ERR_CERT_AUTHORITY_INVALID
embedded-checkout-inner-….html?publishableKey=pk_live_…:8
  Uncaught (in promise) FetchError
```

Chrome rejected the certificate chain for `api.stripe.com`, Stripe's frame could not fetch its
own session, and it rendered its generic "cannot be reached" copy. Everything upstream of that
request — our session, our bundle, `preopenedClientSecret`, Stripe.js, the panel mount — had
already worked.

**Evidence, gathered rather than assumed:**

| Probe | Result |
| --- | --- |
| Blocking matrix, real Chrome, clean profile: block `m.stripe.network` / `r.stripe.com` / `q.stripe.com` / `merchant-ui-api.stripe.com` | form still paints |
| …block `api.stripe.com` | `paidFormShown: false` — the only scenario matching the symptom |
| `openssl s_client api.stripe.com:443` | genuine `DigiCert Assured ID G2 TLS RSA4096 SHA256 2022 CA1` → `CN=api.stripe.com`, SAN `DNS:api.stripe.com` |
| `curl https://api.stripe.com/v1/charges` | `http=401 ssl_verify=0` — chain validates at the socket |
| `scutil --proxy`, Chrome `Preferences.proxy`, managed policy | none, none, none |
| Chrome `Local State.dns_over_https` | `null` — same resolver as the shell |
| Non-Apple roots in System keychain | mkcert, `local.ritualworks.com`, localhost, and a **SurfEasy IKEv2 chain** (leaf `C=IKEV2`) — a VPN endpoint identity, not a TLS-interception root, and not SSL-trusted |
| Fresh-profile Chrome (same binary, machine, network, same minute) fetching `api.stripe.com` from `mumchimp.com` | **ok** (opaque) |
| Founder's live Chrome, same fetch, same minute | **`TypeError: Failed to fetch`** |
| …same fetch to `api.mumchimp.com` | **ok** |
| `js.stripe.com/v3/` navigated in the founder's live Chrome | loads, full bundle |
| Copy of the founder's profile launched fresh, extensions **on** | `api.stripe.com` **ok** |
| …same copy, `--disable-extensions` | `api.stripe.com` **ok** |

**Conclusion.** The failure is scoped to the *running Chrome process*, and to the single host
`api.stripe.com`. It is not our code, not the session, not the storefront, not the network, not
an extension, and not the profile's on-disk state — a copy of that same profile reaches Stripe
fine with extensions enabled. `/Library/Keychains/System.keychain` was modified at
**08:52:36 today**, before the failing session was created (~09:19); a long-lived Chrome process
holding a stale view of the platform trust store fits every observation, though the causal link
is unproven because confirming it means restarting the founder's browser.

**Fix to try first: quit Chrome completely (⌘Q, not just the window) and reopen.** If it
recurs, capture the offending certificate — `chrome://net-export` ▸ record ▸ reproduce ▸ inspect
the `CERT_VERIFIER_JOB` entry — rather than re-running the probes above, which are already
answered.

### The gap it exposed, and the fix

`resolveStripeCheckout` only falls back to hosted checkout when the session *request* fails.
Here the request succeeded and the *render* failed, so there was no fallback at all: the buyer
saw Stripe's error with nowhere to go. That is now closed.

`EmbeddedCheckoutPanel` takes an `onUnreachable` callback and fires it on either of two
independent signals:

1. **Reachability probe** (`src/lib/stripeReachable.ts`) — a same-origin `no-cors` fetch to
   `api.stripe.com`. Resolve (opaque) = reachable; throw = not. This catches the case above,
   where Stripe's iframe *does* appear and then renders its own error.
2. **Mount deadline** — no `<iframe>` inside the panel within 12s. This catches the overlay
   never appearing at all: blocked frames, storage partitioning, an SDK that threw.

`handleEmbeddedUnreachable` (`src/pages/pack/[id].tsx`) closes the panel and redirects to a
freshly requested hosted session — fresh because an embedded session has no `url` to reuse. If
that request also fails, the buyer gets a visible error on the pack page rather than a frozen
overlay.

The probe deliberately **fails safe**: no fetch available, or any ambiguity, reports *reachable*.
A false "unreachable" would bounce a buyer out of a working overlay, which is worse than the bug.

Proven end-to-end against a real live session, local build carrying the live publishable key,
with our checkout API stubbed so no real session is created:

| Scenario | dialog | Stripe iframes | hosted session requested | handed off |
| --- | --- | --- | --- | --- |
| live session, Stripe reachable | **open** | 2 | 0 | **no** |
| same session, `api.stripe.com` blocked | closed | 0 | 1 | **yes** |

That is the control that matters: the fallback stays out of the way of a working overlay and
fires only when the overlay genuinely cannot work. Unit tests: `stripeReachable.test.ts` (5),
alongside `checkoutRoute.test.ts` and `preopenedCheckout.test.ts` — 26 passing; `tsc --noEmit`
clean; `npm run build` green.

**Honest limit:** if `api.stripe.com` is unreachable for the whole browser, Stripe's *hosted*
page may fail too — the handoff is not a guaranteed rescue for that specific cause. It is a
guaranteed rescue for the larger class of embedded-only failures (blocked iframes, partitioned
storage, SDK errors), and it turns a dead end into a different surface worth trying.

Two claims made earlier in this section's history were wrong and are retracted: extensions are
not implicated (proven above), and the extension-driven probe tab was **not** an unreliable
witness here — it was reproducing the genuine failure.

## Tooling caveat — prove the UI with Playwright, not the Chrome extension

`mcp__claude-in-chrome__javascript_tool` reported this page as completely dead:
`Object.keys(document.getElementById('__next'))` empty, `button.click()` inert. Both were
wrong — a headless Playwright run against the same URL returned `__reactContainer$…` and a
fully rendered overlay. (Its *absence of a dialog* was a true observation with a real cause;
see the section above. Only the hydration verdict was spurious.) Read rendered text with the
extension if you like; make any claim about React state, event handlers, or whether a component
mounted with a Playwright script run from `src/Store.Web` (its `node_modules` has
`@playwright/test`; a copy elsewhere will not resolve the import). Use
`waitUntil: 'domcontentloaded'` — Stripe's embedded checkout holds connections open, so
`networkidle` times out at 30s and looks like a page failure.

Two more traps found while diagnosing, both of which produced a confident wrong reading:

- **`fetch('https://js.stripe.com/v3/')` from a `mumchimp.com` page always throws**, in every
  profile. That is our own CSP — `connect-src` lists `'self'`, `api.mumchimp.com` and
  `api.stripe.com`, not `js.stripe.com` (`next.config.ts`). It is not a network fault.
- **Navigating to `https://api.stripe.com/v1/charges` shows a Chrome error page even when the
  connection is perfectly healthy** — Stripe answers `401` with a Basic-auth challenge, which
  Chrome renders as `ERR_INVALID_AUTH_CREDENTIALS`. Use a same-origin `fetch(..., {mode:'no-cors'})`
  and compare `opaque` vs throw; that is the probe that actually discriminates.

## Teardown

Nothing needs disabling in code. To retire the mechanism entirely:

1. `flyctl secrets unset Stripe__SmokeTestPriceId -a prospector-store-api` — the header then
   returns `503` and can never reprice.
2. Archive `price_1TzCA2PMafoirYBFAXrIUDUs` and `prod_UzAUPk2Mq9Trp0` in the Stripe dashboard.

Rotating `Store__InternalApiKey` also invalidates every existing smoke key.

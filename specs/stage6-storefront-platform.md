# Stage 6 — Storefront Spec (Paddle delivering-MoR; thin shop window)

**Status:** spec (manager-authored). **Supersedes the prior modular-monolith version of this file.**
**Author role:** manager (Claude). **Implements:** delegate (Gemini/DeepSeek) against this spec; the two money-adjacent slices (webhook signature verify, EngineBridge upload provenance) reviewed by Claude.
**Date:** 2026-06-15.

---

## 0. The decision that shaped this spec

We sell the £30 packs through a **delivering Merchant of Record: Paddle, from day one.** "Delivering" is the key word — Paddle does **not just take the money**, it also **hosts the paywalled download and emails it to the buyer**. (Verified 2026-06-15: Paddle's "Download" fulfilment method emails the customer a link to a file uploaded to Paddle, or a download URL you specify.)

A Merchant of Record is the **legal seller of record**: Paddle registers for and remits VAT/OSS and sales tax, holds the tax liability, runs PCI-compliant checkout, and owns fraud + chargebacks. This is why we picked it — EU digital VAT has **no threshold** (owed from sale #1 for a UK seller; verified via GOV.UK + OSS guidance), and a one-person shop should not be filing cross-border VAT returns. Fee: **~5% + 50¢ per sale** (≈£1.90 on a £30 pack).

**What choosing a *delivering* MoR deletes from the build** (this is the whole point — these were the heavy, liability-carrying parts):

| Previously planned | Why it's gone |
|--------------------|---------------|
| Payments module (lifted Stripe Checkout `mode=payment` + webhook) | Paddle hosts checkout and takes the card |
| Entitlements keystone (`OrderPaid → grant → outbox → issue download`) | Paddle gates the download to the buyer |
| SecureDelivery / Media (S3 presigned URLs + ClamAV) | Paddle serves the file; our packs are first-party (no user uploads → nothing to virus-scan) |
| Notifications email (receipt + download link) | Paddle emails the receipt and the download |
| Buyer Identity (accounts, login, refresh tokens, MFA) | Guest checkout on Paddle; no buyer accounts in v1 |
| Checkout saga (shipping-optional, skip-stock changes) | No checkout code at all on our side |
| Self-calculated tax (Stripe Tax) | Paddle owns the entire tax line |
| Admin ops surface (refunds, re-issue, disputes) | Handled in the **Paddle dashboard** for v1 |

**What we actually build** is a thin **shop window** plus the one integration that makes it self-stocking. That is the entire scope below.

---

## 1. What we are building

A small storefront that:

1. **Lists the £30 packs** the Prospector engine has passed — title, the "what's inside", price — as a browsable catalogue with our branding and the Stage-5 Monzo voice.
2. **Sends the buyer to Paddle to pay and download.** Each pack's **Buy** button opens that pack's Paddle checkout (overlay or hosted page). Paddle does payment → VAT → receipt → file delivery. The buyer never leaves a flow Paddle doesn't own after the click.
3. **Auto-stocks itself.** When Prospector emits a PASS, the pack is created in Paddle (product + price + uploaded files) and listed on the shop window with **zero manual steps** — the only net-new integration to the engine.
4. **Keeps our own sales log.** A Paddle webhook (`transaction.completed`) tells us a sale happened; we append it to an audit log so we own our numbers. This is **audit-only** — nothing the buyer depends on hangs off it (Paddle already delivered).

One seller (us), many buyers, one-off digital downloads. No marketplace, no accounts, no payouts, no physical goods, no self-hosted delivery.

The product being sold is defined by the **Stage-5 packaging spec**: each pack = three documents (Blueprint, Marketing plan, Build/Launch kit) as `.docx` + `.pdf`, plus a `QA.md` report. We deliver them as **one downloadable bundle** (a `.zip` of the 6 files) uploaded to Paddle.

---

## 2. Architecture — deliberately small

There is no commerce engine to build, so there is no modular-monolith commerce platform here. The store is **three pieces**:

```
[Shop window]  Next.js storefront — lists packs, Buy buttons → Paddle checkout
      │  (reads the catalogue)
[Catalog API]  small .NET service — pack metadata + listed/unlisted state + sales-audit log
      ▲                         ▲
      │ EngineBridge            │ Paddle webhook (transaction.completed → audit)
[Prospector PASS]          [Paddle]  ← payment, VAT, receipt, file delivery (NOT ours)
```

- **Shop window** (`Store.Web`) — lift the **Next.js 16 storefront skeleton** from `the-introduction-exchange/web/` (React 19 / TS / Tailwind, SSR). Strip its introductions-domain pages. Build: a catalogue listing page + a per-pack detail page, each Buy button wired to the pack's Paddle checkout via **Paddle.js** (`Paddle.Checkout.open({ items: [...] })`). No cart, no login, no account pages.
- **Catalog API** (`Store.Api` + a thin `Store.Catalog`) — a minimal .NET 9 service holding pack metadata (`{ id, title, one_line, price_gbp, paddle_product_id, paddle_price_id, listed, dossier_ref }`) and the append-only sales-audit log. This reuses the **intro-exchange skeleton shape + practices** (one `AppDbContext`, EF code-first, analyzer, conformance gate) but only one real domain entity. *Lighter alternative if even this is too much: the catalogue is a generated JSON the engine writes and the storefront reads statically — keep this in pocket if the .NET service earns its keep slowly. Default: the small .NET service, because the EngineBridge and webhook want a home.*
- **EngineBridge** — Prospector PASS → Paddle (create product + price, upload the pack `.zip`) → Catalog (`listed=true`). The only net-new code touching the engine (§4).

We deliberately **do not** stand up `Store.Identity`, `Store.Payments`, `Store.Fulfilment`, `Store.SecureDelivery`, `Store.Notifications`, or a checkout saga. Paddle is those.

---

## 3. What we reuse from the donors (much less than before)

Donor repos stay **untouched** (source libraries, never modified/deleted).

| Take | From | Notes |
|------|------|-------|
| Next.js storefront skeleton | `the-introduction-exchange/web/` | The shop window. Strip introductions pages; keep layout, Tailwind, SSR, conformance script. |
| Engineering practices | `the-introduction-exchange/dotnet/` | Analyzer (ban `NotImplementedException`), `TreatWarningsAsErrors`, money-rail PR checklist (for the webhook/price slices), deploy-log, war-room log, `STATUS.md`-from-code. |
| Money primitive | `the-introduction-exchange/dotnet/ENGINEERING_STANDARDS.md:7-13` | `Money` = `long` pence + banker's rounding — for the £30 price and the audit log. The only money math we keep (Paddle handles real settlement). |

**Not lifted (and not deleted — optionality preserved in the donors):** haworks Payments/Stripe, Media/SecureDelivery, Identity, Notifications, Orders saga, Payouts, Merchant/KYC, Location. A *delivering* MoR makes all of them unnecessary for this store. If a future product needs first-party payments/identity/delivery, that code is still in the donor repos and the module-library path (`specs/platform-modules.md`) is the way to harvest it — see §8.

---

## 4. Engine → store auto-listing contract (the one integration)

On `publish` (PASS only — CLAUDE.md "Publish only on PASS"), the engine hands the store:

```
PublishRequest {
  candidate_id, lane, title, one_line, price_gbp (= 30),
  pack_files: [ { kind: blueprint|marketing|buildkit|qa, format: docx|pdf|md, path } ],
  dossier_ref            # provenance: every figure traces here (source-or-die)
}
```

`EngineBridge` then:

1. **Bundle** the `pack_files` into one `.zip` (the deliverable).
2. **Create in Paddle** (Paddle API): a Product, a one-off Price (£30, `mode=payment` equivalent), and the **Download fulfilment** with the `.zip` uploaded (or a signed URL Paddle pulls from once at creation). Capture `paddle_product_id` + `paddle_price_id`.
3. **Create/flip Catalog** row `{ ..., paddle_product_id, paddle_price_id, listed=true }`.

**Boundary rules (unchanged truth invariants):**
- The store **consumes a PASS**; it never re-runs verification and never lists what the engine didn't pass. A KILL/DEFER never reaches the store (AGENTS.md §2.6, §2.3).
- **Source-or-die survives the MoR:** the `dossier_ref` rides along so every figure in a listed pack still traces to grounded evidence. The store displays packs; it never invents copy that isn't in the dossier/Stage-5 output.

---

## 5. The sales-audit webhook (audit-only)

Paddle → our endpoint on `transaction.completed`:

1. **Verify the Paddle webhook signature** before trusting the payload (Paddle signs with a secret; HMAC verify + timestamp tolerance). *Money-adjacent → Claude-reviewed slice.* Even though it's audit-only, an unverified write is a poisoned log.
2. Append `{ paddle_transaction_id, paddle_product_id, amount, currency, country, occurred_at }` to the append-only sales log.
3. That's it — **no entitlement to grant, no file to release, no email to send.** Paddle already delivered to the buyer. If our endpoint is down, we lose only a log row (re-fetchable from the Paddle dashboard/API), never a customer's purchase.

**Refunds/disputes:** handled in the Paddle dashboard. Optional: also log `transaction.refunded` for our own numbers. No revocation logic — there's no entitlement of ours to revoke.

---

## 6. Security & operations (right-sized to the smaller surface)

The big fenced items (buyer identity, money settlement, secure delivery) **left with the MoR**. What remains:

- **Webhook signature verification** — §5. The one place untrusted input hits our state. FENCED (Claude-reviewed).
- **EngineBridge upload provenance** — the bridge must upload the *correct* pack files for the *correct* candidate and never list a pack whose `dossier_ref` is missing. Source-or-die at the storefront boundary. FENCED (Claude-reviewed).
- **Secrets** — Paddle API key + webhook secret are infra secrets (env/Vault), never in code; enforced by the conformance gate + analyzer. Honours CLAUDE.md "no API-key calls beyond this repo" (these are store infra secrets, not engine LLM keys).
- **Admin** — Paddle dashboard for refunds/disputes/sales in v1 (so no admin auth/MFA to build). If we later want an in-house admin view, it reads the audit log read-only; revisit then.
- **Money as `long` pence; banker's rounding** for the £30 price + audit amounts. No `decimal`.
- **Analyzer + conformance gate + money-rail PR checklist** on the webhook and price/EngineBridge code.
- **Deploy-log discipline; `STATUS.md` from code.** A deploy isn't done until logged.
- **GDPR** — we hold almost no PII (Paddle holds the customer record). Our audit log keeps transaction id + country + amount, not buyer identity. Minimal surface by design.

---

## 7. Build plan (smallest-correct-first)

1. **Catalog API skeleton** — `Store.Api` + `Store.Catalog` from the intro-exchange shape; one `AppDbContext`; one Pack entity + sales-audit table; analyzer + CI gate ported. *(delegate)*
2. **Paddle account + a manual test product** — create one pack by hand in Paddle, confirm the Download fulfilment emails a working link end-to-end (TEST/sandbox). *(user + Claude — proves the MoR before we automate it)*
3. **EngineBridge** — `PublishRequest` → zip → Paddle create product/price/upload → Catalog `listed=true`. *(delegate; upload-provenance reviewed by Claude)*
4. **Sales-audit webhook** — verify signature → append log. *(FENCED slice — Claude implements/reviews verify; delegate the rest)*
5. **Shop window** — Next.js from intro-exchange `web/`; catalogue + detail pages; Paddle.js Buy buttons; Stage-5 voice/branding. *(delegate)*
6. **Deploy** — 1 app (api) + the web (static/SSR); deploy-log; smoke check a real sandbox purchase. *(delegate; review)*

Each phase gates on: build green, analyzer/conformance green, money-rail checklist filled for the two fenced slices.

---

## 8. Relationship to the module library (`specs/platform-modules.md`) — two tracks

The module library was written with **this store as its consumer #1**. The delivering-MoR decision **removes that justification**: the store no longer composes `Identity / Payments / SecureDelivery / Entitlements / Notifications` — Paddle is all of them.

**User decision (2026-06-15): build BOTH, as two independent tracks.**

- **Track 1 — this store.** Ships on Paddle, composes **none** of the modules, and **never waits on the library.** Everything in this spec is Track 1.
- **Track 2 — the module library** (`specs/platform-modules.md`). Built as a **standalone "harvest once, reuse forever" platform investment for future products**, NOT to serve this store. Its consumer is the *next* product that needs first-party payments/identity/delivery (or a deliberate move off a MoR).

**Independence is the whole point:** the store doesn't depend on the library (Paddle), and the library isn't justified by the store (future products). So neither blocks the other. **Recommended sequencing: ship Track 1 first** (it's days of work and it's the revenue path), then run Track 2 (delegating its non-fenced modules). The donor repos stay untouched for both.

---

## 9. Open questions / user actions

1. **Paddle account approval** — confirm Paddle accepts a UK solo seller for one-off digital downloads (standard case; verify at signup). No private-preview gating like Stripe Managed Payments had.
2. **Bundle format** — `.zip` of the 6 files (default) vs Paddle "License List" / per-file. Default `.zip`; confirm before phase 3.
3. **Catalog: .NET service vs generated JSON** — default the small .NET service (it homes EngineBridge + webhook); fall back to engine-written static JSON if the service doesn't earn its keep. Confirm before phase 1.
4. **Hosting** — one small app + the web. Fly.io (donor pattern) vs single VM vs static host for web + serverless webhook. Default: simplest that runs the webhook reliably; confirm before phase 6.

---

*Invariant check (AGENTS.md §2): the store consumes a PASS and never publishes what the engine didn't pass; source-or-die rides the `dossier_ref` to the listing; the one untrusted input (Paddle webhook) is signature-verified before it writes; the MoR carries tax + delivery + settlement, not the truth rules. The moat stays in the engine; the store just sells what the moat already earned.*

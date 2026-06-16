# Payment Rail Independence — Spec

**Status:** Draft for decision · **Date:** 2026-06-16 · **Owner:** founder (money-rail, stays on Claude)
**Goal:** Remove single-vendor dependence on Paddle for the Prospector store, reusing payment
infrastructure that already exists in `haworks-platform` and `the-introduction-exchange` (TIE).

---

## 0. TL;DR (read this first)

1. **The fulfilment half of our rail is already provider-agnostic.** `PaddleTransaction.cs` is
   literally documented as *"Provider-agnostic view of a completed payment."* Order → Entitlement
   → magic-link → presigned-R2 download never touches Paddle. The coupling is confined to the
   **payment-initiation half**: webhook route, signature verify, and product/price creation. So
   this is a **facade job, not a rewrite** (~2–3 dev-days for the seam + one provider).

2. **"Fallback" hides a fork in the road.** Paddle is a **Merchant of Record (MoR)** — it is the
   legal seller and remits UK/EU VAT for you. Both haworks and TIE use **Stripe-direct**, where
   **you become the merchant** and owe VAT yourself. You cannot transparently "fail over" between
   a MoR and a non-MoR rail — switching changes *who is legally selling and who remits tax*. The
   spec forces this decision rather than papering over it (§2, §8).

3. **What the sibling repos actually give us.** haworks has a **production-grade Stripe *Checkout
   Session*** service (the correct pattern for selling a fixed-price digital good) + refund saga +
   3-layer idempotency, all .NET 9 / tested / deploy-ready. TIE has an even more battle-hardened
   **Stripe wrapper** (idempotency filter, append-only ledger, boot-time money-rail config gate,
   reconciliation) but its escrow/PaymentIntent shape is wrong for a one-off digital sale. **Best
   plan: take haworks' Checkout Session as the spine, graft TIE's idempotency/ledger/config-gate
   hardening on top.** Neither has an entitlement layer or VAT — we already have the former.

4. **Seamless switching is in scope (§4d).** Because both providers register behind one seam and
   fulfil through one path, both rails run **concurrently**; switching which rail originates new
   checkouts is a **single hot-reloaded config flip — no redeploy, no downtime, no lost in-flight
   orders** — and automatic health-based failover is a +1d add. *The one asterisk:* the software
   switch is seamless, the **VAT/legal posture is not** (Paddle=MoR vs Stripe=you); §4d + §8 resolve it.

5. **Recommendation:** build the `IPaymentProvider` seam now (cheap, removes lock-in regardless of
   which way you jump), implement **Stripe-direct** as the second provider from haworks code, and
   make the MoR/VAT call explicitly (§8 gives you three honest options, with a recommendation).

---

## 1. Current state — exact coupling map

Canonical store: `prospector/store_platform` (the standalone `~/Documents/code/store_platform` is a
stale partial copy — no Store.Web, no Store.Tests, older migration; **ignore it**).

### 1a. What is already provider-agnostic (do not touch)
The entire post-payment funnel consumes the `PaddleTransaction` record, not raw Paddle JSON:

```
[provider] webhook → parse → PaddleTransaction record ──┐
                                                         ▼
   FulfilmentService.FulfilAsync(PaddleTransaction)  ← provider-agnostic from here down
     ├─ SalesAudit (idempotency key = txn id)
     ├─ Order (BuyerEmail, AmountPence, Currency, Country, Status)
     ├─ Entitlement (GrantToken, ContentKey snapshot)   ← our IP, neither sibling repo has this
     └─ SaveChangesAsync (atomic, all-or-nothing)
   DispatchEmailsAsync → Postmark magic link → /orders/{GrantToken}
   /download/{token} → presigned R2 URL (5-min TTL)
```

Already abstracted behind interfaces: `IEmailSender` (Postmark), `IContentStorage` (R2),
`ITokenGenerator`. **These are model citizens — reuse as-is.**

### 1b. Paddle-specific coupling points (the only things to abstract)

| # | Location | What's Paddle-specific |
|---|---|---|
| 1 | `Store.Api/Endpoints/WebhookEndpoints.cs:18` | Hard-wired route `POST /webhooks/paddle` |
| 2 | `WebhookEndpoints.cs:29,36,219-249` | `Paddle:WebhookSecret`, `Paddle-Signature` header, `VerifyPaddleSignature()` HMAC-SHA256 + ±5min replay window |
| 3 | `WebhookEndpoints.cs:64-75,144-172` | `ParsePaddleTransaction()` — Paddle JSON → `PaddleTransaction` record |
| 4 | `bridge.py:29-32,86-115,293-328` | `PaddleClient` (`create_product`/`create_price`), `PADDLE_API_KEY`, `PADDLE_ENVIRONMENT`; stub IDs `pro_stub_*`/`pri_stub_*` when no key |
| 5 | `Store.Catalog/Domain/Pack.cs:9-10` | `PaddleProductId`, `PaddlePriceId` columns |
| 6 | `Store.Catalog/Domain/Order.cs:13` | `PaddleTransactionId` (required) |
| 7 | `Store.Catalog/Domain/SalesAudit.cs:6-7` | `PaddleTransactionId`, `PaddleProductId` |
| 8 | `Store.Api/Contracts/PublishRequest.cs:8-9` | `PaddleProductId?`, `PaddlePriceId?` over the wire |
| 9 | `FulfilmentService.cs:50` | Pack lookup `p.PaddleProductId == item.ProductId` |
| 10 | `Store.Web/src/lib/paddle.ts`, `pages/pack/[id].tsx` | Frontend Paddle.js checkout |

**Difficulty: MEDIUM-LOW.** Items 1–3 are one provider class. Items 5–9 are a rename + one nullable
column (`PaymentProvider`). Item 4 is a Python interface + one Stripe client. Item 10 is the only
genuinely new UI surface (Stripe needs a checkout entry point; Paddle.js is an overlay).

---

> **DECISION (2026-06-16): Option B chosen** — Stripe-direct is the strategic primary rail (built
> from haworks Checkout Session + TIE hardening) with **Stripe Tax** for VAT calculation; the
> `IPaymentProvider` seam keeps **Paddle pluggable as a free fallback** (Option A is "free" given the
> seam). Operator accepts UK VAT + EU OSS registration/remittance as the cost of owning the rail.
> Implementation proceeds P0→P7 per §9.

## 2. The Merchant-of-Record decision (do not skip)

This is the prospector's own **legality** + **payer_solvency** filter applied to ourselves.

| Dimension | **Paddle (current)** | **Stripe-direct (haworks/TIE code)** |
|---|---|---|
| Legal seller | Paddle | **You / your company** |
| UK VAT (20%) | Paddle calculates **and remits** | You register, calculate, **remit** (Stripe Tax can calc; remittance is yours) |
| EU B2C digital VAT (OSS) | Paddle handles | **You** — *no threshold*; owed from the **first** EU sale |
| US sales tax nexus | Paddle handles | You (Stripe Tax can calc) |
| Chargebacks / disputes | Paddle absorbs workflow | Hit your Stripe account; you dispute |
| Fraud | Paddle | Stripe Radar (must enable/tune) |
| Fees (≈) | ~5% + 50¢ | ~1.5% EU/UK cards, ~2.9% + 20p intl |
| Hosted checkout | Yes (overlay) | Stripe Checkout Session = hosted page (still hosted, just a redirect) |
| PCI scope | None (Paddle) | Minimal with Checkout Session (Stripe-hosted card entry) |

**Consequence:** A Stripe-direct rail is **cheaper and gives full control**, but it **transfers VAT/
MoR/chargeback liability to you**. For a solo operator selling £30 digital goods to a global
consumer audience, the EU "VAT from first sale" rule is the sharp edge. §8 gives three ways to
resolve this; you must pick one before code ships.

---

## 3. Asset inventory — what the sibling repos give us

> **SOURCE-CODEBASE DECISION (2026-06-16): extract from `haworks-platform`, NOT the haworks monolith.**
> There are two distinct "haworks" repos: the **monolith** (`chidionyema/haworks`, local dir
> `~/Documents/code/ritualworks`, solution `haworks.sln`, .NET Aspire) and the **platform**
> (`chidionyema/haworks-platform`, `~/Desktop/haworks-platform`, .NET 9 microservices). Founder
> directs: **use `haworks-platform`.** We extract *code/patterns* from its `Payments` service into
> our single Minimal-API store — we do **not** import its microservice topology (see Extraction
> Manifest §3a + topology risk §11.1).

### 3a. haworks-platform (`~/Desktop/haworks-platform`) — .NET 9 microservices
**Directly reusable, production-grade:**
- **`Payments` service** — Stripe **Checkout Session** create (`StripeCheckoutSessionService.CreateSessionAsync`),
  webhook ingest + verify (`WebhooksController`, `StripeWebhookProcessor` handles
  `checkout.session.completed`), **refund saga**, **3-layer idempotency**
  (Stripe idempotency key + MassTransit inbox dedup + DB unique catch), live **key rotation**.
- `Orders` (Created→Paid state machine), `Identity` (RS256 JWT, JWKS), `Pricing` (price rules +
  promo + a `TaxRate` table keyed on country/state — **manual rates, no Avalara/Stripe Tax**).
- Maturity: 159 test files (Testcontainers Postgres, Pact, arch tests, E2E saga), EF migrations,
  Fly.io deploy configs, Roslyn money-safety analyzers, `Payments:DemoMode` simulator.

**Gaps:** no entitlement/access-grant layer (we have ours); **no MoR/VAT** (manual `TaxRate` only).
**Caveat:** it's a *microservices* topology (MassTransit/RabbitMQ, Vault, per-service Fly apps).
We will **lift the Stripe Checkout + webhook + idempotency *code*, not the whole service mesh** —
our store is a single Minimal-API app and must stay that way.

#### Extraction Manifest — exactly which haworks-platform files to port (and what to drop)
**TAKE (port the logic into `Store.Api/Payments/`, rewired to call our `FulfilmentService` directly):**
| haworks-platform source | → our use | Adapt |
|---|---|---|
| `Payments.Infrastructure/Stripe/StripeCheckoutSessionService.cs` | `StripeProvider.CreateCheckoutAsync` / `CreateProductAsync` | keep Stripe API calls; drop MassTransit event-driven invocation |
| `Payments.Infrastructure/Stripe/StripeWebhookProcessor.cs` | `StripeProvider.VerifyAndParseAsync` (handle `checkout.session.completed` → our `PaymentTransaction`) | strip the `checkout.session.expired`/`subscription.*`/`invoice.*` branches we don't need |
| `Payments.Api/Controllers/WebhooksController.cs` (verify + ingest only) | our `/webhooks/stripe` route body | **DROP** the `PaymentWebhookValidatedEvent`→RabbitMQ outbox publish; call `FulfilmentService.FulfilAsync` inline like our Paddle path does today |
| `Payments.Infrastructure/Webhooks/WebhookIdempotencyGuard.cs` | per-`(provider,eventId)` dedup | back it with our `SalesAudit` unique index instead of its DB table if simpler |
| `Payments.Application/Common/IdempotencyKeyGenerator.cs` | `sha256(provider:eventId)` deterministic id | take verbatim |
| `StripeRefundService.cs` (optional, P-later) | refund support | optional; not needed for v1 launch |

**DROP entirely (do NOT bring into our store):** MassTransit consumers/sagas (`PaymentSessionRequestedConsumer`,
`PaymentWebhookValidatedConsumer`, `RefundSaga`, `CheckoutSaga`), RabbitMQ outbox, HashiCorp Vault,
per-service Fly configs, `Orders`/`CheckoutOrchestrator`/`Payouts`/`Merchant` services (we own
fulfilment via `FulfilmentService`), and the `Pricing` service's manual `TaxRate` table (we use
**Stripe Tax** per Option B instead).

### 3b. the-introduction-exchange (`~/Documents/code/the-introduction-exchange`) — .NET 9 modular monolith
**Reusable patterns (better-hardened than haworks in places):**
- `IPaymentGateway` + `StripePaymentGateway` — clean provider seam, full idempotency keys, Polly
  resilience (retry/circuit-breaker/rate-limiter), kill switch (`PauseMoneyMovement`).
- **`IdempotencyFilter.cs`** — Stripe-style HTTP idempotency (claim→execute→replay). Excellent.
- **`WebhookEvent` dedup** — DB dedup on EventId + unique-index race guard, fail-closed verify.
- **`LedgerEntry`** — append-only, double-entry, pence-based GBP ledger + reconciliation reports.
- **`MoneyRailConfigGate`** — boot-time validator (live-vs-test key isolation, webhook secret
  present, etc.) that refuses to start if misconfigured. **Borrow this pattern wholesale.**

**Not reusable:** escrow/bounty/Connect model is 3-party-introduction-specific; uses **PaymentIntents
(manual capture)** not Checkout Sessions — **wrong shape for a one-off fixed-price digital sale**.
No entitlement model, no VAT.

### 3c. Synthesis
> **Spine = haworks' Stripe *Checkout Session* + webhook processor** (right pattern for digital goods).
> **Hardening = TIE's `IdempotencyFilter`, `WebhookEvent` dedup, `MoneyRailConfigGate`, optional `LedgerEntry`.**
> **Entitlement/delivery = our existing `FulfilmentService` (unchanged).**
> Copy *code/patterns* into our single store app; do **not** import either repo's service topology.

---

## 4. Target architecture — the `IPaymentProvider` seam

### 4a. .NET interface (new — `Store.Api/Payments/IPaymentProvider.cs`)
```csharp
public interface IPaymentProvider
{
    string Name { get; }                       // "paddle" | "stripe"

    // Inbound: verify + parse a webhook into the existing provider-agnostic record.
    Task<WebhookVerifyResult> VerifyAndParseAsync(HttpRequest req, string rawBody, CancellationToken ct);

    // Outbound: provision a sellable product/price; called by the publish path.
    Task<ProviderProduct> CreateProductAsync(string title, long pricePence, string currency,
                                             IDictionary<string,string> metadata, CancellationToken ct);

    // Build the buyer-facing checkout entry (hosted page URL or client token).
    Task<CheckoutHandle> CreateCheckoutAsync(string providerPriceId, string? buyerEmail,
                                             string successUrl, string cancelUrl, CancellationToken ct);
}

public sealed record WebhookVerifyResult(bool Verified, PaymentTransaction? Transaction, string? Reason);
public sealed record ProviderProduct(string ProviderProductId, string ProviderPriceId);
public sealed record CheckoutHandle(string Url, string? ClientSecret);
```
- `PaymentTransaction` = today's `PaddleTransaction` **renamed** (rename the record + file; it is
  already provider-agnostic in content — only the name lies).
- Implementations: `PaddleProvider` (extract items 1–3 from `WebhookEndpoints.cs` verbatim),
  `StripeProvider` (port from haworks `StripeWebhookProcessor` + `StripeCheckoutSessionService`).

### 4b. Webhook routing
Replace the single `/webhooks/paddle` with provider-keyed routes resolved from DI:
```
POST /webhooks/{provider}   →  resolve IPaymentProvider by {provider}
                            →  VerifyAndParseAsync → FulfilmentService.FulfilAsync (unchanged)
```
Keep `/webhooks/paddle` as a permanent alias so live Paddle config keeps working through the cutover.

### 4c. Config-driven selection (no code change to swap — matches the engine's deterministic-on-config rule)
```yaml
# store config
payments:
  active_provider: paddle        # paddle | stripe
  enabled_providers: [paddle, stripe]
  stripe:   { mode: live, tax: stripe_tax }   # see §8
  paddle:   { environment: production }
```
A **`MoneyRailConfigGate`** (ported from TIE) validates at boot: active provider has a webhook
secret + API key, live/test keys aren't mixed, R2 + Postmark present — **refuse to start otherwise**.

### 4d. Seamless switching (explicit requirement)
Goal: flip between Paddle and our own (Stripe) rail **with no redeploy, no downtime, no lost orders**,
and ideally automatically when one rail fails. The seam above makes this cheap because **both
providers run concurrently** — they are just two `IPaymentProvider` registrations and two live
webhook routes. What "seamless" means concretely, and how each level is achieved:

| Level | Mechanism | Cost |
|---|---|---|
| **Both rails always live** | `enabled_providers: [paddle, stripe]` → both `/webhooks/{provider}` endpoints stay active and fulfil into the *same* `FulfilmentService`. A buyer mid-checkout on the old rail still completes after a switch. | Free with the seam |
| **Switch which rail *new* checkouts use** | `active_provider` is read **per request** from a hot-reloaded config (or a DB `PaymentSettings` row), not at boot. Pack page calls `CreateCheckoutAsync` on whatever is active *now*. Flip = one config write; in-flight orders unaffected. | +0.5d (hot-reload + admin toggle) |
| **Per-pack / per-region pinning** | Pack already carries `PaymentProvider`. Allow it to be set per pack (e.g. EU buyers → Paddle MoR; rest → Stripe), router honours the pack's value. | Free (column exists) |
| **Automatic failover** | A lightweight health probe (provider API reachable + recent webhook seen). On `active_provider` failing N checks, auto-flip to the healthy rail and alert. Mirrors the engine's own provider-health/circuit-breaker pattern (`verify.py` / non-critical chain) — reuse that mental model. | +1d (probe + breaker + alert) |

**Invariants that make switching safe:**
- **One fulfilment path.** Every provider parses into the *same* `PaymentTransaction` and calls the
  *same* `FulfilmentService` → identical Order/Entitlement/download regardless of rail. The buyer
  experience downstream of payment is byte-identical.
- **Idempotency is per-`(provider, txnId)`** (§5), so a switch can never double-grant or collide ids
  across rails.
- **No webhook is ever turned off during a switch.** You change which rail *originates* checkouts,
  never which rail is *allowed to fulfil*. Late webhooks from the previous rail still land.

> ⚠️ **The one thing that is NOT seamless — and cannot be made so — is the tax/legal identity.**
> Switching from Paddle (MoR) to Stripe-direct changes *who is the legal seller and who remits VAT*
> mid-stream. The **software** switch is seamless; the **compliance posture** is not. Two clean ways
> to keep even that seamless: (i) choose §8 Option **C** (both rails are MoR → no posture change on
> switch), or (ii) accept §8 Option **B** and treat Paddle-mode sales and Stripe-mode sales as two
> tax streams in your books (the `PaymentProvider` column already partitions them for accounting).
> This is the only place "seamless" has an asterisk — flagged here so it's a decision, not a surprise.

---

## 5. Data model — provider-neutralisation (one migration)

Additive + rename, backward-compatible. EF migration on `Store.Catalog`:

| Entity | Change |
|---|---|
| `Pack` | Add `PaymentProvider` (string, default `"paddle"`). Rename `PaddleProductId`→`ProviderProductId`, `PaddlePriceId`→`ProviderPriceId` (keep semantics; column rename only). |
| `Order` | Rename `PaddleTransactionId`→`ProviderTransactionId`; add `PaymentProvider`. |
| `SalesAudit` | Rename `PaddleTransactionId`→`ProviderTransactionId`, `PaddleProductId`→`ProviderProductId`; add `PaymentProvider`. Idempotency unique index becomes `(PaymentProvider, ProviderTransactionId)`. |
| `PublishRequest` | Rename DTO fields; bridge sends `payment_provider` + generic ids. |
| `FulfilmentService:50` | Lookup `p.ProviderProductId == item.ProductId && p.PaymentProvider == txn.Provider`. |

`PaymentTransaction` record gains a `Provider` field. **Existing 14 live packs**: data migration sets
`PaymentProvider="paddle"` for all current rows so nothing breaks. (Store DB is small / dev — a clean
re-publish is also acceptable; decide at implementation time.)

---

## 6. Python bridge changes (`prospector/bridge.py`)

Mirror the seam on the publish side:
```python
class ProductProvisioner(Protocol):
    def create_product(self, title, price_pence, currency, metadata) -> tuple[str, str]: ...  # (product_id, price_id)

class PaddleProvisioner(ProductProvisioner): ...   # = today's PaddleClient
class StripeProvisioner(ProductProvisioner):       # Stripe Product + Price API (one-off, fixed price)
    ...
```
- Select via config `payments.active_provider`; keep the **stub** path (no key → `prov_stub_*`) so
  offline/dev publish keeps working.
- `publish_pass` sends `payment_provider` + `provider_product_id`/`provider_price_id` (generic).
- **Founder fence:** this is money-rail code — Claude only; never delegated to DeepSeek/MiniMax.

---

## 7. Frontend (`Store.Web`)

- Today: Paddle.js overlay (`lib/paddle.ts`, `pages/pack/[id].tsx`).
- Add `lib/stripe.ts` + a `redirectToCheckout(provider, packId)` that, for Stripe, calls a new
  `POST /packs/{id}/checkout` → `CreateCheckoutAsync` → 302 to the Stripe-hosted Checkout page.
- The pack page picks the provider from the pack's `PaymentProvider` field. Keep Paddle path intact.
- This is the only net-new buyer-facing surface; everything post-payment (magic link, download) is
  shared.

---

## 8. VAT / Merchant-of-Record — three honest options (pick one)

**Option A — Keep Paddle as MoR; Stripe is break-glass only.**
Paddle stays primary; Stripe-direct exists behind the seam but is enabled only if Paddle is down/
deprecates us. *Accept* that while on Stripe you owe VAT for those sales. Simplest code, but the
"fallback" is a degraded legal mode you'd want to exit quickly. Good as a **lock-in insurance policy**.

**Option B — Go Stripe-direct primary + Stripe Tax for VAT.** ✅ *Recommended if the goal is to own
the rail and cut fees.*
Use haworks' Checkout Session + **Stripe Tax** (automatic VAT/sales-tax calculation at checkout).
You still **register and remit** (UK HMRC; EU OSS via one EU registration), but calculation/collection
is automated and fees drop from ~5% to ~1.5–2.9%. This is the path that **actually uses the sibling
code** the way you intended. Cost: you take on compliance ops (periodic filings).

**Option C — Add a *different* MoR provider as the true like-for-like fallback.**
If the real worry is "don't depend on one vendor" **without** taking on VAT, the clean answer is a
second **MoR** (Lemon Squeezy, Polar, FastSpring — all MoR like Paddle). Then failover is genuinely
transparent (neither charges you VAT liability). **But** this barely uses haworks/TIE (they're
Stripe-direct), so it contradicts the stated premise. List it for completeness.

> **Recommendation:** **B for the strategic rail** (own it, cheaper, uses the code you have), with the
> **seam built such that A is free** (Paddle stays pluggable as insurance). Revisit C only if you
> decide VAT ops are not worth owning. Either way, **build the abstraction first** — it's the part
> that removes the dependence and is independent of the MoR choice.

---

## 9. Phased implementation plan

| Phase | Deliverable | Touches | Est. |
|---|---|---|---|
| **P0** | **Seam, no behavior change.** Rename `PaddleTransaction`→`PaymentTransaction`(+`Provider`); extract `PaddleProvider : IPaymentProvider` from `WebhookEndpoints`; add `/webhooks/{provider}` + keep `/webhooks/paddle` alias; `MoneyRailConfigGate` (from TIE). All existing tests still green; Paddle still works. | store_platform (.NET) | 0.5–1d |
| **P1** | **Provider-neutral data model.** EF migration (renames + `PaymentProvider` col + composite idempotency index); set existing rows to `"paddle"`. | Store.Catalog | 0.5d |
| **P2** | **Stripe provider (.NET).** Port haworks `StripeCheckoutSessionService` + `StripeWebhookProcessor` (`checkout.session.completed`→`PaymentTransaction`); graft TIE `IdempotencyFilter` + `WebhookEvent` dedup. Unit + Testcontainers integration test of the webhook→fulfilment path (clone haworks/TIE tests). | Store.Api/Payments | 1–1.5d |
| **P3** | **Stripe provisioning (Python).** `StripeProvisioner` (Product+Price), config select, keep stub path. | bridge.py | 0.5d |
| **P4** | **Frontend checkout.** `POST /packs/{id}/checkout` + `lib/stripe.ts` redirect; provider-aware pack page. | Store.Web | 0.5–1d |
| **P5** | **VAT (per §8 choice).** If B: enable Stripe Tax, register UK + EU OSS, seed Tax config; add VAT line to `SalesAudit`/receipt. | config + ops | 0.5d code + ops |
| **P6** | **Cutover + parity.** Run both in sandbox; golden money-loop test (intent→webhook→entitlement→download) per provider; flip `active_provider`. | tests | 0.5d |
| **P7** | **Seamless switching (§4d).** Make `active_provider` hot-reloaded (config/DB row, not boot-bound) + admin toggle; per-pack provider honoured by router. *Optional* +1d: health probe + auto-failover + alert. | store_platform + admin | 0.5d (+1d auto-failover) |

**Total engineering: ~4.5–7 dev-days** for A/B (excludes VAT registration lead time, which is ops,
not code; includes seamless-switch P7 baseline, +1d if auto-failover).

---

## 10. Testing & safety gates (non-negotiable, money rail)

- **Port the money-loop E2E** from both repos: haworks `SagaFlowsTests`, TIE `MarketplaceJourneyTests`
  / `MoneyLoopSmokeTests` → our `Store.Tests/Fulfilment` already has `FulfilmentServiceTests`; add a
  **per-provider** webhook→entitlement→download test (Testcontainers Postgres + fake provider).
- **Idempotency test**: same webhook delivered twice → exactly one Order/Entitlement (we already have
  the `SalesAudit` unique guard; extend to `(provider, txnId)`).
- **Signature negative tests**: tampered body / stale timestamp / wrong secret → rejected, no fulfilment.
- **Config gate test**: boot with mixed live/test keys or missing secret → app refuses to start.
- **List-only-when-deliverable** invariant (existing `pack_validation` + `is_listed = uploaded and
  pack_complete`) is unaffected — keep it green.
- **Implementation workflow (set 2026-06-16)**: **Gemini implements each phase from this spec; Claude
  reviews every diff before it lands** (run-not-read: Claude runs the build + money-loop tests and
  reads the diff, not just trusts the report). No Fable escalation (not available). The founder fence
  is satisfied by the **mandatory Claude money-rail review gate**, not by Claude typing every line.
  DeepSeek/MiniMax never touch this (moat/money). Each phase: Gemini writes → tests green → Claude
  reviews diff → commit.

---

## 11. Risks & open questions

1. **Topology mismatch (biggest).** haworks Stripe code assumes MassTransit/RabbitMQ outbox + Vault.
   We must port the *logic* into our single Minimal-API app with direct EF writes (like our current
   `FulfilmentService`), **dropping the message bus**. Risk: copying coupling we don't want. Mitigation:
   port the Stripe HTTP calls + parsing only; reuse our existing atomic `SaveChangesAsync` path.
2. **VAT lead time.** UK VAT + EU OSS registration is weeks of ops, not code. If choosing B, start
   registration in parallel with P0–P4.
3. **Stripe Checkout UX vs Paddle overlay.** Stripe Checkout is a redirect (hosted page), Paddle is an
   in-page overlay. Minor UX delta; acceptable.
4. **Secrets.** New `STRIPE_API_KEY` + `STRIPE_WEBHOOK_SECRET` go **only** in chmod-600
   `~/.config/llm/secrets.sh` / store config — never committed (repo is public). Reuse the
   `MoneyRailConfigGate` to fail-closed if absent.
5. **Existing live packs.** 14 packs carry Paddle stub ids today (no real `PADDLE_API_KEY`). Cutover
   re-provisions them under the chosen provider; trivial via `publish_passes` re-run.
6. **Decision still owed:** §8 A vs B vs C. Recommendation = B with A kept free by the seam.

---

## 12. What to do next (proposed)
1. Founder picks §8 option (recommend **B**, seam keeps **A** free).
2. Implement **P0 + P1** (seam + migration) — pure refactor, zero behavior change, fully reversible.
   This *alone* removes the hard single-vendor dependence at the code level.
3. Then P2–P4 (Stripe provider) once the MoR/VAT decision is locked.

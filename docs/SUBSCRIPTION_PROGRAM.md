# Subscription & Commerce-Mode Programme — Design

> Status: **DESIGN, not built.** No engine or store code changed by this document.
> Companion specs: `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md` (the provider seam this extends),
> `docs/SITE_SPEC_PROGRAM.md` (the copy this must reconcile with),
> `docs/COMMERCIAL_READINESS_PROGRAM.md` (the yield baseline).
> Every number below carries the command or `file:line` that produced it. Measured 2026-08-15.

---

## 0. TL;DR

The founder asked for an end-to-end subscription model that sits beside the current payment
system, and for the site to support **direct-pay only / subscription only / both**, configurable,
working seamlessly end to end.

**The design in one paragraph.** Commerce mode becomes a config-declared switch (`direct` |
`subscription` | `both`) read at runtime by the API and mirrored to the web app, exactly the shape
`PAYMENT_RAIL_INDEPENDENCE_SPEC.md §4d` already established for swapping payment providers. A
subscription sells the **engine's ongoing verdict work** — an allowance of pack claims from the
catalogue, standing briefs the engine vets for you, and re-verification of what you own — never a
promised volume of new ideas. Everything a subscriber takes during a paid period is **theirs
forever**; cancelling stops new work and revokes nothing. That single decision is what lets the
brand survive the pivot, because the site's existing anti-subscription argument is built on
"yours forever" and "if you cancel, you keep nothing" (`PriceArgument.tsx`, ComparisonBlock rows).

**The three decisions only the founder can make** are in §13. The largest is not technical: the
storefront has taken **zero sales, ever** (§1.4), so this is revenue architecture designed on zero
demand evidence. §12 sequences the build so the first two phases are valuable in `direct` mode and
commit nothing.

**§15 is the exhaustive edge-case pass** — 61 cases across mode transitions, billing lifecycle,
claims, delivery, identity, briefs, money, ops and abuse. It is not an appendix: it found four
defects in §§3–4 as first drafted (an unspendable rung cap, a mode switch that confiscated paid-for
claims, an allowance derived from Stripe's period fields instead of a paid invoice, and plan terms
read live from config), all fixed above. **§16 summarises those four and the two cases it could not
close.**

---

## 1. Measured ground truth

Everything in this section was run on 2026-08-15. Nothing here is recalled.

### 1.1 What is live on the shelf

```
$ curl -s https://api.mumchimp.com/catalog        # the real route; /v1/catalog and /v1/listings 404
LIVE PACKS: 61
GBP pence  n=61 min=2999 median=4999 max=9999 SUM=346939 (= £3,469.39)
rung histogram: {2999: 14, 4999: 29, 7999: 10, 9999: 8}
packs WITH usd price: 0 of 61
market: {'uk': 48, 'us': 11, 'us-fl': 2}
```

**The entire shelf is worth £3,469.39.** That is the number any all-you-can-eat subscription is
arbitraging against, and it is why §3.3 exists.

Note: **0 of 61 packs carry a USD price**, though `config.yaml:1619 usd_rungs` is declared and
`Pack.PriceUsdCents` exists. US buyers (13 of 61 packs' markets) are therefore billed GBP today —
`CheckoutEndpoints.cs:183-191` falls back to GBP unless *every* pack in the basket has a USD price.
The founder decision "as a US buyer you want to be charged in USD" (`Pack.cs`, 2026-08-14) is
**declared but not in effect on the live shelf.** A subscription in USD inherits this gap.

### 1.2 Supply — the rate a subscription would be sold against

```
$ sqlite3 store/prospector.db "SELECT substr(created_at,1,7), COUNT(*) FROM dossiers
    WHERE decision='pass' GROUP BY 1"
2026-07|16      2026-08|56          (72 pass, 2124 kill, 45 defer; 0 tombstoned)
```

Daily, over the whole publishing history:

```
07-28:1  07-29:2  07-30:5  07-31:8  08-01:16  08-02:1  08-05:5  08-06:7  08-07:7
08-08:3  08-09:1  08-10:2  08-13:1  08-14:5   08-15:8
```

**Supply is bursty, not a rate.** 16 passes on one day, zero on five days (08-03, 08-04, 08-11,
08-12 absent entirely), one on three others. The ML audit of the same morning
(`docs/ML_OPPORTUNITY_AUDIT_2026-08-15.md`) measured the cause: pass rate is 6.66% and yield is
gated on *grounding coverage*, not idea quality — 35.2% of kills fire because evidence was too thin
to rule at all.

> **This is the single most important design input.** Any subscription whose promise is "N new
> opportunities a month" converts a fragile, evidence-limited supply into a contractual obligation,
> and then makes churn the reason to loosen the gates. `CLAUDE.md` forbids exactly that
> ("Two loops never merge... Demand never overrides truth"). §3.2 rejects the feed model on this
> evidence, not on taste.

### 1.3 Churn already happens on the supply side

`store/scheduler/pending_unlist.done.jsonl` — **15 packs retracted**, all on the incumbency gate.
Every one of the 72 passes carries a re-verification due date:

```
$ sqlite3 store/prospector.db "SELECT COUNT(*), SUM(reverify_due_at IS NOT NULL)
    FROM dossiers WHERE decision='pass'"
72|72
```

The ML audit separately measured **12.1% dead citation URLs** (285/2353). So the engine already
knows, on a schedule, when a pack's evidence rots or an incumbent arrives — and today that
knowledge is spent on delisting the pack and **never reaches the person who bought it**. That is
the unmonetised recurring event stream this design turns into a product (§3.4, "Watch").

### 1.4 Demand

**Zero.** No Orders, SalesAudits, or Entitlements rows have ever existed
(ML audit §1, re-confirmed: the store DB is `Data Source=store.db`, SQLite, `Program.cs:26-28`).
The storefront is live and has 61 packs on it.

### 1.5 The payment rail as it stands

| Fact | Receipt |
|---|---|
| Checkout is one-off only | `StripeProvider.cs:418` — `Mode = "payment",` |
| No subscription code exists | 19 files match `subscription\|recurring\|membership` in `store_platform/src`; **all are marketing copy or tests arguing against subscriptions** — none construct a Stripe Subscription, recurring Price, Customer, or billing portal session |
| Webhooks handled | `checkout.session.completed`, `charge.refunded`, `charge.dispute.created` (`StripeProvider.cs:67,105,115`); everything else returns `Ignored: true` at `:69` |
| Provider seam already exists | `Program.cs:103-104` — `AddKeyedScoped<IPaymentProvider>("paddle"/"stripe")` |
| Persistence | SQLite + EF Core migrations (`Store.Catalog/Migrations/`, latest `20260815132103_AddPendingDelivery`) |
| Money receipt idempotency | `SalesAudit` unique index on `(PaymentProvider, ProviderTransactionId)` (`StoreDbContext.cs:103-107`) |

### 1.6 Two prior beliefs that are now stale — both load-bearing

**(a) "The store is accountless."** It is not. A full ASP.NET Identity stack is built and routed:

```
POST /register  /login  /logout  /refresh  /verify-email  /resend-verification
     /forgot-password  /reset-password  /change-password
GET  /me   PUT /me   GET /sessions   DELETE /sessions/{familyId}
GET  /v1/auth/me/orders                    (AccountOrdersEndpoints.cs:36, RequireAuthorization)
GET  /challenge/{provider}  /callback  POST /exchange  /link/{provider}   (external OAuth)
```

Recurring billing **requires** an identity to renew against, and it already exists. This removes
what would otherwise have been the largest blocker. (Memory `project-store-auth-model-accountless.md`
predates this and is corrected by this document.)

**(b) `Entitlement` already has the primitives a subscription needs.**
`Store.Catalog/Domain/Entitlement.cs`:

```csharp
public long OrderId { get; set; }                    // <- the only thing welded to one-off purchase
public required string GrantToken { get; set; }      // opaque, non-enumerable, fixed-time compared
public EntitlementStatus Status { get; set; }        // Active | Revoked
public string? ContentKey { get; set; }              // snapshotted at purchase = deliver-as-sold
public int ContentVersion { get; set; }
public DateTime? ExpiresAt { get; set; }             // null = perpetual  <- already nullable
public int DownloadCount { get; set; }
```

`ExpiresAt` is already nullable and already enforced (`DeliveryEndpoints.cs:215-227` → 410 Gone).
`ContentKey` is already snapshotted so a republish never changes what a buyer holds. **The only
field that assumes one-off purchase is `OrderId`.** §6 makes it polymorphic — a small migration,
not a rewrite.

---

## 2. What a subscription can honestly sell here

Three candidate objects. Two are rejected on the evidence above.

### 2.1 Rejected — all-you-can-read catalogue access

£29/mo for the shelf. Rejected on arithmetic: the shelf is £3,469.39 (§1.1) and a buyer's job is
to find **one** idea. They subscribe, take what they want, and leave — structural churn of roughly
one period, with the entire shelf value discharged for one month's fee. It also contradicts
`pricing.tsx:237` outright with nothing gained.

### 2.2 Rejected — the idea feed ("N new vetted opportunities a month")

This is the obvious model and it is the dangerous one.

- **Supply cannot support the promise.** §1.2: zero passes on five of the last nineteen days.
- **It merges the two loops.** Once MRR depends on monthly volume, every month with three passes is
  a commercial emergency, and the only lever that moves volume is the kill gates. `CLAUDE.md`:
  *"Sales metrics (demand) tune what to offer; truth metrics veto what may ship. Demand never
  overrides truth."* A feed makes violating that rule the rational business response.
- **It is the exact thing the site argues against**, with a cited competitor price
  (`sources.ts:52-59` — Exploding Topics $39/$99/$249). Becoming it forfeits the argument.

### 2.3 Chosen — the engine's ongoing verdict work

Not inventory, not volume. Three things the engine already produces and currently discards or
cannot bill for:

1. **Claims** — an allowance to take packs from the catalogue that already exists. Always
   fulfillable, because it draws on the archive, not on next month's yield. **No supply promise.**
2. **Briefs** — questions the subscriber brings, run through the same six gates. The deliverable is
   a *decision with citations*, pass **or** kill. At a 6.66% pass rate this is the only promise the
   engine can actually keep, and it is native doctrine: *"A KILL with a cited reason is
   first-class."* Nobody else sells "we spent real evidence proving your idea is already dead, here
   is the citation" to a person about to spend a year on it.
3. **Watch** — re-verification of packs the subscriber owns. §1.3: the engine already computes this
   on a schedule for all 72 passes and throws the result away from the buyer's point of view.

**Why this passes the two-loops test by construction, not by discipline:**
a brief steers *generation* (explicitly permitted — "demand tunes what to offer") and enters the
engine as an ordinary signal carrying no priority; claims draw on the archive so no gate is under
volume pressure; watch is *powered by* the truth loop, so its commercial value rises when the gates
are strict. With 61 packs and a 1–3 claim allowance, a subscriber has 20+ periods of runway before
scarcity could ever create gate pressure.

---

## 3. The offer

### 3.1 The contract, stated the way this brand states things

> **What you get.** An allowance of packs from the catalogue, briefs the engine vets for you, and
> a warning when the evidence under something you own stops holding.
>
> **What is yours forever.** Everything delivered while you were paying. Cancel and you keep every
> pack and every brief you took. We stop working; we take nothing back.
>
> **What you do not get.** A promise of how many new opportunities we will publish next month. We
> publish what survives the gates, and some months that is few. You are not buying volume.
>
> **What we will not do.** Loosen a gate because you subscribed.

The middle two paragraphs are the product. The last is the one that makes it defensible.

### 3.2 Tiers

Config-declared, charm endings, GBP with a USD twin column — the same doctrine as
`config.yaml:1572 rungs` / `:1619 usd_rungs`, never a computed number.

| | **Watch** | **Brief** | **Desk** |
|---|---|---|---|
| Price | £4.99/mo · £49/yr | £49/mo · £490/yr | £149/mo · £1,490/yr |
| Pack claims / period | 0 | 1, **any rung** | 3, **any rung** |
| Briefs / period | 0 | 2 | 8 |
| Re-verification alerts | packs you own | everything you own | everything you own |
| Evidence bundle + CSV export | — | — | yes |
| Meaningful in mode | direct, both | all three | all three |

Annual is 10× monthly (two months free) — a discount, and the anti-arbitrage lever in §3.3.

**Why £49, and why claims are rung-agnostic.** This is a **revision made during the edge-case pass**
(§15.C-4); the first draft priced Brief at £39 with claims capped at the £29.99 rung, to anchor
against the competitor price the site already cites (`sources.ts:53` — Exploding Topics, `$39/month`).
The measured rung histogram kills that design: **only 14 of 61 live packs sit at £29.99** (§1.1).
At one claim a month, a Brief subscriber exhausts every pack they are allowed to claim in **14
months**, and from then on pays for an allowance they cannot spend unless new supply happens to
land on one rung. A cap that depends on the shape of future supply is the feed promise (§2.2)
smuggled back in through the pricing table.

Rung-agnostic claims at £49 fix it and simplify the whole system:

- **£49/mo is above the modal pack price of £49.99 by design** — near-identical, never cheaper. A
  subscriber never pays less for the pack itself than a direct buyer, so there is no discount
  channel and no cannibalisation to police. The briefs and watch are the added value, not a price cut.
- **The rung cap and its machinery disappear**, and with it the whole class of edge cases it
  generated: mid-period cap changes, claims against a pack whose price moved, and — most
  importantly — invariant **I4** (§4.2), which existed only because a rung cap could strand packs
  as unbuyable in `subscription` mode. Removing a fence by removing the thing that needed fencing
  is worth more than the £10 of price anchoring it costs.
- The high rungs become a **perceived-value gift** with a small real cost: 8 packs sit at £99.99,
  and a subscriber taking one is getting genuine upside on a £49 plan.

Marginal cost is irrelevant to any of this (the ML audit measured **$1.011 all-in per PASS**); the
price is set against the decision the buyer is making, which is whether to commit a year of their
life.

### 3.3 The arbitrage fence

Perpetual grants plus a claim allowance is an arbitrage unless bounded. Three bounds, now that the
rung cap is gone:

1. **Allowance per period.** Brief = 1 claim, Desk = 3. Unused claims **expire**; they never accrue,
   or a dormant subscriber banks the shelf and discharges it in one month.
2. **Plan price ≥ modal pack price.** £49 vs a £49.99 mode means subscribe-claim-cancel costs the
   same as simply buying the pack, so the loop is not worth running. Desk at £149 for 3 claims
   (up to £299.97 of shelf) **is** below direct — intentional for the high-intent buyer, and the
   trade the founder confirms in §13.3.
3. **Annual is the better deal**, pulling the committed buyer away from the monthly churn loop.

**No mixed payments and no claim top-ups in v1.** A part-subscription-part-card purchase is a new
money path on the rail and, with rung-agnostic claims, buys nothing.

### 3.4 Watch, concretely

The engine re-vets on `reverify_due_at` (§1.3). A watch event fires when, between two vettings of a
pack a subscriber owns, **a gate verdict changes** (most importantly `incumbency` — the gate that
retired all 15 retracted packs) or **cited sources die** (12.1% base rate). The email says which
check moved, quotes the old and new passage, and links the diff. Cost to produce: zero — the
re-vet already runs. This is the cheapest tier to build and the only one that requires an existing
pack sale to have a customer.

---

## 4. Commerce mode — the switch

### 4.1 Declaration

Store-side config (the store is .NET; `config.yaml` governs the engine, not the shelf):

```jsonc
"Commerce": {
  "Mode": "direct",                    // "direct" | "subscription" | "both"
  "OnModeExit": "serve_to_period_end", // "serve_to_period_end" | "cancel_at_period_end"
  "Plans": [ /* code, interval, pricePence, priceUsdCents, providerPriceId per provider+currency,
                packClaimsPerPeriod, maxClaimRungPence, briefsPerPeriod, watch, isAvailable */ ]
}
```

Exposed once, publicly, cached: **`GET /commerce`** → `{ mode, plans[], packsPurchasableDirectly }`.

### 4.2 The five invariants that make it seamless rather than cosmetic

**I1 — Mode governs offers, never obligations.**
Switching mode never invalidates a live checkout session, an active subscription, or an existing
entitlement. This is the same reasoning already written into `Pack.cs` for price changes
(`MinBillablePence` / `EffectiveFloorPence` — a drain expressed as data so there is no tick to
miss). `both → direct` keeps serving existing subscribers to period end; `direct → subscription`
keeps honouring the 24h tail of live one-off sessions. Mode changes what can be **newly bought**.

**I2 — Mode gates ACQUISITION, never CONSUMPTION — and the refusal is server-side.**
Two halves, and conflating them is the defect this invariant exists to prevent.

*Acquisition* endpoints are gated: `POST /packs/{id}/checkout` and `POST /checkout` return
**409 Conflict** in `subscription` mode; `POST /subscriptions/checkout` returns 409 in `direct`
mode. Hiding a button is not a fence — this codebase already has a recorded incident where
progressive disclosure made a guard test vacuous
(memory `progressive-disclosure-makes-a-guard-test-vacuous.md`). The UI reads `GET /commerce` to
decide what to render; the API refuses independently.

*Consumption* endpoints are **never** gated on mode: `POST /packs/{id}/claim`, `GET /download/{token}`,
brief submission, and the billing portal stay open for anyone with an active subscription or a live
entitlement, in every mode. A subscriber who paid for a period keeps spending that period's
allowance after the founder flips the shelf to `direct` — otherwise the flip silently confiscates
paid-for claims, which is I1 violated through the back door.

**Corollary — webhook handlers never read commerce mode at all.** A Stripe Checkout Session lives up
to 24h, so `checkout.session.completed` can legitimately arrive for a one-off sale after the shelf
moved to `subscription` mode. Consulting mode there would refuse a customer who has already been
charged. Mode is read at *offer* time and nowhere else.

**I3 — The web app reads mode at runtime; a switch needs no rebuild.**
`pricing.tsx:279` is already ISR with `revalidate: 300`, so a mode change propagates within five
minutes with no deploy. The mode-dependent copy strings currently sit as literals inside JSX
(`pricing.tsx:46, 159, 237`) — they move into a mode-keyed content module behind the existing
`useCopyVariant.ts` seam (`:41`). Server-side, the mode must be hot-reloadable
(`IOptionsMonitor<CommerceOptions>`, not a value captured at startup) or "configurable" silently
means "configurable with a restart".

**I4 — A pack is never listed in a mode where it cannot be obtained.**
The preflight already exists in exactly this shape: `Program.cs:657-669` refuses to list a pack
whose payment provider cannot bill its price. It gains one condition — in `subscription` mode, a
pack is listable only if some available plan can claim it.

Under the §3.2 revision claims are **rung-agnostic**, so every listed pack is claimable on every
claim-bearing plan and this invariant is *satisfied by construction rather than by enforcement*.
It stays written down because it is the thing that breaks the moment anyone reintroduces a rung
cap, a per-plan catalogue subset, or a category restriction — and it must then be re-checked on
mode change and on plan change, not only at publish time (§15.A-3).

**I5 — The fulfilment fence generalises rather than forking.**
Today: *deliver iff amount paid ≥ `EffectiveFloorMinorUnits(currency)`* (`FulfilmentService.cs:115-129`).
Adds, for a subscription grant: *deliver iff **a paid invoice covers the period this claim is drawn
against** and the claim is within that period's allowance*. Same refusal shape, same `unfulfilled`
routing (the `PendingDelivery` queue added by migration `20260815132103` — never a second delivery
path).

Note the wording: **allowance is authorised by a PAID INVOICE, never by Stripe's period fields.**
A subscription can sit in `past_due` with `current_period_end` already advanced, and reading the
period off the subscription object would hand out a free period to someone whose renewal failed
(§15.B-4).

### 4.3 Mode matrix

| Surface | `direct` | `subscription` | `both` |
|---|---|---|---|
| Pack page CTA | Buy £X | Claim with your plan / Choose a plan | Buy £X **or** claim with a plan |
| `POST /packs/{id}/checkout` (acquire) | 200 | **409** | 200 |
| `POST /subscriptions/checkout` (acquire) | **409** | 200 | 200 |
| `POST /packs/{id}/claim` (consume) | 200 if subscribed | 200 if subscribed | 200 if subscribed |
| `GET /download/{token}` (consume) | 200 | 200 | 200 |
| Webhooks | mode never read (I2 corollary) | never read | never read |
| `/pricing` copy | one-payment argument (today's) | plan comparison, perpetual-grant argument | both, reconciled (§9) |
| Existing subscribers when mode leaves | served to period end | n/a | served per `OnModeExit` (I1) |
| Live one-off session when mode leaves | n/a | honoured for its full 24h | honoured |

---

## 5. Lifecycle, end to end

```
BROWSE (anonymous, unchanged)
  └─ free sample, kill log, full pack pages — no account, no change in any mode

CHOOSE
  ├─ direct path:        POST /packs/{id}/checkout   → Stripe mode=payment       (today, unchanged)
  └─ subscription path:  POST /subscriptions/checkout → Stripe mode=subscription
                          requires an authenticated StoreUser — a recurring charge needs an
                          identity to renew against. One-off stays accountless. That asymmetry is
                          the honest line: a file you own needs no login; a relationship does.

ACTIVATE
  webhook customer.subscription.created + invoice.paid
    → Subscription row (Active, period start/end)  + SubscriptionInvoice row
    → allowance for period 1 is live
  Mailjet welcome mail (MailjetEmailSender.cs — already wired)

USE
  claim a pack   → allowance check → Entitlement{GrantSource=subscription, ExpiresAt=NULL}
                   → magic link, same GrantToken delivery as today, 5-min presign,
                     50-download cap (DeliveryEndpoints.cs:19,25)
  submit a brief → enters the engine as an ordinary signal, no priority
                   → decision delivered pass OR kill, with citations
  watch          → re-vet delta on an owned pack → email

RENEW
  invoice.paid → new SubscriptionInvoice, period rolls, allowance resets (does NOT accrue —
                 unused claims expire; otherwise a dormant subscriber banks the shelf)

FAIL
  invoice.payment_failed → Stripe Smart Retries → past_due → unpaid
    → NEW claims/briefs stop.  Already-granted entitlements are untouched. No clawback, ever.

CANCEL
  cancel_at_period_end → serve to period end → Expired
    → keeps every entitlement.  "We stop working; we take nothing back."

REFUND / DISPUTE
  a refunded invoice revokes only entitlements granted from THAT invoice — hence
  Entitlement.SourceInvoiceId (§6). A month-9 refund must not claw back a month-2 pack.
  Existing charge.refunded → revoke behaviour for one-off orders is unchanged.
```

---

## 6. Domain model — one migration

New entities (mirroring the existing `Order` / `SalesAudit` split: obligation vs money receipt):

```csharp
class Subscription {
  long Id;  string UserId;  string BuyerEmail;            // denormalised, as Order/Entitlement do
  string PaymentProvider;  string ProviderSubscriptionId; // UNIQUE together
  string ProviderCustomerId;  string PlanCode;  string Currency;
  SubscriptionStatus Status;                              // Active|PastDue|Canceled|Expired
  DateTime CurrentPeriodStart, CurrentPeriodEnd;  bool CancelAtPeriodEnd;  DateTime CreatedAt;
}

class SubscriptionInvoice {                               // the SalesAudit of the recurring rail
  long Id;  long SubscriptionId;
  string PaymentProvider;  string ProviderInvoiceId;      // UNIQUE together = idempotency,
                                                          // same pattern as SalesAudit's index
  long AmountMinorUnits;  string Currency;  string Country;
  DateTime PeriodStart, PeriodEnd;  InvoiceStatus Status;  DateTime OccurredAt;
}
```

`Entitlement` becomes source-polymorphic — **four fields, no behaviour lost**:

```csharp
  public long?   OrderId          { get; set; }   // was `long`, now nullable
  public long?   SubscriptionId   { get; set; }   // new
  public string  GrantSource      { get; set; }   // "order" | "subscription" | "founder"
  public long?   SourceInvoiceId  { get; set; }   // new — scopes a refund to its own period
  // DB CHECK: exactly one of (OrderId, SubscriptionId) is non-null.
```

Allowance accounting needs **no new table**: a period's usage is
`COUNT(Entitlement WHERE SubscriptionId=@id AND CreatedAt >= CurrentPeriodStart)`.

Preserved unchanged by this shape: deliver-as-sold (`ContentKey`/`ContentVersion` snapshot), the
opaque non-enumerable `GrantToken`, the 50-download cap, 5-minute presigned URLs, revoke-on-refund,
and the 410 on `ExpiresAt`.

---

## 7. Stripe mechanics

| Concern | Design |
|---|---|
| Objects | One Stripe **Customer** per `StoreUser` (created lazily at first subscription). One recurring **Price** per (plan × interval × currency) — a small fixed set, **not** per pack. `bridge.py` continues to mint one-off Prices per pack and must never mint recurring ones. |
| Checkout | `Mode = "subscription"` alongside the existing `Mode = "payment"` at `StripeProvider.cs:418`. Both live simultaneously in `both` mode. |
| New webhooks | `customer.subscription.created/updated/deleted`, `invoice.paid`, `invoice.payment_failed`, `invoice.refunded`. Registered in the same switch that currently returns `Ignored: true` at `:69`. |
| Idempotency | `(PaymentProvider, ProviderInvoiceId)` unique on `SubscriptionInvoice` — Stripe redelivers invoices, and this is the same guarantee `SalesAudit` already gives one-off charges (`StoreDbContext.cs:103-107`). Note the recorded trap: **Stripe idempotency keys expire at 24h; they are not dedup** (memory `idempotency-keys-expire-they-are-not-dedup`). The DB unique index is the real fence. |
| Dunning | Stripe Smart Retries, then `past_due` → `unpaid`. No custom retry logic. |
| Proration | **None.** Cancel-at-period-end only; no mid-period plan changes in v1. |
| Billing portal | Stripe Billing Portal session behind `RequireAuthorization` — no custom card UI, no PCI surface. |
| Currency | Plans carry `pricePence` **and** `priceUsdCents` as separate declared columns, never a conversion — identical reasoning to `Pack.PriceUsdCents` ("A SEPARATE COLUMN, NOT A CONVERSION"). Blocked by §1.1: no live pack has a USD price yet. |
| Provider neutrality | Everything above goes behind `IPaymentProvider` (`Program.cs:103-104`). Paddle is a Merchant of Record and would also solve §13.2 — do not hard-wire Stripe subscription types into `FulfilmentService`. |

---

## 8. Fences and failure modes

| Failure | Fence |
|---|---|
| Subscriber claims the whole shelf and cancels | Allowance per period (never accrues) + plan price ≥ modal pack price + annual pricing (§3.3) |
| Mode switch strands unbuyable packs on the shelf | I4 — extend the `IsListed` preflight at `Program.cs:657-669` |
| Mode switch orphans paying subscribers | I1 — mode governs offers, not obligations |
| UI hides a path but the API still honours it | I2 — 409 server-side, tested per mode |
| Refund claws back an old pack | `SourceInvoiceId` scopes revocation to its own period |
| Cancel silently deletes what someone paid for | Subscription grants are `ExpiresAt = NULL`, perpetual by construction |
| Churn pressure loosens a kill gate | Architectural: subscription data lives in the store DB; the engine has no read path to it. A brief enters as an ordinary signal. Golden-set discrimination remains the only ship gate. |
| A month with three passes breaks the promise | There is no volume promise (§3.1) |
| Engine outage during a paid period | Briefs queue and are honoured; the daemon's `PAUSE` and DEFER semantics already mean "come back to it", never "your idea is dead" |

This table is the summary. **§15 is the exhaustive pass** — 61 cases across nine categories, each
with the rule that settles it. §16 lists the four defects §15 found in this design and fixed, and
the two cases it could not close.

---

## 9. Copy reconciliation — mandatory, not cosmetic

The site currently argues **against** subscriptions in four places, carefully and with citations:

- `pricing.tsx:46` — *"One payment per pack, no subscription, 14 day money back."*
- `pricing.tsx:159` — under **"What you do not get"**: *"A subscription, dashboard, or seat. The pack is a file you own."*
- `pricing.tsx:237` — *"One payment per pack, no subscription."*
- `PriceArgument.tsx` `ComparisonBlock` — *"Why £X once, not another subscription"*, three rows:
  `You pay: every year, forever` / `once` · `You get: raw leads to vet yourself` / `one vetted opportunity` · **`If you cancel: you keep nothing` / `it was never a subscription`**

Shipping a subscription while that copy stands makes the site false about its own product — on the
page whose entire subject is what the price buys.

**The reconciliation, and why perpetual grants are load-bearing.** Two of the three comparison rows
survive untouched: we still sell answers rather than raw leads, and a pack bought outright is still
yours forever. The third row **inverts into our strongest claim**:

> `If you cancel:` &nbsp; *them:* you keep nothing &nbsp;·&nbsp; *us:* **you keep everything you took**

That is only writable because of the §3.1 decision. Per mode:

- **`direct`** — copy unchanged. It is true.
- **`both`** — the comparison narrows from *"not a subscription"* to *"not that kind of
  subscription"*. `pricing.tsx:159` loses the subscription clause (dashboard/seat stay true).
- **`subscription`** — every "no subscription" sentence must be gone, replaced by the
  perpetual-grant argument. Leaving one behind is a false claim to a paying buyer.

Constraints that still bind: Monzo register, no em-dashes (`feedback-copy-no-dashes`), the
`#what-you-do-not-get` anchor is part of the contract with `/how-it-works` and must not be renamed
(`pricing.tsx:144-146`), and prices are computed from the catalogue, never typed
(`noHardcodedPrice.test.ts`) — plan prices must come from `GET /commerce` for the same reason.

---

## 10. Metrics, and keeping the loops apart

New (demand loop, store DB only): MRR, active subscriptions, claim utilisation, brief throughput,
churn, refund rate, dunning recovery.

Unchanged (truth loop, engine only): golden-set discrimination, grounding integrity, pass rate,
`min_composite`.

**The fence is architectural, not procedural.** Data flows engine → store (via `bridge.py`) and
never store → engine. No subscription metric may appear in `config.yaml`, `kill_filter.py`,
`verify.py`, `score.py`, or any threshold. The one permitted coupling is a brief entering as a
signal, which is the same object an RSS item enters as and carries no priority. If a future change
needs a subscriber count on the engine side, that is the violation — refuse it there.

---

## 11. What this does **not** include

Deliberate v1 exclusions, each because it adds a money path or a promise we cannot keep: mixed
payments / claim top-ups; mid-period upgrades and proration; team seats; gift subscriptions;
usage-based billing; a free trial (no demand data, and trials on digital goods invite abuse before
the first genuine sale); any promise of publication volume.

---

## 12. Build sequence

| Phase | Scope | Commits us to | Value if we stop here |
|---|---|---|---|
| **P0** | Founder decisions (§13). No code. | nothing | — |
| **P1** | `GET /commerce`, mode honoured server-side across all three modes (I1, I2, I3), full 3×N mode test matrix. **Ship with `Mode=direct`: behaviour byte-identical to today.** | nothing | The switch exists and is proven. Real option value. |
| **P2** | `Entitlement` polymorphism migration + `SourceInvoiceId` (§6). Still `direct`. | nothing | Removes the only structural blocker; harmless alone. |
| **P3** | Stripe subscription objects, `mode=subscription` checkout, Customer, recurring Prices, the four new webhooks, `Subscription` + `SubscriptionInvoice`, billing portal. | the rail | Subscriptions can be sold. |
| **P4** | Claims: allowance accounting, fulfilment fence extension (I5), `IsListed` obtainability preflight (I4). | the offer | `subscription` and `both` modes are actually usable. |
| **P5** | Watch: re-vet delta events → Mailjet. Cheapest tier, engine side already computes it (§1.3). | — | Needs pack buyers to exist. |
| **P6** | Briefs: brief → signal, decision (pass **or** kill) delivered. | — | The differentiated tier. |
| **P7** | Mode-aware copy module (§9) + account/billing UI. | — | Required before any non-`direct` mode goes live. |

**P1 and P2 are worth doing regardless of whether a subscription ever ships** — P1 gives the
configurable commerce mode the founder asked for, P2 removes a structural weld. P3 onward is where
the bet is placed.

Testing gate: `PAYMENT_RAIL_INDEPENDENCE_SPEC.md §10` already sets the money-rail bar. Add to it —
every commerce surface tested in all three modes, and a test that asserts the API refuses a
disabled path with 409 **even when the UI would not show it** (I2).

---

## 13. Decisions only the founder can make

**13.1 — Do we build this before the first sale?**
The storefront has taken zero sales, ever (§1.4). A subscription is normally a *retention* product,
and there is nothing yet to retain. Two coherent positions: (a) ship P1+P2, sell one pack, then
decide — lowest risk, keeps the mode switch; (b) subscription-first as the launch bet, on the view
that recurring revenue is the actual business and one-off was the wrong opener. **My recommendation
is (a)**, because P1+P2 cost little and commit nothing, and because a first sale is the cheapest
demand evidence available. This is a judgement about the business, not about the code.

**13.2 — VAT and Merchant of Record. Blocking.**
Recurring supply of digital services to consumers sharpens the place-of-supply question that
one-off sales already raise, and it compounds monthly. `PAYMENT_RAIL_INDEPENDENCE_SPEC.md §8`
already lays out three options. Paddle-as-MoR would settle it and the provider seam already
supports Paddle. **This must be answered before P3, not after.** I have not verified the current
tax setup and am not qualified to rule on it — flagging, not deciding.

**13.3 — Is Desk allowed to undercut direct pay?**
Desk at £99 covers 3 claims at any rung, up to £299.97 of shelf (§3.3). Brief is accretive; Desk is
deliberately not. Confirm that trade, or cap Desk claims at the £49.99 rung.

---

## 14. Open items I could not close

- **USD.** 0 of 61 live packs carry a USD price (§1.1), so the declared US-billed-in-USD decision is
  not in effect on the shelf. Subscription USD pricing inherits this. Separate from this programme
  but it lands in the same rail.
- **Tax.** §13.2 — unverified, deliberately.
- **`GET /commerce` caching.** ISR at 300s (`pricing.tsx:279`) means a mode switch takes up to five
  minutes to appear. Acceptable; stated so nobody reads it as a bug.
- **Auth at load.** The identity stack is built (§1.6a) but has never carried a real user. P3 is the
  first time it becomes load-bearing.

---

## 15. Edge cases — the full pass

Every row is *case → what breaks if built naively → the rule*. Rules marked **★** changed the design
above rather than being handled underneath it. Anything a rule cannot settle is escalated to §13.

### A. Commerce-mode transitions

**A-1. `both → direct` while subscribers are mid-period, with unused claims.**
Naive: the mode flip gates every subscription endpoint, and a subscriber who paid for three claims
and spent one loses two they already own.
**★ Rule (I2):** mode gates acquisition only. Claiming, downloading and briefing stay open for any
active subscription in any mode. `OnModeExit` decides whether the subscription renews, never
whether the paid period is served.

**A-2. One-off Stripe session completes after a flip to `subscription` mode.**
Sessions live up to 24h. Naive: the webhook handler checks mode and refuses, so a charged customer
gets nothing.
**★ Rule (I2 corollary):** webhook handlers never read commerce mode. Ever.

**A-3. `subscription → both` after packs were delisted for being unclaimable.**
Naive: the listability preflight runs at publish time, so packs delisted under the old mode stay
delisted and the shelf silently stays short.
**Rule:** listability is re-evaluated on **mode change and on plan change**, not only at publish.
Under rung-agnostic claims (§3.2) nothing is ever delisted for this reason, which is why the
revision was worth making; the sweep is required the moment any per-plan catalogue restriction
returns.

**A-4. Buyer holds an ISR-cached pack page from before the flip and clicks Buy.**
Naive: 409 renders as a generic "something went wrong", and the buyer leaves.
**Rule:** the 409 body carries a machine-readable `reason: "mode_disabled"`. The client re-fetches
`GET /commerce`, re-renders the correct CTA in place, and explains the change in one sentence.
Up to 300s of staleness is expected (`pricing.tsx:279`), not a bug.

**A-5. Subscription checkout session open when mode flips to `direct`.**
Naive: `customer.subscription.created` arrives and is rejected as impossible.
**Rule:** honour it (I1). A `Subscription` row existing in `direct` mode is legal and must be a
test case, not an assertion failure.

**A-6. Mode read once at process start.**
Naive: "configurable" requires a redeploy; the founder flips a value and nothing happens.
**★ Rule (I3):** `IOptionsMonitor<CommerceOptions>`, hot-reloaded. This estate has a recorded
incident of exactly this class — `settings-json-is-read-once-at-process-start`.

**A-7. `subscription` mode with no available plan** (all `isAvailable:false`, or plan prices not yet
minted at the provider). Nothing on the site is purchasable at all.
**Rule:** startup and `GET /commerce` refuse a mode with no viable purchase path — fail loudly at
boot, the same way `_build_operator` raises on a removed provider rather than silently building a
shorter chain.

### B. Billing lifecycle

**B-1. `invoice.paid` arrives before `customer.subscription.created`.**
Stripe does not guarantee ordering. Naive: FK insert fails, invoice is dropped, subscriber pays and
gets nothing.
**Rule:** both handlers upsert on `ProviderSubscriptionId`; neither assumes the other ran first.

**B-2. Duplicate or replayed webhook.**
**Rule:** unique `(PaymentProvider, ProviderInvoiceId)` on `SubscriptionInvoice`, mirroring
`SalesAudit`'s existing index (`StoreDbContext.cs:103-107`). The DB index is the fence — Stripe
idempotency keys expire at 24h and are not dedup (memory
`idempotency-keys-expire-they-are-not-dedup`).

**B-3. Out-of-order period rolls.** Period N+1's invoice arrives, then a retry of period N's.
Naive: the subscription's current period rolls backwards and the subscriber loses their allowance.
**Rule:** period advance is monotonic — only ever move `CurrentPeriodStart` forward.

**B-4. Renewal fails but Stripe has already advanced `current_period_end`.**
Naive: allowance is computed from the subscription's period fields and an unpaid subscriber gets a
free period.
**★ Rule (I5):** allowance is authorised by a **paid invoice**, never by period fields. Exactly one
allowance per paid invoice, deduped on `(SubscriptionId, PeriodStart)`.

**B-5. Dunning recovers after two weeks.** Did the subscriber lose that period?
**Rule:** falls out of B-4 with no special case — the invoice, once paid, grants its period's
allowance whenever it is paid. Nothing is lost and nothing is doubled.

**B-6. A £0 or credit-note invoice** (founder edits the subscription in the Stripe dashboard;
proration credits; a 100% coupon).
Naive: every `invoice.paid` grants an allowance, so dashboard edits mint free claims.
**Rule:** one allowance per distinct `PeriodStart`, not per invoice event. Amount is irrelevant; the
period is the key.

**B-7. Plan changed manually in the Stripe dashboard.** `customer.subscription.updated` carries a
price id we may not recognise.
**Rule:** re-resolve `PlanCode` from the price id. An **unknown price id alarms and freezes the
allowance** rather than silently retaining the old plan's terms. Money-rail silence is the failure
mode this estate has been bitten by repeatedly.

**B-8. Plan terms edited in config while people are subscribed** (claims 1→0, price change).
Naive: a config edit retroactively changes what someone already paid for.
**★ Rule:** plan terms are **snapshotted onto the `Subscription` row** at creation — the same
reasoning as `Entitlement.ContentKey` snapshotting for deliver-as-sold. `Plans` config governs new
subscriptions only. Stripe grandfathers the price automatically; we must grandfather the *terms* to
match.

**B-9. Partial refund of an invoice.**
**Rule:** partial refund revokes nothing. Only a full refund of an invoice revokes the entitlements
granted from that invoice. Threshold is stated in code, not inferred.

**B-10. Refund in month 9 clawing back a month-2 pack.**
**★ Rule:** `Entitlement.SourceInvoiceId` scopes revocation to its own invoice. Without that field
the naive query is "revoke everything for this subscription", which is theft.

**B-11. Chargeback on a subscription invoice.**
**Rule:** revoke that invoice's grants, set the subscription to a suspended state, and stop future
claims. A dispute is a fraud signal, not just a refund — unlike B-9.

**B-12. Subscriber relocates UK → US and wants USD.**
Stripe subscriptions are fixed-currency for life.
**Rule:** cannot change. Cancel and resubscribe. Stated in the FAQ rather than discovered at support
time. Compounded by §14: no live pack has a USD price yet.

**B-13. Subscription outlives the pack catalogue it was sold against** (mass retraction; §1.3 shows
15 retractions already happened). Allowance exists, nothing worth claiming.
**Rule:** unresolved by design — escalated to §13.4 as a credit/refund policy decision. The
mechanism (pause billing) is easy; the policy is the founder's.

### C. Claims and allowance

**C-1. Two concurrent claim requests for the last allowance slot.**
Naive: both read `count < allowance`, both insert, subscriber gets two packs for one slot.
**Rule:** the claim is a single serialisable transaction, plus a unique index on
`(SubscriptionId, PackId)` so the same pack can never be claimed twice regardless of races. SQLite
is single-writer, which makes this cheap here and must not be relied on if the store ever moves to
Postgres.

**C-2. Claiming a pack the subscriber already bought outright.**
Naive: burns a claim for a second copy of a file they own.
**Rule:** check for an existing Active entitlement first; return the existing grant and **consume no
allowance**. Applies across grant sources — direct purchase, earlier claim, founder grant.

**C-3. Pack is retracted between browse and claim.**
15 of 84 packs have been retracted (§1.3), so this is likely, not theoretical.
**Rule:** refuse the claim on `IsListed=false`, consume nothing, and say why in the buyer's language.

**C-4. Rung cap exhausts the claimable catalogue.**
At 1 claim/month capped to the £29.99 rung, and only 14 packs on that rung, a Brief subscriber runs
out in 14 months and thereafter pays for an unspendable allowance.
**★ Rule:** this is what removed the rung cap and repriced Brief to £49 (§3.2). It is listed here
because it is the case that caused a design change, and because it is the argument against
reintroducing any per-plan catalogue subset.

**C-5. Pack is retracted days after being claimed.**
The grant is perpetual, so the buyer keeps a file whose evidence we have since disowned.
**Rule:** they keep it — deliver-as-sold is absolute — **and Watch fires immediately** with the
reason. Additionally, a claim on a pack retracted within 14 days **restores the allowance slot**,
matching the 14-day refund policy already fenced for direct purchases.

**C-6. Unused claims at period end.** Expire, never accrue (§3.3) — otherwise a dormant subscriber
banks twelve claims and discharges a fifth of the shelf in one month.

**C-7. Watch-tier subscriber calls the claim endpoint.**
**Rule:** 403 with `reason: "plan_has_no_claims"`, not a generic error.

**C-8. Watch subscriber owns zero packs.** They are paying for monitoring of nothing.
**Rule:** the Watch plan cannot be purchased with no entitlements on the account; the checkout is
refused with an explanation. Selling a subscription that is structurally inert is the same defect
class as listing an undeliverable pack.

**C-9. Pack price rises between the claim request and the claim commit.**
**Rule:** rung-agnostic claims make price irrelevant to authorisation (§3.2). The claim records the
price at commit time for audit only. This is the second class of edge case the revision deleted
rather than handled.

### D. Entitlements and delivery

**D-1. Subscription grant must never expire.** `ExpiresAt = NULL` on every subscription-sourced
entitlement. A non-null value here silently converts "yours forever" into rented access and
falsifies §9's copy.

**D-2. Claim succeeds, delivery fails** (storage unreachable, missing `ContentKey`).
**Rule:** route into the existing `PendingDelivery` queue (migration `20260815132103`) and **do not
consume the allowance until an entitlement actually exists**. Never a second delivery path.

**D-3. Magic-link email silently not sent.** `Store.Api/Services/MailjetEmailSender.cs:68-72` returns **`false` without sending when
`IsConfigured` is false** (`:48-51`) — a silent no-op — a live trap for guest purchases today.
**Rule:** subscribers are authenticated, so `GET /v1/auth/me/orders` is a guaranteed recovery path.
Subscriptions are *safer* than guest checkout here, and the delivery UI must lean on the account
rather than the email.

**D-4. Pack republished with a new `ContentKey` after a claim.** Already solved: `ContentKey` is
snapshotted per entitlement (`Entitlement.cs`). No change needed — recorded so nobody "fixes" it.

**D-5. Download cap.** 50 per entitlement (`Store.Api/Endpoints/DeliveryEndpoints.cs:25`, `DefaultMaxDownloads = 50`) applies identically to
subscription grants. A subscriber is not entitled to redistribute.

**D-6. Presigned URL expiry.** 5 minutes (`Store.Api/Endpoints/DeliveryEndpoints.cs:19`, `DownloadUrlTtl`), unchanged. Note the recorded
trap that **local clock skew fakes a presign 403** — a support report of "expired link" may be the
buyer's clock.

### E. Identity

**E-1. Guest bought packs under email B, subscribes under email A.** Watch monitors nothing they own.
**Rule:** a verified "add another email" flow on the account, reusing the existing
verification machinery. Until it ships, state the limitation at checkout rather than letting a
subscriber discover it.

**E-2. Someone registers with a stranger's email to read their purchases.**
Already mitigated: order history requires `email_confirmed` (`AccountOrdersEndpoints.cs`).
**Rule:** the claim and watch paths must enforce the same confirmation gate — a fence that covers
one of three readers is not a fence.

**E-3. User changes their email (`PUT /me`).** Denormalised `BuyerEmail` copies go stale.
**Rule:** `UserId` is authoritative for subscriptions; `BuyerEmail` is for display and for matching
legacy guest orders only. Never key an allowance or an entitlement lookup on the mutable field.

**E-4. OAuth sign-in returns a different email than the purchase email.** Same as E-1; the account
linking already exists (`ExternalAuthEndpoints.cs` `/link/{provider}`).

**E-5. Account deletion / GDPR erasure with an active subscription.**
**Rule:** cancel at period end, anonymise the user, **retain `SalesAudit` and `SubscriptionInvoice`**
as financial records. Erasure of a payment record is not a right and is a legal exposure.
Retention policy needed before P3.

### F. Briefs and the engine

**F-1. Brief submitted while the daemon is paused or the moat is blind.**
**Rule:** queue it — the engine already persists failed signals to `signals/pending/` for
`generate --resume`. A brief must never silently vanish; the subscriber sees queue position.

**F-2. Brief returns DEFER, not a decision.** DEFER means "come back to it", which is not what was
sold.
**★ Rule:** **only a terminal decision (PASS or KILL) consumes a brief allowance.** A DEFER
re-queues at no cost. Charging for an unevaluated check would be the commercial version of the
2026-08-06 defect where an outage was recorded as a reasoned KILL.

**F-3. Brief duplicates an existing catalogue pack** (dedup fires).
**Rule:** return the existing pack and say so. It consumes the brief (real work was done) and the
pack is offered as a separate claim.

**F-4. Abusive, illegal or prompt-injecting brief text.**
**Rule:** the `legality` gate judges the *idea*, not the *input*. Input moderation is a separate
control at submission, before the text ever reaches generation. Treat brief text as untrusted user
content throughout.

**F-5. Brief spend competes with the daemon's own budget.** 8 briefs/period × N Desk subscribers all
draw on `spend.daily_cap_usd`, read from `store/prospector.jsonl`.
**★ Rule:** briefs need a **separate budget line**, or paid subscriber work will trip the shared cap
and stall generation — or generation will starve the work someone paid for. Neither is acceptable
and the shared-cap version fails silently in both directions. Must be settled before P6.

**F-6. Brief turnaround.** Supply is bursty (§1.2), so an SLA is a promise the engine may not keep.
**Rule:** publish a bounded, honest window (7 days) with visible queue position, and no promise
about the *verdict*. Volume is never promised (§3.1); latency, being under our control, can be.

**F-7. A subscriber's brief steers generation.** Permitted and intended — *"demand tunes what to
offer"*. The line it must not cross: a brief enters as an ordinary signal carrying **no priority
flag and no subscriber identity into the gates** (§10).

### G. Money and catalogue consistency

**G-1. Plan price changes.** Stripe grandfathers existing subscriptions automatically;
`GET /commerce` shows new prices to new buyers only. Pair with B-8 for terms.

**G-2. A plan's recurring Price is archived or deleted at the provider.** New checkouts fail at the
last step.
**Rule:** extend the existing `CanBillPriceAsync` preflight (`Program.cs:665`, the `CanBillPriceAsync` refusal) from packs to plans,
and refuse to advertise a plan whose price cannot be billed.

**G-3. Test-key/live-key mismatch when minting plan prices.**
**Rule:** plan prices go through the same fence as pack prices — `bridge.py:587-613` refuses to
price a remote catalogue without a live key. A subscription minted on a test key against the prod
catalogue is the worst version of this bug.

**G-4. Currency without a declared plan price.** Exactly the live gap in §1.1 — 0 of 61 packs carry
USD.
**Rule:** null is the refusal, identical to `Pack.PriceUsdCents`. A plan with no USD price cannot be
sold in USD; never convert at charge time.

**G-5. Provider divergence.** A subscription belongs to one provider. In a Paddle/Stripe mix, a
subscriber cannot claim a pack minted at the other provider — but under this design a **claim is not
a charge**, so no provider is involved at claim time. Recorded because it looks like a problem and
is not.

### H. Concurrency, ops and time

**H-1. Concurrent webhooks under SQLite** (`Program.cs:26-28`). Single-writer; subscription traffic
multiplies webhook volume.
**Rule:** WAL mode plus bounded retry on `SQLITE_BUSY`. Webhook handlers must be idempotent (B-2)
so a retry is always safe. Revisit if the store moves to Postgres.

**H-2. Timezones.** All periods stored UTC, compared UTC. The codebase already uses
`DateTime.UtcNow` throughout; a single local-time comparison would move every renewal boundary.

**H-3. Month-end anchors.** A subscription started on the 31st renews on the 28th/30th in short
months. Stripe handles it; our period-derived allowance must not assume equal-length periods.

**H-4. Clock skew between the engine, the store and Stripe.** Periods come from the *invoice*, never
from local time (B-4), which removes the whole class.

**H-5. Webhook signature verification** — already implemented (`StripeProvider.cs`), unchanged.

### I. Abuse

**I-1. Subscribe → claim → cancel → repeat.** Bounded by §3.3: plan price ≥ modal pack price makes
the loop pointless, and the unique `(SubscriptionId, PackId)` index stops re-claiming the same pack.

**I-2. Many accounts, one person.** Each pays full price for each claim, so the arbitrage does not
exist under rung-agnostic pricing. This is the second reason the §3.2 revision matters.

**I-3. Card testing on the subscription endpoint.** The rate limiting already applied to `/download`
and checkout (`Program.cs:178-190`) must cover `/subscriptions/checkout`.

**I-4. Redistribution of claimed packs.** Unsolvable for digital goods, bounded by the 50-download
cap. Not a fence, a friction — recorded so it is not mistaken for one.

---

## 16. What the edge-case pass changed

Four defects were found in §§3–4 as drafted, and fixed above rather than papered over:

1. **The rung cap was unspendable** (C-4). 14 of 61 live packs sit at £29.99, so a Brief subscriber
   exhausted their claimable catalogue in 14 months. Claims are now rung-agnostic and Brief is
   repriced £39 → £49, which also deleted edge cases C-9, A-3-in-practice, and the enforcement half
   of I4.
2. **Mode gated consumption, not just acquisition** (A-1). As first written, flipping the shelf to
   `direct` would have confiscated claims subscribers had already paid for. I2 now separates the two.
3. **Allowance was derived from Stripe's period fields** (B-4), handing a free period to any
   subscriber whose renewal failed. It is now authorised by a paid invoice.
4. **Plan terms were read live from config** (B-8), so a config edit would retroactively change what
   existing subscribers had bought. Terms are now snapshotted onto the subscription row.

Two cases could not be closed by a rule and are escalated: **F-5** (briefs and the daemon share one
spend cap — must be settled before P6) and **B-13** (what a subscriber is owed if the catalogue
stops being worth claiming), which joins §13 as decision **13.4**.

---

*Design only. No engine or store code was changed. Measured 2026-08-15 against the live prod
catalogue, `store/prospector.db`, and the working tree.*

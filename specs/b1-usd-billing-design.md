# B1 — Charge US buyers in USD (design)

**Status:** design only. No edit made. Founder decision 2026-08-10 supersedes audit finding #19.
**Base:** verified on disk 2026-08-10, branch `fix/storefront-header-logo-filter-jump`.

---

## 0. The one framing error to avoid

The obvious design — "add a `Currency` column to the pack row" — is wrong, and the code says so
itself:

> `config.yaml:1263-1265` — "`market` is the jurisdiction the OPPORTUNITY lives in, **not the
> buyer's locale** — packs sell in GBP wherever they sell."

A UK-market pack (HSE filing, DVSA renewal) can be bought by a US buyer, and a US-market pack by a
UK buyer. **Currency is a property of the checkout, not of the pack.** Any design that keys currency
off `Pack.Market` bills the wrong buyers in the wrong currency and is a refund queue.

`market_rung_offset` (`config.yaml:1266-1268`, `us: 1`) is therefore NOT an FX mechanism and must
not be repurposed as one. It says a US-market opportunity earns one rung more because the addressed
economy is larger. It is orthogonal to who is paying.

---

## 1. What is true today (verified, not recalled)

| Fact | Evidence |
|---|---|
| The single price-minting call passes no currency | `prospector/bridge.py:1003-1007` — `prov.create_price(product_id=…, amount_pence=price.price_pence)` |
| Stripe provisioner defaults it | `bridge.py:1760` — `def create_price(self, product_id, amount_pence, currency: str = "gbp")` |
| Paddle provisioner too | `bridge.py:1673` — `currency: str = "GBP"` |
| `PriceDecision` has no currency field | `prospector/pricing.py:20-38` — `price_pence, rung, segment, rationale, evidence` |
| The catalogue row has no currency | `store_platform/src/Store.Catalog/Domain/Pack.cs:8` — `public long PricePence` |
| The fulfilment fence hard-refuses non-GBP | `Store.Api/Services/FulfilmentService.cs:19` `StoreCurrency = "GBP"`; `:117-120` returns unfulfilled on any mismatch |
| The amount fence is pence-denominated | `FulfilmentService.cs:122-125` — `item.AmountPence < pack.EffectiveFloorPence(...)` |
| Checkout passes a Price **ID**, not an inline amount | `StripeProvider.cs:379-383` — `Price = line.ProviderPriceId` |
| The ladder is pence integers | `config.yaml:1238` — `rungs: [1999, 2999, 4999, 7999, 9999, 14999, 19999]` |
| Display FX is a courtesy, explicitly | `lib/fx.ts:5-7`; rates hardcoded `USD: 1.27` (`fx.ts:43-50`), 24h TTL (`fx.ts:59`) |

**The one asset already in place:** the Stripe idempotency key already includes currency —
`f"prospector-price-{product_id}-{amount_pence}-{currency}"` (`bridge.py:1767`). Minting a
second-currency price is already replay-safe. That was not an accident worth losing.

---

## 2. Decisions

### D1 — Stripe `currency_options` on the existing Price. Not a second Price object.

One `Price` per pack, carrying `currency_options: {usd: {unit_amount: N}}`. Checkout selects the
currency at session creation.

Rejected: a second `Price` per pack. It doubles `ProviderPriceId` into a map, changes the catalogue
schema, and — per memory `republishing-stranded-passes-fails-on-link-rot` — every republish path we
have mints orphan Stripe products. Fifty live packs × a new Price each is fifty chances to strand
one. `currency_options` keeps `ProviderPriceId` a single opaque string, so **the catalogue row does
not change at all** and the fulfilment fence's `ProductId` join is untouched.

> **HYPOTHESIS — this is the go/no-go, and it is not yet proven.** Stripe `Price` objects are
> immutable in `unit_amount`. I have NOT verified that `currency_options` can be *added to an
> existing* Price via `Price.update`. If it cannot, the 50 live packs need re-minted Prices and D1
> collapses into the republish trap above — which changes the whole shape of this work.
> **Exact check, read-only, one call:**
> `.venv/bin/python -c "import stripe,os; stripe.api_key=os.environ['STRIPE_SECRET_KEY']; p=stripe.Price.list(limit=1).data[0]; print(stripe.Price.modify(p.id, currency_options={'usd':{'unit_amount':4999}}))"`
> Run against **test mode keys first**. Do not run this against live without founder sign-off.

### D2 — USD amounts come from a declared USD ladder, never from runtime FX.

Add `listing.pricing.rungs_usd` alongside `rungs`, in **cents**, charm-rounded independently:
`[2499, 3499, 5999, 8999, 11999, 17999, 24999]` (indicative — the actual numbers are a founder
pricing call, not a conversion).

Rationale, and it is the load-bearing one: **charge-time FX is a chargeback.** `fx.ts` caches a rate
for 24h (`fx.ts:59`) and falls back to a hardcoded `1.27` (`fx.ts:45`). If the displayed figure and
the charged figure are derived from a rate at two different instants, they disagree, and the buyer's
statement does not match the page they bought from. A declared ladder is deterministic, auditable,
identical in display and charge, and it survives an FX-feed outage. It also keeps the "price is a
rung, never a computed continuous number" rule (CLAUDE.md) intact in both currencies.

**Consequence for the storefront:** `fx.ts` stops being the source of the USD figure. It must render
the *actual* USD amount the API returns for that pack, not a conversion of the GBP one. Its
conversion path stays only for currencies we do NOT charge in (EUR today), where the "courtesy"
framing in `fx.ts:5-7` remains honest and must be kept visible.

### D3 — The fulfilment fence learns a per-currency floor. It does not learn to trust the buyer.

`FulfilmentService.cs:19`'s `StoreCurrency = "GBP"` const is replaced by a lookup of the currencies
the pack is *sellable* in, and `EffectiveFloorPence` gains a currency argument. The fence's
existing logic — refuse anything below the lowest amount a live session could carry — is correct and
must be preserved per-currency, comment `FulfilmentService.cs:110-115` included.

The fence must still **refuse an unknown currency**. Today's blanket non-GBP refusal is the right
default and only its *set* widens. This is the part that must not be loosened into "accept whatever
Stripe reports".

### D4 — Buyer country is resolved server-side at session creation.

The country already comes from the `fly-client-country` header (`pages/index.tsx:2078`). For
*display* that is fine. For *charging* it must be read at session-creation time in the API, never
accepted as a client-supplied field, or a buyer picks their own currency by editing a request.

---

## 3. Change set (ordered; each independently shippable)

1. `prospector/pricing.py` — `PriceDecision` gains `amounts: dict[str, int]` (currency → minor
   units) beside the existing `price_pence`. Keep `price_pence` as the GBP field so nothing
   downstream breaks in step 1.
2. `config.yaml listing.pricing` — add `rungs_usd`, and a `charge_currencies: [gbp, usd]` list.
   The ladder stays declarative; the second ladder is a founder pricing decision.
3. `prospector/bridge.py:1003-1007` — pass `currency_options` through to `create_price`.
   `bridge.py:1760` signature extends; the idempotency key at `:1767` must incorporate the full
   amount set, or a same-GBP/different-USD mint silently returns the old Price.
4. `Store.Api` checkout — set `Currency` on `SessionCreateOptions` (`StripeProvider.cs:379-383`
   region) from the server-resolved country.
5. `FulfilmentService.cs:19,117-125` + `Pack.EffectiveFloorPence` — per-currency floor (D3).
6. `lib/fx.ts` — render the charged USD amount; keep conversion for EUR only, keep the disclosure.
7. Backfill the 50 live packs (gated entirely on the D1 hypothesis above).

**Do not start at step 3.** Steps 1-2 are inert until 3 lands, and 5 must be deployed *before* 3 or
4, otherwise the first USD payment arrives at a fence that refuses it and the buyer is charged with
no entitlement — the exact failure `price-change-breaks-fulfilment` records.

---

## 4. What I am not deciding

- The USD rung numbers. That is pricing, not engineering.
- Whether EUR follows. The design supports it; nothing here commits to it.
- Tax. USD pricing raises US sales-tax nexus questions that are not an engineering call.

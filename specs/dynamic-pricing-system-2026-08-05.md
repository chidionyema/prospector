# Dynamic Pricing System — analysis and proposal

**Author:** architecture pass, 2026-08-05
**Status:** proposal, not implemented — **v2** (v1's "wait for traffic" posture is superseded by §3)
**Scope:** engine-side price *setting* + store-side price *management*

Every factual claim carries a `file:line`, a command, or a probe output. Anything I could not prove
is marked `HYPOTHESIS:` with the exact check that would settle it.

---

## 0. Verdict up front

1. **Flat pricing is a real value-capture defect.** 22 b2b packs and 29 b2c packs are priced
   identically at £49.00 (§1.1–1.2). Indefensible regardless of traffic, provable with no
   conversion data.

2. **The zero-evidence objection is real but it is not a reason to wait — it is a reason to
   manufacture evidence.** Purchases are the *rarest* event in this funnel (1 in 5,049) and
   therefore the worst possible measuring instrument. Three cheaper instruments give 50–500× the
   event rate, and one of them is **already running in the pipeline and being discarded** (§3.1).
   The 594-day figure in v1 was an artifact of the instrument, not a property of the business.

3. **You cannot change the price of a published pack at all right now, and the first person who
   tries will charge a customer and not deliver.** `Program.cs:445-465` ignores `PricePence` on
   update; `FulfilmentService.cs:88` gates delivery on it. This blocks everything (§5, Layer 0).

4. **Most of the control machinery already exists** — `SimulationHarness`, `CanaryRunner`,
   `MetricsStore`, `measure_effect`, `SelfModificationLog` (§4). Pricing should be a *policy
   registered with that stack*, not a parallel system. This is why "world class" is affordable here.

**The framing that matters:** *there is no no-decision option.* £49 flat is itself a zero-evidence
price, set once and never revisited. The bar is not "prove the new price is optimal" — it is **"is
this better-reasoned than the constant it replaces, and does it get measurably smarter per unit of
traffic?"** Both are achievable now.

---

## 1. Current state — measured

### 1.1 Price is one global constant, applied 61 times

```
$ curl -s https://api.mumchimp.com/catalog | ... Counter(price)
count 61
Counter({'£49.00': 61})
```

- `config.yaml:811` — `price_pence: 4900`
- `prospector/bridge.py:507` — mints the Stripe Price from it
- `prospector/bridge.py:854` — the publish payload sends it
- `store_platform/src/Store.Catalog/Domain/Money.cs:8` — `DefaultPackPricePence = 4900`

No per-pack price input exists anywhere in the pipeline.

### 1.2 The facets prove the packs are not interchangeable

| facet | live distribution |
|---|---|
| `payer` | **b2b 22**, b2c 29, *(unset)* 10 |
| `effort` | automatable 44, part_automatable 13, hands_on 3, *(unset)* 1 |
| `commitment` | part_time 33, evenings 14, full_time 4, *(unset)* 10 |
| `market` | uk 13, us 11, *(unset)* 37 |

A b2b pack on a company card is priced the same as a b2c "evenings" side-hustle bought from
post-tax income. The engine already knows which is which (`prospector/facets.py:26-33`).

### 1.3 The engine already computes a price signal, and nothing consumes it

`prospector/score.py:58-61` defines `listing_price_signal()`. **Zero callers, zero tests** (grep over
`prospector/` and `tests/`). Same for `tiers`, `subscription`, `exclusivity`, `surfaces`
(`config.yaml:813-817`) — declared, zero consumers. Layer 1 finishes an existing design rather than
inventing one.

### 1.4 First-party demand data: essentially nil

`GET /internal/analytics/summary?days=90`, probed 2026-08-05:

| step | count | rate from views |
|---|---|---|
| page_view | 5,049 | — |
| any CTA click | 13 | 0.26% |
| **checkout_completed** | **1** | **0.020%** |

Recent daily views: 08-02 **2,269**, 08-03 **804**, 08-04 **400**, 08-05 **332** (partial).
The allowlist (`AnalyticsEndpoints.cs:25-31`) has no `price_viewed` or `checkout_started`, so
"balked at the price" and "never reached a price" are currently indistinguishable.

> **HYPOTHESIS:** the single `checkout_completed` is the founder's own fulfilment probe.
> **Check:** `stripe payments list`, or match its `Meta` session id against the known probe.

### 1.5 Value dispersion among live packs is real but narrow

61/61 live pack ids joined to `store/dossiers/{id}.pass.json`:

```
composite  min=2.50  p25=2.70  med=2.95  p75=3.10  max=3.55   spread=1.42x
automatability  min=0  max=5   (full range)
```

Composite spans only **1.42×** because the PASS gate already killed the left tail. **A ladder driven
by composite alone would produce nearly flat prices.** Segment (`payer`, `commitment`, `market`) is
what genuinely partitions willingness-to-pay; score modulates within a segment.

---

## 2. Why the naive design fails, and why that is not the end of the story

Purchase-outcome learning at the observed baseline (α=0.05 two-sided, 80% power; Appendix A):

| instrument | baseline | effect | n per arm | days @400 views/day |
|---|---|---|---|---|
| checkout_completed | 0.0198% | +100% | 118,848 | **594** |
| checkout_completed | 0.0198% | +200% | 39,609 | 198 |
| any CTA click | 0.2575% | +50% | 30,382 | 152 |
| any CTA click | 0.2575% | +100% | 9,106 | 46 |

Two conclusions, and only the first was in v1:

- **A price bandit fed purchase outcomes would spend a year acting on noise** while *looking*
  data-driven. That design is genuinely bad and stays rejected.
- **But look at the last two rows.** Simply moving one step up the funnel cuts the requirement
  ~13×. That is the clue: the binding constraint is the *choice of instrument*, and instruments are
  a design variable, not a fact of nature. §3 changes the instrument.

Note also that frequentist power analysis answers *"when may I be confident?"* — the wrong question
for a system that must post a price today regardless. The right question is *"what is the
best action under current uncertainty, and which measurement buys the most information per
visitor?"* That is a Bayesian decision problem, addressed in §3.3.

---

## 3. Five pillars of a world-class system with no first-party evidence

### 3.1 Manufacture evidence: harvest cited reference prices from the moat you already run

**The find:** the grounding engine *already retrieves willingness-to-pay evidence for every single
pack* and then throws the price information away. `prospector/verify.py:192`:

```python
"payer_solvency": ["{q} budget willingness to pay ROI"],
```

Every pack that reaches publication has already had pages fetched about what its payer can afford
and what they pay for adjacent solutions. The `payer_solvency` verdict consumes those passages for
a binary solvent/insolvent judgement and discards everything quantitative in them.

**Proposal — `price_comparables`, a seventh check.** Same six-check machinery, same source-or-die
discipline, run once per candidate:

> *What do people currently pay to get this outcome?* — the consultant's day rate, the competing
> template or course, the SaaS subscription that half-solves it, the cost of the problem going
> unsolved (fines, missed rebates, wasted hours × a cited hourly rate).

Output: a **cited reference-price distribution** per pack — `{low, mid, high, currency, sources[]}` —
with the same retrievability bar as every other verdict. Silence ⇒ `unverifiable` ⇒ the pack falls
back to its segment default. Never a model guess.

This is the single highest-leverage item in the document:

- It produces a **defensible per-pack anchor on day one, with zero customers.**
- Marginal cost is one extra check on a pipeline that already runs six, with grounding already warm.
- It is *native to this repo's whole thesis.* Prospector's claim is that a cited verdict beats an
  asserted one. Applying that to price makes the price itself a proof artifact: **£X because
  [source] shows the alternative costs £Y.**
- It self-improves for free: every new pack adds comparables, and the catalogue-wide distribution
  becomes the prior for §3.3.

**Fence to respect:** `prospector/pack_floors.py:151` already forbids unsourced revenue/TAM figures
and guarantees. Reference prices are *other people's* prices, cited — not a promise about the
buyer's earnings. The rationale record must inherit that constraint verbatim.

### 3.2 Change the instrument: WTP elicitation that works at 400 views/day

Stop measuring with the rarest event. Four instruments, in ascending cost:

| instrument | what it yields | expected rate vs purchases | build |
|---|---|---|---|
| `price_viewed` / `checkout_started` events | price-reveal drop-off | ~13× today, more once instrumented | hours |
| **Waitlist-at-a-price** | *revealed* WTP from non-buyers | 10–100× | small |
| Tier-selection clicks | ordinal preference across rungs | 10–100× | with L4 |
| **Van Westendorp / Gabor-Granger micro-survey** | acceptable price *range* per segment | n≈100 in weeks | small |

**Waitlist-at-a-price deserves emphasis — the surface already exists.**
`store_platform/src/Store.Catalog/Domain/WaitlistSignup.cs` captures an email plus a `Query` field
whose own docstring calls it *"the demand signal"*, with versioned, hashed consent evidence. Add
`PriceAnchorPence` and a prompt — *"tell me when a vetted pack in this space drops below £__"* — and
every non-buyer who cared enough to type an email hands you a WTP datapoint. That is a real
elicitation instrument built on consent machinery that already passes a GDPR bar.

**Van Westendorp** is four questions on the pack page ("at what price is this too expensive / too
cheap to be credible / expensive but worth considering / a bargain"). It needs *respondents*, not
buyers. At 400 views/day, n≈100 per segment is weeks, not 594 days, and it yields a defensible
acceptable-price band per `payer` segment — exactly the parameter §5 Layer 1 needs.

> **HYPOTHESIS:** survey-stated WTP overstates true WTP (well-known in the pricing literature;
> I have not retrieved a citation in this pass). **Mitigation regardless:** use PSM for the
> *relative ordering and band width between segments*, not the absolute level; anchor the level on
> §3.1's cited comparables, which are revealed prices people actually pay.

### 3.3 Decide under uncertainty properly: Bayesian hierarchy + expected value of information

Replace "wait for significance" with "act optimally under the current posterior."

- **Hierarchical (partially pooled) demand model.** Levels: catalogue → cluster
  (`payer × commitment`) → pack. Each pack inherits its cluster's posterior, so 61 packs learn
  cluster-level elasticity far faster than any pack learns its own. With ~6–8 clusters this is
  estimable at event counts that per-pack modelling never reaches.
- **Informative priors, not flat ones.** §3.1 comparables set the location; §3.2 PSM sets the
  spread. The model is *useful on the first observation* rather than needing hundreds to escape a
  uniform prior. This is precisely how you build a learner before evidence exists.
- **Decision rule: maximise expected revenue** `E[price × P(convert | rung, cluster)]` under the
  posterior, reported with credible intervals. Never a p-value gate. (Optimising conversion alone
  drives every price to the floor.)
- **Expected Value of Information directs the experiment.** With scarce traffic, uniform A/B is
  wasteful — most cells are already decided by the prior. EVI ranks candidate (pack, rung) probes by
  information bought per visitor and spends traffic only where the posterior is both uncertain *and*
  decision-relevant. **This is the piece that makes it world-class rather than merely Bayesian**, and
  it matters *most* precisely when traffic is scarce.
- **Thompson sampling falls out naturally** and is correct at low n — it explores in proportion to
  uncertainty and needs no significance threshold to behave sensibly.

Related: `prospector/attribution.py:19 measure_effect` currently uses a Welch's t-test with a
`significant` flag — the same conservative frequentist framing. The Bayesian upgrade applies there
too, and doing both together is one piece of work, not two.

### 3.4 Prove the machinery in simulation, before real data exists

`prospector/simulation.py:145 SimulationHarness` already exists for the self-improvement loop. Extend
the pattern to demand:

- **Synthetic buyer population** with *known* latent WTP distributions per segment.
- Run the full controller against it and assert: converges toward known-optimal rungs; does not
  oscillate; respects every guardrail (floor, cooldown, max step); **recovers when the prior is
  deliberately mis-specified** (the failure mode that matters most, since §3.1/§3.2 priors *will* be
  somewhat wrong); degrades gracefully at realistic traffic.
- **Offline policy evaluation / replay.** Once real events accumulate, evaluate a candidate policy
  counterfactually against logged data *before* it is allowed to write a price.

This is the direct answer to "no evidence yet": you cannot validate the *prices* without data, but
you can fully validate the *machinery* without it. When data arrives, only the prior is unproven —
and that is a much smaller thing to be wrong about.

### 3.5 Anchor to cited value, not to guesses

`prospector/bridge.py:69 _financial_snapshot()` already extracts Month-1 revenue, LTV:CAC and payback
from the rendered financial model, and its docstring notes these are *"arithmetically exact, so they
are safe to surface pre-purchase."* Combine with §3.1 and price becomes a *ratio*, not a number: a
disclosed fraction of cited value, with the citation shown next to it.

A pack whose sourced economics support £2,000/month supports a different price than one at
£200/month — and the buyer can check the arithmetic. Same fence as §3.1: cite the source, never
imply guaranteed earnings (`pack_floors.py:151`).

---

## 4. Build on the control stack that already exists

| existing | file | role in pricing |
|---|---|---|
| `SelfModificationLog` | `self_modify.py:24` | every price-policy change logged with before/after + rollback |
| `CanaryRunner` | `canary.py:57` | price policy runs on a subset, auto-promote / auto-revert |
| `MetricsStore` | `metrics_store.py` | SQLite time series for pricing metrics |
| `measure_effect` | `attribution.py:19` | effect attribution (upgrade to Bayesian per §3.3) |
| `SimulationHarness` | `simulation.py:145` | the §3.4 demand simulator |

Pricing should register as **another self-modification surface**: propose → canary → attribute →
promote or revert, with rollback for free. Building a parallel pricing controller when this stack
exists would be the wrong call.

**One sharp warning.** `store_platform/src/Store.Web/src/lib/useCopyVariant.ts:8` assigns variants
**per viewer**, persisted in a cookie. That is fine for *copy*. It must **never** be reused for
*price* — per-viewer price assignment is personalised pricing (§6.2). Price assignment keys on
`(pack_id, epoch)` and takes no viewer input at all.

> Separately and unrelated to pricing: that cookie appears to contradict the cookieless stance
> asserted in `lib/analytics.ts:16` and `lib/market.ts:13`. Worth a look; not this project.

---

## 5. Architecture

```
  L0  PriceMutator + PATCH /internal/catalog/{id}/price   <- ONLY writer of price. Blocks all else.
  L1  PriceEngine — deterministic segment ladder          <- ships now, no demand data needed
  L2  Evidence manufacture: price_comparables check (3.1)
      + price_viewed / checkout_started + waitlist-at-a-price + PSM survey (3.2)
  L3  Bayesian hierarchical demand model + EVI-directed probes + Thompson (3.3)
      validated in simulation first (3.4); proposes rungs, never writes
  L4  Structure: tiers / subscription / bundles / regional
```

### Layer 0 — Make price mutable without breaking fulfilment *(prerequisite)*

**The hazard, proven.** `store_platform/src/Store.Api/Services/FulfilmentService.cs:88`:

```csharp
if (item.AmountPence < pack.PricePence)
    unfulfilled.Add($"{item.ProductId} (paid {item.AmountPence}p < price {pack.PricePence}p)");
```

Stripe charges the buyer; delivery is then gated on the pack's *current* `PricePence`. The webhook
body is deliberately not trusted to set price (`FulfilmentServiceTests.cs:129`) — correct, that
fence stops a forged cheap purchase. Consequence:

- **Cut** £49→£29, Stripe first: buyer pays 2900, pack says 4900 → **charged, not delivered**.
- **Rise** £49→£79, `PricePence` first: a buyer holding a Checkout Session minted at £49 (Stripe
  sessions live up to 24h) pays 4900 → **charged, not delivered**.

Opposite orderings; no single ordering is safe for both. Hence a structural fix:

| column | meaning | read by |
|---|---|---|
| `PricePence` | price *new* sessions mint at; the displayed price | catalog API, storefront, checkout |
| `MinBillablePence` **(new)** | fulfilment floor — lowest price any *live* session could carry | `FulfilmentService` only |

Invariant: `MinBillablePence = min(PricePence over the last SESSION_TTL window)`.

- **Cut:** set both to 2900 in one transaction, then point at the new Stripe Price. Old £49 sessions
  fulfil (4900 ≥ 2900 ✓); new ones fulfil ✓.
- **Rise:** set `PricePence=7900` + new Stripe Price now; hold `MinBillablePence=4900` and raise it
  after `SESSION_TTL + margin` (~26h). Old sessions drain safely ✓; the floor then closes ✓.

The fence stays fully effective against genuine underpayment and can never refuse a paying customer.
One column, one scheduled tick.

**Endpoint** — mirrors the narrow-PATCH convention `Program.cs:693-698` already argues for:

```
PATCH /internal/catalog/{id}/price
  { "pricePence": 7900, "providerPriceId": "price_1AbC…",
    "reason": "L1 ladder v1: b2b/part_time/us", "actor": "price-engine",
    "rationaleRef": "store/pricing/rationale/<id>.json" }
```

1. Fail-closed on `X-Internal-Key`.
2. **Verify billability before committing** — reuse `CanBillPriceAsync` exactly as the publish path
   does (`Program.cs:537`).
3. Reject `price_stub_*` ids server-side (the `bridge.py:554` rule, enforced on both ends).
4. Write `PackPriceHistory` (id, from, to, providerPriceId, reason, actor, timestamp).
   **Without a price-history table no experiment is analysable after the fact** — this row is what
   joins a conversion back to the rung that produced it.
5. Never touch `IsListed`, `ContentKey`, or facets.

**Stripe note:** `Price` objects are immutable. `bridge.py:1046-1058` already keys idempotency on
`{product}-{amount}-{currency}`, so re-minting the same amount is a no-op and a different amount
naturally mints a new object — correct behaviour. Deactivate old Prices, never delete: historical
sessions and receipts must stay resolvable.

### Layer 1 — Deterministic segment ladder *(ships now)*

Discrete rungs, not a continuous function: each amount is a Stripe object, discrete cells are what
any experiment or bandit needs, and round numbers are what buyers read.

```yaml
listing:
  pricing:
    driver: segment_then_score           # replaces the unwired `driver: composite`
    rungs_pence: [1900, 3900, 7900, 14900]
    base_by_payer:   { b2b: 7900, b2g: 7900, b2c: 3900, _unset: 3900 }
    modifiers:                            # rung OFFSETS, not percentages — they compose safely
      commitment: { full_time: +1, part_time: 0, evenings: -1 }
      market:     { us: +1, uk: 0, _unset: 0 }
      effort:     { automatable: +1, part_automatable: 0, hands_on: -1 }
      score:      { premium_axis: automatability, rung_up_at: 4 }
    comparable_anchor:                    # §3.1 — overrides the ladder when cited evidence exists
      enabled: true
      rung_nearest_to: "0.15 * comparable_mid"
      require_sources: 2
    max_rung_step_per_change: 1
    floor_pence: 1900
```

Resolution: `base_by_payer[payer]` → apply rung offsets → **if a cited comparable exists with ≥2
sources, snap to the rung nearest the anchored fraction** → clamp. Segment-first because §1.5 shows
composite spans only 1.42×; cited-comparable-first *over* segment because a source beats a prior —
that ordering is the repo's whole doctrine.

**`_unset` is doing real work:** 10/61 packs have no `payer`, 37/61 no `market` (§1.2). Those default
conservatively, which makes **facet coverage directly a pricing-revenue task**, not only a discovery
one.

**Every price carries a rationale record** (`store/pricing/rationale/<id>.json`): inputs, ordered
derivation steps, comparable sources with URLs, ladder version, timestamp. If a price is ever
challenged — by you, a buyer, or a regulator — this file is the answer.

**Wiring:** `listing_price_signal` (`score.py:58`) is replaced by `prospector/pricing.py`
`PriceEngine.resolve(candidate, score, comparables, cfg) -> PriceDecision`, called before
`create_price` (`bridge.py:504`) and before the publish payload (`bridge.py:854`). Both must consume
the **same** `PriceDecision`; a pack whose Stripe price and `pricePence` disagree is exactly the L0
hazard.

**Backfill** of the 61 live packs goes through `PATCH …/price` — never the destructive upsert.

### Layers 2–4

Per §3 and §7. L4 (`tiers`, `subscription`, bundles, regional) is where I believe the largest
revenue effect sits: at 13 CTA clicks per 5,049 views, moving £49 to £39 or £79 changes almost
nothing because almost nobody reaches a price. `tiers: [scout, operator, founder_investor]` and
`subscription: true` sit declared and unwired at `config.yaml:814-816`, and 61 packs with ~15/day of
new supply is a subscription product far more naturally than 61 one-off SKUs.

---

## 6. Rails

### 6.1 Operational

- **Kill switch** `store/pricing/PAUSE` — same filesystem pattern `CLAUDE.md` names as a liability
  backstop for unattended operation. Present ⇒ no price write, at all.
- **Daily change cap** and **per-pack cooldown**, so nothing oscillates or churns Stripe objects.
- **Floor** — never below `floor_pence`, never below unit COGS. `spend.daily_cap_usd: 20.0`
  (`config.yaml:854`) against realised pack yield gives a real per-pack cost floor. Not computed here.
- **Audit on both sides** — `PackPriceHistory` row *and* an engine JSONL line, reconcilable.
- **Rollback** — history makes "restore every price to its 2026-08-05 value" a script.

### 6.2 Legal — the one hard constraint

**Price must never vary by individual viewer.** Per-pack, per-epoch and per-market pricing is
ordinary retail practice. Pricing varying by inferred individual characteristics or behaviour is
*personalised pricing*, which carries disclosure obligations under UK consumer law and sits in the
DMCC Act 2024 enforcement area this repo already reasons about for fake reviews.

> Legal claim, statute not retrieved in this pass — **HYPOTHESIS pending counsel.**
> **Check:** CMA guidance on personalised pricing + DMCCA 2024 unfair-practices provisions, read
> against the exact rule shipped. The engineering recommendation stands regardless: key assignment
> on `hash(pack_id, epoch)` with no viewer input and the question never arises.

Also: a price that changes between catalogue card and checkout is a drip-pricing pattern. The
`PriceDecision` object being the single source for card, pack page and Stripe session is what
prevents it. And the §3.2 survey must state plainly that answers do not change the price that
respondent is shown — because under §6.2 they must not, and saying so is both true and trust-building.

---

## 7. Sequencing

| # | Work | Gate | Why here |
|---|---|---|---|
| 1 | **L0**: `MinBillablePence`, `PATCH …/price`, `PackPriceHistory`, tests 1–5 | none | Blocks everything; fixes a charged-and-not-delivered bug live *today* for anyone who edits a price |
| 2 | **L2a**: `price_viewed` / `checkout_started` events | none | Hours of work; starts the clock; today you cannot tell balked-at-price from never-saw-price |
| 3 | **§3.1 `price_comparables` check** | none | Highest leverage in the doc — cited per-pack anchors with zero customers |
| 4 | **L1** `PriceEngine` + ladder + rationale + golden matrix test | after 1, 3 | The value-capture fix, now anchored on evidence rather than my priors |
| 5 | L1 backfill of the 61 live packs | after 4 | One-shot through the audited endpoint |
| 6 | **§3.2** waitlist-at-a-price + PSM survey | parallel with 4 | Builds the elicitation dataset while the ladder ships |
| 7 | **§3.4** demand simulator + policy replay | parallel | Validates L3 before any real data exists |
| 8 | **Decision: subscription vs one-off vs tiers** | ~30 days after 2, 6 | The model question dominates the calibration question |
| 9 | **L3** Bayesian model + EVI probes + Thompson, canary-gated | after 7, and event thresholds derived *then* | Machinery already proven in sim; only the prior is unproven |

**Tests that must exist before anything ships:** (1) cut ordering — a session minted at 4900 still
fulfils after a cut to 2900; (2) rise ordering — old sessions fulfil through the drain window;
(3) underpayment still refused (extends `FulfilmentServiceTests.cs:137-163`); (4) non-billable price
rejected, no history row; (5) `price_stub_*` rejected server-side; (6) ladder golden matrix;
(7) comparable-anchor requires ≥2 sources or falls back; (8) every price write has a resolvable
rationale; (9) L3 gate asserted closed until its thresholds are met.

---

## 8. What I could not prove

- Whether the single `checkout_completed` is organic or your probe (§1.4).
- Whether £49 is above or below WTP for *any* segment. **No evidence exists either way** — which is
  exactly why §3.1 and §3.2 are steps 3 and 6 rather than someday-items.
- Unit COGS per pack, hence the true floor (§6.1).
- The legal position on personalised pricing (§6.2) — flagged; the design sidesteps it.
- That survey-stated WTP tracks real WTP (§3.2) — mitigated by using PSM for *relative* structure and
  cited comparables for *level*.
- The ladder numbers in §5 L1 are my priors, not derivations. After step 3 they should be
  **replaced** by cited anchors; treat the config values as scaffolding with a short life.

---

## Appendix A — power calculation (reproducible)

```python
z = 1.959964 + 0.841621; k = z*z          # alpha=0.05 two-sided, power=0.80
def n(p1, lift):
    p2 = p1*(1+lift); d = p2-p1
    return k*(p1*(1-p1) + p2*(1-p2))/(d*d)
n(1/5049, 1.0)    # -> 118848 per arm  (checkout, +100%)
n(13/5049, 0.5)   # ->  30382 per arm  (any CTA click, +50%)
```

Baselines from `GET /internal/analytics/summary?days=90` on 2026-08-05: 5,049 page_view, 13 CTA
clicks, 1 checkout_completed. Days-to-complete assumes 400 views/day (the 2026-08-04 figure).
**These figures bound the naive purchase-outcome design only** — §3 exists to escape them, and the
L3 thresholds in step 9 must be re-derived against whichever instrument is live at the time.

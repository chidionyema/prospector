# STORY v2: A global opportunity engine — market as a first-class dimension, scaled on data and code, with packs worth paying for anywhere

Date: 2026-07-30. Evidence basis: four on-disk audits this session (pipeline map, pack-content
audit, storefront audit, UK/solo-hardcoding audit). Every factual claim carries `file:line` or a
quoted diagnostic. Unproven ideas are marked **HYPOTHESIS** with the probe that confirms or
kills them. Process risks are labeled as process risks, not quality verdicts.

---

## Part I — Two hard truths before any map gets colored in

Staff-engineer duty is to say these plainly, because the whole plan hangs on them.

### Truth 1: Market count is a multiplier, and today the multiplicand is ~zero.

Last diagnostic tick: `generated=5 … vetted=5 → PASS 0 · KILL 5` (`DIAGNOSTICS_LATEST.txt`,
2026-07-30T10:53Z); the daemon produces ~0–1 PASS/day **in the UK — one of the most
publicly-documented economies on earth** (free Companies House, gov.uk, HSE, ONS). Opening the
US, EU, Nigeria, and Asia multiplies whatever yield the engine has. Multiplying near-zero gives
zero, six times, at six times the wall-clock. So global scope does not replace the yield work
(Part IV); it is the reason the yield work matters. The correct move is: **generalize the
architecture now (cheap today, ossifies daily), gate each market's launch on a probe, and let
the yield engine make the multiplication worth doing.**

### Truth 2: The moat has a structural bias toward data-rich economies.

The doctrine is verdict-from-retrieval-only; silence → `unverifiable`, never `supported`
(CLAUDE.md; enforced in `verify.py`). That is exactly right — and it means the engine can only
see economies **the indexed web documents**. Evidence density varies by orders of magnitude:

| Market | Structured evidence infrastructure | Language | Assessment |
|---|---|---|---|
| US | SEC EDGAR, Census, BLS, FRED, state SoS registries, PACER/CourtListener — mostly free | English | Best on earth; better than UK in places |
| EU | EUR-Lex + 27 national regimes; registries fragmented, some paywalled (DE Handelsregister) | 24 languages | Strong but fragmented; Ireland is the English on-ramp |
| India | MCA registry, English official record, large indexed press | English (official) | Good formal-economy coverage; huge informal blind spot |
| Nigeria | CAC registry (weak programmatic access), NBS patchy; SME economy substantially informal — evidence lives in news (Nairametrics, BusinessDay), GSMA/World Bank/IMF aggregates | English | **The moat as-built will return structurally high unverifiable% — not a bug, a property of the evidence terrain** |

The two failure modes for a low-evidence market are both fatal: (a) honest engine → everything
unverifiable → market "open" but catalogue empty; (b) quiet pressure to lower the bar → junk
packs → the brand dies in exactly the market with the largest narrative upside. The bar never
moves (two-loops rule). What changes per market is the **evidence strategy** (Part III).
**HYPOTHESIS** per market, probed before launch — never assumed (see the Market-Readiness Gate).

---

## Part II — What is actually UK/solo-hardcoded today (proven this session)

| Layer | Finding | Rewrite or config? |
|---|---|---|
| Prompts | UK examples baked into `prompts/query_gen.md:23,29`, `query_gen_batched.md:32-35`, `verdict.md:31,39` (UK probate), `generate_system.md:20-23` (UK construction exemplar); GBP in `artifacts.md:18` | Template rewrite: inject `{market_context}` |
| Candidate model | **No market/jurisdiction/currency field at all** (`models.py:98-118`; Dossier `:220-242` likewise) | Minor schema: add `market` |
| Retrieval | `gov.uk` in `_HIGH_AUTHORITY_DOMAINS` (`retrieval.py:82`); DDG called with **no region param** though the library supports it (`retrieval.py:603-629`) | Config: per-market domain lists + region |
| Generation scope | `operator_archetype: solo_agent` is generation-wide (`config.yaml:377,418`: "ONE AI-leveraged person, no team, no outside capital"); lane directives solo-framed (`config.yaml:246-257,304-312`) | Already parameterized — archetype per lane×market |
| Money rail | `FulfilmentService.cs`: `private const string StoreCurrency = "GBP"` — **non-GBP payments explicitly rejected**; `Money.cs` defaults 4900 pence/£; Stripe+Paddle providers default GBP | Real rewrite, but deferrable (see Part III reframe) |
| Storefront | £49 hardcoded across `index.tsx`/`faq.tsx`/`Seo.tsx`; `terms.tsx:6` governing law England & Wales, `:72` GBP/VAT; **zero i18n infrastructure** | Rewrite, deferrable |
| What's already right | Lane/persona machinery fully parameterized with per-lane overrides of gates/thresholds/weights/directives (`config.yaml` lanes block) — **the template for the market dimension** | Reuse |

Bottom line: the engine is a config-and-prompts change away from multi-market. The **store** is
the heavy rewrite — and Part III shows why that rewrite is deferrable.

---

## Part III — The staff-level reframe: opportunity-market ≠ buyer-market

The unlock that decouples engine expansion from storefront/payments work:

**The jurisdiction an opportunity lives in and the locale of the person who buys the pack are
independent axes.** A pack about a Texas licensing arbitrage can be bought in GBP by anyone.
Diaspora buyers are a real bridge for low-rail markets: a Nigerian in London buying a
Lagos-market pack pays in GBP through the existing Stripe rail — no Paystack integration, no
naira pricing, no new tax nexus, on day one.

Consequences:

1. **Engine goes multi-market immediately; store stays GBP/Stripe** until non-UK packs prove
   demand. No i18n, no PSP work, no `FulfilmentService` surgery on the critical path.
2. The catalogue gains a **market facet** (filter/badge: 🇺🇸 🇳🇬 🇪🇺), which is presentation-layer
   work only — the `Pack` entity gets one field through `PublishRequest.cs`.
3. PPP pricing, local currency, local payment rails (Paystack/Flutterwave), and localized legal
   terms become **Phase-3 product decisions**, made with sales data, not guessed up front.
   Process risk, labeled as such: selling to US/EU consumers has sales-tax/VAT-OSS implications
   even in GBP — needs founder/accountant input before marketing spend targets those buyers,
   but not before listing.

---

## Part IV — The story

> **As a buyer anywhere, I can buy an evidence-grounded opportunity pack for any market the
> engine has proven it can see — and the engine only claims to see a market when a probe, not a
> promise, says so.**

Four epics. C and the yield work (A/B) are prerequisites that make multiplication non-zero;
D is the multiplier; the Gate governs when multiplication is allowed.

### Epic D — Market as a first-class dimension (the multiplier)

**AC-D1 — `market` threads end-to-end.** `Candidate.market` (jurisdiction code, defaulting
`uk`), carried through Dossier → `PublishRequest` → `Pack` entity → catalog API → storefront
badge/filter. Probe: a vetted candidate with `market: us` renders a US-badged pack on the pack
page with no GBP/UK contamination in its artifacts.

**AC-D2 — `markets:` config block mirroring `lanes:`.** Per market: authority-domain list
(replaces the hardcoded `gov.uk` at `retrieval.py:82`), DDG region + search locale, structured
evidence providers (Part V), legality corpus roots, currency/price hints for artifacts,
localized persona notes (the `retiree_cohort` persona at `config.yaml:409` encodes UK pension
assumptions — personas get a per-market overlay, not N copies). Engine stays deterministic on
config: opening a market is a config diff, not a code change.

**AC-D3 — Prompts are market-injected, not UK-flavored.** `{market_context}` block rendered
into generate/query_gen/verdict/content_gen; the UK examples in `query_gen.md`/`verdict.md`
become per-market exemplar sets. Probe: golden-set run for UK must not regress after
de-hardcoding (Part 13B gate) — this proves the injection carries what the baked examples
carried.

**AC-D4 — Market-scoped dedup.** `dedup.py:82` compares title/token similarity with no market
awareness — "mobile notary bond, Texas" vs "mobile notary bond, UK" would collide. Same idea in
a different market is NOT a duplicate. Dedup keys on (market, idea); a separate *cross-market
replication* path deliberately clones proven PASSes into sibling markets for re-verification —
the cheapest high-quality generation channel the engine will ever have (evidence differs,
verdicts re-earned from scratch, bar unchanged).

**AC-D5 — Per-market observability.** Funnel, unverifiable%, kill-gates, spend in
`DIAGNOSTICS_LATEST.txt`/`ticks.jsonl` split by market; `zero_yield` and `dead_gate` alerts keyed
per market. An aggregate over six markets is noise; per-market lines are the standing
peek-diagnostics habit extended to the new dimension.

### The Market-Readiness Gate (state-is-a-probe, applied to expansion)

A market is **closed until a calibration probe passes** — never opened by enthusiasm:

1. Assemble ~10 calibration candidates for the market with known ground truth (mix of
   should-PASS and should-KILL, mirroring the golden set's mixed-sector discrimination job).
2. Run the full vet through the market's configured evidence chain.
3. Open the market only if: unverifiable% ≤ threshold (UK baseline 35.3% is the anchor —
   exact bar is a founder calibration decision); ≥1 structured incumbency source responds;
   legality corpus reachable; discrimination on the calibration set is clean (no
   should-KILL passing).
4. The gate's output is a dated probe artifact in `store/markets/<code>/READINESS.json` —
   quotable evidence, re-runnable, and the only thing that may answer "is market X open?"

This converts "what about Africa?" from a debate into a measurement. If Nigeria's probe fails
on web-search evidence alone, the answer is not "no" — it is "not with this evidence chain,"
which routes to Part V.

### Per-market launch sequence (kill-fast ordering: cheapest decisive market first)

- **Phase 1 — US.** English, richest structured evidence, zero storefront work (GBP checkout;
  optionally USD via Stripe multi-currency — trivial next to a new PSP). Highest ceiling.
  Critical scoping rule: US legality is federal + 50 states — candidates must carry
  jurisdiction at the **state** level or the legality check drowns; the `market` field is
  hierarchical (`us`, `us-tx`). **HYPOTHESIS**: US unverifiable% ≤ UK baseline. Probe: the
  readiness gate.
- **Phase 2 — Ireland/EU-English, then India.** Ireland pilots EU (English, EUR-Lex + CRO).
  India: English official record, MCA registry, enormous solo-operator culture. DACH/France
  wait on the language decision: **HYPOTHESIS — the moat judges non-English passages reliably.**
  Probe: re-run 20 historical UK verdicts against machine-translated French/German versions of
  their own sources; verdict agreement must be near-perfect before any non-English market opens.
- **Phase 3 — Nigeria/anglophone Africa.** Its own product bet, not a config clone: evidence
  chain built on aggregates (World Bank/IMF/GSMA/AfDB), quality local business press, CAC where
  reachable; diaspora buyers on the existing GBP rail first; PPP pricing and Paystack/Flutterwave
  only after demand is proven. If the readiness probe fails even with the alternative chain, the
  market stays closed and the probe artifact says why — that honesty *is* the brand.

### Epic C — Every pack complete and honestly presented (pure code, ships first, unchanged from v1)

The product sold today can ship a 23-byte `Marketing_Assets.md` stub (`bridge.py:457-460`) and
silently omit the financial model (`bridge.py:442-449`); the storefront shows a fake blurred
preview (`pack/[id].tsx:399-420`), identical hardcoded deliverable chips (`index.tsx:33-38`),
one static sample for all packs (`sample.tsx:9`), and drops fields the API already sends. ACs:
validation floors in CI over every bundle; deterministic claim-safe marketing fallback from
existing listing fields; real excerpts from the actual zip; "what we couldn't verify" section
(the dossier holds it — `dossier.py:278-283` — marketing filters to SUPPORTED only at
`artifacts.py:405`); 1-page exec summary + first-week checklist. Zero AI, refund-risk reduction
on live sales, and every improvement is market-agnostic — it compounds across all future markets.

### Epics A/B — Yield and de-AI (the multiplicand, unchanged from v1, now market-aware)

- **B1** Deterministic number-attribution claim-check replacing the LLM call at
  `artifacts.py:287-294` (stricter by construction).
- **B2** Structured evidence fetchers per check as `SearchProvider`s in the existing fallback
  chain (`retrieval.py:1212`) — now designed per-market from day one: Companies House / state
  SoS / CAC are the same *interface*, different config. Incumbency killed 2 of 5 last tick;
  it is the pilot.
- **B3** Claim-graph evidence memory atop DiskCache (`retrieval.py:1153`, 14-day TTL) —
  keyed by (market, canonical claim). Cross-market replication (D4) makes this compound.
- **B5** Grown deterministic prescreen; **A1** signal harvesters (per market: gov.uk ↔
  federalregister.gov ↔ EUR-Lex ↔ NBS/CBN circulars) dropping into the existing
  `signals/pending/` resume path (`run.py:88`); **A2** bounded near-miss pivot loop (non-lossy,
  per the `_refine_wave` lesson); **A4** parallel vet after B2/B3 cut per-vet latency
  (`vet_workers: 1` is the wall-clock bottleneck; 75-min tick deadline stays honoured).

### Audience expansion (flag, not an epic)

Solo-operator is generation-wide (`config.yaml:377`), though smb/growth/venture lanes exist.
Widening the audience beyond solo/side-hustle is a **product** question — a growth-stage buyer
likely wants a different artifact set and price point than a £49 zip — and it is orthogonal to
markets. Recommendation: hold audience constant while the market dimension lands; revisit with
sales data. (Process note: the archetype is already config, so the door is open when wanted.)

---

## Part V — Critical risk register (the things that quietly break)

1. **Golden-set economics.** One golden set per market × every prompt change = the 13B gate
   gets expensive. Mitigation: a small per-market calibration set (the readiness probe doubles
   as it) + the full mixed-sector set stays UK until a market has volume.
2. **Non-English moat** — unproven (probe defined in Phase 2). Do not open non-English markets
   on vibes.
3. **Legality-check explosion** in federal systems (US states, EU members) — solved only by
   hierarchical jurisdiction scoping at candidate level (D1), not by broader searches.
4. **Cross-market dedup false-positives** (D4) — without it, market expansion is silently
   throttled by the dedup gate and nobody notices; add a diagnostic line for dedup-drops-by-market.
5. **Aggregate diagnostics become lies** once markets multiply (D5) — per-market lines before
   Phase 1 opens, or the standing peek-diagnostics rule stops working.
6. **Tax/consumer-law exposure** selling cross-border even in GBP — process risk, founder +
   accountant, before marketing targets those geographies.
7. **The bar-lowering temptation** in low-evidence markets — structurally refused: thresholds
   live in config per lane, not per market; a market with no evidence gets no catalogue, and
   the readiness probe artifact documents why. Demand never overrides truth.

---

## Part VI — Sequencing (one line each, kill-fast order)

1. **Epic C** (days, pure code) — the live product's refund risk, market-agnostic compounding.
2. **D1–D3 schema/config/prompt de-hardcoding NOW** (small, and it ossifies daily) — UK golden
   set green proves the de-hardcoding lossless.
3. **B1/B5, then B2 incumbency pilot** (UK first — richest ground truth to validate against).
4. **US readiness probe** → Phase 1 launch with D4/D5 in place; cross-market replication of
   existing UK PASSes into US as the first US generation channel.
5. **A1 harvesters + B3 claim-graph** (compound with multi-market).
6. **Non-English probe, Ireland/India probes** → Phase 2; **alternative-evidence chain design →
   Nigeria probe** → Phase 3.

## Part VII — Founder decisions needed

1. Readiness-gate bars: max unverifiable%, calibration-set size, who signs a market open.
2. Pricing stance for non-UK packs pre-PPP: flat £49 everywhere initially? (Recommended: yes,
   revisit with data.)
3. Tax/legal review trigger point for cross-border sales (before or after first non-UK-market
   listings).
4. Audience expansion (beyond solo) parked until when — a date or a sales threshold?
5. Epic C floor policy: block listing on incomplete packs vs deterministic-fallback fill
   (v1 recommendation stands: fallback-fill + floor).

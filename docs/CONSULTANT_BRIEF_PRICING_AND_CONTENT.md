# Consultant brief: how pricing works, and how everything we write is produced and policed

Status: BRIEFING DOCUMENT. Written 2026-08-18 for an external consultant. Every claim below
carries a `file:line` or a command output. Where something is unproven it says UNVERIFIED.

## How to read this

Mumchimp sells research packs. A pack is a PDF plus a web listing about one business idea. Two
parts of that are fragile, and this document is the full picture of both.

**Pricing** is one decision made once, in one function, and then copied into three places that
must never disagree: the payment provider, the catalogue database, and the website.

**Content** is not one thing. It is four separate word-producing systems with two separate
enforcement lanes that share rule names but share almost no code. That split is the single
biggest source of the fragility the founder has noticed.

Read Part A on its own. Read Part B in order, because the map in B1 is what makes the rest
legible.

---

# PART A. Pricing

## A1. The decision: a ladder, not a calculation

The price of a pack is a **rung on a fixed ladder**. It is never a computed continuous number.
That is a deliberate design choice recorded at `prospector/pricing.py:1-9`.

`price_for()` (`prospector/pricing.py:176-354`) returns a `PriceDecision`
(`prospector/pricing.py:41-70`) carrying `price_pence`, `rung`, `segment`, `rationale`,
`evidence` and `price_usd_cents`.

The ladder is declared in config, not in code, at `config.yaml:1832` under `listing.pricing`:

| key | value on disk | line |
|---|---|---|
| `rungs` (GBP pence) | `[1999, 2999, 4999, 7999, 9999]` | `config.yaml:1873` |
| `usd_rungs` (US cents) | `[2499, 3999, 6999, 10999, 13999, 19999, 26999]` | `config.yaml:1920` |
| `source_count_bands` | `[25, 30, 35, 45]` | `config.yaml:1904` |
| `default_rung_index` | `2` (so £49.99) | `config.yaml:1932` |
| `tier_rung_index` | side_hustle 1, smb 2, growth 3, venture 4 | `config.yaml:1943-1946` |
| `market_rung_offset` | uk 0, us 1 | `config.yaml:1953-1954` |

`price_for` picks a rung in this order:

1. No usable ladder in config, so fall back to a flat `listing.price_pence`
   (`prospector/pricing.py:226-243`).
2. A `source_count` is present and the bands are valid, so the **depth band** picks the rung
   outright. Tier and market are ignored on this path
   (`prospector/pricing.py:259-298`, band lookup at `:153-157`). In practice `bridge.py` always
   supplies a source count, so this is the live path.
3. Tier is unclassified, so use `default_rung_index`, and ignore market
   (`prospector/pricing.py:304-320`).
4. Tier is classified, so use `tier_rung_index[tier] + market_rung_offset[market]`, clamped to
   the array (`prospector/pricing.py:328-354`).

**The composite score does not move the price.** `price_for` accepts a `score` argument and
never reads it. The reason is stated in the docstring at `prospector/pricing.py:188-193`: the
scorer has a fail safe all zero mode, and tying price to it would turn a scoring outage into a
pricing outage.

USD is **declared, not converted**. `usd_rungs` is a parallel array of prices we chose, indexed
positionally by `_usd_at` (`prospector/pricing.py:160-173`). It is not an FX conversion of the
GBP rung.

## A2. The evidence check: price comparables (C3)

There is a seventh check in the verification pipeline whose only job is to find prices buyers
already pay. `run_price_comparables()` (`prospector/price_comparables.py:296-380`) runs three
price page queries (`config.yaml:1987-1989`), pools them with passages the other checks already
fetched (`prospector/price_comparables.py:341-357`), and has the model transcribe the prices it
can see.

Every anchor is then validated. This is the strictest evidence path in the codebase:

- synthesized sources are stripped (`prospector/price_comparables.py:207-208`)
- the citation must resolve to a real retrieved `source_id` (`:257-260`)
- the price must appear **literally** in the passage it cites, checked by `_appears_in`
  (`:119-141`, called at `:261`)
- it must be inside sane bounds, £1 to £5000 (`:271-277`)
- foreign currency converts only via a config declared FX rate (`:178-188`). Anything we cannot
  convert keeps `amount_pence_gbp=None` and can never move a price (`:416-428`).

To count as evidence at all it needs three anchors across two domains, and it reports the
**median** not the mean (`:431-459`, thresholds at `config.yaml:2035-2036`).

**This check can never kill a candidate.** `kill_filter.is_hard_fail` returns `False`
unconditionally for it (`prospector/kill_filter.py:28-29`), and `verify` strips it from the kill
fast run order before the loop (`prospector/verify.py:1042`). The stated reason at
`prospector/kill_filter.py:24-27` is that "no price page on the open web" is a fact about the
web, not about the idea.

**And by default the anchors change nothing.** `comparables.rung_adjust_enabled` is `false`
(`config.yaml:1971`). When it is on, anchors can move a price by at most one rung, and only on
the tier path, never on the depth band path (`prospector/pricing.py:72-115`, guard at `:266`).

So today: we retrieve real willingness to pay evidence, we record it, and we do not act on it.

## A3. Minting the price and writing the row

`bridge.publish_pass()` is where a decided price becomes money. The order matters:

- All content gates run first and produce `content_ok` (`prospector/bridge.py:1274`).
- A dry run returns **before** `price_for` is called (`prospector/bridge.py:1281-1292`), so a
  rehearsal mints nothing.
- The real path calls `price_for` exactly once (`prospector/bridge.py:1304-1315`, comment reads
  "Decide the price ONCE, here").
- The decision is written to the candidate's tags (`:1322-1326`) and to a rationale record via
  `write_rationale` (`:1336-1341`).
- The provider Price is minted with the same numbers (`:1427-1436`).
- `_update_catalog()` takes `price_pence` as a required argument with no default
  (`prospector/bridge.py:2166-2229`, reason stated at `:2177-2181`) so the catalogue write
  cannot invent a second source of truth.

There is a guard for republishing. `_resolve_money_rail()` (`prospector/bridge.py:1580-1647`)
reuses the live provider Price for a pack that has already sold, because Stripe idempotency keys
expire after 24 hours (`:1591-1600`). If the ladder now disagrees with the live price it **keeps
the live price and logs REPRICE REQUIRED** (`:1629-1640`). It refuses to silently apply the new
rung. The only legitimate mover is the price PATCH endpoint.

## A4. The store, the currency, and what the buyer sees

The catalogue entity is `store_platform/src/Store.Catalog/Domain/Pack.cs`. Relevant columns:
`PricePence` (`:8`), `PriceUsdCents` (`:65`), the drain floors `MinBillablePence` /
`MinBillableEffectiveAt` (`:31,35`) with `EffectiveFloorPence` at `:49-50`, and
`ProviderPriceId` / `IsListed` (`:99-100`).

On the internal publish call (`Program.cs:473`), `PricePence` is set **only on insert**
(`Program.cs:513`). On update it is deliberately untouched (`Program.cs:551-573`). A republish
can only move the provider price pointer, and only when that pointer is uncontested
(`Program.cs:573-591`).

Listing requires two things at once: content present, and the payment provider confirming it can
actually bill that price id (`Program.cs:659-680`). Separately, `MoneyRailConfigGate`
(`store_platform/src/Store.Api/Payments/MoneyRailConfigGate.cs:34-64`) fails the whole app closed
at boot if the Stripe keys, webhook secret or mode are missing, mismatched or placeholder.

Currency splits into two independent systems, and this is important:

- **What we actually charge.** `CheckoutEndpoints.ResolveBuyerCurrency`
  (`store_platform/src/Store.Api/Endpoints/CheckoutEndpoints.cs:183-191`) resolves currency on
  the server from the `Fly-Client-Country` header. It uses USD only if **every** pack in the
  basket has a `PriceUsdCents` (`:190`), otherwise GBP.
- **What we display.** `store_platform/src/Store.Web/src/lib/currency.tsx:34-49` defaults to GBP,
  and `formatPriceForMarket` in `lib/fx.ts:109-126` converts using a **courtesy** FX table
  (`BASE_RATES` at `fx.ts:43-50`, refreshed live and cached 24 hours at `:207-238`). The file
  says in its own header that this is never the actual charge (`fx.ts:6-7, :188-192`).
  `formatChargeNote` (`fx.ts:150-162`) discloses the true GBP amount at the point of purchase.

Verified by search: **Store.Web never reads `priceUsdCents` anywhere.**

```
$ rg -n "priceUsdCents|price_usd" store_platform/src/Store.Web/src
(no output)
```

So the US buyer sees a live FX estimate of the GBP rung, and is then charged the separately
declared `usd_rungs` value. Those two numbers come from different sources and nothing compares
them.

## A5. Changing a price after it is listed

One door only: `PATCH /internal/catalog/{id}/price` (`Program.cs:1071-1221`). It:

- re-verifies billability before writing if the pack is listed (`:1126-1145`)
- computes a drain fence: a price **cut** applies its new floor immediately, a **rise** holds the
  old floor for 26 hours (`Program.cs:1045, 1147-1186`). That is why `Pack.EffectiveFloorPence`
  exists (`Pack.cs:37-95`). A checkout session created before the rise must still be honourable.
- writes a `PackPriceHistory` row in the **same transaction** (`Program.cs:1191-1204`).

## A6. What is tested

Engine: `tests/test_pricing.py` (golden matrix), `tests/unit/test_pricing_monotonic.py` (depth
bands never run price backwards), `tests/unit/test_bridge_pricing.py` (provider Price and
catalogue row agree), `tests/test_price_comparables.py` (the full C3 evidence contract),
`tests/test_price_rationale.py`, `tests/unit/test_price_window.py`,
`tests/unit/test_payer_solvency_price.py`, `tests/unit/test_price_evidence_reachable.py`,
`tests/unit/test_price_history_tool.py`.

Store: `PricePatchTests.cs`, `PublishPricePointerTests.cs`, `PriceHistoryTests.cs`,
`Domain/PackPriceFloorTests.cs`, `Payments/MoneyRailConfigGateTests.cs`,
`Payments/BillablePriceGateTests.cs`.

Naming trap worth flagging: `tests/unit/test_record_usage_priced_gate.py` is about the cost of
LLM calls, not about pack pricing.

## A7. Pricing fragilities

1. **The USD ladder is stale relative to the GBP ladder.** `rungs` was cut from 7 entries to 5
   (`config.yaml:1868-1872` documents the cut) but `usd_rungs` still has 7
   (`config.yaml:1920`). `_usd_at` indexes positionally and guards the length
   (`prospector/pricing.py:160-173`) so nothing crashes, but the last two USD rungs are dead
   config that corresponds to no GBP rung. UNVERIFIED whether that was deliberate.
2. **The displayed USD price and the charged USD price are independently sourced and never
   reconciled.** Display is a live FX estimate (`lib/fx.ts:109-126`,
   `PackBuyButton.tsx:124`); the charge is the declared `usd_rungs` value baked into the Stripe
   Price at publish time (`prospector/bridge.py:1435`). Config allows a 7% publish time
   tolerance and the FX table is up to 24 hours stale on top. No test spans engine to browser for
   this number.
3. **`rung_adjust_enabled` is read in four places, each with its own default.**
   `prospector/price_comparables.py:100`, `prospector/price_rationale.py:95`,
   `prospector/pricing.py:266`, `prospector/pricing.py:340`. All four are `False` today. Nothing
   compares them, so a future edit to one is a silent divergence.
4. **The rule that anchors cannot vote on a depth banded price is enforced by control flow
   only.** The band branch returns before reaching the tier code
   (`prospector/pricing.py:254-258`). There is no shared guard. A reordering refactor
   reintroduces the exact inversion the ladder rewrite was built to remove
   (`prospector/pricing.py:11-27`).
5. **We collect real willingness to pay evidence and throw it away.** C3 is the most rigorously
   validated retrieval path we have, and `rung_adjust_enabled: false` means it has never once
   moved a price. That is a deliberate safety setting, but it means the ladder is currently
   priced on source count, which is a proxy for depth of research, not for value to the buyer.
6. **`market` is documented three times in three files as "never a pricing input"**
   (`prospector/pricing.py:322-330`, `config.yaml:1948-1951`, `Pack.cs:158-163`). The repetition
   is a tell that this was a real bug once. The fix is prose, not a structural guard.

---

# PART B. Content: every word we ship

## B1. The map. Four word sources, two enforcement lanes

This is the part the founder describes as "littered everywhere". It is accurate. Here is the
whole thing on one page.

**Four places words come from:**

| # | Source | Who writes it | Where it ends up |
|---|---|---|---|
| 1 | The model, at generation time | `prompts.py` prompts, run by the engine | pack title, one liner, shelf copy, pack body sections |
| 2 | Deterministic renderers | `prospector/pack_*.py`, template assembly, no model | the structured parts of the pack (tables, checklists, cards, reference lists) |
| 3 | Hand written site copy | the founder, in code | `Store.Web` pages, `lib/copyConfig.ts`, `lib/faqContent.ts`, `lib/disclaimer.ts` |
| 4 | Retrieved source text | the open web, quoted | quotes and citations inside packs |

**Two enforcement lanes, sharing rule names but not code:**

| | Pack lane | Storefront lane |
|---|---|---|
| Engine | `prospector/pack_linter.py`, Python | Vale, plus vitest, plus `scripts/doc_lint.py` |
| Runs on | a pack, in memory, at publish time | `.md`, `.ts`, `.tsx` files on disk |
| Can it stop a ship? | Yes. `report["ok"]` is ANDed into `is_listed` at `prospector/bridge.py:1094` | Only `dashFree.test.ts` and `doc_lint.py`, via CI |
| Runs automatically? | Yes, every publish | Vale: **no, never** |

**Vale cannot see a pack, and the pack linter cannot see the website.** Packs are assembled in
memory and zipped, so there is no file for Vale to read, and launchd's PATH does not carry
`/usr/local/bin/vale`. The two lanes share rule ids (R1, R2, R9 and so on) and that similarity is
misleading: a rule "existing" tells you nothing about whether it runs on the text you care about.

## B2. How a pack's words are actually made

**The prompts are files, not strings in code.** `prompts.render()`
(`prospector/prompts.py:229`) loads a Markdown file out of `prompts/`. Two of those files write
words a buyer reads:

- **`prompts/content_gen.md`**, called from `prospector/artifacts.py:1353`. It produces the
  `listing_page` object (title, headline, subhead, card_line), plus `teaser_social`,
  `seo_preview` and `launch_email`. Its constraints are written as prose inside the prompt:
  `card_line` has a "HARD LIMIT 60 characters" and one over that "is DISCARDED"
  (`prompts/content_gen.md:125`); `headline` is 10 to 15 words (`:100`); "Do NOT use a dash as
  punctuation anywhere" (`:95-96`); a list of banned hedge words including "potentially",
  "arguably", "relatively", "somewhat", "fairly" (`:48-50`); and a truth rule that no number or
  name may appear unless it is verbatim in a verified claim (`:6-18`).
- **`prompts/retitle.md`**, used by `tools/retitle_catalogue.py`. It produces `title`, `headline`
  and `card_line`. It states the title format `<what the business does> for <who pays>` (`:22`),
  bans a coined product name and a leading verb, and sets a hard character limit (`:85`).

**Everything else in the pack is deterministic.** All 15 `prospector/pack_*.py` modules assemble
Markdown, HTML, CSV or PDF from a dossier whose prose was already written upstream. A search
across all of them for a model client (`anthropic`, `openai`, `call_model`, `llm_client`,
`chat.completions`) returns zero hits.

| Module | What it renders | line |
|---|---|---|
| `pack_offer.py` | `The_Offer.md` | `:87` |
| `pack_field.py` | `The_Field.md` | `:308` |
| `pack_bear_case.py` | `What_Would_Sink_This.md` | `:239` |
| `pack_toolkit.py` | `The_Toolkit.md` | `:125` |
| `pack_kicker.py` | `How_To_Know_In_30_Days.md` | `:92` |
| `pack_checklist.py` | `05_First_Week_Checklist.md` | `:146` |
| `pack_reference.py` | the evidence page | `:87` |
| `pack_card.py` | `First_Fortnight.html` shelf card | `:126` |
| `pack_table.py` | `Assumptions.csv` | `:52` |
| `pack_data.py` | zero LLM buyer artifacts, plus `render_pdf` | `:1`, `:686` |
| `pack_html.py` | `index.html` from the 14 sections | `:131` |
| `pack_pdf.py` | `Complete_Pack.pdf` | `:664` |
| `pack_manifest.py` | `manifest.jsonld` | `:210` |
| `pack_floors.py` | claim safe fallback copy for empty fields | `:1` |
| `pack_validation.py` | completeness gate, not copy | `:1` |

`pack_checklist.py` is documented as deliberately model free (`prospector/bridge.py:1885-1892`,
"does NOT get a prose pass ... cannot make a model call at all") so that a pack bought today and
the same pack re-rendered tomorrow do not drift.

**The reading order** is one tuple, `BUNDLE_READING_ORDER` at `prospector/bridge.py:378-397`, 14
entries with the intent commented inline: the lede, then the offer, then the field, then the
numbers, then the case against at full strength, then the how, then the tools, then the kicker,
then the receipts. A warning at `prospector/bridge.py:286-295` notes the filenames are historical
and do not match that order.

**The repair scripts.** These are hand run, and they carry fixes the engine does not learn:
`tools/retitle_catalogue.py` (rewrites live titles into the 60 character format),
`tools/sweep_shelf_copy.py` (re-grades and rewrites shelved copy),
`tools/backfill_listing_copy.py` (replaces floor copy on packs with no `listing_page`),
`tools/site_wide_dash_cleanup.py` (rewrites dashes across storefront source),
`tools/backfill_bundle_html.py` (re-renders a listed pack's zip),
`tools/recover_stranded_passes.py` (recovers passes that never reached the shelf).

## B3. The house voice, and how much of it is actually enforced

`docs/HOUSE_WRITING_SPEC.md` is the normative voice document (status declared at `:1-2`). Its
own ledger at `:405-462` is unusually honest, and it is the single most useful page in this brief.
Of 15 rules, **13 are ADVISORY and 2 are enforced by nothing at all**.

ADVISORY has a precise meaning here, stated at `HOUSE_WRITING_SPEC.md:414-416`: the breach is
recorded in the pack's `.lint.json` receipt and the pack **ships anyway**.

Measured over the whole corpus on 2026-08-15, across 2,187 dossiers, 41,168 sentences and 1.16
million words:

| Rule | What it says | Breach rate | Enforcement |
|---|---|---|---|
| R1 | sentences under 28 words | **43.9%** over, mean 28.2 | advisory |
| R2 | no semicolons | 10.4% | advisory |
| R3 | one claim per sentence | not measured | **nothing** |
| R4 | no four item lists | 13.8% | advisory |
| R6 | (register rule) | 1.4% | advisory |
| R7 | no passive voice | not measured | **nothing** |
| R8 | (register rule) | 2.4% | advisory |
| R9 | banned business register | 4.1% | advisory |
| R10 | (register rule) | 0.1% | advisory |
| Q4 | attribution format | not measured | **nothing** |

R9's top offenders by count: `compounds` x354, `increasingly` x238, `wedge` x218, `moat` x208,
`at scale` x91, `ecosystem` x81.

**R1 has two different limits in two places and only the smaller one can block.** The spec says
28 words. `register_lint.LONG_SENTENCE_WORDS` says 25. The founder has deliberately deferred
fixing this, in their words: "we dont want catalogue unlisted, tackle this after". This is still
open.

R9 has been settled: `leverage` and `ecosystem` are unbanned, `leveraging` is banned, and `moat`,
`wedge` and `compounds` stay banned.

`docs/SITE_SPEC_PROGRAM.md` §5 carries a second, different voice standard for the **website**: a
Monzo style register, a "kitchen table test", and an explicit note that pack copy is held to a
different bar because a pack must keep and define load bearing domain terms. It also carries a
canonical vocabulary table (Catalogue not Catalog; pack not dossier or report or download;
killed and survived; the checks; the engine; evidence backed not grounded).

## B4. The title rule

`docs/SITE_SPEC_PROGRAM.md` §5.4 declares the format: `<what the business does> for <who pays>`,
60 characters or fewer, a noun phrase, no coined product name, comma never a dash, and the title
may not out-claim the description.

It is enforced by `pack_linter.check_title`. Two switches govern it:

```
config.yaml:1798   title_max_chars: 60
config.yaml:1803   title_block_on_breach: true
```

**This gate is ON.** It shipped OFF on 2026-08-09 because it errored on 46 of 48 live packs, and
was turned on on 2026-08-14 (`prospector/pack_linter.py:868-871`). Any brief that still says the
title gate is advisory is out of date.

The front end mirrors the rule independently, in `cardHeading` and `isBusinessFirstTitle` in
`store_platform/src/Store.Web/src/lib/discovery.ts`. That is a second implementation of the same
rule, in a different language, with no shared test.

## B5. The content contract programme: the diagnosis we already have

`docs/CONTENT_CONTRACT_PROGRAM.md` is a 416 line internal diagnosis of exactly the problem the
consultant is being asked about. The consultant should read it in full. The headlines:

**§1.1 The title and one liner are barely checked at generation time.** Only two checks exist:
the key is present (`prospector/generate.py:55`) and the combined length exceeds 50 characters
(`prospector/generate.py:599`). The first real judgement of those fields happens much later, at
`prospector/bridge.py:1102`, at publish time.

**§1.2 The retry loop cannot fix them.** The generation retry at `prospector/run.py:958` is
explicitly barred from the title and one liner fields (`prospector/run.py:700-703`).

**§1.3 The repair path swallows its own failure.** `_repair_title` (`prospector/run.py:697`) and
`_repair_one_liner` (`prospector/run.py:802`) catch failure, log "building the pack on its own
title, which the publish gate will refuse" (`prospector/run.py:793-798`), and then spend the
money building the pack anyway.

**§1.4 Rules get promoted by hand.** Each actuator is a separate config flag someone flips.
`lint_repetition_block` is still off (`config.yaml:1680`).

**§1.5 There are 13 hand run scripts in `tools/` that repair copy after the fact.** The document's
own summary of the problem: "the repair tool gets the fix. The engine does not"
(`prospector/run.py:895-897`).

**§1.6** Shipped does not mean in production.

The programme's ledger of what has been built (§5):

| | What | Status |
|---|---|---|
| P1 | `prospector/content_contract.py`, 21 declared rules | shipped |
| P2 | `prospector/field_write.py`, one grade then repair then re-grade choke point | shipped |
| P3 | | shipped |
| P4 | park unrepairable shelf lines | shipped, but measuring only. `listing.park_unrepairable_shelf_lines` is `False` (`prospector/config.py:597`, behaviour at `prospector/run.py:872-882`) |
| P5 | promotion path | shipped. The **ratchet is not built** |
| P6 | `prospector/ops/content_breaches.py` | shipped as a **reader only**. 123 receipts, 10,704 findings |
| P7 | | not started |

The measured breach table, from the same document. "Shadow" means recorded and shipped.

| Rule | % of packs breaching | findings | actuator |
|---|---|---|---|
| house_style | 98% | 4,633 | shadow |
| house_quote | 98% | 2,803 | shadow |
| human_register | 98% | 300 | shadow |
| register | 91% | 425 | shadow |
| grammar | 90% | 111 | **BLOCKING** |
| repetition | 86% | 1,600 | shadow |
| citation_urls | 69% | 254 | **BLOCKING** |
| register_repeat | 59% | 286 | shadow |
| shelf_copy | 50% | 110 | shadow |
| title_new_word | 41% | 51 | **BLOCKING** |
| title | 17% | 27 | **BLOCKING** |

`ready_to_promote` is empty. Nothing currently qualifies to be turned on.

Baseline of packs stranded unlisted by content faults: 34 (title 20, shelf_copy 15,
citation_urls 4, empty artifacts 2, placeholders 1, never gated 1).

## B6. The pack linter's severity contract

`prospector/pack_linter.py:11-12` states it plainly: an **error** blocks listing and the pack
registers UNLISTED for repair; a **warning** is recorded and does not block. The two constructors
are `_err` (`:73`) and `_warn` (`:77`), and most checks take a `block: bool` parameter that
chooses between them (for example `:199`, `:832`, `:884`).

The decision is one line: `report["ok"] = not any(p["severity"] == "error" ...)` at
`prospector/pack_linter.py:2101`. The publish gate ANDs that into `is_listed`
(`prospector/bridge.py:1094`).

Which checks may emit an error is threaded in as `block=` keyword arguments from `lint_pack()`
(`prospector/pack_linter.py:1902-1927`), wired from `cfg.listing` at
`prospector/bridge.py:1113-1200`. The current split:

- **Always blocking, no toggle:** `check_currency` (`:382`), `check_arithmetic` (`:468`),
  `check_sections` (`:627`), `check_placeholders` (`:575`), `check_marketing` (`:586`),
  `check_truncation` (`:645`), `check_house_dashes` (`prospector/copy_lint.py:111`).
- **Blocking by default:** `check_title` (`:831`), because
  `TITLE_BLOCK_ON_BREACH_DEFAULT = True` at `prospector/pack_linter.py:695`.
- **Advisory unless a config key turns them on:** `check_repetition` (`:198`, wired
  `prospector/bridge.py:1867`), `check_shelf_copy` (`:1319`, wired `bridge.py:1140-1141`),
  `check_engine_leak` (`:1264`, wired `bridge.py:1211`), and the whole house writing spec
  family of register, predictions, quotes and long sentence checks (wired
  `bridge.py:1176-1189`). The comment at `prospector/bridge.py:1177-1180` states the reason
  outright: 43.9% of engine sentences already break R1, so a style knob defaulting ON would
  unlist the catalogue.
- **Only runs if switched on:** `check_urls` (`:1821`), gated on `lint_check_urls`
  (`prospector/bridge.py:1136`). It is `true` on disk (`config.yaml:1621`).

Three config switches decide what blocks:

```
config.yaml:1621   lint_check_urls: true
config.yaml:1654   lint_grammar: true
config.yaml:1680   lint_repetition_block: false
config.yaml:1803   title_block_on_breach: true
```

Design note worth keeping: several checks are deliberately warnings because they cannot tell a
real defect from a style choice. The currency check is the clearest case
(`prospector/pack_linter.py:361, 400, 422-428`): a pack quoting a foreign price alongside the
buyer's own currency is fine, a pack showing **only** foreign currency is an error. Two of the
three currency blocks in the stranded set were false positives of the looser rule.

## B7. The storefront lane in detail

**Where site copy lives.** There is no CMS. Three mechanisms, mixed per page:

- Inline JSX strings, which is most of it. `Store.Web/src/pages/index.tsx` is 161KB. Also
  `pricing.tsx`, `faq.tsx`, `how-it-works.tsx`, `refund.tsx`, `terms.tsx`, `about.tsx`.
- `Store.Web/src/lib/copyConfig.ts:1-230`, a hand curated A/B/C variant dictionary. Its header
  declares the owner as the founder, with "no AI generation".
- Data from the engine over HTTP, consumed by `pages/pack/[id].tsx` and `pages/index.tsx`.
- Smaller modules: `lib/faqContent.ts`, `lib/disclaimer.ts` (`PACK_DISCLAIMER`), `lib/config.ts`
  (`LEGAL`, `FOUNDER`, `BRAND`).

**Which words on a pack page come from the engine.** Defined by the API boundary types at
`Store.Web/src/lib/api/client.ts:92-166` and `:167-172`: `title`, `oneLine`, `headline`,
`cardLine`, `theProblem`, `marketSize`, `whoPays`, `proofPoint`, `subhead`, `qaVerdictSummary`,
`whatYouGet[]`, `sampleExtract[]`, plus the facets and the financial snapshot. Everything else on
that page, including section headings, buy button labels, `RESEARCH_STATS` and the disclaimer, is
hand written in the web app.

**What actually checks the website's words:**

- `dashFree.test.ts` (`Store.Web/src/__tests__/dashFree.test.ts:1-20`) bans em and en dashes
  across every `.ts` and `.tsx` under `pages/`, `components/` and `lib/`. It runs in CI at
  `.github/workflows/ci.yml:666`. This is the only house style rule with real teeth on the
  website.
- `scripts/doc_lint.py` checks documentation, not marketing copy: broken referenced paths, empty
  referenced files, and providers named in docs that `config.yaml` does not select
  (`scripts/doc_lint.py:1-13`). It runs in CI at `.github/workflows/ci.yml:298`.
- `eslint` for Store.Web has architectural rules only, nothing about copy, and **is not run in CI
  for Store.Web**. `npm run lint` appears once in the whole workflow file, at
  `.github/workflows/ci.yml:728`, inside the separate `ops-console` job.
- `ops/config/retired_terms.yaml` is the banned name list. It is 85 lines long and declares
  **exactly one term**: `paddle`, at `ops/config/retired_terms.yaml:12`, with a reason and an
  allow list of paths where the string may legitimately still appear. Everything else in the
  file is explanation. `ops/automations/retired_terms.py` is a generic scanner over all git
  tracked files, so Store.Web is in scope by accident of being tracked rather than by design.
  It is invoked by hand or from an ops console button. No workflow calls it.
- **Vale is configured and never runs.** `.vale.ini` and `styles/Mumchimp/*.yml` exist. The only
  invocation is `scripts/copy_audit.sh:18-19`, which is itself only reachable from a manual ops
  console button (`prospector/ops/console_api.py:2694`).

```
$ rg -n "vale|copy_audit|retired_terms|pack_linter" .github/workflows/
.github/workflows/escape-hatch-drill.yml:55:  # goes red rather than a hand-rolled equivalent going green.
```

That single hit is a code comment. No CI job runs Vale, `copy_audit.sh`, `retired_terms` or the
pack linter.

**The gate chain before web copy reaches production**, in full:

1. CI `nextjs` job (`.github/workflows/ci.yml:616-676`): typecheck, then `npm test` (which
   includes `dashFree.test.ts`), then `npm run build`. No lint, no Vale, no retired terms.
2. `doc_lint` guard job (`:279-298`), docs only, and ratcheted.
3. `scripts/popdd_verify.py` is a local pre-commit proof runner, but **there is no pre-commit
   hook installed in this checkout** (`CLAUDE.md:122-147`), so it only runs if somebody
   remembers to type it.
4. `e2e-live-smoke.yml` runs Playwright against **production**, after deploy. It is a smoke test,
   not a gate.

## B8. Content fragilities

1. **Almost nothing about tone is enforced anywhere.** 13 of 15 house rules are advisory, 2 are
   enforced by nothing (`docs/HOUSE_WRITING_SPEC.md:405-462`). The measured breach rate for the
   headline rule, sentence length, is 43.9%.
2. **The two lanes cannot see each other's text.** Vale cannot read a pack. The pack linter
   cannot read the website. They share rule ids, which makes the coverage gap invisible from
   either side.
3. **Vale, `copy_audit.sh` and `retired_terms` are manual only.** A retired name can sit in live
   site copy indefinitely between hand runs.
4. **The title rule is implemented twice in two languages** (`prospector/pack_linter.py`
   `check_title`, and `isBusinessFirstTitle` in `Store.Web/src/lib/discovery.ts`) with no shared
   test.
5. **`nodash()` is implemented twice**, once in Python (`tools/make_kill_log.py`) and once in
   JavaScript (`Store.Web/src/lib/text.ts`), applied to every prose field on receipt at
   `lib/api/client.ts:235-260`. Kept byte identical by convention only.
6. **The engine cannot fix its own copy.** The retry loop is barred from the title and one liner
   (`prospector/run.py:700-703`), the repair helpers swallow their failures and build the pack
   anyway (`prospector/run.py:793-798`), and 13 hand run `tools/` scripts carry the fixes the
   engine never learns.
7. **The promotion ratchet was never built** (`docs/CONTENT_CONTRACT_PROGRAM.md` §5, P5). Rules
   move from shadow to blocking by a person flipping a config flag, judged by eye. Today nothing
   qualifies: `ready_to_promote` is empty.
8. **R1 has two ceilings, 28 in the spec and 25 in `register_lint.LONG_SENTENCE_WORDS`, and only
   25 can block.** Open by founder decision.
9. **The doc lint baseline hides 45 findings across 14 docs** and only fails on regression
   (`docs/doc_lint_baseline.json`, ratchet at `scripts/doc_lint.py:275-306`). Verified:
   `sum == 45`, `docs == 14`.
10. **`copyConfig.ts` asks for a contract test in its own header** (`:19-21`) and no such test
    exists.
11. **No pre-merge browser test covers a pack detail page.** The only browser level check on
    `/pack/[id]` is the post-deploy live smoke.
12. **The refund period "14 days" is written out three times** with no shared constant:
    `pages/refund.tsx:28,42`, `pages/pricing.tsx:250,272`, `lib/faqContent.ts:135`.

---

# PART C. Observations and suggestions

These are my recommendations, not decisions. Each names the specific fragility it addresses.

## C1. The core problem is not the rules. It is that grading and blocking are the same decision.

Today a rule is either off, advisory, or blocking, and moving between those states is a human
flipping a config flag. That is why 98% breach rates coexist with a shipping catalogue: turning
anything on would unlist the catalogue, so nothing gets turned on, so the breach rate never
falls.

The fix is a **ratchet**, which the content contract programme already specifies as P5 and never
built. Concretely: record the current breach count per rule as a baseline, block only on
regression against that baseline, and let a repair pass lower the baseline. This is exactly the
mechanism `scripts/doc_lint.py:275-306` already implements for docs. It works. It is one file,
and it should be generalised rather than reinvented.

The `doc_lint` baseline is also the counter-example: it hides 45 findings and nothing forces the
number down. A ratchet needs a **downward obligation** to be different from an amnesty. Suggest
pairing the baseline with a scheduled job that reports the number and refuses to let it sit flat.

## C2. Make the engine learn what the repair tools know.

Thirteen `tools/` scripts encode fixes the engine will make the same mistake about tomorrow. The
choke point already exists: `prospector/field_write.py` is a grade, repair, re-grade path. The
work is to route the title and one liner through it, which today's code explicitly refuses to do
(`prospector/run.py:700-703`).

The specific defect worth fixing first is `prospector/run.py:793-798`: the code logs that the
publish gate will refuse this pack, and then spends the money building it. That is a pure waste
loop and it is four lines.

## C3. Pick one enforcement lane for house style, not two.

Vale is configured, never runs, and structurally cannot see the highest volume text we produce.
The pack linter runs on every publish and cannot see the website. Two options:

- **Extend the pack lane.** Emit the pack's prose to a temp file and run Vale over it in the same
  publish step, or port the Vale rules into `register_lint`. Keeps one lane.
- **Drop Vale.** If nothing runs it and nothing will, delete `.vale.ini` and the styles rather
  than leave a rule set that looks like coverage.

Either is better than the current state, where "we have a style guide" is true and "the style
guide affects anything" is not. My recommendation is the first: the rules are written, the corpus
measurement exists, and only the plumbing is missing.

## C4. Reconcile the two USD prices.

This is the one pricing issue with a direct route to charging a buyer a number they did not see.
Store.Web renders an FX estimate and Stripe charges a declared rung, and nothing compares them.
Two cheap fixes, either sufficient:

- Ship `priceUsdCents` over the API and render **that** for a US buyer, so display and charge are
  the same number by construction.
- Or add a test that fails when the declared `usd_rungs` value drifts more than N% from the GBP
  rung at current FX, and run it on a schedule.

Also, `usd_rungs` has seven entries for a five entry GBP ladder. That should be resolved either
way before anyone reasons about it again.

## C5. Decide whether price evidence is decoration.

C3 is a genuinely strong piece of engineering: literal appearance validation, source id
resolution, config declared FX, median not mean, three anchors across two domains. It has never
moved a price. Either turn `rung_adjust_enabled` on behind the ratchet idea above and measure what
it does, or accept that price is set on research depth and stop paying for three extra retrieval
queries per pack.

## C6. Small structural guards worth adding

- One reader for `rung_adjust_enabled` instead of four independent defaults
  (`prospector/pricing.py:266,340`, `prospector/price_comparables.py:100`,
  `prospector/price_rationale.py:95`).
- A shared constant for `LONG_SENTENCE_WORDS` so the spec and the code cannot say 28 and 25.
- A shared constant for the refund period, read by all three web pages.
- A contract test for `copyConfig.ts`, which the file itself already asks for.
- Run `npm run lint` for Store.Web in CI. It is currently only run for the ops console.

## C7. What I would want to know next, and cannot answer here

- Whether the 43.9% long sentence rate is actually harming conversion. We have the breach data
  and the sales data and nobody has joined them. That join decides whether any of Part B matters
  commercially.
- Whether buyers at £29.99 and £99.99 behave differently. The ladder has five rungs and I found
  no analysis of realised conversion by rung.

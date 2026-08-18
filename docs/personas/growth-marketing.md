# Growth and marketing

**What this is.** Where growth can come from, what is measurably blocking it, and every surface a
visitor or a crawler can reach.

**Read this if** you are deciding what to build next for growth, or you want to know why a
catalogue with 2698 researched-and-rejected ideas has only 74 things on sale.

**The one-sentence answer.** Research is not the bottleneck. **74 of 108 packs that passed every
research gate cannot be sold, and 42 of those are blocked on shelf copy alone** — the constraint is
packaging, and it is mechanical work, not thinking.

---

## 1. The funnel, measured today

Every number below was produced by a command run this session. Nothing is estimated.

### 1.1 On disk

```
$ ls store/dossiers/ | wc -l                        2931
$ ls store/dossiers/*.kill.json | wc -l             2698
$ ls store/dossiers/*.pass.json | wc -l              108
$ ls store/dossiers/*.lint.json | wc -l              123
$ ls store/listings/*.json | wc -l                   119
$ ls -d publish/bundles/*/ | wc -l                   189
$ curl -s https://api.mumchimp.com/catalog | ...      74 rows
```

| Stage | Count | Conversion from previous |
|---|---|---|
| Ideas researched to a verdict | **2806** (2698 kills + 108 passes) | — |
| Passed every research gate | **108** | 3.8% |
| Bundles built | 189 | (includes re-renders and stranded work) |
| Listed locally | 119 | |
| **Live and buyable** | **74** | **68.5% of passes** |

**The number that matters: 34 of 108 passes are sellable.** From
`ops/automations/stranded_packs.py`:

```
FINDINGS — 74 of 108 passed packs cannot be sold (34 can).
    73  lint_failed
     1  never_linted
  blocked by these checks (packs affected):
      42  shelf_copy
      21  placeholders
      20  title
       6  citation_urls
       2  marketing_audience
       1  currency
       1  grammar
```

(The live catalogue shows 74 rows, more than 34, because it also carries older packs that predate
the current lint ruleset.)

### 1.2 Why ideas die

Kill gate distribution over all 2698 `.kill.json` files:

| Gate | Kills | Share |
|---|---|---|
| `moat_ungrounded` | 1042 | 38.6% |
| `min_composite` | 744 | 27.6% |
| `source_or_die` | 256 | 9.5% |
| `incumbency` | 254 | 9.4% |
| `adversarial_decisive` | 140 | 5.2% |
| `value_durability` | 112 | 4.2% |
| `payer_solvency` | 59 | 2.2% |
| `legality` | 30 | 1.1% |
| `distribution` | 18 | 0.7% |
| `currency` | 14 | 0.5% |
| `route_to_market` | 13 | 0.5% |
| `pain_reality` | 9 | 0.3% |
| `buyer_intent` | 7 | 0.3% |

**Nearly half of all kills are about our own retrieval, not about the idea.** `moat_ungrounded`
(1042) plus `source_or_die` (256) is 1298 of 2698, 48.1%. Those are ideas we could not find
evidence for. Some deserve to die. Some are a retrieval quality problem.

**HYPOTHESIS: a meaningful fraction of the 1042 `moat_ungrounded` kills would pass on a re-run
with better queries.** The check that would confirm or kill it: re-vet a random sample of 30
`moat_ungrounded` kills and count how many now find grounding. I have not run this. If even 10%
flip, that is 100 more candidate packs — more than the entire current shelf.

---

## 2. The bottleneck, stated plainly

**Packaging, not research.**

The two largest blockers, across all 123 lint receipts:

| Blocking error | Packs affected (of 108 passes) | Total occurrences across 123 receipts |
|---|---|---|
| `placeholders` | 21 | 68 |
| `shelf_copy` | 42 | 66 |
| `title` | 20 | 26 |
| `citation_urls` | 6 | 8 |
| `sections` | — | 6 |
| `marketing_audience` | 2 | 2 |
| `grammar` | 1 | 1 |
| `currency` | 1 | 1 |

`shelf_copy` is the one-line description on the shelf card. `placeholders` are unfilled template
slots. `title` is a title breaking the declared format. All three are **copy defects in
already-validated research**.

**The economics.** Every one of those 74 stranded packs has already cost its full research spend.
The idea survived seven checks. The bundle was built. It sits on disk, unsellable, because of a
sentence. Fixing a shelf line costs a fraction of researching a new idea, and there are 74 of them.

The repair path exists and is a console action:

```
python -m prospector.ops.console_api act shelf.repair_copy --preview  --payload '{...}'
python -m prospector.ops.console_api act shelf.repair_copy --confirm <token> --payload '{...}'
```

`stranded_packs.py` deliberately has **no `--fix`**. It reports. That is the "report mode before
fix mode" rule, and it is why the backlog is visible but not shrinking on its own.

See [content-management.md](content-management.md) §8 for the full lint picture.

---

## 3. The catalogue as a discovery surface

### 3.1 The facet vocabulary

Six closed facets, declared in three languages that must agree:

- `store_platform/src/Store.Web/src/lib/facets.ts` (281 lines)
- `prospector/facets.py`
- `store_platform/src/Store.Catalog/Domain/PackFacets.cs`

`src/lib/__tests__/facets.test.ts` (114 lines) reads `PackFacets.cs` **off disk** and asserts
value-for-value equality and the sizes 5/3/3/3/8/12 (`:49-62`). That test is the only thing
preventing a facet added in one language from being invisible in the other two.

| Facet | Line in `facets.ts` | Values |
|---|---|---|
| `ADVANTAGE` | `:23` | `code, nocode, sales, ops, audience` (5) |
| `PAYER` | `:24` | `b2b, b2c, b2g` (3) |
| `EFFORT` | `:25` | `automatable, part_automatable, hands_on` (3) |
| `COMMITMENT` | `:26` | `evenings, part_time, full_time` (3) |
| `MECHANISM` | `:27-36` | 8 values |
| `SECTOR` | `:37-50` | 12 values |

`MAX_ADVANTAGES = 3` (`:60`).

**Two rules from the header docstring, both load-bearing:**

> No facet is ever inferred from pack text.

> Absent means absent … `label()` returns null for an unknown code rather than prettifying it, a
> rendered guess is a claim nobody made.

A missing facet renders nothing. It does not render "Unknown" or guess from the title.

### 3.2 Live coverage, measured today

```
$ curl -s https://api.mumchimp.com/catalog | python3 -c "..."
rows 74
advantages: 63/74 (85.1%) values=5 {'sales': 42, 'ops': 25, 'code': 20, 'audience': 4, 'nocode': 1}
payer:      63/74 (85.1%) values=2 {'b2b': 34, 'b2c': 29}
effort:     74/74 (100.0%) values=3 {'part_automatable': 40, 'automatable': 24, 'hands_on': 10}
commitment: 58/74 (78.4%) values=3 {'part_time': 31, 'full_time': 16, 'evenings': 11}
mechanism:  66/74 (89.2%) values=8 {'vertical_tool': 22, 'productized_service': 18,
            'transaction_broker': 6, 'physical_ops': 5, 'picks_and_shovels': 4,
            'data_intelligence': 4, 'risk_financing': 4, 'audience_media': 3}
sector:     62/74 (83.8%) values=10 {'professional_services': 17, 'care_benefits': 10,
            'other': 9, 'trades_construction': 8, 'licensing_admin': 7, 'property_probate': 4,
            'employment_pay': 3, 'housing_rental': 2, 'creative_rights': 1, 'pets_animals': 1}
timeToFirstRevenue: 0/74 (0.0%)
```

| Facet | Coverage | Values used | Values unused |
|---|---|---|---|
| effort | **100%** | 3 of 3 | — |
| mechanism | 89.2% | 8 of 8 | — |
| advantages | 85.1% | 5 of 5 | — (`nocode` on 1 pack) |
| payer | 85.1% | **2 of 3** | `b2g` — **zero packs** |
| sector | 83.8% | **10 of 12** | `energy_planning`, `retail_inventory` — **zero packs** |
| commitment | 78.4% | 3 of 3 | — |
| `timeToFirstRevenue` | **0%** | — | the field never renders |

**Three concrete discovery gaps:**

1. **`timeToFirstRevenue` is 0 of 74.** The API returns the key on every row and it is always
   empty. A visitor asking "what can I earn from soonest?" has no answer. This is the strongest
   buying signal on the shelf and it is not populated.
2. **`b2g` has zero packs.** A whole payer segment. The filter exists and returns nothing.
3. **Two sectors are empty**: `energy_planning` and `retail_inventory`. `nocode` has one pack;
   `creative_rights` and `pets_animals` have one each.

**A facet value with zero rows is worse than no facet.** A visitor who filters to `b2g` gets an
empty shelf and concludes the site is thin.

### 3.3 A trap that cost time: two effort columns

`Store.Catalog/Domain/Pack.cs:149` declares `EffortTag` — the legacy field, values like
`medium`, `high`, `solo_operator`, `low`. `Pack.cs:187` declares `Effort` — the facet, values
`automatable`, `part_automatable`, `hands_on`.

**They are different columns.** Reading the wrong one makes the effort facet look dead. It is not:
it is the single best-covered facet at 100%.

`PackFacets.cs` records why: the facet *"Replaces the legacy `low|medium|high` mush, which was
never defined to mean this and must not be string-mapped into it."*

### 3.4 Market skew

```
market: {'uk': 54, 'us': 11, 'us-ga': 5, 'us-fl': 2, 'us-ca': 1, 'us-tx': 1}
```

**73% of the shelf is UK.** The US is 20 rows across five market codes, four of which have five
packs or fewer. A US visitor sees a thin shelf and four state-level slices with one or two items.

---

## 4. Price is still inverted against evidence

Measured today on the live shelf. `sourceCount` is how many sources back a pack.

| Price | Packs | Mean sourceCount |
|---|---|---|
| £19.99 | 2 | 19.5 |
| £29.99 | 17 | 36.4 |
| £49.99 | 30 | 31.1 |
| £79.99 | 16 | **39.8** |
| £99.99 | 9 | 36.6 |

Overall: min 16, mean 34.5, median 34.0, max 51.

**The relationship is not monotonic and it is not what a buyer would expect.** The £29.99 tier
carries more sources on average (36.4) than the £49.99 tier (31.1). The dearest tier, £99.99, is
not the best-evidenced.

`prospector/pricing.py` records the same finding historically: *"£29.99 -> 36.5 mean sources …
£149.99 -> 28.6 <- dearest tier, fewest sources"*.

**Why it happens.** Price is a rung, not a computed number. `config.yaml:1829` declares
`rungs: [1999, 2999, 4999, 7999, 9999]`. The rung is chosen by segment — `tier_rung_index`
(side_hustle 1, smb 2, growth 3, venture 4) plus `market_rung_offset` (uk 0, us 1) — with
`default_rung_index: 2` (`:1888`). **Ambition tier drives price. Evidence volume does not.**

`config.yaml:1860` declares `source_count_bands: [25, 30, 35, 45]`, and `comparables.enabled: true`
— but `comparables.rung_adjust_enabled: false`. **The mechanism to move a rung on evidence exists
and is switched off**, deliberately: the same flag for both would let the catalogue re-price itself
the day a feature merges.

**The marketing consequence.** "Every claim sourced" is the promise
(`TrustGuaranteesRow.tsx:84-91`). The price does not reflect how well sourced a pack is. A buyer
who compares two packs will find the cheaper one better evidenced about as often as not.

---

## 5. Every surface a visitor or crawler can reach

### 5.1 The home page

`store_platform/src/Store.Web/src/pages/index.tsx`. The live copy, quoted:

| Line | Copy |
|---|---|
| `:1719-1721` | "Business ideas that survived a filter built to kill them" |
| `:1732-1736` | "Browse the packs" (primary CTA) |
| `:1750` | "Read a full pack free, no email needed." |
| `:2143-2145` | "Every idea walks into a room built to destroy it." |
| `:2150-2153` | "A claim without a source dies before it reaches this shelf. Every pack here came out the other side." |

`components/marketing/TrustGuaranteesRow.tsx:84-91` renders three guarantees: **"14-day money
back"**, **"Every claim sourced"**, **"One-time payment, {price}"**. `:135-137` carries the
kill-log line.

### 5.2 The link-preview card

`pages/og/pack/[id].tsx`, 1200×630, rendered per pack with `next/og` (satori + resvg, both bundled
with Next — no new dependency) from `getServerSideProps` on the Node runtime.

- Headline `:176`: **"Survived every check it faced"**
- Title `:179-189`
- `EvidenceRunOg` `:78-114` — a run of ticks counted off the pack's own source count
- `proofLine` `:127-135` — *"built only from facts the pack page itself displays. Returns an empty
  string for a pack carrying neither, so the card shows no line rather than '0 sources'"*
- Price pill `:223`
- Brand `:200`

**Why it exists**, `:10-12`: *"Every pack page previously nominated the same generic `/og.png`, so
49 different products shared one image on X, LinkedIn, Slack, iMessage, and in the citation cards
AI assistants now render."*

**Two routing facts that are easy to break:**

- The route is **not** under `/api`. `next.config.ts` rewrites `/api/:path*` to the backend, and an
  array rewrite is evaluated after static pages but before dynamic routes, so `/api/og/pack/[id]`
  would lose to the proxy and 404 from the API (`:16-18`).
- `/og` is **not** in the robots.txt disallow list. `lib/seo/ogImage.ts:9-11`: *"A blocked og:image
  is the same as no og:image."*

**The cache-busting rule.** `DEFAULT_OG_IMAGE_PATH = '/og.png?v=2026-08-14'`. From
`ogImage.ts:37-48`: until 2026-08-14 `public/og.png` was the card of *a different product entirely*
("The Intro Exchange"), shipped in `5f95ca7` and never regenerated. Scrapers cache against the URL
and re-fetch over weeks. **Replacing the bytes without bumping `?v=` changes nothing anyone sees.**
Facebook's cache is only clearable by hand through its Sharing Debugger.

### 5.3 Sitemaps and robots

`pages/sitemap.xml.tsx`:
- `PUBLIC_PATHS` `:21-28`
- pack URLs `:95-105`
- landing pages `:107-116`
- **image sitemap** `:125` — the OG cards are submitted to Google as images

`pages/robots.txt.tsx`:
- disallows `:23-33`
- AI crawler rules `:48-59`
- sitemap pointer `:67`

### 5.4 Metadata

`components/Seo.tsx`:
- default description `:30-33`
- meta tags `:96-162`
- JSON-LD `:154-161`, injected via the only legitimate `dangerouslySetInnerHTML` on the site
  (`:159`)

`lib/seo/ogImage.ts` is one module so *"the route, the `og:image` meta, the Product schema, and the
image sitemap can never disagree about the URL, four call sites is exactly the number at which a
hardcoded string starts drifting."*

---

## 6. The kill log as marketing material

### 6.1 What it is

`pages/kill-log.tsx`, 649 lines. A dense monospace table over 400 records, with a distribution
chart, a cause filter and sorting. `pages/api/kill-log-detail.ts` (28 lines) serves the detail.

The page header comment states the thesis in three words: **"density is the argument"**.

The claim it makes is unusual and strong: we publish the ideas we rejected, with the gate that
killed each one. That is the receipt behind "a filter built to kill them".

### 6.2 What it currently says

`src/data/kill-log-totals.json`:

```json
{"killed": 1364, "passed": 80, "shown": 400,
 "byGate": {"min_composite": 624, "incumbency": 203, "moat_ungrounded": 191,
            "adversarial_decisive": 142, "value_durability": 83, "payer_solvency": 48,
            "source_or_die": 26, "legality": 16, "route_to_market": 8, "pain_reality": 7,
            "currency": 7, "distribution": 6, "buyer_intent": 3}}
```

Baked by `tools/make_kill_log.py`, which excludes kills whose only reason is a score below the bar.
`kill-log.json` is 503051 bytes.

### 6.3 It is stale, and by a lot

```
$ ls -la store_platform/src/Store.Web/src/data/kill-log*.json
kill-log-examples.json    76499   7 Aug 21:11
kill-log-names.json        9633   8 Aug 18:57
kill-log-totals.json        394   7 Aug 21:11
kill-log.json            503051   7 Aug 21:11
```

**Baked 7 August. Eleven days old today.**

| Figure | Published | On disk today | Understated by |
|---|---|---|---|
| killed | 1364 | **2698** | 1334 |
| passed | 80 | **108** | 28 |

**The single best marketing asset on the site is showing half the work.** Re-baking it is one
command and it doubles the headline number.

### 6.4 The number discipline behind it

`src/lib/stats.ts` holds `RESEARCH_STATS` and exists because of a real contradiction on
2026-08-06: `/kill-log` said *"We researched 1168 business ideas and rejected 89%"* while
`/how-it-works` said *"Of 1,313 ideas researched, 145 survived"*. Two pages, two numbers, same
site.

Now `researched` is an invariant: killed + survived. And the survivor count is **deliberately not
exported**, on a founder directive of 2026-08-13: *"saying 80 when only 50 are listed should never
happen regardless of the reasons why survivors are unlisted."*

**That directive is the §2 bottleneck showing up in the copy.** We cannot advertise how many ideas
survived, because most of the survivors are not on sale.

### 6.5 What `/ideas` deliberately does not show

`pages/ideas/index.tsx` shows **no survival rate** and **no representative kill per category**,
because the kill log carries no facet. There is no honest way to say "we killed 40 ideas in your
sector" when the kill records are not sectorised.

**That is a real gap.** A per-sector kill count would be the most persuasive thing on a sector
landing page.

---

## 7. Storefront traps, each verified in code

### 7.1 The site renders no markdown

```
$ rg '"(marked|react-markdown|remark|markdown-it|rehype)' \
     store_platform/src/Store.Web/package.json
(no hits)
```

No markdown library is installed. `dangerouslySetInnerHTML` appears exactly twice: `Seo.tsx:159`
(JSON-LD) and `PopulationField.tsx:135` (marks generated from two integers).

**For anyone writing marketing copy: asterisks render as asterisks.** Every emphasis is a React
element and a CSS class.

### 7.2 An entrance fade delayed LCP

`src/styles/tokens.css:829`: *"`fade-in-up` (20px of travel over 800ms) is deleted"*. `:833-838`
replaces it with `--animate-fade-in/rise/settle` at 0.24s. `:836-837`: *"hero must not fade. Use
`animate-settle` on anything that can be a route's LCP element."*

Measured with `scripts/design-audit/measure-lcp.mjs`, recorded at `:852-865`, including:

```
/pricing 180ms 180ms ONE candidate -- no PageHero, no animate-rise
```

and the conclusion: *"the metric was waiting on a fade"*.

`src/styles/globals.css:69-75` still holds the `fadeIn` keyframes at 0.4s. Do not apply them to a
hero.

### 7.3 `overflow-hidden` killed every descendant sticky

`pages/pack/[id].tsx:1420-1422`:

> THIS RAIL ONLY STARTED STICKING ON 2026-08-14. `sticky top-24` had been here for months and
> computed as `sticky`, but `SectionBand`'s inner div was `overflow-hidden`.

Same note at `components/marketing/PackSpecimen.tsx:252-254`.
`components/marketing/blocks.tsx:76` now mandates `overflow-clip` and never `overflow-hidden`.

**A sticky buy-rail that silently does not stick is a conversion defect that looks like a design
choice.** It was live for months.

### 7.4 The API rate-limits its own storefront

`Store.Api/Infrastructure/RateLimitPolicy.cs`. Three partitions: `/webhooks` unlimited,
`/catalog/waitlist` at `DefaultWaitlistPermitPerMinute = 5`, everything else per-IP at
`DefaultPermitPerMinute = 120`.

The docstring:

> Known blind spot — the storefront is not "an IP" (measured 2026-08-06) … ALL SSR traffic for the
> whole site shares ONE partition. A pack page costs two calls (`fetchPackDetails` +
> `fetchCatalog`, `Store.Web pages/pack/[id].tsx:1083-1086`), so at the 120 default the storefront
> begins throttling itself at roughly 60 page views a minute — and the visitor is served a 503
> error page, because `pages/pack/[id].tsx:1112-1118` maps any non-404/410 to
> `res.statusCode = 503`.

Mitigated by the Fly secret `RateLimiting__PermitPerMinute=600`, roughly 300 page views a minute.
**The structural fix is not done.**

**This is a growth ceiling.** Any successful campaign, any front-page link, any AI assistant
citing several packs at once, hits it. At 300 page views a minute the site starts serving 503s to
real visitors, and there is no alert on it.

---

## 8. Conversion: what is measured, honestly

**One confirmed event.** `pages/orders/success.tsx:122-126` calls
`track('checkout_completed', sessionId)`. The tracking module is `src/lib/analytics.ts`.

That is the bottom of the funnel. Everything above it — impressions, catalogue views, pack views,
filter use, buy-button clicks, checkout starts, checkout abandonments — I could not prove is
instrumented.

**HYPOTHESIS: pack page views and buy-button clicks are not tracked.** The check that would
confirm or kill it: `rg -n "track\(" store_platform/src/Store.Web/src/` and enumerate every event
name. I did not run it exhaustively enough to state a count.

**What this costs.** With only `checkout_completed`, you cannot answer:

- Which facet filters do visitors actually use? (See §3.2 — you cannot tell whether `b2g`'s
  emptiness is costing anything.)
- Do people who read a free pack buy a different one?
- Where in the checkout do people drop?
- Is the sticky buy rail (§7.3) working now that it sticks?

The success page does carry a cross-sell (`success.tsx:153-159`: same market, exclude the pack just
bought, top 3 by sourceCount). Whether it converts is not measured.

---

## 9. What to build next, three items with evidence

### 9.1 Clear the 74 stranded packs

**Evidence:** `stranded_packs.py` — 74 of 108, blocked by 42 shelf_copy / 21 placeholders /
20 title.

**Why first:** the research spend is already sunk. These are finished products behind a sentence.
Clearing them roughly doubles the shelf, from 74 live rows toward 108. Every other growth lever
multiplies against shelf size.

**Cost:** mechanical. The repair action already exists (`act shelf.repair_copy`). The work is
per-pack copy, and the linter tells you exactly which check failed for each.

**Risk:** none to the money rail. `shelf.repair_copy` is a preview-then-confirm write and cannot
touch price.

### 9.2 Re-bake the kill log

**Evidence:** published 1364 killed / 80 passed, baked 7 August. On disk today: 2698 killed / 108
passed. Understated by 1334 kills.

**Why:** the kill log is the proof behind the site's central claim. Doubling its headline costs one
run of `tools/make_kill_log.py`.

**Cost:** one command plus a deploy.

**Do this at the same time:** add a sectorised kill count, so `/ideas` can finally show a
representative kill per category. `pages/ideas/index.tsx` omits it today only because the kill
records carry no facet.

### 9.3 Populate `timeToFirstRevenue`

**Evidence:** 0 of 74 live rows carry it. The API returns the key on every row and it is always
empty.

**Why:** "how soon could this pay?" is the strongest buying signal on a shelf of business ideas,
and it is the one field with zero coverage while every other facet is 78-100%.

**Cost:** unknown until the source is identified. **HYPOTHESIS: the value is derivable from the
financial model already in the pack** (`pack_data.py` renders the financial model, 915 lines). The
check that would confirm or kill it: open
`store/dossiers/142717e797740247.pass.json` and the pack's financial section and see whether a
time-to-first-revenue figure is already computed. If it is, this is a plumbing job, not a research
job.

**Runners-up, with their evidence:**

- **`b2g` and two empty sectors** (§3.2). Generation is not targeting them. Fixing this is a
  generation-side change, not a marketing one.
- **Fix the SSR rate-limit partition** (§7.4). It is a hard ceiling at ~300 page views a minute and
  it has no alert.
- **Instrument the funnel above `checkout_completed`** (§8). Every decision above is currently made
  on structural evidence rather than behavioural evidence.

---

## 10. Invariants — what must stay true

| Invariant | Where enforced | What breaks |
|---|---|---|
| The facet vocabulary is identical in three languages | `facets.test.ts:49-62` reads `PackFacets.cs` off disk | A facet exists in one language and is invisible in the others |
| No facet is inferred from pack text | `facets.ts` header docstring | The site makes a claim nobody verified |
| An unknown facet code renders nothing | `label()` returns null | A prettified guess reads as a fact |
| Every site number comes from `stats.ts` | `src/lib/stats.ts` | Two pages contradict each other, as on 2026-08-06 |
| `researched` = killed + survived | `stats.ts` invariant | The headline stops adding up |
| The survivor count is never published | founder directive 2026-08-13 | We advertise 108 while 74 are buyable |
| `?v=` bumps when `og.png` changes | `ogImage.ts:48` | Every warm scraper cache shows the old brand |
| `/og` stays out of robots disallow | `ogImage.ts:9-11` | Every link preview disappears |
| No `overflow-hidden` on a section wrapper | `blocks.tsx:76` | Sticky rails silently stop sticking |
| No fade on an LCP element | `tokens.css:836-837` | LCP waits on the animation |
| Price is a rung, never a computed number | `config.yaml:1829`, `pricing.py` | Price drifts from the Stripe Price object |

---

## 11. Where to look next

- [content-management.md](content-management.md) — the lint gates that strand the 74 packs, and
  every renderer that produces the words.
- [support.md](support.md) — what happens after a visitor converts, and the rate-limit blind spot
  from the other side.
- [buyer.md](buyer.md) — the same shelf described to the person buying from it.
- [../ESTATE_MAP.md](../ESTATE_MAP.md) — where each surface in this document lives.
- `docs/SITE_SPEC_PROGRAM.md` — the storefront design, UX and copy spec plus its live status
  ledger. Read it before changing the storefront.

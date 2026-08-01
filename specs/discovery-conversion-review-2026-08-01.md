# STORY: Tag the shelf before you relabel it — depth review of the 2026-07-31 design email

**Date:** 2026-08-01 · **Repo:** `prospector` · **Surface:** `prospector/` (engine),
`store_platform/src/Store.Api`, `store_platform/src/Store.Web`
**Reviews:** design/UX/marketing email, chidionyema@gmail.com, 2026-07-31 15:02
**Supersedes for discovery scope:** nothing. Builds on `specs/discovery-ux-2026-07-30.md`,
which shipped the facet system this review measures.

Every claim below carries a `file:line` or pasted command output. Live measurements are from
`GET https://api.mumchimp.com/catalog` pulled 2026-08-01 (HTTP 200, 59096 bytes, 49 packs).
Anything unproven is marked **HYPOTHESIS** with the probe that would settle it. Process and
legal risks are labelled as such, never dressed up as quality verdicts.

---

## Part 0 — The one thing that changes the plan

The email proposes renaming the six filters, adding a seventh, and building a matchmaker.
**Two of those three are already built.** The email's own premise — "this is scoped entirely
as frontend UI, UX, and state-management work" — is false, and the reason it is false is the
finding that should reorder the whole roadmap:

> **The filters are not under-labelled. They are under-populated.**

Measured on the live catalogue this morning:

| Facet | Packs carrying it | Effect of a buyer selecting any value |
|---|---|---|
| `effort` | 34/49 (69%) | 15 packs vanish |
| `sector` | 33/49 (67%) | 16 packs vanish |
| `payer` | 33/49 (67%) | 16 packs vanish |
| `mechanism` | 32/49 (65%) | 17 packs vanish |
| `advantages` | 29/49 (59%) | 20 packs vanish |
| `commitment` | **22/49 (45%)** | **27 packs vanish** |
| `market` | 12/49 (24%) | — (boost, not filter) |
| `timeToFirstRevenue` | **0/49** | dead field on the wire |

```
fully tagged on all 6 facets: 21/49 (43%)
facets carried per pack: {0: 15, 2: 1, 3: 1, 4: 3, 5: 8, 6: 21}
```

**15 of 49 packs (31%) carry zero facets.** By the deliberate null rule at
`store_platform/src/Store.Web/src/lib/facets.ts:18` — "an untagged pack renders no chip and
appears only under All" — those 15 packs are unreachable through every filter, and invisible
to the Matchmaker entirely. They are not broken; they are *absent*. That rule is correct and
must not be softened (it is what stops the storefront inventing claims). The fix is to tag the
packs, not to loosen the rule.

Two of the 15 are named in the email itself:

> "Ensure blueprints like **DLAChild** or **IHT Valuation Barometer** are explicitly tagged
> with the Regulatory Knowledge moat on their respective UI cards."

Both carry **no facets at all** — not sector, not payer, not effort, not commitment, not
mechanism, not advantages. The email asks for a seventh tag on two packs that have none of the
first six. Adding a `moat` facet today would launch at 0% coverage and render nowhere.

### The worst live defect, which the email does not mention

```
advantage totals across all 49 packs: {'ops': 17, 'code': 13, 'sales': 12, 'audience': 1}
```

`nocode` is **0 packs out of 49**. It is a defined vocabulary member (`facets.ts:23`) and the
Matchmaker maps its most sympathetic answer onto it — `{ text: 'None of these yet', advantage:
'nocode' }` (`components/discovery/Matchmaker.tsx:43`).

Matchmaker reachable pool, Q1 × Q2, measured live:

```
  code      evenings ->  2   code      part_time ->  7   code      full_time -> 0
  sales     evenings ->  2   sales     part_time ->  8   sales     full_time -> 1
  ops       evenings ->  3   ops       part_time ->  9   ops       full_time -> 1
  audience  evenings ->  1   audience  part_time ->  0   audience  full_time -> 0
  nocode    evenings ->  0   nocode    part_time ->  0   nocode    full_time -> 0
```

A buyer who answers **"None of these yet"** — the least confident, most guidance-hungry, most
persuadable visitor on the site — gets **zero matches on every path through the router**. The
component is honest about it (`Matchmaker.tsx:26` routes a zero score to the near-miss state
rather than fabricating a winner), so it degrades gracefully rather than lying. But the single
highest-intent funnel on the storefront terminates in "nothing for you" for an entire buyer
class, and no amount of relabelling touches it.

`audience` (1 pack) and `full_time` (2 packs total) are the same defect one order less severe.

**Therefore: coverage before vocabulary, and coverage before any seventh facet.** That is the
improvement on the email, and it is why this is one story about data and not five about CSS.

---

## Part 1 — Verdict on every ask in the email

| # | Ask | Verdict | Proof |
|---|---|---|---|
| **US1** | Rename filters to "Founder Skillset", "Time Commitment", "Target Market", "Tech Enablement", "Revenue Model", "Industry Vertical" | **REJECT** — reverses a documented decision, and the proposed option values are a different taxonomy requiring an engine + API + re-tag | `facets.ts:190-193`, `facets.ts:120-137` |
| **US2** | Replace checkboxes with pills | **ALREADY SHIPPED** — there are no checkboxes; they are `rounded-full` pill buttons with live counts | `FacetBar.tsx:49-63` |
| **US2** | Instant client-side filtering, no reload | **ALREADY SHIPPED** | `FacetBar.tsx:82-91`, `lib/discovery.ts` `filterPacks` |
| **US2** | Progressive disclosure — collapse all but top 3 | **PARTIAL / better mechanism exists** — empty groups already self-hide; mobile collapses to one button | `FacetBar.tsx:79-89`, `:177-212` |
| **US3** | Zero-state with alternatives, no blank screen | **ALREADY SHIPPED, exceeds the ask** — near-miss names the failing constraint and offers a one-tap relaxer, then a consent-versioned waitlist | `components/discovery/EmptyState.tsx:9-16`, `discovery.ts:327-380` |
| **US4** | New "Moat Type" filter | **DEFER** — would launch at 0% coverage; needs engine + C# vocab + migration + backfill of 49 packs. Not frontend work | Part 0; `facets.ts:4-10` |
| **US5** | "Find My Blueprint" 3-question matchmaker | **ALREADY SHIPPED** | `Matchmaker.tsx`, wired at `pages/index.tsx:499,515` |
| **US5** | Q1 = "realistic starting budget (£500 / £2k)" | **REJECT as specified** — no budget/capital facet exists in any of the three vocabularies; it is not a relabel, it is a new engine field | `facets.ts:23-50` |
| **US5** | "Loading spinner for 1-2 seconds for dramatic effect" | **REJECT** — deliberately fabricated latency on a brand whose position is receipts | see Part 3 |
| **§1** | Serif headings (Newsreader / GT Super) | **REJECT** — serif was deliberately deprecated and mapped to sans | `styles/globals.css:101` |
| **§1** | Inter/Geist for UI, muted off-blacks, 4/8px rhythm | **ALREADY SHIPPED** | `globals.css:100`, `:111`, token block `:100-115` |
| **§2** | Remove card borders, ghost hover | **CONFLICTS with an in-flight spec** — `specs/storefront-institutional-polish.md` specifies 1px borders + `translateY(-2px)` hover | that spec, "Design contract" 2 |
| **§4** | Keep checkout in-context, Stripe Elements, no isolated page | **ALREADY SHIPPED** — embedded panel over the pack page | `pages/pack/[id].tsx:112,309`, `components/checkout/EmbeddedCheckoutPanel.tsx:31` |
| **§4** | Slide-out drawer from the *catalogue* | **OPEN / worth building** — today it requires a navigation to `/pack/[id]` first | `pages/index.tsx` has no drawer |
| **📈** | Gate the free sample behind an email | **REJECT as specified** — breaks a promise printed on the homepage | `pages/index.tsx:697` |
| **📈** | Price anchor ("Agency research £3,500 vs £49") | **ACCEPT with sourcing** — genuinely absent; grep for anchor copy returns nothing | Part 4, S4 |
| **📈** | "Only 4 packs left at this verification level" | **REJECT — legal risk, see Part 3** | Part 3 |
| **📈** | Upsell kit / £29-a-month Pro tier | **OUT OF SCOPE** — new products, new fulfilment, new money rail |
| **🧠** | "Lead with outcome, then mechanism, then proof" on cards | **ACCEPT** — the strongest UX idea in the email, and cheap | Part 4, S3 |
| **🧠** | Blueprint opens with a 10-minute micro-win | **ACCEPT** — engine/content change, high retention value | Part 4, S5 |

**Counts in the email are stale.** It variously says 42, 46 and 47+ packs; live is **49**.

---

## Part 2 — What is already shipped (do not rebuild)

An agent picking this up will otherwise re-implement four working systems. They are:

1. **The facet contract** — six closed vocabularies mirrored across Python
   (`prospector/facets.py`), C# (`Store.Catalog/Domain/PackFacets.cs`) and TypeScript
   (`lib/facets.ts`), held in sync by a test that reads the C# off disk and asserts
   value-for-value equality (`facets.ts:4-10`, `lib/__tests__/facets.test.ts`).
2. **The filter bar** — pills, live counts, self-hiding empty groups, "All" always first,
   mobile sheet with focus trap inherited from `Modal` (`FacetBar.tsx`).
3. **The Matchmaker** — 3 questions, multi-select Q1 capped at 2, "Don't mind" distinct from
   skipped, reason sentences built only from facets that actually scored, and a hard rule
   against producing a winner when nothing matched (`Matchmaker.tsx:26,37-64,97-108`).
4. **Near-miss → waitlist** — with `WAITLIST_CONSENT_TEXT` hashed by the API as evidence of
   what was consented to, and a pinned `waitlist-2026-07-30` consent version
   (`EmptyState.tsx:20-25`).

The email's US2, US3 and US5 are, in substance, a request to build these. They exist.

---

## Part 3 — What must not be built, and why

These are the asks where doing what the email says would cost more than it earns. Each is
rejected on a stated failure mode, not on taste or on "blast radius".

### 3.1 Fabricated scarcity — **legal risk, hard gate**

> "Only 4 packs left at this verification level" / "Price increases when 50 packs are sold"

A dossier is an infinitely-copyable digital good. There is no stock, so "4 left" is not a
stretch — it is a false statement of fact shown to a consumer to force a decision. The
storefront is UK-facing (prices in £, `market:'uk'` on 10 of 12 tagged packs, content about
HMRC/DVSA/DWP).

**Legal risk — requires confirmation by a solicitor, not by this document.** Falsely stating
that a product is available only for a very limited time, or falsely stating limited
availability, in order to elicit an immediate purchase decision, is on the face of it a banned
practice under UK consumer protection law (CPUTR 2008 Sch. 1; carried into the Digital
Markets, Competition and Consumers Act 2024 unfair-practices regime). **HYPOTHESIS** on the
exact statutory cite and current commencement — the probe is a solicitor's opinion or the CMA's
published guidance on urgency claims; I have not retrieved either, and this document does not
rule on it. What is *not* hypothetical is that the claim would be untrue.

There is also a self-inflicted contradiction worth naming plainly: `legality` is one of the six
checks this engine runs on every idea it sells (`CLAUDE.md`, "The filter is universal"). Running
a false-scarcity banner while selling legality-vetted business plans is the one marketing tactic
that can discredit the product itself.

**Honest substitutes that create real urgency:** show the true `verifiedAt` date and let staleness
speak; show the real `sourceCount`; show genuine catalogue movement ("6 packs added this month")
if and only if it is computed from data.

### 3.2 Gating the free sample behind an email

The homepage prints, at `pages/index.tsx:697`:

> "A whole dossier, unredacted, every source clickable. **No payment, no email.**"

The email calls this "a beautiful, noble sentiment, but a marketing tragedy" and asserts it loses
"90% of your warm traffic". **That 90% figure is unsourced and is exactly the kind of number this
project refuses to ship** (`CLAUDE.md`: source-or-die). The trade is real and worth testing — but
the version that breaks a printed promise is the wrong version of the test.

**Do this instead (S4):** keep the sample ungated exactly as promised, and add a *voluntary*
capture with its own value exchange — "email me when a pack ships in my sector" — reusing the
waitlist rail that already exists with consent versioning (`EmptyState.tsx:20-25`). That captures
intent without retracting a promise, and it is measurable against the current baseline.

### 3.3 The theatrical loading spinner

> "Display a loading spinner for 1-2 seconds for dramatic effect."

The match is computed synchronously in the browser from data already in memory
(`discovery.ts` `rankMatches`). A 1-2s delay is fabricated work shown to imply analysis that did
not happen. Same objection as 3.1, one order milder: this brand's entire differentiator is that
the work behind a claim is real. A 150ms result transition is polish; 1.5s of fake computation
is a small lie told in the one place the buyer is deciding whether to trust us.

### 3.4 Reintroducing a serif

`globals.css:101` reads `--font-serif: var(--font-sans); /* Deprecate serif, map to sans */`.
This is a live decision, not an oversight. **Process note, not a quality verdict:** there is also
scar tissue here — a previous serif wiring shipped a `var()` that resolved against a scope with no
value, so the webfont downloaded for months and never rendered. Any reversal must be proven with
`getComputedStyle` on a heading, body, *and* mono element, not from `document.fonts`.

### 3.5 Renaming the six filter headings

`facets.ts:190-193` states the reasoning:

> "Each one names the question the buyer is answering about themselves, not the database column
> — 'Sector' told a buyer nothing about what clicking would do."

The email proposes moving from buyer-question phrasing back to database-column phrasing
("Industry Vertical", "Tech Enablement"). That is a legitimate disagreement about register — but
it is a *reversal*, so it needs a reason stronger than "sounds more professional", and the burden
is on the new claim. **The deeper problem is the option values, not the headings:** "Revenue Model
(One-off Fee, Monthly Retainer, SaaS Subscription, Commission, Arbitrage)" is a *pricing* taxonomy;
the shipped `mechanism` vocabulary is a *business-model* taxonomy (`productized_service`,
`transaction_broker`, `picks_and_shovels`…). Swapping one for the other means editing three
language vocabularies in lockstep and re-tagging 49 packs. It is not a rename.

**HYPOTHESIS worth testing cheaply:** headings are the one genuinely reversible piece here. A
copy A/B on headings alone — same codes, same values, `KIND_LABEL` only — would settle register
with data instead of assertion. `KIND_LABEL` is deliberately the single home for these strings
(`facets.ts:85`), so the test costs one file.

---

## Part 4 — The stories, in the order that earns the most

### S1 — Backfill facets on the 28 under-tagged packs · **P0, highest value on the page**

The Matchmaker, the filter bar and the near-miss state are all already built and all
under-fed. This is the only story that makes the other three work.

**AC-1.1** Every pack in the live catalogue carries `sector`, `payer`, `effort`, `commitment`,
`mechanism`, and ≥1 `advantages`. Target ≥95% on each facet (from 45-69%); zero-facet packs → 0
(from 15).
**AC-1.2** Tags are derived by the engine from the dossier's own evidence, through the same path
that tagged the 21 fully-tagged packs — **not** hand-written in the API, and **not** regex-guessed
from title text. The regex-guess failure mode is documented at
`specs/discovery-ux-2026-07-30.md` Part 0 (it published a metal-fabrication tool as a *gardening*
business) and its module was deleted for it.
**AC-1.3** A pack the engine cannot tag with confidence stays untagged. The null rule
(`facets.ts:18`) holds; absent still means absent.
**AC-1.4** `nocode` is either genuinely earned by ≥3 packs or **removed from the vocabulary in all
three languages**, and `Matchmaker.tsx:43`'s "None of these yet" is re-pointed. Shipping a
vocabulary member that matches nothing is the defect; either side of the fork fixes it.
**AC-1.5** Same for `audience` (1 pack) and `full_time` (2 packs): earn it or retire it.
**AC-1.6** `timeToFirstRevenue` is on the wire at 0/49. Populate it or remove it from the
contract — a field that is always null is a promise the API is not keeping.
**AC-1.7** Re-run the Part 0 measurement and paste the output. No story below is "done" while
the pool for any Matchmaker path is 0.

**Process risk:** this touches the engine and the prod catalogue DB. Per the checkpoint, the
`/internal/catalog/{id}/content` door is blocked behind an undeployed API
(`Deploy Store.Api` run 30682753318, Fly token scoped to the wrong app). Facet writes need a
door too — confirm which one exists before starting, and do not assume `PATCH .../content`
covers facets.

### S2 — Fix what a filter does to untagged packs · **P0, ships with S1**

Even at 95% coverage the null rule means selecting a facet hides untagged packs silently.
Today a buyer cannot tell "no pack matches" from "we haven't sorted these yet".

**AC-2.1** When a filter is active and ≥1 pack is excluded *only* because it is untagged on that
facet, the grid shows an honest footer: "N packs aren't sorted by {KIND_NOUN} yet — show them".
**AC-2.2** That control is one tap and reversible.
**AC-2.3** It renders only when N > 0, and disappears entirely once S1 lands. It is scaffolding
for the transition, not a permanent feature — say so in the component doc.

### S3 — Card hierarchy: outcome, then mechanism, then proof · **P1, best idea in the email**

**AC-3.1** The card leads with the buyer outcome, then the product name, then the proof
(`sourceCount`, `verifiedAt`).
**AC-3.2** The outcome line comes from an existing dossier field. If no such field exists, this
story stops and becomes an engine story — it does **not** get written by hand per pack, and it
does **not** get inferred in the browser.
**AC-3.3** `splitTitle` still handles em dash, en dash and hyphen (`lib/__tests__/splitTitle.test.ts`).

### S4 — Honest price anchor + voluntary capture · **P1**

**AC-4.1** An anchor appears on the pack page comparing £49 to a **sourced** market rate for
equivalent research, rendered with its citation visible, exactly like every other claim on the
site. No source → no anchor. The email's "£3,500" is unsourced and may not ship as-is.
**AC-4.2** The sample stays ungated; `index.tsx:697` copy is unchanged.
**AC-4.3** A voluntary "tell me when a pack ships in my sector" capture reuses the waitlist rail,
including `WAITLIST_CONSENT_TEXT` and consent version (`EmptyState.tsx:20-25`).

### S5 — Micro-win as the blueprint's first page · **P2, retention**

**AC-5.1** Every generated pack opens with one concrete action completable in ~10 minutes.
**AC-5.2** It is generated from the dossier's own evidence and carries a source, like everything
else. Engine change (`prospector/`), not a template string in the web app.

### S6 — Catalogue-level checkout drawer · **P2**

**AC-6.1** Buying from the shelf does not require a full navigation to `/pack/[id]`.
**AC-6.2** It reuses `EmbeddedCheckoutPanel` and `resolveStripeCheckout` unchanged — the
"embedded is preferred but never required" fallback is unit-tested for every failure path
including a throw (`pages/pack/[id].tsx:96-112`) and **must not be re-implemented**.
**AC-6.3** Money-rail change → Claude-only per the founder fence; do not delegate.

### S7 — Heading register A/B · **P3, only if someone still wants US1**

**AC-7.1** `KIND_LABEL` values only. No code, vocabulary, or `KIND_NOUN` change (`facets.ts:214-221`
exists because headings and nouns are not interchangeable).
**AC-7.2** Ships with a measurement, or does not ship.

**Deferred:** US4 "Moat Type" — revisit only once S1 has every pack tagged on the existing six.
Its trigger is explicit: `advantages` ≥95% coverage sustained for two catalogue additions.

---

## Part 5 — Files this touches

| Story | Files |
|---|---|
| S1 | `prospector/facets.py`, engine tagging path, backfill tool under `tools/`, an API door for facet writes |
| S2 | `components/discovery/FacetBar.tsx`, `lib/discovery.ts`, `pages/index.tsx` |
| S3 | `pages/index.tsx` card block, `lib/discovery.ts` `splitTitle`, possibly `prospector/` for the outcome field |
| S4 | `pages/pack/[id].tsx`, `components/discovery/EmptyState.tsx` (rail reuse) |
| S5 | `prospector/` generation + `prompts/` |
| S6 | `pages/index.tsx`, `components/checkout/EmbeddedCheckoutPanel.tsx` (reuse only) |
| S7 | `lib/facets.ts` `KIND_LABEL` only |

**Do not touch:** `lib/facets.ts` vocabularies (closed cross-language contract, `facets.ts:4-10`),
`PackFacets.cs`, the null rule, `resolveStripeCheckout`.

---

## Part 6 — Definition of done (run these, paste the output)

```bash
# 1. Coverage — the whole point of S1
curl -s https://api.mumchimp.com/catalog > /tmp/cat.json
python3 - <<'PY'
import json,collections
items=json.load(open('/tmp/cat.json'))
F=['sector','payer','effort','commitment','mechanism']
for f in F+['advantages']:
    n=sum(1 for i in items if i.get(f) not in (None,'',[]))
    print(f'{f:12s} {n}/{len(items)}  {100*n/len(items):.0f}%')
print('zero-facet packs:', sum(1 for i in items
      if not any(i.get(f) for f in F) and not i.get('advantages')))
PY

# 2. No Matchmaker path returns an empty pool  (see Part 0 for the grid)
# 3. Web suite + typecheck  — typecheck is NOT optional: unknown vitest config
#    keys are silently ignored, and typecheck is the only thing that catches it
cd store_platform/src/Store.Web && npm test && npm run typecheck && npm run build

# 4. Python suite — MUST be the venv interpreter; system python3 lacks ddgs
#    and manufactures phantom failures
.venv/bin/python -m pytest -q
```

**Done means:** zero-facet packs = 0, every Matchmaker path returns ≥1 pack, all four commands
exit 0, and the Part 0 table re-measured and pasted into this file's changelog. Not "the labels
look more professional".

# STORY: Discovery — turn the shelf into a router that answers "which one is mine?"

**Date:** 2026-07-30 · **Repo:** `prospector` · **Surface:** `store_platform/src/Store.Web`,
`store_platform/src/Store.Api`, `store_platform/src/Store.Catalog`, `prospector/` (engine)
**Intended executor:** one coding agent (Cursor / MiniMax) in a single pass.
**Evidence basis:** live production catalogue pulled this session
(`curl https://prospector-store-api.fly.dev/catalog` → HTTP 200, 15 packs) plus on-disk reads.
Every claim below carries a `file:line` or a pasted command output. Anything unproven is marked
**HYPOTHESIS** with the probe that would settle it. Process risks are labelled as process risks,
never dressed up as quality verdicts.

---

## Part 0 — The one thing that changes the plan

The design feedback this story answers assumes the facet data already exists:

> "You already use tags like 'Highly automatable' and 'Hands-on service.' Turn these into
> clickable filters."

**It does not exist in a filterable form.** Proven against the live catalogue right now:

| Facet the feedback assumes | What production actually serves | Proof |
|---|---|---|
| Effort tags | **5 distinct values across 2 incompatible vocabularies** on 15 packs: `high`×6, `medium`×4, `Part automatable`×2, `Hands on service`×2, `Highly automatable`×1 | `GET /catalog` (live), counted |
| Time to first revenue | **0 of 15 packs carry it** | same; `timeToFirstRevenue` absent from every row |
| Market / jurisdiction | **0 of 15 packs carry it** | same; `market` null everywhere, though the column exists at `store_platform/src/Store.Catalog/Domain/Pack.cs:44` |
| Sector | **Not data at all** — guessed in the browser from a regex over title+one-liner | `store_platform/src/Store.Web/src/lib/category.ts:25-96` |
| "Unfair advantage" (code / no-code / sales / ops) | **Does not exist** anywhere: not in `Pack.cs`, not in `PublishRequest.cs`, not on the wire | `Pack.cs:3-45`, `Store.Api/Contracts/PublishRequest.cs:8-43`, `GET /catalog` payload |
| Payer type (B2B / B2C / B2G) | **Does not exist**. `whoPays` is a 144–272 character paragraph, not a facet value | live payload, measured lengths |

And the regex sector guess is not merely thin — it is **wrong in public**:

```
FabQuote – The Solo Fabricator's Instant Quote Engine   →  "Garden & outdoor"
   because the one-liner contains "growing"  →  matches /\bgrow/  (category.ts:40)
PackProof — The Dog Walker's Group Walk Evidence Engine →  "Garden & outdoor"
   because the one-liner contains "produces" →  matches /produce/ (category.ts:40)
3 of 15 packs match nothing and fall to the generic "Opportunity" pill (category.ts:89-96)
```

Sector distribution as actually rendered today: `payments`×5, `opportunity`×3 (i.e. unlabelled),
`garden`×3 (two of them wrong), `trades`×2, `operations`×1, `estate`×1.

**Therefore the order of operations in the feedback is inverted, and following it would damage the
brand.** Mumchimp's entire position is "receipts provided, six checks, every claim sourced"
(`store_platform/src/Store.Web/src/pages/index.tsx:597-607, 627-661`). A filter sidebar built on
this data tells a buyer that a metal-fabrication quoting engine is a *gardening* business, and
tells them a pack is "Hands on service effort" — rendered literally, today, at
`index.tsx:169-173` as `{pack.effortTag} effort` → **"Highly automatable effort"**. A filter that
lies is worse than no filter *on this brand specifically*, because the filter is the same promise
as the product: that someone did the sorting properly.

So: **facet data first, facet UI second, in the same story.** That is the improvement on the
feedback, and it is the reason this is one story and not two.

### Two more live defects this story fixes on the way past

1. **`splitTitle` only splits on an em dash.** `index.tsx:44` does `title.indexOf('—')`. Live
   titles: 6 of 15 contain `—` (em dash), 1 contains `–` (en dash — `FabQuote – The Solo
   Fabricator's…`), 8 contain neither. So 9 of 15 cards render the whole 30–85 character string
   as the "name" line, which is exactly the scannability problem the feedback describes.
2. **`theGap` is dead.** `index.tsx:125,154,235` and `lib/api/client.ts:59` read `pack.theGap`;
   there is no `TheGap` on `Pack.cs`, no `TheGap` on `PublishRequest.cs`, and the field never
   appears in the live payload. Every card therefore silently falls back to the solution
   one-liner under the label "The opportunity". Grep proving it (whole repo, excluding
   node_modules): the only 5 hits are the 5 front-end references listed above.

---

## Part 1 — The story

> **As** a builder with a specific set of skills, a specific amount of free time, and no idea
> what business to start,
> **I want** the catalogue to ask me three questions and hand me the one pack that fits,
> **so that** I stop reading fifteen dense descriptions, stop bouncing, and buy the one that is
> actually mine — and **as** the operator, **I want** every routing decision to be made from
> data the engine emitted and a human can audit, so the router never makes a claim the six checks
> did not earn.

**Non-negotiable framing for the implementer:** users do not shop by product name (they have
never heard of `PisteCheck`), and they do not shop by sector first (they do not know they want
"pets"). They shop by **what they already have** (skills, hours) and by **what they refuse to
touch** ("not vets"). Every UI decision below follows from that.

**Scale reality check.** 15 packs live now; this design must hold to ~120. Above that, the
client-side model here stops being correct — see Part 12 for the exact trigger and the server-side
successor. Do not pre-build it.

---

## Part 2 — The facet contract (the spine of the whole story)

One closed vocabulary, defined once, flowing engine → publish API → database → read API →
front end. **No facet may ever be inferred in the browser again.**

### 2.1 The vocabularies

| Facet | Cardinality | Values | Why this axis |
|---|---|---|---|
| `advantage` | **multi** (0–3) | `code`, `nocode`, `sales`, `ops`, `audience` | The buyer's own answer to "what have I got?". The primary router input. |
| `payer` | single | `b2b`, `b2c`, `b2g` | Who signs the cheque. Changes sales motion completely; buyers self-select hard on it. |
| `effort` | single | `automatable`, `part_automatable`, `hands_on` | How much of delivery is machine-doable. Replaces the current `low\|medium\|high` mush. |
| `commitment` | single | `evenings`, `part_time`, `full_time` | Hours to *run* it. Deliberately separate from `effort`: a hands-on service can be evenings-only; an automatable tool can still be a full-time sales grind. The feedback conflates these two; separating them is what makes the quiz's time question honest. |
| `mechanism` | single | the canonical 8 structural forms — `productized_service`, `vertical_tool`, `transaction_broker`, `risk_financing`, `physical_ops`, `audience_media`, `picks_and_shovels`, `data_intelligence` | **How it makes money.** This is the real "more like this" axis (Part 8), not sector. Already a first-class engine concept: `config.yaml:473-482`, `prospector/models.py:109`. |
| `sector` | single | `licensing_admin`, `employment_pay`, `housing_rental`, `care_benefits`, `trades_construction`, `pets_animals`, `creative_rights`, `property_probate`, `energy_planning`, `retail_inventory`, `professional_services`, `other` | Display + **exclusion** only ("anything but vets"). Never the primary filter. |
| `market` | single | existing codes (`uk`, `us`, `us-tx`, …) | Already modelled (`Pack.cs:40-44`); null on all 15 live packs, so the control stays hidden until non-null data exists. No new work. |

### 2.2 The null rule (this is the trust-preserving rule — do not soften it)

- A pack missing a facet is **listed under "All"** and is **never** returned under a specific
  value of that facet.
- When any filter is active and untagged packs exist, the results header states it plainly:
  *"3 packs aren't tagged for this filter yet — showing them separately below."* Untagged packs
  render in a dimmed "Not yet tagged" row beneath the results, never hidden silently.
- **No client-side inference. No default value. No "probably".** An absent facet is absent.

### 2.3 Where the values come from — and the one thing an agent must NOT do

Legacy `effortTag` values must **not** be string-mapped into the new `effort` enum
(`high` → `hands_on` is a guess, and `high` was never defined to mean that; the prompt that
produced it says only `low | medium | high` at `prompts/content_gen.md:47`, with normalisation
dropping anything else at `prospector/artifacts.py:344`). Instead:

**Backfill from the dossiers, which are on disk and complete.** Verified this session: all 15 live
pack ids resolve to `store/dossiers/{id}.pass.json` (15/15). Each carries
`candidate.structural_form`, `candidate.tags` (a dict), `candidate.automatability`,
`candidate.who_pays`, `candidate.hypothesis` — enough for a defensible read.

Beware two proven traps in that source data:
- `automatability` is **type-mixed** across the 15: floats (`0.5`, `0.6`, `0.65`, `0.8`, `0.85`),
  prose (`"high — authority routing is a lookup…"`), bare `"high"`, `"Highly autom…"`, and `None`.
  Parse defensively; when it is not decidable, emit `null`, not a guess.
- `structural_form` has **drifted from the canonical list**: live values include
  `niche_distribution`, `specialist_agency`, `local_service`, `local_service_chain`, and one
  empty string — none of which appear in `config.yaml:473-482`. Map these per-pack in the
  reviewed backfill file, never with a code-level string table.

---

## Part 3 — Backend work

### 3.1 Engine (Python)

1. `prompts/content_gen.md` — replace the lone `"effort_tag"` line (`:47`) with a `facets` object
   emitting exactly the enums in 2.1. Each value must be justified by the dossier, and the prompt
   must state: **omit any field you cannot justify; never guess.**
2. `prospector/artifacts.py::_normalize_listing` (`:304-346`) — validate every facet against its
   closed vocabulary; unknown or missing → `None` (mirrors the existing `effort_tag` guard at
   `:344`). Keep `effort_tag` on the wire, deprecated, for one release.
3. `prospector/bridge.py:266-268` — send the `facets` block alongside `whoPays` / `effortTag` /
   `timeToFirstRevenue`.
4. **New:** `store_platform/scripts/backfill_facets.py` — reads `store/dossiers/*.pass.json` for
   the currently-listed ids, proposes facets, and writes
   `store_platform/data/facets-backfill.json` (`{ "<packId>": { …facets…, "_evidence": "<dossier
   field quoted>" } }`). It **writes a file for review; it does not publish.** A second flag
   `--apply` PATCHes the store. Any pack it cannot decide gets `null` plus an `_unresolved`
   note — an unresolved pack is a correct outcome, not a failure.

### 3.2 Store API (C#)

1. `Store.Catalog/Domain/Pack.cs` — add `Sector`, `Payer`, `Effort`, `Commitment`, `Mechanism`
   (all `string?`) and `AdvantagesJson` (`string?`, JSON array — SQLite has no array column, same
   convention as `WhatYouGetJson` at `:36`).
2. `Store.Api/Contracts/PublishRequest.cs` — append optional params (record positional params are
   append-only for back-compat; the existing test `Store.Tests/Domain/PackMarketTests.cs:29-31`
   constructs `new PublishRequest("p1","T","O","d1")` and must still compile untouched).
3. **Enum validation at the boundary:** a publish carrying an unknown facet value returns
   `400` naming the offending field and the allowed set. Junk must not reach the database.
4. `Store.Api/Program.cs:151-178` (`GET /catalog`) — project the six facets into the response.
   `:180-219` (`GET /catalog/{id}`) — same.
5. **New:** `PATCH /internal/catalog/{id}/facets`, guarded by the same `Store:InternalApiKey`
   check already used by `POST /internal/catalog` (`Program.cs:235-245`, fail-closed when no key
   is configured — keep that behaviour).
6. **New:** `POST /catalog/waitlist` (Part 7). Add a stricter partition to the existing global
   limiter (`Program.cs:100-121`): 5 requests/minute per IP for this path, alongside the existing
   120/min default and the `/webhooks` no-limiter exemption at `:108-111`.
7. EF migrations: `AddPackFacets`, then `AddWaitlistSignup`. Startup already runs
   `MigrateAsync` (`Program.cs:127-131`), so no deploy-time step is added.

### 3.3 Also fix while in here

- Emit `TheGap` end-to-end (engine → `PublishRequest` → `Pack` → both catalog reads) so
  `index.tsx:125,154,235` stop falling back — **or**, if the engine cannot yet produce a
  one-sentence problem statement, delete the three dead front-end references and the field at
  `client.ts:59`. **Do not leave it half-wired.** Implementer's choice; state which you did.

---

## Part 4 — One state model, three doors

The quiz, the filter bar, and the search palette are **not three systems**. They are three doors
into one state object, and that object *is* the URL.

```ts
// store_platform/src/Store.Web/src/lib/discovery.ts  (NEW — the single source of truth)
export interface DiscoveryState {
  advantage: string[];   // ?advantage=code,sales
  payer: string | null;  // ?payer=b2b
  effort: string | null;
  commitment: string | null;
  sector: string | null;
  exclude: string[];     // ?exclude=pets_animals   ("anything but vets")
  q: string;             // ?q=uber
  sort: SortKey;
}
```

Rules:
- Serialised to `?advantage=code,sales&payer=b2b&…`, read in `getServerSideProps`
  (`index.tsx:674-686` already does SSR) so **every filtered view is shareable and
  server-rendered**. The quiz result is a URL, which makes it linkable in an email, a tweet, or
  a support reply.
- Filtering stays client-side over the SSR'd array while the catalogue is small — the existing
  comment at `index.tsx:336-340` already flags this and names the same trigger. Keep the
  filtering pure and in `discovery.ts` so the server-side successor swaps one module.
- Filter application is **AND across facets, OR within a facet**, with the null rule from 2.2.

---

## Part 5 — The Matchmaker (choice paralysis is the actual conversion bug)

Three questions, immediately below the hero, above the shelf. **Deterministic scoring, no LLM at
runtime** — a router that hallucinates on a trust brand is a brand-level incident, and a pure
function is testable.

**Q1 — "What have you already got?"** (multi-select, max 2) → `advantage`
`I can build software` · `I can sell` · `I can run operations` · `I have an audience` ·
`None of these yet` *(this last one is a real answer: it maps to `nocode` + `hands_on` and must
never dead-end)*

**Q2 — "How much time, honestly?"** (single) → `commitment`
`Evenings and weekends` · `Part time, ~20 hrs` · `Full time, this is the plan`

**Q3 — "Who would you rather sell to?"** (single, optional, skippable) → `payer`
`Businesses` · `Consumers` · `Councils and public bodies` · `Don't mind`

**Scoring** (`scoreMatch(pack, answers)`, pure, exported, unit-tested):

```
+3  each advantage overlap
+2  commitment exact match
+1  payer exact match  (0 when the buyer said "don't mind")
+1  pack has ≥15 sources        // rewards the best-evidenced packs, using real data (live range: 5–29)
 0  any facet the pack has not been tagged for  — never negative, never assumed
tie-breaks: verifiedAt desc, then sourceCount desc, then title asc  (stable, so the same answers always give the same pack)
```

Result screen: **one** pack presented as the answer ("Build this one."), with a one-sentence
*reason built from the matched facets* — "You can build software, you have evenings, and this is
a vertical tool a solo can run part-time" — plus two runner-ups in a smaller row, plus
`Show me everything that matched` which drops the buyer into the filtered catalogue with the URL
already populated. **If the top score is 0, do not show a winner** — go to the near-miss state
(Part 7). Never fabricate a match.

Copy at the top of the quiz, in house voice: *"Three questions. We'll tell you which one is
yours — or tell you honestly that we haven't built it yet."*

---

## Part 6 — Search: a command palette, not a text box

Component: `store_platform/src/Store.Web/src/components/discovery/CommandPalette.tsx`.

- Opens on `⌘K` / `Ctrl+K`, on click of the search field, and on `/`. Escape closes; focus returns
  to the trigger. Full keyboard nav (`↑` `↓` `Enter`), `role="combobox"` + `aria-activedescendant`,
  and a `aria-live="polite"` result count.
- Results update as you type. **No Enter, no results page.**
- **Search across `title`, `oneLine`, `headline`, and `whoPays`** — not title alone. Proof this
  matters: the feedback's own worked example is a buyer typing "Uber". The string "Uber" appears
  in `PlateStart`'s `oneLine` and `whoPays`, never in its title. A title-only search returns
  nothing for the exact query the feedback used to illustrate the feature.
- Each row shows **name → descriptor → facet chips → price**, e.g.
  `PlateStart · The Gig Driver's Private-Hire Licence Route Optimizer · B2C · Part automatable · £49`.
  Descriptor comes from a **fixed** `splitTitle` that handles em dash (`—`), en dash (`–`), and
  hyphen-surrounded-by-spaces, falling back to `headline` when the title has no separator (9 of 15
  live packs — see Part 0).
- Highlight the matched substring in the row. Cap at 7 rows + "See all N matches".

---

## Part 7 — Near-miss before empty, and only then the waitlist

The feedback jumps from "no results" to email capture. At 15 packs a *filtered* empty state is
common, and the buyer usually had a purchasable pack one facet away. Sending them to an email form
burns a sale that was on the table. Three states, in this order:

**A. Near miss** (any pack matches ≥2 of 3 active constraints):
> *"Nothing matches all three. These match two —"* then the cards, each with a chip naming the
> miss: `Needs full-time, you said evenings`. Plus one-tap constraint relaxers: `Allow full-time`,
> `Any payer`.

**B. True empty, catalogue-wide** (a search term matching nothing — e.g. "AI for dentists"):
> **"No vetted pack for 'AI for dentists' — yet."**
> "We only list an idea once it survives six checks with a clickable source behind every claim.
> Most ideas in a hot space die on the incumbent test. Tell us where to point the engine and we'll
> email you if one survives."
> `[ email field ] [ ☐ Email me if a pack in this space survives ] [ Put it in the queue ]`
> Under it, quiet and honest: *"One email, only if a pack ships. No newsletter. Unsubscribe in one
> click."* Then: *"Meanwhile, the free sample report shows exactly what survives looks like →"*
> (`/sample` already exists — `src/pages/sample.tsx`).

**C. Nothing live at all** — keep the existing copy at `index.tsx:381-393` unchanged.

### Legal constraints on B — these are hard gates, not polish

- The consent checkbox is **unticked by default** and its label is the lawful basis. Store the
  consent text **version** and a hash of the exact string shown, plus timestamp, alongside the
  email. Schema: `WaitlistSignup(Id, Email, Query, ConsentVersion, ConsentTextHash, CreatedAt,
  IpHash, Source)` — hash the IP, do not store it raw.
- `privacy.tsx` must be updated in the same PR: purpose, lawful basis (consent), retention
  (24 months from signup, then deleted), and withdrawal route. The page currently states
  *"We do not share data for marketing by third parties"* (`privacy.tsx:118`) — that stays true
  and must not be quietly invalidated.
- **Do not wire a marketing send in this story.** The sub-processor list (`privacy.tsx:89-105`)
  carries an explicit open comment that the correct Mailjet contracting entity is not yet
  established, and naming the wrong one is a false statement in a UK GDPR notice. Capture and
  store now; sending is a separate story once the entity is read off the Service Order.
- Success state must be honest about that: *"You're in the queue. We'll email you from
  support@mumchimp.com if one ships."*

---

## Part 8 — "Mechanically similar" (the safety net, done on the right axis)

On every pack page, below the fold, above the footer: **"Same mechanics, different industry."**

Ranking (deterministic, pure, unit-tested; current pack always excluded):

```
+4  same mechanism                      // the money-making shape — the axis that actually transfers
+2  same payer
+1  same effort
-2  same sector                         // NEGATIVE on purpose: the buyer bounced off the industry, not the model
tie-break: verifiedAt desc, then sourceCount desc
show top 3; if fewer than 2 score >0, hide the whole row rather than pad it with noise
```

Section copy: *"Like the mechanics of B2B fee recovery but don't fancy dealing with vets? These
run on the same engine, in a different industry."*

This is why `mechanism` exists as a facet: the feedback's own example — *"like B2B payment
recovery, but not vets"* — is a mechanism match with a sector *mismatch*. Sector-tag similarity
would return the very thing the buyer just rejected.

---

## Part 9 — Card, page, and proof surfaces

**Cards** (`index.tsx:120-204`) — the feedback is right that they are too dense. Keep: name,
descriptor (2 lines max), facet chips, price, source count, freshness, `Survived 6 checks` seal.
**Remove from the card:** the `Who pays` paragraph block (`:155`) — measured at 144–272 characters
live, it is the single densest thing on the card and it belongs on the detail page.
Keep `The gap` only once Part 3.3 makes it real.

**Chips must read as English.** Today `index.tsx:170-172` renders `{effortTag} effort` →
"Highly automatable effort". Render from the new enums via a label map:
`automatable` → `Mostly automated`, `part_automatable` → `Part automated`, `hands_on` → `Hands-on
service`; `evenings` → `Evenings-friendly`; `b2b` → `Sells to businesses`.

**Detail page** (`src/pages/pack/[id].tsx`) — the feedback asks for a sticky buy button and a
"peek inside". Both partly exist already: the desktop sticky checkout card is at `:499-501`
(`sticky top-24`), the mobile purchase bar at `:257`, and `sampleExtract` renders at `:458-466`.
So the work is **not** "add sticky CTA" — it is:
- Give the sample extract a real "peek inside the file" treatment (monospace, filename header,
  a soft fade at the cut) instead of a plain list, and label it *"A real page from this pack's
  Markdown, unedited."*
- Add the Part 8 similar row.
- Verify the mobile bar does not overlap the similar row on small viewports (Playwright, 390px).

**Hero** — apply the two copy changes that cost nothing and sharpen the position:
- Primary CTA `Browse vetted blueprints — £49` → **`See the 15 that survived`**, count read from
  the live `stats.listed` value already fetched at `index.tsx:676` (never hardcode 15).
- Add the anti-persona line under the hero sub-copy: *"Don't buy this if you want something to
  read. Buy it if you've got a free weekend and want to ship."*

Do **not** move the free-sample preview inline into the homepage in this story — `/sample` is a
full page today and inlining it competes with the shelf for the same scroll. Ship the router
first; treat inlining as its own A/B with a stated metric.

---

## Part 10 — Files this touches (complete list)

**New**
```
store_platform/src/Store.Web/src/lib/discovery.ts                  # state, URL codec, filter, scoreMatch, scoreSimilar
store_platform/src/Store.Web/src/lib/facets.ts                     # closed vocabularies + display labels (single source of copy)
store_platform/src/Store.Web/src/components/discovery/Matchmaker.tsx
store_platform/src/Store.Web/src/components/discovery/FacetBar.tsx  # sticky horizontal on mobile, sidebar ≥lg
store_platform/src/Store.Web/src/components/discovery/CommandPalette.tsx
store_platform/src/Store.Web/src/components/discovery/EmptyState.tsx  # near-miss + waitlist
store_platform/src/Store.Web/src/components/discovery/SimilarPacks.tsx
store_platform/src/Store.Web/e2e/discovery.spec.ts
store_platform/src/Store.Api/Contracts/WaitlistRequest.cs
store_platform/src/Store.Catalog/Domain/WaitlistSignup.cs
store_platform/src/Store.Tests/Domain/PackFacetTests.cs
store_platform/src/Store.Tests/Domain/WaitlistTests.cs
store_platform/scripts/backfill_facets.py
store_platform/data/facets-backfill.json                            # reviewed output, committed
```

**Modified**
```
prompts/content_gen.md                     (:47 — facets block)
prospector/artifacts.py                    (:304-346 — validate + normalise facets)
prospector/bridge.py                       (:266-268 — send facets)
store_platform/src/Store.Catalog/Domain/Pack.cs          (+6 columns)
store_platform/src/Store.Catalog/Persistence/StoreDbContext.cs
store_platform/src/Store.Api/Contracts/PublishRequest.cs (append-only)
store_platform/src/Store.Api/Program.cs    (:100-121 rate-limit partition; :151-219 project facets; new PATCH + waitlist)
store_platform/src/Store.Web/src/lib/api/client.ts       (Pack type + splitTitle move)
store_platform/src/Store.Web/src/lib/category.ts         (regex table DELETED; keep colour/icon map keyed by engine sector)
store_platform/src/Store.Web/src/pages/index.tsx         (hero copy, quiz, facet bar, card slimming, empty states, SSR state)
store_platform/src/Store.Web/src/pages/pack/[id].tsx     (peek-inside, similar row)
store_platform/src/Store.Web/src/pages/privacy.tsx       (waitlist purpose/basis/retention)
```

---

## Part 11 — Acceptance criteria

Numbered, each one testable. A criterion is met only when the named test passes.

**Data integrity**
1. `GET /catalog` returns `sector`, `payer`, `effort`, `commitment`, `mechanism`, `advantages[]`
   for every listed pack; absent facets serialise as `null` / `[]`, never as a default value.
2. `POST /internal/catalog` with an unknown facet value returns `400` naming the field and the
   allowed set, and writes nothing. *(`PackFacetTests.Publish_RejectsUnknownFacetValue`)*
3. A publish omitting all facets still succeeds and lists.
   *(`PackFacetTests.Publish_OmittingFacets_IsValid`; `PackMarketTests.cs:29-31` still compiles unmodified)*
4. `store_platform/data/facets-backfill.json` exists, covers all 15 live ids, and every non-null
   value carries an `_evidence` string quoting the dossier field it came from. Undecidable facets
   are `null` with an `_unresolved` note. **A backfill that guesses fails this criterion.**
5. No file under `Store.Web/src` infers a facet from pack text. `category.ts`'s regex `TABLE`
   (`:25-87`) is gone; what remains is a colour/icon map keyed by the engine's `sector`.
   *(grep assertion in the test suite)*

**Router**
6. `scoreMatch` is pure and exported; same answers always produce the same ordering.
   *(unit test, including the stable tie-break)*
7. Completing the quiz updates the URL to a shareable query string; loading that URL cold (SSR)
   renders the same filtered result. *(`discovery.spec.ts`)*
8. A quiz run whose best score is 0 shows the near-miss/empty state and **no** "winner" card.
9. "None of these yet" in Q1 always yields a non-empty result or the near-miss state — never a
   dead end.

**Filtering**
10. A pack with `effort = null` never appears under `?effort=hands_on`, and always appears under
    "All". *(`discovery.spec.ts`)*
11. When a filter is active and untagged packs exist, the count line names them explicitly, and
    they render in the dimmed "Not yet tagged" row.
12. Facet controls whose data is entirely null across the catalogue (today: `market`) do not
    render at all.

**Search**
13. Typing `uber` in the palette surfaces `PlateStart` with its descriptor and facet chips, with
    no Enter press and no navigation. *(`discovery.spec.ts` — this is the regression guard for the
    title-only-search failure in Part 6.)*
14. `⌘K` opens, `Esc` closes and restores focus to the trigger, `↑`/`↓`/`Enter` navigate and
    select. Palette rows have accessible names.
15. `splitTitle` splits em dash, en dash, and spaced hyphen; falls back to `headline`; is unit
    tested against all 15 live titles as a fixture. *(`splitTitle.test.ts`)*

**Empty / waitlist**
16. A filter combination with ≥2-of-3 partial matches shows the near-miss state with the
    named-miss chips and working relaxers — not the email form.
17. A catalogue-wide miss shows the waitlist with the consent box **unticked**; submitting with it
    unticked is rejected client- and server-side.
    *(`WaitlistTests.Rejects_MissingConsent`)*
18. A stored signup carries `ConsentVersion`, `ConsentTextHash`, hashed IP, and the originating
    query. Raw IP is never persisted. *(`WaitlistTests.Persists_ConsentEvidence_AndHashesIp`)*
19. `/catalog/waitlist` returns `429` after 5 requests in a minute from one IP; `/webhooks` remains
    exempt from throttling. *(`WaitlistTests.RateLimits_PerIp`)*
20. `privacy.tsx` names the purpose, lawful basis, retention period, and withdrawal route for
    waitlist data, and no marketing send is wired.

**Similar packs**
21. The similar row excludes the current pack, prefers same-`mechanism`/different-`sector`, and
    hides itself entirely when fewer than 2 candidates score > 0. *(unit + `discovery.spec.ts`)*

**Regression floor**
22. All four existing tests in `e2e/storefront.spec.ts` still pass unchanged — in particular
    `pack detail renders with a buy button` (the `get instant access` control must remain visible
    and unobstructed at 390 × 844).
23. `dotnet test` green; `next build` clean; no new lint errors introduced (note: `lint` is
    **not** in the CI gate today — do not treat its silence as proof).

---

## Part 12 — Out of scope, and the exact triggers that would change that

- **Server-side facet querying.** Trigger: catalogue > 120 listed packs *or* SSR payload > 250 KB.
  Then `GET /catalog?advantage=&payer=&q=&sort=` with the same vocabulary, and `discovery.ts`'s
  filter function becomes a thin client of it. Not before.
- **Analytics on the funnel.** There is deliberately no third-party tracker
  (`privacy.tsx:82` states no third-party tracking cookies) and adding one is a privacy-notice
  change, not a UI change. **HYPOTHESIS: this story raises conversion.** Probe that settles it
  without a tracker: Stripe order count and pack-mix for the 14 days before vs after the deploy,
  compared against the same window's sessions from the Fly access log. Do not add a pixel to
  answer it.
- **Inlining the sample report on the homepage** — its own story, own metric (Part 9).
- **Sending waitlist email** — blocked on naming the Mailjet contracting entity (Part 7).
- **Market facet UI** — code the facet through the stack; render the control only when a pack
  carries a non-null `market` (0 of 15 today).

**Process risk, labelled as such:** this story touches the money path's neighbouring files
(`Program.cs`, `Pack.cs`, the catalog reads) but changes no checkout, webhook, fulfilment, or
entitlement code. Keep it that way — if an edit lands in `FulfilmentService.cs`, `Payments/`, or
`WebhookEndpoints.cs`, the change is out of scope and should be reverted.

---

## Part 13 — Definition of done (run these, paste the output)

```bash
# 1. Backend + contract tests
dotnet test store_platform/src/Store.Tests            # expect: 0 failed

# 2. Front end builds and the e2e suite passes against a real catalogue
cd store_platform/src/Store.Web && npm run build && npx playwright test

# 3. The facet data is real, not defaulted — count what is actually tagged
curl -s https://prospector-store-api.fly.dev/catalog | python3 -c "
import sys,json,collections
d=json.load(sys.stdin); print('packs:',len(d))
for f in ('sector','payer','effort','commitment','mechanism'):
    print(f, collections.Counter(p.get(f) for p in d))"

# 4. The store is still sellable — the money rail is the floor, not the feature
bash store_platform/scripts/verify_store.sh           # exit 0 = sellable
```

**Ship criteria:** (3) shows every facet with at least one real value and no facet defaulted
across the board, (4) exits 0, and criteria 1–23 pass. If the backfill leaves facets `null` on
some packs, that is a **pass** — the null rule (2.2) is what keeps the filter honest, and an
honest "not tagged yet" is on-brand in a way a guess never is.

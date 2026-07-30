# Executor brief for MiniMax — Discovery UX (front end + engine emission)

**Spec (read it first, in full):** `specs/discovery-ux-2026-07-30.md`
**Branch:** `discovery-ux-2026-07-30`
**Role split:** `WORKFLOW.md:6-15` — Claude is the manager (writes the spec, reviews the diff),
you are the executor (implement against the spec). You do not rule on verdicts, and you do not
decide what a pack *is* — see §2.

---

## 1. What you are building, in one paragraph

The Mumchimp storefront is a flat grid of 15 packs with a text-search box. A buyer who does not
know the product names (`PisteCheck`, `FabQuote`) and does not yet know what business they want
cannot get from the shelf to a purchase. You are replacing passive browsing with an **opinionated
router**: three questions that hand the buyer one pack, a facet bar built on real engine data, a
⌘K command palette that searches the text buyers actually type, an honest near-miss state instead
of a dead "no results", and a "same mechanics, different industry" row on every pack page. All of
it is driven by one state object that **is the URL**, so every result is shareable and
server-rendered.

---

## 2. Your lane, and the fence you must not cross

### You own (implement + self-verify + commit)

```
store_platform/src/Store.Web/src/lib/discovery.ts            (new)
store_platform/src/Store.Web/src/lib/facets.ts               (new)
store_platform/src/Store.Web/src/components/discovery/*.tsx  (new — 5 components)
store_platform/src/Store.Web/src/lib/api/client.ts           (Pack type + splitTitle)
store_platform/src/Store.Web/src/lib/category.ts             (DELETE the regex TABLE)
store_platform/src/Store.Web/src/pages/index.tsx
store_platform/src/Store.Web/src/pages/pack/[id].tsx
store_platform/src/Store.Web/src/pages/privacy.tsx           (copy only — see §7)
store_platform/src/Store.Web/e2e/discovery.spec.ts           (new)
prompts/content_gen.md                                       (:47 — facets block)
prospector/artifacts.py                                      (:304-346 — validate facets)
prospector/bridge.py                                         (:266-268 — send facets)
store_platform/scripts/backfill_facets.py                    (new — the SCRIPT only)
```

### You must NOT touch (founder fence — Claude implements these)

```
store_platform/src/Store.Catalog/Domain/Pack.cs              schema/contract
store_platform/src/Store.Api/Contracts/*.cs                  contract
store_platform/src/Store.Api/Program.cs                      money rail + migrations run here
store_platform/src/Store.Catalog/Migrations/*                migrations
store_platform/src/Store.Api/Payments/*                      money rail
store_platform/src/Store.Api/Services/FulfilmentService.cs   money rail
store_platform/src/Store.Api/Endpoints/WebhookEndpoints.cs   money rail
store_platform/data/facets-backfill.json                     the OUTPUT is a judgment call
```

**If a change you are making requires editing a fenced file, stop and report it.** Do not work
around the fence by duplicating logic on your side of it.

**The backfill file specifically:** you write `backfill_facets.py`, which *proposes* facets and
writes the JSON with an `_evidence` quote per value. You never run `--apply`, and you never
hand-author the JSON. A human/Claude reviews the proposals before they reach the store, because
those values become buyer-facing claims on a brand whose entire position is "every claim sourced".

---

## 3. Ground truth — measured this session, do not re-derive it

Re-verify any of it with the command given; do not trust your own assumptions about the data.

| Fact | Command that proves it |
|---|---|
| 15 packs live; `effortTag` has 5 values across 2 vocabularies (`high`×6, `medium`×4, `Part automatable`×2, `Hands on service`×2, `Highly automatable`×1) | `curl -s https://prospector-store-api.fly.dev/catalog \| python3 -c "import sys,json,collections;print(collections.Counter(p.get('effortTag') for p in json.load(sys.stdin)))"` |
| `timeToFirstRevenue` and `market` are null on **all 15** | same payload |
| Sector is a browser regex, and it is wrong: `FabQuote` → "Garden & outdoor" via `"growing"` matching `/\bgrow/`; `PackProof` (dog walking) → same via `"produces"`; 3 of 15 hit the generic default | `store_platform/src/Store.Web/src/lib/category.ts:40,89-96` |
| `splitTitle` splits only on em dash, so 9 of 15 titles render unsplit (1 uses an en dash: `FabQuote – …`) | `store_platform/src/Store.Web/src/pages/index.tsx:44` |
| The card renders `{effortTag} effort` literally → "Highly automatable effort" | `index.tsx:169-173` |
| `theGap` is read in 3 places but exists nowhere in the backend | `client.ts:59`, `index.tsx:125,154,235`; no `TheGap` in `Pack.cs` |
| Sticky buy already exists — do **not** rebuild it | `pack/[id].tsx:499-501` (desktop), `:257` (mobile bar) |
| `sampleExtract` already renders — you are restyling it, not adding it | `pack/[id].tsx:458-466` |

**The consequence you must internalise:** every facet is null in production today. That is not a
blocker — it is the normal state your code must handle correctly. Build the whole front end
against null facets; the null rule (§4) defines exactly what that looks like.

---

## 4. The null rule — copy this into `discovery.ts` and obey it everywhere

```ts
// A pack missing a facet is shown under "All" and is NEVER returned under a specific value.
// No default. No inference. No "probably". Absent is absent.
export function matchesFacet(packValue: string | null, selected: string | null): boolean {
  if (selected === null) return true;      // "All" — untagged packs included
  if (packValue === null) return false;    // untagged never matches a specific value
  return packValue === selected;
}
```

When a filter is active and untagged packs exist, the results header says so in words —
*"3 packs aren't tagged for this filter yet — showing them separately below"* — and those packs
render in a dimmed "Not yet tagged" row beneath the results. **Never hide them silently, never
fabricate a value to make the grid look full.**

---

## 5. Task order (each task ends with a passing command)

Work in this order. Do not start a task until the previous one's verify command passes.

**T1 — Contract + vocabularies.** `lib/facets.ts`: the six closed vocabularies exactly as
listed in spec §2.1 (`advantage` `payer` `effort` `commitment` `mechanism` `sector`), plus the
display-label map from spec Part 9 (`automatable` → "Mostly automated", `hands_on` → "Hands-on
service", `b2b` → "Sells to businesses", …). Extend the `Pack` interface in `lib/api/client.ts`
with the six optional facet fields. *Verify:* `npx tsc --noEmit`.

**T2 — `splitTitle` fix + unit test.** Move `splitTitle` out of `index.tsx:43-49` into
`lib/api/client.ts`. Handle em dash `—`, en dash `–`, and a hyphen surrounded by spaces; fall
back to `headline` when there is no separator. *Verify:* `splitTitle.test.ts` runs against all 15
live titles as a committed fixture — AC-15.

**T3 — `discovery.ts`.** `DiscoveryState` (spec §4), URL codec (`?advantage=code,sales&payer=b2b`),
`filterPacks`, `scoreMatch`, `scoreSimilar`. **All pure functions, all exported, all unit tested.**
Scoring weights are given verbatim in spec Part 5 and Part 8 — use them exactly; do not
"improve" them. *Verify:* unit tests for AC-6, AC-10, AC-21.

**T4 — `category.ts` gutted.** Delete the regex `TABLE` (`:25-87`) and `categoryFor`'s inference.
What remains is a colour/icon map keyed by the engine's `sector`, with a neutral default for
`null`. *Verify:* AC-5 — a grep assertion that no file under `Store.Web/src` derives a facet from
pack text, and that `FabQuote` no longer renders as "Garden & outdoor".

**T5 — `FacetBar.tsx`.** Sidebar at `lg` and up, sticky horizontal scroller below that. Reads and
writes `DiscoveryState` only. Facets whose values are entirely null across the catalogue do not
render at all (AC-12 — today that hides `market`, and initially every facet; that is correct).

**T6 — `Matchmaker.tsx`.** Three questions from spec Part 5, verbatim. Deterministic `scoreMatch`
— **no model call at runtime**. Top score 0 ⇒ no winner, fall through to the near-miss state.
"None of these yet" must never dead-end (AC-9). The result writes the URL (AC-7).

**T7 — `CommandPalette.tsx`.** ⌘K/Ctrl+K, `/`, and click. Searches `title` + `oneLine` +
`headline` + `whoPays` — **all four**. Title-only search returns nothing for "Uber", which is the
exact query this feature exists to serve (AC-13). Rows: name · descriptor · facet chips · price,
matched substring highlighted, 7 rows max. Full keyboard nav + `role="combobox"` (AC-14).

**T8 — `EmptyState.tsx`.** Near-miss first (≥2 of 3 constraints matched) with named-miss chips and
one-tap relaxers; only a catalogue-wide miss reaches the waitlist form. Consent box **unticked**,
submit blocked while unticked (AC-16, AC-17). The POST target `/catalog/waitlist` is Claude's to
build — code against it and handle a 404 gracefully until it lands.

**T9 — `SimilarPacks.tsx`.** Spec Part 8 weights: `+4` same mechanism, `+2` same payer, `+1` same
effort, **`−2` same sector** (negative on purpose — the buyer just rejected that industry). Fewer
than 2 candidates scoring > 0 ⇒ hide the whole row (AC-21).

**T10 — Card, hero, detail page.** Slim the card (drop the `whoPays` paragraph at `index.tsx:155`),
fix the chip copy, hero CTA → "See the N that survived" with N read from `stats.listed`
(`index.tsx:676`) and **never hardcoded**, add the anti-persona line, restyle the sample extract as
a "peek inside the file". *Verify:* `npm run build` clean, then Playwright including the 390×844
check that the mobile purchase bar does not overlap the similar row (AC-22).

**T11 — Engine emission.** `prompts/content_gen.md:47` emits the `facets` object;
`prospector/artifacts.py::_normalize_listing` validates against the closed vocabularies and sets
unknown/missing to `None` (mirror the existing guard at `:344`); `bridge.py:266-268` sends them.
*Verify:* `python3 -m pytest tests/unit -q`.

**T12 — `backfill_facets.py`.** Reads `store/dossiers/{id}.pass.json` (all 15 live ids resolve —
verified), proposes facets, writes `store_platform/data/facets-backfill.json` with an `_evidence`
quote per value and `_unresolved` where it cannot decide. **`--apply` exists but you never run
it.** Three traps in that source data, all measured:
- `automatability` is type-mixed: floats (`0.5`–`0.85`), prose (`"high — authority routing is…"`),
  bare `"high"`, and `None`. Parse defensively; undecidable ⇒ `null`.
- `structural_form` has drifted off the canonical list at `config.yaml:473-482`: live values
  include `niche_distribution`, `specialist_agency`, `local_service`, `local_service_chain`, and
  one empty string. Map per-pack in the proposal with evidence — **never with a code-level string
  table**.
- Legacy `effortTag` must **not** be string-mapped into the new `effort` enum. `high` → `hands_on`
  is a guess, and a guess here becomes a false claim on the storefront.

---

## 6. Rules that override your defaults

1. **Never invent a facet value.** Null is a correct, shippable answer. A wrong label on this
   brand is worse than a blank, because the filter is the same promise as the product.
2. **Never write marketing copy from scratch.** Every user-facing string is in spec Part 5, 7, 9
   or below in §7. If you need a string that isn't there, stop and ask.
3. **Weights and vocabularies are given, not suggested.** Changing them silently invalidates the
   tests and the review.
4. **No new dependencies.** No search library, no state library, no analytics SDK. There is
   deliberately no third-party tracker (`privacy.tsx:82`) and adding one is a privacy-notice
   change, not a UI change.
5. **Don't touch the money path.** If your diff reaches checkout, webhooks, fulfilment, or
   entitlements, it is out of scope — revert it and report.

---

## 7. The copy you are allowed to ship (verbatim)

- Quiz intro: *"Three questions. We'll tell you which one is yours — or tell you honestly that we
  haven't built it yet."*
- Hero CTA: *"See the {N} that survived"* (N from `stats.listed`)
- Anti-persona: *"Don't buy this if you want something to read. Buy it if you've got a free
  weekend and want to ship."*
- Near miss: *"Nothing matches all three. These match two —"* + per-card miss chip, e.g.
  *"Needs full-time, you said evenings"*
- True empty: *"No vetted pack for '{query}' — yet."* / *"We only list an idea once it survives
  six checks with a clickable source behind every claim. Most ideas in a hot space die on the
  incumbent test. Tell us where to point the engine and we'll email you if one survives."*
- Consent label: *"Email me if a pack in this space survives"* (unticked)
- Under the form: *"One email, only if a pack ships. No newsletter. Unsubscribe in one click."*
- Waitlist success: *"You're in the queue. We'll email you from support@mumchimp.com if one
  ships."*
- Similar row: *"Same mechanics, different industry."* / *"Like the mechanics of B2B fee recovery
  but don't fancy dealing with vets? These run on the same engine, in a different industry."*
- Sample extract label: *"A real page from this pack's Markdown, unedited."*
- Untagged row: *"Not yet tagged"* + *"{n} packs aren't tagged for this filter yet."*

British English throughout. No exclamation marks. No "revolutionise", no "seamless", no "unlock".

---

## 8. Definition of done

```bash
cd store_platform/src/Store.Web
npx tsc --noEmit                 # clean
npm run build                    # clean
npx playwright test              # discovery.spec.ts green AND the 4 existing
                                 # storefront.spec.ts tests still green (AC-22)
cd ../../.. && python3 -m pytest tests/unit -q
bash store_platform/scripts/verify_store.sh   # exit 0 — the money rail is the floor on every chunk
```

Report back with: the command output above (pasted, not summarised), the list of acceptance
criteria from spec Part 11 you believe are met **with the test name that proves each**, and an
explicit list of anything you could not do and why. "Done" without pasted output is not done.

Note: `lint` is **not** in the CI gate today and has pre-existing errors — its silence proves
nothing, so do not cite it as evidence.

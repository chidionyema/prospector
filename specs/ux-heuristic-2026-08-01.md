# UX Heuristic Story — 2026-08-01

## Goal

Resolve the actionable items from the heuristic UX evaluation of Mumchimp.com that the founder
signed off on. One PR, four reviewable commits, no fabricated content, no design assets.

## Out of scope (deferred by the founder's decision)

- **Testimonials** — the project's source-or-die invariant (AGENTS.md §2) bars fabricated figures;
  `/kill-log` already provides the honest substitute. No changes.
- **Hero illustration / dossier mockup** — requires design assets. No code change.

## Commits in this PR

### 1. `store: account link gets visual weight in the header`

`components/marketing/MarketingLayout.tsx` — the `/account` link (lines 85-89) becomes a small
outlined pill: `inline-flex items-center gap-1.5 ... rounded-md border border-border px-3 py-1.5
text-sm font-semibold text-text hover:bg-bg`. Same icon and label. No other change to the header.

### 2. `store: move email capture from before the catalogue to after`

`pages/index.tsx` — the `<WaitlistForm source="home-after-sample" … />` block at lines 909-924
(currently between the sample section and the catalog) moves to after the catalog grid closes
but before the final `<CtaBand>`. The `source` tag stays `"home-after-sample"` (semantics: still
about the sample — the position just changed).

### 3. `store: FAQ — three categories, plus the format and competition questions`

Two files.

**`lib/faqContent.ts`** — add a `category: 'packs' | 'payment' | 'process'` field to each
existing `FaqItem` (10 items) and add two new items:

- `category: 'packs'`, question `"What format is the pack delivered in?"`, answer that names the
  zip of plain Markdown files, links to `/sample` as a live example, and links to
  `/pack/<id>#table-of-contents` as the per-pack format. **Do not invent a screenshot** — point
  at the existing `PreviewDocument` blurred preview on the pack page instead.

- `category: 'packs'`, question `"If 500 other people buy the same pack, aren't 500 people
  copying my idea?"`, answer that names the *honest* moat (specific niche sizing, route-to-market
  specificity, buyer profile granularity) and links to `/kill-log` so the reader can see how many
  candidates die on those gates. The answer MUST cite the kill-log in plain text — no fabricated
  scarcity number ("only 100 copies" or similar). The honest claim is "the bar is the moat, not
  a copy count."

**`pages/faq.tsx`** — split the single "Buying a pack" section into three:
1. "About the packs" (category `packs`)
2. "Payment & access" (category `payment`)
3. "The vetting process" (category `process`)

Each section keeps the same card styling (`bg-white border border-border p-8 rounded-lg …`) and
keeps the `<Aside>` sticky contact panel. The JSON-LD `FAQPage` schema must continue to enumerate
all 12 questions in declaration order — the schema is the source of truth for rich-result
eligibility, not the visible section headings. Add an assertion to the contract test.

### 4. `store: how-it-works — stepped timeline, the six checks, and the graveyard`

`pages/how-it-works.tsx` — replace the four wall-of-text sections (lines 36-105 in the current
file) with:

**A. The six checks, as a stepped timeline.** One step per gate, in a vertical timeline
(numbered cards, each card has the gate name, what it kills, and one inline example from
`/data/kill-log.json`):

1. **Real pain** — gate `pain_reality`. Inline example: `NI-GapSweep — The Gen Z Casual Worker's
   NI-Record Gap Audit…` with the entry's `reason` truncated to ~160 chars and a small
   `See kill-log` link.
2. **Lasting value** — gate `value_durability`. Inline example: `DecibelKit — the home noise
   evidence pack…`.
3. **Room past the incumbents** — gate `incumbency`. Inline example: `SaltCourt Rounds — The
   Council Leisure Manager's Portable Pool-Hall…`.
4. **Payer can actually pay** — gate `payer_solvency`. Inline example:
   `SplitCare Rebate — The Primary Carer's Council-Tax…`.
5. **Route to the buyer** — gate `route_to_market`. Inline example:
   `AssessAid — the carer's statutory assessment evidence dossier builder`.
6. **Legality** — gate `legality`. Inline example:
   `GasSafe Hold-Bond — The Sole-Trader Domestic Gas Engineer's…`.

The inline examples must come from `data/kill-log.json` (read at build time via static import —
no new API calls). Each card carries a link to `/kill-log` for the full entry.

**B. The adversarial pass.** A short section explaining that, after the six gates clear, a
second agent attacks the surviving claim and the dossier survives only if it can be defended.
One paragraph, not a wall of text.

**C. The graveyard — already on the site.** A section titled "Why most ideas die" with a single
sentence: "Of 960 ideas researched, 103 survived." plus a CTA block linking to `/kill-log`
where the reader sees all 60 documented rejections. **Do NOT replicate the kill-log inline** —
link out. The current `pages/kill-log.tsx` is the canonical home; duplicating its entries here
would drift them and double the maintenance cost.

**D. Honest limits.** Preserve the existing "honest limits" section verbatim — a pack is grounded
research, not a promise.

## Acceptance

A new static test file at `src/__tests__/uxHeuristicContract.test.ts` asserts each item by
reading the source as text:

- `MarketingLayout.tsx` account link class string includes `border-border` and `rounded-md`.
- `pages/index.tsx` source no longer contains a `<WaitlistForm` before `<CatalogBrowser` /
  `<Section bg="bg"` (the catalog wrapper). The form MUST appear after the catalog.
- `lib/faqContent.ts` exports 12 items (10 existing + 2 new); each item has a `category` of one
  of `'packs' | 'payment' | 'process'`; the JSON-LD in `pages/faq.tsx` enumerates all 12
  questions (the `FAQS.map(...)` call is intact).
- `pages/faq.tsx` renders three `<h2>` or `<Section title=>` headings — "About the packs",
  "Payment & access", "The vetting process".
- `pages/how-it-works.tsx` imports `killLog` from `@/data/kill-log.json`, renders all six gate
  names (pain_reality, value_durability, incumbency, payer_solvency, route_to_market, legality)
  as visible text in step labels, contains the literal string "960" (the killed count) and
  "103" (the passed count), and links to `/kill-log`.
- `pages/how-it-works.tsx` does NOT contain inline card markup that duplicates `kill-log.json`
  entries beyond the 6 example titles specified above — guard against the agent inlining the
  whole kill-log here.

The full verify chain exits 0:
```
cd store_platform/src/Store.Web
npm test -- --run && npm run verify && npm run build
```

## Anti-goals

- No new dependencies.
- No money path, no API, no identity, no migration changes.
- No testimonials, no fabricated quotes, no fake copy counts.
- No design-asset additions (hero illustration remains deferred).
- Runtime artifacts (`store/scheduler/audit/*.jsonl`, `store/provider_health*.json`,
  `store/control_center/config_history.jsonl`, `store/scheduler/DIAGNOSTICS_LATEST.txt`,
  `storage/durable_ledger.md`) must NOT be committed.

## Out of scope (deferred)

- SpotlightCard density reduction.
- Buy drawer copy/structure changes.
- Catalogue grid redesign.
- SEO/structured data changes beyond preserving the FAQPage schema.
# Mumchimp Deep UI Audit — 2026-08-02

## Audit scope

Every user-facing page and component audited against 2026 bleeding-edge patterns
(Pixelhop "agentic search", ZipChat "5 discovery patterns", Constructor "Beyond Relevance",
Baymard Institute e-commerce benchmarks).

## Finding 1 (CRITICAL): Discovery is hidden behind a click

**Current**: The progressive 3-step question flow ("What skills? → How much time? → Who pays?")
is inside a collapsible panel opened by the "Refine" button. A first-time visitor sees the full
unfiltered catalogue with zero guidance.

**Target**: The first question ("What skills do you bring?") should be visible by default above
the shelf, with large tappable cards. After answering, the shelf filters immediately AND the
next question slides in. The flow stays open until the buyer dismisses it or completes all
three steps.

**Rationale**: Netflix asks genre. Spotify asks mood. They don't hide the question behind
"Refine." The progressive flow is the right interaction model — it's just in the wrong place.
Moving it above the fold as a default-visible surface makes discovery the first thing a buyer
experiences, not something they have to find.

**Implementation**: Move step 1 of the progressive flow into the CatalogBrowser as a default-
visible row between the toolbar and the grid. After step 3 completes, collapse to a summary
chip row. The "Refine" button still exists to re-open it.

## Finding 2 (HIGH): Pack detail page is a wall of text

**Current**: 176px decorative gradient cover, title, one-liner, metadata, deliverables list,
six-checks narrative, scored axes (0-100 bars), similar packs, sticky purchase panel. On
mobile this is a very long scroll to reach the buy button.

**Target**: 
- Cover reduced: h-44 (176px) → h-28 (112px). The gradient is decorative, not informative.
- Scored axes (0-100 bars with labels like "Defensibility") removed. They're internal tooling
  language, not consumer-facing. Replace with 3-4 buyer-facing proof points: "Real demand,"
  "Someone pays," "You can reach them."
- Purchase CTA visible within the first viewport on mobile. Currently buried after scroll.
- Sticky bottom bar on mobile already exists — good. Keep it.

**Rationale**: The pack page should sell the outcome, not the methodology. A buyer at £49
wants to know "can I build this?" and "will it make money?" not "what's the defensibility
score." Linear's project pages and Stripe's docs are information-dense but never feel like
dashboards.

## Finding 3 (HIGH): No personalization anywhere

**Current**: Every visitor sees identical content. No "based on your browsing," no "trending
now," no "since you viewed X." The shelf is static.

**Target**: 
- After a buyer views 1-2 packs, show a "Based on your browsing" row with similar packs.
  The SimilarPacks component already exists — surface it on the catalog page.
- SpotlightCard rotates through "Trending this week" not just "Latest to survive."
- Heartbeat shows "X people browsing now" (approximate, non-creepy).

**Rationale**: Personalization is table stakes in 2026. Even a simple "Recently viewed" row
makes the site feel alive and adaptive. The data exists (SimilarPacks already computes
similarity). It's just not surfaced on the catalog.

## Finding 4 (MEDIUM): CommandPalette is keyword-only

**Current**: ⌘K searches titles and one-liners. "B2B technical evenings" returns nothing
unless those exact words appear in a title.

**Target**: The already-built `extractIntent()` function maps natural language to facet
values. Wire it into the CommandPalette: typing "B2B technical evenings" extracts
payer:b2b, advantage:code, commitment:evenings and shows matching packs. The buyer
sees "Found 4 packs matching B2B + technical + evenings" with pack cards in the palette.

**Rationale**: Semantic search is pattern 2 of 5 on the maturity curve. Mumchimp is at
pattern 1 (keyword). The NLP logic already exists (`extractIntent` in discovery.ts,
21 passing tests). It just needs to be called from the CommandPalette.

## Finding 5 (MEDIUM): Trust is told through text, not shown through data

**Current**: The trust band says "We tried to destroy every claim" with bullet points.
The kill log link says "See the 1,080 we rejected." These are text claims.
Heartbeat shows "Live database" with a ping dot and last-updated timestamp.

**Target**:
- Pull live kill stats into the Heartbeat pill more prominently:
  "1,080 killed. 129 survived. Last check: today."
- On each PackCard's proof line, show "34 sources" as a clickable count that opens a
  mini source preview (1-2 citations inline).
- The kill log is the site's strongest trust asset. Surface a live ticker or recent-kill
  carousel on the catalog page: "Just rejected: GasSafe — no legal pathway to market."

**Rationale**: The kill log is unique. No other storefront shows its rejects. It's the
one piece of evidence that can't be faked. Currently it's buried on its own page. Pulling
it into the main experience turns "trust us" into "here's the proof, live."

## Finding 6 (MEDIUM): No micro-interactions or sense of liveness

**Current**: The page is static. The Heartbeat ping dot is the only animated element.
Cards have a subtle hover lift. Everything else is stationary.

**Target**:
- Live count animations: pack count, kill count, browse count update with subtle number
  transitions (not jarring, just alive).
- Cards have a subtle entrance animation on scroll (stagger children).
- When filters change, the grid cross-fades rather than snapping.
- The CommandPalette has a typing indicator or result-count animation.

**Rationale**: Premium products feel alive. Linear's issue tracker animates status
changes. Stripe's dashboard has subtle number transitions. Vercel's deploy logs stream.
A storefront that claims "live database" should feel live.

## Finding 7 (LOW): Navigation is standard 2020-era SaaS

**Current**: Sticky header with logo, nav links (Catalog, Browse by category, How it works,
FAQ), cart button, account link. Mobile: hamburger menu. Footer: 3-column link grid.

**Target**: 
- The header is fine. Don't over-design it.
- Mobile: the hamburger menu could be a bottom sheet instead of a dropdown. More
  reachable on large phones.
- Footer: current footer is clean. Keep it.

**Rationale**: Navigation is not where the differentiation lives. The header works.
Focus energy on the discovery surface and the pack page.

## Finding 8 (LOW): Empty states are excellent, keep them

The near-miss → waitlist progression is genuinely modern. "Nothing matches all of it.
These come closest" with one-tap relaxers is the right pattern. Don't touch it.

---

## Priority ranking

| # | Finding | Impact | Effort | File(s) |
|---|---|---|---|---|
| 1 | Discovery hidden behind click | CRITICAL | 2h | index.tsx, FacetBar.tsx |
| 2 | Pack page wall of text | HIGH | 3h | pack/[id].tsx |
| 3 | No personalization | HIGH | 2h | index.tsx, SimilarPacks.tsx |
| 4 | CommandPalette keyword-only | MEDIUM | 1h | CommandPalette.tsx |
| 5 | Trust told not shown | MEDIUM | 2h | index.tsx, kill-log.tsx |
| 6 | No micro-interactions | MEDIUM | 3h | index.tsx, globals.css |
| 7 | Navigation | LOW | — | (defer) |
| 8 | Empty states | — | — | (already excellent) |

## Immediate action: Fix #1 (Discovery default-visible)

The progressive 3-step flow already exists and works. The fix is moving it from behind
the Refine click to a default-visible position between the toolbar and the grid.

### Spec

In `CatalogBrowser` (pages/index.tsx), replace the Refine button + collapsible panel with:

```
┌─ Toolbar ─────────────────────────────────────────────┐
│ [Search ⌘K]                      61 packs  [Sort ▾]   │
└───────────────────────────────────────────────────────┘

┌─ Discovery (default visible, collapsible) ────────────┐
│ Step 1 of 3: What skills do you bring?                │
│                                                       │
│ [🛠 Builders] [📈 Sellers] [⚙ Operators] [🎨 Creative]│
│                                                       │
│ Pick as many as you like    [Skip] [Next →]           │
└───────────────────────────────────────────────────────┘

┌─ Active chips (when filters applied) ─────────────────┐
│ [Suits builders ✕] [B2B ✕]   [Clear all]              │
└───────────────────────────────────────────────────────┘

┌─ Grid ────────────────────────────────────────────────┐
│ [SpotlightCard]                                       │
│ [PackCard] [PackCard] [PackCard]                      │
│ ...                                                   │
└───────────────────────────────────────────────────────┘
```

After all 3 steps complete, collapse to a summary:

```
┌─ Discovery (collapsed summary) ───────────────────────┐
│ ✓ 12 packs match  [Edit] [Clear]                      │
└───────────────────────────────────────────────────────┘
```

- Default: step 1 visible with cards
- Each selection filters the shelf immediately
- "Skip" advances without selecting
- After step 3: collapse to summary row
- "Edit" reopens the flow at step 1
- Dismiss by clicking outside or pressing Escape
- "Refine" button removed (the flow IS the refine surface)

### What changes
- `FacetBar.tsx`: Export a `StepFlow` sub-component that renders just the step UI
  (without the mobile modal wrapper) so CatalogBrowser can embed it directly.
- `index.tsx` (CatalogBrowser): Add the StepFlow between toolbar and grid.
  Remove the Refine button + collapsible panel. Keep AppliedFilterChips.
- The FacetBar itself (with mobile modal) stays for mobile — the mobile "Filter"
  button still opens the sheet with the same flow.

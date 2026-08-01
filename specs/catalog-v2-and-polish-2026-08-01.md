# Catalog v2 + Polish Story — 2026-08-01

## Goal

Resolve the catalog-card redesign from the second heuristic evaluation PLUS the Tier 1 and Tier 2
polish items from the broader audit. Twelve changes total. Three items already shipped in PR #39
and #40 are out of scope: `<AppliedFilterChips>`, `<ShelfEndCapture>`, and the focus-visible
ring on `PackCard`.

One PR, three reviewable commits (catalog v2 → Tier 1 → Tier 2). No fabricated content, no
design assets, no horizontal-swipe carousel on mobile (deliberately deferred — see Open
Questions).

## Out of scope (deferred)

- **Testimonials** — see `pages/kill-log.tsx:15-24`. Source-or-die invariant (§2 AGENTS.md).
- **Hero illustration / dossier mockup** — design assets only.
- **Horizontal-swipe carousel on mobile** — strongly not recommended for a 60-item catalogue
  (every serious SaaS marketplace uses vertical scroll on mobile). Flagged in the PR body.
- **Saved/favorited packs** — touches identity; out of scope for a polish PR.
- **Compare packs** — significant state mgmt + new UI surface; edge case at <100 items.

## Already shipped in #39 / #40 (do NOT touch)

- `AppliedFilterChips` — `<components/discovery/FacetBar.tsx>` and rendered in `pages/index.tsx:584`
- `ShelfEndCapture` — `<components/discovery/ShelfEndCapture.tsx>` and rendered in `pages/index.tsx:627`
- `PackCard` `:focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2` — already
  added in the design-contract PR

## Commits in this PR

### 1. `store: catalog card v2 — title weight, ghost CTA, monochrome chips, seal relocation`

`pages/index.tsx` — the `PackCard` component (around lines 252-321).

| # | Change | Source | Replace with |
|---|--------|--------|--------------|
| 1.1 | Title weight | `text-base font-bold leading-snug tracking-tight` | `text-lg font-extrabold leading-tight tracking-tighter` |
| 1.2 | CTA | "View blueprint" text link + arrow circle | Ghost button: `w-full rounded-md border border-border bg-transparent px-4 py-2 text-sm font-bold text-text transition-colors group-hover:border-primary group-hover:bg-primary group-hover:text-white`. Label: "View blueprint →" |
| 1.3 | Evidence row | `ProofLine` shows `{sources} sources · {freshness}` | Add the check tally inline: `<Icon name="verified" /> 6/6 checks · {sources} sources · {freshness}`. Update `ProofLine` in `pages/index.tsx:216-237` |
| 1.4 | FitChips | Primary chip is `bg-primary/10 uppercase tracking-wide text-primary`; rest are `bg-bg text-muted` | ALL chips become `bg-bg text-muted` — fully monochrome |
| 1.5 | Survived seal position | Sits on the cover (bottom-left) inside `<Cover>` | Remove from cover. Render inside the card body, under the title, as a slim line: `<span className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-bold text-success"><Icon name="verified" size={12} /> Survived 6 checks</span>` |
| 1.6 | Card hover | Currently `hover:bg-primary/[0.02] hover:shadow-... hover:ring-...` — synchronous | Keep current hover, BUT add `hover:border-text/15` ring transition so the darken matches the lift. The ghost button already changes state via `group-hover:`. |

`pages/index.tsx` `Cover` (line ~160) — `<SurvivedSeal />` is removed from cover children;
`PackCard` no longer renders it inside `<Cover>`.

### 2. `store: polish — survived badge on pack detail, sticky mobile checkout, back-to-top, dossier card consistency`

| # | Change | File |
|---|--------|------|
| 2.1 | "Survived 6 checks" badge inside the right rail checkout panel of `/pack/[id]` | `pages/pack/[id].tsx` — inside the `sticky top-24` panel, near the price block. Use the same slim-line styling as 1.5. |
| 2.2 | Sticky mobile checkout bar on `/pack/[id]` | `pages/pack/[id].tsx`. A `<div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-white p-3 lg:hidden">` carrying the price + Buy button. Mounted conditionally on `usePackCheckout().canCheckout` so it doesn't render for a not-yet-buyable pack. Hidden when the embedded checkout overlay is open (mirror the `clientSecret` branch). |
| 2.3 | "Back to top" floating button on `/pack/[id]` | `pages/pack/[id].tsx`. A `<button>` positioned `fixed right-4 z-20`, hidden by default, revealed after the user scrolls past the hero. `hidden lg:block` to avoid stacking with the mobile checkout bar on phones — the bar itself can be tapped to scroll up, so a separate button is a desktop-only affordance. |
| 2.4 | Shared `DossierCard` mini-component matching `PackCard`'s design language | New file `components/discovery/DossierCard.tsx`. Used by `SimilarPacks` (`components/discovery/SimilarPacks.tsx`) and `PackGrid` (`components/discovery/PackGrid.tsx`). Same radius / padding / hover / ProofLine as `PackCard`, but smaller (no FitChips cap of 5, no Buy/AddToCart buttons). |

### 3. `store: polish tier 2 — matchmaker progress, palette hint, empty-state reset, near-miss consolidation`

| # | Change | File |
|---|--------|------|
| 3.1 | Matchmaker progress + revise link | `components/discovery/Matchmaker.tsx`. Add a `Step N of 3` indicator above the fieldsets. After submit, the trigger button text changes to "Revise answers" and reopens the panel. |
| 3.2 | `↵` keyboard hint on the active command palette row | `components/discovery/CommandPalette.tsx`. Render `<kbd>↵</kbd>` next to the price on `rows[active]` only. Tailwind 4 — use the same `kbd` styling as the trigger button. |
| 3.3 | "Reset all filters" button in the empty waitlist state | `components/discovery/EmptyState.tsx` — `DiscoveryWaitlist`. Add a `<Button variant="secondary" onClick={() => onChange({ ... })}>Reset all filters</Button>` next to the form. Wire through `pages/index.tsx` so the index page passes a callback. |
| 3.4 | Near-miss chips become the relaxer | `components/discovery/EmptyState.tsx` — `DiscoveryNearMiss`. Convert each miss `<li>` into a `<button>` that calls `onRelax(candidate.relaxedState)`. Keep the existing relaxer buttons as a fallback for users who prefer the "Show any X" wording. |

## Files in scope

| File | Change |
|------|--------|
| `pages/index.tsx` | 1.1–1.6, 3.3 wiring |
| `pages/pack/[id].tsx` | 2.1, 2.2, 2.3 |
| `components/discovery/SimilarPacks.tsx` | 2.4 |
| `components/discovery/PackGrid.tsx` | 2.4 |
| `components/discovery/Matchmaker.tsx` | 3.1 |
| `components/discovery/CommandPalette.tsx` | 3.2 |
| `components/discovery/EmptyState.tsx` | 3.3, 3.4 |
| `components/discovery/DossierCard.tsx` | **new** — 2.4 |
| `__tests__/storefrontDesignContract.test.ts` | Update regex for the new PackCard className (cx-wrapped). Same pattern as the previous PR's update. |
| `__tests__/catalogV2AndPolishContract.test.ts` | **new** — source-level contract test for items 1.1–1.6, 2.1–2.4, 3.1–3.4 |
| `specs/catalog-v2-and-polish-2026-08-01.md` | **new** — this file |

## Acceptance

A new static test file at `src/__tests__/catalogV2AndPolishContract.test.ts` reads each source file
as text and asserts the structural facts. Twelve describes, one per item. Examples:

- `pages/index.tsx` `PackCard` heading class contains `font-extrabold` AND `tracking-tighter`.
- `pages/index.tsx` `PackCard` CTA block contains the substring `group-hover:bg-primary` (the ghost-button fill).
- `pages/index.tsx` `ProofLine` source contains the literal `6/6` (or `6 / 6`).
- `pages/index.tsx` `FitChips` chip class no longer contains `bg-primary/10` for the primary chip (monochrome).
- `pages/index.tsx` `PackCard` does NOT contain `<SurvivedSeal />` inside `<Cover>`.
- `pages/pack/[id].tsx` right-rail panel source contains `Survived 6 checks`.
- `pages/pack/[id].tsx` source contains a `fixed bottom-0` (or `inset-x-0 bottom-0`) class string and `lg:hidden` (the mobile checkout bar).
- `pages/pack/[id].tsx` source contains a `Back to top` string and a `right-4` fixed-position button.
- `components/discovery/DossierCard.tsx` exists and exports `DossierCard`.
- `components/discovery/SimilarPacks.tsx` imports `DossierCard` and uses it inside the `<li>`.
- `components/discovery/PackGrid.tsx` imports `DossierCard` and uses it inside the `<li>`.
- `components/discovery/Matchmaker.tsx` source contains `Step` and `of 3` AND `Revise answers`.
- `components/discovery/CommandPalette.tsx` source contains `<kbd>` and `↵` and the substring `rows[active]` (the active row gets the hint).
- `components/discovery/EmptyState.tsx` `DiscoveryWaitlist` source contains `Reset all filters`.
- `components/discovery/EmptyState.tsx` `DiscoveryNearMiss` candidate list renders `<button>` (not `<li>`) for the chip-relaxer behavior.

The full verify chain exits 0:

```
cd store_platform/src/Store.Web
npm test -- --run && npm run verify && npm run build
```

## Anti-goals

- No new dependencies.
- No money path, no API, no identity, no migration changes.
- No testimonials, no fabricated figures.
- No horizontal-swipe carousel on mobile.
- Runtime artifacts (`store/scheduler/audit/*.jsonl`, `store/provider_health*.json`,
  `store/control_center/config_history.jsonl`, `store/scheduler/DIAGNOSTICS_LATEST.txt`,
  `storage/durable_ledger.md`) must NOT be committed.
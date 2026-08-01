# Matchmaker Promotion — 2026-08-01

## Goal

Capture the "Personality Match" framing from the heuristic evaluation without rebuilding the
IA. Three small, contained changes that promote the existing `Matchmaker` from a collapsible
toolbar widget to the buyer's primary entry point, and reframe the language from "filter" to
"tell us what fits your life".

One PR, one commit. No data model changes, no new components.

## Hard scope

Three files only:

- `pages/index.tsx`
- `components/discovery/Matchmaker.tsx`
- `components/discovery/FacetBar.tsx`

Plus a new source-level contract test and a spec file.

## Changes

### 1. Auto-open the Matchmaker on a buyer's first visit to `/`

The buyer who arrives at `/` and has never used the Matchmaker sees it open by default, with the
shelf still rendered below it. A `localStorage` flag (`mumchimp.matchmaker.autoOpened.v1`) is
set when the panel opens — returning visitors see the closed toolbar widget as today.

Implementation lives in `pages/index.tsx`'s `CatalogBrowser`:

- A `useEffect` that fires once on mount. Reads the flag from `localStorage`. If absent, calls
  `setMatchOpen(true)` and sets the flag.
- Guard against SSR: read `localStorage` inside the effect, not at render time, so the HTML
  doesn't depend on browser state (regression of the same pattern in `pages/index.tsx:432` for
  `useSyncExternalStore`).
- If the buyer closes the panel without answering anything, do NOT re-open on the next visit —
  the flag is set on first auto-open, but the user can still re-open manually via the toolbar
  trigger.
- If the buyer has `cart.count > 0` or `account`, treat them as a returning visitor and skip the
  auto-open. They're not new.

### 2. Reframe the language

Match the buyer's ego: they are not configuring a database; they are telling us what fits their
life. Three copy changes, no mechanics change.

| Surface | Old | New |
|---------|-----|-----|
| `FacetBar.tsx:213` (mobile disclosure button) | "Filters" | "Your constraints" |
| `FacetBar.tsx:233` (Modal title) | "Narrow the shelf" | "Tell us what fits your life" |
| `Matchmaker.tsx` trigger label (where `MatchmakerTrigger` is rendered) | "Matchmaker" (or whatever the current label is — see file:117) | "Find my fit" |

The interior copy of the Matchmaker stays verbatim from the spec it was built from. Only the
external labels change.

### 3. Dynamic count on the Matchmaker trigger

The toolbar trigger button now reads `Find my fit — {N} that fit your life` where `{N}` is the
live count of matches the current answers produce. When no answers are set, it reads `Find my fit
— {N} total` (the live pack count).

Implementation:

- In `pages/index.tsx`'s `CatalogBrowser`, compute `liveMatches = rankMatches(packs, EMPTY or
  current answers)` whenever `packs` or the answers state change. This is the same function the
  Matchmaker already calls inside its submit handler — lift the call up so the trigger can read
  it.
- Pass `count={liveMatches.length}` and `countLabel="that fit"` (or `countLabel="total"` when no
  answers are set) into `MatchmakerTrigger` as new optional props.
- The trigger renders `Find my fit — {count} {label}` when a count is provided; otherwise it
  renders `Find my fit` as today.
- `MatchmakerTrigger` itself stays a presentational component — the count comes in via props, no
  internal data fetching.

## Files in scope

| File | Change |
|------|--------|
| `pages/index.tsx` | 1 (auto-open), 2 (copy), 3 (count wiring) |
| `components/discovery/Matchmaker.tsx` | 2 (trigger label), 3 (`MatchmakerTrigger` accepts `count` + `countLabel`) |
| `components/discovery/FacetBar.tsx` | 2 (mobile disclosure label + modal title) |
| `__tests__/matchmakerPromotionContract.test.ts` | **new** — source-level contract test |
| `specs/matchmaker-promotion-2026-08-01.md` | **new** — this file |

## Acceptance

A new static test file at `src/__tests__/matchmakerPromotionContract.test.ts` reads each source
file as text and asserts:

- `pages/index.tsx` source contains `mumchimp.matchmaker.autoOpened.v1` (the localStorage key).
- `pages/index.tsx` source contains a `useEffect` that calls `setMatchOpen(true)` (or equivalent)
  gated on the localStorage flag.
- `pages/index.tsx` source references `cart.count` (or equivalent) as a returning-visitor guard.
- `Matchmaker.tsx` source contains the literal `"Find my fit"` (trigger label).
- `MatchmakerTrigger` accepts a `count` and `countLabel` prop (interface or destructure).
- `FacetBar.tsx` source contains the literal `"Your constraints"` (mobile disclosure label).
- `FacetBar.tsx` source contains the literal `"Tell us what fits your life"` (modal title).
- `pages/index.tsx` source contains `liveMatches` (or equivalent) and passes it into
  `MatchmakerTrigger`.

The full verify chain exits 0:

```
cd store_platform/src/Store.Web
npm test -- --run && npm run verify && npm run build
```

## Anti-goals

- No new components.
- No data model changes (no new facet, no new engine output).
- No money path, no API, no identity, no migration changes.
- No "Risk Tolerance" facet (not in the engine — would fabricate data).
- No "Shortlist for guests" feature (deferred to a separate PR if you want it).
- No hero rebuild / Mad-Libs sentence (deferred — separate UX research pass needed).
- Runtime artifacts must NOT be committed.

## Out of scope (deferred)

- Anti-search hero rebuild with Mad-Libs sentence
- Shortlist / save-without-account for guests
- "Risk Tolerance" facet (would require engine changes)
- Comparison mode for shortlist (depends on shortlist)
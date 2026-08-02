# Discovery v2 — Progressive Question Flow Spec

## Goal
Transform the FacetBar "Refine" panel from a 6-group wall of equal-weight toggles into a
progressive 3-step question flow. Each step is one decision with large tappable cards.
The remaining 3 groups live behind "Advanced filters."

## Changes: `FacetBar.tsx` (rewrite of the internal panel, keep AppliedFilterChips)

### Step flow
```
┌─────────────────────────────────────────────┐
│  Step 1 of 3                                │
│                                             │
│  What skills do you bring?                  │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 🛠       │  │ 📈       │  │ ⚙        │  │
│  │ Builders │  │ Sellers  │  │ Operators│  │
│  │ 25 packs │  │ 12 packs │  │ 8 packs  │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│                                             │
│  Pick as many as you like                   │
│                                             │
│           [Skip]              [Next →]      │
└─────────────────────────────────────────────┘
```

### Groups
- **Primary** (shown as steps): advantage, commitment, payer
- **Advanced** (hidden behind "Advanced filters" expander): effort, mechanism, sector

### Card design
- Large rounded-xl cards with icon, label, and count
- Selected state: ring-2 ring-primary, bg-primary/5
- Unselected: ring-1 ring-border, bg-white, hover:ring-text/20
- Count shown as small muted text below label
- Multi-select for advantage (checkmarks), single-select for others

### Navigation
- Back button (←) on steps 2+
- Skip button on each step (clears selection for that group)
- Next button (→) advances to next step
- On step 3, "Show results" instead of "Next"
- Step indicator dots or "Step X of 3" text

### After completion
- Shows: "Showing N packs that match" with a summary of active selections
- "Edit your answers" link to go back through steps
- "Advanced filters ▼" expander for effort/mechanism/sector

### Mobile
- Same flow rendered inside the existing Modal
- Modal title: "What fits your life?"
- Step navigation at the bottom

### What stays unchanged
- AppliedFilterChips (export, component, all logic)
- Filter engine (filterPacks, facetCounts, offeredFacetValues)
- GROUPS order, foldFacetGroups (still used for advanced section)
- The parent CatalogBrowser integration (FacetBar is still inside the collapsible container)
- Active count badge on the Refine button

## Acceptance criteria
1. Tapping "Refine" shows Step 1 of 3 with large cards
2. Selecting card(s) on Step 1 filters the shelf immediately
3. "Next" advances to Step 2; "Back" returns to Step 1
4. "Skip" clears the group and advances
5. After Step 3, summary + "Advanced filters" expander visible
6. All existing filter tests pass (filter engine unchanged)
7. Mobile modal works with the new flow
8. TypeScript compiles clean

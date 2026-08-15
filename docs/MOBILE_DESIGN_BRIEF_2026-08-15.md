# Mumchimp — mobile design, polish and visual system brief

**Source:** founder, 2026-08-15, verbatim below the ledger. **Branch:** `design/mobile-visual-system`.
**Read `docs/SITE_SPEC_PROGRAM.md` too** — this brief is a delta on that spec, not a replacement.

This file exists because the last storefront spec lived only in a chat transcript and its status
evaporated between sessions (memory: `a-spec-that-lives-only-in-a-transcript`). **Update the ledger
in the same commit as the change it describes.** A tick with no `file:line` and no measurement is
not a tick.

---

## STATUS LEDGER

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Card system — Row vs Spotlight, shared tokens, delete tile-grid | **DONE** | Four formats → two. `PackCard`'s `weight` prop is gone: `row` moved out verbatim to `components/discovery/PackRow.tsx:45` (now shared by the shelf, the regional group, `PackGrid` on /ideas/<slug>, `SimilarPacks` on the pack page, recently-viewed, personalised, newest and near-miss — eight surfaces, one component); `mid` DELETED (`index.tsx` −2,758→ the branch and its odd-count promotion hack are gone); `DossierCard.tsx` DELETED (`git rm`). `PackSpotlight` (`index.tsx:233`) is the only card left and renders in exactly TWO places, each a single pack alone: the hero's `New this week` slot and the head of the shelf. Shelf is now one spotlight + `divide-y` rows, so no vertical run holds two formats. `tsc --noEmit` clean, `npm run build` exit 0. |
| 2 | Buttons — one primary sitewide | **DONE** | The spotlight's `View pack` was a hand-rolled fill (`bg-primary px-4 py-2.5` + its own radius/type) and is now `buttonClasses({ className: 'group-hover:bg-primary-hover' })` (`index.tsx`), so it shares the variant, not just the colour. The brief's second primary, **filled navy, does not exist in this build** — `Button.tsx:16-23` records `--action` moving navy `#1B3F8B` → charcoal `#2D3436` on 2026-08-15 ("the navy read as an orphan beside the teal identity"), and no filled navy is reachable. Remaining pair is filled charcoal `primary` + teal-outline `secondary`, which is the one-primary rule. Teal never fills, black never fills: `VARIANTS.secondary` is `bg-surface text-brand-mark border`. |
| 3a | Category labels — drop monospace | TODO | |
| 3b | Titles — two-line clamp, no mid-word cut | TODO | |
| 3c | Filter-tile counts — own right-aligned column | **DONE** | PR #218 (`abdbfa0`). `FacetBar.tsx` StepFlow tile: `justify-between`, `min-w-[2.5ch]`, `text-right`, `tabular-nums`, `font-mono` dropped. Measured 390/320: every count on the padding edge, delta +0; before, `I can run operations` overshot +45px at 320 and clipped. `chipClasses` gained `wrap`. |
| 4a | Floating "Narrow it down" pill overlaps body | TODO | |
| 4b | Sticky purchase bar — body text slices through | TODO | |
| 4c | Pack sample card — 3 nested containers, ~55% measure | TODO | |
| 4d | Sticky header — `scroll-margin-top` on headings | TODO | |
| 5 | Horizontal overflow in free-sample section | TODO | note: a `w-max` sector rail overflows at 320 BY DESIGN (scroll-snap); do not "fix" that one |
| 6a | Category chip carousel — snap + end gutters | TODO | |
| 6b | Filter tile grid — odd item leaves a gap | **PARTIAL** | `[&>*:last-child:nth-child(odd)]:col-span-2` already makes the orphan span both columns (`FacetBar.tsx`). Verify against the brief's intent. |
| 7 | Spacing scale 8/16/24/40/64, cap section gaps | TODO | |
| 8a | "Suits" labels → first person | **DONE** | PR #218. `facets.ts` LABELS: I can build / I can sell / I can run operations / I have an audience; `nocode` → "I don't code" (my call, flagged). `CLAUSE_LABELS` keeps the third-person form for sentence slots — `missLabelFor` was rendering "I can sell, you said i can build". |
| 8b | Pack detail page prints its intro paragraph twice | TODO | |
| P2 | Colour tokens + 7 rules | TODO | **CONFLICT, see below** |
| P3 | Icons — Lucide only, one family | TODO | |
| P4 | Images — glyph family, doc previews, diagrams | TODO | |

### Open conflict to resolve before touching colour

Part Two sets `--action: #1B3F8B` (navy) and "Blue fills every interactive element". On
2026-08-15 the founder chose **Option B, teal + charcoal**, and `--action` shipped as **`#2D3436`
charcoal** with `--bg: #FAF9F7`, on the stated grounds that "the teal logo and navy buttons feel
like they're from two different websites". The brief also says "Three primaries currently coexist:
filled charcoal (`View pack`), filled navy, and teal outline — pick one."

Both readings are self-consistent; they pick different winners. **Ask before implementing Part
Two.** Do not silently revert the charcoal decision, and do not silently ignore the navy token.

Second contradiction, same section: rule 5 says "drop category colour-coding entirely", but
`docs/SITE_SPEC_PROGRAM.md` §3 records the 12 `--cat-*` hues as one of two **deliberate documented
exceptions** to the design system, on the grounds that "they carry discovery meaning". The brief's
reasoning — 8+ categories is past what a colour set can teach, and it is the direct cause of the
ransom-note effect — is a live argument against that exception, not an oversight of it. Deleting
`--cat-*` is therefore a change to §3 and must be recorded there in the same commit.

Also already partly satisfied: §3 records `lucide-react` as the other documented exception, "for
UI **chrome** only". Part Three may be closer to done than the brief assumes — measure which
icons are actually non-Lucide before ripping anything out.

---

## PART ONE — LAYOUT AND COMPONENT FIXES

### 1. Card system — two variants, split by job

Do NOT collapse to a single component. Define two variants and enforce where each is used.

**Row** (workhorse): dense list row, price right-aligned, no button — the whole row is the tap
target. Used for catalogue listings, regional sections, search results, related packs.

**Spotlight**: bordered card with category label, title, description, multiple, sources glyph,
price and `View pack` button. Used only where a single pack is being presented rather than
browsed — featured pick, "same mechanics as the last pack you opened", homepage hero.

**Rule:** never more than one Spotlight in a vertical run. One Spotlight above a list of Rows is
hierarchy. Three stacked Spotlights is a broken list.

**Shared tokens** — these must be identical across both variants, and currently are not: title
typeface and weight, category label treatment, price treatment, source glyph, border colour,
corner radius. Only density and the presence of a button may differ.

**Delete** the tile-grid card format entirely. It duplicates Row and carries the alignment and
orphan-item defects.

### 2. Buttons — one system

- Primary: filled, single colour sitewide
- Secondary: outline
- Tertiary: text + arrow

Three primaries currently coexist: filled charcoal (`View pack`), filled navy, and teal outline
(`Show the other 36 UK packs`). Pick one primary colour and apply it everywhere.

Rules:
- Blue never appears on non-interactive text
- Teal never fills a button
- Black never fills a button

### 3. Typography

**Category labels:** drop monospace. 11–12px, uppercase, `letter-spacing: 0.06em`, `--ink-faint`,
no background strip. Monospace is reserved for genuine metadata counts (`8 checks · 8 sources`,
`61 packs in the catalogue`).

**Truncation:** titles currently cut at ~40 characters mid-word ("Florida real…", "elderly owners
and…", "Cal/OSHA citation contest tool for California…"). Replace with a two-line clamp on the
full title. A complete two-line title beats one mangled line.

**Counts in filter tiles:** counts sit as inline siblings of the label, so `4` collides with
"Suits an audience" while `15` / `32` / `24` sit clear. Fix:

```css
.filter-tile {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.filter-tile__count {
  min-width: 2.5ch;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
```

Counts use the same typeface, weight and grey across all tiles.

### 4. Overlays and containers

**Floating "Narrow it down" pill** overlaps body content at most scroll positions. Either dock it
with `padding-bottom` reserved on the page body, or remove it — the section it links to is already
on-page.

**Sticky purchase bar:** body text currently slices through it.

```css
.purchase-bar {
  border-top: 1px solid rgba(0,0,0,0.08);
  box-shadow: 0 -8px 24px rgba(0,0,0,0.06);
}
body { padding-bottom: <bar height>; }
```

**Pack sample card:** three nested padded containers reduce the text column to ~55% of viewport,
wrapping at four words per line. Collapse to one padded container below 640px. Tie `line-height`
to the realised measure.

**Sticky header:** headings clip under it on scroll. Add `scroll-margin-top` equal to header
height on all heading elements.

### 5. Horizontal overflow

The free-sample section exceeds viewport width — H2 clips, preview card border goes off-screen,
italic pull quote overruns every line. Audit for fixed `width` / `min-width` on the preview card
and blockquote.

### 6. Carousels and grids

**Category chip carousel:** items clip at both viewport edges mid-scroll. Add `scroll-snap-align`
and start/end gutters so no scroll position is ever unresolved.

**Filter tile grid:** odd item count leaves a lone tile with a trailing gap. Either pad to an even
count or make the last item full-width.

### 7. Spacing

~300px empty gaps between sections read as failed image loads. Establish a spacing scale
(8 / 16 / 24 / 40 / 64) and cap section gaps at the largest step.

Footer logo currently sits directly under body copy with no rule or space above it.

### 8. Copy

Replace the "Suits" filter labels. The pattern breaks on the fourth item — "Suits builders" means
*suits people who build*; "Suits an audience" means *requires you to have an audience*. Match the
section's first-person voice:

**I can build** · **I can sell** · **I can run operations** · **I have an audience**

Also: the pack detail page prints its intro paragraph twice, verbatim.

---

## PART TWO — COLOUR

### Tokens

```css
--ink:            #14161A;   /* all body and heading text */
--ink-muted:      #5C636E;   /* secondary text, metadata */
--ink-faint:      #8A919C;   /* counts, timestamps, category labels */

--brand:          <sample from logo funnel>;   /* teal */
--brand-surface:  <brand @ 4% on white>;
--brand-rule:     <brand @ 100%>;

--action:         #1B3F8B;   /* every interactive fill */
--action-hover:   <action −8% lightness>;
--action-tint:    rgba(27,63,139,0.07);

--surface:        #FFFFFF;
--surface-alt:    var(--brand-surface);   /* replaces ALL grey section bg */
--line:           rgba(0,0,0,0.08);
```

Semantic — verdict states only, not decorative, keep these:

```css
--verdict-refuted: #8A5A12;   /* amber, on #FDF8EF */
--verdict-killed:  #A32020;
--verdict-passed:  var(--brand);
```

### Rules

1. One decorative hue: teal. It appears **large or not at all** — section surfaces, the sources
   glyph, diagrams. Never as 12px tinted label text.
2. Blue fills every interactive element. It never appears on non-interactive text.
3. All text is `--ink` or `--ink-muted`. No exceptions outside verdict states.
4. Semantic colours appear only on verdicts inside check lists and the kill log.
5. **Drop category colour-coding entirely.** With 8+ categories no colour set is learnable, and it
   is the direct cause of the ransom-note effect. Categories are distinguished by label text only.
6. Every grey section background becomes `--surface-alt`. This is where the site stops feeling
   clinical — large teal-tinted surfaces, one hue, no new colours introduced.
7. Contrast: all text ≥4.5:1. Verify `--ink-faint` on `--surface-alt` specifically.

> **Standing constraint that outranks a token rename:** keep the existing verdict reds where they
> are current (`--danger: #dc2626`, `--kill: var(--danger)`, `--ins-kill: #f26d6d`). The brief's
> `--verdict-killed: #A32020` is a change to those; confirm before shipping it.

---

## PART THREE — ICONS

### Family

One set, sitewide. **Lucide** (MIT, 24px grid, 2px stroke) pairs correctly with the current
geometric sans. Remove every icon not from this set — three families are currently in use across
the trust row alone.

### Spec

```
Stroke:  1.5px @ 16/20px · 2px @ 24px
Sizes:   16 (inline with text) · 20 (default) · 24 (section marker)
Colour:  currentColor, inheriting --ink-muted
Fill:    never — outline only, no mixed styles
Align:   optical centre to cap-height, not baseline
```

### Permitted

- Trust row (money back / sourced / one-time payment)
- File-type markers in the pack manifest
- Verdict states
- Search and menu affordances
- Arrows in buttons and links

### Forbidden

Next to headings, next to category labels, in filter chips, or as decoration in body copy. An icon
that does not aid scanning is noise. This discipline is what keeps "add more icons" from making
things worse.

---

## PART FOUR — IMAGES

The product is documents and evidence. **No stock photography and no photographs of people** —
both read as false on a site whose entire proposition is that nothing here is invented.

Three permitted asset types.

### 1. The data glyph family — the signature asset

The sources bar-glyph is the only original visual asset on the site and it works. Extend it into a
system:

- **Sources density** — existing glyph, bar count scaled to source count
- **Checks passed / refuted** — same bar language, verdict-coloured
- **Price multiple** — same language, expressing the `×` figure

```
Height:  16px inline · 32px in Spotlight cards · 64px as section art
Colour:  --brand, with per-bar opacity 40–100%
Bars:    max 24, scale count to value
```

### 2. Document previews

Real renders of actual pack pages, cropped to a meaningful region. Truthful, and shows what is
being bought.

```
Ratio:   4:3 or 3:2, consistent within a section
Border:  1px --line, radius 4px
Shadow:  none
Loading: lazy, with --surface-alt placeholder at final dimensions (no layout shift)
```

### 3. Diagrams

The strongest opportunity on the site. Two to build first:

- **The funnel** — 1,444 researched → 1,364 killed → what survives. There is a funnel in the logo
  mark and a funnel in the proposition, and it currently appears as neither.
- **The 8-check pipeline** — the checks a pack faces, in order, with verdicts.

```
Style:   line + flat fill, monochrome in --brand tints only
Stroke:  matches icon stroke (1.5 / 2px) — diagrams and icons must read as one hand
Type:    same sans as body, minimum 12px
Width:   full bleed to content column, max 720px
```

### Density rule

One image or diagram per section, maximum. If a section needs two, it is two sections.

---

## VERIFICATION CHECKLIST

- [ ] No hex value outside the token list appears anywhere in CSS
- [ ] No coloured text below 14px
- [ ] Every icon resolves to the same library
- [ ] No filled and outline icons in the same view
- [ ] Every grey background replaced with `--surface-alt`
- [ ] No photograph of a person anywhere on the site
- [ ] Every image has explicit dimensions set
- [ ] No two card formats visible in the same vertical list
- [ ] No horizontal scroll at 390px viewport width
- [ ] All headings clear the sticky header when scrolled to

### How each box gets ticked

Every one of these is a COMMAND, not an opinion. Tailwind v4 is in use, so remember an unmapped
colour utility emits no rule at all — a token added to `:root` without a matching `@theme inline`
entry in `src/styles/tokens.css` silently does nothing, and the checklist would still "pass" a
grep. Verify in the browser at a real viewport, not by grepping HTML
(memory: `never-judge-design-by-grepping-html`).

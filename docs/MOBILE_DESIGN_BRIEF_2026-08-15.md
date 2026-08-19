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
| 3a | Category labels — drop monospace | **DONE** | `font-mono` gone from both places a sector is set: `PackCardHeader.tsx` (the Spotlight's band) and `PackRow.tsx:120`. Both now use `CATEGORY_LABEL` = `tracking-[0.06em] font-medium` at `text-caption`. **No background strip** — `bg-surface2` and its `border-b` removed from the band; the fixed `h-10` STAYS, because that is the jitter rule (9 of 63 packs are untagged and an empty reserved box keeps titles on one baseline) and it was never about the fill. Caps come from `label.toUpperCase()`, not the `uppercase` utility, which `weightAndCasePolicy.test.ts` bans repo-wide (CSS caps leave the accessible name in sentence case). |
| 3b | Titles — two-line clamp, no mid-word cut | **DONE** | `PackRow.tsx:100` was `line-clamp-2 … sm:line-clamp-none sm:truncate`; the `sm:truncate` is removed, so the clamp holds at every width. `truncate` is a MID-WORD cut, which made the widest viewport the only place a title could still stop inside a word — the defect was hiding on desktop because it bites only the longest titles. The Spotlight already clamped at two lines (`index.tsx`, `line-clamp-2 block text-h2`). No character-count truncation exists in `cardHeading` (`lib/discovery.ts`); the 150-char publish cut is repaired by `repairTruncation` before render. |
| 3c | Filter-tile counts — own right-aligned column | **DONE** | PR #218 (`abdbfa0`). `FacetBar.tsx` StepFlow tile: `justify-between`, `min-w-[2.5ch]`, `text-right`, `tabular-nums`, `font-mono` dropped. Measured 390/320: every count on the padding edge, delta +0; before, `I can run operations` overshot +45px at 320 and clipped. `chipClasses` gained `wrap`. |
| 4a | Floating "Narrow it down" pill overlaps body | **ALREADY DONE** | `FacetBar.tsx:722` FilterFab is `pointer-events-none fixed inset-x-0 bottom-4 z-40 … px-4`, and `:708` reserves the space it occupies: `body.style.paddingBottom = 'calc(4.5rem + env(safe-area-inset-bottom))'`. Nothing can end up under it. No change. |
| 4b | Sticky purchase bar — body text slices through | **PARTIAL — third conflict, see below** | Two thirds are already live and unchanged: `border-t border-border` on the bar (`pack/[id].tsx`) and the page reserving the bar's height on `body`. The **box-shadow is NOT applied**: `tokens.css:456` is a documented sitewide rule — "§3.4 (2026-08-08): NO BOX-SHADOWS. Depth is a surface step plus a hairline" — with `--shadow-1`/`--shadow-2` both set to `none` and `threeRadiiTwoShadows.test.ts` failing any shadow utility outside those two. I applied `shadow-[0_-8px_24px_rgba(0,0,0,0.06)]`, measured the test fail, and reverted rather than override a shipped rule silently. **Founder decision needed** (same class as the two colour conflicts below).
| 4c | Pack sample card — 3 nested containers, ~55% measure | **ALREADY DONE on mobile** | The plinth is breakpoint-gated: `PackSpecimen.tsx:188` `rounded-md sm:border sm:border-border sm:bg-surface3 sm:p-8` — inactive below `sm`, so it adds 0 at 390px. The only inset left is the document's own margin, `:217` `px-5 pb-10 pt-7 sm:px-12 …` = 20px a side, giving a 350px text column at 390px (**90%**, not 55%). The three-container stack the brief measures is the ≥`sm` rendering; re-measure there before touching it. |
| 4d | Sticky header — `scroll-margin-top` on headings | **ALREADY DONE** | `globals.css:416` — `[id] { scroll-margin-top: 5.5rem }`, i.e. EVERY jump target, not just `<section>`. 5.5rem = the tall header (5rem) + 0.5rem of air, so it clears the header in both its states (`h-20` → `h-16` on scroll). Components opting into more (`scroll-mt-24`) still win; this is a floor. No change needed. |
| 5 | Horizontal overflow in free-sample section | **DONE — measured, not reproducible** | Playwright, Chromium, viewports **320 and 390**, pages `/`, `/how-it-works`, `/sample`, `/ideas`: `document.documentElement.scrollWidth` equals the viewport width on **all eight combinations**, and a sweep of every painted element for `right > viewport` or `left < 0` (excluding elements inside a deliberate scroll container) returned **zero offenders**. Almost certainly closed by #217 (`a94dc54`), which landed concurrently with the brief. |
| 6a | Category chip carousel — snap + end gutters | **ALREADY DONE** | `index.tsx:531` scroller `snap-x snap-mandatory scroll-px-4 sm:snap-none sm:scroll-px-0`; chips at `:543`/`:559` carry `snap-start`; gutters at `:518` `-mx-4 … px-4 … sm:mx-0 sm:px-0`, so the rail bleeds to the edge and the first/last chip still clear it. No change. |
| 6b | Filter tile grid — odd item leaves a gap | **PARTIAL** | `[&>*:last-child:nth-child(odd)]:col-span-2` already makes the orphan span both columns (`FacetBar.tsx`). Verify against the brief's intent. |
| 7 | Spacing scale 8/16/24/40/64, cap section gaps | **DONE for the shared band; the ~300px figure is not reproduced** | Measured at 390 by sweeping every painted box and finding the y-bands no element covers. **Before:** the six largest whitespace bands on `/how-it-works` were **178, 149, 129, 129, 129, 129px**; `/` was 146, 126, 126, 113; `/ideas` 126, 97, 88. **Nothing near 300px** at 390 — that figure does not reproduce on this build. The 129s were the shared marketing band paying `py-16` twice: 64px above + 64px below = 128px between the last line of one section and the first of the next. `blocks.tsx:198` and `:273`, `GuideLayout.tsx:34`, `about.tsx:42`, `index.tsx:2027` and `:1945` now cap the MOBILE side at `py-10` (40px, on the brief's scale), desktop `md:py-24` untouched — at 1280px a 96px band reads as composition and the defect is specific to the width where the column is 350px. **After:** `/how-it-works` **178 → 130** and the 129 cluster → 81/88; `/` 146 → 126; `/ideas` 126 → 102; total page height 10,175 → 9,839. Still above the brief's 64px cap: the survivors are per-page hero padding and `mb-10` heading margins, not the shared band, and each needs its own before/after. 896 tests pass, build exit 0. |
| 8a | "Suits" labels → first person | **DONE** | PR #218. `facets.ts` LABELS: I can build / I can sell / I can run operations / I have an audience; `nocode` → "I don't code" (my call, flagged). `CLAUSE_LABELS` keeps the third-person form for sentence slots — `missLabelFor` was rendering "I can sell, you said i can build". |
| 8b | Pack detail page prints its intro paragraph twice | **DONE** | Confirmed and fixed. `pack/[id].tsx:666` guarded `oneLine` with `!(isTruncated(pack.oneLine) && pack.subhead)` — it dropped the lead only when it was BOTH cut AND had a subhead. On a pack with a subhead whose `oneLine` survived intact both branches were true and the page printed two lead paragraphs, same slot, same size, same colour. Exposure: the last catalogue-wide measurement found **34 of 63** published one-liners truncated (memory `published-onelines-truncated-mid-word`), so the ~29 untruncated ones are the population that doubled up — derived from that measurement, not re-counted today. Guard is now `!pack.subhead`, which is the rule the block's own docblock already stated: "There is a `subhead`: the cut sentence is dropped outright and the subhead is the lead." |
| P2 | Colour tokens + 7 rules | TODO | **CONFLICT, see below** |
| P3 | Icons — Lucide only, one family | **DONE, with one measured exception** | **The brief's premise is refuted where it is most specific:** "three families are currently in use across the trust row alone" — `TrustGuaranteesRow.tsx:21-142` renders `ShieldIcon`, `BadgeCheckIcon`, `CoinsIcon`, all `lucide-react`, one family. The second hand was elsewhere and is now gone: `pack/[id].tsx` hand-inlined the two lucide `link-2` paths at `strokeWidth="2"` for its copy button (an icon we already ship) and printed a `✓` DINGBAT for the copied state — a glyph drawn by the user's font stack, so a different piece of vendor artwork per OS. Both are now `<Icon name="link"/>` / `<Icon name="check"/>`; `orders/success.tsx:222` had the same `✓` and got the same fix. `Icon.tsx` gained `link: Link2Icon`. **Stroke is now optical, not nominal** (`Icon.tsx::opticalStrokeWidth`): `strokeWidth` lives in the 24-unit viewBox, so the old hardcoded `1.5` rendered **1.0px at size 16, 1.25px at 20, 1.5px at 24** — the inline-with-text icons were the lightest on the site, which is backwards. It now solves for the brief's rendered targets (1.5px ≤20, 2px at 24). **Exception, deliberate:** X and LinkedIn stay hand-inlined — lucide-react 1.28 ships no brand marks (`twitter.mjs`/`linkedin.mjs` are absent from the package) and a trademark redrawn in our outline hand is wrong, not consistent. |
| P3n | `BespokeIcon` — the 11-shape second family | **NOT REMOVED — founder call, one line** | It draws **nowhere**: the only references outside its own file are `nThreeBespokeIcons.test.ts` and a comment at `ideas/index.tsx:254` recording that the tiles dropped it (the page was `/ideas` when this was measured, e157be8 renamed it to `/collections`, and it has since been renamed back to `/ideas` -- see `collectionsRename.test.ts`). So it is not one of the families "in use" and Part Three does not bite it. Deleting it anyway would collide with an explicit prior decision: `nThreeBespokeIcons.test.ts:88` keeps the shapes on the record under the no-silent-feature-removal rule, "still here the day a designer draws the missing seven". Also on the record there: its 19 kinds resolve to only 9 shapes and **not one** of the 16 landing slugs is a key in `ICON_MAP`, so every tile drew `DefaultIcon`. **Delete the component and its test, or keep it parked?** |
| P4a | Diagram 1 — the funnel | **DONE** | `components/marketing/FunnelDiagram.tsx`, rendered on `/how-it-works` in the section that already states the two figures, so the picture and the prose read the same `RESEARCH_STATS` and cannot drift. Slabs are the brand mark's geometry re-derived at this aspect (mark slabs 32/24/16 of 88, `Logo.tsx:143-146`), stroke 1.5 to match the icon hand, ink at three opacities and no hue. **The taper is to scale**: the stub is 5.5% of the top because that is what survives. **The third term of the brief's "→ what survives" is deliberately UNLABELLED** — the founder cut the survivor figure sitewide on 2026-08-13 and `lib/stats.ts` does not export it, and 1,364 killed + 50 listed do not sum to 1,444, so a numbered third stratum would assert a partition that does not close (the c8e6ed0 defect). `survivorFraction` is consumed by geometry in the expression that defines it and reaches no text node. viewBox is 440 not 720 because SVG type does not reflow: at 720 the labels render 11px in a 358px mobile column, under the brief's own 12px floor. Build exit 0, 896 tests pass.  **Measured in Chromium at 390** after wiring: the svg lays out 342px wide, the two figures render 23.3px and the captions 12.4px — the captions were 16 viewBox units only because 15 measured **11.7px**, under the brief's own 12px floor. |
| P4b | Diagram 2 — the 8-check pipeline | **ALREADY SERVED, in a stronger form** | `components/marketing/CheckSequence.tsx`, on `/how-it-works:172`. It is not a diagram: it is one real idea entering at the top and each of the eight checks firing on it in order, with the verdict, the confidence and the opening sources on each, all read from `data/sample-report.json` — the same file `/sample` renders in full, so it cannot drift from the record it claims to show. A drawn pipeline beside it would be a second, thinner copy of the page's strongest asset, and the brief's own density rule ("one image per section, maximum") forbids it. **No change; say so rather than build a duplicate.** |
| P4c | Glyph family — checks passed/refuted, price multiple | TODO | The two existing originals are `PopulationField` (1,444 marks, home page) and `Glyph` (verdict marks, used on /sample, /kill-log and the pack page). Extending the bar language to a verdict count and a price multiple is unstarted. |
| P4d | Document previews | TODO | Real crops of pack pages, 4:3 or 3:2, 1px border, no shadow, lazy with a placeholder at final dimensions. Unstarted; needs real renders, not CSS. |
| F1 | "New this week" was broken at every desktop width | **DONE** | Founder, looking at the live server: *"New this week is broke style"*. `PackSpotlight`'s internal breakpoints were **viewport** queries (`sm:`/`lg:`) on a card whose width comes from its **container**, and the hero's featured slot is a 420px column. Measured at 1440x900 before the fix: `lg:` was true, so `lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto]` fired inside a **388px** card, the claim track resolved to **~71px**, and the title was clipped mid-word by the card's own `overflow-hidden` — "Condo due diligen / packet / for Florida / real estate / agents" — beside ~200px of empty white, the card **894px tall in a 900px viewport**. Fix is `@container` on the card plus `@lg:` on all five internal breakpoints (`index.tsx`, `PackSpotlight`), so the card reads its own inline size: hero copy stacks at 388px, shelf copy keeps three tracks at ~1200px. **Measured after: 894px → 518px, no clipping, at both 1440 and 1280.** The shelf's copy of the same component was always correct, which is why this shipped — one component, two widths, only one of them ever looked at. |
| F2 | "US rules" → "US market" | **DONE** | Founder: *"US rules shouldbe US market"*. Two render sites, both changed so the shelf says one thing: the row chip `PackRow.tsx:144` (`{marketLabel(pack.market)} market`) and the group divider `index.tsx` (`Built for the {group.label} market`). The divider's own subtitle already argues the wider reading — "the buyers, numbers and legal steps in these are US" — and only the last of those three is a rule. `usTwoPackArt.test.ts:169` pinned the old noun; it now pins `market`, and the rule it actually exists to enforce (**in words, never a flag emoji or a bare country code**) is unchanged. |

### Open conflict to resolve before touching colour

**RESOLVED 2026-08-15: charcoal `#2D3436` stays. The brief's navy `#1B3F8B` is withdrawn.**
Founder, having seen both rendered side by side on a live server: *"charcoal 12.68:1, is
preferrable"*. Contrast on white text, both AAA: charcoal **12.68:1**, navy **9.86:1**.
`tokens.css:200-207` is already correct and needs no edit; the brief's Part Two `--action` line
(`:207`) is now dead and must not be re-applied. Part Two is unblocked for everything except the
`--cat-*` question below.

The comparison was made on `http://localhost:3131` with a throwaway `:root` override, not with
screenshots, so what was judged was the whole button system moving together (`--primary:
var(--action)`, `tokens.css:217`) rather than one crop. The harness was
`src/components/dev/VariantSwitch.tsx` plus a four-line mount in `_app.tsx`, both deliberately <!-- doc-lint-ok: the next line says this harness was deliberately never committed -->
uncommitted.

The history, kept because it is the argument and not just the outcome: Part Two set `--action:
#1B3F8B` and "Blue fills every interactive element". On 2026-08-15 the founder chose Option B,
teal + charcoal, on the grounds that "the teal logo and navy buttons feel like they're from two
different websites", and `Button.tsx:16-23` records the same reading ("the navy read as an orphan
beside the teal identity"). The brief's own "pick one" instruction is now answered: the remaining
pair is filled charcoal `primary` + teal-outline `secondary`.

Second contradiction, same section: rule 5 says "drop category colour-coding entirely", but
`docs/SITE_SPEC_PROGRAM.md` §3 records the 12 `--cat-*` hues as one of two **deliberate documented
exceptions** to the design system, on the grounds that "they carry discovery meaning". The brief's
reasoning — 8+ categories is past what a colour set can teach, and it is the direct cause of the
ransom-note effect — is a live argument against that exception, not an oversight of it. Deleting
`--cat-*` is therefore a change to §3 and must be recorded there in the same commit.

**Third contradiction (item 4b, not colour):** the brief asks the sticky purchase bar for
`box-shadow: 0 -8px 24px rgba(0,0,0,0.06)`. `tokens.css:456` §3.4 (2026-08-08) is "NO BOX-SHADOWS.
Depth is a surface step plus a hairline", `--shadow-1`/`--shadow-2` are both `none`, and
`__tests__/threeRadiiTwoShadows.test.ts` fails any other shadow utility in the tree. The brief's
defect is real and specific — body copy passing under a 1px hairline meets it mid-glyph and reads
as a strikethrough — and §3.4's own replacement (a surface step) is weak here because the bar and
the content behind it are both near-white. Either §3.4 gains a named exception for the one element
that has to float over scrolling text, or the bar gets a stronger tone step instead. Not my call.

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

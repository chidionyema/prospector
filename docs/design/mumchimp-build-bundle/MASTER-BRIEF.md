# MUMCHIMP — MASTER BUILD BRIEF

**Read this file completely before writing any code.**

You are rebuilding the public site at mumchimp.com. Twelve finished HTML mockups sit beside this file in `/mockups`. They are the source of truth for appearance. This file is the source of truth for engineering, data and sequencing. Where they disagree on how something *looks*, the mockup wins. Where they disagree on how something *works*, this file wins.

The site is **live**. Ship in the order given in §8. Do not merge steps.

---

## 0 · WHAT'S IN THE BUNDLE

| File | What it is |
|---|---|
| `mockups/index.html` | Landing page — approved, the reference for everything else |
| `mockups/pack-detail.html` | Pack page (`/pack/{id}`) |
| `mockups/kill-log.html` | `/kill-log` |
| `mockups/how-it-works.html` | `/how-it-works` |
| `mockups/sample.html` | `/sample` |
| `mockups/pricing.html` | `/pricing` |
| `mockups/collections.html` | `/collections` (currently `/ideas`) |
| `mockups/about.html` | `/about` |
| `mockups/faq.html` | `/faq` |
| `mockups/account.html` | `/account` |
| `mockups/refund.html` | Legal template — applies to `/refund`, `/terms`, `/privacy` |
| `mockups/404.html` | Not-found and error states |

All copy in the mockups is the site's real published copy. **Do not rewrite it.** The tone has been worked on deliberately. Where a mockup shortens or reorders existing copy, that change is intentional and is listed in §7.

---

## 1 · DESIGN TOKENS

Every colour, radius and spacing value in the built CSS comes from this block. After this work, a literal outside this list is a bug.

```css
:root{
  color-scheme: light only;

  /* surfaces */
  --paper:#FAFAF7;    /* the page, everywhere, header included */
  --surface:#FFFFFF;  /* cards and panels only */
  --line:#E7E7E1;     /* hairline: inside cards, between rows */
  --line-2:#D8D8D1;   /* rule between sections */

  /* ink */
  --ink:#17191C;      /* headings, the one button, prices */
  --ink-2:#565B62;    /* body */
  --ink-3:#8B9096;    /* captions, eyebrows, mono meta */

  /* meaning — see §2 */
  --brand:#14706A;      --brand-soft:#CFE3E0; --brand-tint:#F2F8F7;
  --warn-b:#C9A227;     --warn-t:#8A6D0B;     --warn-f:#FCF8E8;
  --kill:#B4342B;
  --link:#2447C9;
  --dead:#DEDED7;

  /* shape */
  --r-card:12px; --r-ctl:8px; --pad:20px;

  /* sticky offsets — single source, never hardcode */
  --h-header:58px; --h-filter:40px;
}
```

Permitted derived values, nothing else: `#EFEFEA` (icon hover), `#FCFCFA` (row hover), `#B9BDC2` (count inside a dark chip), `#FFF`/`#000` on buttons, and the kill-grid cause shades `#C2544C #CE6A62 #D8837C #E09C96 #D4B455 #A2A7AC #B8BCC0`.

Spacing on a 4px grid: 4 / 8 / 12 / 16 / 20 / 24 / 26 / 30 / 34 / 40 / 44 / 46.

## 2 · COLOUR IS A CONTRACT

Three colours are the verdict system. A reader learns them once and they hold on every page.

| | Means | Where it appears |
|---|---|---|
| **Teal** `--brand` | survived | logo, passed checks, survivor cells, live source links, "new" badge |
| **Amber** `--warn-*` | pushed back / unverifiable | checks that found nothing decisive, the unverifiable flag |
| **Red** `--kill` | killed | kill verdicts, kill counts, kill-grid cells |
| Blue `--link` | interaction | text links, "View →", focus rings |

**Red is reserved.** It must not be used for form errors, sale badges, required-field markers or emphasis. Form validation uses `--warn-b`. If red appears anywhere that nothing died, that is a bug.

## 3 · TYPE

**Inter** and **IBM Plex Mono**. Self-host both as latin `woff2` subsets, `font-display:swap`, preload the above-fold weights. Do not load from Google Fonts in production — a third-party connection on first paint, and an extra data processor in a UK privacy policy. (The mockups link Google Fonts only because they are standalone files.)

| Role | Size | Weight | Notes |
|---|---|---|---|
| H1 | 31 → 50px | 690 | -0.03em, LH 1.06, max 19ch |
| Section H2 | 23 → 31px | 665 | -0.023em |
| Sub H3 | 18 → 22px | 655 | -0.02em |
| Row / card title | 16.5–17.5px | 625–640 | -0.014em, LH 1.3 |
| Body | 15.5–16px | 400 | LH 1.58–1.68, `--ink-2`, max 62ch |
| About essay body | 18px | 400 | LH 1.68, `--ink`, max 56ch |
| Eyebrow | 12px | 650 | +0.08em, uppercase, `--ink-3` |
| Mono meta | 12–13px | 400/500 | emphasis `--ink` at 500 |
| Verdict chip | 11px | 400 | +0.08em, uppercase, mono |
| Price | 19px (34px in buy box) | 655–690 | £ one step smaller, 600, `--ink-2` |
| Signature figure | 34 → 52px | 710 | -0.035em |

`font-variant-numeric: tabular-nums` on **every** number. Mono is confined to: kickers, counts, proof lines, verdict chips, market tags, citations, dates, file names, footer stat labels. Sentence case throughout; nothing Title Case, nothing ALL CAPS except eyebrows.

## 4 · LAYOUT GRAMMAR

1080px max width, 20px gutters. Three rule weights carry all hierarchy and nothing else does:

- **2px `--ink`** — major section break (`.rule2`)
- **1px `--line-2`** — between sections, above lists
- **hairline `--line`** — inside cards, between rows

Radius 12px cards, 8px controls. No shadows, no gradients, no fourth grey. One button style (ink on white text); secondary is the ghost button or a text link; there is no third.

## 5 · THE DATA LAYER — DO THIS FIRST

The live site currently contradicts itself. These are not styling problems and they must be fixed before any page is rebuilt.

### 5.1 Pack count says four different things
`/` says **68**. `/pricing` says **74**. `/kill-log` says **74**. `/ideas` says **63**.

One source of truth. Every page reads it. On a site whose whole proposition is that its numbers are checkable, this is the most damaging defect on the list.

### 5.2 Three different lists of checks
The pack page names six checks. `/how-it-works` runs nine, worded differently. `/kill-log` lists twelve causes, three of which are not checks at all.

**Canonical six**, used with this exact wording everywhere:

1. Is the pain real, or imagined?
2. Will the value last, or evaporate?
3. Do incumbents already own the space?
4. Can the payer actually pay?
5. Is there a route to reach the market?
6. Is there a legal landmine?

Ideas may face more; a pack page states its own count ("this idea faced 9"). The three kill-log-only causes — *scored below the bar*, *did not survive the adversarial pass*, *defensibility not evidence-backed* — are **stages**, not checks. Label them as stages wherever they appear.

### 5.3 Verdict vocabulary
Three verdicts only: **Survived**, **Pushed back**, **Killed**. "Pushed back" must be defined in the interface at first appearance on `/how-it-works`: *the check found nothing decisive either way, so the idea continued and the doubt stays on the record.*

### 5.4 Shape

```ts
type SiteCounts = { researched:number; killed:number; shelf:number;
                    publishedKills:number; killsWithSources:number;
                    killsByCause:{ cause:string; count:number; isStage:boolean }[] };
type Check = { id:1|2|3|4|5|6; label:string };   // §5.2 wording, immutable
type Pack = { slug:string; title:string; description:string; category:string;
              collections:string[]; sources:number; payback:number|null; price:number;
              market:string|null; addedAt:string; verifiedAt:string;
              checks:{ check:string; verdict:"survived"|"pushed-back"|"killed";
                       reasoning:string; sourceCount:number }[];
              economics:{ month1Revenue:number; ltvCac:number; paybackMonths:number } };
type Kill  = { slug:string; title:string; cause:string; reasoning:string;
               sourceCount:number; assessedAt:string };
```

**`description` is returned whole.** The server must never truncate it — the current mid-clause cuts ("…the financier covers the difference if copper") are a data-layer bug. Clamping is CSS only (`-webkit-line-clamp:2`). Separately audit all descriptions so each ends at a full stop within ~160 characters.

**Proof line** is rendered by one component from `sources` and `payback`, one format sitewide: `41 sources` or `17× payback · 28 sources`. Retire "cited sources behind it" and "the price back in month one, modelled" from cards.

## 6 · SHARED COMPONENTS

Build these once. Every page imports them.

| Component | Props | Notes |
|---|---|---|
| `SiteHeader` | `current` | Sticky, `--paper`, 1px line beneath. Nav: Collections / How it works / Kill log / FAQ, then Account, Search, Menu. **"Catalogue" spelling everywhere.** Naked icons in 44px hit areas. Exactly **one** wordmark in the DOM — the live site renders "MumchimpMumchimp" on every page. |
| `SiteFooter` | — | Identical on every page, including the disclaimer. `/ideas` currently ships a different one. |
| `VerdictChip` | `kind` | survived / pushed-back / killed. The only place `--kill` may appear. |
| `EvidenceCard` | `quote`, `sourceDomain`, `href` | Teal left rule, tint ground, source as live link. The most reusable component in the system — it is what "every claim is sourced" looks like when shown rather than said. |
| `CheckRow` | `index`, `label`, `reasoning`, `sourceCount`, `verdict` | Used on pack, how-it-works, sample. |
| `PackRow` | `pack`, `density:"full"\|"compact"` | Catalogue, related packs, account shortlist. |
| `ProofLine` | `sources`, `payback` | One format, §5.4. |
| `Facts` | 3 × `{label,value}` | The three-cell strip. |
| `SigCard` | `children` | Wrapper for every signature device in §7. |
| `EmailBox` | `variant` | One component, strings swap. |

## 7 · PER-PAGE SPEC

Each page has **one** signature device, built from that page's own data. It is the thing the page is remembered by; everything around it stays quiet.

### `/` — landing *(mockups/index.html)*
Signature: **the kill grid** — 1,444 cells, 1,364 dead, 68 (→74) teal.

**Build it as server-rendered inline SVG, never 1,444 DOM nodes.** `viewBox="0 0 38 38"`, `shape-rendering="crispEdges"`, all dead cells as a **single `<path>`**, each survivor as its own `<rect>` with a `<title>` and an `href` to that pack. 68 interactive nodes is cheap; 1,444 divs is not. Zero client JS. Order cells by research date, oldest first, so the picture is stable between visits.

Everything else: one filter system only (search, category, capability, price + sort), URL-driven per §9. Delete the three-step wizard. The duplicate category rail and capability chips below the bar are removed — they are the same controls twice.

### `/pack/{id}` *(pack-detail.html)*
Signature: **"6 in 100"** — a 100-dot field with six teal, above the six gates.

Order: breadcrumb → title → description → verdict strip → signature → evidence card → economics (£870 / 3.7× / 8 months) → six checks with verdicts and source counts → who it suits → look inside → 14 documents → 6 files → author line → related packs → closing bar.

**One sticky buy box, one closing bar.** The live page renders the full price box twice plus a sticky bar. Drop "34 cited sources, £1.47 each" — it invites price-shopping the sources and penalises packs whose topic needs fewer. Keep the count and the £372/day commissioned-research comparison.

### `/kill-log` *(kill-log.html)*
Signature: **the cause-coloured grid** — 1,444 cells shaded by which check fired.

**The argument is the row.** The live page hides the reasoning until a row is selected, in a 400-row table that is unusable on a phone. Each row shows title, two lines of the real reasoning, the cause, the date, the source count, and a kill chip. Keep sort and cause filters. Distribution bars below the grid, same data, second form.

### `/how-it-works` *(how-it-works.html)*
Signature: **the attrition cascade** — 1,444 narrowing gate by gate with real kill counts subtracted, down to 74.

The nine-check worked example keeps every verdict; the five-source citation lists collapse behind "open them". Then the canonical six with real kill counts and one named example each. Then adversarial pass, human review, honest limits. Define "pushed back" here.

### `/sample` *(sample.html)*
Signature: **the document reader** — sticky contents rail, sheet, failed check flagged amber.

Lead with the check that **failed**. The filter admitting uncertainty is the most persuasive artefact on the site. No email gate, ever.

### `/pricing` *(pricing.html)*
Signature: **the identical-contents matrix** — five price rungs, fourteen identical document marks on every row.

Then the ladder with real counts (9 / 16 / 30 / 17 / 2), the two comparisons as matched pairs, what you don't get beside what's always included. Close on the free sample.

### `/collections` *(collections.html)*
Signature: **the mosaic**, tiles sized by pack count.

**Rename from `/ideas`.** The catalogue already uses "Categories" for a different taxonomy (10 subject categories); this page holds 16 collections about how a business runs and who it suits. Two things cannot share one word. Redirect `/ideas` → `/collections`, keep old category URLs alive. Every tile links to a pre-filtered catalogue URL, not a separate page style. Give each collection a **short display name** alongside its long SEO name — the live page truncates to "Busin…".

### `/about` *(about.html)*
Signature: **the essay setting** — 18px, 56ch measure, signature rule.

Copy is verbatim and stays that way.

### `/faq` *(faq.html)*
Questions reordered by purchase blocker; "Why not just ask a chatbot?" is first. **Remove the "Was this helpful? Yes / No" widget** — 26 dead-end controls on one page. If you want the signal, measure which accordions open. Keep the four group filters and "a human reads every email".

**Note:** answers 2–13 in the mockup were reconstructed from copy elsewhere on the site, because the live page ships them collapsed. Replace with the real answers before shipping.

### `/account` *(account.html)*
Owned packs with download links first, shortlist second, "new since your last visit" third. That third block is the cheapest return hook available.

### Legal *(refund.html)*
One template for `/refund`, `/terms`, `/privacy`. Narrow measure, sticky contents, last-updated at top, plain headings.

### Errors *(404.html)*
Name what happened, offer the one action that fixes it. Errors don't apologise and are never vague.

## 8 · BUILD ORDER — ONE PR PER STEP

1. **Data layer** (§5). No visual work. Fixes the count contradiction and the check lists everywhere at once.
2. **Shared layer** (§1–4, §6). Tokens, type, header, footer, buttons, cards, evidence card, verdict chips, `color-scheme`. Fixes the duplicate wordmark and the nav divergence.
3. **Landing page** — visual only first (no DOM restructure), then the kill grid, then the filter system **behind a feature flag**. Compare catalogue engagement for one week before removing the old wizard path.
4. **Pack detail** — highest commercial value per hour.
5. **Kill log** — highest engagement value.
6. **How it works, sample, pricing, collections** (with the `/ideas` redirect).
7. **About, FAQ, account, legal, errors.**

## 9 · CROSS-CUTTING REQUIREMENTS

**Filters.** State lives in the URL query string (`/?q=&cat=&can=&price=&sort=`), not component state — shareable, back-button correct, server-renderable, and indexable later. Facet counts recompute against other active filters. Zero-result options are **disabled, not hidden**, so controls never reflow under a finger. Result count in an `aria-live="polite"` region.

**Sticky behaviour.** Header at `top:0`, filter bar at `top:var(--h-header)`. On mobile, hide the header on scroll-down and restore on scroll-up so browsing costs 40px, not 98px; disable under `prefers-reduced-motion`. `scroll-margin-top: calc(var(--h-header) + var(--h-filter) + 12px)` on every anchor target.

**Dark mode.** Every page declares `color-scheme: light only` in `<meta>` and CSS, sets `theme-color` to `#FAFAF7`, and paints `--paper` onto `main`, `header`, `footer` and `section` — not `body` alone. Without this, in-app browsers and Android auto-dark render the site on black and the teal goes muddy. The live site currently sets `theme-color:#171717` on most pages and `#0A0A0A` on `/ideas`; neither matches the background.

**Never truncate text by character budget.** Not descriptions, not labels, not nav items. Shorten the source string or clamp in CSS.

**Accessibility.** Focus-visible ring `--link` 2px at 2px offset on every interactive element. 44px minimum hit areas. One `<h1>`, unbroken heading levels. Colour never the only signal. Signature graphics are a single `role="img"` with a full aria-label; interactive cells inside are links with accessible names. Target Lighthouse a11y ≥ 95 and a clean keyboard-only pass.

**Performance.** LCP < 2.0s on a mid-range Android, CLS < 0.05, page JS < 40KB gzipped, no layout-triggering animation, catalogue paginated server-side.

**Structured data.** `Product` + `offers` on pack pages, `ItemList` on catalogue and collections, `FAQPage` on the FAQ, `Organization` sitewide.

**Analytics.** Wire these names: `landing_view`, `grid_survivor_click{slug}`, `filter_change{dimension,value,resultCount}`, `filter_zero_results`, `catalogue_page_more`, `pack_row_click{slug,position}`, `featured_click`, `sample_cta_click`, `kill_row_click{slug,cause}`, `band_view{bandId}`, `email_submit`, `scroll_depth{25,50,75,100}`.

## 10 · ACCEPTANCE — RUN EVERY LINE, REPORT EACH CONFIRMED

- [ ] Pack count identical on every page, from one source
- [ ] One canonical check list, §5.2 wording, used identically everywhere
- [ ] Stages labelled as stages, not checks
- [ ] "Pushed back" defined in the interface at first appearance
- [ ] `--kill` appears only where something died; form errors use `--warn-b`
- [ ] No colour outside §1's tokens and permitted derived values
- [ ] Header and footer identical on every page; "Catalogue" spelling; Search present
- [ ] "Mumchimp" appears exactly once in the header DOM
- [ ] `color-scheme: light only` + `theme-color:#FAFAF7` on every page; renders on paper in a dark-mode phone browser
- [ ] Kill grid is inline SVG: one path + N rects, zero client JS, correct aria-label
- [ ] No text truncated by character budget anywhere
- [ ] No rendered description ends mid-word; all audited to end at a full stop
- [ ] One proof-line format sitewide
- [ ] Exactly one filter system on the landing page; state round-trips through the URL; back button restores results
- [ ] Zero-result facet options disabled, not hidden
- [ ] Kill log rows show reasoning without a click
- [ ] Pack page has one sticky buy box plus one closing bar; per-source pricing removed
- [ ] FAQ helpfulness widget removed
- [ ] `/ideas` redirects to `/collections`; old category URLs alive
- [ ] Tabular numerals everywhere; mono confined to permitted uses
- [ ] Focus rings, 44px targets, one `<h1>` per page
- [ ] Keyboard-only pass completes each page's primary task
- [ ] Lighthouse a11y ≥ 95, performance ≥ 90, CLS < 0.05
- [ ] All twelve analytics events fire with correct payloads
- [ ] Screenshots at 390px and 1280px for every page

## 11 · PASTE THIS TO START

> Build the Mumchimp public site to `MASTER-BRIEF.md` in this bundle, using the twelve files in `/mockups` as the visual reference. Mockups win on appearance, the brief wins on engineering.
>
> Begin with §5, the data layer, before any visual work. The live site states 68, 74 and 63 packs on different pages and uses three different lists of checks — that is the highest-priority defect and it is a data problem.
>
> Hard rules: every colour and spacing value comes from §1; teal means survived, amber means pushed back, red means killed and appears nowhere else; header and footer are single shared components with "Catalogue" spelling; every page declares `color-scheme: light only` and paints `--paper` onto layout elements; the kill grid is server-rendered inline SVG with zero client JS; no text is ever truncated by character budget; all copy in the mockups is the site's real published copy and must not be rewritten.
>
> Follow the build order in §8, one PR per step, with step 3's filter system behind a feature flag. For each PR, run every line of the §10 checklist and paste it back confirmed, with screenshots at 390px and 1280px and a keyboard-only walkthrough note.

# Design, Look-and-Feel and UX Audit — pre-launch, every page

> Founder directive, 2026-08-08: *"a serious design, looking feel and ux audit across every page
> before launch, we need to exceed thresholds and be thinking 2050 standards"* and *"obsessive
> details across the board"*.
>
> **This document is the programme.** Findings are appended HERE, never to a chat transcript and
> never to `CLAUDE.md`. Sibling programmes: `SITE_SPEC_PROGRAM.md` (the design/copy spec and its
> status ledger), `COMMERCIAL_READINESS_PROGRAM.md`, `COST_PROGRAM.md`.

---

## 0. The two rules that produced this document

**0.1 — An audit produces FINDINGS, not commits.** On 2026-08-08 the §3 design system was
implemented in full (61 files, PR 134) and rejected by the founder on sight after one local look:
*"it looks objectively worse than whats live currently."* `docs/SITE_SPEC_PROGRAM.md` row 3 had
already said `do not implement without founder sign-off`. Nothing in this programme gets built
before its finding is agreed and, where taste is involved, seen. A screenshot costs a minute; a
redesign costs a week and can be worse.

**0.2 — Every finding carries a measured number and a picture.** Not "the spacing feels off":
*"`/pricing` at 360×780, the gap between the rung cards is 12px while every other card grid on the
site uses 24px (`index.tsx:1702`, `kill-log.tsx:311`) — screenshot `audit/pricing-360.png`."* A
finding with no number and no image is an opinion, and opinions are the founder's job, not the
auditor's. Related: memory `never-judge-design-by-grepping-html` — the DOM is not the design;
measure the RENDERED page.

---

## 1. The bar: what "2050 standards" means, concretely

Aspiration is not auditable, so the phrase is decomposed into falsifiable thresholds. Each one is
stricter than the industry-standard floor, because the directive is to EXCEED thresholds, not meet
them. The floor is given alongside so the gap is explicit.

| # | Dimension | Industry floor | **This bar** | How it is measured |
|---|---|---|---|---|
| T1 | Text contrast | WCAG AA 4.5:1 | **AAA 7:1** body, 4.5:1 for ≥24px | computed styles → contrast ratio, every text node |
| T2 | Non-text contrast | 3:1 | **3:1 with no exceptions**, incl. borders, focus rings, disabled states | computed styles on borders/icons |
| T3 | Tap targets | 24×24 (AA) | **44×44 minimum, 48×48 preferred**, 8px min gap | bounding boxes of every interactive element |
| T4 | Above the fold | "hero visible" | **the PRODUCT visible with ≥40px showing at 360×780** | `e2e/discovery.spec.ts:70` (already enforced) |
| T5 | LCP | <2.5s | **<1.2s on Slow 4G**, <0.8s on cable | Lighthouse + WebPageTest, live |
| T6 | CLS | <0.1 | **0.00** — every image and embed reserves its box | Lighthouse, plus a font-swap check |
| T7 | INP | <200ms | **<100ms** | Lighthouse, plus manual on the facet bar |
| T8 | Keyboard | "operable" | **every task completable without a mouse, focus visible at 3:1 at all times, no traps, logical order** | manual tab-through, recorded |
| T9 | Zoom / reflow | 200% no loss | **400% at 320px wide, no horizontal scroll, nothing clipped** | viewport 320 + browser zoom |
| T10 | Motion | reduced-motion honoured | **honoured AND ≤200ms AND one easing curve** | computed styles + emulate `prefers-reduced-motion` |
| T11 | Type | "readable" | **45–75ch measure, ≤6 sizes sitewide, ≤2 weights per size, no widows on headings** | computed styles + text metrics |
| T12 | Colour | "on brand" | **one accent, ≤3 neutrals, every hex traceable to a token** | computed styles, no arbitrary hex |
| T13 | Consistency | "similar" | **one primitive per job — one button, one card, one chip, one link style** | component census across all pages |
| T14 | States | hover + focus | **all 8: rest, hover, focus-visible, active, disabled, loading, empty, error** | forced states, screenshot each |
| T15 | Content edges | "looks fine" | **longest + shortest real record renders correctly**, 0 results, 1 result, missing image | real catalogue data, not lorem |
| T16 | Dark mode | optional | **decided explicitly** — either supported everywhere or supported nowhere; no half-state | `prefers-color-scheme` emulation |

---

## 2. Method — how each page is audited

Per page, at **five viewports**: 320×568 (smallest real phone), 360×780 (the worst-case Android
that has already caught one regression), 390×844, 768×1024 (tablet portrait, the width nobody
tests), 1440×900 (desktop). Plus 2560 wide for max-width behaviour.

For each page/viewport pair, capture:

1. **Full-page screenshot** → `docs/audit/<page>-<width>.png`
2. **First-screen screenshot** (viewport-clipped) — what the buyer actually meets
3. **Block ledger** — every block above the fold with its `y` and `height`, so the fold budget is a
   table of numbers rather than an impression (the technique that diagnosed the 240px proof strip)
4. **Computed-style census** — every distinct font-size, weight, line-height, colour, border-radius,
   shadow, gap actually RENDERED on the page. This is the only honest way to count "how many type
   sizes does this site have"; the stylesheet declares intent, the page is the truth.
5. **Interactive inventory** — every focusable element, its accessible name, its box, its 8 states
6. **Axe-core pass** — automated a11y violations, as a floor, never as the ceiling

Then read the page as a **buyer**, at each width, and answer in writing:
- What is this page for, and does its first screen say so in under 3 seconds?
- What is the single next action, and is it unmistakably the loudest thing?
- What here is decoration that costs vertical space and earns nothing?
- What would a sceptic distrust, and is the receipt for it one click away?

---

## 3. Severity scale

| | Meaning | Ship gate |
|---|---|---|
| **S0** | Broken or embarrassing on a real device; loses the sale outright | blocks launch |
| **S1** | Measurably costs conversion or excludes users (a11y, mobile fold, unreadable contrast) | blocks launch |
| **S2** | Inconsistency a careful visitor notices; erodes the "this is rigorous" claim | fix before launch if cheap, else logged |
| **S3** | Taste and refinement; needs founder sign-off before any work starts | never auto-implemented |

The distinction matters because of §0.1: **S0/S1 are objective and I can fix them; S3 is the
founder's call and I must show, not build.**

---

## 4. Page ledger

Status values: `not started` / `captured` (screenshots + measurements taken) / `audited` (findings
written) / `agreed` (founder has ruled on S3 items) / `fixed`.

| Page | Route | Priority | Status | Findings |
|---|---|---|---|---|
| Home | `/` | P0 — the shop | audited | F-001 fold, F-002, F-003, F-005, F-006 |
| Pack detail | `/pack/[id]` | P0 — the money page | audited | F-002, F-003 |
| Pricing | `/pricing` | P0 — the money page | audited | F-003 |
| Checkout overlay | (embedded on pack) | P0 — the money rail | **not started** | needs a driven flow, not a page load — see §5.1 gap 1 |
| Sample | `/sample` | P1 — the proof | audited | F-003, F-006 |
| Kill log | `/kill-log` | P1 — the receipt | audited | F-003 (1224 nodes — worst on the site) |
| How it works | `/how-it-works` | P1 | audited | F-003, F-005 |
| Catalogue browse states | `/` + facets | P1 | **not started** | needs interaction states — §5.1 gap 2 |
| Ideas index | `/ideas` | P1 | audited | F-006, F-007 |
| Idea detail | `/ideas/[slug]` | P1 | audited | F-003, F-005 |
| About | `/about` | P2 | audited | F-003 |
| FAQ | `/faq` | P2 | audited | F-003 |
| Order receipt | `/orders/[token]` | P1 — post-purchase | **not started** | needs a real order token — §5.1 gap 3 |
| Order success | `/orders/success` | P1 — post-purchase | audited | F-004 (minor CLS) |
| Account | `/account` | P2 | audited | **F-004 — worst CLS on the site** |
| Auth callback | `/auth/callback` | P2 | **not started** | needs a live auth round-trip — §5.1 gap 3 |
| Terms | `/terms` | P3 | audited | F-003 |
| Privacy | `/privacy` | P3 | audited | F-003 |
| Refund | `/refund` | P3 | audited | F-003 |
| 404 | `/404` | P2 | audited | F-003 |
| 500 | `/500` | P2 | **not started** | cannot be provoked from outside — §5.1 gap 4 |
| Global chrome | header, footer, nav, skip link | P0 — on every page | audited | F-006 (search button 34×30) |
| Metadata | `<title>`, OG image, favicon per route | P2 | partial | titles+descriptions captured; OG/favicon not — §5.1 gap 5 |

**The post-purchase pages are P1, not P3, on purpose.** They are the only pages a paying customer
sees after money moves, and they are the least looked at.

---

## 5. Findings

> Appended as the audit runs. Format is fixed: ID, page, viewport, severity, the measured claim,
> the evidence path, and the proposed change — with S3 items stating explicitly that they need
> sign-off before any code is written.

### F-001 — Home, mobile: the first product is below the fold on every phone (S1) — **FIXED 2026-08-08**

**Outcome, measured on a built tree at `3be12ca` by `scripts/design-audit/measure-fold.mjs`:**

| viewport | before | after |
|---|---|---|
| 360×780 | card at y=937, **−157px** (FAIL) | y=704, **+76px** (PASS) |
| 390×844 | y=937, **−93px** (FAIL) | y=704, **+140px** (PASS) |
| 430×932 | y=875, +57px (thin pass) | y=666, **+266px** (PASS) |
| 1280×720 | y=129, +591px | y=129, +591px (unchanged) |

**Two things in the original finding below are wrong, and only re-measuring the current tree
caught either:**

1. **"proof strip 240px" does not name `HeroEvidenceStrip`.** That component is `hidden md:block`
   (`src/pages/index.tsx:1579`) and contributes zero height on a phone. The 233px block is the
   *stats* band — "1,444 ideas researched. 80 survived." — a different element entirely.
   `e2e/discovery.spec.ts:56` had the culprit right where this finding had it wrong.
2. **The numbers had drifted.** The card was at y=937, not y=958, because four merges landed
   between the audit and the fix. A finding not re-measured before it is fixed is a finding
   about a tree that no longer exists.

**The fix contained a silent no-op that measurement caught before it shipped.** `SectionBand`
applies `className` to the INNER div, not the `<section>` (`blocks.tsx:47-48`). `order` only
means something to a flex *parent*, so it would have landed on a node that is not the wrapper's
child: present in the DOM, applied cleanly, cascading nothing, fold unchanged. `SectionBand` and
`Section` now take an explicit `outerClassName`. Wrapping the shelf also made it `:last-child`
for the first time, which `last:border-b-0` would have used to delete the divider under the
shelf at every width — pinned with `outerClassName="!border-b"`.

The probe itself had to be corrected twice, and both defects would have produced confident wrong
attributions: it read `textContent` (which serialises `display:none` subtrees, so the hero
reported the hidden kill column's text), and it listed DOM-preceding siblings rather than
visually-above ones (which would have reported this very fix as having changed nothing, since
`order` moves the band without moving it in the document).

---

**Original finding, as written:**

`e2e/discovery.spec.ts:70` red against production, run 31231400949. Measured on live at 360×780:
header 65px, hero 385px, **proof strip 240px**, first pack card at **y=958** on a 780px screen —
178px below the fold; 114px at 390×844; clears 430×932 by 2px. Introduced by PR 133 (`bcda8cc`),
which added the proof strip above the shelf; last green smoke was `6935307`.

Fix: the strip keeps its spec position from `sm:` up and moves below the shelf on phones, via
`order` on a flex wrapper (one DOM node, no duplicated copy). Shrinking was measured and rejected —
dropping the second paragraph and tightening padding recovers ~90px of the 218px needed.

### Provenance for F-002 … F-012

Harness `store_platform/src/Store.Web/scripts/design-audit/audit.mjs`, reporter `report.mjs`.
Run 2026-08-08T02:16Z against **https://mumchimp.com** (§6: live is the baseline), Chromium
headless, 16 routes × 6 viewports = **96 pairs, 0 errors**, 208 screenshots in `docs/audit/`,
raw numbers in `docs/audit/audit-raw.json`. Reproduce:

```bash
cd store_platform/src/Store.Web
AUDIT_BASE=https://mumchimp.com node scripts/design-audit/audit.mjs   # ~20 min, writes docs/audit/
node scripts/design-audit/report.mjs                                  # scores it against T1-T16
```

**The instrument was checked before its output was believed** (§0.2 applies to the auditor too).
An independent Python recompute of the WCAG formula agreed with the harness on **40/40** fg/bg
pairs. Two classes of false positive were found and are now excluded rather than reported:
`sr-only` skip links measure 1×1 by design, and WCAG 2.5.8 exempts links inline in a sentence.
A third — "3766 elements still animating under reduced-motion" — was a **defect in my metric,
not the site**; see F-011.

### F-002 — `--text-faint` is 2.56:1: fails even the AA floor (S1)

Measured on live: `rgb(161, 161, 170)` on `rgb(255,255,255)` = **2.56:1**, and on the `rgb(250,250,250)`
search chip = **2.46:1**. The bar is 7:1; the WCAG **AA floor is 4.5:1**, so this is not a
"we set a strict bar" finding — it is below the legal-ish floor too.

Cross-validated independently: axe-core flags the same node, `color-contrast`, impact **serious**,
selector `.text-faint.flex-1.text-meta`. Two instruments, one conclusion.

Where it shows: the header search button's placeholder "Search the catalogue" (14px/400), its `⌘K`
hint (12px), and every `├──`/`└──` tree glyph in the pack shelf (12px). 89 failing text nodes on
`/` at 360; 68 on `/pack/[id]`. Evidence: `docs/audit/home-360.png`, `audit-raw.json`.

Proposed change (objective, no taste call): raise `--text-faint` until it clears 7:1 on **both**
backgrounds it actually renders on. Computed candidates — the near-miss is the point, the token has
to clear the darker `#fafafa` chip, not just white:

| candidate | on `#ffffff` | on `#fafafa` | verdict |
|---|---|---|---|
| `rgb(161,161,170)` (current) | 2.56 | 2.46 | fails the AA floor |
| `rgb(90,90,99)` | 6.82 | 6.54 | still fails 7:1 |
| `rgb(88,88,96)` | 7.05 | 6.75 | passes on white only |
| **`rgb(85,85,94)`** | **7.38** | **7.07** | **clears 7:1 on both** |

**S1 — I can fix this without sign-off**, but it changes a global token, so the diff should be seen
before merge.

### F-003 — the site's main muted colour is 4.63:1: passes AA, misses the 7:1 bar (S2)

`rgb(113, 113, 122)` measures **4.83:1 on white** and **4.63:1 on `#fafafa`** — the two backgrounds
it is ever rendered on (1878 captured nodes: 810 on white, 1068 on `#fafafa`; the `#f4f4f5`
pairing, which would compute 4.40 and breach the AA floor, was checked for and **does not occur**).
It is far and away the most common failing colour, i.e. it is *the* body-secondary token.

The "worst 4.63" headline on several routes is in fact a tie: the kill-log's `rgb(220,38,38)`
"killed" red on `#fafafa` also lands on 4.63. Volume by route at 360: kill-log **1224** failing
nodes of 1696 checked, home 89, pack-detail 68, pricing 58, idea-detail 57, how-it-works 49.

This is the honest shape of the finding: **the site is comfortably AA-compliant and fails only the
AAA bar this programme chose to set.** Fixing it is a sitewide tone shift on the largest text
surface, which is a taste decision, not a defect repair. Recorded as **S2 and explicitly NOT
actioned**: per §0.1 it needs sign-off, and per §3 only S0/S1 are mine to fix.

### F-004 — `/account` shifts 0.184 after load (S1)

CLS by viewport: 320 **0.134**, 360 **0.184**, 390 **0.185**, 768 **0.186**, 1440 **0.110**,
2560 **0.083**. The bar is 0.00 and the industry floor is 0.1 — five of six viewports miss the
floor. Two discrete shifts every time, at ~710ms and ~790ms (`audit-raw.json` → `perf.shifts`),
which is the signature of auth state resolving and swapping the content block.

Two other routes shift, both trivially: `/orders/success` max **0.008** and `/pack/[id]` max
**0.003** (1440 and 2560 only). **13 of the 16 routes measured 0.000 at all six viewports**, and
**0 images sitewide lack a reserved box** — so `/account` is one localised bug, not a systemic CLS
problem. S1, objectively fixable: reserve the block's height while auth resolves.

### F-005 — LCP 2.3–3.8s on four routes, against a 1.2s bar and a 2.5s floor (S1) — **FIXED 2026-08-08**

**The stated hypothesis was wrong, and so were the two I formed after it.** The finding below
proposed that the slow set was "the routes doing client-side data fetching after hydration". It
is not: under throttling, **1/1 over-floor routes and 5/5 under-floor routes** have a post-load
`xhr`/`fetch`, so the property does not discriminate at all. I then proposed the `animate-rise`
entrance animation (0.24s — far too short to explain a 1.7s delta) and a production-API round
trip in `getServerSideProps` (TTFB measured **6–150ms** on every route). Both dead.

**What it actually was**, from the check the finding itself specified — capture the LCP
*element* — implemented in `scripts/design-audit/measure-lcp.mjs` by serialising `entry.element`
**inside** the observer callback, where it is still live, instead of reading it afterwards when
React has re-rendered the node and the field is null:

```
route            FCP     LCP    LCP candidates
/               328ms  1940ms   p @328ms (9,696) then the h1 @1940ms (33,796)
/how-it-works   164ms  1824ms   lead @164ms then the hero lead @1824ms
/ideas          208ms  1860ms   caption @208ms then the h1 @1860ms
/pricing        180ms   180ms   ONE candidate
/about          136ms   136ms   ONE candidate
/kill-log       316ms   316ms   ONE candidate
```

Every page painted in **136–328ms**. The three slow routes emitted a *second, larger* candidate
~1.7s later — the hero headline. `@keyframes rise` starts at `opacity: 0` (`tokens.css:537`),
and **an element at opacity 0 is not eligible to be the Largest Contentful Paint**. The slow set
is exactly the set with an animated hero: `/` (`index.tsx:1461`) and the two routes using
`PageHero` (`blocks.tsx:98`). The pages were never slow — the metric was waiting on a fade.

Fix: `animate-settle`, the same curve and duration with the opacity leg removed, on hero bands
only. `animate-rise` is unchanged everywhere else.

| route | before (unthrottled) | after | before (LH-mobile) | after |
|---|---|---|---|---|
| `/` | 1972ms | **436ms** | 2632ms | **1304ms** |
| `/how-it-works` | 1800ms | **188ms** | 2012ms | **1064ms** |
| `/ideas` | 1872ms | **228ms** | 2064ms | **1124ms** |
| `/kill-log` (control) | 1452ms | 1456ms | 1452ms | 1456ms |

Routes over the 2500ms floor under Lighthouse-mobile throttling: **4 → 0**. `/kill-log` is the
control and is unchanged, which is what makes the other three attributable to the change rather
than to the lab.

**Still over the 1.2s bar under throttling:** `/` at 1304ms and `/kill-log` at 1456ms. Those are
real and unfixed; the floor is cleared, the bar is not.

---

**Original finding, as written:**

`/` measured 2584–3544ms across the six viewports. Because a single slow load proves nothing, it
was **re-measured five times at 360 with a fresh context**: 3292, 3180, 3768, 3260, 3152ms —
min 3152, max 3768, spread 616ms, ratio 1.20. **Stable, therefore a property of the page, not the
network.**

Consistently over the floor at all six viewports: `/` (2584–3544), `/how-it-works` (2264–3088),
`/ideas` (2324–3064), `/ideas/[slug]` (2264–2784).

Fast, for contrast — the same harness, same session: `/pricing` 292–416ms, `/about` 252–392ms,
`/kill-log` 508–728ms, `/pack/[id]` 420–528ms, `/404` 276–432ms. So the platform is capable of
sub-500ms; four routes are not getting it.

**HYPOTHESIS, not yet proven:** the slow set is the routes doing client-side data fetching after
hydration. The check that would confirm or kill it: capture the LCP *element* per route (the probe
returned `?` because `entry.element` is null once the node is re-rendered) and compare against each
route's data-fetch waterfall in `read_network_requests`.

Not established: `/sample`, `/terms`, `/privacy`, `/refund`, `/faq` each swung between ~250ms and
~3800ms across viewports on identical content. That is a 10× spread, so **those numbers are noise
and are not reported as findings** — they need a throttled lab run (Lighthouse) as T5 specifies.

### F-006 — real tap targets under 44×44 (S1)

Excluding sr-only and inline-prose links, the genuine misses:

- `/ideas` category links are SVG anchors (`div.rounded-md.border > svg > a`): **31×27, 31×28,
  31×31, 37×23, 39×23, 44×23** at 320. Seven of them, all below bar on both axes.
- The global header search button is **34×30 on every route and every viewport** — it is in the
  sticky chrome, so it fails on all 23 pages at once.

Counts of real (non-exempt) failures at 360: kill-log 28, sample 21, ideas-index 22, home 18,
pack-detail 17, faq 16, account 13. S1, objectively fixable: pad to 44×44, which for the header
button is a padding change with no visual weight change.

### F-007 — `/ideas` has 7 fractional type sizes from SVG text (S2)

Sitewide the HTML type scale is disciplined: **6 sizes or fewer on 15 of 16 routes** (12, 14, 16,
24, 32, 48) — that **passes T11**. `/ideas` alone reports 14, and the extra 7 are all fractional —
12.017, 12.2727, 12.7841, 14.8295, 15.0852, 15.8523, 16.3636px — every one of them `<text>` inside
`svg > a`, i.e. a scaled SVG label, one node each. Not a stylesheet problem; an artefact of scaling
text in SVG. S2.

### F-008 — 19 distinct text colours against a "one accent, ≤3 neutrals" bar (S2/S3)

Rendered, not declared: 19 text colours, 9 backgrounds, 5 border colours. The set includes six
distinct semantic hues (`rgb(4,120,87)`, `rgb(15,118,110)`, `rgb(29,78,216)`, `rgb(37,99,235)`,
`rgb(67,56,202)`, `rgb(109,40,217)`, `rgb(157,23,77)`, `rgb(180,83,9)`, `rgb(185,28,28)`,
`rgb(220,38,38)`) — that is at least two blues and two reds doing similar jobs. Two values are
`oklab(...)` with alpha, which are not traceable to a named token.

Consolidation is a design decision. **S3 — show, do not build** (§0.1).

### F-009 — 16 distinct grid/flex gap values (S2)

`1px, 2px, 4px, 6px, 8px, 8.16px, 10px, 12px, 16px, 20px, 24px, 28px, 32px, 40px, 48px, 56px`.
The `8.16px` is not on any spacing scale and is almost certainly a computed leftover. Against
T13's "one primitive per job" this is the weakest area of the system. S2.

By contrast **border-radius is clean**: exactly three values — `4px`, `8px`, and a pill
(`3.35544e+07px`, Chrome's computed form of a full round) — and **one** box-shadow sitewide. T13
passes on those two.

### F-010 — two easing curves (S3)

`cubic-bezier(0.2, 0, 0, 1)` and `cubic-bezier(0.4, 0, 0.2, 1)` (the Tailwind default). T10 asks for
one. Trivial to unify, but it is a motion-feel decision. S3.

### F-011 — RETRACTED: "reduced motion is not honoured" was my bug, not the site's

The first pass reported *"3766 elements still animating under prefers-reduced-motion"* on `/` and a
violation on all 16 routes. **That finding is withdrawn.** The metric counted elements whose
computed transition-duration was non-zero, which is every element carrying a 150ms hover — a design
system, not a defect.

Re-probed authoritatively with `reducedMotion: 'reduce'` emulated: the stylesheet contains **3
`prefers-reduced-motion` rules**, and the count of elements exceeding the 200ms bar is **0** — the
240s `killDrift` animation on `.kill-drift` is correctly disabled. **T10 passes on both
reduced-motion and the ≤200ms bar.** The harness metric was rewritten to report
`over200ms`; the discredited `stillAnimating` shape now prints as "legacy — re-run" rather than a
number that meant something else.

### F-012 — axe-core floor: 3 real violation classes (S1/S2)

Run at 360 and 1440 on every route. Aggregated:

| impact | rule | nodes | meaning |
|---|---|---|---|
| serious | `dlitem` | 24 | `<dt>`/`<dd>` not contained by a `<dl>` — invalid HTML, breaks screen-reader list semantics. **S1** |
| serious | `link-name` | 4 | links with no discernible text — unreachable by voice control or screen reader. **S1** |
| serious | `color-contrast` | 7 | the F-002 nodes, independently confirmed |
| moderate | `heading-order` | 8 | heading levels skip (e.g. `.md\:p-8 > h3`). **S2** |

### F-013 — the harness manufactured its own LCP failure (S1, instrument) — **FIXED 2026-08-08**

A 6-viewport home sweep on production reported **LCP 4964ms @1440 and 4672ms @2560** against
472–952ms on phones, i.e. 5–7× worse at the *larger* viewport. That number was the instrument, not
the site.

`audit.mjs` screenshotted **before** it read the metrics, and `page.screenshot({fullPage: true})`
resizes the viewport. The resize re-fires `largest-contentful-paint` for the **same** element at its
new size with a late timestamp, and `measure` takes `Math.max` of every entry (`audit.mjs:330`).

Repro, production, one page load, reading `window.__lcpAll` either side of the screenshot call:

```
=== 1440x900 ===
max LCP BEFORE fullPage screenshot:  716ms  (1 candidate)
max LCP AFTER  fullPage screenshot: 3652ms  (2 candidates)
  late candidate: {"t":3652,"size":55263,"tag":"H1","text":"Business ideas with the research already done."}
=== 360x780 ===
max LCP BEFORE:  596ms  ·  AFTER: 596ms  (1 candidate)   <- phones never fired a second candidate
```

Same element (the H1), larger box (55263 vs 51728), late clock. Phones did not fire a second
candidate, which is exactly why the artefact looked like a desktop-only regression.

**Fix:** `Object.assign(rec, await page.evaluate(measure))` now runs *before* the screenshot loop
(`scripts/design-audit/audit.mjs:361`), with the reason in a comment so it cannot be reordered back.

**Corrected numbers, production, home, after the fix** — LCP passes the 1200ms bar everywhere:

| vp | LCP (was) | LCP (real) | CLS | contrast fails |
|---|---|---|---|---|
| 320 | 952 | **564** | **0.033** | 80/267 |
| 360 | 804 | **484** | 0.001 | 80/267 |
| 390 | 672 | **472** | 0.002 | 80/267 |
| 768 | 696 | **492** | 0.017 | 87/290 |
| 1440 | 4964 | **564** | 0.009 | 207/412 |
| 2560 | 4672 | **612** | 0.007 | 207/412 |

Three consequences, and they matter more than the fix:

1. **"Desktop LCP" is withdrawn.** There is no desktop performance defect on home. Do not open work
   against it.
2. **CLS 0.033 at 320 survived the correction** (0.033 before, 0.033 after), so it is real, not an
   artefact of the same resize. Against T6's 0.000 bar it stands as a genuine open item.
3. **The "desktop contrast is 2.5× worse" reading is also withdrawn.** 207@1440 vs 80@360 is not a
   desktop-specific palette: it is the **same two tokens on more rendered nodes** (412 checked vs
   267). Grouped by colour pair, both viewports are the identical four pairs —
   `rgb(113,113,122)` at 4.83/4.63 (**F-003**) and `rgb(161,161,170)` at **2.56** (**F-002**), 8
   nodes at every width. Only **8 of the 207** are below the AA 4.5:1 floor; the rest fail only the
   7:1 house bar. Fixing F-002 and F-003 clears both viewports; there is no third finding here.

**Also confirmed by this run:** F-002's 2.56:1 nodes are still live **on production** — the a11y
pass that fixed them landed on `fix/storefront-a11y`, not on what is served.

### F-014 — a phone gets no evidence above the fold at all (S1)

`HeroEvidenceStrip` is `hidden md:block` (`src/pages/index.tsx:1673`) and the featured pack slot is
`hidden lg:block` (`src/pages/index.tsx:1681`). Below 768px the fold therefore contains a headline,
a sub-line and two CTAs, and **nothing the brand is built on**: no verdict, no kill count, no pack.
Confirmed two ways in the sweep — `home-360-fold.png`, and the heading census, where 320/360/390
carry neither "New this week" nor "Newest survivors" while 768+ carry both.

For an evidence-first storefront this is the largest conversion item in the ledger: the one claim
the site can prove on sight is withheld from the majority device class. It is **not** a redesign —
the artefact already exists and already renders; the question is only what a phone may see of it,
and at what fold cost (F-001 bought that budget back, and the 360 fold currently passes with 236px
to spare against a 40px bar).

S1. Proposed change is a story, not a patch: see `specs/home-mobile-evidence-and-cls.md`.

### 5.1 What this audit did NOT cover (so the ledger is not read as complete)

1. **Checkout overlay** — embedded on the pack page and only reachable by driving a purchase; a page
   load cannot see it. The P0 money-rail surface is therefore **unaudited**.
2. **Catalogue browse/facet states** and T14's 8 component states (hover, focus-visible, active,
   disabled, loading, empty, error) — this harness measures the rest state only.
3. **`/orders/[token]` and `/auth/callback`** — need a real order token and a live auth round-trip.
4. **`/500`** — cannot be provoked from outside.
5. **T8 keyboard**, **T15 content edges** (longest/shortest real record, 0/1 results), **OG images
   and favicons**, and **T9 at 400% browser zoom** (only 320px width was measured, and it was clean).
6. **T5 in a lab** — see F-005; five routes have unusable LCP numbers until throttled runs exist.

**Passing, and worth recording as such** — an audit that only lists faults misrepresents the site:

- **T6** CLS 0.000 at all six viewports on **13 of 16 routes**, and 0 images sitewide missing a
  reserved box.
- **T9** zero horizontal overflow at every width measured, including 320px.
- **T10** reduced-motion honoured (3 rules, 0 elements over 200ms under `reduce`); all durations
  ≤200ms.
- **T11** ≤6 type sizes on **15 of 16** routes (12/14/16/24/32/48).
- **T13** exactly three border-radii and **one** box-shadow sitewide.
- **T16** dark mode consistently absent on all 16 routes — a decided "nowhere", not a half-state.

---

## 6. Standing constraints on this programme

- **No redesign lands without sign-off.** See §0.1. The §3 branch
  `feat/site-spec-3-design-system` (`d19a39c`) is preserved but closed; do not resurrect it wholesale.
- **The live site is the baseline**, not any local branch. The founder judged live better than the
  §3 preview, so `https://mumchimp.com` at `origin/main` is what "current" means here.
- **Appearance unit tests are suspended** (founder directive, 2026-08-08) and are NOT the mechanism
  for this audit. This programme measures the rendered page in a real browser, which is what those
  tests could never do — a source-text scan cannot see a fold, a contrast ratio, or a tap target.
- **Buyer-facing truth guards stay on** (`fixedCheckCount`, `checkLexicon`, `packContents`,
  `priceRange`, `stats`): a false number told to a buyer is not an appearance question.

---

## 7. Fix log — the S1 axe floor (2026-08-08)

Branch `fix/storefront-a11y`, cut from `origin/main` **after** PR #137 merged the §3 design system
(so `styles/tokens.css` exists on main; §6's "the §3 branch is closed" refers to
`feat/site-spec-3-design-system`, a different tree).

**Verification is a command, not a claim.** `scripts/design-audit/verify-a11y.mjs` re-runs the five
rules that produced findings, on 8 routes × 2 viewports, against a **built** tree served by
`next start` and pointed at the real API — because a dev-server or source-text check cannot see any
of this. It exits non-zero on any surviving node.

    NEXT_PUBLIC_API_URL=https://api.mumchimp.com npm run build
    npx next start -p 3411 &
    VERIFY_BASE=http://localhost:3411 node scripts/design-audit/verify-a11y.mjs

| rule | audit | after | fix |
|---|---|---|---|
| `dlitem` + `definition-list` | 24 | 0 | `sample.tsx`, `pack/[id].tsx` scorecards |
| `color-contrast` | 7 | 0 | `--faint` misuse, plus two token *pairings* (below) |
| `link-name` | 4 | 0 | `ShareRow`'s X and LinkedIn links had no accessible name |
| `heading-order` | 8 | 0 | footer `h3`→`h2`; `MethodCostAnchor` `h3`→`h2` |

### The two corrections this pass made to its own earlier diagnosis

1. **A single `<div>` wrapper inside `<dl>` is VALID** — the HTML Living Standard allows it and
   axe-core 4.12.1 passes it. Fixture-proven before any edit: only a *doubly*-nested div, or a
   non-`dt`/`dd` sibling under the wrapper, fails. An earlier pass had rewritten `DataList.tsx` and
   all three `PriceArgument.tsx` lists on the assumption that any wrapper was the defect, which
   bought a fragile split-border hack and a layout change **for zero violations**; it was reverted.
   The real defect was only ever the two scorecards, which nested twice — 6 axes × 2 nodes × 2
   pages = exactly the 24 reported.
   Consequence for the fix: the wrapper is *kept*, so the 2-up card grid survives untouched. The
   bar moves inside `<dd>`, absolutely positioned, with `pb-3` reserving what `gap-1.5` + `h-1.5`
   occupied — same height, same rhythm, no visual change.

2. **`link-name` was NOT already fixed.** A probe of the live site returned zero, which was read as
   "PR #137 fixed it". It had not: the probe never loaded a `/pack/` route, and all 4 nodes are
   there. A rule that reports clean on routes that cannot contain the defect is not evidence.

### Contrast: two of these were the design system contradicting itself

`tokens.css` states the failing ratios in its own comments, and two components paired against them:

- `tokens.css:143` — "`--danger` #DC2626 on `--danger-bg` #FEF2F2 measures 4.41:1", under AA.
  `CheckSequence.tsx:94` painted `text-kill` on `bg-kill-bg`, i.e. exactly that. `--kill-strong`
  exists for this case and measures 5.91:1 on the same tint. The *border* stays `--kill`: an edge
  is a UI boundary held to 3:1, not text.
- `sample.tsx`'s `VerdictBadge` used `bg-warning/10 text-warning` — an ad-hoc 10% alpha tint that
  no token declares and nothing had measured. Replaced with the declared pair `bg-warning-bg
  text-warning-strong` (6.84:1); the success branch moves to `bg-success-bg text-success-strong`
  (7.29:1) so the two badges stay one system.

### Still open after this pass

- ~~**F-001** (first product below the fold on mobile) and **F-005** (LCP 2.3–3.8s on four
  routes) are untouched.~~ **Both fixed 2026-08-08** — see the outcome blocks on each finding.
  Two new probes assert them: `scripts/design-audit/measure-fold.mjs` and
  `scripts/design-audit/measure-lcp.mjs`, both exiting non-zero on regression.
- **What remains on F-005:** the 2500ms floor is cleared on every route, but `/` (1304ms) and
  `/kill-log` (1456ms) are still over the 1200ms bar under Lighthouse-mobile throttling.
- **`e2e/discovery.spec.ts` still runs at one viewport in CI.** `playwright.config.ts:18` has
  only `devices['Desktop Chrome']` (1280×720), which is why F-001 lived on a phone for a day
  while a desktop fold test stayed green. The mobile assertion in that file sets its own
  viewport, so it works — but nothing stops the next block from being added above the shelf and
  measured only at 1280 wide.
- **F-003** (`--muted` at 4.63:1 against the self-imposed 7:1 bar), **F-007** to **F-010** are S2/S3
  and unaddressed.
- §5.1's coverage gaps are unchanged: the checkout overlay, component states, `/orders/[token]`,
  `/auth/callback`, `/500`, keyboard, content edges, and throttled LCP remain unaudited.

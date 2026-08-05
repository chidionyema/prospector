# Storefront design critique + direction — 2026-08-05

Measured against the production build (`next build` + `next start -p 3210`, `NEXT_PUBLIC_API_URL=https://api.mumchimp.com`),
not against source. Every number below is a runtime measurement or a `file:line`. Where I have a
judgment and no measurement, it is labelled **JUDGMENT**.

---

## 0. The one-sentence version

The site is *well engineered and under-designed*. The components are individually careful —
the pack buy panel is genuinely good — but there is no system holding them together, so the page
reads as several competent designs stacked rather than one. Three font families, 17 type styles in
the first screen, 8 corner radii and 5 shadows on one page is not a style, it is an absence of one.

And the single most valuable thing the brand owns — "every claim is backed by a source you can
open" — is the thing the design does least with. The product page prints its sources as
**unclickable text**.

---

## 1. The brand promise is not rendered

**Measured.** `GET /pack/8d5e24fbe6c1f5d3`, rendered HTML with `__NEXT_DATA__` stripped:

```
external hrefs: 5   → api.stripe.com, js.stripe.com, own canonical, x.com share, linkedin share
real source links: 0
```

The page instead contains prose like:

> …printable PDFs (source: https://socialstorytemplates.com/). A published coll…
> …each page carrying picture symbols (source: https://www.scribd.com/document/821626746/…)

Plain text. Not anchors. On the same page that says, verbatim:

> All six checks, each verdict, and a clickable source behind every claim.

`/sample` does render 8 real `<a href>` source links, so the capability exists; the pack page just
doesn't use it. This is the same class of bug as the storefront-has-no-markdown-parser trap: the
engine writes a source into a text field and the storefront prints the field literally.

**This is the highest-leverage design fix on the site**, and it is not a "design" fix at all in the
decorative sense. The differentiator is *provable research*. Every rendered source URL should be a
styled, clickable, favicon-bearing citation chip. That single change does more for perceived
quality than any palette work, because it converts the central claim from an assertion into an
artifact the visitor can click. Right now the site makes the claim and then withholds the proof —
which is exactly the posture the whole product exists to attack.

---

## 2. There is no type system

**Measured** on `/` at 1440×900, over every visible leaf text node in the first 900px:

| | |
|---|---|
| font families in the fold | **3** — Hanken Grotesk (25 nodes), Geist Mono (17), Newsreader (3) |
| distinct `font-size`/`font-weight` pairs in the fold | **17** |
| smallest type in the fold | **10px / 400** |

17 type styles in one screen means no scale — each component picked its own size. The tell is
`12.5px/400`, `12px/600`, `12px/700`, `12px/400`, `11px/700`, `10px/700`, `10px/400`: seven
near-identical small styles that a reader cannot distinguish but that guarantee nothing ever
optically aligns.

Note also that `brandV2.test.ts:26` records decision #3 — *"drop the third family (Geist Mono)"* —
and it never landed: Geist Mono is the **second most used family in the fold**. The test that was
supposed to guard it could never fail (`brandV2.test.ts:103-119` documents why). This is a founder
call, not a test fix: dropping it re-types 74 components.

**Direction.** Commit to a 7-step scale and delete everything else:

```
display  56/1.05/-0.02em   serif       hero h1 only
h2       32/1.15/-0.01em   serif
h3       20/1.3            sans 700
body     16/1.6            sans 400
small    14/1.5            sans 400
micro    12/1.4/0.08em     mono upper  labels, eyebrows, data
```

Six styles. Nothing below 12px. The mono family earns its place *only* as the data/evidence voice —
kill gates, source counts, pack IDs, verdicts — which is a real semantic job. If it is used for
decorative eyebrows too, it is noise and decision #3 was right.

---

## 3. The storefront doesn't sell anything above the fold

**Measured** — vertical offset of the first `a[href^="/pack/"]`:

| viewport | first product | in screens |
|---|---|---|
| 1440×900 | y = 1221 | **1.4 screens down** |
| 390×844 | y = 1433 | **1.7 screens down** |

The desktop fold (`shots/desktop-home-fold.png`) contains: an eyebrow, a 5-claim headline, a
paragraph, one CTA, and a kill-log card. The only CTA is **"READ A FREE REPORT, NO EMAIL"**. There
is no buy affordance and no product on the first screen of a shop.

Between the hero and the shelf sits a *"What skills do you bring?"* picker — a personalisation gate
placed before the visitor has seen a single thing to personalise.

The price is stated **three times before any product appears**: eyebrow `£49 EACH`, headline
`£49 a pack`, body `Each £49 pack`. And the headline itself carries five claims in one sentence
("Skip 6 months of research. Validated ideas you can actually ship today. Zero fluff, ready to
build. £49 a pack.").

**Direction.** The fold should be: one claim, the evidence card, and *three real packs*. Trim the
headline to a single claim and let the shelf be the argument. A storefront that shows product in
the fold is not a growth-hack; it is what the visitor came for. Keep "read a free report" as the
secondary — it is a strong offer, just not the *only* one.

**JUDGMENT:** the skills picker belongs *after* the first row of packs, as a refinement
("narrow this down"), not before them as a toll gate.

---

## 4. Three visual languages on one screen

From `shots/desktop-home-fold.png`, within 900px:

1. **Brutalist** — the CTA: flat vermillion, square-ish, hard 4px offset black shadow.
2. **Terminal** — the filter-log card: black, monospace, hairline rules, offset shadow.
3. **Soft product UI** — the nav pill, the rounded status bar, `rounded-full` chips.

**Measured** on the same page, over all visible elements:

| | |
|---|---|
| distinct `border-radius` values | **8** (`full`, 16, 12, 8, 6, 5, 4, and a mixed `0 4px 4px 0`) |
| distinct `box-shadow` values | **5** |

Brutalist and terminal are the *same* idea and they work together — that pairing is the brand.
The soft-product-UI layer is the intruder. It is what makes the page read as "startup template
with a custom hero" rather than as a research instrument.

**Direction.** Pick two radii and two shadows and enforce them:

```
--radius-sharp: 2px    /* everything structural: cards, buttons, inputs, the shelf */
--radius-pill:  999px  /* only genuinely pill-shaped things: filter chips, badges */
--shadow-offset: 3px 3px 0 var(--text)   /* the brand shadow, used sparingly */
--shadow-lift:   0 1px 2px rgb(0 0 0 / .06)  /* hover only */
```

That is the deferred consolidation spec — but it is not cosmetic tidying. Eight radii is *why*
nothing on the page looks like it comes from the same house.

---

## 5. Brand colour is spent on the wrong pixels

In the fold, the most saturated element after the CTA is a **decorative orange progress bar**
labelled "1 of 3" — a carousel position indicator. Vermillion is the brand's entire visual
signature and 1440px of it goes to a scroll dot.

Meanwhile on the pack page (`shots/desktop-pack-fold.png`) the same vermillion is spent on an
eyebrow reading **"SURVIVED SIX CHECKS"** — which duplicates the green pill **"Survived 6 checks"**
sitting 400px to its right. Same fact, two colours, two cases, two shapes, one fold.

**Direction.** One rule: **vermillion means "you can act here."** Buy buttons and primary CTAs
only. Evidence and verdict states get the green/red pair (already defined). Structure gets ink and
hairlines. Nothing decorative is ever vermillion. This is the cheapest change with the largest
effect on perceived intent — right now the eye cannot tell what the orange is *for*.

---

## 6. The pack page buries the product

From `shots/desktop-pack-fold.png` and runtime measurement:

- The title is rendered **7 times** in the DOM on one page.
- Three of those are in the fold: truncated breadcrumb → cover caption → 60px serif `h1`.
- A **~550px empty navy rectangle** occupies the prime visual slot. It carries a pack ID, a market
  tag, a ghost icon, and the title again. It communicates nothing the buyer does not already have.
- **Share buttons (link / X / LinkedIn) sit at y≈247** — above the product, before the visitor
  knows what it is. Nobody shares something they haven't read.
- The `h1` is `text-4xl md:text-5xl` (`pack/[id].tsx:398`) applied to a 100-character title, so it
  consumes ~400px and is *still not finished* at the fold boundary.

The buy panel on the right is the best-designed component on the site — price, guarantee, CTA,
secondary action, three reassurance lines, honest disclaimer. It should be the model for
everything else.

**Direction.** Replace the empty cover with **a real page of the dossier** — a rendered excerpt of
the QA report showing a check, its verdict, and its clickable source. The pack page's job is to
prove the pack is real; a decorative gradient does the opposite. Demote the title to one h1 at
`text-3xl`, kill the cover caption and the eyebrow duplicate, and move share to the footer of the
article.

---

## 7. The shelf has no shape

**Measured:** `/` is **21,717px tall on desktop (24 screens)** and **49,558px on mobile (59
screens)**. 73% of that (15,875px) is the catalog section — 61 cards, all rendered, no pagination,
no lazy loading, no "load more".

I want to be careful here: a shelf *should* dominate a storefront, so height alone is not the
defect. The defect is that 61 undifferentiated cards in one flat scroll give the buyer no way to
form a shortlist. There is no visual hierarchy between pack #1 and pack #61.

**Direction.** Rows with meaning instead of one infinite grid: *"Newest survivors"* (3), *"Cleared
all six checks"* (N), *"Most sources"* (N), then the full grid behind a "browse all 61". The facet
bar already exists; it is doing filtering work but no *editorial* work.

---

## 8. Fixed today (was shipping)

Both found by runtime probe, both now fixed and covered by non-vacuous tests:

1. **The home page rendered two different live counts.** `index.tsx:337` read `stats.listed` from
   the live `/catalog` (61); `TrustGuaranteesRow.tsx:28` read `kill-log-totals.json`, frozen at
   build time (`"shown": 60`). The page shipped "61 live now" and "60 live now" on one scroll, and
   the gap widened with every publish-without-redeploy. Fixed by passing the live figure as a prop
   (`TrustGuaranteesRow.tsx:20`, `index.tsx:1032`); snapshot retained only as fallback. Guarded by
   `nOneTrustRow.test.ts` — verified to fail on the pre-fix source.
2. **The kill-log card's rows were centre-aligned on mobile.** `text-center` on the mobile hero
   wrapper inherits into the card, so the three pack names landed at x=125/83/100 inside a list
   whose legibility depends on a shared left edge. Fixed by making the card set its own alignment
   (`LiveKillCard.tsx:105`). Verified: all three now at x=58, `text-align: left`.

---

## 9. Priority order

Ranked by (effect on perceived quality) ÷ (cost). Items 1–3 are the "100x" ones; the rest is
tidying that only pays off once those land.

| # | Change | Why it is first |
|---|---|---|
| 1 | Render source URLs as clickable citation chips, everywhere | Converts the central claim from assertion to artifact. The differentiator is currently invisible. |
| 2 | One colour rule: vermillion = actionable, only | Free. Makes intent legible instantly. |
| 3 | Product in the fold; headline down to one claim | It is a shop. |
| 4 | 6-step type scale, delete the other 11 | The single biggest source of "template" feel |
| 5 | 2 radii, 2 shadows; drop the soft-product-UI language | Makes it one house |
| 6 | Pack page: dossier excerpt replaces the empty cover; one title, not three | The money page should prove, not decorate |
| 7 | Editorial rows on the shelf; paginate the tail | 61 flat cards is a database, not a shop |
| 8 | Decide Geist Mono: data-voice only, or drop it (74 components) | Founder call — brand-v2 decision #3 never landed |

## 10. Open, not fixed — needs a decision

**The pack page shows two prices in two currencies.** With `Fly-Client-Country: US` the headline
renders `$62.23` while the CTA one line below renders `Unlock this pack · £49`
(`PackBuyButton.tsx:103` uses `formatPrice`, which is GBP-only). The note between them reads
`£49 at today's rate` — but £49 is the *source* figure, not the rate-derived one, so the wording
describes the wrong number.

The buyer is genuinely charged in GBP, so this is a money-display decision, not a bug with an
obvious fix: either the local currency is the anchor and the CTA follows it (with the GBP charge
disclosed), or GBP is the anchor and the conversion is an explicitly-approximate footnote. I have
not chosen unilaterally.

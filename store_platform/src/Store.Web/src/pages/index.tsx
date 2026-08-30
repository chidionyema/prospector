import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
// `buttonClasses` is back (2026-08-15, brief item 2: ONE button system). The spotlight's "View
// pack" was hand-rolled -- `bg-primary px-4 py-2.5` with its own radius and type -- so it was a
// filled primary that shared no code with the primary, i.e. exactly the drift `buttonClasses`
// exists to stop. It is a `<span>` because the whole card is already one `<a>`.
import { Button, Icon, Dropdown, buttonClasses, chipClasses, textLinkClass, PriceText } from '@/components/ui';
import { cx } from '@/components/ui/cx';
// No `CtaBand` here any more: this page's closing band is hand-composed (argument left, purchase
// terms right) rather than the shared title/lead/two-buttons shape. See the note above it.
import { SectionBand, Section } from '@/components/marketing/blocks';
// The home page OWNS the pack manifest (§5.3 of docs/SITE_SPEC_PROGRAM.md, founder-confirmed
// 2026-08-07). `PACK_DOCUMENTS` for the count beside the prices, `PackContentsSection` for the
// manifest itself. /pricing keeps bare filenames only (`pricing.tsx:123`), which is the same
// section's other half of the ownership split, not a duplicate.
import { PACK_DOCUMENTS, PackContentsSection } from '@/components/marketing/PackContents';
// `EvidenceRecordPanel` is no longer imported here. `PackSpecimen` took its render site and its
// job -- it shows the same failed check as a typeset PAGE rather than as a web table, which is the
// claim that component's own eyebrow ("A real page from a real pack") was already making. The file
// is left in the tree, unused, rather than deleted in the same commit that replaces it.
import { PackSpecimen } from '@/components/marketing/PackSpecimen';
// `LiveKillCard` is no longer imported here: its render site below the shelf was removed on
// 2026-08-14 (see the record where it stood). The component is untouched and still used elsewhere.
import { HeroEvidenceStrip } from '@/components/marketing/HeroEvidenceStrip';
import HeroRatio from '@/components/marketing/HeroRatio';
import TrustGuaranteesRow from '@/components/marketing/TrustGuaranteesRow';
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, FilterFab, FilterSheet, StepFlow } from '@/components/discovery/FacetBar';
import { PackCardHeader } from '@/components/ui/PackCardHeader';
/* THE SHELF'S TWO CARD FORMATS NOW LIVE IN ONE PLACE (2026-08-15, founder's mobile brief).
   `PackRow` is the dense format -- it was this file's `PackCard weight="row"` branch, moved out
   verbatim so the catalogue, the regional group, search results and `SimilarPacks` all render the
   SAME row instead of four near-copies. `PackSpotlight` below is the other and only other format.
   `PackFigure` moved with the row because both formats draw it. */
import { PackRow, PackRowList, PackFigure, PackTileGrid } from '@/components/discovery/PackRow';
import { KillGateBand, SourcesBand } from '@/components/marketing/EvidenceBands';
import { EvidenceBar } from '@/components/ui/EvidenceBar';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
// Last-known-good catalogue. A failed fetch must never render as "nothing is for sale".
import { freshCatalog, lastKnownCatalog, rememberCatalog } from '@/lib/catalogCache';
import { formatPriceForMarket, currencyForCountry, type Currency } from '@/lib/fx';
import { repairTruncation } from '@/lib/copy';
import {
  startScrollDepthTracking,
  track,
  trackFilterChange,
  trackFilterZeroResults,
} from '@/lib/analytics';
import { useCardImpressions } from '@/lib/useCardImpressions';
import { priceRange, formatGbp } from '@/lib/priceRange';
// `type Category` was imported here for `PackCoverArt`'s `category` prop and went with it
// (2026-08-14). The card reads the object off `categoryFor(pack)` locally and never passes it.
import { allCategories, categoryFor } from '@/lib/category';
// The card's lead figure. The priority order, and why the modelled MONEY figure is deliberately
// not in it, are written out in the module -- this is the only import site that matters.
import { packLeadStat, type PackLeadStat } from '@/lib/packStat';
import type { Sector } from '@/lib/facets';
import { graph, itemListNode } from '@/lib/seo/schema';
import {
  cardHeading,
  cardLine,
  decodeDiscoveryState,
  EMPTY_DISCOVERY_STATE,

  encodeDiscoveryState,
  facetCounts,
  filterPacks,
  isFiltered,
  nearMisses,
  similarPacks,

  type DiscoveryState,

} from '@/lib/discovery';
import { DEFAULT_MARKET, groupByMarket, packMarket, resolveMarket } from '@/lib/market';
import { KIND_NOUN } from '@/lib/facets';
import { useCopyVariant } from '@/lib/useCopyVariant';
import { RESEARCH_STATS, killsSummary } from '@/lib/stats';
import { resolveFlags, type Flags } from '@/lib/flags';
import { FilterBar } from '@/components/discovery/FilterBar';
import { SITE_COPY } from '@/lib/siteCopy';

interface HomeProps {
  packs: Pack[];
  stats: CatalogStats | null;
  /** Resolved on the server, once, per request. See `lib/flags.ts` for why not `NEXT_PUBLIC_*`. */
  flags: Flags;
  /** Discovery state decoded from the query string on the server, so a shared filtered link
   *  renders filtered in the HTML rather than flashing the whole catalogue first. */
  initialState: DiscoveryState;
  /** The visitor's resolved market (`?market=` override -> `market` cookie -> `Fly-Client-Country`
   *  -> "uk"; see `resolveMarket` in `lib/market.ts`). Boosts that market's packs to the top of
   *  the grid, every other market is still fully shown, just below. */
  market: string;
  /** The currency to render prices in. Decoupled from market: a French visitor sees UK packs
   *  first (no EU market yet) but the price in EUR. Computed from the country header on the
   *  server so the rendered HTML is correct on first paint. */
  currency: Currency;
  /** N2: similar packs to the visitor's most recently viewed pack. Empty when
   *  the visitor has not viewed any pack yet (or the anchor pack is gone),
   *  in which case `RecentlyViewed` is the fallback. (It used to fall back to a
   *  "Most sources" row; that row was deleted -- see the header comment.) */
  personalised: Pack[];
  /** Pack ids from the `recentlyViewed` cookie, most-recent first. Two jobs, both server-rendered
   *  so neither flashes: the "Recently viewed" row when there is nothing personalised to show, and
   *  the "Viewed" marker on any card the buyer has already opened. It used to be read from
   *  `localStorage` inside `RecentlyViewed`, which could never work -- the pack page writes a
   *  COOKIE (`pages/pack/[id].tsx:1071`, asserted by `__tests__/nTwoPersonalised.test.ts`), so
   *  that key was never set and the fallback row has never once rendered. */
  viewedIds: string[];
  /** True only when the catalogue could not be reached AND this server has never held one, so
   *  `packs` is empty because of OUR outage rather than because nothing is for sale. The shelf
   *  branches on it: an empty catalogue we actually fetched still says "No packs are live right
   *  now", which is a true statement about the business; an empty one we failed to fetch must
   *  not, and used to (see `lib/catalogCache.ts`). */
  catalogUnavailable: boolean;
}

/*
 * `TrustPill` was DELETED with its only call site (2026-08-06, second pass). It rendered an icon
 * and a factual line, and the row it built restated `TrustGuaranteesRow` exactly. Kept as a note
 * rather than a component: the next person who wants a reassurance row on this page should add it
 * to that row, which is the one place the purchase terms are allowed to be stated.
 */

/*
 * `CategoryPill`, `Cover` and `ProofLine` were deleted on 2026-08-06 with the gradient card.
 * `Cover` painted the sector gradient the new card does not have; `CategoryPill` was an uppercase
 * bold pill replaced by the 8px `cat.dot` plus a plain sector label; `ProofLine` is now four
 * inline mono spans in the card body. Nothing else imported them.
 */

/**
 * The product card (brand v3, 2026-08-06).
 *
 * What was deleted, and why each one was costing a sale:
 *
 *  - **The gradient cover.** A saturated 135deg tile with the title in white serif over it, then
 *    the same title repeated in the body. Sixty-one of them made the shelf read as "colourful
 *    tiles", not "sixty-one researched dossiers", and the title on the cover was the least
 *    legible text on the page.
 *  - **The per-card buy button.** Sixty-one identical CTAs on one screen is banner blindness: no
 *    card can win, and the grid is a browsing surface, not a checkout. The price is now a quiet
 *    scannable element instead of being buried inside a CTA label ("Unlock this pack · £49"),
 *    which made comparing prices down a column impossible.
 *    HYPOTHESIS -- this is the one change here that could move revenue the wrong way. The check
 *    is checkout-starts per catalogue session over two weeks against the pre-change baseline; the
 *    rollback is this one component.
 *  - **The "TRENDING" badge.** It fired on `sourceCount >= 30`, which is a property of our
 *    research effort, not of demand. It told the buyer a popularity story we had no data for.
 *  - **The six-dash "verification bar".** Six identical full bars on every card, always. It
 *    encoded nothing. Its replacement, a hardcoded `6/6 checks` token in the evidence row, was
 *    no better and is gone too: the check count is lane-dependent (measured on the live API
 *    2026-08-06, only 40 of 61 listed packs are 6/6; 14 are 8/8, 3 are 7/8, 3 are 9/9, 1 is 6/8)
 *    and `GET /catalog` carries no check field at all, so a card cannot state one. It states
 *    what the list payload actually has: the source count and the verification date.
 *  - **The 3px orange left border, the icon-in-a-circle, the "or view details" line, and the
 *    per-card FX note.** The FX disclosure moves to the point of purchase (detail + checkout);
 *    printing exchange-rate legalese under every tile taxed browsing with contract copy.
 *
 * The category dot is the only colour on the card.
 */
/**
 * A product card.
 *
 * Rewritten 2026-08-06 (second pass) against a rendered-page critique the founder accepted in
 * full. What it used to be: a hairline plate whose top row carried the sector on the left and
 * `UK № FCF4A5` on the right, then title, then a mono evidence line reading `29 sources ·
 * Verified 4 days ago`, then price and a text "View pack".
 *
 * Four things were wrong with that, and each maps to a change below.
 *
 * 1. THE CARD HAD NO PICTURE, AND NEITHER DID ANYTHING ELSE. The rendered page carried zero
 *    images across 63 products. There is no photography for a business blueprint, so the cover is
 *    generated: the sector's hue at 10%, its icon at 40px, and a deterministic offset so two
 *    adjacent cards in the same sector do not look like a repeat. This is not decoration for its
 *    own sake -- it is the only thing on the shelf that lets you scan by shape instead of by
 *    reading, and reading 63 titles is what made the page feel like documentation.
 *    (`lib/cover.ts` + `ui/CoverArt.tsx` did something like this and were deleted earlier the
 *    same day as unreferenced. They were unreferenced because the card had stopped using them,
 *    not because a shelf does not need covers.)
 * 2. `№ FCF4A5` IS DEBUG OUTPUT. A truncated uppercase hash of the pack id, printed on a product,
 *    in mono, at the same size as the sector. It identifies nothing a buyer can act on.
 * 3. `29 sources · Verified 4 days ago` IS A CLAIM ABOUT US, NOT A BENEFIT TO THEM. "Is 29 good?"
 *    has no answer on a card, and a freshness stamp on a research product reads as a shelf life --
 *    it makes the thing look like it expires. Both move to the pack page, where there is room to
 *    say what they mean.
 * 4. "View pack" WAS TEXT. On a shelf where the entire card is already a link, the affordance
 *    that converts is a button with a filled background; a grey caption next to a price is the
 *    weakest possible terminal element on the most important row.
 *
 * The sector name renders whenever `cat.tagged`, and NOTHING renders when it is false -- see the
 * rule in `lib/category.ts`: hue is decoration, the label identifies.
 */
/**
 * ── EDITORIAL WEIGHT (2026-08-07) ────────────────────────────────────────────────────────────
 *
 * THE MEASUREMENT THAT FORCED THIS. On the served homepage, all 57 pack anchors rendered with a
 * byte-identical class string: `group flex flex-col overflow-hidden rounded-md border
 * border-border bg-surface ...`. One card treatment, 57 times, in a uniform `lg:grid-cols-3`.
 * A grid where every cell has the same weight gives the eye nothing to land on, so the reader
 * either scans all 57 titles or none of them -- and 57 is well past the number anyone reads.
 * Every other fix on this page is downstream of that: the type scale, the marks and the evidence
 * bar all need somewhere to be LOUD, and a uniform grid has no loud position.
 *
 * WEIGHT FOLLOWS PRICE, and that is a factual mapping rather than a design flourish. The price
 * ladder is set by how big the opportunity is (`config.yaml listing.pricing`, rungs 1900-19900),
 * so price already encodes "how much is at stake here". Rendering a £149 pack at six times the
 * area of a £29 one makes the shelf's layout agree with the shelf's own pricing argument. The
 * thresholds sit ON ladder rungs, not between them, so a pack cannot drift weight without an
 * actual repricing.
 *
 * Measured distribution over the live shelf (2026-08-07): £149 x5, £99 x1, £79 x7, £49 x40,
 * £39 x3, £29 x16. So `lead` selects a handful, `mid` a handful, and the long tail becomes rows
 * -- which is also why the tail is rows and not cards. 44 more cards is 44 more things claiming
 * to be a poster; 44 rows is a list you can actually run your eye down, and it is roughly a third
 * of the page height.
 */
export type PackWeight = 'spotlight' | 'row';

/**
 * Price in pence -> weight tier.
 *
 * `pricePence` is optional on `Pack`, and the fallback is `row` rather than a guess parsed out of
 * the formatted `price` string: a missing price is a fact we do not have, and promoting an
 * unknown to the loudest position on the shelf is exactly the kind of invented emphasis this site
 * is not allowed to make.
 */
export function packWeight(pack: Pack): PackWeight {
  const pence = pack.pricePence ?? 0;
  if (pence >= 9900) return 'spotlight'; // £99 and £149 rungs
  return 'row';
}

/**
 * `cardLine` MOVED to `lib/discovery.ts` (2026-08-15), unchanged, and is re-exported here so the
 * import path in `lib/__tests__/cardLine.test.ts` still resolves. It moved because the shelf row
 * is now a shared component (`components/discovery/PackRow`) and a component cannot import a
 * helper from the page that renders it without a cycle. Its full argument -- the three boundaries,
 * the 30-word cap, the sixteen measured dangling tails -- travelled with it.
 */
export { cardLine };


/* THE SPOTLIGHT -- one of the site's two card formats, and the only one that is a card.
   It was `PackCard weight="lead"`. The `weight` prop is gone with the tiers it selected: `row`
   moved to `components/discovery/PackRow` and `mid` was DELETED outright. The mid tier's own code
   carried the evidence against it -- an odd count left "a 590px card at x=120 with 610px of empty
   white beside it, directly under a full-bleed lead card", patched by promoting the odd card to
   `lead`, which is a tier admitting it cannot hold its own band. Three formats in one vertical run
   is what the founder's brief calls the ransom note. Use this for a SINGLE pack presented alone;
   everything in a list is a `PackRow`. */
function PackSpotlight({
  pack,
  currency,
  viewerMarket,
  viewed = false,
}: {
  pack: Pack;
  currency: Currency;
  /* The market this reader is browsing. Used ONLY to suppress the card's market flag when it
     would be true of every card on screen. It used to live on `PackCoverArt`'s plate; that plate
     is gone (see the record where it was declared) and the flag now renders on the card body's
     meta row, on the same condition. Optional so a caller with no market context (the hero's
     featured slot renders before any grouping) simply gets the flag. */
  viewerMarket?: string;
  /* True when this pack is in the reader's `recentlyViewed` cookie. A returning buyer scanning
     63 near-identical cards has no way to tell which ones they already opened, so the second
     visit is the first visit again. Server-rendered from the cookie, so it is in the first paint
     and never flashes in after hydration. */
  viewed?: boolean;
}) {
  const cat = categoryFor(pack);
  /* The card's lead figure, and the card's only visual. Computed once here and rendered by all
     three variants, so a pack cannot lead with one number on the shelf and another in the
     "recently viewed" row. `null` only when the pack carries no number at all, which no live
     pack does -- the ladder's floor is the source count and that is populated 62 of 62. */
  const stat = packLeadStat(pack);
  /* The evidence bar drops its numeral when the lead figure IS the source count: the bar exists
     to make two cards comparable at a glance, the numeral existed because "a chart without its
     figure is decoration" (EvidenceBar's own note), and the figure is now set six times larger a
     few lines away. Printing "34" twice on one card is the duplication the cover removal was
     about. When the lead is the modelled multiple the bar keeps its numeral, because then the
     two are different facts. */
  const evidenceLabel = stat?.kind !== 'sources';
  const { heading, sub } = cardHeading(pack);
  // `repairTruncation` repairs the publish path's character-150 cut; `cardLine` then caps at a
  // word boundary so the card never shows a clause that stops mid-thought. See `cardLine`.
  // NO WORD BUDGET (2026-08-18, fix prompt D3a: "Remove every character-budget cut in the
  // data layer"). `Infinity` leaves `cardLine`'s first-sentence normalisation and removes its
  // cap, so nothing is ever cut mid-clause. Clamping is CSS only, in `.d`.
  const line = cardLine(repairTruncation(pack.oneLine) || sub, Infinity);
  const price = formatPriceForMarket(pack.price, currency);
  const focusRing =
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus';


  /* THE DRAWING'S FEATURED ARTICLE (`mockups/index.html` section 7, `<article class="featured">`).
     It was a Tailwind card that re-stated the drawing's numbers by hand, and it shared none of
     the drawing's class names, so the structure check in `scripts/sections.mjs` reported
     `featured`, `stat`, `big`, `spark-row`, `price-lg` and `cur` as never emitted by this page.
     That is what "the section is completely different" looks like from a script.

     The drawing's order is: sector, title, the one-line claim, the modelled multiple at 44px,
     the evidence run, then a rule and the money row. Every number below is the same one the card
     already computed; only the markup changed.

     IT IS AN ARTICLE, NOT A WHOLE-CARD LINK, because the drawing puts the action in one filled
     button in the foot. `trackCardClick` moves onto that button, so the click analytics keep
     recording the same event from the same card. */
  return (
    <article className="featured w-full">
      {cat.tagged && <span className="eyebrow">{cat.label.toUpperCase()}</span>}
      <h3>{heading}</h3>
      {line && <p className="d">{line}</p>}
      {stat && <PackFigure stat={stat} weight="spotlight" />}
      {/* The drawing's `.spark` is a decorative row of bars. Ours is `EvidenceBar`, which draws
          the same shape from the pack's REAL cited-source count and prints that count beside it,
          so the bars mean something a buyer can check. It IS the `.spark-row` now -- the wrapper
          that used to sit here made an element the drawing does not have. */}
      <EvidenceBar count={pack.sourceCount} label={evidenceLabel} />
      <div className="foot">
        {/* One element, not two. `.price-lg` (mumchimp.css:340) sets the size, weight and
            tracking; a nested `PriceText` span inside it added a second box for no rule. */}
        <PriceText className="price-lg num">{price}</PriceText>
        <Link
          href={`/pack/${pack.id}`}
          className={cx('btn', focusRing)}
        >
          View pack
          <Icon name="arrowRight" size={16} />
        </Link>
      </div>
    </article>
  );

}

/*
 * `PackCoverArt` -- THE GENERATED COVER -- IS DELETED (2026-08-14). Its call site was the first
 * child of the mid card; see the note there for where its four facts now render.
 *
 * WHAT IT WAS, so nobody rebuilds it by accident: a 112px `h-28 border-b border-ins-line bg-ins-bg`
 * plate at the top of every pack card, carrying a bottom-left radial lift and one fact per corner
 * -- the sector in mono top-left, "For <market> rules" top-right (only when the pack's market
 * differed from the reader's), the cited-source run as an `EvidenceBar tone="instrument" size="lg"`
 * bottom-left, and a "Viewed" chip bottom-right.
 *
 * WHY IT WENT. Founder verdict from a screenshot of the deployed shelf: at 112px it takes roughly
 * 60% of a card and reads as the placeholder where a product image failed to load. Every argument
 * the old docblock made for it was an argument about what to put ON a cover, and none of them
 * answered the prior question of whether a shop that has no photography should be drawing a frame
 * for photography it does not have. It is out until there is real imagery to put in it. The
 * objection that the plate was the only thing encoding the source count was raised and overruled,
 * and the removal is faithful to the objection rather than to the plate: nothing the plate stated
 * was dropped, all four facts moved into the card body in the card's normal ink.
 *
 * THE THREE DECISIONS THE OLD DOCBLOCK RECORDED, KEPT, because each was earned and each still
 * binds whatever renders those facts:
 *
 *  - DETERMINISM. A card's appearance had to be a function of `pack.id` and nothing else -- a
 *    cover that changes on reload is worse than no cover, because a buyer returning to the shelf
 *    cannot find the card they were looking at. `Math.random()` stayed banned from card rendering,
 *    and `__tests__/usTwoPackArt.test.ts` asserts it. That constraint is now trivially satisfied:
 *    the card draws no generated artwork at all, only facts read off the pack.
 *  - THE MARKET FLAG IS CONDITIONAL, AND THE CONDITION IS THE POINT. "Which country's rules is
 *    this written for" is the one fact on a card that can make a pack useless to a reader, but a
 *    UK reader on the UK shelf got "For UK rules" on all 63 cards -- a label true of every item on
 *    a shelf tells you nothing about any item on it, and it competed for the eye with the sector,
 *    which is the fact that actually distinguishes one card from the next. It still renders only
 *    on `pack.market !== viewerMarket`, which is what makes it the loudest thing on the card in
 *    the "Built for US rules" group, where a reader can buy the wrong country's rules by accident.
 *  - THE UNTAGGED PACKS NEED NO FALLBACK. 9 of the 63 live packs carry no sector. The pastel
 *    cover before the plate needed `COVER_WEAVE` (a 3%-black diagonal hairline, deleted 2026-08-14)
 *    so those nine did not render as one flat empty rectangle; the plate needed nothing because it
 *    was identical on all 63. The card body needs nothing either, for the stronger reason: an
 *    absent sector is now an absent line of mono in a meta row, which reads as "this pack has no
 *    sector", not as a region that failed to load. The rule `COVER_WEAVE` existed to demonstrate
 *    outlives it -- Tailwind scans source TEXT, so any arbitrary-value class must be written as a
 *    full literal and never built by interpolation.
 *
 * TWO TESTS PIN THE COMPONENT BY NAME AND FAIL ON THIS REMOVAL, deliberately and correctly, since
 * they pin a design that has been withdrawn: `src/__tests__/usTwoPackArt.test.ts` (requires
 * `<PackCoverArt ... category={cat}`) and `src/lib/__tests__/categoryScale.test.ts` (slices the
 * source between `function PackCoverArt` and `function SectorChips`). The rule the latter actually
 * defends -- "a marker with no name beside it is decoration pretending to be information" -- is
 * upheld by the card that replaced it, which draws no glyph on either branch and prints the sector
 * only as its own label. Both assertions need re-pointing at the card body's meta row.
 */

/**
 * The sector chips, directly above the grid.
 *
 * The shelf already prints a sector on every card and already holds a `sector` facet in the
 * discovery state, and until now the only way to reach it was `StepFlow`'s "Advanced filters"
 * disclosure -- which renders AFTER the last card, i.e. past 63 products. So the one filter the
 * buyer can see on screen was the one filter they could not use, and a 63-item catalogue was a
 * scroll-and-hope surface.
 *
 * Counts come from `facetCounts`, not from a tally of `pack.sector`. That matters as soon as any
 * OTHER filter is on: `facetCounts` re-runs the whole state with the sector constraint removed, so
 * each number answers "what do I get if I click this" rather than "how many of these exist" -- and
 * a chip reading 12 that yields 3 because a query is also active is a number the catalogue made
 * up. A sector that would yield nothing is not offered at all (the same rule `FacetBar` states: a
 * filter whose every option returns nothing is a dead control that makes the shelf look broken).
 *
 * Shape comes from `chipClasses()` and nowhere else -- `__tests__/storefrontDesignContract.test.ts`
 * fails any file that reproduces `h-8` + `rounded-full` itself, which is how the same chip once
 * shipped three different ways.
 */
function SectorChips({
  packs,
  state,
  onChange,
}: {
  packs: Pack[];
  state: DiscoveryState;
  onChange: (next: DiscoveryState) => void;
}) {
  const counts = React.useMemo(() => facetCounts(packs, state, 'sector'), [packs, state]);
  /* "All packs" is the same question with the sector cleared, so it is the same computation --
     never `packs.length`, which would print 63 beside chips summing to 21 whenever a query is on. */
  const allCount = React.useMemo(
    () => filterPacks(packs, { ...state, sector: null }).length,
    [packs, state],
  );

  /* A DEAD SECTOR IS SHOWN AND DISABLED, not hidden (MASTER-BRIEF section 9; the same rule
     `FacetBar` now follows). Hiding it removes two facts at once: that the sector exists, and that
     the filters already on screen are what emptied it. A buyer who narrowed to UK and watched four
     chips vanish cannot tell a sector we have never carried from one their own query excluded, so
     the rail silently rewrites itself and the shelf reads as a smaller catalogue than it is.
     Disabled says both: the sector is real, and nothing in it survives the current filters. */
  const offered = allCategories();
  if (offered.every((cat) => (counts[cat.key] ?? 0) === 0)) return null;

  return (
    /* Bleeds to the viewport edge and scrolls on a phone rather than wrapping to four rows above
       the first product -- the fold budget this page's e2e test guards. From `sm` it wraps
       normally, where there is width for it. */
    <div
      data-facet-control="sector"
      /* The right-edge fade is the SCROLL AFFORDANCE, and it only exists below `sm`, where the
         row is a single scrolling line. Without it the eleventh chip is simply sliced by the
         viewport edge mid-word, which is the same silhouette as a layout bug -- a phone reader
         has no scrollbar to tell them the difference, so the row reads as broken rather than as
         "there is more this way". `sm:` and up the chips wrap and there is nothing to fade. */
      className={cx(
        '-mx-4 mb-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:overflow-visible sm:px-0 sm:pb-0',
        /* SCROLL-SNAP, below `sm` only (founder review, 2026-08-15). Measured on the live rail at
           390: `scroll-snap-type: none` on the scroller and `scroll-snap-align: none` on all
           eleven chips, so no scroll position was ever visually resolved -- the row came to rest
           wherever momentum left it, which is how a reader ends up looking at "…efits claims" on
           the left and half a chip on the right. The mask above was doing the whole job of
           explaining that state, and a fade can only say "there is more"; it cannot stop a
           resting position from slicing two labels at once.

           `scroll-px-4` matches the `px-4` gutter this scroller already carries, so a snapped
           chip lands ON the gutter rather than flush against the clipped edge -- without it
           `snap-start` would align each chip to the padding box and undo the inset. `sm:snap-none`
           because from `sm` up the chips wrap and there is nothing to scroll. */
        'snap-x snap-mandatory scroll-px-4 sm:snap-none sm:scroll-px-0',
        '[mask-image:linear-gradient(to_right,transparent_0,black_1rem,black_calc(100%-2.5rem),transparent_100%)]',
        'sm:[mask-image:none]',
      )}
    >
      <div className="flex w-max gap-1.5 sm:w-auto sm:flex-wrap">
        <button
          type="button"
          aria-pressed={state.sector === null}
          onClick={() => onChange({ ...state, sector: null })}
          className={chipClasses({
            selected: state.sector === null,
            className: 'snap-start gap-1.5 whitespace-nowrap',
          })}
        >
          All packs
          <span className={cx('text-caption tabular-nums', state.sector === null ? 'text-white/70' : 'text-subtle')}>
            {allCount}
          </span>
        </button>
        {offered.map((cat) => {
          const active = state.sector === cat.key;
          const dead = (counts[cat.key] ?? 0) === 0 && !active;
          return (
            <button
              key={cat.key}
              type="button"
              aria-pressed={active}
              disabled={dead}
              onClick={() => onChange({ ...state, sector: active ? null : (cat.key as Sector) })}
              className={chipClasses({
                selected: active,
                className: cx(
                  'snap-start gap-1.5 whitespace-nowrap',
                  dead && 'cursor-not-allowed opacity-45',
                ),
              })}
            >
              {/* THE GLYPH IS NEUTRAL (founder review, 2026-08-15). It used to take `cat.ink`, on
                  the argument recorded here before -- "the hue is the card's hue, so the chip and
                  the pill on the card it filters to are visibly the same object". That argument
                  is sound and the rail is where it stopped paying: eleven chips in one scrolling
                  line put every sector hue on screen at once, so instead of one chip matching one
                  card, the reader gets the entire category scale as a stripe of unexplained
                  colour. Measured on the live rail: mustard rgb(122,74,11) beside magenta
                  rgb(157,23,77) beside violet rgb(109,40,217) -- the founder read it as
                  off-palette, and as the per-category colouring that was deliberately taken OFF
                  the catalogue cards coming back in through the filter bar.

                  The hue still lives on the card's own sector tag, where there is exactly one of
                  it and a label beside it. Here the glyph is a wayfinding mark, not a claim about
                  which sector this is -- the text next to it says that -- so it takes the same
                  `--subtle` as the count on its other side. */}
              <Icon name={cat.icon} size={12} className={active ? undefined : 'text-subtle'} />
              {cat.label}
              <span className={cx('text-caption tabular-nums', active ? 'text-white/70' : 'text-subtle')}>
                {counts[cat.key] ?? 0}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/*
 * `SpotlightCard` was DELETED (brand v3, 2026-08-06).
 *
 * It rendered the newest pack as a full-width horizontal slab with a 3px hard offset shadow, a
 * "Latest to survive" pill, its own price treatment and its own buy button -- a second product
 * card with a second set of rules, sitting directly above the grid of the first kind. The stated
 * reason was "so the grid is not eleven identical blocks", but a grid of consistent cards is the
 * point of a shelf: it is what lets a buyer compare. `sort=Newest` is the default, so the same
 * pack is already the first card in the grid; the slab was showing it twice.
 *
 * The "Most sources" editorial row went with it, for the same reason plus a truthfulness one:
 * ranking by how many sources WE happened to gather is a claim about our research effort dressed
 * up as a recommendation to the buyer.
 */

/*
 * `Heartbeat` was DELETED. It was a bordered pill reading "Live database • Last intelligence
 * added 3 days ago • 61 live now • 1,080 killed, 129 survived" -- four separate facts, in one
 * capsule, above a toolbar that then stated the count again. The freshness and the count now sit
 * in the shelf toolbar as one mono caption (`61 packs · updated 3d ago`), and the killed/survived
 * pair is in the filter-log card, where it is evidence rather than chrome.
 */

/**
 * The last few packs the buyer viewed. Renders nothing on a first visit.
 *
 * Reads the ids handed down from `getServerSideProps`, NOT `localStorage`. The previous version
 * called `localStorage.getItem('mumchimp.recentlyViewed')`, and nothing on the site has ever
 * written that key: the pack page sets a `recentlyViewed` COOKIE
 * (`pages/pack/[id].tsx:1071`, and `__tests__/nTwoPersonalised.test.ts` asserts it is a cookie and
 * not localStorage). So this row was dead code -- the "empty state" the reader met on a second
 * visit was not a design decision, it was a component reading a key that does not exist. Off the
 * cookie it is also in the server HTML, so it does not pop in after hydration.
 *
 * It renders full `PackCard`s. It used to render one-line text rows with an arrow glyph, i.e. the
 * packs we had the strongest reason to re-show got the weakest treatment on the page: no price,
 * no picture, no CTA, and a tap target a third the height of a card.
 */
function RecentlyViewed({
  packs,
  viewedIds,
  currency,
  market,
}: {
  packs: Pack[];
  viewedIds: string[];
  currency: Currency;
  market: string;
}) {
  const items = viewedIds
    .slice(0, 3)
    .map((id) => packs.find((p) => p.id === id))
    .filter((p): p is Pack => !!p);
  // A FULL STRIP OF THREE, OR NOTHING. A reader who has opened one pack got a labelled
  // section with a single row in it, directly above the shelf -- two bordered row
  // containers in one vertical run, which is what A10 forbids, and the shelf already
  // marks that pack "Seen". The row list starts earning its own heading at three.
  if (items.length < 3) return null;

  return (
    <div className="mb-8">
      <h3 className="mb-3 text-meta font-semibold text-text">Pick up where you left off</h3>
      {/* Rows, was a three-up card grid. A pack the reader has ALREADY opened is the weakest
          claim on the page for poster treatment, and this grid sat directly above the shelf's own
          cards -- two card formats in one vertical run, which the brief forbids. */}
      <PackRowList
        packs={items}
        currency={currency}
        viewerMarket={market}
        viewedIds={new Set(items.map((p) => p.id))}
      />
    </div>
  );
}

const SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'price-asc', label: 'Price: low to high' },
  { value: 'price-desc', label: 'Price: high to low' },
  { value: 'title', label: 'Name: A to Z' },
] as const;

type SortKey = (typeof SORTS)[number]['value'];

/** Buyer-facing name for the one filter a near-miss pack fails. KIND_NOUN, not KIND_LABEL: the
 *  heading form produced "Show any what you already have" (see the note in `lib/facets.ts`). */
function relaxLabelFor(kind: keyof typeof KIND_NOUN): string {
  return `Show any ${KIND_NOUN[kind]}`;
}

/**
 * The discovery dimensions a `filter_change` beacon can name, in a fixed order.
 *
 * Written out rather than read off `Object.keys`, because a beacon has to report the same name
 * for the same control forever. Key order is not something the type promises, and a dimension
 * added to `DiscoveryState` should be a deliberate addition here too.
 */
const FILTER_DIMENSIONS = [
  'q',
  'advantage',
  'sector',
  'payer',
  'effort',
  'commitment',
  'mechanism',
  'maxPence',
] as const;

type FilterDimension = (typeof FILTER_DIMENSIONS)[number];

/**
 * The value a beacon reports for one dimension, or `null` when the visitor has not set it.
 *
 * The advantage facet is multi-select, so its selections are sorted and joined. Sorting is what
 * stops "picking A then B" and "picking B then A" from looking like two different filters.
 */
function filterValueOf(state: DiscoveryState, dimension: FilterDimension): string | number | null {
  const value = state[dimension];
  if (Array.isArray(value)) return value.length > 0 ? [...value].sort().join('+') : null;
  if (value === '' || value === undefined) return null;
  return value;
}

/**
 * The names of the dimensions the visitor has constrained. Names only, never values: the search
 * box holds text the visitor typed, and this page does not send that anywhere.
 */
function constrainedDimensions(state: DiscoveryState): string[] {
  return FILTER_DIMENSIONS.filter((dimension) => filterValueOf(state, dimension) !== null);
}

/**
 * The shelf, driven by the discovery state (spec Parts 4, 6, 7).
 *
 * Filtering is client-side over the packs the server already sent, and the state round-trips
 * through the URL so a filtered shelf is a link someone can send. The URL update is `shallow`:
 * the packs are already here, so re-running `getServerSideProps` would be a network round trip
 * that changes nothing on screen.
 */
/**
 * The home shelf's own list of rows, and the reason it is not `PackRowList`.
 *
 * Rows past the fold are `hidden`, not unmounted, so their links stay in the server HTML for
 * search. That per-row class is the one thing the shared list cannot express, which is why this
 * list is written out separately.
 *
 * It is a component rather than inline JSX because it counts impressions, and counting needs a
 * hook. The block it replaced sat inside an IIFE in the middle of `CatalogBrowser`'s render, where
 * a hook call would be conditional on the branch above it and React forbids that.
 *
 * The spotlight above this list is deliberately NOT counted. It is a different card format, and a
 * click-through rate that mixes a poster with a row measures the format, not the title. Whichever
 * pack holds the spotlight therefore contributes no data to a title test that day.
 */
function ShelfRows({
  rows,
  currency,
  viewerMarket,
  viewedSet,
  beyondFold,
  belowSpotlight,
}: {
  rows: readonly Pack[];
  currency: Currency;
  viewerMarket: string;
  viewedSet: ReadonlySet<string>;
  /** True for rows the reader has not revealed yet; they render `hidden`. */
  beyondFold: (pack: Pack) => boolean;
  /** Adds the gap under the spotlight card when there is one. */
  belowSpotlight: boolean;
}) {
  const { observe } = useCardImpressions();
  return (
    /* THE DRAWING'S `.rows` CARD (`mockups/index.html` section 8): the whole catalogue is ONE
       card, white surface, 1px hairline, 12px radius, `overflow-hidden` so the first and last
       rows clip to its corners. Every other list on this page already used it, through
       `PackRowList`; the main shelf, which is the longest list on the site, was a bare
       `divide-y` on the page ground, so the section a buyer spends the most time in was the one
       section drawn without edges.

       NO `<ul>`/`<li>`. The rows are direct children, because `.row:last-child{border-bottom:0}`
       (mumchimp.css) is what removes the hairline above the card's bottom edge; with a `<li>`
       between the card and the row, every row is its own parent's last child and the rule fires
       on all of them. The beyond-fold `hidden` class moves onto the row itself. */
    <div className={cx('rows', belowSpotlight && 'mt-8')}>
      {rows.map((pack, i) => (
        <PackRow
          key={pack.id}
          pack={pack}
          className={cx(beyondFold(pack) && 'hidden')}
          currency={currency}
          viewerMarket={viewerMarket}
          viewed={viewedSet.has(pack.id)}
          observeRef={observe(pack.id)}
          position={i + 1}
        />
      ))}
    </div>
  );
}

function CatalogBrowser({
  packs,
  flags,
  initialState,
  market,
  currency,
  personalised,
  viewedIds,
  featuredId,
  catalogUnavailable,
}: {
  packs: Pack[];
  flags: Flags;
  initialState: DiscoveryState;
  market: string;
  currency: Currency;
  personalised: Pack[];
  viewedIds: string[];
  /* Only distinguishes the two empty states below; it never changes a non-empty shelf. */
  catalogUnavailable: boolean;
  /* The pack the hero is already showing in its desktop-only featured slot, so the shelf can
     avoid printing the same product twice on the same screen. Undefined on any render where the
     hero has no featured card, in which case the shelf behaves exactly as it did before. */
  featuredId?: string;
}) {
  const router = useRouter();
  const [state, setState] = React.useState<DiscoveryState>(initialState);
  const [sort, setSort] = React.useState<SortKey>('newest');
  const { open, setOpen, close, triggerRef } = useCommandPalette();
  /* O(1) lookup for the "Viewed" marker, so the card does not scan the id list 63 times. */
  const viewedSet = React.useMemo(() => new Set(viewedIds), [viewedIds]);

  /* `/?search=1` opens the palette. That is the landing the header's search control uses from
     every OTHER page on the site: the palette needs the catalogue to search, the catalogue is only
     loaded here, and a search control in the chrome that does nothing on /faq is worse than no
     search control at all. On this page the header dispatches a window event instead and never
     navigates (see `useCommandPalette`). */
  React.useEffect(() => {
    if (router.query.search === '1') setOpen(true);
  }, [router.query.search, setOpen]);

  const apply = React.useCallback(
    (next: DiscoveryState) => {
      setState(next);
      /* MASTER-BRIEF section 9, the discovery instrument. Every control on this page changes
         the shelf by calling `apply`, so this is the one place that cannot miss a control: the
         chips, the sheet, the wizard, the palette and the near-miss "show any X" all arrive
         here. Sorting is not counted, because it reorders the shelf rather than filtering it.

         The count comes from `filterPacks`, the same function the shelf renders from, so the
         number in the beacon is the number the visitor is looking at. */
      const resultCount = filterPacks(packs, next).length;
      for (const dimension of FILTER_DIMENSIONS) {
        const before = filterValueOf(state, dimension);
        const after = filterValueOf(next, dimension);
        if (before !== after) trackFilterChange(dimension, after, resultCount);
      }
      /* Fired every time a change lands on an empty shelf, not only on the first one. A visitor
         who tries three combinations and finds nothing three times is three failures, and the
         thing this counter exists to size is how often the catalogue disappoints. */
      if (resultCount === 0) trackFilterZeroResults(constrainedDimensions(next));
      const qs = encodeDiscoveryState(next);
      void router.replace(qs ? `/?${qs}` : '/', undefined, { shallow: true, scroll: false });
    },
    [packs, router, state],
  );

  /* An empty shelf the visitor never filtered their way into. A filtered URL is a link people
     send each other, so it can land on nothing without a single control being touched, and the
     `apply` beacon above would never see it. Fires once per page view. */
  const zeroOnLandingReported = React.useRef(false);
  React.useEffect(() => {
    if (zeroOnLandingReported.current) return;
    zeroOnLandingReported.current = true;
    if (isFiltered(initialState) && filterPacks(packs, initialState).length === 0) {
      trackFilterZeroResults(constrainedDimensions(initialState));
    }
  }, [initialState, packs]);

  /* The filter sheet, and the block it is a second way into. The open state lives HERE rather than
     inside the trigger because two things open it -- the pinned trigger, and (when the shelf came
     back empty) nothing else can -- and because the inline router unmounts while it is open. See
     `shelfControls`. */
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const shelfControlsRef = React.useRef<HTMLDivElement>(null);
  /* Where the shelf STOPS. `FilterFab` needs both edges of the region it filters, not just the
     top one -- see the `pastEnd` observer in FacetBar.tsx for why one edge left the trigger
     floating over the specimen at the bottom of this page. */
  const shelfEndRef = React.useRef<HTMLDivElement>(null);

  /* Measured height of the inline StepFlow block, kept live while it's mounted so the spacer
     below can stand in for it. WHY THIS EXISTS: opening the sheet unmounts that block (see the
     comment on `shelfControls`), and for anyone who has scrolled past it -- which is exactly who
     the pinned FilterFab trigger is for -- collapsing ~300-400px of page height that sits ABOVE
     their current scroll position shifts everything below it up by that amount while `scrollY`
     stays put. The reader's viewport lands on whatever content happened to end up at that pixel
     offset: a "jump to a random section" that isn't random at all, just unmeasured. A same-height
     placeholder keeps total page height constant across the open transition, so the scroll
     position keeps pointing at the same content. */
  const [stepFlowHeight, setStepFlowHeight] = React.useState<number | null>(null);
  const stepFlowWrapRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = stepFlowWrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => setStepFlowHeight(entry.contentRect.height));
    ro.observe(el);
    return () => ro.disconnect();
  }, [filtersOpen]);

  const visible = React.useMemo(() => {
    const filtered = filterPacks(packs, state);
    if (sort === 'newest') return filtered; // server already returns newest-first
    return [...filtered].sort((a, b) => {
      if (sort === 'title') return a.title.localeCompare(b.title);
      const delta = parseFloat(a.price) - parseFloat(b.price);
      return sort === 'price-asc' ? delta : -delta;
    });
  }, [packs, state, sort]);

  // Only computed when the shelf came back empty, the near-miss row exists to rescue that case.
  const candidates: NearMissCandidate[] = React.useMemo(() => {
    if (visible.length > 0) return [];
    return nearMisses(packs, state).map((miss) => ({
      pack: miss.pack,
      missLabel: missLabelFor(miss.kind, miss.wanted, miss.actual),
      relaxedState: miss.relaxedState,
      relaxLabel: relaxLabelFor(miss.kind),
    }));
  }, [visible.length, packs, state]);

  const filtered = isFiltered(state);

  // Boost, don't block: partition the filtered/sorted shelf into the visitor's market and every
  // other, so the grid can render "your market" first without ever dropping a pack.
  const grouped = React.useMemo(() => groupByMarket(visible, market), [visible, market]);

  // No spotlight slab any more (see the deletion note above SpotlightCard's former home): the
  // default sort is `newest`, so the newest pack is already the first card in the grid.
  const gridPacks = grouped.matching;

  /*
   * The shelf's editorial shape (spec section 7, 2026-08-05).
   *
   * Measured before this: `/` was 21,717px on desktop and 49,558px on mobile, 73% of it one flat
   * grid of 61 cards with no hierarchy between pack #1 and pack #61. A shelf SHOULD dominate a
   * storefront, so the height was never the defect; the absence of any way to form a shortlist
   * was.
   *
   * Two rows carry meaning, and only on the default view -- once the visitor has filtered or
   * re-sorted, THEY have stated the ordering and an editorial row talking over it is noise.
   *
   * The spec also proposed a "Cleared all six checks" row. It is deliberately not built, though
   * NOT for the reason first written here. The original note claimed "a pack only reaches the
   * catalogue by clearing all six (CLAUDE.md, 'Publish only on PASS')" -- that is false. The
   * publish rule is that no HARD GATE is refuted; score_checks run and score but never kill
   * (config.yaml `lanes.side_hustle.score_checks`). Measured 2026-08-06 on the live /catalog
   * detail endpoint: 5 of 63 published packs report fewer cleared than total ("7/8" x4, "6/8" x1),
   * e.g. CureSafe Strip, whose dossier carries claims_verifiable=refuted and
   * payer_solvency=refuted yet legitimately passed on its lane's four hard gates. The row stays
   * unbuilt because it would select 58 of 63 -- near-useless as a filter -- not because it
   * selects everything.
   */
  const editorial = !filtered && sort === 'newest';

  /* The tail is capped, not dropped: every card stays in the server HTML and is only display-
   * hidden, so a crawler and the "a filtered URL comes back filtered" e2e still see all of them
   * while the buyer gets a page with an end.
   *
   * 9, not 24 (2026-08-06). 24 + the 3-card newest row is 27 products before the reader reaches
   * any reason to stop, and each card is now ~112px taller than it was because it has a cover --
   * that combination is what made `/` read as an endless scroll rather than a shelf. 9 = 3 rows of
   * 3 (lg), and with the newest row above it the first screenful of catalogue is 12 packs, which
   * is a set a person can actually hold in their head before choosing to see more. The remaining
   * 51 are one click away and, per the note above, are in the HTML the whole time. */
  const SHELF_PAGE = 9;
  const [showAll, setShowAll] = React.useState(false);
  /* THE SAME PRODUCT TWICE ON ONE SCREEN (measured 2026-08-06 on the built page at 1440x900:
     "Council specific recycling boards for flat bin stores" rendered in the hero's featured slot
     AND as the first card of "Newest survivors", both fully visible above the fold).
     `featured` is `packs[0]` and the row starts at `gridPacks[0]`, which is the same pack whenever
     the newest pack is in the reader's market -- i.e. almost always. The comment above `featured`
     claimed the slot "is NOT a second copy of the card" because it is `hidden lg:block`; that is
     true on a phone and false on the width where both were on screen together.

     So on lg the row takes the NEXT three and the duplicate is hidden; below lg, where the hero
     slot is not rendered, the row takes four and the reader meets the newest pack once, in the
     grid. Four either way, so the row is full at every breakpoint and the "Showing n of N" count
     below is exact at both: 4 in the row on mobile, 3 in the row plus 1 in the hero on desktop.

     Guarded by an id comparison rather than an index: `gridPacks` is the reader's market only and
     `featured` is the newest pack overall, so for a reader whose market does not contain the
     newest pack the two differ -- and hiding `gridPacks[0]` there would hide a card they had
     never been shown. */
  const rowHasFeatured = editorial && !!featuredId && gridPacks[0]?.id === featuredId;
  const newestRow = editorial ? gridPacks.slice(0, rowHasFeatured ? 4 : 3) : [];
  const tailPacks = editorial ? gridPacks.slice(newestRow.length) : gridPacks;
  const shown = showAll ? tailPacks.length : Math.min(SHELF_PAGE, tailPacks.length);

  // The most recent verification across the live shelf, rendered once, in the toolbar. It used to
  // be its own bordered "Live database" capsule above the toolbar that then restated the count.
  const lastVerified = React.useMemo(
    () => freshnessLabel(packs.map((p) => p.verifiedAt).filter((d): d is string => !!d).sort().at(-1)),
    [packs],
  );

  /*
   * THE SHELF CONTROLS -- search, count, sort, sector chips -- as ONE block, so the page can
   * choose where they go instead of having them nailed above the grid.
   *
   * WHY (measured on the live page, 2026-08-08, 1280x800). The section headed "What survived" ran:
   * heading, one line of copy, a search field, a count, a sort dropdown, then ELEVEN sector chips
   * over two rows -- and only then a product. The first pack card sat at y=983 of an 8,284px page
   * with ~200px of control panel directly above it. A storefront that puts a database console
   * between a stranger and its products has asked them to operate the shop before it has sold them
   * anything; the controls are a tool for narrowing a shelf, which is a thing a visitor wants
   * AFTER they have seen the shelf and decided it is too big.
   *
   * This is the same argument, and the same fix, that already moved `StepFlow` below the first
   * product row (see the note where it used to render). It is a REORDER, not a removal: every
   * control, every chip and the palette are exactly as they were.
   *
   * Rendered EXACTLY ONCE per page. Two `SearchTrigger`s would give the palette two ref'd owners
   * and the chips two sources of truth, so the two render sites below are mutually exclusive
   * branches, never an either/or that can both be true.
   */
  const wizardControls = (
    <div ref={shelfControlsRef} className="mb-8 pt-8">
      {/* Named, because an unlabelled control panel sitting mid-shelf reads as debris. It says
          what it is FOR, which is the thing the old placement never had to say because it was
          simply in the way. */}
      <h3 className="sub">Narrow it down</h3>
      <p className="lede">Four filters. Use one, or all of them, they combine.</p>

      {/* THE THREE CONTROLS ARE ONE FILTER (founder review, 2026-08-15).
          A search field, a sector rail and a three-question router stack vertically in this block
          with nothing saying how they relate, so they read as three competing filters and the
          reader has to guess which one is THE one -- or fears that using the second undoes the
          first. They do not compete: all three write to the same `DiscoveryState` through the
          same `apply`, and `filterPacks` ANDs every field, so they compose.

          That is a fact about the code, and one sentence is enough to state it. I am deliberately
          NOT collapsing three mechanisms into two here: each answers a different question a
          reader actually arrives with (I know the words / I know the sector / I know only my own
          situation), and deleting one is a product decision about which of those readers we stop
          serving -- the founder's call to make, not a defect for me to patch out silently. The
          defect named in the review is the missing relationship, and this is that.

          Cut to seven words on 2026-08-16 (founder: "why so much words saying so little"). The
          first version described each of the three controls in turn, which the controls do
          themselves, immediately below. The only thing a reader cannot see by looking is whether
          using the second undoes the first, so that is the only thing left. */}
      <p className="mb-4 lede">Use one or all three. They combine.</p>

      {/* Toolbar: search, count, sort. */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:w-64">
          <SearchTrigger onOpen={() => setOpen(true)} triggerRef={triggerRef} />
        </div>
        {/* Wraps on a phone, and that is a bug fix rather than a tidy-up.

            2026-08-15, measured on the live shelf at 320/360/390: this row put a
            `whitespace-nowrap` caption 295px wide next to a fixed `w-40` control with a 16px
            gap -- 471px of content in at most 342px of usable width -- inside an ancestor that
            clips on the x axis. So the sort control was laid out at x=335 and simply cut: at
            390px it read "Newes", and at 320px it began past the right edge and was invisible
            and untappable. Nothing scrolled and nothing overflowed the document, because the
            clip swallowed it, which is why five viewports' worth of `scrollWidth == innerWidth`
            checks all passed while the control was unreachable on every phone.

            `flex-wrap` plus a caption that only refuses to break from `sm` up is the whole fix:
            the dropdown drops to its own line under the count on a phone and the desktop row is
            byte-identical. */}
        <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 sm:w-auto sm:flex-nowrap">
          {/* Count and freshness in one mono caption -- both are quantities, and this is the only
              place either is stated on the shelf now.

              THIS COUNT NAMES WHAT IT COUNTS (2026-08-14, founder review). It is `visible.length`,
              i.e. the catalogue AFTER the current filters and search, across EVERY market -- and it
              said only "45 packs", 800px under a hero saying "62 packs" and directly above a button
              offering "Show the other 37". Three numbers that cannot all be the same number, none
              of which said which population it was about, on a shop whose pitch is that it counts
              carefully. Nothing about the filtering changed here; the numbers were already correct
              and were already reconcilable. What was missing was the noun.

              So: unfiltered it states the catalogue total, filtered it states the match AGAINST that
              total, which makes the subtraction visible instead of leaving the reader to infer it.
              `visible.length === packs.length` is a label branch and nothing else -- `visible` is
              `filterPacks(packs, state)` re-sorted, so the two are equal exactly when no filter is
              narrowing anything. */}
          <span className="font-mono text-caption text-subtle sm:whitespace-nowrap">
            {visible.length === packs.length
              ? `${packs.length} packs in the catalogue`
              : `${visible.length} of ${packs.length} packs match`}
            {lastVerified && ` · updated ${lastVerified.replace(/^Verified /, '')}`}
          </span>
          <div className="w-40 shrink-0">
            <Dropdown<SortKey> label="Sort packs" value={sort} options={SORTS} onChange={setSort} />
          </div>
        </div>
      </div>

      {/* The sector filter, in the same place the eye already met the sector: the pills on the
          cards. */}
      <SectorChips packs={packs} state={state} onChange={apply} />

      <AppliedFilterChips state={state} onChange={apply} className="mb-4" />

      {/* The three-question router, CONSOLIDATED here from the foot of the shelf.
          It used to render after the last of 53 cards -- y=4054 on desktop, 5.1 screens down --
          on the reasoning that the only reader a router helps is one who scanned the shelf and
          picked nothing. That is true of who it helps and false about what it costs: a reader who
          decided at card three that the shelf was too big had to scroll the whole thing to reach
          the control that would have made it smaller. It belongs with the other controls, and the
          controls already sit after the first product row, so it no longer pushes product down.

          Unmounted while the sheet is open, because the sheet renders the same component and this
          file's rule is that these controls exist EXACTLY ONCE per page (see the note above the
          block). Two mounted routers would mean two wizard positions for one filter state, and
          would double every selector an e2e test matches on. The remount costs the step position,
          which is the right thing to lose: opening the sheet is starting the narrowing again.

          The unmount itself is real -- `stepFlowHeight` below only stands in for its FOOTPRINT,
          so page height doesn't move and a reader scrolled past this block doesn't get jumped.
          See the comment on `stepFlowHeight`. */}
      {filtersOpen ? (
        stepFlowHeight != null && <div aria-hidden="true" style={{ height: stepFlowHeight }} />
      ) : (
        <div ref={stepFlowWrapRef} className="mt-12">
          <StepFlow packs={packs} state={state} onChange={apply} />
        </div>
      )}
    </div>
  );

  /**
   * The one filter system (MASTER-BRIEF §7), behind `flags.filterBar`.
   *
   * It is the whole of `wizardControls` above in one row: the same search trigger, the sector
   * filter, the capability filter, a price ceiling and the sort -- all writing the same
   * `DiscoveryState` through the same `apply`. There is no sector rail and no applied-chip row,
   * because each control now shows its own selection; and no `StepFlow`, which is the deletion §7
   * asks for.
   *
   * IT KEEPS `shelfControlsRef`. That ref is what `FilterFab` measures to know whether the reader
   * has scrolled past the controls, and the fab is the only way back to them from four screens
   * down. The bar is shorter than the stack it replaces, so it goes past the top of the viewport
   * sooner, not later.
   *
   * The count and the freshness line come with it. They are a statement about the shelf rather
   * than a control, so they sit under the bar rather than in it.
   */
  const barControls = (
    <div ref={shelfControlsRef} className="mb-8 pt-8">
      {/* THE DRAWING'S SECTION 6 (`mockups/index.html`), which the bar had lost: the shelf's own
          heading and the one line that says the filters combine. The note this replaces argued
          that a control panel needing a caption is a broken control panel. That argument was about
          FOUR stacked controls competing; one row of four is a different object, and the drawing
          gives it this line. No dash in it (founder's standing rule on copy): the mockup's em dash
          is a full stop here. */}
      <h3 className="sub">Narrow it down</h3>
      <p className="lede mb-4">Four filters. Use one, or all of them. They combine.</p>
      <FilterBar
        packs={packs}
        state={state}
        onChange={apply}
        sort={sort}
        sortOptions={SORTS}
        onSortChange={(value) => setSort(value as SortKey)}
        currency={currency}
        onOpenSearch={() => setOpen(true)}
        searchTriggerRef={triggerRef}
      />
      <p className="mt-2 font-mono text-caption text-subtle">
        {visible.length === packs.length
          ? `${packs.length} packs in the catalogue`
          : `${visible.length} of ${packs.length} packs match`}
        {lastVerified && ` \u00b7 updated ${lastVerified.replace(/^Verified /, '')}`}
      </p>
    </div>
  );

  /* One name for both paths, so every render site below is untouched by the flag. §8 asks for the
     two to coexist for a week of comparison before the wizard is deleted. */
  const shelfControls = flags.filterBar ? barControls : wizardControls;

  if (packs.length === 0) {
    /* Two different facts, and they were rendered as one sentence until 2026-08-15. An empty
       catalogue we SUCCESSFULLY fetched means nothing is live; an empty one we failed to fetch
       means our own API is unreachable, and saying "no packs are live" there is a false claim
       about the business caused by our outage. See `lib/catalogCache.ts`. */
    return (
      <div className="rounded-md border border-dashed border-border bg-surface py-16 text-center">
        <div className="mx-auto mb-3 flex items-center justify-center text-faint">
          <Icon name={catalogUnavailable ? 'warning' : 'search'} size={24} />
        </div>
        <p className="text-body font-semibold text-text">
          {catalogUnavailable
            ? "We can't reach the catalogue right now."
            : 'No packs are live right now.'}
        </p>
        <p className="mx-auto mt-1 lede">
          {catalogUnavailable
            ? 'This is on our side, not yours. Nothing has sold out. Refresh in a moment.'
            : 'We publish an opportunity the moment it clears every check. Check back shortly.'}
        </p>
      </div>
    );
  }

  return (
    <>
      {/* Only shown once we have boosted away from the default shelf. A visitor already on "uk"
          has nothing to be told, the grid below is already every pack, in the usual order. */}
      {market !== DEFAULT_MARKET && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface2 px-4 py-3 text-meta">
          <span className="text-muted">Showing packs for {marketLabel(market)} first.</span>
          {/* Sets the `market` cookie server-side (getServerSideProps) on the next request, so
              the switch survives past this one click, not just this one page load. */}
          <Link
            href={`/?market=${DEFAULT_MARKET}`}
            className="whitespace-nowrap py-3 font-medium text-accent hover:text-accent-hover"
          >
            Switch to {marketLabel(DEFAULT_MARKET)}
          </Link>
        </div>
      )}

      {/* StepFlow used to sit HERE, as the first thing in the catalogue, and it is why
          `e2e/discovery.spec.ts` "the first pack card is above the fold" was failing at -500px
          (measured 2026-08-05, 1280x720). The spec's own comment records the form as 107px when
          the fold was last fixed; it is now 397px, so it had grown 290px unnoticed -- exactly the
          additive regression that test was written to catch, on a page whose entire pitch is
          "here is what survived".

          It now renders after the first product row instead (see below). A facet router is a tool
          for narrowing a shelf, and it is asked for after the visitor has seen the shelf, not
          before: at the top of the page it is a three-question quiz standing between a stranger
          and the product. Nothing is removed and no step changes -- only the order. */}

      {/* The toolbar and the sector chips USED TO RENDER HERE, above every product on the page.
          They now render as `shelfControls`, after the first row of packs -- or, when the shelf
          came back empty, immediately below, because an empty shelf is the one state where the
          controls ARE the content the visitor needs (they are what un-filters it). */}
      {visible.length === 0 && shelfControls}

      {/* WHY ONE CARD SAYS £49 AND THE NEXT SAYS £29, stated where the prices are.
          Six distinct prices run down this grid (measured on the live /catalog 2026-08-06: £29 x7,
          £49 x48, £79 x5, £99, £149, £199) with nothing on the page explaining the difference, so
          the buyer is left to infer it -- and the inference they reach is "the dear ones must be
          the better ones", which invites them to distrust the cheap ones and hesitate over the
          dear ones. The rule is real and it is the opposite: `config.yaml listing.pricing` picks a
          rung on a fixed ladder from the opportunity's ambition tier plus a market offset, and
          every pack ships the identical `PACK_DOCUMENTS.length` documents. The page already said
          this, ~6,000px below the shelf, in the "What you get" intro.
          A per-card tier BADGE was the other option and is deliberately not built: the ladder is
          not invertible from the price, because a us/smb pack and a uk/growth pack both land on
          £79, so a badge derived from the price would be a label we cannot source.

          ONE LINE, AT EVERY WIDTH, ONCE ON THE PAGE. This used to be a `sm:`-and-up sentence plus
          a shorter `sm:hidden` twin, and the same explanation ran again ~6,000px below in the
          "What you get" intro and a third time on /pricing: the ladder was described three times
          on one scroll. The full rule (ambition tier plus a market offset, on a fixed published
          ladder) belongs to /pricing, which is the page a buyer opens with that exact question.
          What has to be here is the part that stops the misreading at the shelf -- "the dear ones
          must be the better ones" -- and that is two facts: the contents never change, and the
          price tracks the size of the opportunity.

          Short enough to sit on one line at 360px, which is a fold-budget constraint, not a style
          one: `e2e/discovery.spec.ts` asserts the first pack card is above the fold at 360x780,
          and the four-line version of this paragraph failed it by 16px. */}
      <p className="mb-4 max-w-[68ch] text-caption text-subtle">
        Same {PACK_DOCUMENTS.length} documents in every pack. Bigger opportunity, higher price.{' '}
        <Link href="/pricing" className={textLinkClass('font-medium')}>
          Why prices differ
        </Link>
      </p>



          {visible.length > 0 ? (
            <>
              {/* THE "BASED ON YOUR BROWSING" ROW IS GONE (fix prompt D8, 2026-08-18).

                  It was an `h3` at `text-meta` over a grey `text-caption` subline, and neither
                  is a shape `mockups/index.html` draws: the drawing introduces a group of packs
                  with `h2.sec` and a `.lede`, or with nothing at all. So the one section on the
                  page that claimed to be personalised was also the one section wearing a
                  heading style used nowhere else, which is what made this end of the page read
                  as a different site from the top of it.

                  `RecentlyViewed` stays and is now unconditional. It does the same job -- packs
                  this visitor has already opened -- without asserting a recommendation the page
                  cannot show its working for, on a site whose whole pitch is showing the
                  working. The personalisation cookie and `personalised` are untouched upstream;
                  only this render site is removed. */}
              <RecentlyViewed
                packs={packs}
                viewedIds={viewedIds}
                currency={currency}
                market={market}
              />
              {newestRow.length > 0 && (
                <div className="mb-8">
                  {/* `text-body`, was `text-meta`. A row heading set at the same size as the
                      body copy INSIDE the cards it introduces does not read as a heading at all;
                      on the built shelf "Newest survivors" and a card's one-line description were
                      the same 14px, so the grid arrived with no visible tier between "label for a
                      group of products" and "sentence about one product". This is the smallest
                      step that separates them and it stays sentence case, so the house policy in
                      `__tests__/weightAndCasePolicy.test.ts` is untouched. */}
                  <h3 className="mb-3 hidden sm:block sub">
                    Newest survivors
                  </h3>
                  {/* Rows. The `lg:hidden` on the hero's featured pack went with the card grid:
                      as a row this entry is one line in a list rather than a second poster of the
                      pack already spotlit in the hero, so the duplicate it guarded against no
                      longer costs a screen -- and the internal link stays in the server HTML at
                      every width, which is what that guard was protecting. */}
                  {/* TILES, as drawn. `mockups/index.html` breaks its column of rows exactly
                      once, here, with three tiles. */}
                  <PackTileGrid packs={newestRow.slice(0, 3)} currency={currency} viewedIds={viewedSet} />
                </div>
              )}

              <KillGateBand />

              {/* PRODUCT FIRST, THEN THE MEANS TO NARROW IT. See the note on `shelfControls`.
                  When the visitor has already filtered, `editorial` is false, so `newestRow` is
                  empty and this lands directly above the results -- which is correct: at that
                  point the controls are what they are USING, not what is in their way. */}
              {shelfControls}

              {/* Was "The rest of the catalogue, newest first". The shelf above it is headed
                  "Newest survivors" -- a claim -- and then the same products, in the same order,
                  were introduced as leftovers. "The rest of" says the good ones were the three
                  above and these are what remains, which is not true of a catalogue where every
                  row passed the identical filter. One voice, both headings. */}
              {editorial && tailPacks.length > 0 && (
                /* BOTH row headings are desktop-only, and the pair is why.
                   They label the two halves of a THREE-COLUMN grid: "Newest survivors" over the
                   top row, "More survivors, newest first" over everything after it. On a phone
                   the grid is one column, so the reader meets a heading, three cards, and then a
                   second heading announcing more of the same list in the same order -- a
                   distinction that only exists because of a breakpoint. The section is already
                   headed "What survived" and the sort control already reads "Newest", so nothing
                   is lost and the shelf reads as one continuous list, which is what it is.

                   It also pays for the "What survived" heading added above: measured at 360x780
                   on the built page, the first card had moved to y=779 against a bar of 740, and
                   dropping this pair puts it back at 740. */
                /* The heading names the ACTUAL order after the editorial banding, which is by
                   price tier and then by recency inside each tier. It used to say "newest first",
                   which was true of the uniform grid and is not true of this one -- and a heading
                   that misdescribes the list under it is the same class of error as an unsourced
                   number. */
                <h3 className="mb-3 hidden sm:block sub">
                  More survivors, biggest opportunities first
                </h3>
              )}
              {/* ── THE SHELF ────────────────────────────────────────────────────────────
                  ONE SPOTLIGHT, THEN ROWS (2026-08-15, founder's mobile brief).

                  This was three treatments chosen by price tier: full-bleed `lead`, half-width
                  `mid`, hairline `row`. The brief's first instruction is that the site has two
                  card formats and that never more than one spotlight appears in a vertical run,
                  because a shelf where three formats alternate reads as a page assembled from
                  three different sites rather than as an editorial ranking.

                  The mid band is deleted, not demoted. Its own code recorded why: at 1440x900 an
                  odd count left "a 590px card at x=120 with 610px of empty white beside it,
                  directly under a full-bleed lead card -- which does not read as an editorial
                  choice, it reads as a card that failed to load", patched by promoting the odd
                  card into the lead band. A tier that has to leave its own band to lay out is not
                  a tier. Everything that was `mid` is now a row.

                  The editorial claim survives in the one place it costs nothing: the highest-
                  ranked £99/£149 pack keeps the spotlight, at the head of the shelf. Every other
                  pack, at every price, is a row -- so ORDER is preserved exactly (`tailPacks`
                  order, not re-banded), which also fixes the honesty problem the old note owned
                  up to: the heading no longer has to describe a list the bands had reordered.

                  `shown` still gates by position in the original tail order, so "Show the other N
                  packs" reveals the same set and the count under the button stays correct. */}
              {(() => {
                const rank = new Map(tailPacks.map((p, i) => [p.id, i]));
                const beyondFold = (p: Pack) => (rank.get(p.id) ?? 0) >= shown;
                /* The spotlight is the FIRST visible spotlight-tier pack, not all of them: the
                   whole point of the format is that it is singular. A spotlight-tier pack that is
                   past the fold does not claim the slot from a visible one, because the slot is
                   about what the reader sees, not about the array. */
                const spotlight =
                  tailPacks.find((p) => packWeight(p) === 'spotlight' && !beyondFold(p)) ?? null;
                const rows = tailPacks.filter((p) => p !== spotlight);

                return (
                  <>
                    {spotlight && (
                      <div className="flex animate-rise">
                        <PackSpotlight
                          pack={spotlight}
                          currency={currency}
                          viewerMarket={market}
                          viewed={viewedSet.has(spotlight.id)}
                        />
                      </div>
                    )}

                    {rows.length > 0 && (
                      <ShelfRows
                        rows={rows}
                        currency={currency}
                        viewerMarket={market}
                        viewedSet={viewedSet}
                        beyondFold={beyondFold}
                        belowSpotlight={Boolean(spotlight)}
                      />
                    )}
                  </>
                );
              })()}
              {/* THE BUTTON NAMES THE POPULATION IT WILL REVEAL (2026-08-14, founder review).
                  `tailPacks.length - shown` is the remainder of the READER'S OWN MARKET group only
                  -- `tailPacks` comes off `gridPacks`, which is `grouped.matching` -- so "Show the
                  other 37 packs" on a page whose hero says 62 read as an arithmetic error rather
                  than as two different populations. Naming the market makes it subtract correctly
                  against the market line directly below it, which states this group's total. The
                  cap, the ordering and what is hidden are all untouched: this is the label. */}
              {shown < tailPacks.length && (
                <div className="mt-8 flex flex-col items-center gap-2">
                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={() => {
                      /* MASTER-BRIEF section 9, `catalogue_page_more`. Meta is "shown:total" for
                         the reader's own market, which is the same pair the button label states,
                         so a press can be read against how much shelf the reader already had. */
                      track('catalogue_page_more', `${shown}:${tailPacks.length}`);
                      setShowAll(true);
                    }}
                  >
                    Show the other {tailPacks.length - shown} {marketLabel(market)} packs
                    <Icon name="arrowRight" size={15} />
                  </Button>
                </div>
              )}

              {gridPacks.length > 0 && (
                <div className="mt-4 flex justify-center">
                  {/* THE SHELF, BROKEN DOWN BY MARKET, and by nothing else.

                      This read "Showing 13 of 47 written for your market, plus 10 written for other
                      markets below." Three numbers, two of which are an artefact of how far the
                      reader has scrolled: 13 is the pagination cursor, and it changes when the
                      button directly above it is pressed. The one durable fact a reader needs here
                      is how the catalogue splits, because the split is the reason some packs are
                      below the divider rather than in the grid.

                      Every figure is counted from the packs in this render, so the parts sum to the
                      total the page states elsewhere by construction. The earlier version could
                      not: the hero printed `packs.length` (63) while this line printed `gridPacks`
                      (52), two totals for one catalogue ~800px apart, with nothing saying the 11
                      missing ones were further down rather than missing.

                      THE LINE NOW SHOWS ITS OWN SUM (2026-08-14, founder review). "Every figure is
                      counted from the packs in this render, so the parts sum to the total the page
                      states elsewhere by construction" was true and invisible: the parts were
                      printed and the total they sum to was not, so a reader comparing this line
                      against the hero's 62 or the button's 37 had to hold three unlabelled
                      populations in their head. `gridPacks.length` is the reader's market after
                      filtering; `group.packs.length` is each other market after the same filtering;
                      together they ARE `visible.length`, which is the number the toolbar states. It
                      is written as the sum of the parts, not as `visible.length`, so a partition
                      that ever stopped summing would print the discrepancy rather than hide it.

                      The per-market parts keep their exact template -- `${gridPacks.length}
                      ${marketLabel(market)} packs` -- because `__tests__/shelfHasShape.test.ts`
                      pins that string as the proof the breakdown is computed from live data rather
                      than typed. The total is appended as a further part rather than wrapped around
                      them, which satisfies both: the line still reads as one `·`-joined series. */}
                  {/* The drawing's `.spread` (`mockups/index.html:509`), the centred mono line
                      under the shelf. */}
                  <p className="spread num">
                    {[
                      `${gridPacks.length} ${marketLabel(market)} packs`,
                      ...grouped.others.map((group) => `${group.packs.length} ${group.label} packs`),
                      `${gridPacks.length + grouped.others.reduce((n, g) => n + g.packs.length, 0)} in total`,
                    ].join(' · ')}
                  </p>
                </div>
              )}

              {/* Boost, don't block: every other market's packs are still fully on the shelf,
                  clearly separated rather than mixed in or hidden.

                  The heading was an `<h2>` reading "Also available, US" -- larger than the `<h3>`s
                  above it, so a reader scanning by heading weight met the off-market group as if it
                  outranked the catalogue it was appended to, and "also available" does not say what
                  is different about it. It is an `<h3>` matching its siblings now, it names the
                  difference in the heading, and one line underneath says what buying one of these
                  actually means. Each card in the group also carries the "For US rules" chip that
                  the on-market cards no longer waste space on. */}
              {/* TWO GROUPS, NOT FIVE (2026-08-18). `mockups/index.html` section 13 draws exactly
                  two market appendices. The page printed every group it had -- US, UK, US-FL,
                  US-CA, US-TX -- five headed sections of three rows each below a shelf that had
                  already capped itself, and that is most of the 3,900px this page runs over the
                  drawing. The rest arrive with the same "show all" the shelf uses, so nothing is
                  hidden, it is just not all printed before anyone asked. */}
              {(showAll ? grouped.others : grouped.others.slice(0, 2)).map((group) => (
                /* A REAL RULE, NOT A GAP (2026-08-14, founder review at 390px). The boundary
                   between the reader's own shelf and this appendix was `mt-16` and a
                   `text-meta` heading -- on a phone, after forty rows, that is whitespace
                   followed by a line barely heavier than the body text. Every row below it
                   correctly prints "US rules", and the founder read them as UK rows that had
                   been mistagged: a correct flag on the wrong side of an invisible border
                   looks exactly like a data bug. The divider carries the same weight as the
                   distinction it is making now. */
                <div key={group.market}>
                  {/* US PACKS DIVIDER (email §1). The divider is about what the buyer would be
                      BUILDING, not what the page has written, and the subtitle states the
                      consequence plainly: the research is American, and the package cannot be
                      transplanted.

                      "market", not "rules" (founder, 2026-08-15). The subtitle directly under it
                      already says what travels with the country -- "the buyers, numbers and legal
                      steps" -- and only the last of those three is a rule, so the heading was
                      naming the smallest part of its own argument. Same change on the row chip
                      (`PackRow.tsx:144`), so the shelf says one thing. */}
                  {/* THE DRAWING'S MARKET HEADER (`mockups/index.html` section 13): a flex row
                      holding an `h2.sec` and a mono pack-count chip, then the lede under it.
                      It was an `h3.sub` with Tailwind utilities, which cannot look like the
                      drawing: mumchimp.css is imported into the `components` layer and every
                      property a utility also sets wins over it. */}
                  <div className="mkt-h">
                    <h2 className="sec">Built for the {group.label} market</h2>
                    <span className="mkt-tag num">
                      {group.packs.length} {group.packs.length === 1 ? 'pack' : 'packs'}
                    </span>
                  </div>
                  <p className="lede mb-[18px]">
                    The buyers, the numbers and the legal steps all follow {group.label} rules.
                    Read them anywhere; build them there.
                  </p>
                  {/* Rows, not cards. This group is explicitly secondary -- the copy directly
                      above says the numbers and legal steps will not transfer -- so giving it the
                      same card treatment as the on-market shelf contradicted the sentence
                      introducing it. Rows keep every pack fully present and linkable while
                      reading as an appendix, which is what it is. Each row still prints its
                      "<market> rules" flag, since `viewerMarket` is deliberately not passed. */}
                  {/* CAPPED, like the shelf above it (2026-08-18). Every off-market group printed
                      in full, so the landing page ran to 14,239px against the drawing's 8,653 --
                      five market appendices, forty rows, below a shelf that had already capped
                      itself at nine. `mockups/index.html` section 13 shows two market groups of a
                      few rows each. Same `showAll` toggle as the main shelf, so one press opens
                      the whole catalogue and there is still exactly one control for it. */}
                  <PackRowList
                    className="mt-6"
                    packs={showAll ? group.packs : group.packs.slice(0, 3)}
                    currency={currency}
                    viewedIds={viewedSet}
                  />
                  {!showAll && group.packs.length > 3 && (
                    <div className="more-row">
                      <button type="button" className="more" onClick={() => setShowAll(true)}>
                        Show the other {group.packs.length - 3} {group.label} packs
                      </button>
                    </div>
                  )}
                </div>
              ))}

              {/* The three-question router USED TO RENDER HERE, after the whole shelf, and the
                  note that put it here argued the only reader it helps is one who scanned every
                  card and picked nothing. That is right about who it helps and silent about what
                  it cost everyone else: measured on prod it sat at y=4054, 5.1 screens down, past
                  all 53 cards. It now renders inside `shelfControls` with the other controls, and
                  is reachable from anywhere on the page via `FilterFab` -- so the reader this
                  block was written for still meets it at the end of their scan, without it being
                  the only place anyone else can find it. */}
              {/* The "Every pack carries a 14-day money back guarantee" line that closed the shelf
                  is gone: appearance 2 of 4 of the same promise on one page. `TrustGuaranteesRow`
                  states it once, below. */}
              {/* The waitlist ask sits AFTER the shelf on purpose: the deployed variant put it
                  between the hero and the first card, spending above-the-fold pixels on buyers
                  who had not yet seen a product. Down here it reaches the only buyer it converts
                 , one who scrolled the shelf and still wants more. It renders ONLY on this
                  branch: the near-miss and empty states carry their own ask (DiscoveryWaitlist),
                  and two email forms on one screen is a duplicate ask that also breaks selector
                  uniqueness. Rationale in ShelfEndCapture.tsx.

                  ONE FORM IS ALREADY TRUE; ONE VERB IS NOT (audited 2026-08-14, founder review).
                  The count is not in doubt -- this render and `DiscoveryWaitlist` two branches down
                  are arms of the same ternary, so no state of this page can produce two email
                  fields, and the only email field in the whole marketing tree is the one inside
                  `WaitlistForm` (`MarketingLayout` has none). What IS wrong is the LABEL on the
                  submit: this placement passes `submitLabel="Tell me when one survives"`
                  (`ShelfEndCapture.tsx:61`) while the empty state takes the component default, "Put
                  it in the queue" (`WaitlistForm.tsx:51`) -- two verbs for one action, on one page,
                  differing only by which branch the reader landed on.

                  THEY ARE NOT TWO LISTS AND MUST NOT BE KEPT APART FOR THAT REASON. Both mount the
                  same `WaitlistForm`, which posts to one endpoint with one `WAITLIST_CONSENT_TEXT`
                  hash; the ONLY thing that differs is the `source` tag, which is attribution in the
                  ledger ("homepage-shelf-end" vs "catalogue-empty-state") and not a subscription.

                  THE FIX IS ONE LINE AND IT IS NOT IN THIS FILE: drop the `submitLabel` override at
                  `ShelfEndCapture.tsx:61` so every placement takes the default verb. The default is
                  the one that must win rather than the override, because `WaitlistCallout` uses it
                  too on /kill-log and /sample -- unifying on the override would leave three surfaces
                  disagreeing instead of two. Left undone here only because this pass is scoped to
                  `pages/index.tsx`. */}
              <ShelfEndCapture className="mt-10" />
            </>
          ) : candidates.length > 0 ? (
            /* A. Something is one facet away, sell that before asking for an email address. */
            <DiscoveryNearMiss candidates={candidates} onRelax={apply}>
              {/* Rows. These are near misses -- packs that did NOT match the reader's filters --
                  so they are the last thing on the page entitled to the one format reserved for a
                  pack presented alone. */}
              <PackRowList
                className="mt-5"
                packs={candidates
                  .map((candidate) => packs.find((p) => p.id === candidate.pack.id))
                  .filter((p): p is Pack => !!p)}
                currency={currency}
                viewerMarket={market}
                viewedIds={viewedSet}
              />
            </DiscoveryNearMiss>
          ) : (
            /* B. Nothing in the catalogue comes close. Only now is an email address the honest ask. */
            <DiscoveryWaitlist query={state.q} onReset={() => apply(EMPTY_DISCOVERY_STATE)} />
          )}

      {/* The end of the shelf, as a measurable thing. All three branches above are shelf, and
          everything below this line is the marketing tail -- so this is the last point at which
          "narrow it down" is an offer about what the reader is looking at. Zero-height and
          aria-hidden: it is a coordinate, not content. */}
      <div ref={shelfEndRef} data-testid="shelf-end" aria-hidden="true" />

      <CommandPalette
        packs={packs}
        open={open}
        onClose={close}
        onSeeAll={(q) => apply({ ...state, q })}
      />

      {/* Both portal to <body>, so they sit here at the page root rather than inside the shelf --
          their position in this tree does not decide where they paint, and putting them next to
          the palette keeps every page-level overlay in one place. */}
      {/* WIZARD PATH ONLY. `FilterSheet` renders `StepFlow`, so on the bar path it would be the
          deleted control coming back through an overlay, and `FilterFab` exists to open it. The
          bar's own scroll-back story is the reader scrolling up to a control that is one row tall
          instead of four. */}
      {!flags.filterBar && (
        <>
          <FilterFab
            anchorRef={shelfControlsRef}
            endRef={shelfEndRef}
            state={state}
            open={filtersOpen}
            onOpen={() => setFiltersOpen(true)}
          />
          <FilterSheet
            packs={packs}
            state={state}
            onChange={apply}
            open={filtersOpen}
            onClose={() => setFiltersOpen(false)}
          />
        </>
      )}
    </>
  );
}

/*
 * `MethodCostAnchor` and `ComparisonBlock` used to live here. They moved to
 * `components/marketing/PriceArgument.tsx` on 2026-08-06 and now render on /pricing.
 *
 * Neither was deleted: both are carefully sourced arguments about what the work costs and why it
 * is one payment. Stacked at the bottom of this page they added roughly 4,000px of argument
 * between the shelf and the footer, on a page that already ran ~16,000px. /pricing is the page a
 * buyer opens when the question is "why does this cost what it costs"; the home page's job is to
 * show the product.
 */

export default function Home({ packs, stats, flags, initialState, market, currency, personalised, viewedIds, catalogUnavailable }: HomeProps) {
  // The live "N live now" figure is rendered by <Heartbeat>, which takes `stats` directly, so the
  // duplicate `stats?.listed ?? packs.length` that used to sit here was computed and dropped.
  const { variant } = useCopyVariant();
  /* Every price claim on this page is computed from the packs this render already holds. The
     shelf stopped being one price when the segment ladder shipped (`feat(pricing)` #105/#107);
     see lib/priceRange.ts for the measurement that made each of the four claims below false. */
  const range = priceRange(packs);
  /* The hero's featured product. `packs` arrives newest-first from the server and `sort=Newest` is
     the shelf's default, so this is the same pack the grid shows first -- deliberately, so the
     hero and the shelf cannot disagree about what is newest. It is NOT a second copy of the card:
     the featured slot is `hidden lg:block`, and on mobile the reader simply meets it as the first
     card in the grid. */
  const featured = packs[0];

  /* MASTER-BRIEF section 9. Three page-level beacons, wired here because each is about the page
     rather than about any one component inside it. */

  /* How far down this page readers get. `startScrollDepthTracking` returns its own stop
     function, so leaving the page ends the page view and the next arrival starts a fresh set of
     thresholds rather than staying silent. */
  React.useEffect(() => startScrollDepthTracking(), []);

  /* The waitlist ask was taken. The form is `WaitlistForm`, which /kill-log and /sample render
     too, so putting the beacon inside it would file every page's signups under one name.
     Listening for the submit event here counts only the asks made on this page, and it adds no
     wrapper element to the shelf layout.

     Once per page view. A visitor who submits without ticking the consent box is refused and
     submits again. That is one visitor who asked, not two.

     No meta. `WaitlistForm` already posts a `source` tag that the waitlist ledger stores, so a
     placement written here would be a second copy of one fact, free to disagree with the first. */
  const emailSubmitReported = React.useRef(false);
  React.useEffect(() => {
    const onSubmit = () => {
      if (emailSubmitReported.current) return;
      emailSubmitReported.current = true;
      track('email_submit');
    };
    document.addEventListener('submit', onSubmit);
    return () => document.removeEventListener('submit', onSubmit);
  }, []);

  /* A click on the hero's featured product. The handler is attached to the DOM node rather than
     written as an `onClick` prop because the slot is a plain container: jsx-a11y fails the build
     on a static element with a click handler, and the keyboard path is the card's own link,
     which needs no help from here.

     Only a click that landed on a link counts, so the heading above the card and the padding
     around it are not counted as a click on the product. */
  const featuredSlotRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = featuredSlotRef.current;
    if (!el || !featured) return;
    const onClick = (event: MouseEvent) => {
      if ((event.target as HTMLElement | null)?.closest('a')) {
        track('featured_click', featured.id);
      }
    };
    el.addEventListener('click', onClick);
    return () => el.removeEventListener('click', onClick);
  }, [featured]);

  /* THE KILL TOTAL IS STATED ONCE ON THIS PAGE, in the proof strip below the hero. It was in
     `HeroEvidenceStrip` as well until 2026-08-13, which put "1,364" and an identically-worded
     "Read the kill log" link at y=735 and again at y~1180 of the same 1440x900 screen. The strip
     is the copy that stayed because it is the only one a phone ever reaches: `HeroEvidenceStrip`
     is `hidden md:block` and `KillGrid` is desktop only.

     The old rule still stands and is the reason the number is not typed anywhere: every surface
     reads `kill-log-totals.json` or `RESEARCH_STATS`, never its own copy, because a "1,168 killed"
     figure duplicated across components is exactly how one of them goes stale. */
  return (
    // One drawer for the whole shelf. Inside MarketingLayout so the drawer's own Modal renders
    // above the header, and so a card anywhere on the page can reach it without prop threading.
    <BuyDrawerProvider currency={currency}>
    <MarketingLayout>
      <Seo
        // DISTINCT FROM THE H1 (founder review, 2026-08-16, item 4). "survived a filter built to
        // kill them" moved to the H1 below because it read stronger there; leaving the same
        // string here would make the browser tab and the page heading identical, which is also
        // how the two Mumchimp tabs (this page, `/ideas`) looked alike next to each other. This
        // line keeps the tab identifiable by its first few words even before the H1 loads.
        title={`Sourced business ideas, priced and ready to build${
          range ? `, ${range.uniform ? range.label + ' each' : 'from ' + formatGbp(range.min)}` : ''
        }`}
        /* The catalogue as structured data. The shelf below is filtered and sorted in the browser,
           so what a crawler keeps is whatever the server happened to send; this block states the
           full list once, in order, with a real URL per pack. It is also the single cheapest thing
           on the site for an assistant to quote when asked what Mumchimp currently sells. */
        jsonLd={graph(
          itemListNode(
            packs.map((pack) => ({ name: pack.title, path: `/pack/${pack.id}` })),
            'Business opportunity packs',
          ),
        )}
      />

      {/* 1. HERO, deliberately short enough that the shelf starts above the fold.
             It was 606px tall at 1280x720 (measured), which put the first pack card at y=1094:
             a storefront whose entire argument is "here is what survived" opened on an argument
             and no product. Nothing here was deleted outright, the long pitch paragraph is the
             "What you get for £49" section further down, and the trust pills restate the
             guarantee that also sits under the grid. What is left is the claim, the price, and
             the two doors. `e2e/discovery.spec.ts` asserts the resulting fold position, so the
             next block added above the grid fails a test instead of quietly undoing this. */}
      {/* width="7xl" to match the catalogue Section immediately below. It was "6xl" (1152px) while
          the shelf was "7xl" (1280px), so the hero's left edge sat 64px inside the grid's on any
          viewport past 1280px: the headline and the first pack card did not line up, which reads
          as a broken column rather than a deliberate one. The narrower editorial sections further
          down are a separate, intentional rhythm; these two are stacked and must share an edge. */}
      {/* Left-aligned at EVERY breakpoint (brand v3, 2026-08-06). The `text-center md:text-left`
          that used to be here centred the headline, the 64ch paragraph and the CTA on mobile --
          and text-align inherits, so it also centred every row inside the filter-log card below
          it, turning a log into ragged decoration. A centred paragraph gives each line a
          different starting x, which the reader's eye has to re-find on every line. */}
      {/* The short-viewport override is a HEIGHT query, not a width one, because the thing being
          protected is a height budget. At 1280x720 (Playwright's Desktop Chrome, and a real 720p
          laptop) the header + this band + the catalogue's own heading block put the first pack card
          at y=727 against a 720px fold: on an ecommerce home page the product was entirely
          off-screen. Width breakpoints cannot express that, and the previous answer -- capping the
          h1's measure, see the comment on the h1 below -- bought 1.5px of clearance, which is not a
          margin, it is a coincidence. Trimming 56px of band padding on short screens only leaves
          tall displays with the generous hero and puts the shelf back on the first screen. */}
      <SectionBand
        bg="white"
        width="7xl"
        // `band_view` (MASTER-BRIEF section 9). The hero is the band every visitor should reach,
        // so its count is the baseline the bands below it are read against.
        bandId="home-hero"
        // The mobile padding is `pt-8 pb-8`, not `pt-10 pb-12`. Moving the filter-log panel below
        // the shelf (see the note there) put the first card at y=728/753/689 on the three phone
        // sizes measured, which clears the 40px-visible bar at 390x844 and 430x932 but left only
        // 27px at 360x780 -- the h1 takes one more line at that width. 24px of band padding is
        // the difference between a card you can see and a sliver. `md:` is untouched, so nothing
        // above a phone gets tighter.
        // `animate-settle`, not `animate-rise`: this band holds the h1, which is the page's
        // LCP element, and `rise` fades from opacity 0 -- which made LCP 1940ms against a
        // 328ms first paint (F-005). See the keyframes note in `tokens.css`.
        // NO BAND PADDING ON DESKTOP, because `.hero` already carries its own. The shipped
        // stylesheet sets `.hero{padding:52px 0 44px}` (`mumchimp.css:274`), and `md:pt-14`
        // added another 56px on top of it. Measured at 1280, drawing against built page:
        // the hero grid started at y=103 in `mockups/index.html` and y=159 here, the right-hand
        // panel at y=155 against y=211, the h1 at y=297 against y=353. Every row exactly 56px
        // low, which is `pt-14`. `md:pb-16` was the same mistake at the other end. The two
        // `[@media(max-height:820px)]:md:*` overrides went with them: they existed to claw back
        // padding on a short laptop screen, and there is none left to claw back.
        // The PHONE padding is untouched on purpose. `pt-8 pb-8` there was set by measuring
        // where the first shelf card landed at 360x780, 390x844 and 430x932, and the drawing's
        // own media query drops `.hero` to `padding:36px 0 32px` below 900px anyway.
        className="animate-settle pt-8 pb-8 md:pt-0 md:pb-0"
      >
        {/* Two columns on lg+: the claim on the left, the evidence for it on the right. The
            filter-log card is the argument -- it is the only thing above the fold that a
            sceptical stranger can check. */}
        {/* The `relative` wrapper and the `z-10` on the row below are the last of the positioning
            scaffolding that `AmbientKillColumn` needed (it was `absolute inset-y-0 right-0 z-0`
            behind this row). The column is gone -- see `KillGrid` in the right-hand slot for what
            replaced it and the measurement that condemned it -- and the stacking context is kept only
            because the featured card's opaque fill still relies on it. */}
        <div className="relative">
        {/* `1fr 380px` at a 48px gap, which is `mockups/index.html`'s `.hero` exactly. The right
            column was 420px, so the kill grid drew 40px wider than the drawing and the headline
            column 40px narrower. */}
        <div className="hero relative z-10">
          <div className="w-full min-w-0">
            {/* Mono because both halves are quantities. This replaces an uppercase
                `tracking-[0.2em]` eyebrow -- letterspaced small caps is the single most dated
                device on the page, and it was applied to the price, which is the one thing a
                buyer wants to read at a glance. */}
            {/* NOT mono, and no longer says "live".
                Mono is this site's evidence voice -- it means "this is a checkable quantity".
                Applied to the price it made the single most commercial line on the page read as
                terminal output, which is precisely the "built by an engineer, for engineers"
                signal the shelf could not afford.
                "63 packs live" was insider jargon: `live` is a word about our deployment state,
                not about the buyer's choice. A shop says how many things are on the shelf. */}
            {/* "IN THE CATALOGUE", NOT "TO CHOOSE FROM" (2026-08-14, founder review). `packs.length`
                is every listed pack in every market, before any filter -- the largest of the four
                counts this page prints, and the one a reader meets first, so it is the one that
                sets their expectation for the three below it. "62 packs to choose from" promises a
                choice of 62 on the shelf they are about to scroll, and the shelf shows the reader's
                own market first (~45 of them) with the rest under a divider further down. Naming
                the population it counts is the whole fix: the toolbar states how many match, the
                market line states how that splits, the show-more button states the remainder of one
                market. Four numbers, four nouns, and the arithmetic between them now reads. */}
            {/* THE DRAWING'S `.kicker`: mono, 13px, `--ink-3` (`mockups/index.html`). It was
                sans at 14px in `--ink-2`. The 2026-08-14 note below took mono OFF this line
                because mono read as terminal output on the most commercial line of the page;
                the founder's instruction of 2026-08-18 is that the page match the drawing, and
                the drawing sets mono here. Both halves of the line are quantities -- a price and
                a count -- which is the declared scope of `monoIsTheDataVoice.test.ts`. */}
            <p className="kicker num">
              {range ? (range.uniform ? `${range.label} each` : `From ${formatGbp(range.min)}`) : 'One payment'}
              {` · ${packs.length} packs in the catalogue`}
            </p>
            {/* The cap is in rem, NOT ch, and that is the whole point. `ch` is the advance width of
                "0", so it means a different number of pixels in every font: the old max-w-[24ch]
                measured 576px in SF Pro but 819px in Verdana. That made the headline's line count
                a function of which font the platform happened to pick, so macOS landed on 2 lines
                and CI Linux on 3, putting the first card 1.5px above the fold. 56rem clears every
                measured fallback. Geist is loaded and applied now, so the platform no longer gets
                a vote, but the absolute cap stays and stays the thing under test. */}
            {/* THE DISPLAY CUT IS `lg:` ONLY, and that is a fold decision, not a taste one.
                Up to `md` this page is ONE column: the headline sits directly above the shelf, so
                every pixel the type grows pushes the first product down, which is the budget the
                comments above were written to protect. At `lg` the layout becomes two columns and
                the product moves into the right-hand slot BESIDE the headline, so its y-position
                stops depending on the headline's height entirely. The 48px-to-96px step therefore
                costs the measured 1280x720 fold nothing, because at that width the thing being
                protected is no longer underneath.

                THE 96px STEP IS GONE (2026-08-08, §3.2). `lg:text-mega` was a seventh size on a
                six-size scale; the hero is --text-display and nothing else, and that token now
                carries its own mobile size as a clamp, so the whole responsive ladder collapses to
                one class.

                --text-display IS NOW 72px AT THE DESKTOP END, not the 48px this comment described
                until 2026-08-14, and the fold argument above is what makes that affordable rather
                than a reversal of it: the retune only bites at `lg`, where the headline no longer
                sits above the product. The clamp is `clamp(2.25rem, 1.2rem + 4vw, 4.5rem)`, so the
                one-column widths this paragraph is about still set 36px and the measured fold is
                untouched. Anything that reads a fixed px out of this comment is reading a stale
                number; `tokens.css` is the declaration and `storefrontDesignContract.test.ts`
                is what holds it.

                The 44rem cap went with it. It existed because 96px in an 812px column fits about
                17 characters, so 56rem would have set ragged three-line display text. 72px in the
                two-column slot this cap applies to (`md:` and up) reads as an ordinary measure,
                and the tighter cap would just make the headline wrap early for no reason. */}
            {/* NO `font-semibold`. It was on this h1 and it was INERT, which is worth a line
                because the reason is not local to this file: `globals.css` is unlayered, so its
                `h1, h2, h3 { font-weight: 560 }` beat the utility Tailwind emits into
                `@layer utilities` no matter what was written here. The heading takes its weight
                from the scale token (`--text-display--font-weight`, 660) via the
                `:is(h1,h2,h3).text-display` rule added alongside that fix. A class that does
                nothing is worse than no class: it reads as the answer to "what weight is this?" */}
            <h1>
              {/* THE FOUNDER'S LINE, 2026-08-18, given verbatim: "Business ideas with the
                  research and starter packs ready." The founder gave it twice that day, the
                  second time trimming "already done" to "ready"; this is the second, final
                  wording. It replaces "Business ideas that survived a filter built to kill them",
                  which was itself promoted from the page `<title>` on 2026-08-16. Read the round
                  trip before changing it again.

                  What the new line does that neither predecessor did: it names the DELIVERABLE.
                  "Survived a filter built to kill them" is a claim about our process, and a
                  visitor who has never heard of us has no reason to care how hard our filter is
                  until they know what arrives when they pay. "The research and starter packs
                  ready" says what is in the box. The filter claim is not lost -- it is the
                  sub, the kill grid beside it, and the page `<title>`, all of which still lead
                  with it.

                  ONE STRING, NO HAND BREAKS. The previous line carried two `<br className=
                  "md:hidden" />` chosen from Playwright measurements of three specific word
                  groups at 390px and 640px. Those measurements are about words that are no longer
                  here, so keeping the breaks would have split this sentence at points nobody
                  measured. `text-balance` wraps it evenly at every width, and at the display
                  token's 33px mobile size (`clamp(2.0625rem, 6vw, 3.375rem)`) there is room for
                  it to. `max-w-[14ch]` is the mockups' own cap on `h1`. */}
              {/* RESTORED TO THE MOCKUP'S OWN SENTENCE, 2026-08-18, on the founder's fix
                  prompt: "The homepage H1 must be exactly: Business ideas with the research
                  already done." That is `mockups/index.html:295` verbatim. The block above
                  records a verbal given earlier the same day ("...and starter packs ready");
                  the written fix prompt is later and names the live string as the defect, so
                  the mockup wins. `max-w-[14ch]` is `mockups/index.html:70`'s own `h1`
                  max-width, not the 12ch the prompt cites; the drawing is the specification. */}
              {SITE_COPY.heroH1}
            </h1>
            {/* Shown on mobile too. This was `hidden sm:block`, so a phone got the headline, then
                a CTA, then a ~120px void where the explanation should be. */}
            {/* `.hero .sub`: 17.5px at 1.55, capped at 44ch (`mockups/index.html`). It was
                `text-body` (16px) at 56ch, so the line was smaller and ran 12 characters wider
                than the drawing, which is why the hero read as a paragraph rather than a
                standfirst. */}
            <p className="sub">
              {variant.globalHookDescription}
            </p>
            {/* The hierarchy INVERTS here. The shelf was previously the thing you had to scroll
                past an orange "Read a free report" slab to reach: the primary action on a shop is
                the shop. The sample is the risk-reducer, so it is the quiet link beside it. */}
            <div className="cta-row">
              <Link className="btn" href="#catalog">
                Browse the packs
                <Icon name="arrowRight" size={16} />
              </Link>
              <Link
                href="/sample"
                onClick={() => track('sample_cta_clicked')}
                className="tlink"
              >
                {/* ONE LINE, IN THE LINK. This was a link ("Read a free sample") over a caption
                    ("A whole report, free. No payment, no email."), which restated "free" twice
                    and then answered a question nobody had asked twice more. It then became a
                    short link over a three-word caption, which is still two elements for one
                    offer: a reader scanning the hero has to assemble the sentence from a link and
                    a line of grey text below the button row. The offer and the friction it removes
                    are one thought, so they are one clickable string. */}
                {/* THE DRAWING'S OWN SENTENCE. `mockups/index.html:299` sets this link as an
                    em dash and no full stop, because a link never ends in one. The trailing
                    arrow is gone with the full stop: the drawing's `.tlink` is text only, and
                    the glyph was wrapping to a line of its own at 390px.
                    The opt-out pragma has to sit on the SAME line as the character it exempts
                    (`src/__tests__/dashFree.test.ts:68` tests `line.includes(IGNORE)`), so it
                    leads the text node below rather than this comment block. It renders
                    nothing. */}
                {SITE_COPY.sampleLinkHero}
              </Link>
            </div>
            {/* The kill log, DEMOTED to one line.
                It used to be a 420px panel in the right column, listing three named dead ideas
                behind red crosses -- so the first colour a stranger met on the page was failure,
                and the largest object beside the headline was a list of things we do not sell.
                The number is the credible part and it survives here intact; the three corpses do
                not need to be above the fold to make it true. */}
            {/* `packs.length`, NOT `passedTotal`. The eyebrow directly above says "63 packs to
                choose from" and this line said "...before these 145 made the shelf": two counts of
                the same shelf, 82 apart, 300px apart, with no explanation. Both were true --
                145 have ever passed, 63 are listed today -- but a stranger reads the pair as an
                arithmetic error on a page whose entire pitch is "we check our numbers", which is
                the same self-inflicted wound as the "7 of 8 checks" line. One shelf, one count. */}
            {/* `hidden md:flex`. This exact sentence, with the same two numbers, is the panel
                directly below the shelf at every width -- so on a phone it was 110px of the first
                screen spent restating something the reader meets again 800px later, and it was the
                last thing standing between the fold and a product. Kept on desktop, where the hero
                is two columns and the line costs nothing that a card wanted. */}
            {/* THE DOSSIER, PROMOTED. What stood here was a single line restating the kill total
                and linking to /kill-log -- an assertion about how much checking happens, made
                entirely in adjectives, on the one screen that had room to prove it instead. The
                full dossier panel was 80% down the page, below the whole shelf.

                `HeroEvidenceStrip` replaces the sentence with the artefact: eight real verdicts from
                `sample-report.json`, one of them a failure, and four live source domains a
                stranger can click before they trust a single word on this page. The kill total is
                not lost, it moved INSIDE that component, where it sits next to the failed check
                it is evidence for.

                `hidden md:block` is kept from the line it replaces, for the same reason: on a
                phone this is the last object between the fold and a product. */}
          </div>
          {/* THE SIGNATURE DEVICE (MASTER-BRIEF §7, `mockups/index.html`). Every idea the
              engine has researched, one square each, with the shelf in teal and every teal square
              a link to its pack.

              IT TOOK THE HERO'S RIGHT COLUMN FROM THE FEATURED PACK, AND THE PACK DID NOT GO. It
              moved to a band directly under this row, which is the slot `PopulationField` used to
              hold. The brief gives each page one signature device and puts this one here; the
              product is still on the first screen on any display tall enough to have shown the
              old population band, one scroll-free row lower.

              THE OLD DOM-ORDER ARGUMENT DOES NOT APPLY TO IT. `PopulationField` had to sit after
              this row because it was ~1,400 elements and the h1 is this page's LCP element. The
              grid is one `<path>` plus one `<rect>` per listed pack -- around fifty nodes -- so
              there is nothing to defer. */}
          {/* HIDDEN BELOW 901px, WHICH IS THE STYLESHEET'S OWN HERO BREAKPOINT, NOT A GUESS.
              `mumchimp.css:432` is `@media(max-width:900px){.hero{grid-template-columns:1fr}}`:
              below 901px the hero stops being two columns and this figure stacks UNDER the
              headline instead of beside it. Measured on live mumchimp.com at a 400px viewport on
              2026-08-19: `figure.gridwrap` is 550px tall, the hero band is 1070px, and the first
              visible pack card sits at y=1288 -- a shop whose home page opens with no product on
              screen on every phone size we test.

              This is the gate `PopulationField` carried (`hidden [@media(min-height:821px)]:lg:block`)
              and that the redraw did not carry over when this component took its slot. The number
              is 901 rather than Tailwind `lg:` (1024px) so the figure appears exactly when the
              stylesheet gives it a column to appear in; `lg:` would leave 901-1023px drawing a
              two-column hero with an empty right side.

              It is a utility class, so `scripts/parity.mjs` is unaffected -- it compares tag names
              and mumchimp.css classes only, and the element stays in the DOM either way. */}
          <HeroRatio packCount={packs.length} className="hidden min-[901px]:block" />
        </div>
        {/* THE PRODUCT, not the filter log.
            What stood here was `LiveKillCard` -- the killed/survived ledger. Beside a headline
            promising researched business ideas, the largest and only coloured object on the
            first screen was three ideas we had thrown away. A shop's first screen shows the
            thing you can buy.

            Desktop only, and there is no mobile duplicate any more: the whole `hidden lg:block`
            / `lg:hidden` pair is gone, because the reason it existed was to place a panel that
            is no longer in the hero.

            `featured.id` is handed to the shelf so this card and the shelf's "Newest survivors"
            row cannot show the same pack at the same time -- they did, on the first screen at
            1440x900, until the row was made breakpoint-aware (see `rowHasFeatured`). On mobile
            this slot is not rendered and the pack is simply the first card in the grid. */}
        {featured && (
          /* `relative z-10 bg-surface` was added because this slot sat directly over
             `AmbientKillColumn` (`absolute inset-y-0 right-0 z-0`): the card itself is opaque
             (`bg-surface`, see `PackSpotlight`), but the heading above it and the
             padding around it were not, so ticker text rendered legibly through the gap --
             "...Builder  The value would n[ot last]" sitting directly above "New this week"
             (ss_0456bw1wg, live mumchimp.com/, 2026-08-09). That column is gone, so nothing
             shows through any more; the fill stays because `--surface` and `--bg` are the same
             white (tokens.css:80,81) and removing it would be a no-op edit on a card whose
             background is otherwise inherited from whatever band it is dropped into. */
          <div
            ref={featuredSlotRef}
            /* NO CARD CHROME ON THE WRAPPER. `PackSpotlight` is the drawing's `.featured` article now,
               which carries its own surface, hairline and 12px radius; a `rounded-card bg-surface
               p-4` parent around it draws a second card 16px outside the first. */
            /* FULL WIDTH, NO 420px CAP. The drawing's `article.featured`
               (`mockups/index.html` section 7) is 1040px wide -- the whole content measure --
               and ours was capped at 420px while sitting in a full-width row of its own.
               Measured at 1280 on 2026-08-18: the card drew x=120..540 in a band running
               120..1160, so 620px to its right was empty, and the founder read the result as
               a hole in the page. `.featured`'s own CSS is written for the full measure, so
               removing the cap is what makes the card the drawn object rather than a
               narrow copy of it. */
            className="relative z-10 mt-10 hidden w-full lg:block"
          >
            {/* Sentence case, and the same `text-meta font-semibold` as every other row heading
                on the shelf below. It was `uppercase tracking-wide text-caption`, which the
                house policy forbids (`__tests__/weightAndCasePolicy.test.ts`): CSS caps leave
                the accessible name in sentence case while a screen reader may spell out the
                rendered form, and this label sits directly above the one product on screen. */}
            <h2 className="mb-3 text-meta font-semibold text-text">
              New this week
            </h2>
            <PackSpotlight
              pack={featured}
              currency={currency}
              viewerMarket={market}
              viewed={viewedIds.includes(featured.id)}
            />
          </div>
        )}
        </div>
      </SectionBand>

      {/* THE SOURCE STRIP (`mockups/index.html:304`, `.srcstrip`).

          It used to render INSIDE the hero's left column, capped at 46rem. At that measure four
          source pills and the "See the whole thing" link did not fit on one line, so the row
          wrapped and read as two rows of chips. The drawing puts this on its own full-width
          section directly under the hero, at `padding:20px 0 24px`, which is why its four chips
          and its link sit on one line.

          `hidden md:block` is carried over from where it stood, for the reason recorded there:
          on a phone this is the last object between the fold and a product. */}
      {/* HIDE THE BAND, NOT JUST WHAT IS IN IT. `hidden md:block` sat on the strip alone, so on a
          phone the SectionBand still rendered: an empty 45px block with a background and a
          `border-b`, measured at 390 on the built page at y=1264, exactly where the drawing has
          the 224px source strip. An empty ruled band reads as a broken section. The control now
          sits on the outer `<section>`, so the whole band leaves the page below `md`. */}
      <SectionBand bg="bg" width="7xl" className="!pt-5 !pb-6" outerClassName="hidden md:block">
        <HeroEvidenceStrip />
      </SectionBand>

      {/*
        PROOF STRIP, POSITION 2.

        The email's spec puts the kill total here, right under the hero, so the strongest stat
        the shop owns -- the survival rate -- is on the first screen rather than buried at the
        bottom of /how-it-works (where it lived until this pass). Every number is read from
        `RESEARCH_STATS`; nothing here is typed, so a future batch that changes the totals
        updates the page with it.

        The strip states no survivor count. It used to, and then it spent a week explaining why
        that number is bigger than the shelf. The founder cut the figure on 2026-08-13: what is
        left is the research total, the kill count, and a link to the receipts.

        The link is the action the strip earns: the kill log is the receipt behind the strip,
        and a curious reader is one click from it. The "Every idea is checked" section below
        used to do this work too; it now stops repeating the same total and just describes the
        method.
      */}
      {/* THE PHONE FOLD IS A HEIGHT BUDGET, AND THIS STRIP IS 233px OF IT (F-001).
          Measured on the built tree at 3be12ca by `scripts/design-audit/measure-fold.mjs`: the
          first pack card sat at y=937 with the fold at 780/844, so a shop's home page opened
          with no product on screen at 360x780 (-157px) and 390x844 (-93px), and cleared
          430x932 by only 57px.

          The budget above the card, measured, not guessed: header 65 + hero 379 + THIS STRIP
          233 + catalogue heading 29 + pricing line 31 + search toolbar 92 + sector chips 36.
          The strip is the single biggest block that is not the hero and not the shelf's own
          controls, and it is the only one that is pure argument -- every other block is either
          navigation or the shelf itself.

          So it moves below the shelf on phones and keeps its spec position from `sm:` up, via
          `order` on a flex wrapper. ONE DOM node, no duplicated copy: rendering it twice behind
          `hidden`/`block` would put the same two numbers in the document twice, which is a
          screen-reader defect and a copy-drift risk for a section whose whole job is that its
          numbers are trustworthy.

          Shrinking instead was measured and rejected in the original audit: dropping the second
          paragraph and tightening padding recovers ~90px of the ~197px needed at 360.

          NOTE FOR WHOEVER ADDS THE NEXT BLOCK HERE: this is additive. Anything else placed
          above the shelf spends the same budget, and `measure-fold.mjs` is the check --
          `e2e/discovery.spec.ts` only runs at 1280x720 and physically cannot see it. */}
      <div className="flex flex-col">
      <Section bg="bg" width="7xl" outerClassName="order-1 sm:order-none" className="!py-10 md:!py-12">
        {/* THE SPLIT (`mockups/index.html:322`, `.split`): one bordered card, two equal cells,
            a 1px line between them, `padding:22px`. What stood here was a single prose line and
            a link, floated apart on one row. The drawing gives each number its own cell, its own
            label and its own route out, which is why a reader can take in both counts without
            reading a sentence.

            THE COPY SAYS "every check we ran", NOT the drawing's "all six checks".
            `fixedCheckCount.test.ts` refuses a bare cardinal next to a checks-noun: the number of
            checks a pack ran is not fixed, and this page has already paid for printing one as if
            it were.

            THE LEFT FIGURE IS THE SHELF COUNT, NOT THE SURVIVOR COUNT. The drawing prints "68
            survived" there; `lib/stats.ts` does not export that number and will not
            (founder directive, 2026-08-13), and this page has already been wrong three ways
            printing it. `packs.length` is what is listed today, it is the number the hero prints
            two rows above, and it is the only one of the two a buyer can act on.

            THE LABELS ARE NOT MONO, NOT UPPERCASE AND NOT LETTERSPACED, all three of which the
            drawing sets. Case and tracking are refused by `weightAndCasePolicy.test.ts`: CSS caps
            leave the accessible name in sentence case while a screen reader may spell the
            rendered form out. Mono is refused by `monoIsTheDataVoice.test.ts`, whose audit is
            explicit that a WORD under a tally is a label and only the FIGURE is data. The
            figures above them keep their tabular numerals.

            THE RESEARCH TOTAL IS STILL HERE, in the right cell's sentence. It has to be: on a
            phone `KillGrid` is not rendered and this strip is the only place the total appears
            at all. */}
        <div className="split">
          <div>
            <p className="lbl">Available now</p>
            <b className="n num">
              {packs.length}
            </b>
            <p>
              {/* The drawing says "Passed all six checks". The number of checks varies by
                  idea, so `fixedCheckCount.test.ts` refuses a closed count in shipped copy.
                  The drawing's second sentence stands as written. */}
              Passed every check they faced. Every claim sourced, every number traceable.
            </p>
            <Link
              href="#catalog"
              className="tlink"
            >
              Browse the catalogue
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
          <div>
            <p className="lbl">Researched, not listed</p>
            <b className="n num">
              {RESEARCH_STATS.killed.toLocaleString('en-GB')}
            </b>
            <p>
              {`We have researched ${RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas. ${killsSummary()}, and the evidence behind it.`}
            </p>
            <Link
              href="/kill-log" prefetch={false}
              className="tlink"
            >
              Read the kill log
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
        </div>
      </Section>

      <div id="catalog" className="scroll-mt-20" />
      {/* `!border-b` pins a border this band already had. `SectionBand` carries
          `last:border-b-0`, and the flex wrapper introduced above makes this the LAST child of
          its parent for the first time -- so wrapping it would silently delete the divider
          between the shelf and the section below, on every viewport, as a side effect of a
          mobile-only fold fix. `:last-child` is DOM order, not flex order, so this holds at
          both breakpoints. */}
      {/* `bg="surface3"` (was `bg`): the shelf's ground, so 57 white cards read as paper on a
          gutter instead of as hairline outlines on the same white as the page. See the tone's
          note in blocks.tsx for why the tint goes UNDER the cards rather than on them. */}
      <Section bg="surface3" width="7xl" outerClassName="!border-b" className="!pt-2 !pb-[calc(4rem+env(safe-area-inset-bottom,0px))] md:!pt-3 md:!pb-20">
        {/* THE SHELF HAS A NAME AT EVERY WIDTH NOW.
            This block was `hidden sm:block` outright, to buy fold budget on a phone. What that
            actually bought was a phone reader going from the hero's last line straight into a
            bare search field and a row of chips, with no statement of what is being searched --
            the one screen where the brand's whole claim ("these are the ones that survived") had
            to be inferred from the placeholder text of an input.

            The trade is taken at the level of the PARAGRAPH, not the heading: mobile gets the
            heading, desktop additionally gets the two sentences under it. A heading is ~30px and
            names the section; the paragraph is ~60px and repeats what the panel below the shelf
            already says at every width.

            The copy rewrite cut the paragraph from 67 words to 22 and dropped `hidden sm:block`
            with it, which reversed the split above while leaving this comment standing -- the code
            and its stated reason disagreed. Restored, because shortening the sentence does not
            answer the reason it is hidden: the redundancy against the panel below survives the
            cut, and the measurement that set the split is on record while nothing measures the
            new state. If mobile should get the paragraph, that is a fold measurement to take, not
            a side effect of an edit to the wording. */}
        <div className="mb-4 sm:mb-6">
          {/* THE CATALOGUE INTRO (email §1).
              The email replaces the 67-word version with a 22-word line that does the whole job:
              it states what every pack is (same `PACK_DOCUMENTS.length` documents, COUNTED not
              typed -- see below), why prices differ (opportunity size,
              not download size), and where to read the longer version (/pricing). The kill-rate
              line is not here because the proof strip above the shelf already carries it -- this
              sentence is the SHOP intro, not the FILTER intro. */}
          {/* `text-h1`, which is this site's 24-32px step and the drawing's `h2.sec`
              (`font-size:clamp(24px,4.6vw,32px)`). It was `text-h2`, the 19-23px step, which is
              the drawing's `h3.sub` -- so every section heading on this page sat one step below
              the drawing and the page read flat. */}
          <h2 className="sec">What survived</h2>
          {/* The pricing sentence that used to sit here is GONE, and its removal is the fix for a
              measured defect rather than a trim for length. It was `hidden sm:block`, so from
              640px up the page stated one fact twice, ~14px apart, under the same heading, with
              the same "Why prices differ" link to the same /pricing page: this paragraph, then
              `CatalogBrowser`'s at :1107. Measured on production 2026-08-08 at 1440x900 -- both
              rendered; at 360 only :1107 did, which is why a phone-only read never showed it.

              :1107 is the copy that survives, not this one, because SITE_SPEC_PROGRAM.md 6.1
              pins its exact wording ("Same 8 documents in every pack. Bigger opportunity, higher
              price.") and it is the one a phone already sees. Site spec 5 is the rule broken:
              say each thing once, sitewide. Twice on ONE screen is the loudest version of it. */}
        </div>

        <CatalogBrowser packs={packs} flags={flags} initialState={initialState} market={market} currency={currency} personalised={personalised} viewedIds={viewedIds} featuredId={featured?.id} catalogUnavailable={catalogUnavailable} />
      </Section>
      </div>

      {/* THE FILTER LOG (`LiveKillCard`) IS REMOVED FROM THIS PAGE (founder, 2026-08-14). It is not
          deleted from the codebase and this note is the record of what it was and why it earned a
          place here for as long as it did.

          WHAT IT WAS: a bordered panel below the shelf, headed by a mono chip reading
          "<killed> killed" (`LiveKillCard.tsx:146`) over three real dead ideas with the check that
          killed each, read from the same `kill-log.json` / `kill-log-totals.json` that /kill-log
          renders, so the two could never disagree.

          THE ARGUMENT THAT PUT IT HERE, and it was a good one: it is a claim a sceptic can check
          without leaving the page. It also had a placement fight behind it -- it was `lg:hidden`
          here and the hero's right column on desktop, and both were the same mistake at different
          breakpoints, because the first thing a stranger met was an argument with nothing for sale
          in view. Measured on the built page before that move:

            hero text   y=105  h=425   ends 530
            gap-10              40
            filter log  y=570  h=274   ends 844   <- the whole 844px viewport, before any product
            first card  y=1042                    -> 1.23 screens down (390x844)
                                                     1.37 (360x780), 1.08 (430x932)

          WHY IT GOES ANYWAY: the number of killed ideas was stated FOUR times on one scroll. This
          panel's chip was one of them, and it is the copy with the least context around it -- a bare
          count in a chip. The one that survives is the proof strip under the hero, which states the
          research total and the kill total in one sentence, says in the line under it that the kills
          are published with their reasons, and carries the only "Read the kill log" link on the
          page. Everything this panel showed is on /kill-log, one click from that link, in full
          rather than three at a time.

          The two remaining statements are NOT in this file's gift and are flagged rather than
          silently left: `TrustGuaranteesRow` hardcodes "<killed> ideas were killed to list these
          <live>" at `TrustGuaranteesRow.tsx:117` with no prop to suppress it, and the row itself is
          load-bearing for a different reason -- it is the page's single canonical statement of the
          purchase terms. `KillGrid` states the kill total only inside the SVG `<desc>` that
          describes the picture to a screen reader, never in visible text, and its own docblock
          records that the visible arithmetic was deliberately removed for exactly this reason. */}

      {/* 3. ONE REAL PACK, SHOWN. Format ambiguity is the biggest killer on a digital download
             page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      {/* "What you get, at every price" IS GONE. The manifest under it is not, and the difference
          is the whole point of §5.3.

          Two sections used to argue the same thing here. The first was an essay about the ladder:
          which rung a pack lands on, why £29 and £199 buy the same documents, what the ambition
          tier and the market offset do -- that is /pricing's fact, and it is now one line above the
          shelf ("Same {PACK_DOCUMENTS.length} documents in every pack...") plus a link. The second,
          `PackContentsSection`, is the manifest, and §5.3 names THIS page its owner: the buyer's
          "what do I actually get for £49" is answered where they meet the price, not one click
          away. /pricing keeps bare filenames only; a pack page lists its own.

          Recorded because it was got wrong once: on 2026-08-07 two concurrent sessions each
          deleted one of these two sections, neither knowing about the other, and the manifest
          left the page entirely -- a fact with a named owner ended up stated nowhere. If you are
          about to delete this again, the section you want is the pricing essay, and it already
          went. */}
      <Section
        bg="white"
        width="7xl"
        className="!py-10 md:!py-20"
      >
        {/* The three-pill row that stood here is GONE, not restyled. It rendered
            "one payment / 14-day money back / every claim sourced" -- the same three facts, in the
            same order, that `TrustGuaranteesRow` renders 600px further down, and that row's own
            docblock claims to be the page's single canonical statement of the purchase terms
            ("the buyer who scans the page from top to bottom sees the trust once, definitively").
            It was not once: the money-back promise appeared four times on one scroll and the
            sourcing promise six, which is what makes a page read as though it is trying to
            convince you rather than sell you something. One statement, in the row that says it
            is the statement. */}
        {/* THE ORDER INVERTS HERE, and that is the point of the section.
            It used to be the manifest first and `EvidenceRecordPanel` under it: a list of nine
            titles, then a web table of eight verdicts. Both were CLAIMS about what a buyer
            receives, and the founder's verdict on the pair was "underwhelming... show not tell".
            So the object goes first and the inventory goes under it -- you show someone the page,
            then tell them how many more there are.

            `EvidenceRecordPanel` is GONE from this page, not merely reordered. It rendered these
            same eight verdicts under the eyebrow "A real page from a real pack" while looking like
            a web table, so it made the specimen's claim and could not back it; keeping both would
            put two evidence objects 200px apart, which is the duplication this pass exists to
            remove. Nothing is lost -- the record's SHAPE is still in the hero
            (`HeroEvidenceStrip`) and its full CONTENT is on /sample, where this section's only
            call to action points. */}
        <PackSpecimen />
        {/* The manifest, DEMOTED to what it is: the contents page, read after the specimen rather
            than instead of it. It stays on this page and stays owned by this page --
            `__tests__/factOwnership.test.ts` pins Home as the owner of `<PackContentsSection`, and
            on 2026-08-07 two concurrent sessions each deleted one of this section's two halves and
            the manifest left the site entirely. The heading changes because its job changed: it is
            no longer the answer to "what am I buying", it is the answer to "what else is in
            there". "The full contents" and NOT "the other eight documents", which was the first
            draft of this heading: the specimen shows a page of one of the nine, but the list below
            still lists all nine, so a heading that subtracted the one shown would have been an
            arithmetic claim its own list contradicts. */}
        {/* THE DRAWING'S HEADING AND LEDE (`mockups/index.html:564`). This read "The full
            contents" with no lede, which names the section by its position in the page rather
            than by what it gives the reader. Founder, 2026-08-18: use the mockup's version. */}
        <PackContentsSection
          className="mt-16 border-t border-border pt-12"
          heading="What you actually get"
          lead="The same fourteen documents sit inside every pack, whatever it costs."
        />
        {/*
          `MethodCostAnchor` and `ComparisonBlock` were REMOVED from the homepage (2026-08-06) and
          are not deleted -- both are cited, carefully-sourced arguments, and both belong to
          /pricing, which is the page a buyer opens when the question is "why does this cost what
          it costs". Stacked here they added ~4,000px of argument between the shelf and the
          footer, on a page that already ran ~16,000px. The homepage's job is to show the product.
        */}
      </Section>

      {/* 4. THE METHOD, in one light band. This was a near-black full-bleed section with white
             `font-bold` headings and four glassy `bg-white/5` pills -- the single loudest surface
             on the site, arguing for a filter, below a shelf whose cards had just stated the same
             six checks in mono. Light, bordered, one column of argument. */}
      {/* No explicit `border-y` here any more. `className` on `SectionBand` lands on the INNER,
          max-w-7xl-and-centred div (blocks.tsx:48), while the band's own outer `<section>`
          already draws a full-bleed `border-b` by default (blocks.tsx:59) -- and the section
          above supplies this one's top rule the same way. The explicit `border-y` was a second,
          narrower pair of rules (1280px, centred) sitting directly against the full-bleed ones
          from the section system, which is a doubled/offset hairline at any viewport wider than
          1280px -- one candidate for the "weird lines going across pages" report, confirmed at
          the code level 2026-08-09. */}
      {/* THE PAGE NOW CLOSES ONCE. Measured on the rendered page at 1440x900 before this merge,
          the last 1,300px were three consecutive full-width bands:

            y=6980  this band            "Every idea walks into a room built to destroy it."
                                          -> /how-it-works, -> /kill-log ("See the 1,364 it rejected")
            y=7400  TrustGuaranteesRow   three terms + "1,364 ideas were killed to list these 50"
            y=7620  CtaBand              "Find your next business from GBP 29.99."
                                          -> #catalog, -> /how-it-works

          Two closing CTA bands, 640px apart, both linking to /how-it-works, with "1,364" stated in
          each of the first two 200px from each other -- and each band left-aligned inside a 1200px
          container, so all three had an empty right half. That is the "same paragraph four times"
          defect at page scale, in the last thing a reader sees.

          One band now. The argument keeps the left column (it is the better line, and a closing
          statement should give a reason, not repeat the offer), the purchase terms take the right
          column so the width is actually used, and the primary button is the commercial one that
          the deleted `CtaBand` carried -- browse the shelf -- with the method as the secondary. The
          kill figure is stated once here, by the terms column, and the standalone
          "Find your next business" band is REMOVED from this page (it survives on /how-it-works,
          /ideas and /ideas/[slug], which is where `CtaBand` is still the right closing shape). */}
      {/* `band_view` (MASTER-BRIEF section 9). This is the closing band, below the whole shelf,
          so its count against the hero's says how many readers got to the end of the page. */}
      {/* THE SOURCES BAND (mockups/index.html section 12), after the shelf as drawn. The figure is
          summed from the packs on this page, not typed in. */}
      <SourcesBand
        sourcesTotal={packs.reduce((n, p) => n + (p.sourceCount ?? 0), 0)}
        packCount={packs.filter((p) => (p.sourceCount ?? 0) > 0).length}
      />

      {/* The drawing's section 16, `.close`: a 2px rule above it and the last word of the page. */}
      <SectionBand bandId="home-stress-tested" bg="surface2" width="7xl" className="close py-10 md:py-24">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-16">
        <div className="max-w-[46rem]">
          {/*
            "STRESS TESTED" SECTION, email §1.
            The previous four-sentence / six-label / two-link version argued for the filter at
            length, on the same page that already printed the kill total twice (proof strip + the
            LiveKillCard panel above the shelf). Three peer CTAs and an unfiltered jargon strip
            (pain reality / value durability / ...) were the load. The email cuts it to two
            sentences and one primary + one text link; the six verdict labels move to /how-it-
            works with plain-English glosses (that page owns the check list, per §5.3).

            The kill total is no longer here because the proof strip above the shelf already
            carries it. Repeating the figure a third time on one scroll would put the
            "sceptic who counts our numbers" exactly back where they started.
          */}
          <h2 className="sec">
            Every idea walks into a room built to destroy it.
          </h2>
          {/* "everything that survived" was an ALL claim about a population, and it was false in
              the same way the survivor count was: 80 ideas cleared the gates, 50 are on the shelf.
              A reader cannot check it either way, so it bought nothing and risked the one thing
              this page is selling. What is left claims only what the shelf can show. */}
          <p className="mt-4 lede">
            A claim without a source dies before it ever goes on sale. Every pack here came out
            the other side.
          </p>
          {/* The kill figure left this row with the second band: the terms column beside it now
              states it once, in a sentence that also says what the log actually contains. A link
              whose label is a number, 200px above a sentence containing the same number, was the
              near-duplicate that made the tail read as a page arguing with itself. */}
          {/* THE SECOND "BROWSE THE PACKS" IS GONE (founder, 2026-08-14). It was an
              `href="#catalog"` primary button, word for word the hero's primary button ~7,000px
              above it, and the note directly above records this band already absorbing one round of
              exactly this defect -- the closing `CtaBand` was removed for restating the offer the
              band beside it was already making. Removing a duplicate and then rebuilding it out of
              the survivor's own parts is the same page arguing with itself, one layer down.

              THE HERO'S COPY IS THE ONE THAT STAYS, and it is not a coin toss: it is above the fold,
              it is the first door a stranger meets, and it is the only one a reader who never
              scrolls will ever see. This band's job is to give a REASON, which is what its heading
              and paragraph do; "See how the filter works" is the action that reason earns, so it
              becomes this band's single link rather than a secondary to a duplicate.

              The one thing lost is the return path from the foot of a ~16,000px page back up to the
              shelf. That is a real cost and it is not unmitigated: `#catalog` is still the target of
              the hero button and of the header's own navigation, which is present at every scroll
              position. If it needs a dedicated control at the page foot, that is a "back to the
              shelf" affordance, which is a different object from a third copy of the primary CTA. */}
          <div className="mt-8 flex flex-wrap items-center gap-x-8 gap-y-3">
            <Link
              href="/how-it-works"
              className="inline-flex items-center gap-1.5 py-3 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              See how the filter works
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
          {/* `FounderNote` is REMOVED from the homepage (not deleted, and not from the site): the
              founder's paragraph now lives once, on /about, which is the page that answers "who is
              behind this" in full and which the link directly above reaches. Rendering the bio
              here as well meant a stranger met the same person twice in two lengths, and the
              homepage's job is the product. */}
        </div>

        {/* N1: the purchase terms, once, as the closing band's right column. Same component and
            same live `stats.listed` it had as a standalone band -- only its container changed
            (`layout="stack"`), so the counts still cannot drift from the kill log. */}
        <TrustGuaranteesRow layout="stack" listed={stats?.listed} price={range ?? undefined} className="lg:pt-2" />
        </div>
      </SectionBand>

      {/* The second "Want the next one, when it survives?" band used to sit here, and it was the
          home page's SECOND email ask. The shelf branch above already renders `ShelfEndCapture`,
          the empty and near-miss branches carry their own, and this band rendered under all three,
          so every state of this page asked a stranger for the same address twice in the same words
          (measured on the rendered DOM: 2 `input[type=email]` on `/` and on `/?q=<no match>`,
          2026-08-06). The rule was already written down one screen up (`index.tsx:537`: "two email
          forms on one screen is a duplicate ask that also breaks selector uniqueness") and this
          band was the thing violating it -- it also made the consent e2e fail strict mode, which is
          how it surfaced at all. The contextual asks win: they sit where the shelf actually runs
          out, and their `source` tags keep shelf-end and empty-state signups tellable apart in the
          ledger. One ask per state, enforced by `oneEmailAskPerScreen` in e2e/discovery.spec.ts. */}
      {/* THE TRUST ROW AND THE CLOSING `CtaBand` STOOD HERE and are both accounted for above:
          the row moved into the closing band as its right column (`layout="stack"`, same live
          `listed` prop), and the band was removed from this page.
          THIS NOTE USED TO CLAIM `CtaBand`'S TWO LINKS BOTH SURVIVED IN THE BAND ABOVE -- "Browse
          the packs" as the primary, "See how the filter works" as the secondary. Half of that is
          now stale and is corrected rather than deleted: the "Browse the packs" copy went on
          2026-08-14 because it was the hero's primary button restated at the foot of the page (see
          the record at that link). Nothing became UNREACHABLE, which was this note's actual claim:
          `#catalog` is still the hero button's target and the header navigation reaches it from
          every scroll position.
          `price` is still computed from the packs this render already has, never a constant, since
          the shelf stopped being one price when the segment ladder shipped (lib/priceRange.ts). */}
    </MarketingLayout>
    </BuyDrawerProvider>
  );
}

export const getServerSideProps: GetServerSideProps<HomeProps> = async (context) => {
  // Decoded server-side: out-of-vocabulary values in a hand-edited URL are dropped rather than
  // filtering the shelf down to nothing on a value no pack can ever carry.
  const initialState = decodeDiscoveryState(context.query);
  /* Read from the request environment, not from a build-time constant, so the operator flips
     a filter path with a restart instead of a redeploy. `?ff=filterbar` overrides for one
     request. See `lib/flags.ts`. */
  const flags = resolveFlags(process.env, context.query);

  // Same precedence order documented on `resolveMarket`: an explicit `?market=` (the switcher)
  // beats a stored cookie, which beats the edge-supplied country header, which beats "uk".
  const queryMarket = context.query.market;
  const cookieMarket = context.req.cookies.market ?? null;
  const countryHeader = context.req.headers['fly-client-country'];
  const market = resolveMarket({
    queryMarket: typeof queryMarket === 'string' || Array.isArray(queryMarket) ? queryMarket : null,
    cookieMarket,
    countryHeader: typeof countryHeader === 'string' ? countryHeader : null,
  });

  // An explicit `?market=` is a user choice and must persist, or the switcher would silently
  // revert on the visitor's very next request. This is the ONLY place the market cookie is
  // ever set, geo inference stays per-request off the header, nothing stored (see
  // lib/market.ts header comment). `market` is safe in the header because resolveMarket
  // clamps to KNOWN_MARKETS; the queryMarket guard means a merely-inferred value never
  // persists, and the clamp means an unknown `?market=` resolved elsewhere, so it won't
  // match `market` and no cookie is written for junk input.
  if (
    typeof queryMarket === 'string' &&
    queryMarket.trim().toLowerCase() === market &&
    market !== cookieMarket
  ) {
    context.res.setHeader('Set-Cookie', `market=${market}; Path=/; Max-Age=31536000; SameSite=Lax`);
  }

  // N2: read the recently-viewed cookie set by the pack detail page. The
  // personalised "Based on your browsing" row anchors on the most recent
  // pack. The list is MRU-ordered by the pack detail's Set-Cookie write.
  const recentlyViewedIds: string[] = (() => {
    const raw = context.req.cookies.recentlyViewed;
    if (!raw) return [];
    return raw.split(',').filter(Boolean).slice(0, 10);
  })();

  // US-5: the currency is decoupled from the market. A US visitor sees US packing first AND
  // the price in dollars; a French visitor sees UK packing first (no EU market yet) AND the
  // price in euros. The country header is the single source of truth for the display side.
  const currency = currencyForCountry(
    typeof countryHeader === 'string' ? countryHeader : null,
  );

  // N2: derive the personalised row. The most recently viewed pack anchors the similarity. If
  // the cookie is empty or the anchor pack is no longer in the catalogue, the row is hidden and
  // `RecentlyViewed` is rendered instead. Hoisted out of the try so the cached catalogue served
  // on the failure path below gets the same row, rather than silently losing personalisation
  // during an outage.
  const personalisedFor = (available: Pack[]): Pack[] => {
    if (recentlyViewedIds.length === 0) return [];
    const anchor = available.find((p) => p.id === recentlyViewedIds[0]);
    if (!anchor) return [];
    return similarPacks(anchor, available);
  };

  /*
    THE SHELF IS NOT PER-VISITOR, SO IT IS NOT RE-FETCHED PER VISITOR (2026-08-16).

    Everything above this line is derived from the request -- query, cookies, the country header --
    and costs nothing. The catalogue is the opposite: the same two calls, returning the same bytes,
    awaited before the first byte of HTML can leave. Measured against the live API that is 0.37-
    0.48s for `/catalog` plus 0.36s for `/catalog/stats`, and it showed up as a 0.495s TTFB on the
    home page while /kill-log, which is ISR, answered in 0.39s with far more HTML to send.

    So a catalogue fetched within the last minute is served straight from this process. The
    personalised row, the market, the currency and the cookie are all still computed per request:
    what is cached is the shelf, not the page.
  */
  const fresh = freshCatalog();
  if (fresh) {
    return {
      props: {
        packs: fresh.packs,
        stats: fresh.stats,
        flags,
        initialState,
        market,
        currency,
        personalised: personalisedFor(fresh.packs),
        viewedIds: recentlyViewedIds,
        catalogUnavailable: false,
      },
    };
  }

  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    // Only a SUCCESSFUL fetch is remembered -- that is what makes the fallback below "the last
    // catalogue we actually saw" rather than a guess.
    rememberCatalog(packs, stats);
    return {
      props: {
        packs,
        stats,
        flags,
        initialState,
        market,
        currency,
        personalised: personalisedFor(packs),
        viewedIds: recentlyViewedIds,
        catalogUnavailable: false,
      },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);

    // A failed fetch is not evidence that nothing is for sale. Serving the last catalogue this
    // server actually held keeps the shelf honest through an API restart; only a process that
    // has never held one falls through to saying so out loud. Before this, ANY catalogue
    // failure rendered "No packs are live right now." -- a sold-out claim manufactured by our
    // own outage, on the one page the whole business runs through.
    const cached = lastKnownCatalog();
    if (cached) {
      return {
        props: {
          packs: cached.packs,
          stats: cached.stats,
          flags,
          initialState,
          market,
          currency,
          personalised: personalisedFor(cached.packs),
          viewedIds: recentlyViewedIds,
          catalogUnavailable: false,
        },
      };
    }

    return {
      props: {
        packs: [],
        stats: null,
        flags,
        initialState,
        market,
        currency,
        personalised: [],
        viewedIds: recentlyViewedIds,
        catalogUnavailable: true,
      },
    };
  }
};

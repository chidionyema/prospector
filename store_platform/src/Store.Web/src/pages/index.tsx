import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
// `buttonClasses` went with the closing band's duplicate "Browse the packs" link (2026-08-14): it
// was the only caller in this file, because it is what lets a `<Link>` wear a button's shape.
import { Button, Icon, Dropdown, chipClasses, textLinkClass, PriceText } from '@/components/ui';
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
import PopulationField from '@/components/marketing/PopulationField';
import TrustGuaranteesRow from '@/components/marketing/TrustGuaranteesRow';
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, FilterFab, FilterSheet, StepFlow } from '@/components/discovery/FacetBar';
import { PackCardHeader } from '@/components/ui/PackCardHeader';
import { EvidenceBar } from '@/components/ui/EvidenceBar';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
// Last-known-good catalogue. A failed fetch must never render as "nothing is for sale".
import { freshCatalog, lastKnownCatalog, rememberCatalog } from '@/lib/catalogCache';
import { formatPriceForMarket, currencyForCountry, type Currency } from '@/lib/fx';
import { repairTruncation } from '@/lib/copy';
import { track } from '@/lib/analytics';
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

interface HomeProps {
  packs: Pack[];
  stats: CatalogStats | null;
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
export type PackWeight = 'lead' | 'mid' | 'row';

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
  if (pence >= 9900) return 'lead'; // £99 and £149 rungs
  if (pence >= 7900) return 'mid';  // £79 rung
  return 'row';
}

/**
 * The card's one-line description, hard-capped.
 *
 * `repairTruncation` already repairs the publish path's character-150 cut, but repairing a cut is
 * not the same as not making one: measured in the served HTML on 2026-08-07, 32 card descriptions
 * still ended mid-clause on a lowercase word followed by an ellipsis ("...fixes the knee, neck
 * and wrist pain…", "...and the approved contractor booking, so a…"). A sentence that stops in
 * the middle of a clause reads as a broken string, not as a summary, and it is the LAST thing the
 * eye sees before the price.
 *
 * A WORD BOUNDARY WAS NEVER THE THING THAT MATTERED (2026-08-15, founder: this is "the worst
 * thing on the shelf"). This function used to cut at 20 words and append nothing, on the
 * argument that "at a clean word boundary the line reads as a complete short summary". Measured
 * against the live catalogue (all 59 packs, GET api.mumchimp.com/catalog): SIXTEEN of them ended
 * on a dangling function word -- "...and the approved contractor booking, so a", "...exactly
 * which permit, licence and", "...the contractor must withhold part of". Word 20 is not a
 * meaning boundary, so cutting there lands mid-clause about a quarter of the time, and no
 * ellipsis is what makes it read as broken DATA rather than as an elision.
 *
 * The engine is not at fault and was wrongly blamed for this: the same fetch shows all 59
 * `oneLine` values arriving whole, every one ending in terminal punctuation, longest 268 chars
 * against `bridge.py`'s 280 cap. The shelf was cutting its own copy.
 *
 * THREE BOUNDARIES, IN DESCENDING ORDER OF MEANING. The first sentence, because these strings
 * are one sentence by construction and a second one is a restatement of the purchase terms.
 * Then a clause boundary inside the window, because a line ending on a comma's clause is a
 * finished thought. Only then a word boundary -- and there, back off over any trailing function
 * word, which is the specific defect: a line may not end on "so", "the", "which", "part of".
 *
 * 30 words rather than 20 because the cap now costs something. At 30, 44 of 59 pass through
 * WHOLE (median 155 chars, max 203) against 6 of 59 at 20, and the dangling count is 0 at both
 * -- so the lower cap was mutilating three quarters of the shelf to buy nothing. Still capped
 * rather than unbounded because the card clamps in CSS, and a clamp reached mid-word puts the
 * browser's own ellipsis back on the card.
 */
const DANGLING_TAIL = new Set([
  'the', 'a', 'an', 'and', 'or', 'but', 'so', 'to', 'of', 'in', 'on', 'at', 'for', 'with',
  'that', 'which', 'what', 'they', 'by', 'from', 'its', 'their', 'as', 'into', 'per', 'up',
  'out', 'over', 'under', 'is', 'are', 'was', 'were', 'be', 'been', 'when', 'while', 'after',
  'before', 'than', 'then', 'if', 'this', 'these', 'those', 'part', 'each', 'every', 'both',
]);

export function cardLine(text: string | null | undefined, maxWords = 30): string {
  if (!text) return '';
  let clean = text.replace(/\s*[…]\s*$/, '').replace(/\s*\.\.\.\s*$/, '').trim();
  // The first sentence only. Split on `. ` rather than `.` so a decimal or an abbreviation
  // mid-sentence cannot cut the line short -- the same rule `ideas/index.tsx`'s `firstSentence`
  // uses on landing descriptions.
  const stop = clean.search(/\.\s/);
  if (stop !== -1) clean = clean.slice(0, stop);
  clean = clean.replace(/\.$/, '').trim();

  const words = clean.split(/\s+/);
  if (words.length <= maxWords) return clean;

  const head = words.slice(0, maxWords);
  // A clause boundary inside the window beats a word boundary at the end of it. Bounded to the
  // last 8 words so a comma near the start cannot amputate the line to three words.
  for (let i = head.length - 1; i >= Math.max(head.length - 8, 0); i -= 1) {
    if (/[,;:]$/.test(head[i])) return head.slice(0, i + 1).join(' ').replace(/[,;:]+$/, '');
  }
  // Otherwise back off over trailing function words, so the line cannot end on "so the".
  while (head.length > 0 && DANGLING_TAIL.has(head[head.length - 1].replace(/[,;:]$/, '').toLowerCase())) {
    head.pop();
  }
  return head.join(' ').replace(/[,;:]+$/, '');
}

/**
 * THE CARD'S VISUAL, AND IT IS A NUMBER.
 *
 * The shelf card had no visual at all after the generated cover was removed on 2026-08-14 (see
 * the record where `PackCoverArt` was declared): the plate was a frame drawn for photography this
 * shop does not have, and the mark inside it was a hash of the pack id, which encodes nothing
 * about the pack. Both were "earned" by the letter of the rule and meant nothing by it.
 *
 * What replaces them is the pack's own strongest figure set at display-adjacent size. It is a
 * genuine visual -- it is the largest thing on the card and it is what the eye lands on -- and it
 * cannot be unearned, because it is a number the engine computed about THIS pack. Which number,
 * and the ladder that guarantees it is never blank, is `lib/packStat.ts`.
 *
 * ONE DEVICE AT THREE SIZES, not three treatments. Figure over label on the two cards, figure
 * beside label on the row, because a row has one line and no column to stack in. The sizes are
 * steps of the six-step scale (§3.2) and nothing else: `text-display` on the lead poster,
 * `text-h1` on the shelf card, `text-body` on the row -- each one step above the price it sits
 * with, which is what makes it the lead rather than a second price.
 *
 * MONO ON THE FIGURE, SANS ON THE LABEL. Not a new decision: tokens.css §3.2 states the site's
 * rule as "Commit Mono for anything the engine produced ... monospace is the site's promise that
 * a string is checkable", and the price beside it is mono for exactly that reason
 * (`PriceText`). `tabular-nums` so two cards' figures align down a column, which is the whole
 * point of putting the same number in the same place on every card.
 *
 * NO FIXED HEIGHT anywhere in here. The plate that was removed was 112px tall on a ~300px card;
 * this is two lines of type that size to their own content, so a card with a long title does not
 * grow a hole and a card with a short one does not stretch.
 */
function PackFigure({ stat, weight }: { stat: PackLeadStat; weight: PackWeight }) {
  if (weight === 'row') {
    return (
      /* `min-w-0` HERE AND ON THE LABEL, and the parent must be able to wrap. All three, or the
         row breaks in one of two opposite ways -- which is why the first attempt at this fix
         traded one for the other instead of ending it.

         The reported defect was collision: at 390px "48" printed over "US rules" as "48S rules",
         and "9" over the evidence bar. The cause was NOT `min-w-0` on this box. It was `min-w-0`
         on a box whose PARENT could not wrap and had no `min-w-0` of its own, so the meta line
         overflowed, this box was squeezed toward zero, and the `flex-none` digits kept their
         natural size and painted outside their own box onto the next item. Removing `min-w-0`
         here stopped the collision by refusing to shrink at all -- measured at 390px, this box
         then sat at W=229 inside a W=179 column, hanging 50px into the price's lane.

         229 is not a mystery, it is the automatic minimum size: with no `min-w-0`, `min-width`
         resolves to this box's MIN-CONTENT, and `truncate` on the label carries
         `white-space: nowrap`, so the label's min-content contribution is the whole 199px text
         run -- 24 (figure) + 6 (gap) + 199 = 229 exactly. `min-w-0` on the label sets the
         LABEL's own used minimum; it does not lower its parent's min-content. So the parent
         needs its own `min-w-0` to stop being floored by a run of text that was never going to
         be drawn at full length anyway.

         Collapse-to-zero cannot come back, because the parent now wraps (`:421`): this box gets
         a line to itself with the column's full width to shrink INTO, the `flex-none` figure
         keeps the number at natural size, and the label absorbs the squeeze through `truncate`.
         That is the shrink order the row wants -- the number is the fact, the word beside it is
         the gloss. `max-w-full` is the belt: whatever the line width, this box cannot exceed it. */
      <span className="flex min-w-0 max-w-full shrink items-baseline gap-1.5">
        <span className="flex-none font-mono text-body font-semibold tabular-nums text-text">
          {stat.figure}
        </span>
        <span className="min-w-0 truncate text-caption text-muted">{stat.label}</span>
      </span>
    );
  }

  const lead = weight === 'lead';
  return (
    <span className="block">
      <span
        className={cx(
          'block font-mono tabular-nums leading-none text-text',
          lead ? 'text-display' : 'text-h1',
        )}
      >
        {stat.figure}
      </span>
      <span className={cx('mt-1.5 block text-muted', lead ? 'text-meta' : 'text-caption')}>
        {stat.label}
      </span>
    </span>
  );
}

function PackCard({
  pack,
  currency,
  viewerMarket,
  viewed = false,
  weight = 'mid',
}: {
  pack: Pack;
  currency: Currency;
  /** Editorial weight. See `packWeight`. */
  weight?: PackWeight;
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
  const line = cardLine(repairTruncation(pack.oneLine) || sub);
  const price = formatPriceForMarket(pack.price, currency);
  const focusRing =
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus';

  /* ── ROW ────────────────────────────────────────────────────────────────────────────────────
     The long tail. Full width, hairline-divided, no card chrome at all.

     This is not a smaller card, it is a different object, and that is the point: a card says
     "consider me", a row says "here is the list". Forty-four more cards would be forty-four more
     posters competing with the lead, which is how the shelf got flat in the first place. As rows
     the same forty-four packs occupy roughly a third of the height and can actually be scanned
     down a column -- the price and the evidence bar land on the same x on every row, so
     comparing them is a vertical eye movement rather than a hunt.

     No border on the row itself. The divider comes from the parent `divide-y`, which is the
     "hairline dividers only where structural" rule: the line between two rows is structural, a
     box drawn around each row is not. */
  if (weight === 'row') {
    return (
      <Link
        href={`/pack/${pack.id}`}
        className={cx(
          'group flex items-center gap-4 px-3 py-4 sm:gap-5 sm:px-4',
          // Hover LIFTS to paper (`--surface`) rather than sinking to `--surface3`, which is now
          // the shelf's own ground -- a hover state painted the same colour as the surface under
          // it is not a hover state. Same direction as the cards: white = a thing you can pick up.
          'transition-colors hover:bg-surface',
          focusRing,
        )}
      >
        {/* THE SPINE IS GONE (2026-08-15), and it is the last of four near-black blocks to go.
            Its own two docblocks are the argument for removing it: the first records that on a
            pale ground forty of them read as "forty rows that have not finished loading", the
            second that on the instrument ground they read as "forty solid black blocks, i.e. as
            images that failed to load". Two grounds were tried, both were reported as a failed
            render, and the reason is the same one the founder gave for the plate and the cover --
            a generated mark in the place a product photo goes is read as the photo, missing. The
            fix was never the third ground.

            It also buys the row 44px of horizontal space at 390px, where the file already
            documents the title fitting 41% of its own string. A row is a line in a list; it
            carries no chrome at all, which is exactly what makes it a different object from a
            card rather than a smaller one. */}
        <span className="min-w-0 flex-1">
          {/* TWO LINES ON A PHONE, ONE FROM `sm` UP. The reported defect was "cuts at ~50% of
              available width while empty space remains", and the space is real but it is not the
              title's to take: measured at 390px the text column runs L=80..R=259 and the price
              group starts at L=275, so the column ALREADY fills everything up to the 16px gap.
              There is no missing `min-width: 0` here. The gap the eye sees is the price's own
              lane, which is blank at the title's y-band only because the price is centred
              vertically against a three-line row.

              So the column cannot be widened much, and the title needs 439px against 179px
              available -- 41%, which is where "Freelance pay bench..." comes from. A second line
              is the only thing that actually buys the words back. Measured after the arrow note
              below frees its 32px, the column runs L=80..R=286: 2 x 206px is 412px, so nearly
              the whole title survives instead of two fifths of it.
              `line-clamp-2` still ellipses, so a pathological title cannot push the row open.
              From `sm` the single line has the room to be honest, and the shelf keeps the flat
              scan-down-a-column rhythm the row variant exists for. */}
          <span className="flex min-w-0 items-center gap-2">
            <span className="line-clamp-2 text-body font-semibold text-text sm:line-clamp-none sm:truncate">
              {heading}
            </span>
            {viewed && (
              <span className="flex-none font-mono text-caption text-subtle">seen</span>
            )}
          </span>
          {line && <span className="mt-0.5 block truncate text-meta text-muted">{line}</span>}
          {/* THE CONTAINER, NOT THE ROWS. This was `flex items-center gap-3` with two
              `flex-none` children and an evidence bar that cannot shrink below its own tick
              run, on a line that gets ~246px at 390px. Nothing in it could yield, so the row
              overflowed and its items collided -- the single cause of three separate reported
              defects (overlapping meta items, the bar running past the card's padding, and the
              title truncating early because the overflow stole its space).
              `flex-wrap` + `gap-y` is the same schema the mid card has always used
              (`:653`), which is also the answer to the fourth: the two variants stop
              disagreeing about how this row lays out. A wrapped row is taller; a row whose
              contents print on top of each other is broken. */}
          <span className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            {/* A FIXED COLUMN, so the promise the note below makes is finally kept (2026-08-15).
                That note claims the figure "lands on the same x on every row". It did not: the
                sector printed at its natural width and the labels run from "Sector" to "Care and
                benefits claims", so the figure started at a different x on nearly every row -- and
                on an untagged pack the slot collapsed and the whole run jumped left. Measured on
                the deployed shelf, that ragged left edge is what makes a column of rows read as
                unaligned even though every row is built identically.

                From `sm` the sector gets an 11rem column; the longest label in the catalogue,
                "Care and benefits claims", sets ~10.8rem at `text-caption` mono, so it fits and
                anything longer ellipses rather than pushing the run. An untagged pack leaves the
                column EMPTY instead of closing it, which is the whole point. Below `sm` the line
                wraps anyway, so a fixed column there would only steal width from a 390px row --
                hence the placeholder is `hidden sm:block`, not a transparent spacer. */}
            {cat.tagged ? (
              <span className={cx('flex-none truncate font-mono text-caption sm:w-44', cat.ink)}>
                {cat.label}
              </span>
            ) : (
              <span className="hidden flex-none sm:block sm:w-44" aria-hidden />
            )}
            {/* THE SAME DEVICE AS THE CARDS, at the smallest of its three sizes: figure and label
                on one baseline instead of stacked. A row is a line in a list, so the number sits
                in the line rather than above it -- and it lands on the same x on every row, which
                is what makes forty of them scannable down a column. */}
            {stat && <PackFigure stat={stat} weight="row" />}
            {/* Label off: the row already prints a sector in mono beside it, and two mono
                fragments on one line read as a single run-on string. The bar alone still says
                "more evidence than its neighbour", which is the comparison the shelf is for.
                The bar goes entirely when the lead figure is already the source count -- at row
                scale the figure, its label, a sector and a forty-tick run of the same number is
                a line the eye cannot parse. */}
            {/* Capped harder HERE than the component's default 40. The cap is honest either
                way (past it the run draws an over-marker and the numeral carries the exact
                value), and 40 ticks is a ~79px object competing for a line that has ~246px on
                a phone for a sector, a figure, a label and a market flag. The bar's job in a
                row is "more evidence than the row above", which 14 ticks state as well as 40. */}
            {evidenceLabel && <EvidenceBar count={pack.sourceCount} label={false} cap={14} />}
            {/* COMPARE LIKE WITH LIKE. `groupByMarket` buckets on `packMarket(pack)` -- which
                case-folds and applies the null-is-uk rule -- while this test used the RAW
                field against the already-resolved viewer market. Two different value spaces,
                so a pack the grouper had correctly placed in the reader's own shelf would
                still flag itself foreign on any casing variance ("UK" vs "uk"). The guard on
                the raw field stays: a pack carrying no market at all makes no claim about
                jurisdiction, so it prints none. */}
            {pack.market && packMarket(pack) !== viewerMarket && (
              <span className="flex-none font-mono text-caption text-warning">
                {marketLabel(pack.market)} rules
              </span>
            )}
          </span>
        </span>

        <span className="flex flex-none items-center gap-3 sm:gap-4">
          <PriceText className="text-body">{price}</PriceText>
          {/* THE ARROW IS A HOVER AFFORDANCE, so it costs 32px on the one device that cannot
              hover. Its whole job is `group-hover:translate-x-0.5` -- on touch that never fires,
              and the entire row is already a link, so at 390px it is 32px (glyph + `gap-3`) spent
              on nothing. Handing those back to the text column takes it from 179px to a measured
              206px, which is what makes the two-line title above land at 412px of its 439px
              instead of 358px. Reclaiming width from a decoration beats squeezing the content
              that had to be read. */}
          <Icon
            name="arrowRight"
            size={15}
            className="hidden text-subtle transition-transform group-hover:translate-x-0.5 sm:block"
          />
        </span>
      </Link>
    );
  }

  /* ── LEAD ───────────────────────────────────────────────────────────────────────────────────
     Full-bleed and the widest card on the shelf: the one pack allowed to look like a poster.

     "Poster" is now a claim about WIDTH and TYPE, not about artwork -- the near-black mark column
     that used to open it is removed (see the record at its call site). The card still outranks its
     neighbours by every means that costs nothing: full container width, `text-h2` on the heading
     against their `text-body`, the lead figure at `text-display`, and a price rail with a filled
     button that no other weight carries.

     It no longer claims a `view-transition-name`. The morph's other half was the pack page's own
     near-black masthead, removed in the same edit; a shared element with one half left is a
     cross-fade of the whole root, which is the state this was originally added to fix. */
  if (weight === 'lead') {
    return (
      <Link
        href={`/pack/${pack.id}`}
        className={cx(
          /* `w-full` is load-bearing and was missing. The card is a flex ITEM (its wrapper in the
             shelf is `flex animate-rise`), so with no width it sizes to its content: measured at
             1440x900 the lead card ran x=120..1020 inside a 1200px container, while the row list
             directly beneath it ran the full 120..1320. Two right edges 300px apart in one shelf
             is not an editorial choice, it is a card that looks unfinished next to the list under
             it -- and the "poster" claim this treatment makes is a claim about WIDTH. */
          /* `lg:flex-row` moved DOWN one level (2026-08-15). The card's own axis is now vertical
             on every breakpoint -- header band, then body -- and the body is what turns into two
             columns at `lg`. It had to be the card while the mark column was the card's first
             child; with the mark gone, a header that stops 34% short of the right edge is not a
             header. */
          'group flex w-full flex-col overflow-hidden rounded-md border border-border bg-surface',
          'transition-[border-color,box-shadow] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
          'hover:border-border-strong',
          focusRing,
        )}
      >
        {/* THE POSTER COLUMN IS GONE (2026-08-15), and with it the last `--ins-bg` on the shelf.

            It was a 305x305 near-black square -- measured, at 1440, the largest single graphic on
            the homepage -- carrying a generated `PackMark` and a readout. Its own docblock spent
            four paragraphs tuning the ink ON that ground (`--ins-dim2` at 0.10-0.34, contrast
            measured to 5.14:1) and every one of those paragraphs answers "what should be drawn on
            the black block", never "should there be one". The founder answered the prior question
            on 2026-08-14: "Remove the black media block until there is real imagery for it"
            (docs/SITE_SPEC_PROGRAM.md:1007). The mid card and `PackCoverArt` obeyed that day; this
            one and the row spine did not, so the same ruling produced a shelf with two identities.

            THE MORPH GOES WITH IT, deliberately. `morph` named a shared element whose other half
            was the pack page's own near-black masthead, and that masthead is removed in the same
            edit for the same reason -- a transition is not a reason to keep two blocks nobody
            wanted. `PackMark` itself is untouched and still exported.

            NOTHING THE COLUMN STATED IS DROPPED. The sector is in the header band, in the same
            mono caption at the same size as every other card on the site; the evidence run is in
            the body a few lines below, at `size="lg"`, drawn for a light surface. */}
        {/* `sm:px-8` because THIS card's body opens to `p-8` from `sm` (:552) while every other
            card stays at `p-6`. The header's inset is not a constant, it is the card's own left
            edge -- a shared component that hardcoded one inset would put a 8px step inside the
            widest card on the shelf. */}
        <PackCardHeader
          label={cat.tagged ? cat.label : null}
          labelClassName={cat.ink}
          className="sm:px-8"
        />

        {/* TWO COLUMNS AT `lg`: what it is / what it costs. (It was three; the mark column is
            removed above.) The price and its button are a vertically-centred right rail rather
            than a bottom row, which spends the card's width on the two things a shelf card is for
            -- the claim and the number. Below `lg` this is untouched: one column, price row last,
            price left, button right. */}
        {/* THREE TRACKS AT `lg`, NOT TWO (2026-08-15). Removing the poster column left this card a
            two-column flex whose left child was `flex-1` while its copy was capped at `max-w-[58ch]`
            -- so at 1440 the copy set to ~520px inside a ~950px track and the card carried a ~430px
            hole between the paragraph and the price rail. Measured on the deployed shelf: the lead
            card was the emptiest object on the page, which is the opposite of what "the one card
            allowed to look like a poster" is supposed to mean.

            A grid fixes it by construction rather than by tuning a max-width against a flex basis:
            `1.4fr` for the claim, `1fr` for the evidence, `auto` for the money. Every track is
            filled because the tracks ARE the width -- there is no leftover to leak into a gap. The
            proportion also keeps the copy near a readable measure (~46ch at 1440) without a cap
            that fights the layout. Below `lg` nothing changes: one column, in reading order. */}
        <span
          className={cx(
            'flex flex-1 flex-col p-6 sm:p-8',
            'lg:grid lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] lg:items-center lg:gap-10',
          )}
        >
          <span className="flex min-w-0 flex-col">
            {/* CLAMPED, LIKE THE OTHER TWO WEIGHTS. This was the only card heading on the shelf
                with no bound, and it is also the largest type (`text-h2`), so it ran longest where
                it cost most: pack titles measure 43..60 characters on the live catalogue (all 59
                packs, 2026-08-14), which at this size takes three lines and pushes the price rail
                out of the card's optical centre. `row` truncates to one line (:437) and `mid`
                clamps to two (:691); one shelf should not state the same field at three lengths. */}
            <span className="line-clamp-2 block text-h2 font-semibold text-text">{heading}</span>
            {line && <span className="mt-2 block text-body text-muted">{line}</span>}
          </span>

          {/* THE EVIDENCE TRACK. Both numbers the card carries, in the order the mid card already
              uses -- figure first, run under it (`:697`) -- so the two weights stop disagreeing
              about which of the two is read first. The run came back off the deleted plate at the
              same `size="lg"`, drawn for a light surface; the figure is `text-display`, one step
              above the other weights, because this is the one card whose number is allowed to be
              the biggest type in the band. Neither is above the heading: a figure about a thing
              means nothing until the heading has said what the thing is. */}
          <span className="mt-6 flex min-w-0 flex-col gap-4 lg:mt-0">
            {stat && <PackFigure stat={stat} weight="lead" />}
            <EvidenceBar count={pack.sourceCount} size="lg" label={evidenceLabel} />
          </span>
          <span className="mt-auto flex items-end justify-between gap-4 pt-6 lg:mt-0 lg:flex-none lg:flex-col lg:items-end lg:gap-5 lg:pt-0">
            <PriceText className="text-h1">{price}</PriceText>
            <span
              className={cx(
                'inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2.5',
                'text-meta font-medium text-on-primary transition-colors group-hover:bg-primary-hover',
              )}
            >
              View pack
              <Icon name="arrowRight" size={14} />
            </span>
          </span>
        </span>
      </Link>
    );
  }

  /* ── MID ────────────────────────────────────────────────────────────────────────────────────
     The vertical card, and as of 2026-08-14 it is TEXT ALL THE WAY DOWN: a title, a one-liner, a
     meta row of facts, a price. No cover, no plate, no generated artwork of any kind.

     The two edits that got it here were made a week apart and point the same way. First the
     cover's `8 documents · N sources` chip went, because the document half was a constant printed
     57 times (see `EvidenceBar`) and the varying half was printed second, in the same size and
     colour as the constant beside it. Then the cover itself went -- see the note on the body
     below, and the record where `PackCoverArt` was declared. Both removals are the same finding
     twice: on this shelf, every pixel that is not a fact about THIS pack is a pixel that makes two
     cards harder to tell apart. What is left is the evidence bar sitting at a fixed y in the text
     column, which is what makes two adjacent cards' source counts comparable at a glance. */
  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex flex-col overflow-hidden rounded-md border border-border bg-surface',
        'transition-[border-color,box-shadow,transform] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
        'hover:-translate-y-px hover:border-border-strong',
        focusRing,
      )}
    >
      {/* THE BODY OPENS ON THE TITLE, ON EVERY CARD -- and it is now the ONLY thing in the card.
          `PackCoverArt`, the 112px near-black plate that used to render here, is REMOVED (founder,
          2026-08-14, from a screenshot of the deployed shelf). Its own docblock is kept below as a
          record; the verdict on it was that at 112px it occupied roughly 60% of a card's height and
          reads as the placeholder where a product image has not loaded yet. A dark rectangle where
          an image belongs is a promise the shop cannot keep, so it goes until there is real imagery
          to put in it. The objection that the plate encoded the source count was raised and
          overruled -- correctly, because the count is a FACT and the plate was a FRAME, and the fact
          does not need the frame: every one of the four facts the plate carried is rendered a few
          lines below, in the card's ordinary ink, on the meta row.

          THE JITTER FIX THE PLATE WAS ALSO DOING SURVIVES IT, and that is why the facts land BELOW
          the title rather than above it. The sector chip used to be the FIRST element of this body,
          and it renders only when the pack carries a sector -- 9 of the 63 live packs do not. So in
          a three-up row where one card was untagged, that card's title sat ~34px HIGHER than its
          neighbours' and its price row was pushed down by the same amount (measured on the built
          shelf at 1440, 2026-08-06: row 1 mixed one tagged with two untagged, row 2 the reverse, so
          the title baseline jittered on every row of the grid). Moving the chip to the plate fixed
          that by taking it out of the flow; putting it back BELOW the title and above an `mt-auto`
          price row fixes it the same way for free -- the title is the first child on every card, so
          its baseline cannot move, and everything the optional facts add or remove is absorbed by
          the `mt-auto` gap, not passed on to a neighbour. */}
      {/* A HEADER THAT SAYS SOMETHING (founder, 2026-08-14: "the card headers on the landing page
          the styling looks messy").

          WHAT WAS HERE FOR ONE DEPLOY, and why it was wrong. The band arrived earlier the same day
          to answer "why are cards missing headers ... like the header shading/colour": the `mid`
          cards were the only weight on the shelf opening on bare white while `lead` (:544) and
          `row` (:410) both wear an instrument plate, so they read as the cards whose header failed
          to render. That diagnosis stands. The EXECUTION was `bg-ins-bg` (#0B0D0F, tokens.css:242)
          carrying a generative `PackMark` -- i.e. a 40px near-black strip with a different faint
          squiggle in each one, forty times down a white grid.

          That is the same object the founder had killed six hours earlier at 112px, and the reason
          it was killed applies at any height: a dark rectangle at the top of a product card is the
          place a photo goes, so it reads as a photo that did not load. The docblock it replaced
          argued "a band this size cannot be mistaken for an image slot". It was, on sight. The
          height was never the defect; a decorative ground where a header belongs was.

          SO THE BAND STAYS AND THE DECORATION GOES. `--surface2` is the token whose own comment
          names this exact use ("Sunken/tinted panels: plate headers, table heads, footer, code",
          tokens.css:83) -- one notch off white, with a hairline to close it, which separates the
          header from the body without competing with anything in it. In it goes the ONE fact a
          shelf is scanned by, the sector, in the same mono caption it was already set in.

          It is MOVED, not copied: the sector left the meta row below (:772) in the same edit, so
          the card still states it exactly once. That also buys back a line of the meta row, which
          on an untagged pack was the only thing holding the row's left edge.

          An untagged pack (9 of 63 live) gets the band with no label rather than no band. The
          band is fixed-height and outside the body's flow, so an empty one costs nothing and keeps
          every title in the grid on the same baseline -- the jitter rule the docblock above spends
          a paragraph on. A card with no ground at all is what started this. */}
      <PackCardHeader label={cat.tagged ? cat.label : null} labelClassName={cat.ink} />

      <div className="flex flex-1 flex-col p-6">
        {/* No `group-hover:text-primary`. A title that changes colour on hover implies the title
            alone is the link; the whole card is. Border + lift already say "interactive". */}
        <h3 className="line-clamp-2 text-body font-semibold leading-snug text-text">{heading}</h3>
        {/* Three lines, was two. At two the one-liner was cut mid-clause on most cards ("...for
            small" / "...that pulls your fleet's MOT, tacho and"), which reads as a broken string
            rather than a summary. The price row is `mt-auto`, so the extra line costs card height
            and nothing else. */}
        {line && <p className="mt-1.5 line-clamp-3 text-meta text-muted">{line}</p>}

        {/* THE CARD'S VISUAL. It is the pack's own number, set at `text-h1` -- one step above the
            price at the foot of the same card, which is what makes it the thing the eye lands on
            rather than a second price. See `PackFigure` above for the device and `lib/packStat.ts`
            for which number and why.

            IT SITS HERE, between the description and the meta row, for the reason the removed
            plate's four facts sit below the title: the title is the first child on every card and
            its baseline cannot move, and everything optional below it is absorbed by the `mt-auto`
            gap above the price rather than passed on to a neighbour. A figure ABOVE the title
            would be a number with nothing to be a number about, and it would reintroduce exactly
            the jitter the plate removal was careful to keep fixed. */}
        {stat && (
          <div className="mt-4">
            <PackFigure stat={stat} weight="mid" />
          </div>
        )}

        {/* THE FOUR FACTS THE COVER PLATE CARRIED, IN THE CARD'S OWN INK.
            The plate held one fact per corner -- top-left what it is about (sector), top-right
            whose rules it is written for (market), bottom-left what is in the box (the cited-source
            run), bottom-right whether you have been here before (viewed). Deleting the plate must
            not delete any of them, so all four are here, in the order the eye already reads them.

            THE EVIDENCE BAR IS BACK WHERE IT WAS ON 2026-08-07, and the reason it was put there
            then is the reason it belongs here now: "at a fixed y in the text column, which is what
            makes two adjacent cards' source counts comparable". The plate's counter-argument was
            that a fixed 112px cover gives the same fixed y higher up the card. With the plate gone
            that argument goes with it, and `mt-auto` on the price row below re-establishes the
            fixed y from the bottom instead.

            `label` is left ON here (the row variant turns it off). On a row the bar sits inline
            with a mono sector label and two mono fragments on one line read as a run-on string; in
            a card body there is a whole line for it, and the founder's fix is explicit that the
            SOURCE COUNT must still be readable as text now that the run no longer has a plate of
            its own to be the largest thing on. `EvidenceBar` renders nothing at all when a pack has
            no `sourceCount`, so this row does not print a zero.

            `text-warning` on the market flag and `text-subtle` on "seen" are the same two treatments
            the row variant uses, so the two weights state the same fact the same way. */}
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {/* THE SECTOR IS NOT HERE ANY MORE -- it moved up into the header band (see its
              docblock). Stated once, sitewide, is the rule; stated once per CARD is the same rule
              at card scale, and a chip that repeats its own header is the noise the founder called
              messy. Everything else on this row stays exactly where it was. */}
          {/* The numeral drops when the lead figure above already IS the source count (see
              `evidenceLabel`); the tick run stays either way, because the run is the comparison
              between two cards and the figure is the value of one. */}
          <EvidenceBar count={pack.sourceCount} label={evidenceLabel} />
          {pack.market && pack.market !== viewerMarket && (
            <span className="font-mono text-caption text-warning">
              {marketLabel(pack.market)} rules
            </span>
          )}
          {viewed && <span className="font-mono text-caption text-subtle">seen</span>}
        </div>

        {/* `mt-auto` is what equalises card heights in the grid: the price row sits at the same y
            on every card in a row regardless of how long the title ran. */}
        <div className="mt-auto flex items-end justify-between gap-3 pt-5">
          {/* `font-mono`, and it was `text-h4` -- a token this stylesheet does not declare. The
              scale is six steps (display/h1/h2/body/meta/caption) plus the new `mega`; in Tailwind
              v4 an unmapped utility emits NO rule, so every price on the shelf was rendering at
              inherited body size with only `font-semibold` distinguishing it. Mono because a price
              is a checkable quantity, which is exactly the rule the house style already states,
              and `tabular-nums` so £49 and £149 align on the decimal down a column. */}
          <PriceText className="text-h2">{price}</PriceText>
          <span
            className={cx(
              'inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-2',
              'text-meta font-medium text-on-primary',
              'transition-colors group-hover:bg-primary-hover',
            )}
          >
            View pack
            <Icon name="arrowRight" size={14} />
          </span>
        </div>
      </div>
    </Link>
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

  const offered = allCategories().filter((cat) => (counts[cat.key] ?? 0) > 0);
  if (offered.length === 0) return null;

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
          return (
            <button
              key={cat.key}
              type="button"
              aria-pressed={active}
              onClick={() => onChange({ ...state, sector: active ? null : (cat.key as Sector) })}
              className={chipClasses({ selected: active, className: 'snap-start gap-1.5 whitespace-nowrap' })}
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
                {counts[cat.key]}
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
  if (items.length === 0) return null;

  return (
    <div className="mb-8">
      <h3 className="mb-3 text-meta font-semibold text-text">Pick up where you left off</h3>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((pack) => (
          <div key={pack.id} className="flex">
            <PackCard pack={pack} currency={currency} viewerMarket={market} viewed />
          </div>
        ))}
      </div>
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
 * The shelf, driven by the discovery state (spec Parts 4, 6, 7).
 *
 * Filtering is client-side over the packs the server already sent, and the state round-trips
 * through the URL so a filtered shelf is a link someone can send. The URL update is `shallow`:
 * the packs are already here, so re-running `getServerSideProps` would be a network round trip
 * that changes nothing on screen.
 */
function CatalogBrowser({
  packs,
  initialState,
  market,
  currency,
  personalised,
  viewedIds,
  featuredId,
  catalogUnavailable,
}: {
  packs: Pack[];
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
      const qs = encodeDiscoveryState(next);
      void router.replace(qs ? `/?${qs}` : '/', undefined, { shallow: true, scroll: false });
    },
    [router],
  );

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
  const shelfControls = (
    <div ref={shelfControlsRef} className="mb-8 pt-8">
      {/* Named, because an unlabelled control panel sitting mid-shelf reads as debris. It says
          what it is FOR, which is the thing the old placement never had to say because it was
          simply in the way. */}
      <h3 className="text-body font-semibold text-text">Narrow it down</h3>

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
      <p className="mb-4 max-w-prose text-meta text-muted">Use one or all three. They combine.</p>

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
        <p className="mx-auto mt-1 max-w-sm text-meta text-muted">
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
              {/* N2: "Based on your browsing" when the visitor has viewed a
                  pack, otherwise `RecentlyViewed`. Both rows are 3-card
                  compact summaries, the same shape, so the page rhythm stays
                  consistent. */}
              {personalised.length > 0 ? (
                <div className="mb-8">
                  <h3 className="mb-1 text-meta font-semibold text-text">Based on your browsing</h3>
                  <p className="mb-3 text-caption text-subtle">
                    Same mechanics as the last pack you opened.
                  </p>
                  {/* FULL CARDS, was three one-line rows.
                      Those rows were the worst treatment on the page given to the packs the site
                      had the strongest reason to show: `truncate` cut every title mid-word at one
                      line ("UV strips plus a paper log for gel ..."), so the value proposition was
                      the part that got cut; there was no price above a fold, no picture, and no
                      CTA, on a row the algorithm had just argued was the most relevant thing on
                      screen. Reusing `PackCard` is also what stops this row and the shelf drifting
                      apart: one card component, one set of rules. */}
                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {personalised.slice(0, 3).map((pack) => (
                      <div key={pack.id} className="flex">
                        <PackCard
                          pack={pack}
                          currency={currency}
                          viewerMarket={market}
                          viewed={viewedSet.has(pack.id)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <RecentlyViewed
                  packs={packs}
                  viewedIds={viewedIds}
                  currency={currency}
                  market={market}
                />
              )}
              {newestRow.length > 0 && (
                <div className="mb-8">
                  {/* `text-body`, was `text-meta`. A row heading set at the same size as the
                      body copy INSIDE the cards it introduces does not read as a heading at all;
                      on the built shelf "Newest survivors" and a card's one-line description were
                      the same 14px, so the grid arrived with no visible tier between "label for a
                      group of products" and "sentence about one product". This is the smallest
                      step that separates them and it stays sentence case, so the house policy in
                      `__tests__/weightAndCasePolicy.test.ts` is untouched. */}
                  <h3 className="mb-3 hidden text-body font-semibold text-text sm:block">
                    Newest survivors
                  </h3>
                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {newestRow.map((pack) => (
                      /* `lg:hidden`, not unmounted, and only on the one card the hero is already
                         showing: dropping it from the DOM would take an internal link out of the
                         server HTML to win a duplicate the reader never sees at that width. */
                      <div
                        key={pack.id}
                        className={cx('flex', pack.id === featuredId && 'lg:hidden')}
                      >
                        <PackCard
                          pack={pack}
                          currency={currency}
                          viewerMarket={market}
                          viewed={viewedSet.has(pack.id)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

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
                <h3 className="mb-3 hidden text-body font-semibold text-text sm:block">
                  More survivors, biggest opportunities first
                </h3>
              )}
              {/* ── THE EDITORIAL SHELF ──────────────────────────────────────────────────────
                  Three treatments instead of one, chosen by price tier (`packWeight`).

                  The uniform `lg:grid-cols-3` this replaces gave all 57 packs identical weight,
                  so nothing on the shelf was a focal point and the reader's eye had no entry.
                  Now the £99/£149 packs run full-bleed, the £79s run half-width, and the £29-£49
                  long tail runs as hairline-divided rows.

                  ORDER IS PRESERVED WITHIN EACH BAND but the bands themselves reorder the shelf,
                  which is a real trade and worth naming: the section is headed "newest first" and
                  after this pass that is true within a band rather than across the whole list. It
                  is the honest reading of what an editorial grid IS -- a claim that some items
                  deserve more space -- and the price ladder is the basis for the claim, so the
                  heading below says so rather than promising a strict recency order it no longer
                  keeps.

                  `shown` still gates by the pack's position in the ORIGINAL tail order, not by
                  its position after banding, so "Show the other N packs" reveals exactly the same
                  set it did before and the count under the button stays correct. */}
              {(() => {
                const rank = new Map(tailPacks.map((p, i) => [p.id, i]));
                const beyondFold = (p: Pack) => (rank.get(p.id) ?? 0) >= shown;
                const leads = tailPacks.filter((p) => packWeight(p) === 'lead');
                const allMids = tailPacks.filter((p) => packWeight(p) === 'mid');
                const rows = tailPacks.filter((p) => packWeight(p) === 'row');

                /*
                  AN ODD MID BAND LEAVES A HOLE, so the odd one is promoted instead.

                  The mid band is `lg:grid-cols-2`. Measured on the live shelf at 1440x900 the
                  band held exactly ONE card: a 590px card at x=120 with 610px of empty white
                  beside it, directly under a full-bleed lead card -- which does not read as an
                  editorial choice, it reads as a card that failed to load. Any odd count does the
                  same thing to its last row.

                  So when the count is odd the first mid (the highest-ranked one, keeping the
                  band's order intact) renders with the `lead` treatment and joins the row above,
                  leaving an even number to fill the grid. The tier still decides ORDER and which
                  band a pack belongs to; what it stops deciding, in the one case where it cannot
                  be honoured, is a layout that would be visibly broken. The alternative --
                  stretching the odd card across both columns -- gives a mid card the width of a
                  lead card anyway, but with a treatment drawn for half of it.

                  PARITY IS COUNTED OVER THE VISIBLE CARDS, NOT THE ARRAY. Cards past the fold are
                  rendered `hidden` rather than unmounted (see the note on `beyondFold`), so
                  `allMids.length` is the count AFTER "Show the other N packs" is pressed, not the
                  count on screen. The first attempt at this fix used it and changed nothing: two
                  mids, one of them hidden, reads as even and leaves the same hole. Both figures
                  recompute on every render, so pressing the button re-evaluates the promotion for
                  the expanded shelf.
                */
                const visibleMids = allMids.filter((pack) => !beyondFold(pack));
                const promoted = visibleMids.length % 2 === 1 ? visibleMids.slice(0, 1) : [];
                const mids = allMids.filter((pack) => !promoted.includes(pack));
                const leadRow = [...leads, ...promoted];

                return (
                  <>
                    {leadRow.length > 0 && (
                      <div className="flex flex-col gap-6">
                        {leadRow.map((pack) => (
                          <div
                            key={pack.id}
                            /* `hidden`, not unmounted. Dropping the nodes would strip internal
                               links out of the server HTML to win a scroll bar. */
                            className={cx('flex animate-rise', beyondFold(pack) && 'hidden')}
                          >
                            <PackCard
                              pack={pack}
                              weight="lead"
                              currency={currency}
                              viewerMarket={market}
                              viewed={viewedSet.has(pack.id)}
                            />
                          </div>
                        ))}
                      </div>
                    )}

                    {mids.length > 0 && (
                      <div
                        className={cx(
                          'grid grid-cols-1 gap-6 lg:grid-cols-2',
                          leadRow.length > 0 && 'mt-6',
                        )}
                      >
                        {mids.map((pack) => (
                          <div
                            key={pack.id}
                            className={cx('flex animate-rise', beyondFold(pack) && 'hidden')}
                          >
                            <PackCard
                              pack={pack}
                              weight="mid"
                              currency={currency}
                              viewerMarket={market}
                              viewed={viewedSet.has(pack.id)}
                            />
                          </div>
                        ))}
                      </div>
                    )}

                    {rows.length > 0 && (
                      /* `divide-y` on the parent, no border on the child. The line between two
                         rows is structural; a box drawn around each row is not. */
                      <div
                        className={cx(
                          'divide-y divide-border',
                          (leadRow.length > 0 || mids.length > 0) && 'mt-12',
                        )}
                      >
                        {rows.map((pack) => (
                          <div key={pack.id} className={cx(beyondFold(pack) && 'hidden')}>
                            <PackCard
                              pack={pack}
                              weight="row"
                              currency={currency}
                              viewerMarket={market}
                              viewed={viewedSet.has(pack.id)}
                            />
                          </div>
                        ))}
                      </div>
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
                  <Button variant="secondary" size="lg" onClick={() => setShowAll(true)}>
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
                  <p className="text-caption text-subtle">
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
              {grouped.others.map((group) => (
                /* A REAL RULE, NOT A GAP (2026-08-14, founder review at 390px). The boundary
                   between the reader's own shelf and this appendix was `mt-16` and a
                   `text-meta` heading -- on a phone, after forty rows, that is whitespace
                   followed by a line barely heavier than the body text. Every row below it
                   correctly prints "US rules", and the founder read them as UK rows that had
                   been mistagged: a correct flag on the wrong side of an invisible border
                   looks exactly like a data bug. The divider carries the same weight as the
                   distinction it is making now. */
                <div key={group.market} className="mt-16 border-t border-text pt-8">
                  {/* US PACKS DIVIDER (email §1). The label is now "Built for US rules" -- the
                      divider is about what the buyer would be BUILDING, not what the page has
                      written, and the subtitle states the consequence plainly: the research is
                      American, and the package cannot be transplanted. */}
                  <h3 className="text-body font-semibold text-text">
                    Built for {group.label} rules
                  </h3>
                  <p className="mt-1 max-w-[60ch] text-caption text-subtle">
                    The buyers, the numbers and the legal steps all follow {group.label} rules.
                    Read them anywhere; build them there.
                  </p>
                  {/* Rows, not cards. This group is explicitly secondary -- the copy directly
                      above says the numbers and legal steps will not transfer -- so giving it the
                      same card treatment as the on-market shelf contradicted the sentence
                      introducing it. Rows keep every pack fully present and linkable while
                      reading as an appendix, which is what it is. Each row still prints its
                      "<market> rules" flag, since `viewerMarket` is deliberately not passed. */}
                  <div className="mt-6 divide-y divide-border">
                    {group.packs.map((pack) => (
                      <PackCard
                        key={pack.id}
                        pack={pack}
                        weight="row"
                        currency={currency}
                        viewed={viewedSet.has(pack.id)}
                      />
                    ))}
                  </div>
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
              <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2">
                {candidates.map((candidate) => {
                  const pack = packs.find((p) => p.id === candidate.pack.id);
                  return pack ? (
                    <PackCard
                      key={pack.id}
                      pack={pack}
                      currency={currency}
                      viewerMarket={market}
                      viewed={viewedSet.has(pack.id)}
                    />
                  ) : null;
                })}
              </div>
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

export default function Home({ packs, stats, initialState, market, currency, personalised, viewedIds, catalogUnavailable }: HomeProps) {
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
  /* THE KILL TOTAL IS STATED ONCE ON THIS PAGE, in the proof strip below the hero. It was in
     `HeroEvidenceStrip` as well until 2026-08-13, which put "1,364" and an identically-worded
     "Read the kill log" link at y=735 and again at y~1180 of the same 1440x900 screen. The strip
     is the copy that stayed because it is the only one a phone ever reaches: `HeroEvidenceStrip`
     is `hidden md:block` and `PopulationField` is desktop-and-tall only.

     The old rule still stands and is the reason the number is not typed anywhere: every surface
     reads `kill-log-totals.json` or `RESEARCH_STATS`, never its own copy, because a "1,168 killed"
     figure duplicated across components is exactly how one of them goes stale. */
  return (
    // One drawer for the whole shelf. Inside MarketingLayout so the drawer's own Modal renders
    // above the header, and so a card anywhere on the page can reach it without prop threading.
    <BuyDrawerProvider currency={currency}>
    <MarketingLayout>
      <Seo
        title={`Business ideas that survived a filter built to kill them. Researched and ready to build${
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
        // The mobile padding is `pt-8 pb-8`, not `pt-10 pb-12`. Moving the filter-log panel below
        // the shelf (see the note there) put the first card at y=728/753/689 on the three phone
        // sizes measured, which clears the 40px-visible bar at 390x844 and 430x932 but left only
        // 27px at 360x780 -- the h1 takes one more line at that width. 24px of band padding is
        // the difference between a card you can see and a sliver. `md:` is untouched, so nothing
        // above a phone gets tighter.
        // `animate-settle`, not `animate-rise`: this band holds the h1, which is the page's
        // LCP element, and `rise` fades from opacity 0 -- which made LCP 1940ms against a
        // 328ms first paint (F-005). See the keyframes note in `tokens.css`.
        className="animate-settle pt-8 pb-8 md:pt-14 md:pb-16 [@media(max-height:820px)]:md:pt-8 [@media(max-height:820px)]:md:pb-8"
      >
        {/* Two columns on lg+: the claim on the left, the evidence for it on the right. The
            filter-log card is the argument -- it is the only thing above the fold that a
            sceptical stranger can check. */}
        {/* The `relative` wrapper and the `z-10` on the row below are the last of the positioning
            scaffolding that `AmbientKillColumn` needed (it was `absolute inset-y-0 right-0 z-0`
            behind this row). The column is gone -- see `PopulationField` below for what replaced
            it and the measurement that condemned it -- and the stacking context is kept only
            because the featured card's opaque fill still relies on it. */}
        <div className="relative">
        <div className="relative z-10 flex flex-col gap-10 lg:grid lg:grid-cols-[1fr_420px] lg:items-start lg:gap-12">
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
            <p className="mb-3 text-meta font-medium text-muted">
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
            <h1 className="w-full min-w-0 max-w-full text-display text-text md:max-w-[56rem] md:text-balance">
              {variant.globalHookLead}
            </h1>
            {/* Shown on mobile too. This was `hidden sm:block`, so a phone got the headline, then
                a CTA, then a ~120px void where the explanation should be. */}
            <p className="mt-4 max-w-[56ch] text-body text-muted">
              {variant.globalHookDescription}
            </p>
            {/* The hierarchy INVERTS here. The shelf was previously the thing you had to scroll
                past an orange "Read a free report" slab to reach: the primary action on a shop is
                the shop. The sample is the risk-reducer, so it is the quiet link beside it. */}
            <div className="mt-6 flex flex-col items-start gap-3 sm:flex-row sm:items-center md:mt-8">
              <Link href="#catalog">
                <Button size="lg">
                  Browse the packs
                  <Icon name="arrowRight" size={16} />
                </Button>
              </Link>
              <Link
                href="/sample"
                onClick={() => track('sample_cta_clicked')}
                className="inline-flex items-center gap-1.5 px-1 py-3 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
              >
                {/* ONE LINE, IN THE LINK. This was a link ("Read a free sample") over a caption
                    ("A whole report, free. No payment, no email."), which restated "free" twice
                    and then answered a question nobody had asked twice more. It then became a
                    short link over a three-word caption, which is still two elements for one
                    offer: a reader scanning the hero has to assemble the sentence from a link and
                    a line of grey text below the button row. The offer and the friction it removes
                    are one thought, so they are one clickable string. */}
                Read a full pack free, no email needed.
                <Icon name="arrowRight" size={14} />
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
            <HeroEvidenceStrip className="mt-5 hidden md:mt-6 md:block" />
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
               (`bg-surface`, see PackCard's "mid" branch), but the heading above it and the
               padding around it were not, so ticker text rendered legibly through the gap --
               "...Builder  The value would n[ot last]" sitting directly above "New this week"
               (ss_0456bw1wg, live mumchimp.com/, 2026-08-09). That column is gone, so nothing
               shows through any more; the fill stays because `--surface` and `--bg` are the same
               white (tokens.css:80,81) and removing it would be a no-op edit on a card whose
               background is otherwise inherited from whatever band it is dropped into. */
            <div className="relative z-10 hidden w-full rounded-md bg-surface p-4 lg:block">
              {/* Sentence case, and the same `text-meta font-semibold` as every other row heading
                  on the shelf below. It was `uppercase tracking-wide text-caption`, which the
                  house policy forbids (`__tests__/weightAndCasePolicy.test.ts`): CSS caps leave
                  the accessible name in sentence case while a screen reader may spell out the
                  rendered form, and this label sits directly above the one product on screen. */}
              <h2 className="mb-3 text-meta font-semibold text-text">
                New this week
              </h2>
              <PackCard
                pack={featured}
                currency={currency}
                viewerMarket={market}
                viewed={viewedIds.includes(featured.id)}
              />
            </div>
          )}
        </div>
        {/* THE POPULATION, AT FULL WIDTH AND UNDER THE CLAIM IT SUPPORTS.

            AFTER the two-column row in DOM order, not behind it. The h1 is this page's LCP
            element (see the `animate-settle` note on the band above, F-005), and the field is
            ~1,400 elements: putting it first would make the browser lay all of them out before it
            painted the headline. Here it costs the LCP nothing.

            THE HEIGHT GATE IS A FOLD DECISION AND USES THE SAME THRESHOLD AS THE BAND PADDING
            ABOVE. The field costs ~150px including its captions. At 1280x720 -- Playwright's
            Desktop Chrome and a real 720p laptop -- the first pack card already sits within ~50px
            of the fold after the padding trim documented on the SectionBand, so 150px there would
            put the product back off-screen, which is the exact regression that trim exists to
            undo. `min-height:821px` is the complement of that `max-height:820px` query: on a tall
            display the hero has the room, on a short one the shop keeps its product.

            `lg:` because below it the layout is one column and every pixel here pushes the first
            card down directly -- the same reason `HeroEvidenceStrip` beside it is `hidden md:block`. */}
        <PopulationField
          shelfCount={packs.length}
          className="mt-10 hidden [@media(min-height:821px)]:lg:block"
        />
        </div>
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
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="max-w-3xl">
            {/* TWO COUNTS, BOTH ABOUT KILLING, AND NO SURVIVOR FIGURE. This strip has been wrong
                three ways in one week, and every version failed for the same reason: it printed
                the survivor count, which is 80, next to a shelf holding 50. First it printed
                "80 survived. That's a 6% pass rate" (6% of 1,444 is 87). Then it explained the
                gap. Then it explained the whole partition. The founder cut the figure instead:
                the strip now states what we researched and what we killed, and the shelf states
                its own live count where the copy is about the shelf. Nothing left to reconcile. */}
            <p className="text-body font-semibold text-text">
              {RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas researched.{' '}
              {RESEARCH_STATS.killed.toLocaleString('en-GB')} killed on cited evidence.
            </p>
            {/* THIS LINE NAMES NO NUMBER, and every number it used to name was wrong or unasked
                for. What shipped read "80 survived the checks; 50 are packaged and listed so far.
                The other 1,364 are published, each with the evidence that killed it." -- a
                partition of 1,414 printed under a total of 1,444, with "published" attached to
                1,364 when 400 kills are published. The first repair stated all three denominators
                inline; the founder cut it on 2026-08-13 as a headache the buyer never asked for.
                So the only figures on this strip are the three in the line above, all from
                `RESEARCH_STATS`, which no longer exports a survivor count at all, so no page can
                reprint it. The receipts live on /kill-log, which the link beside this strip
                opens. */}
            <p className="mt-2 max-w-[64ch] text-meta text-muted">{killsSummary()}.</p>
          </div>
          <Link
            href="/kill-log"
            className="inline-flex flex-none items-center gap-1.5 py-3 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
          >
            Read the kill log
            <Icon name="arrowRight" size={14} />
          </Link>
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
          <h2 className="text-h2 font-semibold text-text">What survived</h2>
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

        <CatalogBrowser packs={packs} initialState={initialState} market={market} currency={currency} personalised={personalised} viewedIds={viewedIds} featuredId={featured?.id} catalogUnavailable={catalogUnavailable} />
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
          purchase terms. `PopulationField` states the kill total only in its `role="img"` label
          (`PopulationField.tsx:132`), never in visible text, and its own docblock records that the
          visible arithmetic was deliberately removed for exactly this reason. */}

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
        className="!py-14 md:!py-20"
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
        <PackContentsSection
          className="mt-16 border-t border-border pt-12"
          heading="The full contents"
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
      <SectionBand bg="surface2" width="7xl" className="py-16 md:py-24">
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
          <h2 className="text-h1 font-semibold text-text">
            Every idea walks into a room built to destroy it.
          </h2>
          {/* "everything that survived" was an ALL claim about a population, and it was false in
              the same way the survivor count was: 80 ideas cleared the gates, 50 are on the shelf.
              A reader cannot check it either way, so it bought nothing and risked the one thing
              this page is selling. What is left claims only what the shelf can show. */}
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            A claim without a source dies before it reaches this shelf. Every pack here came out
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

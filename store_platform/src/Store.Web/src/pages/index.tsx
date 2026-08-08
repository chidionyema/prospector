import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Button, Icon, Dropdown, chipClasses, textLinkClass, buttonClasses } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SectionBand, Section, CtaBand } from '@/components/marketing/blocks';
// The home page OWNS the pack manifest (§5.3 of docs/SITE_SPEC_PROGRAM.md, founder-confirmed
// 2026-08-07). `PACK_CONTENTS` for the count beside the prices, `PackContentsSection` for the
// manifest itself. /pricing keeps bare filenames only (`pricing.tsx:123`), which is the same
// section's other half of the ownership split, not a duplicate.
import { PACK_CONTENTS, PackContentsSection } from '@/components/marketing/PackContents';
import { EvidenceRecordPanel } from '@/components/marketing/EvidenceRecordPanel';
import LiveKillCard from '@/components/marketing/LiveKillCard';
import { HeroEvidenceStrip } from '@/components/marketing/HeroEvidenceStrip';
import AmbientKillColumn from '@/components/marketing/AmbientKillColumn';
import TrustGuaranteesRow from '@/components/marketing/TrustGuaranteesRow';
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, FilterFab, FilterSheet, StepFlow } from '@/components/discovery/FacetBar';
import PackMark from '@/components/ui/PackMark';
import { EvidenceBar } from '@/components/ui/EvidenceBar';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
import { formatPriceForMarket, currencyForCountry, type Currency } from '@/lib/fx';
import { repairTruncation } from '@/lib/copy';
import { track } from '@/lib/analytics';
import { priceRange, formatGbp } from '@/lib/priceRange';
import { allCategories, categoryFor, type Category } from '@/lib/category';
import type { Sector } from '@/lib/facets';
import { checkVerdicts } from '@/lib/checks';
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
import { DEFAULT_MARKET, groupByMarket, resolveMarket } from '@/lib/market';
import { KIND_NOUN } from '@/lib/facets';
import { useCopyVariant } from '@/lib/useCopyVariant';
import { RESEARCH_STATS, survivorsSummary } from '@/lib/stats';

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
 * So the card gets its own line, cut at a WORD boundary at 20 words, independent of whatever
 * length the full description happens to be. No ellipsis is appended: at a clean word boundary
 * the line reads as a complete short summary, and an ellipsis would reintroduce the "there is
 * more and you are missing it" signal this exists to remove.
 */
function cardLine(text: string | null | undefined, maxWords = 20): string {
  if (!text) return '';
  const clean = text.replace(/\s*[…]\s*$/, '').replace(/\s*\.\.\.\s*$/, '').trim();
  const words = clean.split(/\s+/);
  if (words.length <= maxWords) return clean;
  // Drop a trailing comma/semicolon left dangling by the cut -- "the knee, neck and wrist," is a
  // worse ending than "the knee, neck and wrist".
  return words.slice(0, maxWords).join(' ').replace(/[,;:]$/, '');
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
  /* The market this reader is browsing. Used ONLY to suppress the cover's market chip when it
     would be true of every card on screen -- see `PackCoverArt`. Optional so a caller with no
     market context (the hero's featured slot renders before any grouping) simply gets the chip. */
  viewerMarket?: string;
  /* True when this pack is in the reader's `recentlyViewed` cookie. A returning buyer scanning
     63 near-identical cards has no way to tell which ones they already opened, so the second
     visit is the first visit again. Server-rendered from the cookie, so it is in the first paint
     and never flashes in after hydration. */
  viewed?: boolean;
}) {
  const cat = categoryFor(pack);
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
          'transition-colors hover:bg-surface3',
          focusRing,
        )}
      >
        {/* The mark as a SPINE. At row scale a cover is impossible (there is no vertical room for
            one) but an identity is still needed, so the stratigraphy runs as a narrow vertical
            core sample -- which is the orientation the form was drawn for anyway. */}
        <span
          className={cx(
            'relative h-12 w-7 flex-none overflow-hidden rounded-sm sm:w-8',
            cat.tint,
            cat.ink,
          )}
        >
          <PackMark id={pack.id} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate text-body font-semibold text-text">{heading}</span>
            {viewed && (
              <span className="flex-none font-mono text-caption text-subtle">seen</span>
            )}
          </span>
          {line && <span className="mt-0.5 block truncate text-meta text-muted">{line}</span>}
          <span className="mt-1.5 flex items-center gap-3">
            {cat.tagged && (
              <span className={cx('flex-none font-mono text-caption', cat.ink)}>{cat.label}</span>
            )}
            {/* Label off: the row already prints a sector in mono beside it, and two mono
                fragments on one line read as a single run-on string. The bar alone still says
                "more evidence than its neighbour", which is the comparison the shelf is for. */}
            <EvidenceBar count={pack.sourceCount} label={false} />
            {pack.market && pack.market !== viewerMarket && (
              <span className="flex-none font-mono text-caption text-warning">
                {marketLabel(pack.market)} rules
              </span>
            )}
          </span>
        </span>

        <span className="flex flex-none items-center gap-3 sm:gap-4">
          <span className="font-mono text-body font-semibold tabular-nums text-text">{price}</span>
          <Icon
            name="arrowRight"
            size={15}
            className="text-subtle transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </Link>
    );
  }

  /* ── LEAD ───────────────────────────────────────────────────────────────────────────────────
     Full-bleed, horizontal, and the only pack on the shelf allowed to look like a poster.

     It carries `morph` on its mark: this is the card most likely to be clicked, so it is the one
     worth spending the shared-element transition on. Exactly one element per document may claim
     a given `view-transition-name`, and the lead is rendered once, which is what makes it the
     safe place to put it -- see the note on `PackMark`'s `morph` prop. */
  if (weight === 'lead') {
    return (
      <Link
        href={`/pack/${pack.id}`}
        className={cx(
          'group flex flex-col overflow-hidden rounded-md border border-border bg-surface lg:flex-row',
          'transition-[border-color,box-shadow] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
          'hover:border-border-strong',
          focusRing,
        )}
      >
        <span
          className={cx(
            'relative h-36 w-full flex-none overflow-hidden sm:h-44 lg:h-auto lg:w-[34%]',
            cat.tint,
            cat.ink,
          )}
        >
          {/* `axis="down"` for the same reason the detail masthead uses it, and the reason is
              MEASURED, not inferred from the class list: this box is never tall. `h-36 w-full` is
              ~2.4:1 on a phone, `sm:h-44 w-full` ~2.0:1, and `lg:h-auto lg:w-[34%]` measures
              305x305 -- exactly 1.00:1, which is why an "is it wide?" check written as `ratio > 1`
              skips it while the eye does not. Drawn `across` at any of those, the bands are
              ragged-width horizontal lines: the text-skeleton idiom, in the largest single graphic
              on the homepage. It is worst on an UNTAGGED pack, where the ink is zinc #71717A and
              the result is a grey bar stack indistinguishable from a card that has not loaded.
              Matching the masthead also makes the shared-element morph a clean scale instead of a
              transpose, since both ends of the transition now run the same way. */}
          <PackMark id={pack.id} morph axis="down" />
          {cat.tagged && (
            <span
              className={cx(
                'absolute left-4 top-4 inline-flex items-center gap-1.5 rounded-sm',
                'bg-surface/90 px-2.5 py-1 text-caption font-medium',
                cat.ink,
              )}
            >
              <Icon name={cat.icon} size={12} className="flex-none" />
              {cat.label}
            </span>
          )}
        </span>

        <span className="flex flex-1 flex-col p-6 sm:p-8">
          <span className="block text-h2 font-semibold text-text">{heading}</span>
          {line && <span className="mt-2 block max-w-[58ch] text-body text-muted">{line}</span>}
          <EvidenceBar className="mt-4" count={pack.sourceCount} />
          <span className="mt-auto flex items-end justify-between gap-4 pt-6">
            <span className="font-mono text-h1 font-semibold tabular-nums text-text">{price}</span>
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
     The vertical card, kept close to what shipped, because at half-width it still works. What
     changed: the cover's `8 documents · N sources` chip is gone (the document half was a
     constant printed 57 times -- see `EvidenceBar`), and the evidence bar now sits in the body
     where it can be compared against the card beside it rather than floating on the artwork. */
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
      <PackCoverArt pack={pack} category={cat} viewerMarket={viewerMarket} viewed={viewed} />

      {/* THE BODY OPENS ON THE TITLE, ON EVERY CARD.
          The sector chip used to be the first element in here, and it renders only when the pack
          carries a sector -- 9 of the 63 live packs do not. So in a three-up row where one card
          was untagged, that card's title sat ~34px HIGHER than its neighbours' and its price row
          was pushed down by the same amount. Measured on the built shelf at 1440 (2026-08-06):
          row 1 mixed one tagged with two untagged, row 2 the reverse, so the title baseline
          jittered on every row of the grid. Nothing else on the page telegraphs "assembled from
          parts" as loudly as a column of headings that do not line up.

          The chip now sits in the cover's top-left corner, where its presence or absence changes
          no other element's position, and where it is next to the tint it is derived from. */}
      <div className="flex flex-1 flex-col p-5">
        {/* No `group-hover:text-primary`. A title that changes colour on hover implies the title
            alone is the link; the whole card is. Border + lift already say "interactive". */}
        <h3 className="line-clamp-2 text-body font-semibold leading-snug text-text">{heading}</h3>
        {/* Three lines, was two. At two the one-liner was cut mid-clause on most cards ("...for
            small" / "...that pulls your fleet's MOT, tacho and"), which reads as a broken string
            rather than a summary. The price row is `mt-auto`, so the extra line costs card height
            and nothing else. */}
        {line && <p className="mt-1.5 line-clamp-3 text-meta text-muted">{line}</p>}

        {/* The evidence bar, in the BODY rather than on the artwork. It replaces the cover's
            `8 documents · N sources` chip: the document half was a constant (`PACK_CONTENTS.length`
            is the same 8 on every pack), so it was the first thing the eye read on all 57 cards
            and it distinguished none of them. Here it sits at a fixed y in the text column, which
            is what makes two adjacent cards' source counts comparable at a glance. */}
        <EvidenceBar className="mt-3" count={pack.sourceCount} />

        {/* `mt-auto` is what equalises card heights in the grid: the price row sits at the same y
            on every card in a row regardless of how long the title ran. */}
        <div className="mt-auto flex items-end justify-between gap-3 pt-5">
          {/* `font-mono`, and it was `text-h4` -- a token this stylesheet does not declare. The
              scale is six steps (display/h1/h2/body/meta/caption) plus the new `mega`; in Tailwind
              v4 an unmapped utility emits NO rule, so every price on the shelf was rendering at
              inherited body size with only `font-semibold` distinguishing it. Mono because a price
              is a checkable quantity, which is exactly the rule the house style already states,
              and `tabular-nums` so £49 and £149 align on the decimal down a column. */}
          <span className="font-mono text-h2 font-semibold tabular-nums tracking-tight text-text">
            {price}
          </span>
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

/**
 * The generated cover.
 *
 * Deterministic in `pack.id` so a given pack always looks the same across renders, sessions and
 * machines -- a cover that changes on reload is worse than no cover, because a buyer who returns
 * to the shelf cannot find the card they were looking at. `Math.random()` is therefore banned
 * here, and `__tests__/usTwoPackArt.test.ts` asserts the component's source contains no call to
 * it.
 *
 * The market chip lives here rather than on the meta row because "which country's rules is this
 * written for" is the one fact on the card that can make a pack useless to a reader, and it was
 * previously a bare `US` in mono beside a hash. It now says which market in words.
 *
 * It renders ONLY when the pack's market differs from the one the reader is browsing. A UK reader
 * on the UK shelf got "For UK rules" on all 63 cards: a label true of every item on a shelf tells
 * you nothing about any item on it, and it was competing for the eye with the sector badge, which
 * is the fact that actually distinguishes one card from the next. On the "Also available, US"
 * group -- and only there -- the same chip is the single most important thing on the card, because
 * that is where a reader can buy the wrong country's rules by accident.
 */
/**
 * The hairline weave every cover carries, tagged or not.
 *
 * Written as a full literal because Tailwind scans source text. It is stated in plain `rgb(0 0 0 /
 * a)` rather than a design token on purpose: this is a surface texture, not a semantic colour, and
 * a token would invite someone to "fix" its contrast against text that is never printed on it.
 *
 * Its whole job is to make an untagged cover read as DELIBERATELY blank instead of as a region
 * that failed to load. 9 of the 63 live packs carry no sector, so on a three-up grid roughly every
 * other row contained one flat, empty, pale rectangle sitting beside two covers with a mark on
 * them -- which is the same "is this broken?" signal as a missing image.
 */
const COVER_WEAVE =
  'bg-[image:repeating-linear-gradient(135deg,rgb(0_0_0/0.03)_0px,rgb(0_0_0/0.03)_1px,transparent_1px,transparent_10px)]';

function PackCoverArt({
  pack,
  category,
  viewerMarket,
  viewed = false,
}: {
  pack: Pack;
  category: Category;
  viewerMarket?: string;
  viewed?: boolean;
}) {
  return (
    /* 112px. It was 96px, and the extra 16px is bought outright: the sector chip moved up here out
       of the body, which took ~34px off the text block, so the card is net SHORTER than it was
       while the cover is bigger. */
    <div className={cx('relative h-28 overflow-hidden border-b border-border', category.tint)}>
      {/* The UNTAGGED FALLBACK is "no mark", not "a different mark".
          What stood here was a 5.5rem monogram of the card heading's initials, drawn for the 9 of
          63 live packs that carry no `sector` (measured on the live /catalog, 2026-08-06). On the
          rendered shelf it reads as `HA` and `SE` floating in the header of a product card: two
          capitals that map to nothing the buyer can look up, sitting where a picture goes, which
          is indistinguishable from placeholder art or a code you are expected to recognise. The
          argument for it was that a flat tint "reads as an empty box" -- true of the tint alone,
          and no longer true, because the tint now carries the spec strip below. A cryptic mark is
          worse than no mark: it makes the reader stop and fail to decode something. */}
      <div className={cx('pointer-events-none absolute inset-0', COVER_WEAVE)} />

      {/* ONE mark, fully inside the frame, in the same place on every card.
          What stood here was two marks at 36px and 88px, the small one at one of five seeded
          `left-[n%]` offsets and the large one at `-bottom-7 -right-6`, i.e. clipped by two edges
          at once. On the built shelf that reads as a rendering artifact rather than as art: the
          eye sees a shape cut off on the corner and looks for the thing that cropped it, and no
          two cards in a row cropped it the same way.

          The seeded jitter existed to stop the grid looking uniform. That was solving the wrong
          problem -- variety across the shelf already comes from twelve hues and twelve icons, and
          a mark that lands somewhere different on each card does not read as variety, it reads as
          unaligned. A grid of 63 products looks designed when the furniture repeats exactly. */}
      {category.tagged ? (
        <Icon
          name={category.icon}
          size={72}
          className={cx(
            'pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 opacity-[0.14]',
            category.ink,
          )}
        />
      ) : null}

      {/* THE SECTOR, moved here from the body -- see the note in `PackCard` about the title
          baseline. `bg-surface/90` rather than `cat.tint`, because the cover IS `cat.tint`: the
          chip's own tint over the same tint at full strength is an invisible chip. The ink stays
          the category's, so the chip still carries the hue, and it now matches the other three
          corner chips instead of being a fourth treatment. */}
      {category.tagged && (
        <span
          className={cx(
            'absolute left-3 top-3 inline-flex max-w-[calc(100%-1.5rem)] items-center gap-1.5',
            'truncate rounded-sm bg-surface/90 px-2.5 py-1 text-caption font-medium',
            category.ink,
          )}
        >
          <Icon name={category.icon} size={12} className="flex-none" />
          {category.label}
        </span>
      )}

      {/* THE SPEC STRIP -- what you are actually buying, on the shelf.
          A £49 digital product whose card shows no page count, no file count and no preview is
          bought blind, and the specific fear on a download page is "two pages in a Google Doc".
          Both figures are checkable rather than promotional:
            - `PACK_CONTENTS.length` is pinned to `prospector/bridge.py::BUNDLE_FILES` by
              `__tests__/packContents.test.ts`, and `bridge.py` ANDs a re-audit of the written zip
              into `is_listed`, so a pack missing a file cannot be on this shelf to be counted.
            - `sourceCount` is present on all 63 live packs (measured on /catalog, 2026-08-06).
          The card's own docblock argued sources are "a claim about us, not a benefit to them".
          That is right about a source count ALONE, where "is 29 good?" has no answer. Beside a
          fixed document count it stops being a ranking and becomes the spec of the thing in the
          box, which is the question the card was previously leaving entirely unanswered. Mono
          because both halves are quantities, the same voice as the toolbar caption. */}
      {/* THE SPEC STRIP IS GONE, and the document count with it.
          Measured in the served HTML on 2026-08-07: `8 documents` appeared 61 times on one page,
          once per card plus the prose. `PACK_CONTENTS.length` is a constant, so that half of the
          chip carried identical information on every card while occupying the first position the
          eye reaches -- the definition of dead ink. The half that DID vary, `sourceCount`, was
          printed second, in the same size and colour as the constant beside it, which is why the
          shelf read as 57 copies of one label.

          The argument the old chip made ("a £49 download with no spec is bought blind") is
          sound and is preserved, in two better places: the fixed document count now appears
          ONCE per page as prose, and `EvidenceBar` renders the varying number in the card body
          as a physical bar you can compare across cards without reading a digit. */}

      {/* FOUR CORNERS, one fact each, and each corner always holds the same KIND of fact:
          top-left what it is about, top-right whose rules it is written for, bottom-left what is
          in the box, bottom-right whether you have been here before. `viewed` was top-left, which
          is now the sector's corner -- two chips fighting for one corner is how the market chip
          and the sector badge ended up competing before. */}
      {pack.market && pack.market !== viewerMarket && (
        <span className="absolute right-3 top-3 rounded-sm bg-surface/90 px-2.5 py-1 text-caption font-medium text-muted">
          For {marketLabel(pack.market)} rules
        </span>
      )}
      {viewed && (
        <span className="absolute bottom-2.5 right-3 rounded-sm bg-surface/90 px-2.5 py-1 text-caption font-medium text-subtle">
          Viewed
        </span>
      )}
    </div>
  );
}

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
            className: 'gap-1.5 whitespace-nowrap',
          })}
        >
          All packs
          <span className={cx('font-mono text-caption', state.sector === null ? 'text-white/70' : 'text-subtle')}>
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
              className={chipClasses({ selected: active, className: 'gap-1.5 whitespace-nowrap' })}
            >
              {/* The hue is the card's hue, so the chip and the pill on the card it filters to are
                  visibly the same object. On the selected (ink-filled) chip the sector ink would
                  fail contrast, so the glyph inherits the fill's own text colour instead. */}
              <Icon name={cat.icon} size={12} className={active ? undefined : cat.ink} />
              {cat.label}
              <span className={cx('font-mono text-caption', active ? 'text-white/70' : 'text-subtle')}>
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
}: {
  packs: Pack[];
  initialState: DiscoveryState;
  market: string;
  currency: Currency;
  personalised: Pack[];
  viewedIds: string[];
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
    <div ref={shelfControlsRef} className="mb-8 border-t border-border pt-6">
      {/* Named, because an unlabelled control panel sitting mid-shelf reads as debris. It says
          what it is FOR, which is the thing the old placement never had to say because it was
          simply in the way. */}
      <h3 className="mb-3 text-body font-semibold text-text">Narrow it down</h3>

      {/* Toolbar: search, count, sort. */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:w-64">
          <SearchTrigger onOpen={() => setOpen(true)} triggerRef={triggerRef} />
        </div>
        <div className="flex items-center gap-4">
          {/* Count and freshness in one mono caption -- both are quantities, and this is the only
              place either is stated on the shelf now. */}
          <span className="whitespace-nowrap font-mono text-caption text-subtle">
            {visible.length} {visible.length === 1 ? 'pack' : 'packs'}
            {lastVerified && ` · updated ${lastVerified.replace(/^Verified /, '')}`}
          </span>
          <div className="w-40">
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
          which is the right thing to lose: opening the sheet is starting the narrowing again. */}
      {!filtersOpen && (
        <div className="mt-6 border-t border-border pt-6">
          <StepFlow packs={packs} state={state} onChange={apply} />
        </div>
      )}
    </div>
  );

  if (packs.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-surface py-16 text-center">
        <div className="mx-auto mb-3 flex items-center justify-center text-faint">
          <Icon name="search" size={24} />
        </div>
        <p className="text-body font-semibold text-text">No packs are live right now.</p>
        <p className="mx-auto mt-1 max-w-sm text-meta text-muted">
          We publish an opportunity the moment it clears every check. Check back shortly.
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
            className="whitespace-nowrap font-medium text-accent hover:text-accent-hover"
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
          every pack ships the identical `PACK_CONTENTS.length` documents. The page already said
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
        Same {PACK_CONTENTS.length} documents in every pack. Bigger opportunity, higher price.{' '}
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
                const mids = tailPacks.filter((p) => packWeight(p) === 'mid');
                const rows = tailPacks.filter((p) => packWeight(p) === 'row');

                return (
                  <>
                    {leads.length > 0 && (
                      <div className="flex flex-col gap-6">
                        {leads.map((pack) => (
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
                          leads.length > 0 && 'mt-6',
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
                          'divide-y divide-border border-y border-border',
                          (leads.length > 0 || mids.length > 0) && 'mt-8',
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
              {shown < tailPacks.length && (
                <div className="mt-8 flex flex-col items-center gap-2">
                  <Button variant="secondary" size="lg" onClick={() => setShowAll(true)}>
                    Show the other {tailPacks.length - shown} packs
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
                      missing ones were further down rather than missing. */}
                  <p className="text-caption text-subtle">
                    {[
                      `${gridPacks.length} ${marketLabel(market)} packs`,
                      ...grouped.others.map((group) => `${group.packs.length} ${group.label} packs`),
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
                <div key={group.market} className="mt-10 border-t border-border pt-8">
                  {/* US PACKS DIVIDER (email §1). The label is now "Built for US rules" -- the
                      divider is about what the buyer would be BUILDING, not what the page has
                      written, and the subtitle states the consequence plainly: the research is
                      American, and the package cannot be transplanted. */}
                  <h3 className="text-meta font-semibold text-text">
                    Built for {group.label} rules
                  </h3>
                  <p className="mt-1 max-w-[60ch] text-caption text-subtle">
                    The buyers, numbers and legal steps in these are {group.label}. Read them
                    anywhere; build them there.
                  </p>
                  {/* Rows, not cards. This group is explicitly secondary -- the copy directly
                      above says the numbers and legal steps will not transfer -- so giving it the
                      same card treatment as the on-market shelf contradicted the sentence
                      introducing it. Rows keep every pack fully present and linkable while
                      reading as an appendix, which is what it is. Each row still prints its
                      "<market> rules" flag, since `viewerMarket` is deliberately not passed. */}
                  <div className="mt-4 divide-y divide-border border-y border-border">
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
                  uniqueness. Rationale in ShelfEndCapture.tsx. */}
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

export default function Home({ packs, stats, initialState, market, currency, personalised, viewedIds }: HomeProps) {
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
  /* The hero's kill total moved into `HeroEvidenceStrip`, which reads the SAME `kill-log-totals.json`
     this page still reads for the panel below the shelf. That shared source is the point: a
     "1,168 killed" figure repeated across components is exactly how one of them goes stale, so no
     component is allowed to hold its own copy of the number. */
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
        {/* `relative` so the ambient kill column can be positioned against the hero rather than
            the viewport, and `z-10` on the content so the drifting names stay behind the headline
            at every scroll position. The column is desktop-only and `pointer-events-none`, so it
            cannot touch the measured phone fold budget or intercept a tap on the CTA. */}
        <div className="relative">
        <AmbientKillColumn />
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
            <p className="mb-3 text-meta font-medium text-muted">
              {range ? (range.uniform ? `${range.label} each` : `From ${formatGbp(range.min)}`) : 'One payment'}
              {` · ${packs.length} packs to choose from`}
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
                six-size scale; the spec puts the homepage hero at --text-display, 3rem, and that
                token now carries its own mobile size as a clamp, so the whole responsive ladder
                collapses to one class. The fold argument above still holds and is now slack
                rather than tight: dropping 96px to 48px can only give the fold more room.

                The 44rem cap went with it. It existed because 96px in an 812px column fits about
                17 characters, so 56rem would have set ragged three-line display text. At 48px
                that column reads as an ordinary measure and the tighter cap would just make the
                headline wrap early for no reason. */}
            <h1 className="w-full min-w-0 max-w-full text-display font-semibold text-text md:max-w-[56rem] md:text-balance">
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
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center md:mt-8">
              <Link href="#catalog" className="w-full sm:w-auto">
                <Button size="lg" fullWidth className="sm:w-auto">
                  Browse the packs
                  <Icon name="arrowRight" size={16} />
                </Button>
              </Link>
              <Link
                href="/sample"
                onClick={() => track('sample_cta_clicked')}
                className="inline-flex items-center gap-1.5 px-1 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
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
            <div className="hidden w-full lg:block">
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
        </div>
      </SectionBand>

      {/*
        PROOF STRIP, POSITION 2.

        The email's spec puts the kill total here, right under the hero, so the strongest stat
        the shop owns -- the survival rate -- is on the first screen rather than buried at the
        bottom of /how-it-works (where it lived until this pass). Every number is read from
        `RESEARCH_STATS`; nothing here is typed, so a future batch that changes the totals
        updates the page with it.

        `survivorsSummary(listed)` reconciles the surviving-vs-listed gap on the SAME line as
        the kill total, so a reader who only reads the proof strip still meets the explanation
        the home page would otherwise need a second card to state.

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
            <p className="text-body font-semibold text-text">
              {RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas researched.{' '}
              {RESEARCH_STATS.survived.toLocaleString('en-GB')} survived. That&apos;s {RESEARCH_STATS.rejectRate}%.
            </p>
            {/* The full stop is HERE and not inside `survivorsSummary`, and that is deliberate.
                Without it the home page ran two sentences together -- confirmed live on
                2026-08-08, `curl https://mumchimp.com/` renders "...49 are packaged and listed so
                far The other 1,364 are published...". The helper returns a CLAUSE, and its other
                two callers (LiveKillCard.tsx:175, kill-log.tsx:286) print it as a standalone stat
                beside a glyph, where a trailing full stop would be wrong. Punctuation belongs to
                whoever continues the sentence. */}
            <p className="mt-2 max-w-[64ch] text-meta text-muted">
              {survivorsSummary(stats?.listed)}. The other{' '}
              {RESEARCH_STATS.killed.toLocaleString('en-GB')} are published, each with the evidence
              that killed it.
            </p>
          </div>
          <Link
            href="/kill-log"
            className="inline-flex flex-none items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
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
      <Section bg="bg" width="7xl" outerClassName="!border-b" className="!pt-2 !pb-[calc(4rem+env(safe-area-inset-bottom,0px))] md:!pt-3 md:!pb-20">
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
              it states what every pack is (same `PACK_CONTENTS.length` documents, COUNTED not
              typed -- see below), why prices differ (opportunity size,
              not download size), and where to read the longer version (/pricing). The kill-rate
              line is not here because the proof strip above the shelf already carries it -- this
              sentence is the SHOP intro, not the FILTER intro. */}
          <h2 className="text-h2 font-semibold text-text">What survived</h2>
          <p className="mt-1.5 hidden max-w-[60ch] text-meta text-muted sm:block">
            {/* COUNTED, never typed. This line shipped a hand-written "8" while the same file
                renders `{PACK_CONTENTS.length}` for the identical fact ~640 lines up, and
                `PACK_CONTENTS` is pinned to the engine's own `BUNDLE_FILES` by
                `components/marketing/__tests__/packContents.test.ts`. The two would diverge the
                day the bundle changes, and one page would print both numbers -- which is exactly
                the drift recorded in `lib/faqContent.ts` ("it said four while the bundle had
                grown to eight"). */}
            Every pack is the same {PACK_CONTENTS.length} documents. Price follows the size of the
            opportunity, not the size of the download.{' '}
            <Link href="/pricing" className="font-medium text-accent underline underline-offset-2 hover:text-accent-hover">
              Why prices differ
            </Link>
            .
          </p>
        </div>

        <CatalogBrowser packs={packs} initialState={initialState} market={market} currency={currency} personalised={personalised} viewedIds={viewedIds} featuredId={featured?.id} />
      </Section>
      </div>

      {/* THE FILTER LOG, at every width now, and always AFTER the shelf.
          It used to be `lg:hidden` here and the hero's right column on desktop. Both positions
          were the same mistake at different breakpoints: the first thing a stranger met was an
          argument, with nothing for sale in view. Measured on the built page before this change:

            hero text   y=105  h=425   ends 530
            gap-10              40
            filter log  y=570  h=274   ends 844   <- the whole 844px viewport, before any product
            first card  y=1042                    -> 1.23 screens down (390x844)
                                                     1.37 (360x780), 1.08 (430x932)

          The panel is NOT deleted, because the reason it earns its place is undamaged: it is the
          only claim on the page a sceptic can check without leaving it. What changed is who meets
          it. A reader who has scrolled past a screen of products is exactly the one with a
          question; a reader who has seen nothing yet just wanted to know what you sell. */}
      <Section bg="bg" width="7xl" className="!pt-0 !pb-10">
        {/* `listed` is the live catalogue count, so the card can reconcile the two survivor
            numbers the site prints. It said "81 survived" and the shelf said 57, ~600px apart,
            and nothing on the page ever explained the 24. */}
        <LiveKillCard listed={stats?.listed} className="w-full lg:mx-auto lg:max-w-2xl" />
      </Section>

      {/* 3. ONE REAL PACK, SHOWN. Format ambiguity is the biggest killer on a digital download
             page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      {/* "What you get, at every price" IS GONE. The manifest under it is not, and the difference
          is the whole point of §5.3.

          Two sections used to argue the same thing here. The first was an essay about the ladder:
          which rung a pack lands on, why £29 and £199 buy the same documents, what the ambition
          tier and the market offset do -- that is /pricing's fact, and it is now one line above the
          shelf ("Same {PACK_CONTENTS.length} documents in every pack...") plus a link. The second,
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
        {/* A list of filenames names the documents; this shows one. The fear on a digital download
            page is paying £49 for a two-page Google Doc, and a noun does not answer it. Real
            rows from the free sample, including the check that failed, a preview of eight
            green ticks would advertise better and claim something the shop does not. */}
        <PackContentsSection heading="What's inside your pack" />
        <EvidenceRecordPanel />
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
      <SectionBand bg="surface2" width="7xl" className="border-y border-border py-16 md:py-24">
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
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            A claim without a source dies before it reaches this shelf. What you’re browsing is
            everything that survived.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-8 gap-y-3">
            <Link
              href="/how-it-works"
              className={buttonClasses({ size: 'lg' })}
            >
              See how the filter works
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link
              href="/kill-log"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              See the {RESEARCH_STATS.killed.toLocaleString('en-GB')} it rejected
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
          {/* `FounderNote` is REMOVED from the homepage (not deleted, and not from the site): the
              founder's paragraph now lives once, on /about, which is the page that answers "who is
              behind this" in full and which the link directly above reaches. Rendering the bio
              here as well meant a stranger met the same person twice in two lengths, and the
              homepage's job is the product. */}
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
      {/* N1: the single trust-and-guarantees row above the CtaBand. Three purchase terms,
          one place. The buyer who scrolls the page from top to bottom sees the terms of the sale
          once, definitively. */}
      {/* `price` computed from the packs this render already has, never a constant -- the shelf
          stopped being one price when the segment ladder shipped (lib/priceRange.ts). */}
      <TrustGuaranteesRow listed={stats?.listed} price={range ?? undefined} />

      {/* `lead` was "One payment. Every claim sourced. 14 day money back guarantee." -- the same
          three terms a third time, and directly under `TrustGuaranteesRow`, which had just said
          them. A closing band should give the reader a reason to scroll back up, not re-read the
          row immediately above it. */}
      <CtaBand
        width="7xl"
        title={range ? `Find your next business from ${formatGbp(range.min)}.` : 'Find your next business.'}
        lead={`${packs.length} packs. Research done, every claim sourced.`}
        primary={{ href: '#catalog', label: 'Browse the packs' }}
        secondary={{ href: '/how-it-works', label: 'How it works' }}
      />
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

  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    // N2: derive the personalised row. The most recently viewed pack anchors
    // the similarity. If the cookie is empty or the anchor pack is no
    // longer in the catalogue, the row is hidden and `RecentlyViewed` is
    // rendered instead.
    const personalised: Pack[] = (() => {
      if (recentlyViewedIds.length === 0) return [];
      const anchorId = recentlyViewedIds[0];
      const anchor = packs.find((p) => p.id === anchorId);
      if (!anchor) return [];
      return similarPacks(anchor, packs);
    })();
    return {
      props: { packs, stats, initialState, market, currency, personalised, viewedIds: recentlyViewedIds },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [], stats: null, initialState, market, currency, personalised: [], viewedIds: recentlyViewedIds },
    };
  }
};

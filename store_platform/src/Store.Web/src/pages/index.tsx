import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Button, Icon, Dropdown } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SectionBand, Section, CtaBand } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_CONTENTS } from '@/components/marketing/PackContents';
import { DossierPreview } from '@/components/marketing/DossierPreview';
import LiveKillCard from '@/components/marketing/LiveKillCard';
import TrustGuaranteesRow from '@/components/marketing/TrustGuaranteesRow';
import FounderNote from '@/components/marketing/FounderNote';
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, StepFlow } from '@/components/discovery/FacetBar';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
import { formatPriceForMarket, currencyForCountry, type Currency } from '@/lib/fx';
import { track } from '@/lib/analytics';
import { priceRange, formatGbp } from '@/lib/priceRange';
import { categoryFor, type Category } from '@/lib/category';
import { graph, itemListNode } from '@/lib/seo/schema';
import {
  cardHeading,
  decodeDiscoveryState,
  EMPTY_DISCOVERY_STATE,

  encodeDiscoveryState,
  filterPacks,
  isFiltered,
  nearMisses,
  similarPacks,

  type DiscoveryState,

} from '@/lib/discovery';
import { DEFAULT_MARKET, groupByMarket, resolveMarket } from '@/lib/market';
import { KIND_NOUN } from '@/lib/facets';
import { useCopyVariant } from '@/lib/useCopyVariant';
// Totals only, the full kill log is a separate import on /kill-log so its 60 entries stay
// out of the home page bundle. Both files come from tools/make_kill_log.py.
import killTotals from '@/data/kill-log-totals.json';

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
function PackCard({
  pack,
  currency,
  viewerMarket,
}: {
  pack: Pack;
  currency: Currency;
  /* The market this reader is browsing. Used ONLY to suppress the cover's market chip when it
     would be true of every card on screen -- see `PackCoverArt`. Optional so a caller with no
     market context (the hero's featured slot renders before any grouping) simply gets the chip. */
  viewerMarket?: string;
}) {
  const cat = categoryFor(pack);
  const { heading, sub } = cardHeading(pack);
  const line = pack.oneLine || sub;

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex flex-col overflow-hidden rounded-md border border-border bg-surface',
        'transition-[border-color,box-shadow,transform] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
        'hover:-translate-y-px hover:border-border-strong hover:shadow-1',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      )}
    >
      <PackCoverArt pack={pack} category={cat} viewerMarket={viewerMarket} />

      <div className="flex flex-1 flex-col p-5">
        {cat.tagged && (
          <span
            className={cx(
              'mb-2.5 inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1',
              'text-caption font-medium',
              cat.tint,
              cat.ink,
            )}
          >
            <Icon name={cat.icon} size={12} />
            {cat.label}
          </span>
        )}

        {/* No `group-hover:text-primary`. A title that changes colour on hover implies the title
            alone is the link; the whole card is. Border + lift already say "interactive". */}
        <h3 className="line-clamp-2 text-body font-semibold leading-snug text-text">{heading}</h3>
        {line && <p className="mt-1.5 line-clamp-2 text-meta text-muted">{line}</p>}

        {/* `mt-auto` is what equalises card heights in the grid: the price row sits at the same y
            on every card in a row regardless of how long the title ran. */}
        <div className="mt-auto flex items-end justify-between gap-3 pt-5">
          <span className="text-h4 font-semibold tracking-tight text-text">
            {formatPriceForMarket(pack.price, currency)}
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
 * Five offsets for the foreground mark. FULL LITERALS, indexed by seed: Tailwind scans source
 * text, so a computed `left-[${n}%]` compiles to nothing and the mark silently stacks at 0.
 */
const COVER_OFFSETS = [
  'left-[18%]',
  'left-[26%]',
  'left-[34%]',
  'left-[42%]',
  'left-[50%]',
] as const;

function PackCoverArt({
  pack,
  category,
  viewerMarket,
}: {
  pack: Pack;
  category: Category;
  viewerMarket?: string;
}) {
  // A stable small integer from the id. Sum of char codes is enough: the only requirement is that
  // it is deterministic and reasonably spread, not that it is uniform or unguessable.
  const seed = React.useMemo(
    () => Array.from(pack.id).reduce((acc, ch) => acc + ch.charCodeAt(0), 0),
    [pack.id],
  );
  const offset = COVER_OFFSETS[seed % COVER_OFFSETS.length];
  /* The untagged cover. Measured 2026-08-06 on the live API: 9 of 63 packs carry no `sector`, and
     every one of them was drawing `UNLABELLED.icon` -- a grey briefcase, twice, at 40 and 96px.
     That is the exact thing `lib/category.ts` forbids in its own header ("an untagged pack renders
     NO marker at all ... a mute dot with no label beside it is decoration pretending to be
     information"): a sector glyph on a pack whose sector we do not know is a claim with nothing
     behind it, and nine identical grey briefcases on one shelf is also the worst case for telling
     cards apart. The replacement carries no claim -- it is the initials of the words already
     printed on this card, so it says nothing the reader cannot check by looking down.

     Taken from `cardHeading(pack).heading`, NOT from `pack.title`. The first version used the raw
     title and shot wrong at once: pack 0cc434887c47cb9a is titled "FridgePass Kit -- the fridge
     logger that ..." but its card is headed by its `cardLine`, "Sell a fridge sensor that prints
     daily hygiene logs". The cover read `FK`, two letters that appear nowhere on the card, which
     is worse than no mark -- it looks like a code the buyer is supposed to recognise. The card
     never renders `cardHeading`'s `eyebrow`, so the brand name is not on screen at all.

     Stop-words are skipped for the same reason: "Sell a fridge sensor ..." would otherwise give
     `SA`, where the `A` is the article. */
  const monogram = React.useMemo(() => {
    const stopWords = new Set([
      'a', 'an', 'the', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'by', 'with', 'that',
      'your', 'you', 'from', 'into', 'when', 'how',
    ]);
    const words = cardHeading(pack)
      .heading.split(/\s+/)
      .map((word) => word.replace(/[^a-z0-9]/gi, ''))
      .filter((word) => word.length > 0 && /[a-z]/i.test(word));
    const meaningful = words.filter((word) => !stopWords.has(word.toLowerCase()));
    return (meaningful.length > 0 ? meaningful : words)
      .slice(0, 2)
      .map((word) => word[0].toUpperCase())
      .join('');
  }, [pack]);

  return (
    <div className={cx('relative h-28 overflow-hidden border-b border-border', category.tint)}>
      {category.tagged ? (
        <>
          <Icon
            name={category.icon}
            size={40}
            className={cx('absolute top-1/2 -translate-y-1/2 opacity-[0.28]', offset, category.ink)}
          />
          {/* A second, larger, fainter mark bleeding off the right edge. Two marks at different
              scales is what stops a flat tint from reading as an empty box. */}
          <Icon
            name={category.icon}
            size={96}
            className={cx('absolute -bottom-8 -right-6 opacity-[0.10]', category.ink)}
          />
        </>
      ) : (
        <span
          aria-hidden="true"
          className={cx(
            'absolute -bottom-6 -right-3 select-none font-semibold leading-none tracking-tight',
            'text-[5.5rem] opacity-[0.12]',
            category.ink,
          )}
        >
          {monogram}
        </span>
      )}
      {pack.market && pack.market !== viewerMarket && (
        <span className="absolute right-3 top-3 rounded-full bg-surface/90 px-2.5 py-1 text-caption font-medium text-muted">
          For {marketLabel(pack.market)} rules
        </span>
      )}
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

/** The last few packs the buyer viewed, from localStorage. Renders nothing on first visit. */
function RecentlyViewed({ packs }: { packs: Pack[] }) {
  const [viewed, setViewed] = React.useState<string[]>([]);
  React.useEffect(() => {
    try {
      const raw = localStorage.getItem('mumchimp.recentlyViewed');
      if (raw) setViewed(JSON.parse(raw).slice(0, 3));
    } catch { /* storage unavailable */ }
  }, []);

  if (viewed.length === 0) return null;
  const items = viewed
    .map((id) => packs.find((p) => p.id === id))
    .filter((p): p is Pack => !!p);
  if (items.length === 0) return null;

  return (
    <div className="mb-6">
      <h3 className="text-meta font-semibold text-text">Recently viewed</h3>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {items.map((pack) => (
          <Link
            key={pack.id}
            href={`/pack/${pack.id}`}
            className="flex items-center gap-3 rounded-md border border-border bg-surface p-3 text-meta font-medium text-text transition-colors hover:border-border-strong hover:bg-surface2"
          >
            <Icon name="arrowRight" size={14} className="flex-none text-subtle" />
            {pack.cardLine || pack.title}
          </Link>
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
  featuredId,
}: {
  packs: Pack[];
  initialState: DiscoveryState;
  market: string;
  currency: Currency;
  personalised: Pack[];
  /* The pack the hero is already showing in its desktop-only featured slot, so the shelf can
     avoid printing the same product twice on the same screen. Undefined on any render where the
     hero has no featured card, in which case the shelf behaves exactly as it did before. */
  featuredId?: string;
}) {
  const router = useRouter();
  const [state, setState] = React.useState<DiscoveryState>(initialState);
  const [sort, setSort] = React.useState<SortKey>('newest');
  const { open, setOpen, close, triggerRef } = useCommandPalette();

  const apply = React.useCallback(
    (next: DiscoveryState) => {
      setState(next);
      const qs = encodeDiscoveryState(next);
      void router.replace(qs ? `/?${qs}` : '/', undefined, { shallow: true, scroll: false });
    },
    [router],
  );

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

          <AppliedFilterChips state={state} onChange={apply} className="mb-4" />



          {visible.length > 0 ? (
            <>
              {/* N2: "Based on your browsing" when the visitor has viewed a
                  pack, otherwise `RecentlyViewed`. Both rows are 3-card
                  compact summaries, the same shape, so the page rhythm stays
                  consistent. */}
              {personalised.length > 0 ? (
                <div className="mb-6">
                  <h3 className="mb-3 text-meta font-semibold text-text">Based on your browsing</h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    {personalised.slice(0, 3).map((pack) => (
                      <Link
                        key={pack.id}
                        href={`/pack/${pack.id}`}
                        className="group flex items-start gap-3 rounded-md border border-border bg-surface p-4 transition-colors hover:border-border-strong"
                      >
                        <Icon name="verified" size={16} className="mt-0.5 flex-none text-success" />
                        <div className="min-w-0">
                          <p className="truncate text-meta font-medium text-text">
                            {pack.cardLine || pack.title}
                          </p>
                          <p className="mt-0.5 font-mono text-caption text-subtle">
                            {pack.sourceCount ?? 0} sources · {formatPriceForMarket(pack.price, currency)}
                          </p>
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              ) : (
                <RecentlyViewed packs={packs} />
              )}
              {newestRow.length > 0 && (
                <div className="mb-8">
                  <h3 className="mb-3 text-meta font-semibold text-text">Newest survivors</h3>
                  <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {newestRow.map((pack) => (
                      /* `lg:hidden`, not unmounted, and only on the one card the hero is already
                         showing: dropping it from the DOM would take an internal link out of the
                         server HTML to win a duplicate the reader never sees at that width. */
                      <div
                        key={pack.id}
                        className={cx('flex', pack.id === featuredId && 'lg:hidden')}
                      >
                        <PackCard pack={pack} currency={currency} viewerMarket={market} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {editorial && tailPacks.length > 0 && (
                <h3 className="mb-3 text-meta font-semibold text-text">
                  The rest of the catalogue, newest first
                </h3>
              )}
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {tailPacks.map((pack, i) => (
                  <div
                    key={pack.id}
                    /* `hidden`, not unmounted. Dropping the nodes would strip 37 internal links
                       out of the server HTML to win a scroll bar. */
                    className={cx('flex animate-rise', i >= shown && 'hidden')}
                    style={{ animationDelay: `${Math.min(i * 30, 300)}ms` }}
                  >
                    <PackCard pack={pack} currency={currency} viewerMarket={market} />
                  </div>
                ))}
              </div>
              {shown < tailPacks.length && (
                <div className="mt-8 flex flex-col items-center gap-2">
                  <Button variant="secondary" size="lg" onClick={() => setShowAll(true)}>
                    Show the other {tailPacks.length - shown} packs
                    <Icon name="arrowRight" size={15} />
                  </Button>
                  {/* The count the button used to give was the total, which read as "you have seen
                      none of 63" directly under twelve packs the reader had just scrolled. */}
                  <p className="text-caption text-subtle">
                    Showing {shown + newestRow.length} of {tailPacks.length + newestRow.length}.
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
                  <h3 className="text-meta font-semibold text-text">
                    Written for {group.label} rules
                  </h3>
                  <p className="mt-1 max-w-[60ch] text-caption text-subtle">
                    The research, the buyers and the regulations in these are {group.label}. Worth
                    reading anywhere, but the numbers and the legal steps will not transfer.
                  </p>
                  <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {group.packs.map((pack) => (
                      <PackCard key={pack.id} pack={pack} currency={currency} />
                    ))}
                  </div>
                </div>
              ))}

              {/* The three-question router, AFTER the whole shelf.
                  It sat between the newest row and the tail grid: a quiz wedged between row 1 and
                  row 2 of a product grid, which a reader mid-scan has to step over. Twice now the
                  fix has been to move it one block down and twice the DOM has put it back in the
                  middle of the shelf, so the rule is stated as a position, not an intention: it
                  renders after the LAST card, where the only reader who reaches it is one who
                  scanned the shelf and did not pick anything -- the only reader a router helps. */}
              <div className="mt-10 border-t border-border pt-8">
                <StepFlow packs={packs} state={state} onChange={apply} />
              </div>
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
                    <PackCard key={pack.id} pack={pack} currency={currency} viewerMarket={market} />
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

export default function Home({ packs, stats, initialState, market, currency, personalised }: HomeProps) {
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
  /* Read from the same JSON the filter-log panel reads, so the demoted one-liner in the hero and
     the panel below the shelf can never state different totals -- which is the specific way a
     "1,168 killed" figure repeated in two components goes stale in one of them. */
  const killedTotal = (killTotals as { killed: number; passed: number }).killed;
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
        className="animate-rise pt-8 pb-8 md:pt-14 md:pb-16 [@media(max-height:820px)]:md:pt-8 [@media(max-height:820px)]:md:pb-8"
      >
        {/* Two columns on lg+: the claim on the left, the evidence for it on the right. The
            filter-log card is the argument -- it is the only thing above the fold that a
            sceptical stranger can check. */}
        <div className="flex flex-col gap-10 lg:grid lg:grid-cols-[1fr_420px] lg:items-start lg:gap-12">
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
            <h1 className="w-full min-w-0 max-w-full text-h1 font-semibold text-text md:max-w-[56rem] md:text-balance md:text-display">
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
                Read a free sample
                <Icon name="arrowRight" size={14} />
              </Link>
            </div>
            {/* One line, was two. "A whole dossier, unredacted, every source clickable. No payment,
                no email." wrapped at 390px, and "unredacted" only means anything to someone who
                already suspected we were redacting -- the defensive register the critique named. */}
            <p className="mt-3 text-caption text-subtle">
              A whole pack, free. No payment, no email.
            </p>
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
            <p className="mt-5 hidden flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle md:mt-6 md:flex">
              <Icon name="verified" size={13} className="text-success" />
              <span>
                {killedTotal.toLocaleString('en-GB')} ideas tested and rejected before these
                {` ${packs.length.toLocaleString('en-GB')}`} made the shelf.
              </span>
              <Link
                href="/kill-log"
                className="font-medium text-accent underline-offset-2 transition-colors hover:text-accent-hover hover:underline"
              >
                See what we rejected
              </Link>
            </p>
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
                Newest on the shelf
              </h2>
              <PackCard pack={featured} currency={currency} viewerMarket={market} />
            </div>
          )}
        </div>
      </SectionBand>

      <div id="catalog" className="scroll-mt-20" />
      <Section bg="bg" width="7xl" className="!pt-2 !pb-[calc(4rem+env(safe-area-inset-bottom,0px))] md:!pt-3 md:!pb-20">
        <div className="mb-6 hidden sm:block">
          <h2 className="text-h2 font-semibold text-text">What survived</h2>
          <p className="mt-1.5 max-w-[60ch] text-meta text-muted">
            A pack is listed only once it clears every check, with a clickable source behind every
            claim. Most ideas never make it.
          </p>
        </div>

        <CatalogBrowser packs={packs} initialState={initialState} market={market} currency={currency} personalised={personalised} featuredId={featured?.id} />
      </Section>

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
        <LiveKillCard className="w-full lg:mx-auto lg:max-w-2xl" />
      </Section>

      {/* 3. WHAT YOU GET, the deliverable breakdown. Format ambiguity is the biggest killer on a
             digital download page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      {/* The heading has said "at every price" since the ladder shipped, and the page never once
          said what the prices MEAN. A shelf running £29 to £199 with no stated rule reads as
          arbitrary -- worse, it reads as "the dear ones must be the good ones", which invites the
          buyer to distrust the cheap ones and hesitate over the dear ones. The rule is real and
          simple (config.yaml `listing.pricing`: the rung is chosen by the opportunity's ambition
          tier, side_hustle through venture, plus a market offset, and every pack gets the identical
          eight documents), so it is stated in the intro where the spread is first named rather than
          left on /pricing for the reader who thought to go looking. */}
      <Section
        bg="white"
        width="7xl"
        title={`What you get${range ? ', at every price' : ''}`}
        intro={
          range && !range.uniform
            ? `One finished opportunity, already vetted, in ${PACK_CONTENTS.length} documents you own outright. Every pack contains the same ${PACK_CONTENTS.length}, whether it is ${formatGbp(range.min)} or ${formatGbp(range.max)}: the price follows the size of the opportunity the research found, never the length of the download. No subscription, no drip feed, no upsell.`
            : `One finished opportunity, already vetted, in ${PACK_CONTENTS.length} documents you own outright. No subscription, no drip feed, no upsell.`
        }
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
        <PackContentsSection heading="What’s inside your download" />
        {/* The list above names the documents; this shows one. The fear on a digital download
            page is paying £49 for a two-page Google Doc, and a noun does not answer it. Real
            rows from the free sample, including the check that failed, a preview of eight
            green ticks would advertise better and claim something the shop does not. */}
        <DossierPreview />
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
          <h2 className="text-h1 font-semibold text-text">
            Stress tested the way a sceptical investor would.
          </h2>
          <p className="mt-4 max-w-[60ch] text-body text-muted">
            Every opportunity walks into a room built to destroy it. Anything that cannot back a
            claim with a real source dies before it reaches this store. What you see is everything
            that survived.
          </p>
          {/* The six gates, named. Mono because these are the engine's own gate identifiers --
              the same strings the kill log prints beside each rejection, so a reader can match
              a claim here to a receipt there. */}
          <p className="mt-6 font-mono text-caption text-subtle">
            pain reality · value durability · incumbency · payer solvency · distribution · legality
          </p>
          {/* Two links, because this band makes two different promises. "How it works" describes
              the process; the kill log is the only thing on the site that proves it ran. A
              stranger who doubts the claim above needs evidence, not a longer description. */}
          <div className="mt-8 flex flex-wrap items-center gap-x-8 gap-y-3">
            <Link
              href="/kill-log"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              See the {killTotals.killed.toLocaleString('en-GB')} we rejected
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link
              href="/how-it-works"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              See exactly how it works
              <Icon name="arrowRight" size={14} />
            </Link>
            {/* THE THIRD LINK IS THE POINT. This band spends four sentences and six gate names on
                "an engine did the work", and until now the page never once suggested a person was
                attached to any of it -- while `/about`, the page that answers exactly that, had no
                inbound link from anywhere on the site. "We" appears throughout the copy with
                nothing behind it. This link is the minimum honest fix and works whether or not
                `FOUNDER` is filled in; the block below is the better one, and needs a real name. */}
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 text-meta font-medium text-accent transition-colors hover:text-accent-hover"
            >
              Who is behind this
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
          {/* Renders nothing at all until a real person is named in `lib/config.ts`. Deliberately
              in this band rather than the hero: the reader who wants to know who we are is the one
              who has just read the argument, and a bio above the shelf is the founder's-syndrome
              move this whole pass is undoing. */}
          <FounderNote className="mt-10 max-w-[46rem]" />
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
        lead={`${packs.length} of them, each with the research and the sources already done.`}
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
      props: { packs, stats, initialState, market, currency, personalised },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [], stats: null, initialState, market, currency, personalised: [] },
    };
  }
};

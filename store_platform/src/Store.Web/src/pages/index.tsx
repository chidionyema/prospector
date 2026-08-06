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
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, StepFlow } from '@/components/discovery/FacetBar';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
import { formatPriceForMarket, currencyForCountry, type Currency } from '@/lib/fx';
import { track } from '@/lib/analytics';
import { priceRange, formatGbp } from '@/lib/priceRange';
import { categoryFor } from '@/lib/category';
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

type PillIcon = 'check' | 'shield' | 'download' | 'lock' | 'money';

/* One factual line, an icon and a label. The green circle behind the icon is gone (brand v3):
   it made three terms of sale look like three achievements, and it was the only place on the page
   where `--success` carried no meaning -- success on this site means "a check passed", and
   "14-day money back" is not a check that passed. */
function TrustPill({ icon, label }: { icon: PillIcon; label: string }) {
  return (
    <div className="flex items-center gap-2 text-meta text-muted">
      <Icon name={icon} size={16} />
      {label}
    </div>
  );
}

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
function PackCard({ pack, currency }: { pack: Pack; currency: Currency }) {
  const cat = categoryFor(pack);
  const { heading, sub } = cardHeading(pack);
  const line = pack.oneLine || sub;
  const sources =
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? pack.sourceCount : null;
  const fresh = freshnessLabel(pack.verifiedAt);

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
      {/* The plate: sector on the left, market + short ID on the right. Everything on this row is
          a fact about the listing rather than a claim about it, which is why the right half is
          mono. */}
      <div className="flex h-11 items-center justify-between gap-3 border-b border-border bg-surface2 px-4">
        <span className="flex min-w-0 items-center gap-2">
          <span className={cx('h-2 w-2 flex-none rounded-full', cat.dot)} aria-hidden="true" />
          {cat.tagged && (
            <span className="truncate text-caption font-medium text-muted">{cat.label}</span>
          )}
        </span>
        <span className="flex flex-none items-center gap-2 font-mono text-caption text-subtle">
          {pack.market && <span>{marketLabel(pack.market)}</span>}
          <span aria-hidden="true">№ {pack.id.slice(0, 6).toUpperCase()}</span>
        </span>
      </div>

      <div className="flex flex-1 flex-col">
        <div className="px-5 py-4">
          {/* No `group-hover:text-primary`. A title that changes colour on hover implies the title
              alone is the link; the whole card is. Border + lift already say "interactive". */}
          <h3 className="line-clamp-2 text-body font-semibold leading-snug text-text">
            {heading}
          </h3>
          {line && (
            <p className="mt-1.5 line-clamp-2 text-meta text-muted">{line}</p>
          )}

          {/* The evidence row. Mono because every token in it is a checkable quantity, which is
              the whole rule for mono on this site. */}
          {(sources !== null || fresh) && (
            <p className="mt-4 flex flex-wrap items-center gap-x-1.5 font-mono text-caption text-subtle">
              <Icon name="verified" size={12} className="text-success" />
              {sources !== null && (
                <>
                  <span>{sources} sources</span>
                  {fresh && <span aria-hidden="true">·</span>}
                </>
              )}
              {fresh && <span>{fresh}</span>}
            </p>
          )}
        </div>

        {/* `mt-auto` is what equalises card heights in the grid: the rule sits at the same y on
            every card in a row regardless of how long the title ran. */}
        <div className="mt-auto flex h-12 items-center justify-between border-t border-border px-5">
          <span className="font-mono text-body font-semibold text-text">
            {formatPriceForMarket(pack.price, currency)}
          </span>
          <span className="inline-flex items-center gap-1 text-meta font-medium text-muted transition-colors group-hover:text-text">
            View pack
            <Icon name="arrowRight" size={14} />
          </span>
        </div>
      </div>
    </Link>
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
}: {
  packs: Pack[];
  initialState: DiscoveryState;
  market: string;
  currency: Currency;
  personalised: Pack[];
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
   * The spec also proposed a "Cleared all six checks" row. It is deliberately not built: a pack
   * only reaches the catalogue by clearing all six (CLAUDE.md, "Publish only on PASS"), so that
   * row is every pack on the shelf. A label that selects nothing is decoration wearing the
   * costume of a filter, which is the failure this whole pass is removing.
   */
  const editorial = !filtered && sort === 'newest';

  /* The tail is capped, not dropped: every card stays in the server HTML and is only display-
   * hidden, so a crawler and the "a filtered URL comes back filtered" e2e still see all of them
   * while the buyer gets a page with an end. 24 = 8 rows of 3 (xl), 12 of 2 (sm). */
  const SHELF_PAGE = 24;
  const [showAll, setShowAll] = React.useState(false);
  const newestRow = editorial ? gridPacks.slice(0, 3) : [];
  const tailPacks = editorial ? gridPacks.slice(3) : gridPacks;
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
                      <PackCard key={pack.id} pack={pack} currency={currency} />
                    ))}
                  </div>
                </div>
              )}

              {/* The three-question router, AFTER the first row of real packs.
                  It was already meant to be: it was moved down from above the toolbar with a
                  comment saying "it sits after the first row of real packs, so the first thing on
                  the page is product". It did not. It sat between `RecentlyViewed` and
                  `newestRow`, and `RecentlyViewed` renders nothing for a visitor with no cookie --
                  which is every first-time visitor, the exact person the placement was for. The
                  desktop screenshot on 2026-08-06 showed a quiz as the first thing under "What
                  survived". Ordered by the DOM now rather than by a comment. */}
              <div className="mb-6">
                <StepFlow packs={packs} state={state} onChange={apply} />
              </div>

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
                    <PackCard pack={pack} currency={currency} />
                  </div>
                ))}
              </div>
              {shown < tailPacks.length && (
                <div className="mt-8 flex justify-center">
                  <Button variant="secondary" size="lg" onClick={() => setShowAll(true)}>
                    Browse all {tailPacks.length + newestRow.length} packs
                    <Icon name="arrowRight" size={15} />
                  </Button>
                </div>
              )}
              {/* Boost, don't block: every other market's packs are still fully on the shelf,
                  clearly separated rather than mixed in or hidden. */}
              {grouped.others.map((group) => (
                <div key={group.market} className="mt-10 border-t border-border pt-8">
                  <h2 className="text-meta font-semibold text-text">
                    Also available, {group.label}
                  </h2>
                  <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {group.packs.map((pack) => (
                      <PackCard key={pack.id} pack={pack} currency={currency} />
                    ))}
                  </div>
                </div>
              ))}
              <p className="mt-8 flex items-center gap-2 text-meta text-muted">
                <Icon name="shield" size={16} />
                Every pack carries a 14-day money back guarantee.
              </p>
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
                  return pack ? <PackCard key={pack.id} pack={pack} currency={currency} /> : null;
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
  return (
    // One drawer for the whole shelf. Inside MarketingLayout so the drawer's own Modal renders
    // above the header, and so a card anywhere on the page can reach it without prop threading.
    <BuyDrawerProvider currency={currency}>
    <MarketingLayout>
      <Seo
        title={`Business ideas that survived six brutal checks. Researched and ready to build${
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
        className="animate-rise pt-10 pb-12 md:pt-14 md:pb-16 [@media(max-height:820px)]:md:pt-8 [@media(max-height:820px)]:md:pb-8"
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
            <p className="mb-3 font-mono text-caption text-subtle">
              {range ? (range.uniform ? `${range.label} each` : `From ${formatGbp(range.min)}`) : 'One payment'}
              {` · ${packs.length} packs live`}
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
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
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
            <p className="mt-3 text-caption text-subtle">
              A whole dossier, unredacted, every source clickable. No payment, no email.
            </p>
          </div>
          {/* ONE instance. This was rendered twice, `hidden md:block` and `md:hidden`, which put
              two copies in the DOM on every viewport: `display:none` hides an element, it does not
              stop React mounting it or running its effects. The card is responsive on its own. */}
          <LiveKillCard className="w-full" />
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

        <CatalogBrowser packs={packs} initialState={initialState} market={market} currency={currency} personalised={personalised} />
      </Section>

      {/* 3. WHAT YOU GET, the deliverable breakdown. Format ambiguity is the biggest killer on a
             digital download page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      <Section
        bg="white"
        width="7xl"
        title={`What you get${range ? ', at every price' : ''}`}
        intro={`One finished opportunity, already vetted, in ${PACK_CONTENTS.length} documents you own outright. No subscription, no drip feed, no upsell.`}
        className="!py-14 md:!py-20"
      >
        {/* Three terms of the sale, left-aligned, no pills. "Instant download" was cut from this
            row: it is a delivery detail the buy box states at the moment it matters, and four
            reassurances in a centred row of pills is the shape that made this page read as a
            landing page rather than a shop. */}
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:gap-8">
          <TrustPill icon="money" label={range ? `${range.label}, one payment` : 'One payment'} />
          <TrustPill icon="shield" label="14-day money back" />
          <TrustPill icon="check" label="Every claim sourced" />
        </div>
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
          </div>
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

      <CtaBand
        width="7xl"
        title={range ? `Find your next business from ${formatGbp(range.min)}.` : 'Find your next business.'}
        lead="One payment. Every claim sourced. 14 day money back guarantee."
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

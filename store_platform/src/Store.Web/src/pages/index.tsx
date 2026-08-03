import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, IconName, Dropdown } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SectionBand, Section, CtaBand } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_CONTENTS } from '@/components/marketing/PackContents';
import { DossierPreview } from '@/components/marketing/DossierPreview';
import { SourcedCaveat, SourcedFigure } from '@/components/marketing/SourcedFigure';
import { WaitlistForm } from '@/components/waitlist/WaitlistForm';
import { AddToCartButton } from '@/components/cart/AddToCartButton';
import { BuyDrawerProvider, BuyNowButton, useRequestBuy } from '@/components/checkout/BuyDrawer';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { AppliedFilterChips, StepFlow } from '@/components/discovery/FacetBar';
import { FacetChips } from '@/components/discovery/FacetChips';


import { ShelfEndCapture } from '@/components/discovery/ShelfEndCapture';
import { fetchCatalog, fetchCatalogStats, formatPrice, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
import { track } from '@/lib/analytics';
import { citedFigure } from '@/lib/sources';
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

  type DiscoveryState,

} from '@/lib/discovery';
import { DEFAULT_MARKET, groupByMarket, resolveMarket } from '@/lib/market';
import { KIND_NOUN } from '@/lib/facets';
import { cleanProofPoint } from '@/lib/proof';
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
}

type PillIcon = 'check' | 'shield' | 'download' | 'lock' | 'money';

function TrustPill({ icon, label }: { icon: PillIcon; label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm font-medium text-text/70">
      <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-success/10 text-success">
        <Icon name={icon} size={12} />
      </span>
      {label}
    </div>
  );
}

// The deliverable chips are identical for every pack (the bundle is the bundle), so they render
// Colour-coded sector label. `onLight` sits on a white card body; the default glass pill sits on the
// coloured cover.
function CategoryPill({ cat, onLight = false }: { cat: Category; onLight?: boolean }) {
  // An untagged pack shows no pill at all, same rule as FacetChips below, and for the same
  // reason: absence is rendered as absence, never as a badge about the state of our pipeline.
  if (!cat.tagged) return null;
  if (onLight) {
    return (
      <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide', cat.chip)}>
        <Icon name={cat.icon} size={12} /> {cat.label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-text shadow-sm backdrop-blur">
      <Icon name={cat.icon} size={12} className={cat.accent} /> {cat.label}
    </span>
  );
}

// Shared cover backdrop: the sector gradient, a soft top highlight, and a large faint sector icon as
// distinct per-industry imagery. Children are the badges placed over it.
function Cover({ cat, iconSize, className, children }: { cat: Category; iconSize: number; className?: string; children: React.ReactNode }) {
  return (
    <div className={cx('relative overflow-hidden', cat.cover, className)}>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_120%_at_12%_-10%,rgba(255,255,255,0.25),transparent_55%)]" />
      <Icon
        name={cat.icon}
        size={iconSize}
        className="pointer-events-none absolute -bottom-6 -right-4 text-white/15 transition-transform duration-300 group-hover:scale-105"
      />
      {children}
    </div>
  );
}

/** The proof tier: how much evidence stands behind the listing, and when it was last checked.
 *
 *  Deliberately not chips and deliberately not capped. It is the last thing a buyer reads before
 *  the CTA because it is the claim the rest of the card rests on, every other line describes the
 *  opportunity, this one says why we think it is real. It renders nothing when there is nothing
 *  to cite, which is the same rule as everywhere else: we do not print a reassurance we cannot
 *  back. */
function ProofLine({ pack }: { pack: Pack }) {
  const sources =
    typeof pack.sourceCount === 'number' && pack.sourceCount > 0 ? pack.sourceCount : null;
  const fresh = freshnessLabel(pack.verifiedAt);
  if (sources === null && !fresh) return null;
  return (
    <p className="mt-2.5 flex flex-wrap items-center gap-x-1.5 text-[11px] font-medium text-muted">
      <Icon name="verified" size={12} className="text-primary" />
      {sources !== null && (
        <>
          <span>
            <span className="font-bold text-text/80">{sources}</span> sources
          </span>
          <span aria-hidden="true">·</span>
        </>
      )}
      <span className="font-bold text-text/80">6 / 6</span> checks
      {fresh && (
        <>
          <span aria-hidden="true">·</span>
          <span>{fresh}</span>
        </>
      )}
    </p>
  );
}

function PackCard({ pack }: { pack: Pack }) {
  const cat = categoryFor(pack);
  const { name, heading, eyebrow, sub } = cardHeading(pack);
  const line = pack.oneLine || sub;
  const requestBuy = useRequestBuy();

  // Status badge from available data. Only show when it means something.
  const badge: string | null =
    pack.sourceCount && pack.sourceCount >= 30 ? 'Trending' : null;

  // Bold the hook: first sentence of the description as a secondary anchor.
  const hookEnd = line ? Math.min(
    line.indexOf('.') > 0 ? line.indexOf('.') + 1 : 60,
    line.indexOf(',') > 0 ? line.indexOf(',') : 60,
  ) : 0;
  const hook = line && hookEnd > 0 && hookEnd < line.length ? line.slice(0, hookEnd) : null;
  const rest = hook ? line!.slice(hookEnd).trim() : line;

  return (
    <Link
      href={`/pack/${pack.id}`}
      className={cx(
        'group flex flex-col border-l-[3px] border-l-primary bg-surface px-5 py-4 transition-colors',
        'rounded-r-sm border border-border border-l-primary',
        'hover:bg-[#F8F5EF] hover:border-l-primary',
        'focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2',
      )}
    >
      {/* Category icon + label row -- visual anchor, breaks text monotony */}
      <div className="flex items-center gap-2 mb-2">
        {cat.tagged && (
          <span className="flex h-7 w-7 items-center justify-center rounded-full" style={{ backgroundColor: '#042F2E10' }}>
            <Icon name={cat.icon} size={14} className="text-primary" />
          </span>
        )}
        <div className="flex items-baseline gap-2 flex-1 min-w-0">
          {cat.tagged && (
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: '#0D9488' }}>
              {cat.label}
            </span>
          )}
          {eyebrow && (
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted truncate">{eyebrow}</span>
          )}
          {pack.market && (
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-faint">{marketLabel(pack.market)}</span>
          )}
        </div>
        {badge && (
          <span className="flex-none text-[10px] font-bold uppercase tracking-wide px-2 py-0.5" style={{ color: '#0D9488', backgroundColor: '#0D948810' }}>
            {badge}
          </span>
        )}
      </div>

      <h3
        className={cx(
          'line-clamp-2 text-lg font-bold leading-snug tracking-tight text-text transition-colors group-hover:text-primary',
        )}
      >
        {heading}
      </h3>
      {line && (
        <p className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed text-muted">
          {hook ? (
            <><span className="font-semibold text-text/80">{hook}</span>{rest}</>
          ) : (
            line
          )}
        </p>
      )}

      {/* Verification mini-bar */}
      <div className="mt-3 flex gap-[2px]" aria-hidden>
        {Array.from({ length: 6 }).map((_, i) => (
          <span key={i} className="h-[3px] flex-1 rounded-full bg-[#0D9488]" />
        ))}
      </div>

      <ProofLine pack={pack} />

      <div className="mt-auto pt-4">
        <span
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (requestBuy) requestBuy(pack); }}
          className="w-full bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-hover inline-flex items-center justify-center cursor-pointer"
        >
          Unlock for {formatPrice(pack.price)}
        </span>
        <p className="mt-2 text-center text-[13px] font-medium text-muted">
          or view details <Icon name="arrowRight" size={13} className="inline align-middle" />
        </p>
      </div>
    </Link>
  );
}

// The hero of the shelf: the newest survivor, given real visual weight (full width, horizontal) so
// the grid is not eleven identical blocks. Anchors the page and breaks the pattern.
function SpotlightCard({ pack }: { pack: Pack }) {
  const cat = categoryFor(pack);
  const { name, heading, eyebrow, sub } = cardHeading(pack);
  return (
    <div className="group relative mb-6 overflow-hidden border-2 border-text bg-surface transition-all duration-150 hover:-translate-x-[1px] hover:-translate-y-[1px]" style={{ boxShadow: '3px 3px 0 #1A1A1A' }}>
      <Link
        href={`/pack/${pack.id}`}
        className="flex flex-col md:flex-row"
      >
        <Cover cat={cat} iconSize={120} className="min-h-[120px] md:w-[32%]">
          <span className="absolute left-4 top-4 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-text shadow-sm backdrop-blur">
            <Icon name="trending-up" size={12} className={cat.accent} /> Latest to survive
          </span>
        </Cover>

        <div className="flex flex-1 flex-col justify-center gap-2.5 p-5 md:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <CategoryPill cat={cat} onLight />
            {eyebrow && (
              <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-muted">{eyebrow}</span>
            )}
          </div>
          <div>
            <h3 className="text-xl font-black leading-tight tracking-tight text-text transition-colors group-hover:text-primary md:text-2xl">
              {heading}
            </h3>
            {sub && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text/75 line-clamp-2">{sub}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xl font-black tracking-tight text-text">{formatPrice(pack.price)}</span>
            <span className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-bold text-white transition hover:bg-primary-hover">
              View vetted blueprint <Icon name="arrowRight" size={15} />
            </span>
            <BuyNowButton pack={pack} />
          </div>
        </div>
      </Link>
    </div>
  );
}

// Proof of life: the catalogue is a live, dated database, not a static page. Shows the most
// recent verification date across the live packs with a quiet pulse. No fabricated scarcity,
// just the real freshness signal.
function Heartbeat({ packs, stats }: { packs: Pack[]; stats: CatalogStats | null }) {
  const latest = packs
    .map((p) => p.verifiedAt)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1);
  const label = freshnessLabel(latest);
  if (!label && !stats) return null;
  return (
    <div className="inline-flex flex-wrap items-center gap-x-3 gap-y-1.5  border border-border bg-surface px-4 py-2 text-xs font-semibold text-muted">
      <span className="inline-flex items-center gap-2">
        <span className="inline-flex h-2 w-2 rounded-full bg-[#0DDB8B]" />
        <span className="text-text">Live database</span>
      </span>
      {label && (
        <>
          <span aria-hidden className="text-faint">
            •
          </span>
          <span>Last intelligence added {label.replace(/^Verified /, '')}</span>
        </>
      )}
      {stats && (
        <>
          <span aria-hidden className="text-faint">
            •
          </span>
          <span>
            {stats.registered > stats.listed
              ? `${stats.listed} live now, of ${stats.registered} that reached final packaging`
              : `${stats.listed} live now`}
          </span>
        </>
      )}
      <span aria-hidden className="text-faint">
        •
      </span>
      <Link
        href="/kill-log"
        className="font-bold text-text hover:text-primary transition-colors"
      >
        {killTotals.killed.toLocaleString('en-GB')} killed, {killTotals.passed} survived
      </Link>
    </div>
  );
}

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
      <h3 className="text-sm font-bold text-text">Recently viewed</h3>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {items.map((pack) => (
          <Link
            key={pack.id}
            href={`/pack/${pack.id}`}
            className="flex items-center gap-3 rounded-lg border border-border bg-surface p-3 text-sm font-semibold text-text transition-colors hover:border-text/20 hover:bg-bg"
          >
            <Icon name="arrowRight" size={14} className="text-muted" />
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
}: {
  packs: Pack[];
  initialState: DiscoveryState;
  market: string;
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

  // Spotlight the newest survivor only on the unfiltered, unsorted, full view, when it is
  // genuinely "newest" and there is a grid behind it to anchor. Drawn from the visitor's own
  // market only: the single biggest promotional slot on the page boosting a pack from a market
  // that then gets "Also available" below it would be the opposite of the point.
  const spotlight =
    !filtered && sort === 'newest' && grouped.matching.length > 2 ? grouped.matching[0] : null;
  const gridPacks = spotlight ? grouped.matching.slice(1) : grouped.matching;

  // Trending: top 3 by source count, only on unfiltered default view
  const trending = React.useMemo(() => {
    if (filtered || sort !== 'newest') return [];
    return [...packs]
      .filter((p) => typeof p.sourceCount === 'number' && p.sourceCount > 0)
      .sort((a, b) => (b.sourceCount ?? 0) - (a.sourceCount ?? 0))
      .slice(0, 3);
  }, [filtered, sort, packs]);

  if (packs.length === 0) {
    return (
      <div className=" border border-dashed border-border bg-surface py-20 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-bg text-muted">
          <Icon name="search" size={20} />
        </div>
        <p className="font-semibold text-text">No packs are live right now.</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted">
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
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border border-border bg-bg/60 px-4 py-3 text-sm">
          <span className="text-text">Showing packs for {marketLabel(market)} first.</span>
          {/* Sets the `market` cookie server-side (getServerSideProps) on the next request, so
              the switch survives past this one click, not just this one page load. */}
          <Link
            href={`/?market=${DEFAULT_MARKET}`}
            className="whitespace-nowrap font-semibold text-primary hover:underline"
          >
            Switch to {marketLabel(DEFAULT_MARKET)}
          </Link>
        </div>
      )}

      {/* Progressive discovery -- first thing in the catalog. No border box. */}
      <div className="mb-6">
        <StepFlow packs={packs} state={state} onChange={apply} />
      </div>

      {/* Toolbar: search, count, sort. */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:w-64">
          <SearchTrigger onOpen={() => setOpen(true)} triggerRef={triggerRef} />
        </div>
        <div className="flex items-center gap-3">
          <span className="whitespace-nowrap text-sm font-semibold text-muted">
            {visible.length} {visible.length === 1 ? 'pack' : 'packs'}
          </span>
          <div className="w-40">
            <Dropdown<SortKey> label="Sort packs" value={sort} options={SORTS} onChange={setSort} />
          </div>
        </div>
      </div>

          <AppliedFilterChips state={state} onChange={apply} className="mb-4" />



          {visible.length > 0 ? (
            <>
              <RecentlyViewed packs={packs} />
              {/* Trending picks: 3-card row, only on default unfiltered view */}
              {trending.length === 3 && (
                <div className="mb-6">
                  <h3 className="text-sm font-bold text-text mb-3">Trending picks</h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    {trending.map((pack) => (
                      <Link
                        key={pack.id}
                        href={`/pack/${pack.id}`}
                        className="group flex items-start gap-3 border border-border bg-surface p-4 transition-colors hover:bg-[#F8F5EF]"
                      >
                        <span className="flex h-8 w-8 flex-none items-center justify-center" style={{ backgroundColor: '#042F2E10' }}>
                          <Icon name="trending-up" size={16} className="text-primary" />
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-text group-hover:text-primary transition-colors truncate">
                            {pack.cardLine || pack.title}
                          </p>
                          <p className="mt-0.5 text-xs text-muted">
                            {pack.sourceCount ?? 0} sources · {formatPrice(pack.price)}
                          </p>
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              )}
              {spotlight && <SpotlightCard pack={spotlight} />}
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
                {gridPacks.map((pack, i) => (
                  <div key={pack.id} className="animate-rise" style={{ animationDelay: `${Math.min(i * 30, 300)}ms` }}>
                    <PackCard pack={pack} />
                  </div>
                ))}
              </div>
              {/* Boost, don't block: every other market's packs are still fully on the shelf,
                  clearly separated rather than mixed in or hidden. */}
              {grouped.others.map((group) => (
                <div key={group.market} className="mt-10 border-t border-border pt-8">
                  <h2 className="text-xs font-bold uppercase tracking-widest text-muted">
                    Also available, {group.label}
                  </h2>
                  <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
                    {group.packs.map((pack) => (
                      <PackCard key={pack.id} pack={pack} />
                    ))}
                  </div>
                </div>
              ))}
              <p className="mt-8 flex items-center justify-center gap-2 text-sm font-medium text-muted">
                <Icon name="shield" size={15} className="text-success" />
                Every pack carries a 14 day money back guarantee.
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
                  return pack ? <PackCard key={pack.id} pack={pack} /> : null;
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

/**
 * Why £49 once beats a subscription, side by side. Justifies the impulse price by anchoring against
 * the category the buyer is actually comparing us to.
 *
 * Deliberately no competitor is named IN THE ROWS and no capability is denied on their behalf: the
 * left column states only the things that are true by definition of a subscription idea feed (it
 * recurs, and it hands you leads you still have to vet).
 *
 * The price is the exception, and it had to become one. This block used to read "Typically $300 to
 * $1,000 a year", hedged as typical precisely because nobody could say where it came from. An
 * unnamed range is not the cautious choice it looks like, it is a number about a competitor with
 * no way for the reader to check it, on a page whose entire pitch is that we do not do that. It now
 * cites one real published plan price, named and linked, and says so is one product rather than a
 * category average (`lib/sources.ts`).
 *
 * Naming the seller for the price while keeping the rows generic is the deliberate line: their
 * price is a fact they publish, whereas "you keep nothing if you cancel" would be a claim about
 * their terms that we have not read. We cite what we checked and generalise only what is true by
 * definition.
 */
/**
 * What the method costs when you commission it, next to what it costs here.
 *
 * The brief asked for a straight price anchor, "£3,500 agency vs £49", and that exact figure is
 * the thing this block refuses to print, because nobody could tell me whose £3,500 it was. What
 * survived research is narrower and checkable: a market-research firm's own published price list,
 * with a row for the method a pack actually is. They call it documentary research; we call it
 * reading published sources until a claim either holds or dies. Same activity, their price.
 *
 * Two temptations were declined, and both would have produced a bigger number:
 *
 * A UK agency guide priced B2B market research at £15k to £80k, which is the figure a marketer would
 * pick. It is not comparable, that range buys depth interviews and commissioned surveys, primary
 * research a pack does not contain and does not claim to. Anchoring against it would inflate the
 * gap by pricing work we do not do.
 *
 * The second was to convert euros to pounds so both sides of the comparison shared a unit. That
 * needs an exchange rate the source does not print, which would make the headline number partly
 * ours. The currencies stay as published and the reader does the last step, because a comparison
 * this favourable has to be checkable to be worth making at all.
 *
 * The caveat renders with the figure rather than under an asterisk: their deliverable answers a
 * question a client brings them, and a pack answers one we chose. That difference is the actual
 * reason the price can be £49, so burying it would be arguing badly as well as dishonestly.
 */
function MethodCostAnchor() {
  const documentary = citedFigure('documentary-research');
  return (
    <div className="mt-12 border border-border bg-bg/40 p-6 md:p-8">
      <h3 className="text-xl font-bold tracking-tight text-text md:text-2xl">
        What this costs when you commission it
      </h3>
      <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted md:text-base">
        A pack is desk research: published sources, read until a claim either holds or dies. Firms
        sell that by the project, and publish what they charge for it.
      </p>

      <dl className="mt-6 grid gap-5 sm:grid-cols-2">
        <div className="bg-surface p-5 border border-border">
          <dt className="font-mono text-[10px] font-bold uppercase tracking-widest text-faint">
            {documentary.publisher}, {new Date(documentary.publishedOn ?? documentary.checkedOn).getFullYear()} price list
          </dt>
          <dd className="mt-2 text-sm leading-relaxed text-text/80">
            <SourcedFigure id="documentary-research" />
            <span className="mt-1 block text-xs text-muted">for {documentary.of}</span>
          </dd>
        </div>
        <div className="bg-surface p-5 border border-success/30">
          <dt className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
            A pack, already run
          </dt>
          <dd className="mt-2 text-sm leading-relaxed text-text/80">
            <span className="font-semibold text-text">£49</span>
            <span className="mt-1 block text-xs text-muted">
              one payment, {PACK_CONTENTS.length} documents, every claim sourced
            </span>
          </dd>
        </div>
      </dl>

      <p className="mt-5 max-w-[68ch] text-xs leading-relaxed text-faint">
        <SourcedCaveat id="documentary-research" />
      </p>
    </div>
  );
}

function ComparisonBlock() {
  const rows: { label: string; feed: string; pack: string }[] = [
    { label: 'What you pay', feed: 'Every year, for as long as you want access', pack: 'Once. No renewal, no seat fees' },
    // Counted, never typed. This row said "four documents" while the bundle had grown to eight,
    // the same drift `PACK_CONTENTS` was made the single source of truth to end, surviving in a
    // table two hundred lines away from it.
    { label: 'What arrives', feed: 'A stream of raw leads and trend signals', pack: `One finished opportunity, ${PACK_CONTENTS.length} documents` },
    { label: 'Who does the vetting', feed: 'You do, on every idea in the feed', pack: 'Already done: six checks, every claim sourced' },
    { label: 'Launch assets', feed: 'None. The idea is the product', pack: 'Build spec, GTM plan, ops, unit economics and launch copy' },
    { label: 'If you cancel', feed: 'Access ends, you keep nothing', pack: 'Yours forever, plus 14 day money back' },
  ];
  return (
    <div className="mt-14">
      <h2 className="text-xl font-bold tracking-tight text-text md:text-2xl">Why £49 once, not another subscription</h2>
      <p className="mt-2 max-w-[64ch] text-sm leading-relaxed text-muted md:text-base">
        Idea feeds and trend tools sell you the search. We sell you the answer to one.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Left: the category being compared against */}
        <div className="flex flex-col border border-border bg-bg/50 p-6">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-text/5 text-muted">
              <Icon name="close" size={14} />
            </span>
            <span className="text-base font-bold text-text/70">Subscription idea feeds</span>
          </div>
          <p className="mt-1.5 text-sm text-muted">
            <SourcedFigure id="idea-feed-entry-plan" />
          </p>
          <p className="mt-1 text-xs leading-relaxed text-faint">
            <SourcedCaveat id="idea-feed-entry-plan" />
          </p>
          <dl className="mt-5 space-y-3.5">
            {rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-0.5">
                <dt className="font-mono text-[10px] font-bold uppercase tracking-widest text-faint">{r.label}</dt>
                <dd className="text-sm leading-relaxed text-text/65">{r.feed}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Right: the offer */}
        <div className="flex flex-col border-2 border-success/40 bg-surface p-6">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-success/10 text-success">
              <Icon name="check" size={14} />
            </span>
            <span className="text-base font-bold text-text">A Mumchimp Pack</span>
          </div>
          <p className="mt-1.5 text-sm font-semibold text-success">£49 one time, yours forever</p>
          <dl className="mt-5 space-y-3.5">
            {rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-0.5">
                <dt className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">{r.label}</dt>
                <dd className="text-sm font-medium leading-relaxed text-text/85">{r.pack}</dd>
              </div>
            ))}
          </dl>
          <Link
            href="#catalog"
            className="mt-6 inline-flex items-center justify-center gap-2 rounded-md bg-primary px-6 py-3 text-sm font-medium text-white transition-all hover:bg-primary-hover"
          >
            Browse the packs <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function Home({ packs, stats, initialState, market }: HomeProps) {
  // Never a literal. The catalogue grows on every PASS, so the only honest number is the one the
  // API just reported; with no stats endpoint answer we fall back to what we were actually sent.
  const survived = stats?.listed ?? packs.length;
  const { variant } = useCopyVariant();
  return (
    // One drawer for the whole shelf. Inside MarketingLayout so the drawer's own Modal renders
    // above the header, and so a card anywhere on the page can reach it without prop threading.
    <BuyDrawerProvider>
    <MarketingLayout>
      <Seo
        title="Business ideas that survived six brutal checks. Researched and ready to build, £49 each"
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
      <SectionBand bg="white" width="6xl" className="pt-4 pb-3 md:pt-4 md:pb-3 text-center animate-rise">
        <p className="mb-1.5 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Stress tested business ideas · £49 each
        </p>
        {/* The cap is in rem, NOT ch, and that is the whole point. `ch` is the advance width of
            "0", so it means a different number of pixels in every font: the old max-w-[24ch]
            measured 576px in SF Pro but 819px in Verdana. That made the headline's line count a
            function of which font the platform happened to pick, back when --font-sans named
            "Inter" and nothing ever downloaded it, so every OS picked a different one. macOS
            landed on 2 lines and CI Linux on 3, putting the first card at y=718.5 with 1.5px
            showing. Measured minimum width for 2 lines: SF Pro 652px, Arial/Liberation 736px,
            Tahoma 768px, Verdana 872px, 56rem (896px) clears all of them. It does not widen the
            headline, because text-balance shortens the lines to even them up: the longest
            rendered line is 677px, narrower than the 736px box this replaces.

            globals.css now really does load and apply Hanken Grotesk, so the platform no longer
            gets a vote, but the absolute cap stays, and stays the thing under test. It is what
            makes this headline survive the font being slow, blocked, or swapped: measured with
            the family forced to each of Verdana/Tahoma/Georgia/Courier New/Arial, the line count
            is still 2 and the first card still clears the fold by 88px at worst. */}
        <h1 className="mx-auto max-w-[56rem] text-balance text-3xl font-bold leading-[1.08] tracking-tight text-text md:text-5xl">
          {variant.globalHookLead}
        </h1>
        <p className="mx-auto mt-2 max-w-[64ch] text-base leading-relaxed text-text/75 hidden sm:block">
          {variant.globalHookDescription}
        </p>
        {/* Hero CTA: ghost button so it doesn't compete with Buy buttons below */}
        <div className="mt-4 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="/sample"
            onClick={() => track('sample_cta_clicked')}
            className="inline-flex w-full items-center justify-center gap-2 border-2 border-primary px-6 py-3 text-sm font-bold text-primary transition-all hover:bg-primary/5 sm:w-auto"
          >
            Read a free report, no email
          </Link>
        </div>
        <p className="mt-2 text-sm font-medium text-muted">
          A whole dossier, unredacted, every source clickable. No payment, no email.
        </p>
      </SectionBand>

      <div id="catalog" className="scroll-mt-20" />
      <Section bg="bg" width="7xl" className="!pt-2 !pb-[calc(4rem+env(safe-area-inset-bottom,0px))] md:!pt-3 md:!pb-20">
        <div className="mb-2 flex-wrap items-end justify-between gap-x-6 gap-y-3 hidden sm:flex">
          <div>
            <h2 className="text-2xl font-black tracking-tight text-text md:text-3xl">What survived</h2>
            <p className="mt-1.5 max-w-[70ch] text-sm text-text/75">
              A pack is listed only once it clears every check, with a clickable source behind every
              claim. Most ideas never make it.
            </p>
          </div>
          <Heartbeat packs={packs} stats={stats} />
        </div>

        <CatalogBrowser packs={packs} initialState={initialState} market={market} />
      </Section>

      {/* 3. WHAT YOU GET, the deliverable breakdown. Format ambiguity is the biggest killer on a
             digital download page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">What you get for £49</span>}
        intro={`One finished opportunity, already vetted, in ${PACK_CONTENTS.length} documents you own outright. No subscription, no drip feed, no upsell.`}
        className="!py-14 md:!py-20"
      >
        {/* The four terms of the sale. They were in the hero, where they cost ~75px directly
            above the shelf; they answer "what am I actually buying and what if it's wrong?",
            which is a question asked at the deliverable list, not at the headline. */}
        <div className="mb-8 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <TrustPill icon="money" label="£49, one payment" />
          <TrustPill icon="shield" label="14 day money back" />
          <TrustPill icon="check" label="Every claim sourced" />
          <TrustPill icon="download" label="Instant download" />
        </div>
        <PackContentsSection heading="What’s inside your download" />
        {/* The list above names the documents; this shows one. The fear on a digital download
            page is paying £49 for a two-page Google Doc, and a noun does not answer it. Real
            rows from the free sample, including the check that failed, a preview of eight
            green ticks would advertise better and claim something the shop does not. */}
        <DossierPreview />
        <MethodCostAnchor />
        <ComparisonBlock />
      </Section>

      {/* 4. WHY TRUST IT, condensed reassurance, sits below the shelf, not above it. */}
      <SectionBand bg="band" width="6xl" className="py-14 md:py-20">
        <div className="grid items-center gap-10 md:grid-cols-[1.4fr_1fr]">
          <div>
            <p className="mb-4 font-mono text-xs font-bold uppercase tracking-[0.2em] text-on-band-faint">
              Why you can trust this
            </p>
            <h2 className="max-w-[22ch] text-balance text-3xl font-bold leading-tight tracking-tight text-white md:text-4xl">
              Stress tested the way a skeptical investor would.
            </h2>
            <p className="mt-6 max-w-xl text-base leading-relaxed text-on-band-muted md:text-lg">
              Every opportunity walks into a room built to destroy it. Six hard checks: real demand, a payer
              who can actually pay, room past the incumbents, a route to market, and legality. Anything that
              cannot back a claim with a real source dies before it reaches this store. What you see is
              everything that survived.
            </p>
            {/* Two links, because this band makes two different promises. "How it works"
                describes the process; the kill log is the only thing on the site that proves
                it ran, the rejects, with the sourced argument that killed each one. A
                stranger who doubts the claim above needs evidence, not a longer description. */}
            <div className="mt-7 flex flex-wrap items-center gap-x-7 gap-y-3">
              <Link
                href="/kill-log"
                className="inline-flex items-center gap-2 text-sm font-bold text-white underline underline-offset-4 transition-opacity hover:opacity-80"
              >
                See the {killTotals.killed.toLocaleString('en-GB')} we rejected
                <Icon name="arrowRight" size={15} />
              </Link>
              <Link
                href="/how-it-works"
                className="inline-flex items-center gap-2 text-sm font-bold text-white underline-offset-4 transition-opacity hover:opacity-80"
              >
                See exactly how it works
                <Icon name="arrowRight" size={15} />
              </Link>
            </div>
          </div>

          <ul className="space-y-3">
            {['We tried to disprove the demand. It was real.', 'We tried to prove no one pays. Someone does.', 'We tried to crown the incumbents. There was room.', 'We tried to break every claim. Each cites a source.'].map((item) => (
              <li key={item} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3.5">
                <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-success/20 text-white">
                  <Icon name="check" size={13} />
                </span>
                <span className="text-sm font-medium text-white">{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </SectionBand>

      <Section bg="white" width="4xl" className="!py-10 md:!py-12">
        <div className="border border-border bg-bg/40 p-6 md:p-8">
          <h2 className="text-lg font-bold tracking-tight text-text md:text-xl">
            Want the next one, when it survives?
          </h2>
          <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-muted">
            Most ideas we run die on the incumbent test, so this is not a weekly send, there is
            nothing to send most weeks. Leave an address and you get one email on the day a pack
            clears all six checks. The sample above stays free either way, and this form is not in
            front of it.
          </p>
          <div className="mt-5">
            <WaitlistForm source="home-after-sample" submitLabel="Email me when one survives" />
          </div>
        </div>
      </Section>

      <CtaBand
        title="Find your next business for £49."
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

  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    return {
      props: { packs, stats, initialState, market },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [], stats: null, initialState, market },
    };
  }
};

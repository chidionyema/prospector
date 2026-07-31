import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, IconName, Dropdown } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SectionBand, Section, CtaBand } from '@/components/marketing/blocks';
import { PackContentsSection } from '@/components/marketing/PackContents';
import { AddToCartButton } from '@/components/cart/AddToCartButton';
import { CommandPalette, SearchTrigger, useCommandPalette } from '@/components/discovery/CommandPalette';
import { DiscoveryNearMiss, DiscoveryWaitlist, missLabelFor, type NearMissCandidate } from '@/components/discovery/EmptyState';
import { FacetBar } from '@/components/discovery/FacetBar';
import { FacetChips } from '@/components/discovery/FacetChips';
import { Matchmaker } from '@/components/discovery/Matchmaker';
import { fetchCatalog, fetchCatalogStats, formatPrice, freshnessLabel, marketLabel, Pack, CatalogStats } from '@/lib/api/client';
import { categoryFor, type Category } from '@/lib/category';
import {
  decodeDiscoveryState,
  encodeDiscoveryState,
  filterPacks,
  isFiltered,
  nearMisses,
  splitTitle,
  type DiscoveryState,
} from '@/lib/discovery';
import { KIND_LABEL } from '@/lib/facets';

interface HomeProps {
  packs: Pack[];
  stats: CatalogStats | null;
  /** Discovery state decoded from the query string on the server, so a shared filtered link
   *  renders filtered in the HTML rather than flashing the whole catalogue first. */
  initialState: DiscoveryState;
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

// The four deliverables inside every pack, as scannable icon chips. Matches the real bundle
// manifest — see the audit note in components/marketing/PackContents.tsx.
const DELIVERABLES: { icon: IconName; label: string }[] = [
  { icon: 'briefcase', label: 'Blueprint' },
  { icon: 'handshake', label: 'GTM plan' },
  { icon: 'code', label: 'Ops & numbers' },
  { icon: 'verified', label: 'Sources' },
];

/** One scannable label/value row on a card. Clamped hard: a card is read in three seconds, so a
 *  long engine-written sentence has to truncate rather than push the CTA off the shelf. */
function CardFact({ label, children, clamp = 'line-clamp-2' }: { label: string; children: React.ReactNode; clamp?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">{label}</span>
      <span className={cx('text-xs leading-relaxed text-text/75', clamp)}>{children}</span>
    </div>
  );
}

function DeliverableChips() {
  return (
    <div className="flex flex-wrap gap-1.5">
      {DELIVERABLES.map((d) => (
        <span
          key={d.label}
          className="inline-flex items-center gap-1.5 rounded-md bg-bg px-2 py-1 text-[11px] font-semibold text-muted"
        >
          <Icon name={d.icon} size={12} /> {d.label}
        </span>
      ))}
    </div>
  );
}

// Colour-coded sector label. `onLight` sits on a white card body; the default glass pill sits on the
// coloured cover.
function CategoryPill({ cat, onLight = false }: { cat: Category; onLight?: boolean }) {
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

// The authority mark: every pack on the shelf cleared all six checks. Reads as a struck seal, not a
// loose word in a box.
function SurvivedSeal() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-text/85 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-white shadow-sm backdrop-blur">
      <Icon name="verified" size={13} className="text-emerald-300" /> Survived 6 checks
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

function PackCard({ pack }: { pack: Pack }) {
  const cat = categoryFor(pack);
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  return (
    <Link
      href={`/pack/${pack.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:-translate-y-1 hover:border-text/15 hover:shadow-[0_18px_40px_rgba(0,0,0,0.10)]"
    >
      <Cover cat={cat} iconSize={132} className="h-36">
        <span className="absolute left-4 top-4">
          <CategoryPill cat={cat} />
        </span>
        <span className="absolute right-4 top-4 rounded-lg bg-white px-3 py-1 text-lg font-black tracking-tight text-text shadow-sm">
          {formatPrice(pack.price)}
        </span>
        <span className="absolute bottom-4 left-4">
          <SurvivedSeal />
        </span>
      </Cover>

      <div className="flex flex-1 flex-col p-6">
        {/* Name first, engine-written descriptor demoted: eleven 25-word titles is not a shelf. */}
        <h3 className="text-lg font-bold leading-snug tracking-tight text-text transition-colors group-hover:text-primary">
          {name}
        </h3>
        {/* Given real weight (sm/text-80, not xs/muted). The name stays the H3 — a live
            descriptor runs to 90+ chars ("PitchCall Forensics — The Under-27 Gig Driver's
            Insurance-Refusal Reversal & Telematics-Data Subject-Access Round"), so promoting it
            to the heading gives twenty cards of wrapped bold text instead of a scannable shelf.
            But "PitchBrief" alone means nothing to a first-time visitor, so what the thing
            actually DOES can no longer be the quietest line on the card. */}
        {descriptor && (
          <p className="mt-1.5 line-clamp-2 text-sm font-medium leading-relaxed text-text/80">{descriptor}</p>
        )}

        {/* Scannable label/value rows, not a paragraph. `Who pays` is gone: the payer facet chip
            says the same thing in two words, and the engine's sentence pushed the CTA off the card. */}
        <div className="mt-4 space-y-3">
          {pack.oneLine && <CardFact label="The opportunity">{pack.oneLine}</CardFact>}
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">Deliverables</span>
            <DeliverableChips />
          </div>
        </div>

        {/* Renders nothing at all when the engine could not justify a facet — an untagged pack
            shows no chips rather than a guessed one. */}
        <FacetChips pack={pack} compact max={4} className="mt-4" />

        {(pack.market || pack.timeToFirstRevenue || pack.sourceCount || freshnessLabel(pack.verifiedAt)) && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {pack.market && (
              <span className="rounded-md bg-primary/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
                {marketLabel(pack.market)}
              </span>
            )}
            {pack.timeToFirstRevenue && (
              <span className="rounded-md bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
                Revenue in {pack.timeToFirstRevenue}
              </span>
            )}
            {typeof pack.sourceCount === 'number' && pack.sourceCount > 0 && (
              <span className="rounded-md bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
                {pack.sourceCount} sources
              </span>
            )}
            {freshnessLabel(pack.verifiedAt) && (
              <span className="rounded-md bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
                {freshnessLabel(pack.verifiedAt)}
              </span>
            )}
          </div>
        )}

        {/* Active CTA at the price, not a passive "see what is inside". The basket toggle sits
            beside it rather than replacing it: opening the pack stays the primary action, and a
            shelf where every card demands a cart decision is a worse shelf. */}
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border/70 pt-4">
          <span className="text-sm font-bold text-text transition-colors group-hover:text-primary">
            View vetted blueprint ({formatPrice(pack.price)})
          </span>
          <div className="flex flex-none items-center gap-2">
            <AddToCartButton
              size="compact"
              line={{ id: pack.id, title: name, price: pack.price }}
            />
            <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-bg text-text transition-all group-hover:bg-primary group-hover:text-white">
              <Icon name="arrowRight" size={15} />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}

// The hero of the shelf: the newest survivor, given real visual weight (full width, horizontal) so
// the grid is not eleven identical blocks. Anchors the page and breaks the pattern.
function SpotlightCard({ pack }: { pack: Pack }) {
  const cat = categoryFor(pack);
  const { name, descriptor } = splitTitle(pack.title, pack.headline);
  return (
    <Link
      href={`/pack/${pack.id}`}
      className="group relative mb-6 flex flex-col overflow-hidden rounded-3xl border border-border bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:-translate-y-0.5 hover:border-text/15 hover:shadow-[0_24px_50px_rgba(0,0,0,0.12)] md:flex-row"
    >
      <Cover cat={cat} iconSize={240} className="min-h-[210px] md:w-[38%]">
        <span className="absolute left-5 top-5 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-text shadow-sm backdrop-blur">
          <Icon name="trending-up" size={12} className={cat.accent} /> Latest to survive
        </span>
        <span className="absolute bottom-5 left-5">
          <SurvivedSeal />
        </span>
      </Cover>

      <div className="flex flex-1 flex-col justify-center gap-4 p-7 md:p-9">
        <div className="flex flex-wrap items-center gap-3">
          <CategoryPill cat={cat} onLight />
          <span className="text-sm font-semibold text-muted">Newest in the catalogue</span>
        </div>
        <h3 className="text-2xl font-black leading-tight tracking-tight text-text transition-colors group-hover:text-primary md:text-3xl">
          {name}
        </h3>
        {descriptor && <p className="max-w-2xl text-base leading-relaxed text-text/75 line-clamp-2">{descriptor}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <CardFact label="The opportunity">{pack.oneLine}</CardFact>
        </div>
        <FacetChips pack={pack} />
        <DeliverableChips />
        <div className="mt-1 flex flex-wrap items-center gap-4">
          <span className="text-2xl font-black tracking-tight text-text">{formatPrice(pack.price)}</span>
          <span className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-sm transition group-hover:opacity-90">
            View vetted blueprint <Icon name="arrowRight" size={15} />
          </span>
          <AddToCartButton size="compact" line={{ id: pack.id, title: name, price: pack.price }} />
        </div>
      </div>
    </Link>
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
    <div className="inline-flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-full border border-border bg-white px-4 py-2 text-xs font-semibold text-muted shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
      <span className="inline-flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
        </span>
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
          <span>{stats.listed} live now</span>
        </>
      )}
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

/** Buyer-facing name for the one filter a near-miss pack fails. */
function relaxLabelFor(kind: keyof typeof KIND_LABEL): string {
  return `Show any ${KIND_LABEL[kind].toLowerCase()}`;
}

/**
 * The shelf, driven by the discovery state (spec Parts 4, 6, 7).
 *
 * Filtering is client-side over the packs the server already sent, and the state round-trips
 * through the URL so a filtered shelf is a link someone can send. The URL update is `shallow`:
 * the packs are already here, so re-running `getServerSideProps` would be a network round trip
 * that changes nothing on screen.
 */
function CatalogBrowser({ packs, initialState }: { packs: Pack[]; initialState: DiscoveryState }) {
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

  // Only computed when the shelf came back empty — the near-miss row exists to rescue that case.
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

  // Spotlight the newest survivor only on the unfiltered, unsorted, full view — when it is
  // genuinely "newest" and there is a grid behind it to anchor.
  const spotlight = !filtered && sort === 'newest' && visible.length > 2 ? visible[0] : null;
  const gridPacks = spotlight ? visible.slice(1) : visible;

  if (packs.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-white py-20 text-center">
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
      <div className="mb-10">
        <Matchmaker packs={packs} onShowAll={apply} onNoMatch={apply} />
      </div>

      <div className="grid gap-8 lg:grid-cols-[15rem_1fr]">
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <FacetBar packs={packs} state={state} onChange={apply} />
        </aside>

        <div>
          <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="w-full sm:max-w-xs">
              <SearchTrigger onOpen={() => setOpen(true)} triggerRef={triggerRef} />
            </div>
            <div className="flex items-center gap-3 sm:justify-end">
              <span className="whitespace-nowrap text-sm font-semibold text-muted">
                {visible.length} {visible.length === 1 ? 'pack' : 'packs'}
              </span>
              <div className="w-52">
                <Dropdown<SortKey> label="Sort packs" value={sort} options={SORTS} onChange={setSort} />
              </div>
            </div>
          </div>

          {visible.length > 0 ? (
            <>
              {spotlight && <SpotlightCard pack={spotlight} />}
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
                {gridPacks.map((pack) => (
                  <PackCard key={pack.id} pack={pack} />
                ))}
              </div>
              <p className="mt-8 flex items-center justify-center gap-2 text-sm font-medium text-muted">
                <Icon name="shield" size={15} className="text-success" />
                Every pack carries a 14 day money back guarantee.
              </p>
            </>
          ) : candidates.length > 0 ? (
            /* A. Something is one facet away — sell that before asking for an email address. */
            <DiscoveryNearMiss candidates={candidates} onRelax={apply}>
              <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2">
                {candidates.map((candidate) => {
                  const pack = packs.find((p) => p.id === candidate.pack.id);
                  return pack ? <PackCard key={pack.id} pack={pack} /> : null;
                })}
              </div>
            </DiscoveryNearMiss>
          ) : (
            /* B. Nothing in the catalogue comes close. Only now is an email address the honest ask. */
            <DiscoveryWaitlist query={state.q} />
          )}
        </div>
      </div>

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
 * Deliberately no competitor is named and no capability is denied on their behalf: the left column
 * states only the two things that are true by definition of a subscription idea feed (it recurs, and
 * it hands you leads you still have to vet). The "$300 to $1,000 a year" range is the figure this
 * page already carried before this rewrite — it is unsourced, so it is hedged as "typically".
 */
function ComparisonBlock() {
  const rows: { label: string; feed: string; pack: string }[] = [
    { label: 'What you pay', feed: 'Every year, for as long as you want access', pack: 'Once. No renewal, no seat fees' },
    { label: 'What arrives', feed: 'A stream of raw leads and trend signals', pack: 'One finished opportunity, four documents' },
    { label: 'Who does the vetting', feed: 'You do, on every idea in the feed', pack: 'Already done: six checks, every claim sourced' },
    { label: 'Launch assets', feed: 'None. The idea is the product', pack: 'Build spec, GTM plan, ops and unit economics' },
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
        <div className="flex flex-col rounded-2xl border border-border bg-bg/50 p-6">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-text/5 text-muted">
              <Icon name="close" size={14} />
            </span>
            <span className="text-base font-bold text-text/70">Subscription idea feeds</span>
          </div>
          <p className="mt-1.5 text-sm font-semibold text-muted">Typically $300 to $1,000 a year</p>
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
        <div className="flex flex-col rounded-2xl border-2 border-success/40 bg-white p-6 shadow-[0_8px_30px_rgba(0,0,0,0.05)]">
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
            className="mt-6 inline-flex items-center justify-center gap-2 rounded-xl bg-text px-6 py-3.5 text-sm font-bold uppercase tracking-wide text-white transition-all hover:-translate-y-0.5"
          >
            Browse the packs <Icon name="arrowRight" size={15} />
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function Home({ packs, stats, initialState }: HomeProps) {
  // Never a literal. The catalogue grows on every PASS, so the only honest number is the one the
  // API just reported; with no stats endpoint answer we fall back to what we were actually sent.
  const survived = stats?.listed ?? packs.length;
  return (
    <MarketingLayout>
      <Seo title="Business ideas that survived six brutal checks. Researched and ready to build, £49 each" />

      {/* 1. HERO — short. A storefront states what it sells and moves you to the shelf. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10 text-center animate-rise">
        <p className="mb-5 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Stress tested business ideas · £49 each
        </p>
        <h1 className="mx-auto max-w-[22ch] text-balance text-4xl font-bold leading-[1.08] tracking-tight text-text md:text-6xl">
          Skip 6 months of research. Launch a business that&apos;s already vetted.
        </h1>
        <p className="mx-auto mt-6 max-w-[60ch] text-base leading-relaxed text-text/75 md:text-lg">
          Stop wasting weekends building ideas nobody will pay for. Each £49 Mumchimp Pack gives you a fully
          researched, market-validated business blueprint: who the buyer is, what they pay, the pricing and
          unit economics, and a step-by-step go-to-market plan. Every claim backed by a real source you can
          open.
        </p>
        <div className="mx-auto mt-8 flex max-w-3xl flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <TrustPill icon="money" label="£49, one payment" />
          <TrustPill icon="shield" label="14 day money back" />
          <TrustPill icon="check" label="Every claim sourced" />
          <TrustPill icon="download" label="Instant download" />
        </div>
        {/* Two clear next actions: the shelf for buyers, the free report for the sceptical. */}
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="#catalog"
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-text px-8 py-4 text-sm font-bold uppercase tracking-wide text-white shadow-[0_4px_16px_rgba(15,23,42,0.18)] transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.24)] sm:w-auto"
          >
            {survived > 0 ? `See the ${survived} that survived` : 'Browse vetted blueprints'} — £49
          </Link>
          <Link
            href="/sample"
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-border bg-white px-8 py-4 text-sm font-bold text-text transition-colors hover:border-text/30 sm:w-auto"
          >
            <Icon name="download" size={15} className="text-primary" />
            Read the free sample report
          </Link>
        </div>
        <p className="mt-4 text-sm font-medium text-muted">
          One whole verification dossier, unredacted, every source clickable. Zero pence, no email needed.
        </p>
      </SectionBand>

      {/* 2. THE STORE — products lead. This is the page; everything else is reassurance below it. */}
      <div id="catalog" className="scroll-mt-20" />
      <Section bg="bg" width="7xl" className="!pt-8 !pb-16 md:!pt-10 md:!pb-20">
        <div className="mb-6">
          <div className="mb-4">
            <Heartbeat packs={packs} stats={stats} />
          </div>
          <h2 className="text-2xl font-black tracking-tight text-text md:text-3xl">What survived</h2>
          <p className="mt-2 max-w-[60ch] text-base text-text/75">
            We list a pack only when it clears every check, with a clickable source behind every claim.
            Most ideas never make it. £49 each, yours the moment you pay.
          </p>
          {stats && stats.registered > stats.listed && (
            <p className="mt-3 inline-flex items-center gap-2 rounded-full bg-success/5 px-3 py-1.5 text-xs font-semibold text-success">
              <Icon name="shield" size={13} />
              {stats.listed} live now, of {stats.registered} that reached final packaging.
            </p>
          )}
        </div>

        <CatalogBrowser packs={packs} initialState={initialState} />
      </Section>

      {/* 3. WHAT YOU GET — the deliverable breakdown. Format ambiguity is the biggest killer on a
             digital download page: the buyer's real fear is paying £49 for a two-page Google Doc. */}
      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">What you get for £49</span>}
        intro="One finished opportunity, already vetted, in four documents you own outright. No subscription, no drip feed, no upsell."
        className="!py-14 md:!py-20"
      >
        <PackContentsSection heading="What’s inside your download" />
        <ComparisonBlock />
      </Section>

      {/* 4. WHY TRUST IT — condensed reassurance, sits below the shelf, not above it. */}
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
            <Link
              href="/how-it-works"
              className="mt-7 inline-flex items-center gap-2 text-sm font-bold text-white underline-offset-4 transition-opacity hover:opacity-80"
            >
              See exactly how it works
              <Icon name="arrowRight" size={15} />
            </Link>
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

      <CtaBand
        title="Find your next business for £49."
        lead="One payment. Every claim sourced. 14 day money back guarantee."
        primary={{ href: '#catalog', label: 'Browse the packs' }}
        secondary={{ href: '/how-it-works', label: 'How it works' }}
      />
    </MarketingLayout>
  );
}

export const getServerSideProps: GetServerSideProps = async (context) => {
  // Decoded server-side: out-of-vocabulary values in a hand-edited URL are dropped rather than
  // filtering the shelf down to nothing on a value no pack can ever carry.
  const initialState = decodeDiscoveryState(context.query);
  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    return {
      props: { packs, stats, initialState },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [], stats: null, initialState },
    };
  }
};

import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, IconName, Input, Dropdown, Button } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import { SectionBand, Section, FeatureCard, CtaBand } from '@/components/marketing/blocks';
import { fetchCatalog, fetchCatalogStats, formatPrice, freshnessLabel, Pack, CatalogStats } from '@/lib/api/client';
import { categoryFor, type Category } from '@/lib/category';

interface HomeProps {
  packs: Pack[];
  stats: CatalogStats | null;
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

// The three deliverables inside every pack, as scannable icon chips.
const DELIVERABLES: { icon: IconName; label: string }[] = [
  { icon: 'briefcase', label: 'Blueprint' },
  { icon: 'handshake', label: 'GTM plan' },
  { icon: 'code', label: 'Build kit' },
];

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
        <h3 className="text-lg font-bold leading-snug tracking-tight text-text transition-colors group-hover:text-primary">
          {pack.title}
        </h3>
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-text/70">{pack.oneLine}</p>

        {pack.whoPays || pack.effortTag || pack.timeToFirstRevenue ? (
          // Per-pack specifics out-sell generic deliverable chips: name the buyer and the shape.
          <div className="mt-4 space-y-2.5">
            {pack.whoPays && (
              <p className="line-clamp-2 text-xs leading-relaxed text-text/70">
                <span className="font-semibold text-text">Who pays.</span> {pack.whoPays}
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              {pack.effortTag && (
                <span className="rounded-md bg-bg px-2 py-1 text-[11px] font-semibold capitalize text-muted">
                  {pack.effortTag} effort
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
          </div>
        ) : (
          <div className="mt-5">
            <DeliverableChips />
          </div>
        )}

        <div className="mt-6 flex items-center justify-between border-t border-border/70 pt-4">
          <span className="text-sm font-bold text-text transition-colors group-hover:text-primary">See what is inside</span>
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-bg text-text transition-all group-hover:bg-primary group-hover:text-white">
            <Icon name="arrowRight" size={15} />
          </span>
        </div>
      </div>
    </Link>
  );
}

// The hero of the shelf: the newest survivor, given real visual weight (full width, horizontal) so
// the grid is not eleven identical blocks. Anchors the page and breaks the pattern.
function SpotlightCard({ pack }: { pack: Pack }) {
  const cat = categoryFor(pack);
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
          {pack.title}
        </h3>
        <p className="max-w-2xl text-base leading-relaxed text-text/75 line-clamp-3">{pack.oneLine}</p>
        <DeliverableChips />
        <div className="mt-1 flex flex-wrap items-center gap-4">
          <span className="text-2xl font-black tracking-tight text-text">{formatPrice(pack.price)}</span>
          <span className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-sm transition group-hover:opacity-90">
            See what is inside <Icon name="arrowRight" size={15} />
          </span>
        </div>
      </div>
    </Link>
  );
}

// Colour-coded sector filter. Turns the catalogue from a list into a discovery tool.
function FilterPill({
  active,
  onClick,
  label,
  count,
  icon,
  accent,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  icon?: IconName;
  accent?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        'inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-semibold transition',
        active
          ? 'border-text bg-text text-white shadow-sm'
          : 'border-border bg-white text-text/70 hover:border-text/30 hover:text-text',
      )}
    >
      {icon && <Icon name={icon} size={14} className={active ? 'text-white' : accent} />}
      {label}
      <span className={cx('rounded-full px-1.5 text-xs font-bold', active ? 'bg-white/20 text-white' : 'bg-bg text-muted')}>
        {count}
      </span>
    </button>
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

/**
 * Client-side catalog browser: search (title + one-line) and sort over the packs the server already
 * sent. Pure client filtering is right while the catalogue is small (tens of packs); a server-side
 * query (`/catalog?q=&sort=`) and lane/sector filters are the next step once packs carry taxonomy.
 */
function CatalogBrowser({ packs }: { packs: Pack[] }) {
  const [query, setQuery] = React.useState('');
  const [sort, setSort] = React.useState<SortKey>('newest');
  const [activeCat, setActiveCat] = React.useState<string>('all');

  // Sectors actually present in the catalogue, with counts, in first-appearance order.
  const cats = React.useMemo(() => {
    const m = new Map<string, { cat: Category; count: number }>();
    for (const p of packs) {
      const c = categoryFor(p);
      const e = m.get(c.key);
      if (e) e.count += 1;
      else m.set(c.key, { cat: c, count: 1 });
    }
    return [...m.values()];
  }, [packs]);

  const visible = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = packs;
    if (activeCat !== 'all') filtered = filtered.filter((p) => categoryFor(p).key === activeCat);
    if (q) {
      filtered = filtered.filter(
        (p) => p.title.toLowerCase().includes(q) || p.oneLine.toLowerCase().includes(q),
      );
    }
    if (sort === 'newest') return filtered; // server already returns newest-first
    return [...filtered].sort((a, b) => {
      if (sort === 'title') return a.title.localeCompare(b.title);
      const delta = parseFloat(a.price) - parseFloat(b.price);
      return sort === 'price-asc' ? delta : -delta;
    });
  }, [packs, query, sort, activeCat]);

  // Spotlight the newest survivor only on the unfiltered, unsorted, full view — when it is genuinely
  // "newest" and there is a grid behind it to anchor. Otherwise every result is an equal grid card.
  const spotlight =
    activeCat === 'all' && !query.trim() && sort === 'newest' && visible.length > 2 ? visible[0] : null;
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
      {cats.length > 1 && (
        <div className="mb-5 flex flex-wrap gap-2">
          <FilterPill active={activeCat === 'all'} onClick={() => setActiveCat('all')} label="All sectors" count={packs.length} />
          {cats.map(({ cat, count }) => (
            <FilterPill
              key={cat.key}
              active={activeCat === cat.key}
              onClick={() => setActiveCat(cat.key)}
              label={cat.label}
              count={count}
              icon={cat.icon}
              accent={cat.accent}
            />
          ))}
        </div>
      )}

      <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:max-w-xs">
          <Input
            label="Search packs"
            hideLabel
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or idea…"
          />
        </div>
        <div className="flex items-center gap-3 sm:justify-end">
          <span className="whitespace-nowrap text-sm font-semibold text-muted">
            {visible.length} {visible.length === 1 ? 'pack' : 'packs'}
          </span>
          <div className="w-52">
            <Dropdown<SortKey>
              label="Sort packs"
              value={sort}
              options={SORTS}
              onChange={setSort}
            />
          </div>
        </div>
      </div>

      {visible.length > 0 ? (
        <>
          {spotlight && <SpotlightCard pack={spotlight} />}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {gridPacks.map((pack) => (
              <PackCard key={pack.id} pack={pack} />
            ))}
          </div>
          <p className="mt-8 flex items-center justify-center gap-2 text-sm font-medium text-muted">
            <Icon name="shield" size={15} className="text-success" />
            Every pack carries a 14 day money back guarantee.
          </p>
        </>
      ) : (
        <div className="rounded-2xl border border-dashed border-border bg-white py-16 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-bg text-muted">
            <Icon name="search" size={20} />
          </div>
          <p className="font-semibold text-text">No packs match “{query.trim()}”.</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Try a broader word, or clear the search.</p>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => setQuery('')}>
              Clear search
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

export default function Home({ packs, stats }: HomeProps) {
  return (
    <MarketingLayout>
      <Seo title="Business ideas that survived six brutal checks. Researched and ready to build, £49 each" />

      {/* 1. HERO — short. A storefront states what it sells and moves you to the shelf. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10 text-center animate-rise">
        <p className="mb-5 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Stress tested business ideas · £49 each
        </p>
        <h1 className="mx-auto max-w-[18ch] text-balance text-4xl font-bold leading-[1.08] tracking-tight text-text md:text-6xl">
          We tried to kill these business ideas. They survived.
        </h1>
        <p className="mx-auto mt-6 max-w-[54ch] text-base leading-relaxed text-text/75 md:text-lg">
          Each pack is one fully researched business opportunity that cleared six brutal checks, with a
          clickable source behind every claim. Pick one below and start building something that already holds
          up.
        </p>
        <div className="mx-auto mt-8 flex max-w-3xl flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <TrustPill icon="money" label="£49, one payment" />
          <TrustPill icon="shield" label="14 day money back" />
          <TrustPill icon="check" label="Every claim sourced" />
          <TrustPill icon="download" label="Instant download" />
        </div>
        <p className="mt-7 text-sm font-semibold text-muted">
          Want proof first?{' '}
          <Link href="/sample" className="text-primary underline-offset-4 hover:underline">
            Read a full report free
          </Link>
          , every source clickable, zero pence.
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

        <CatalogBrowser packs={packs} />
      </Section>

      {/* 3. WHAT YOU GET — product detail, the three deliverables inside every pack. */}
      <Section
        bg="white"
        width="6xl"
        title={<span className="font-black">What you get for £49</span>}
        intro="Idea feeds and trend tools charge a subscription, often $300 to $1,000 a year, for a stream of leads you still have to vet yourself. This is the opposite. One finished idea, already vetted, one payment of £49, yours to keep."
        className="!py-14 md:!py-20"
      >
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <FeatureCard icon="briefcase" title="The Blueprint">
            The opportunity and the evidence behind it. The market, the gap, and why it is worth your time,
            with every claim backed by a real source.
          </FeatureCard>
          <FeatureCard icon="handshake" title="The GTM plan">
            Who actually pays, where to find them, and how to reach them, so you start with a real route to a
            paying customer instead of a guess.
          </FeatureCard>
          <FeatureCard icon="code" title="The Build Kit">
            The concrete steps to ship. The stack, the sequence, and the first moves to get from idea to first
            revenue without guesswork.
          </FeatureCard>
        </div>
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

export const getServerSideProps: GetServerSideProps = async () => {
  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    return {
      props: { packs, stats },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [], stats: null },
    };
  }
};

import React from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, CoverArt, Input, Select, Button } from '@/components/ui';
import { SectionBand, Section, FeatureCard, CtaBand } from '@/components/marketing/blocks';
import { fetchCatalog, formatPrice, Pack } from '@/lib/api/client';
import { coverFor } from '@/lib/cover';

interface HomeProps {
  packs: Pack[];
}

const INSIDE = ['Blueprint', 'GTM plan', 'Build kit'] as const;

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

function PackCard({ pack }: { pack: Pack }) {
  return (
    <Link
      href={`/pack/${pack.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:-translate-y-1 hover:border-text/15 hover:shadow-[0_18px_40px_rgba(0,0,0,0.10)]"
    >
      <div className={`relative h-36 overflow-hidden ${coverFor(pack.id)}`}>
        <CoverArt title={pack.title} />
        <span className="absolute left-4 top-4 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-text shadow-sm">
          <Icon name="verified" size={12} /> Survived
        </span>
        <span className="absolute bottom-4 right-4 rounded-lg bg-white px-3 py-1 text-lg font-black tracking-tight text-text shadow-sm">
          {formatPrice(pack.price)}
        </span>
      </div>

      <div className="flex flex-1 flex-col p-6">
        <h3 className="text-lg font-bold leading-snug tracking-tight text-text transition-colors group-hover:text-primary">
          {pack.title}
        </h3>
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-text/70">{pack.oneLine}</p>

        <div className="mt-5 flex flex-wrap gap-1.5">
          {INSIDE.map((chip) => (
            <span key={chip} className="rounded-md bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
              {chip}
            </span>
          ))}
        </div>

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

  const visible = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? packs.filter(
          (p) => p.title.toLowerCase().includes(q) || p.oneLine.toLowerCase().includes(q),
        )
      : packs;
    if (sort === 'newest') return filtered; // server already returns newest-first
    return [...filtered].sort((a, b) => {
      if (sort === 'title') return a.title.localeCompare(b.title);
      const delta = parseFloat(a.price) - parseFloat(b.price);
      return sort === 'price-asc' ? delta : -delta;
    });
  }, [packs, query, sort]);

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
          <div className="w-48">
            <Select
              label="Sort packs"
              hideLabel
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>

      {visible.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((pack) => (
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

export default function Home({ packs }: HomeProps) {
  return (
    <MarketingLayout>
      <Seo title="Validated business opportunities, researched and ready to build. £49 each" />

      {/* 1. HERO — short. A storefront states what it sells and moves you to the shelf. */}
      <SectionBand bg="white" width="6xl" className="pt-14 pb-8 md:pt-20 md:pb-10 text-center animate-rise">
        <p className="mb-5 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Validated business opportunities · £49 each
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
      </SectionBand>

      {/* 2. THE STORE — products lead. This is the page; everything else is reassurance below it. */}
      <div id="catalog" className="scroll-mt-20" />
      <Section bg="bg" width="7xl" className="!pt-8 !pb-16 md:!pt-10 md:!pb-20">
        <div className="mb-6">
          <h2 className="text-2xl font-black tracking-tight text-text md:text-3xl">What survived</h2>
          <p className="mt-2 max-w-xl text-base text-text/70">
            We list a pack only when it clears every check. Most ideas never make it. £49 each, yours the
            moment you pay.
          </p>
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
    const packs = await fetchCatalog();
    return {
      props: { packs },
    };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    return {
      props: { packs: [] },
    };
  }
};

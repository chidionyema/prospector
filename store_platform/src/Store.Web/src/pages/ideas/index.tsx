import React from 'react';
import Link from 'next/link';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { SearchInput, buttonClasses, textLinkClass } from '@/components/ui';
import { fetchCatalog } from '@/lib/api/client';
import { eligibleLandings, packMatchesLanding } from '@/lib/seo/landings';
import { priceRange, formatGbp } from '@/lib/priceRange';
import { cx } from '@/components/ui/cx';
import CategoryGraph, { type CategoryNode } from '@/components/discovery/CategoryGraph';
import BespokeIcon from '@/components/marketing/BespokeIcon';
import { resolveVariant } from '@/lib/getCopyVariant';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

/**
 * One tile of the taxonomy map.
 *
 * `low`/`high` are the real GBP bounds of the packs that actually match this landing, computed on
 * the server from the live catalogue by the same `packMatchesLanding` predicate the landing page
 * itself uses -- so the range on the tile and the packs behind the link can never disagree. They
 * are nullable because `priceRange` returns null when no matching pack carries a parseable price,
 * and a tile with no price says nothing about price rather than guessing at one.
 *
 * There is deliberately NO survival rate and NO representative kill per category, both of which
 * would be the natural third and fourth facts here. Neither is derivable: the kill log records a
 * `gate`, a `reason` and a date per rejected idea and carries no facet at all (see the entry shape
 * in `data/kill-log-examples.json`), so a per-category kill count would have to be invented and a
 * "representative kill" would have to be assigned by hand. On this storefront that is the one
 * thing a page may not do. The kill log stays whole, at /kill-log, where every record is real.
 */
interface Category {
  slug: string;
  h1: string;
  description: string;
  count: number;
  low: number | null;
  high: number | null;
}

interface Props {
  categories: Category[];
  total: number;
  variant: VariantKey;
}

export const getServerSideProps: GetServerSideProps<Props> = async (context) => {
  const { req, query } = context;
  const variant = resolveVariant(
    query.variant,
    req?.cookies?.['mumchimp.copy.variant'],
    req?.headers?.['user-agent'],
  );
  try {
    const packs = await fetchCatalog();
    return {
      props: {
        total: packs.length,
        categories: eligibleLandings(packs).map(({ landing, count }) => {
          // Same predicate the landing page filters on, so the range describes exactly the shelf
          // the tile links to. `priceRange` reads `pack.price` (a formatted string) and returns
          // null when nothing parses, which is why both bounds are nullable downstream.
          const range = priceRange(packs.filter((p) => packMatchesLanding(p, landing)));
          return {
            slug: landing.slug,
            h1: landing.h1,
            description: landing.metaDescription,
            count,
            low: range ? range.min : null,
            high: range ? range.max : null,
          };
        }),
        variant,
      },
    };
  } catch (error) {
    console.error('/ideas: catalog fetch failed:', error);
    return { props: { total: 0, categories: [], variant } };
  }
};

export default function IdeasHub({ categories, total, variant }: Props) {
  const [search, setSearch] = React.useState('');

  const filtered = React.useMemo(() => {
    // Biggest shelf first. The mosaic's two lead tiles are the two largest categories, so the
    // ordering IS the hierarchy -- without this the "lead" slot would go to whichever landing
    // `LANDINGS` happens to declare first, and the tile sizes would state a ranking that is not
    // one. Ties fall back to the name so the layout is stable across catalogue refreshes rather
    // than reshuffling every time the daemon publishes.
    if (!search.trim()) {
      return [...categories].sort((a, b) => b.count - a.count || a.h1.localeCompare(b.h1));
    }
    const q = search.toLowerCase();
    return categories.filter(
      (c) =>
        c.h1.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q),
    );
  }, [categories, search]);

  return (
    <MarketingLayout>
      <Seo
        title="Business ideas by category"
        description="Browse researched business ideas by industry. Every pack cites a source for every claim."
        jsonLd={graph(
          itemListNode(
            categories.map((c) => ({ name: c.h1, path: `/ideas/${c.slug}` })),
            'Business idea categories',
          ),
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Business ideas', path: '/ideas' },
          ]),
        )}
      />

      <PageHero
        width="7xl"
        eyebrow="Categories"
        title="Explore stress-tested ideas by industry."
        lead={
          total > 0
            ? `${total} researched packs across ${categories.length} categories. Choose your battleground.`
            : 'Researched packs, grouped by who they sell to, the hours they need, the skills they suit.'
        }
      />

      <Section bg="white" width="7xl">
        {/* Search */}
        <SearchInput
          label="Search industries, skills, or markets"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search industries, skills, or markets…"
          className="mb-8"
        />

        {/* US-7: the 2D category graph. Sized by pack count, placed by relatedness.
            Tapping a node navigates to that category's landing page. Below the
            graph, the existing flat list stays as the text fallback (some buyers
            scan text, some scan visuals - keep both). */}
        {!search && categories.length > 0 && (
          <div className="mb-10">
            <h2 className="text-meta font-semibold text-text mb-4">Browse the shape of the catalogue</h2>
            <CategoryGraph
              categories={categories.map((c) => ({
                kind: c.slug,
                label: VARIANTS[variant].categoryH1[c.slug] ?? c.h1,
                count: c.count,
                description: c.description,
              })) as CategoryNode[]}
              filterPath={(kind) => `/ideas/${kind}`}
            />
            <div className="mt-6 border-t border-border pt-6">
              <h2 className="text-meta font-semibold text-text">All categories</h2>
            </div>
          </div>
        )}

        {/*
         * THE MOSAIC, not a link list.
         *
         * What was here: `grid gap-4 sm:grid-cols-2` of identical bordered cards, every category
         * the same size whether it held 5 packs or 30. That is the catalogue's own object rendered
         * with category names in it, which made this page indistinguishable from the shelf at a
         * glance and gave a visitor no reason to be on it. A taxonomy page's job is to show the
         * SHAPE of the catalogue, and shape means some things are bigger than others.
         *
         * Weight is assigned by rank, not by a continuous function of count. Three reasons:
         * a 30-pack category is not six times more interesting than a 5-pack one, so area
         * proportional to count would hand almost the whole page to one tile; ranks give a stable
         * layout that cannot collapse when the daemon publishes overnight and the counts shift;
         * and a two-step ladder (wide, then standard) is legible as a hierarchy, where five
         * gradations read as noise. `rank < 2` takes the full row on `sm`, everything else pairs.
         *
         * Every tile carries three real facts and no adjectives: the count, the actual price range
         * of the packs behind the link, and the description written for that facet. The count and
         * the range are set in mono because they are quantities; the name is the only prose.
         *
         * Search collapses the hierarchy on purpose. Once a query is typed the ranking that
         * produced the mosaic is no longer the thing being looked at, and a result set where the
         * first two hits are twice the size of the rest reads as relevance ranking, which it is
         * not -- it is still catalogue size. Filtered results are therefore uniform.
         */}
        {filtered.length > 0 ? (
          <ul className="grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
            {filtered.map((cat, i) => {
              const lead = !search && i < 2;
              return (
                <li key={cat.slug} className={cx(lead && 'sm:col-span-2')}>
                  <Link
                    href={`/ideas/${cat.slug}`}
                    className={cx(
                      'group flex h-full flex-col justify-between gap-4 rounded-md bg-surface p-5',
                      'transition-[background-color,box-shadow] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)]',
                      'hover:bg-surface2',
                      lead && 'sm:flex-row sm:items-end sm:p-7',
                    )}
                  >
                    <span className="flex min-w-0 items-start gap-4">
                      <span
                        className={cx(
                          'flex flex-none items-center justify-center rounded-sm bg-surface2',
                          lead ? 'h-12 w-12' : 'h-10 w-10',
                        )}
                      >
                        <BespokeIcon kind={cat.slug} size={lead ? 22 : 18} className="text-muted" />
                      </span>
                      <span className="min-w-0">
                        {/* The one place on this page where type size carries meaning. A lead
                            tile's name is a step up because its shelf is bigger, which is the
                            fact the mosaic exists to communicate. */}
                        <h2
                          className={cx(
                            'font-semibold leading-snug text-text',
                            lead ? 'text-h2' : 'text-body',
                          )}
                        >
                          {VARIANTS[variant].categoryH1[cat.slug] ?? cat.h1}
                        </h2>
                        <p className="mt-1.5 max-w-[62ch] text-meta leading-relaxed text-muted">
                          {cat.description}
                        </p>
                      </span>
                    </span>

                    {/* Count and range, in the data voice. `low === high` prints one figure
                        rather than "£49 to £49", which reads as a bug in a price ladder. */}
                    <span className="flex flex-none items-baseline gap-2 font-mono text-caption text-subtle sm:flex-col sm:items-end sm:gap-1">
                      <span className="text-text">
                        {cat.count} pack{cat.count !== 1 ? 's' : ''}
                      </span>
                      {cat.low !== null && cat.high !== null && (
                        <span>
                          {cat.low === cat.high
                            ? formatGbp(cat.low)
                            : `${formatGbp(cat.low)} to ${formatGbp(cat.high)}`}
                        </span>
                      )}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="py-12 text-center">
            <p className="text-meta text-muted">No categories match &ldquo;{search}&rdquo;.</p>
            <button
              type="button"
              onClick={() => setSearch('')}
              className={buttonClasses({ variant: 'secondary', className: 'mt-3' })}
            >
              Clear search
            </button>
          </div>
        )}

        <p className="mt-10 text-meta leading-relaxed text-muted">
          Categories appear once enough packs have cleared the checks to fill them. Ideas that failed are in the{' '}
          <Link href="/kill-log" className={textLinkClass('font-medium')}>
            kill log
          </Link>{' '}
          with the sourced reason why.
        </p>
      </Section>

      <CtaBand
        width="7xl"
        title="Or see everything at once."
        lead=""
        primary={{ href: '/', label: 'Browse every pack' }}
      />
    </MarketingLayout>
  );
}

import React from 'react';
import Link from 'next/link';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { fetchCatalog } from '@/lib/api/client';
import { eligibleLandings } from '@/lib/seo/landings';
import CategoryGraph, { type CategoryNode } from '@/components/discovery/CategoryGraph';
import BespokeIcon from '@/components/marketing/BespokeIcon';
import { resolveVariant } from '@/lib/getCopyVariant';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

interface Props {
  categories: { slug: string; h1: string; description: string; count: number }[];
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
        categories: eligibleLandings(packs).map(({ landing, count }) => ({
          slug: landing.slug,
          h1: landing.h1,
          description: landing.metaDescription,
          count,
        })),
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
    if (!search.trim()) return categories;
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
        eyebrow="Categories"
        title={<span className="leading-tight tracking-tighter">Explore stress-tested ideas by industry.</span>}
        lead={
          total > 0
            ? `${total} researched packs across ${categories.length} categories. Choose your battleground.`
            : 'Researched packs, grouped by who they sell to, the hours they need, the skills they suit.'
        }
      />

      <Section bg="white" width="7xl">
        {/* Search */}
        <div className="relative mb-8">
          <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search industries, skills, or markets…"
            className="w-full border border-border bg-surface py-3 pl-11 pr-4 text-sm text-text outline-none transition-colors focus:border-primary/40"
          />
        </div>

        {/* US-7: the 2D category graph. Sized by pack count, placed by relatedness.
            Tapping a node navigates to that category's landing page. Below the
            graph, the existing flat list stays as the text fallback (some buyers
            scan text, some scan visuals - keep both). */}
        {!search && categories.length > 0 && (
          <div className="mb-10">
            <h2 className="text-sm font-bold text-text mb-4">Browse the shape of the catalogue</h2>
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
              <h2 className="text-sm font-bold text-text">All categories</h2>
            </div>
          </div>
        )}

        {/* All categories grid */}
        {filtered.length > 0 ? (
          <ul className="grid gap-4 sm:grid-cols-2">
            {filtered.map((cat) => (
              <li key={cat.slug}>
                <Link
                  href={`/ideas/${cat.slug}`}
                  className="group flex h-full items-start gap-4 border border-border bg-surface p-5 transition-colors hover:bg-surface2 hover:border-text/20"
                >
                  <span className="flex h-10 w-10 flex-none items-center justify-center mt-0.5 bg-primary/10">
                    <BespokeIcon kind={cat.slug} size={18} className="text-primary" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-base font-bold text-text group-hover:text-primary transition-colors leading-snug">
                      {VARIANTS[variant].categoryH1[cat.slug] ?? cat.h1}
                    </h2>
                    <p className="mt-1 text-sm leading-relaxed text-muted line-clamp-2">{cat.description}</p>
                    <span className="mt-2 inline-flex text-xs font-semibold text-primary">
                      {cat.count} pack{cat.count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="py-12 text-center">
            <p className="text-sm text-muted">No categories match &ldquo;{search}&rdquo;.</p>
            <button
              type="button"
              onClick={() => setSearch('')}
              className="mt-2 text-sm font-semibold text-primary hover:underline"
            >
              Clear search
            </button>
          </div>
        )}

        <p className="mt-10 text-sm leading-relaxed text-muted">
          Categories appear once enough packs have cleared the filter to fill them. Ideas that failed are in the{' '}
          <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">
            kill log
          </Link>{' '}
          with the sourced reason why.
        </p>
      </Section>

      <CtaBand
        title="Or see everything at once."
        lead=""
        primary={{ href: '/', label: 'Browse every pack' }}
      />
    </MarketingLayout>
  );
}

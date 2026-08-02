import React from 'react';
import Link from 'next/link';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { fetchCatalog } from '@/lib/api/client';
import { eligibleLandings } from '@/lib/seo/landings';
import { resolveVariant } from '@/lib/getCopyVariant';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

/**
 * `/ideas`, the hub the landing pages hang off.
 *
 * It exists for two reasons beyond being a useful page. First, the pack pages' breadcrumb names
 * "Business ideas" as the parent, and a breadcrumb whose middle crumb 404s is worse than no
 * breadcrumb. Second, crawl depth: without a hub, each `/ideas/<slug>` is reachable only from its
 * siblings and the sitemap, which is a weak internal-linking position for the pages meant to bring
 * in search traffic. One hub linked from the site chrome puts every landing two clicks from home.
 */

interface Props {
  categories: { slug: string; h1: string; description: string; count: number }[];
  /** Total live packs, for the honest count in the lead. Zero when the catalogue is unreachable. */
  total: number;
  /** Copy variant resolved server-side from cookie/query/UA. */
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
    // Degrade to an empty hub rather than 404ing: the page still explains what the catalogue is
    // and still links to it, which is more than a 404 does for a crawler that arrives mid-outage.
    console.error('/ideas: catalog fetch failed, rendering hub with no categories:', error);
    return { props: { total: 0, categories: [], variant } };
  }
};

export default function IdeasHub({ categories, total, variant }: Props) {
  return (
    <MarketingLayout>
      <Seo
        title="Business ideas by category"
        description="Browse researched business ideas by who they sell to, the hours they need, the skills they suit, and the sector they sit in. Every pack cites a source for every claim."
        jsonLd={graph(
          itemListNode(
            categories.map((category) => ({ name: category.h1, path: `/ideas/${category.slug}` })),
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
        title={<span className="leading-tight tracking-tighter">Business ideas by category.</span>}
        lead={
          total > 0
            ? `${total} researched packs, grouped by who they sell to, the hours they need, the skills they suit, and the sector they sit in.`
            : 'Researched packs, grouped by who they sell to, the hours they need, the skills they suit, and the sector they sit in.'
        }
      />

      <Section bg="white" width="7xl">
        {categories.length > 0 ? (
          <ul className="grid gap-4 sm:grid-cols-2">
            {categories.map((category) => (
              <li key={category.slug}>
                <Link
                  href={`/ideas/${category.slug}`}
                  className="flex h-full flex-col rounded-xl border border-border bg-surface p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-text/20 hover:shadow-[0_12px_28px_rgba(0,0,0,0.08)]"
                >
                  <span className="flex items-baseline justify-between gap-4">
                    <h2 className="text-lg font-black leading-snug tracking-tight text-text">
                      {VARIANTS[variant].categoryH1[category.slug] ?? category.h1}
                    </h2>
                    <span className="shrink-0 text-sm font-bold text-muted">{category.count}</span>
                  </span>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{category.description}</p>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-base text-muted">
            The catalogue is briefly unavailable.{' '}
            <Link href="/" className="font-semibold text-text underline underline-offset-2">
              Browse every pack
            </Link>{' '}
            instead.
          </p>
        )}

        <p className="mt-10 text-sm leading-relaxed text-muted">
          A category only appears once enough packs have cleared the filter to fill it, so this list
          grows as the engine publishes. Ideas that failed are in the{' '}
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

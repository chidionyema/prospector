import React from 'react';
import Link from 'next/link';
import { textLinkClass } from '@/components/ui';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand, HeroList } from '@/components/marketing/blocks';
import { PackGrid } from '@/components/discovery/PackGrid';
import { Seo } from '@/components/Seo';
import { fetchCatalog, type Pack } from '@/lib/api/client';
import { checksSentence } from '@/lib/checks';
import {
  eligibleLandings,
  landingBySlug,
  landingH1,
  landingMetaTitle,
  packMatchesLanding,
  type Landing,
} from '@/lib/seo/landings';
import { resolveVariant } from '@/lib/getCopyVariant';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

/**
 * A topical landing page, one slice of the catalogue at a stable, indexable URL.
 *
 * See `lib/seo/landings.ts` for why these exist, and for the three guards that stop a set of
 * category pages becoming the doorway-page pattern Google demotes. The one enforced HERE is the
 * thin-content threshold: a landing whose slice the live catalogue cannot fill returns a genuine
 * 404 rather than rendering an almost-empty shelf. That check runs per request against the live
 * catalogue, so the set of live landing pages tracks supply on its own as the engine publishes.
 *
 * Server-rendered, not client-filtered. The whole point is that a crawler and an assistant see the
 * matching packs, their titles, and real anchors to them in the initial HTML.
 */

interface Props {
  landing: Landing;
  packs: Pack[];
  /** The other live landings, for the cross-links at the foot of the page. */
  siblings: { slug: string; h1: string; count: number }[];
  /** The catalogue was unreachable. Rendered as a 503 holding page, never indexed. */
  unavailable?: boolean;
  /** Copy variant resolved server-side from cookie/query/UA. */
  variant: VariantKey;
}

export const getServerSideProps: GetServerSideProps<Props> = async (context) => {
  const { params, res, req, query } = context;

  const variant = resolveVariant(
    query.variant,
    req?.cookies?.['mumchimp.copy.variant'],
    req?.headers?.['user-agent'],
  );

  const landing = landingBySlug(typeof params?.slug === 'string' ? params.slug : undefined);
  if (!landing) return { notFound: true };

  let all: Pack[];
  try {
    all = await fetchCatalog();
  } catch (error) {
    // MEASURED, 2026-08-01: `res.statusCode = 503` together with `return { notFound: true }` does
    // NOT serve a 503, Next overrides it and the response is a 404. The server log showed
    // "/ideas/b2b-business-ideas: catalog fetch failed" on a request curl recorded as 404.
    //
    // That is the difference between "come back later" and "this page is gone", and Google acts
    // on the difference: a 404 on a live landing page is grounds for dropping it from the index,
    // so a two-second API blip would cost the page its ranking. Serve a real 503 with a holding
    // body instead. `noindex` on top, because a crawler that ignores the status must not record
    // an empty category page either.
    console.error(`/ideas/${landing.slug}: catalog fetch failed:`, error);
    res.statusCode = 503;
    res.setHeader('Retry-After', '120');
    return { props: { landing, packs: [], siblings: [], unavailable: true, variant } };
  }

  const eligible = eligibleLandings(all);
  const mine = eligible.find((entry) => entry.landing.slug === landing.slug);
  if (!mine) return { notFound: true };

  return {
    props: {
      landing,
      packs: all.filter((pack) => packMatchesLanding(pack, landing)),
      siblings: eligible
        .filter((entry) => entry.landing.slug !== landing.slug)
        .map(({ landing: other, count }) => ({ slug: other.slug, h1: other.h1, count })),
      variant,
    },
  };
};

export default function IdeasLanding({ landing, packs, siblings, unavailable, variant }: Props) {
  if (unavailable) {
    return (
      <MarketingLayout
        breadcrumbs={[
          { href: '/', label: 'Catalogue' },
          { href: '/ideas', label: 'Categories' },
          { href: '#', label: landing.h1 },
        ]}
        breadcrumbsWidth="7xl"
      >
        <Seo title={landing.metaTitle} description={landing.metaDescription} noindex />
        <PageHero
        width="7xl"
          eyebrow="Temporarily unavailable"
          title={landing.h1}
          lead="The catalogue is briefly unreachable, so this page cannot list its packs right now. Try again in a minute."
        />
        <Section bg="white" width="7xl">
          <p className="lede">
            <Link href="/" className={textLinkClass()}>
              Browse every pack
            </Link>{' '}
            or{' '}
            <Link href="/ideas" className={textLinkClass()}>
              see the other categories
            </Link>
            .
          </p>
        </Section>
      </MarketingLayout>
    );
  }

  return (
    <MarketingLayout
      breadcrumbs={[
        { href: '/', label: 'Catalogue' },
        { href: '/ideas', label: 'Categories' },
        { href: '#', label: landingH1(landing.slug, variant) },
      ]}
      breadcrumbsWidth="7xl"
    >
      <Seo
        title={landingMetaTitle(landing.slug, variant)}
        description={landing.metaDescription}
        jsonLd={graph(
          itemListNode(
            packs.map((pack) => ({ name: pack.title, path: `/pack/${pack.id}` })),
            landing.h1,
          ),
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Business ideas', path: '/ideas' },
            { name: landing.h1, path: `/ideas/${landing.slug}` },
          ]),
        )}
      />

      <PageHero
        width="7xl"
        eyebrow={`${packs.length} researched ${packs.length === 1 ? 'pack' : 'packs'}`}
        title={landingH1(landing.slug, variant)}
        lead={landing.slug === 'automated-business-ideas' ? VARIANTS[variant].automatedIdeasIntro : landing.intro}
        aside={
          siblings.length > 0 ? (
            <HeroList
              label="Other ways in"
              items={siblings.slice(0, 6).map((s) => s.h1)}
            />
          ) : undefined
        }
      />

      <Section bg="white" width="7xl">
        {/* The landing's own selection rule, handed to the grid so no card repeats it. This page
            IS `payer === 'b2c'`; printing `B2C` on all 31 cards spends the first chip slot on the
            one fact the visitor already has, and pushes a facet that varies off the end of the
            row. `landing.kind`/`landing.value` are the same two fields `packMatchesLanding` filters
            on, so the chip that disappears is exactly the chip the page guarantees. */}
        <PackGrid packs={packs} />

        <p className="mt-10 lede">
          Every pack on this page faced the same checks: {checksSentence()}. Each then survived an
          adversarial review.{' '}
          <Link href="/how-it-works" className={textLinkClass()}>
            How the checks work
          </Link>
          , and the{' '}
          <Link href="/kill-log" prefetch={false} className={textLinkClass()}>
            kill log
          </Link>{' '}
          lists what it killed.
        </p>

        {siblings.length > 0 && (
          <nav className="mt-12 border-t border-border pt-8" aria-label="Other categories">
            <h2 className="text-meta font-semibold text-muted">
              Browse another way
            </h2>
            <ul className="mt-4 flex flex-wrap gap-2">
              {siblings.map((sibling) => (
                <li key={sibling.slug}>
                  <Link
                    href={`/ideas/${sibling.slug}`}
                    className="inline-flex items-center gap-2 rounded-sm border border-border px-4 py-3 text-meta font-semibold text-text transition-colors hover:border-text/30 hover:bg-bg"
                  >
                    {sibling.h1}
                    <span className="text-muted">{sibling.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </Section>

      <CtaBand
        width="7xl"
        title="See the whole catalogue."
        lead=""
        primary={{ href: '/', label: 'Browse every pack' }}
      />
    </MarketingLayout>
  );
}

import React from 'react';
import Link from 'next/link';
import type { GetServerSideProps } from 'next';

import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { PackRowList } from '@/components/discovery/PackRow';
import { Seo } from '@/components/Seo';
import { textLinkClass } from '@/components/ui';
import { fetchCatalog, type Pack } from '@/lib/api/client';
import { currencyForCountry, type Currency } from '@/lib/fx';
import { groupByMarket, resolveMarket } from '@/lib/market';
import { breadcrumbNode, graph, itemListNode } from '@/lib/seo/schema';

/**
 * THE PLAIN INDEX: every pack in the catalogue, on one server-rendered page.
 *
 * FR-10 of `docs/FIRST_RUN_AND_NAVIGATION_PROGRAM.md`. Measured 2026-08-21 against live: the home
 * page links 63 of 77 packs, `/ideas` links 0 (its 15 links are categories), and the union of the
 * 15 category pages is 77. So 14 packs were three clicks from every page on the site -- they exist
 * in the sitemap and in no listing a reader or a crawler could walk in two.
 *
 * The 14 are not missing from the home page by accident. It caps the shelf on purpose
 * (`pages/index.tsx:1445` shows 2 of N market groups, `:1494` shows 3 of each until `showAll`),
 * founder-reviewed 2026-08-18, because printing every group took that page to 14,239px against the
 * drawing's 8,653. `showAll` is a <button>, so the hidden rows are not in the served HTML at all.
 *
 * This page is the answer that leaves that decision alone: no cap, no filters, no client state, one
 * footer link. The footer renders on EVERY page, the legal ones included -- `LegalDoc.tsx:113`
 * renders through `MarketingLayout` like everything else, confirmed against live 2026-08-21
 * (`curl -s https://mumchimp.com/terms` carries the footer's Store column). So `/packs` is one
 * click from every entry route and every pack is two.
 *
 * This is a shop index, not a second marketing page. Same row, same type, same picture as the
 * home shelf; no cap, no filters. The job is to look like a list of goods a buyer can scan.
 */

/** Exported so `src/__tests__/everyPackIsListed.test.tsx` can hand the real props straight from
 *  `getServerSideProps` into the component, rather than casting through `never` and losing the
 *  very shape it is there to check. */
export interface Props {
  /** The visitor's own market first, then every other market as its own labelled section. */
  groups: { key: string; label: string | null; packs: Pack[] }[];
  total: number;
  currency: Currency;
  market: string;
  /** The catalogue was unreachable. Rendered as a 503 holding page, never indexed. */
  unavailable?: boolean;
}

/** Alphabetical, because the one job of an index is that a reader can find a known title in it.
 *  Every other surface orders by recency or by score; this one orders for lookup. */
const byTitle = (a: Pack, b: Pack) => a.title.localeCompare(b.title, 'en-GB');

export const getServerSideProps: GetServerSideProps<Props> = async (context) => {
  const { req, res, query } = context;

  const queryMarket = query.market;
  const countryHeader = req.headers['fly-client-country'];
  const country = typeof countryHeader === 'string' ? countryHeader : null;
  // Read the same three sources in the same order as the home page, but never WRITE the cookie:
  // `pages/index.tsx` is deliberately the only place the market choice is persisted, so a visitor
  // arriving here with `?market=` sees that market and nothing is stored on their behalf.
  const market = resolveMarket({
    queryMarket: typeof queryMarket === 'string' || Array.isArray(queryMarket) ? queryMarket : null,
    cookieMarket: req.cookies.market ?? null,
    countryHeader: country,
  });
  const currency = currencyForCountry(country);

  let packs: Pack[];
  try {
    packs = await fetchCatalog();
  } catch (error) {
    // Same trap as `/ideas/[slug]`, and the same measured reason (2026-08-01): `res.statusCode =
    // 503` together with `return { notFound: true }` serves a 404, not a 503. A 404 on a live
    // listing page is grounds for dropping it from the index, and this page is the one every
    // other page links to, so it must say "come back later" rather than "this is gone".
    console.error('/packs: catalog fetch failed:', error);
    res.statusCode = 503;
    res.setHeader('Retry-After', '120');
    return { props: { groups: [], total: 0, currency, market, unavailable: true } };
  }

  const grouped = groupByMarket(packs, market);
  const groups = [
    { key: market, label: null, packs: [...grouped.matching].sort(byTitle) },
    ...grouped.others.map((other) => ({
      key: other.market,
      label: other.label,
      packs: [...other.packs].sort(byTitle),
    })),
  ].filter((group) => group.packs.length > 0);

  return { props: { groups, total: packs.length, currency, market } };
};

export default function AllPacks({ groups, total, currency, market, unavailable }: Props) {
  const breadcrumbs = [
    { href: '/', label: 'Packs' },
    { href: '#', label: 'Every pack' },
  ];

  if (unavailable) {
    return (
      <MarketingLayout breadcrumbs={breadcrumbs} breadcrumbsWidth="7xl">
        <Seo
          title="Every pack"
          description="The full index of researched packs."
          noindex
        />
        <PageHero
          width="7xl"
          eyebrow="Temporarily unavailable"
          title="Every pack"
          lead="The packs are briefly unreachable, so this page cannot list them right now. Try again in a minute."
        />
        <Section bg="white" width="7xl">
          {/* `/#catalog`, not `/`. `/` is the top of a long marketing page; the shelf itself is
              the anchor, and it is what the other pages point at. It also matters that this link
              is a real forward link: when the catalogue is unreachable this holding page is the
              WHOLE page, so a link to the top of the marketing site leaves a visitor with
              nowhere to go, and `e2e/first-run.spec.ts` FR3 says so. */}
          <p className="lede">
            <Link href="/#catalog" className={textLinkClass()}>
              Back to the catalogue
            </Link>
            .
          </p>
        </Section>
      </MarketingLayout>
    );
  }

  return (
    <MarketingLayout breadcrumbs={breadcrumbs} breadcrumbsWidth="7xl">
      <Seo
        title="Every pack"
        description={`All ${total} researched packs in one list, newest and oldest alike.`}
        jsonLd={graph(
          itemListNode(
            groups.flatMap((group) => group.packs).map((pack) => ({ name: pack.title, path: `/pack/${pack.id}` })),
            'Every pack',
          ),
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Every pack', path: '/packs' },
          ]),
        )}
      />

      <PageHero
        width="7xl"
        eyebrow={`${total} ${total === 1 ? 'pack' : 'packs'}`}
        title="Every pack"
        lead="Every researched pack we sell. Alphabetical, this market first."
      />

      <Section bg="white" width="7xl">
        {groups.map((group, i) => (
          <div key={group.key} className={i === 0 ? undefined : 'mt-8'}>
            {/* The visitor's own market has no heading: it is the first thing on the page and
                labelling it "United Kingdom" tells a UK reader something they did not ask. Every
                OTHER market gets one, because a US pack in a UK reader's list needs to say so. */}
            {group.label && (
              <h2 className="text-meta font-semibold text-muted">
                Also available in {group.label}
              </h2>
            )}
            <PackRowList
              packs={group.packs}
              currency={currency}
              viewerMarket={market}
              className={group.label ? 'mt-4' : undefined}
            />
          </div>
        ))}

        <p className="mt-10 lede">
          Sorted by title, so a pack you have heard of is findable. To browse by sector or buyer,
          use the{' '}
          <Link href="/ideas" className={textLinkClass()}>
            categories
          </Link>
          . What did not survive the checks is in the{' '}
          <Link href="/kill-log" prefetch={false} className={textLinkClass()}>
            kill log
          </Link>
          .
        </p>
      </Section>

      <CtaBand
        width="7xl"
        title="Start with the newest."
        lead=""
        primary={{ href: '/', label: 'Back to the catalogue' }}
      />
    </MarketingLayout>
  );
}

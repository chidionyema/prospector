/**
 * HOME, on the estate UI kit (crew#700 CP1, 2026-10-01).
 *
 * One proposition, one proof line, six packs, one CTA. The full catalogue is one route (/packs);
 * the explanations live on /how-it-works and /sample. The previous home carried the catalogue,
 * three stat bands, a chart, a waitlist, the sample and a closing claim in 2,595 lines and
 * 13,619px on a phone (audit 2026-09-30, F4/F6). Everything a visitor needs to decide is on this
 * screen. Everything else is one tap away and not repeated here.
 *
 * Kept verbatim from the previous page: the catalogue fetch with its last-known-good fallback
 * (lib/catalogCache: an outage must never render as "nothing is for sale"), the copy variant
 * cookie, the currency from the edge country header, and SITE_COPY.heroH1 as the one h1
 * (verify.mjs asserts it). Dropped: discovery state, flags, personalisation; they belong to the
 * catalogue route, not the landing.
 */
import React from 'react';
import type { GetServerSideProps } from 'next';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { BuyDrawerProvider } from '@/components/checkout/BuyDrawer';
import { Landing, Empty } from '@estate/ui-kit';
import { fetchCatalog, fetchCatalogStats, type Pack, type CatalogStats } from '@/lib/api/client';
import { freshCatalog, lastKnownCatalog, rememberCatalog } from '@/lib/catalogCache';
import { currencyForCountry, formatPriceForMarket, type Currency } from '@/lib/fx';
import { priceRange, formatGbp } from '@/lib/priceRange';
import { VARIANTS, type VariantKey } from '@/lib/copyConfig';
import { pickVisitorVariant, appendSetCookie, variantSetCookie, VARIANT_COOKIE } from '@/lib/getCopyVariant';
import { RESEARCH_STATS } from '@/lib/stats';
import { SITE_COPY } from '@/lib/siteCopy';
import { graph, itemListNode } from '@/lib/seo/schema';
import { similarPacks } from '@/lib/discovery';
import { categoryFor } from '@/lib/category';
import TrustGuaranteesRow from '@/components/marketing/TrustGuaranteesRow';
import { cardLine } from '@/lib/discovery';
import { repairTruncation } from '@/lib/copy';

// Re-exported so lib/__tests__/cardLine.test.ts keeps its import path; the featured cards use it below.
export { cardLine };

interface HomeProps {
  packs: Pack[];
  stats: CatalogStats | null;
  currency: Currency;
  /** True only when the catalogue could not be reached AND this server never held one. */
  catalogUnavailable: boolean;
  copyVariant: VariantKey;
  /** N2: packs similar to the most recently viewed one (the recentlyViewed cookie the pack page writes). */
  personalised: Pack[];
}

/** Six newest verified packs. The catalogue route shows all of them. */
function newest(packs: Pack[], n: number): Pack[] {
  return [...packs]
    .sort((a, b) => (b.verifiedAt ?? '').localeCompare(a.verifiedAt ?? ''))
    .slice(0, n);
}

export default function Home({ packs, stats, currency, catalogUnavailable, copyVariant, personalised }: HomeProps) {
  const copy = VARIANTS[copyVariant] ?? VARIANTS.a;
  const range = priceRange(packs);
  const count = packs.length;
  const description = copy.globalHookDescription;
  return (
    <BuyDrawerProvider currency={currency}>
      <MarketingLayout>
        <Seo
          title={count && range ? `${count} researched business ideas, ${formatGbp(range.min)} to ${formatGbp(range.max)}` : undefined}
          description={description}
          jsonLd={graph(itemListNode(packs.map((p) => ({ name: p.title, path: `/pack/${p.id}` })), 'Packs for sale'))}
        />
        <div className="mx-auto flex w-full max-w-(--size-content) flex-col gap-12 px-(--size-gutter) py-8">
          {catalogUnavailable ? (
            <>
              <Landing
                headline={SITE_COPY.heroH1}
                lede={description}
                cta={{ label: 'Read the free sample', href: '/sample' }}
                secondary={{ label: 'How every pack is checked', href: '/how-it-works' }}
              />
              {/* An outage is not a sold-out catalogue (lib/catalogCache, catalogueOutageIsNotSoldOut.test). */}
              <Empty
                title="The packs could not be loaded"
                text="The catalogue service did not answer. The packs are still for sale. Try again in a minute."
                action={{ label: 'Try again', href: '/' }}
              />
            </>
          ) : (
            <Landing
              headline={SITE_COPY.heroH1}
              lede={description}
              proof={[
                `${RESEARCH_STATS.researched.toLocaleString('en-GB')} ideas researched`,
                `${count} for sale`,
                'every claim sourced',
              ]}
              cta={{ label: count ? `See all ${count} packs` : 'See the packs', href: '/packs' }}
              secondary={{ label: SITE_COPY.sampleLinkHero, href: '/sample' }}
              featured={{
                // N2: a visitor who has opened a pack sees packs like it (similarPacks), else the newest.
                title: personalised.length ? 'Based on your browsing' : 'Newest packs',
                items: (personalised.length ? personalised : newest(packs, 6)).slice(0, 6).map((p) => {
                  const cat = categoryFor(p);
                  return {
                    title: p.title,
                    text: cardLine(repairTruncation(p.cardLine || p.oneLine)),
                    meta: [cat.tagged ? cat.label : null, p.sourceCount ? `${p.sourceCount} sources` : null, formatPriceForMarket(p.price, currency)].filter((m): m is string => !!m),
                    href: `/pack/${p.id}`,
                  };
                }),
              }}
            />
          )}
          {/* The purchase terms, once, with the live count (nOneTrustRow). */}
          {!catalogUnavailable && (
            <TrustGuaranteesRow layout="stack" listed={stats ? stats.listed : undefined} />
          )}
        </div>
      </MarketingLayout>
    </BuyDrawerProvider>
  );
}

export const getServerSideProps: GetServerSideProps<HomeProps> = async (context) => {
  const ua = context.req.headers['user-agent'];
  const picked = pickVisitorVariant(
    context.query.variant,
    context.req.cookies[VARIANT_COOKIE],
    typeof ua === 'string' ? ua : undefined,
  );
  const copyVariant = picked.key;
  if (picked.persist) appendSetCookie(context.res, variantSetCookie(copyVariant));

  const countryHeader = context.req.headers['fly-client-country'];
  const currency = currencyForCountry(typeof countryHeader === 'string' ? countryHeader : null);

  // N2: the pack page writes `recentlyViewed` (MRU, ten ids); the most recent anchors the similar row.
  const recentlyViewedIds: string[] = (context.req.cookies.recentlyViewed ?? '').split(',').filter(Boolean).slice(0, 10);
  const personalisedFor = (available: Pack[]): Pack[] => {
    if (recentlyViewedIds.length === 0) return [];
    const anchor = available.find((p) => p.id === recentlyViewedIds[0]);
    return anchor ? similarPacks(anchor, available) : [];
  };

  // The catalogue is not per-visitor, so it is not re-fetched per visitor: a catalogue fetched within
  // the last minute is served from this process (measured 2026-08-16: the two calls cost ~0.5s TTFB).
  const fresh = freshCatalog();
  if (fresh) {
    return { props: { packs: fresh.packs, stats: fresh.stats, currency, catalogUnavailable: false, copyVariant, personalised: personalisedFor(fresh.packs) } };
  }
  try {
    const [packs, stats] = await Promise.all([fetchCatalog(), fetchCatalogStats()]);
    rememberCatalog(packs, stats);
    return { props: { packs, stats, currency, catalogUnavailable: false, copyVariant, personalised: personalisedFor(packs) } };
  } catch (error) {
    console.error('Error fetching catalog:', error);
    const cached = lastKnownCatalog();
    if (cached) {
      return { props: { packs: cached.packs, stats: cached.stats, currency, catalogUnavailable: false, copyVariant, personalised: personalisedFor(cached.packs) } };
    }
    return { props: { packs: [], stats: null, currency, catalogUnavailable: true, copyVariant, personalised: [] } };
  }
};

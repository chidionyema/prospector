/**
 * THE PACK PAGE, on the estate UI kit (crew#700 CP1, 2026-10-01).
 *
 * The money page: one purchase action, the checks that cleared, the sources you can open. The
 * Detail template owns the layout; this file owns the data and the checkout. Kept verbatim from
 * the previous page because each is a production incident written down: getServerSideProps
 * (gone vs down, the recentlyViewed cookie), usePackCheckout, PackBuyButton, the on-demand
 * EmbeddedCheckoutPanel, the sticky mobile bar, and the same-or-dearer rule for similar packs.
 *
 * What the API gives is what the page says. A pack carries "7/8 checks cleared · 28 sources
 * cited" (lib/api/client parseCheckCounts), not a verdict per check, so the panel states the
 * count and no per-check pill is drawn: an unverifiable pill would be a claim (audit F7). Sources
 * are the URLs the pack's own sample extract cites.
 */
import React from 'react';
import type { GetServerSideProps } from 'next';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/router';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { productJsonLd } from '@/lib/productJsonLd';
import { breadcrumbNode, graph } from '@/lib/seo/schema';
import { packOgImagePath } from '@/lib/seo/ogImage';
import { ErrorState, textLinkClass } from '@/components/ui';
import { COMMON_CHECKS } from '@/lib/checks';
import EvidenceExcerptPlate from '@/components/marketing/EvidenceExcerptPlate';
import { PackContentsSection } from '@/components/marketing/PackContents';
import { SixInHundred } from '@/components/marketing/SixInHundred';
import { LEGAL, RESEARCH_RATE_ANCHOR } from '@/lib/config';
import { categoryFor } from '@/lib/category';
import { Detail, Button } from '@estate/ui-kit';
import { ApiError, fetchCatalog, fetchPackDetails, freshnessLabel, marketLabel, parseCheckCounts, splitVerdict, type Pack, type PackDetails } from '@/lib/api/client';
import { formatPriceForMarket, formatChargeNote, currencyForCountry, type Currency } from '@/lib/fx';
import { trackPriceEvent } from '@/lib/analytics';
import PackBuyButton from '@/components/checkout/PackBuyButton';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { PREOPENED_CHECKOUT_PARAM, preopenedClientSecret } from '@/lib/preopenedCheckout';
import { SimilarPacks } from '@/components/discovery/SimilarPacks';
import { similarPacks } from '@/lib/discovery';
import { SITE_COPY } from '@/lib/siteCopy';

// Loaded on demand: the Stripe Elements wrapper renders only once `clientSecret` is set, after
// the buyer clicks Buy, so it must not sit in every visitor's First Load JS.
const EmbeddedCheckoutPanel = dynamic(
  () => import('@/components/checkout/EmbeddedCheckoutPanel').then((m) => m.EmbeddedCheckoutPanel),
  { ssr: false },
);

interface PackPageProps {
  pack: PackDetails | null;
  similar: Pack[];
  error?: string;
  unavailable?: boolean;
  currency: Currency;
}

/** Same price or dearer, so the row can only trade up (founder 2026-08-16: it read as a discount anchor). */
function sameOrDearer(pack: PackDetails, similar: Pack[]): Pack[] {
  const floor = pack.pricePence ?? 0;
  return similar.filter((p) => (p.pricePence ?? 0) >= floor);
}

const CHECKS = COMMON_CHECKS.map((check) => check.question);

const SOURCE_RE = /\(source:\s*(https?:\/\/[^\s)]+)\)/g;

/** The URLs a pack's own extract cites, deduplicated, labelled by host and path. */
function citedSources(extract: string[] | undefined): { label: string; href: string }[] {
  const seen = new Set<string>();
  const out: { label: string; href: string }[] = [];
  for (const line of extract ?? []) {
    for (const m of line.matchAll(SOURCE_RE)) {
      const href = m[1];
      if (seen.has(href)) continue;
      seen.add(href);
      try {
        const u = new URL(href);
        out.push({ label: `${u.hostname}${u.pathname.length > 1 ? u.pathname : ''}`.slice(0, 80), href });
      } catch {
        out.push({ label: href.slice(0, 80), href });
      }
    }
  }
  return out;
}

/** An extract line with its "(source: …)" tail turned into a numbered citation link. */
function Extract({ line, sources }: { line: string; sources: { href: string }[] }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of line.matchAll(SOURCE_RE)) {
    parts.push(line.slice(last, m.index));
    const n = sources.findIndex((s) => s.href === m[1]) + 1;
    parts.push(
      <a key={m.index} href={m[1]} rel="noopener noreferrer" target="_blank" className="font-mono text-sm text-accent underline underline-offset-4">
        [{n || '?'}]
      </a>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(line.slice(last));
  return <p>{parts}</p>;
}

export default function PackPage({ pack, similar, error, unavailable, currency }: PackPageProps) {
  const router = useRouter();
  const packId = router.query.id as string;
  if (!pack) {
    return (
      <MarketingLayout>
        <Seo title="Pack temporarily unavailable" noindex={unavailable !== false} />
        <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
          <ErrorState title="Could not load this pack" message={error || 'The pack data could not be retrieved. The server may be temporarily unavailable.'} />
          <button
            type="button"
            className="mt-4"
            onClick={() => { import('@/lib/api/client').then(({ fetchPackDetails: f }) => f(packId).then(() => window.location.reload())); }}
          >
            Try again
          </button>
        </div>
      </MarketingLayout>
    );
  }
  return <PackPageContent pack={pack} similar={similar} currency={currency} />;
}

function PackPageContent({ pack, similar, currency }: { pack: PackDetails; similar: Pack[]; currency: Currency }) {
  const router = useRouter();
  const preopened = preopenedClientSecret(router.query[PREOPENED_CHECKOUT_PARAM]);
  const { checkingOut, checkoutError, clientSecret, canCheckout, buy, handleUnreachable, closeOverlay } = usePackCheckout(pack, preopened);

  // Keyed on (id, pricePence): a price that changes under a client-side navigation is a separate view.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => { trackPriceEvent('price_viewed', pack); }, [pack.id, pack.pricePence]);

  const cat = categoryFor(pack);
  const counts = parseCheckCounts(pack.qaVerdictSummary);
  const verdict = splitVerdict(pack.qaVerdictSummary);
  const sources = citedSources(pack.sampleExtract);
  const price = formatPriceForMarket(pack.price, currency);
  const fresh = freshnessLabel(pack.verifiedAt);
  const notifyHref = `mailto:${LEGAL.supportEmail}?subject=${encodeURIComponent(`Notify me: ${pack.title}`)}`;
  const eyebrow = [marketLabel(pack.market), cat.tagged ? cat.label : null, fresh].filter(Boolean).join(' · ');
  const lead = pack.headline;
  const outcomeSentence = counts ? `This pack cleared ${counts.cleared} of ${counts.total}.` : '';

  const buyControl = canCheckout ? (
    <PackBuyButton pack={pack} variant="detail" buy={buy} checkingOut={checkingOut} canCheckout={canCheckout} currency={currency} className="w-full" />
  ) : (
    <Button asChild size="lg" variant="secondary" className="w-full"><a href={notifyHref}>Notify me when this opens</a></Button>
  );

  return (
    <MarketingLayout breadcrumbs={[{ href: '/', label: 'Home' }, { href: '/packs', label: 'Packs' }, { href: `/pack/${pack.id}`, label: pack.title }]}>
      <Seo
        title={pack.title}
        description={pack.oneLine}
        ogType="product"
        ogImagePath={packOgImagePath(pack.id)}
        ogImageAlt={pack.title}
        jsonLd={graph(productJsonLd(pack), breadcrumbNode([{ name: 'Home', path: '/' }, { name: 'Packs', path: '/packs' }, { name: pack.title, path: `/pack/${pack.id}` }]))}
      />
      <div className="mx-auto flex w-full max-w-(--size-content) flex-col gap-12 px-(--size-gutter) py-8">
        <Detail
          eyebrow={eyebrow}
          title={pack.title}
          lede={pack.subhead || pack.oneLine}
          price={{ amount: price, note: 'one payment' }}
          checksSummary={counts ?? undefined}
          facts={['14-day money back', 'Guest checkout, no account needed', `Operated by ${LEGAL.legalName}, London`]}
          cta={buyControl}
          panelExtra={
            <>
              {checkoutError && <p role="alert" className="text-sm text-state-red-ink">{checkoutError}</p>}
              {canCheckout && currency !== 'GBP' && <p className="text-sm text-text-2">{formatChargeNote(pack.price, currency)}</p>}
              {/* The one comparison the buyer is actually making: a pack against a day of a person (a cited market rate). */}
              <p className="text-sm text-text-2">
                Having this researched for you starts at <b className="text-text">{RESEARCH_RATE_ANCHOR.dayRateLabel} a day</b>{' '}
                <a href={RESEARCH_RATE_ANCHOR.url} target="_blank" rel="noopener noreferrer" className={textLinkClass()}>({RESEARCH_RATE_ANCHOR.source}, {RESEARCH_RATE_ANCHOR.sourceDetail})</a>.
              </p>
            </>
          }
          sample={{ label: SITE_COPY.sampleLinkPanel, href: '/sample' }}
          sources={sources.length ? sources : undefined}
          body={
            <>
              {/* Opens on a sourced dossier excerpt, not a cover (usTwoPackArt: the evidence is the art). */}
              <EvidenceExcerptPlate pack={pack} />
              {lead && <p className="text-lg text-text">{lead}</p>}
              {/* A row is a cited fact from the dossier or it is absent; a heading over an empty list is worse than none. */}
              {(pack.theProblem || pack.marketSize || pack.whoPays) && (
                <dl className="flex flex-col gap-4 border-l-2 border-border-strong pl-4">
                  {pack.theProblem && (
                    <div><dt className="font-mono text-xs uppercase tracking-wider text-text-2">The problem</dt><dd className="mt-1">{pack.theProblem}</dd></div>
                  )}
                  {pack.marketSize && (
                    <div><dt className="font-mono text-xs uppercase tracking-wider text-text-2">How big it is</dt><dd className="mt-1">{pack.marketSize}</dd></div>
                  )}
                  {pack.whoPays && (
                    <div><dt className="font-mono text-xs uppercase tracking-wider text-text-2">Who pays</dt><dd className="mt-1">{pack.whoPays}</dd></div>
                  )}
                </dl>
              )}
              {pack.proofPoint && (
                <section className="flex flex-col gap-2">
                  <h2 className="font-display text-lg font-bold">Why now</h2>
                  <p>{pack.proofPoint}</p>
                </section>
              )}
              {verdict.risk && (
                <section className="flex flex-col gap-2 rounded-md border border-border bg-surface-1 p-4">
                  <h2 className="font-display text-lg font-bold">The main risk we found</h2>
                  <p>{verdict.risk}</p>
                </section>
              )}
              <section className="flex flex-col gap-3">
                <h2 className="font-display text-lg font-bold">The checks</h2>
                <p className="text-text-2">
                  Each check asks one question. {outcomeSentence}{' '}
                  {/* checksBlock.test.ts reads this sentence whole: keep it on one line. */}
                  A pass is not the same as finding a green light: it means no cited evidence went against the idea on that check.
                  {' '}See how each check works on <Link href="/how-it-works" className={textLinkClass()}>/how-it-works</Link>.
                </p>
                <ol className="flex flex-col gap-2">
                  {CHECKS.map((q, i) => (
                    <li key={q} className="flex gap-3"><span className="font-mono text-sm text-text-2 tabular-nums w-6 shrink-0">{String(i + 1).padStart(2, '0')}</span><span>{q}</span></li>
                  ))}
                </ol>
              </section>
              {/* The one ratio block: fewer than six in a hundred ideas survive the checks. */}
              <SixInHundred />
              {pack.whatYouGet?.length ? (
                <section className="flex flex-col gap-2">
                  <h2 className="font-display text-lg font-bold">What you get</h2>
                  <ul className="flex flex-col gap-2 pl-6 list-disc">{pack.whatYouGet.map((w) => <li key={w}>{w}</li>)}</ul>
                </section>
              ) : null}
              {pack.sampleExtract?.length ? (
                <section className="flex flex-col gap-2">
                  <h2 className="font-display text-lg font-bold">A look inside</h2>
                  <div className="flex flex-col gap-3 border-l-2 border-border-strong pl-4 text-text-2">
                    {pack.sampleExtract.map((line, i) => <Extract key={i} line={line} sources={sources} />)}
                  </div>
                </section>
              ) : null}
            </>
          }
        />
        <PackContentsSection sourceCount={pack.sourceCount} />
        <SimilarPacks items={similar} />
      </div>

      {clientSecret && (
        <EmbeddedCheckoutPanel clientSecret={clientSecret} onClose={closeOverlay} title={pack.title} onUnreachable={handleUnreachable} />
      )}

      {/* Sticky mobile checkout bar: price and CTA stay reachable on a phone. */}
      {canCheckout && !clientSecret && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface-2 p-4 pb-[env(safe-area-inset-bottom)] desktop:hidden">
          <div className="mx-auto flex max-w-(--size-content) items-center justify-between gap-3">
            <div className="text-sm text-text-2 leading-snug">
              <span className="block font-medium text-text">One payment</span>
              <span className="block">14 day refund</span>
            </div>
            <PackBuyButton pack={pack} variant="sticky" buy={buy} checkingOut={checkingOut} canCheckout={canCheckout} currency={currency} />
          </div>
        </div>
      )}
      <Link href="/sample" className="sr-only">{SITE_COPY.sampleLink}</Link>
    </MarketingLayout>
  );
}

export const getServerSideProps: GetServerSideProps = async ({ params, req, res }) => {
  const countryHeader = req.headers['fly-client-country'];
  const currency = currencyForCountry(typeof countryHeader === 'string' ? countryHeader : null);

  // N2: the recently-viewed cookie the home and catalogue read. Set only on a successful load,
  // MRU order, ten ids, Path=/ (asserted by __tests__/nTwoPersonalised.test.ts).
  const id = params?.id as string;
  if (id) {
    try {
      const raw = req.cookies.recentlyViewed;
      const ids: string[] = raw ? raw.split(',').filter(Boolean) : [];
      const next = [id, ...ids.filter((x) => x !== id)].slice(0, 10);
      res.setHeader('Set-Cookie', `recentlyViewed=${encodeURIComponent(next.join(','))}; Path=/; Max-Age=2592000; SameSite=Lax`);
    } catch {
      // A cookie write must never 500 the page someone is buying from.
    }
  }

  try {
    const [pack, catalog] = await Promise.all([fetchPackDetails(id), fetchCatalog().catch(() => [] as Pack[])]);
    return { props: { pack, similar: sameOrDearer(pack, similarPacks(pack, catalog)), currency } };
  } catch (error) {
    console.error('Error fetching pack details:', error);
    // Gone and down are different pages: a withdrawn pack is a real 404; an API blip is a 503
    // with Retry-After and noindex, so the URL stays in the index (measured 2026-08-05).
    const status = error instanceof ApiError ? error.status : 0;
    if (status === 404 || status === 410) return { notFound: true };
    res.statusCode = 503;
    res.setHeader('Retry-After', '60');
    const message = error instanceof Error ? error.message : 'Could not load pack details.';
    return { props: { pack: null, similar: [], error: message, currency, unavailable: true } };
  }
};

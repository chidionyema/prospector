import React from 'react';
import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { productJsonLd } from '@/lib/productJsonLd';
import { breadcrumbNode, graph } from '@/lib/seo/schema';
import { packOgImagePath } from '@/lib/seo/ogImage';
import { Icon, CoverArt, ErrorState, Breadcrumbs } from '@/components/ui';
import type { IconName } from '@/components/ui/Icon';
import { cx } from '@/components/ui/cx';
import { Section } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_CONTENTS } from '@/components/marketing/PackContents';
import { fetchCatalog, fetchPackDetails, formatPrice, freshnessLabel, marketLabel, scoreAxes, splitVerdict, Pack, PackDetails } from '@/lib/api/client';
import { track } from '@/lib/analytics';
import { EmbeddedCheckoutPanel } from '@/components/checkout/EmbeddedCheckoutPanel';
import { BuyerIdentityNote } from '@/components/checkout/BuyerIdentityNote';
import { usePackCheckout } from '@/lib/checkout/usePackCheckout';
import { PREOPENED_CHECKOUT_PARAM, preopenedClientSecret } from '@/lib/preopenedCheckout';
import { FacetChips } from '@/components/discovery/FacetChips';
import { SimilarPacks } from '@/components/discovery/SimilarPacks';
import { LEGAL } from '@/lib/config';
import { coverFor } from '@/lib/cover';
import { paybackEquation } from '@/lib/payback';
import { AddToCartButton } from '@/components/cart/AddToCartButton';

const subscribeToNothing = () => () => {};

interface PackPageProps {
  pack: PackDetails | null;
  /** The rest of the catalogue, for the "same mechanics" row. Empty when that fetch failed,
   *  a catalogue outage must never take down a page someone is trying to buy from. */
  catalog: Pack[];
  error?: string;
}

/**
 * The six fronts an idea is attacked on before it can be listed.
 *
 * These name the FILTER, not this pack's findings, deliberately, because this page has no
 * per-check verdicts to render (`PackDetails` in lib/api/client.ts carries none) and a static
 * list therefore may only say what is true of every listed pack.
 *
 * The previous copy said "We tried to show the value would not last. **It held.**" beside a green
 * success tick, six times. Two things make that a claim the page cannot support:
 *
 *   - a check that finds no matching passage returns `unverifiable`, which is silence, not a
 *     finding. Across the 111 passing dossiers, `incumbency` has no positive finding for 71 of
 *     them (59 unverifiable + 12 never run) and `legality` for 52;
 *   - and not every check runs in every lane at all, the smb and side_hustle lanes never run
 *     `value_durability` or `incumbency` (see the per-lane `hard_gates`/`score_checks` in
 *     config.yaml). "We tried" is false for those packs before the second clause even arrives.
 *
 * What IS true of every listed pack is the gate: it died on the first front where we found cited
 * evidence against it, and it did not die (kill_filter.is_hard_fail, only a cited killing
 * verdict kills; silence never does). So the lines state the front, the prose states what
 * surviving means, and the marker is a numeral rather than a green tick.
 *
 * Framing stays refutational, two-sided attack framing out-persuades one-sided "validated"
 * claims (Allen 1991, O'Keefe 1999, Eisend 2006). The change is scope, not tone: this pack's own
 * answers are real and directly below, in the scored axes with their weak ones left visible, and
 * in the QA report inside the pack, which marks each individual claim SUPPORTED or not.
 */
const CHECKS = [
  'Whether the pain is imagined',
  'Whether the value decays',
  'Whether incumbents already own the space',
  'Whether anyone will actually pay',
  'Whether it can reach a market at all',
  'Whether there is a legal landmine',
];

// The deliverable list lives in one shared place (PackContents) so this page and the homepage can
// never drift into promising different things for the same £49.

export default function PackPage({ pack, catalog, error }: PackPageProps) {
  const router = useRouter();

  // Hooks must run unconditionally. If the server couldn't fetch the pack, render an error
  // panel, the inner component runs only when pack is non-null.
  const packId = router.query.id as string;

  if (!pack) {
    return (
      <MarketingLayout>
        <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center px-6 py-16">
          <ErrorState
            title="Could not load this pack"
            message={error || 'The pack data could not be retrieved. The server may be temporarily unavailable.'}
          />
          <button
            type="button"
            onClick={() => {
              import('@/lib/api/client').then(({ fetchPackDetails }) => {
                fetchPackDetails(packId).then(() => window.location.reload());
              });
            }}
            className="mt-4"
          >
            Try again
          </button>
        </div>
      </MarketingLayout>
    );
  }

  return <PackPageContent pack={pack} catalog={catalog} />;
}

/** Inner component: all hooks that require a non-null pack live here. */
function PackPageContent({ pack, catalog }: { pack: PackDetails; catalog: Pack[] }) {
  const router = useRouter();
  const preopened = preopenedClientSecret(router.query[PREOPENED_CHECKOUT_PARAM]);

  // The buy path itself, shared verbatim with the shelf's Buy drawer, which is the point: the
  // logic it holds is three production incidents written down, and two copies would mean the
  // next such fix lands in only one of them. See lib/checkout/usePackCheckout.
  const {
    checkingOut,
    checkoutError,
    clientSecret,
    canCheckout,
    provider,
    buy: handleBuy,
    handleUnreachable: handleEmbeddedUnreachable,
    closeOverlay,
  } = usePackCheckout(pack, preopened);

  const axes = scoreAxes(pack.financialSnapshot);
  const verdict = splitVerdict(pack.qaVerdictSummary);

  // Map internal axis keys to buyer-facing labels so the scored section
  // reads as consumer content, not internal tooling.
  const axisLabel = (key: string): string => {
    const labels: Record<string, string> = {
      pain_acuity: 'Real demand',
      money_provability: 'People will pay',
      defensibility: 'Hard to copy',
      distribution: 'Can reach buyers',
      build_feasibility: 'You can build this',
      automatability: 'Runs without you',
    };
    return labels[key] ?? key.replace(/_/g, ' ');
  };

  // Back-to-top visibility, revealed after scrolling past the hero (~600px).
  const [showBackToTop, setShowBackToTop] = React.useState(false);
  React.useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 600);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Track viewed pack for the 'Recently viewed' row on the catalog
  React.useEffect(() => {
    try {
      const raw = localStorage.getItem('mumchimp.recentlyViewed');
      const ids: string[] = raw ? JSON.parse(raw) : [];
      const next = [pack.id, ...ids.filter((id) => id !== pack.id)].slice(0, 10);
      localStorage.setItem('mumchimp.recentlyViewed', JSON.stringify(next));
    } catch { /* storage unavailable */ }
  }, [pack.id]);

  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';
  const priceLabel = formatPrice(pack.price);
  const payback = paybackEquation(pack.price, pack.financialSnapshot);

  const notifyHref =
    `mailto:${LEGAL.supportEmail}` +
    `?subject=${encodeURIComponent(`Notify me when "${pack.title}" opens`)}` +
    `&body=${encodeURIComponent(`Please email me the moment this pack is available to buy: ${pack.title} (${pack.id}).`)}`;

  // Shared checkout body, rendered in the desktop sticky card and the mobile purchase bar.
  // Deliberately an element VALUE, not a component defined during render: a component declared
  // inline is a new type on every render, so React unmounts and remounts the subtree and the
  // checkout button loses its state mid-purchase. The same element object can be placed twice,
  // React instantiates it independently at each position.
  const checkoutBody = (
    <>
      <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-muted">One time price</span>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-4xl font-black tracking-tight text-text">{priceLabel}</span>
        <span className="text-sm font-medium text-muted">once</span>
      </div>

      <div className="mt-4 flex items-center gap-2 rounded-lg bg-success/5 px-3 py-2 text-xs font-semibold text-success">
        <Icon name="shield" size={14} />
        14 day money back, no questions asked
      </div>

      <span className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-bold text-success">
        <Icon name="verified" size={12} /> Survived 6 checks
      </span>

      {pack.financialSnapshot &&
        (pack.financialSnapshot.month1Revenue ||
          pack.financialSnapshot.ltvCac ||
          pack.financialSnapshot.paybackMonths) && (
          <div className="mt-4 rounded-lg border border-border/70 bg-bg/40 p-3">
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
              Modelled economics
            </span>
            <dl className="mt-2 space-y-1.5 text-xs">
              {pack.financialSnapshot.month1Revenue && (
                <div className="flex items-baseline justify-between gap-2">
                  <dt className="text-muted">Month 1 revenue</dt>
                  <dd className="font-bold text-text">{pack.financialSnapshot.month1Revenue}</dd>
                </div>
              )}
              {pack.financialSnapshot.ltvCac && (
                <div className="flex items-baseline justify-between gap-2">
                  <dt className="text-muted">Lifetime value to cost</dt>
                  <dd className="font-bold text-text">{pack.financialSnapshot.ltvCac}</dd>
                </div>
              )}
              {pack.financialSnapshot.paybackMonths && (
                <div className="flex items-baseline justify-between gap-2">
                  <dt className="text-muted">Payback</dt>
                  <dd className="font-bold text-text">{pack.financialSnapshot.paybackMonths}</dd>
                </div>
              )}
            </dl>
            <p className="mt-2 text-[10px] leading-relaxed text-muted">
              Computed by the engine from the pack&apos;s verified inputs. Your own results will differ.
            </p>
          </div>
        )}

      {/* The one comparison a buyer is actually making, put where they make it. £49 alone is a
          cost with nothing to weigh it against; the figures that answer "worth it?" were already
          on this page, 400px below, inside "Modelled economics". No new engine field, the only
          new thing is the division, and it is shown. `paybackEquation` returns null (renders
          nothing) whenever the comparison would not be honest, including when the modelled
          revenue fails to clear the price: this must never be a widget that appears only when
          it flatters the sale. */}
      {payback && (
        <div className="mt-4 rounded-lg border border-border/70 bg-bg/40 p-3">
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
            What it has to earn back
          </span>
          <p className="mt-2 font-mono text-xs leading-relaxed text-text">
            {payback.revenueLabel} <span className="text-muted">modelled month 1</span> ÷{' '}
            {payback.priceLabel} <span className="text-muted">pack</span> ={' '}
            <span className="font-bold">{payback.multiple}×</span>
          </p>
          <p className="mt-2 text-xs leading-relaxed text-text/80">
            One month at the modelled rate covers the pack {payback.multiple} times over
            {payback.paybackMonths ? `, with the build itself modelled to pay back in ${payback.paybackMonths}` : ''}.
          </p>
          {/* The same hedge as the Modelled economics box below, a model, not a forecast, and
              not a claim about this buyer. It travels with the number wherever the number goes. */}
          <p className="mt-2 text-[10px] leading-relaxed text-muted">
            Computed by the engine from the pack&apos;s verified inputs. Your own results will differ.
          </p>
        </div>
      )}

      {checkoutError && (
        <div className="mt-4 rounded-lg border border-danger/20 bg-danger/5 p-3 text-xs text-danger">
          {checkoutError}
        </div>
      )}

      {canCheckout ? (
        <>
          <button
            onClick={handleBuy}
            disabled={checkingOut}
            className="mt-4 w-full bg-text py-4 text-sm font-bold uppercase tracking-wide text-white transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          >
            {/* Not "Redirecting…": the embedded path opens a panel in place and never navigates,
                so that label promised a page change that never came. This wording is true of both
                routes, the overlay and the hosted redirect. */}
            {checkingOut ? 'Opening secure checkout…' : `Get instant access, ${priceLabel}`}
          </button>
          {/* Under the button, not above it: the address only matters once the buyer has decided,
              and putting an account-shaped sentence in front of the price is how a storefront
              teaches guests that they need an account. They do not. */}
          <BuyerIdentityNote className="mt-3 text-xs leading-relaxed text-muted" />
          {/* Secondary on purpose: buying this one pack stays a single click above. The basket is
              only a gain for someone who wants several, so it never sits in front of the direct path. */}
          <div className="mt-3">
            <AddToCartButton line={{ id: pack.id, title: pack.title, price: pack.price }} />
          </div>
        </>
      ) : (
        <>
          <a
            href={notifyHref}
            className="mt-4 block w-full bg-text py-4 text-center text-sm font-bold uppercase tracking-wide text-white transition-all hover:-translate-y-0.5 active:translate-y-0"
          >
            Notify me when this opens
          </a>
          <p className="mt-2 text-xs font-medium text-muted">
            Checkout is opening shortly. Tap to get a single email the moment this pack goes live.
          </p>
        </>
      )}

      <div className="mt-7 space-y-3 border-t border-border/70 pt-6">
        {([
          { icon: 'download', text: 'Instant download the moment you pay' },
          { icon: 'lock', text: `Secure checkout via ${providerLabel}` },
          { icon: 'mail', text: 'A private link sent straight to you' },
        ] satisfies { icon: IconName; text: string }[]).map((feat, i) => (
          <div key={i} className="flex items-center gap-3 text-xs font-medium text-muted">
            <Icon name={feat.icon} size={14} className="text-text/60" />
            {feat.text}
          </div>
        ))}
      </div>

      <p className="mt-6 text-center text-[11px] leading-relaxed text-muted">
        A pack is grounded research, not a promise of business success. See our{' '}
        <Link href="/refund" className="font-semibold text-primary hover:underline">refund policy</Link>.
      </p>
    </>
  );

  return (
    <MarketingLayout>
      <Seo
        title={`${pack.title} · A business idea that survived our filter`}
        description={pack.oneLine || undefined}
        ogType="product"
        ogImagePath={packOgImagePath(pack.id)}
        ogImageAlt={`${pack.title}, a £49 researched business pack from Mumchimp`}
        jsonLd={graph(
          productJsonLd(pack),
          // The trail Google renders in place of the raw URL, so a result reads
          // "Mumchimp › Business ideas › <pack>" instead of a 16-hex-character id.
          breadcrumbNode([
            { name: 'Mumchimp', path: '/' },
            { name: 'Business ideas', path: '/ideas' },
            { name: pack.title, path: `/pack/${pack.id}` },
          ]),
        )}
      />

      {clientSecret && (
        <EmbeddedCheckoutPanel
          clientSecret={clientSecret}
          title={pack.title}
          onClose={closeOverlay}
          onUnreachable={handleEmbeddedUnreachable}
        />
      )}

      <Section bg="bg" width="6xl" className="!pt-8 !pb-24">
        {/* Breadcrumb */}
        <Breadcrumbs
          items={[
            { href: '/', label: 'Catalog' },
            { href: '/ideas', label: 'Browse by category' },
            { href: '#', label: pack.title },
          ]}
        />

        {/* Back to catalog -- prominent, always visible */}
        <Link
          href="/"
          className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-muted hover:text-text transition-colors"
        >
          <Icon name="arrowRight" size={14} className="rotate-180" />
          Back to catalog
        </Link>

        <ShareRow title={pack.title} />

        <div className="mt-6 flex flex-col gap-12 lg:flex-row">
          {/* Left: Content */}
          <div className="flex-1">
            {/* Document header: left-rule + verified badge, no decorative cover */}
            <div className="mb-6 border-l-[3px] border-l-primary pl-5">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: '#0D9488' }}>
                <Icon name="verified" size={13} /> Survived six checks
              </span>
            </div>

            <h1 className="text-4xl font-black leading-tight tracking-tight text-text md:text-5xl">
              {pack.title}
            </h1>
            <p className="mt-5 max-w-[65ch] text-lg leading-relaxed text-text/80">{pack.oneLine}</p>
            {pack.subhead && (
              <p className="mt-3 max-w-[65ch] text-base leading-relaxed text-text/70">{pack.subhead}</p>
            )}

            {(pack.market ||
              freshnessLabel(pack.verifiedAt) ||
              (typeof pack.sourceCount === 'number' && pack.sourceCount > 0) ||
              verdict.summary) && (
              <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs font-medium text-muted">
                {/* Near the title, not just in the "Is this for you?" section further down,
                    a buyer landing here from the "Also available" shelf should see straight
                    away which market this pack is for, without scrolling. */}
                {pack.market && (
                  <span className="inline-flex items-center gap-1.5">
                    <Icon name="landmark" size={13} />
                    {marketLabel(pack.market)} market
                  </span>
                )}
                {freshnessLabel(pack.verifiedAt) && (
                  <span className="inline-flex items-center gap-1.5">
                    <Icon name="scheduled" size={13} />
                    {freshnessLabel(pack.verifiedAt)}
                  </span>
                )}
                {typeof pack.sourceCount === 'number' && pack.sourceCount > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <Icon name="check" size={13} className="text-success" />
                    {pack.sourceCount} sources cited
                  </span>
                )}
                {verdict.summary && <span className="max-w-[60ch]">{verdict.summary}</span>}
              </div>
            )}

            {/* Mobile purchase bar, keeps price + CTA above the fold on small screens */}
            <div className="mt-8 border border-border bg-surface p-6 lg:hidden">
              {checkoutBody}
            </div>

            {/* Deliverables first: "what do I actually receive for £49" is the question that stalls a
                digital purchase, and it has to be answered before the trust argument. */}
            <div className="mt-12">
              <PackContentsSection
                heading="What’s inside your download"
                lead={`The moment you pay, you download the whole pack. ${PACK_CONTENTS.length} documents, no drip feed, no login.`}
                sourceCount={pack.sourceCount}
              />
            </div>

            {/* How the idea was attacked, the filter, stated as the filter. The per-pack answers
                are the scored axes immediately below and the QA report inside the pack; see the
                CHECKS doc comment for why this block deliberately makes no per-check claim. */}
            <div className="mt-12">
              <h2 className="text-xl font-bold tracking-tight text-text">Six ways we tried to kill it</h2>
              <p className="mt-2 text-sm text-muted">
                Each one is an attack, not a rubber stamp. An idea dies on the first front where we find
                cited evidence against it, and a listing means none of the six produced that evidence.
                Finding nothing is not the same as finding a green light, so the scores below show where
                this pack&rsquo;s case is strong and where it is thin.
              </p>
              <ul className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {CHECKS.map((check, i) => (
                  <li
                    key={check}
                    className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3"
                  >
                    {/* A numeral, not a tick: a green success mark on a static line reads as this
                        pack's verdict on that check, which is exactly what this page cannot know. */}
                    <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-border bg-bg font-mono text-[11px] font-bold text-muted">
                      {i + 1}
                    </span>
                    <span className="text-sm font-medium text-text">{check}</span>
                  </li>
                ))}
              </ul>
              <Link
                href="/how-it-works"
                className="mt-5 inline-flex items-center gap-1.5 text-sm font-bold text-primary hover:underline"
              >
                See how each check works
                <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {/* The stress test, scored, show the stress. Real per-pack scores, including the
                weak axes, plus the surfaced main risk. Hiding the cons would kill the pros. */}
            {(axes.length > 0 || verdict.risk) && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">How it scores</h2>
                <p className="mt-2 max-w-[60ch] text-sm text-muted">
                  Six things we measure. The strong ones are strengths. The weaker ones are things
                  you should know before you build.
                </p>

                {axes.length > 0 && (
                  <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                    {axes.map((a) => {
                      const tone =
                        a.value >= 4 ? 'bg-success' : a.value === 3 ? 'bg-primary' : 'bg-warning';
                      return (
                        <div key={a.label} className="flex flex-col gap-1.5">
                          <div className="flex items-baseline justify-between gap-2">
                            <dt className="text-sm font-semibold text-text">{axisLabel(a.label)}</dt>
                            <dd className="font-mono text-xs font-bold text-muted">
                              {a.value} / {a.outOf}
                            </dd>
                          </div>
                          <div className="flex gap-1" aria-hidden>
                            {Array.from({ length: a.outOf }).map((_, i) => (
                              <span
                                key={i}
                                className={cx(
                                  'h-1.5 flex-1 rounded-full',
                                  i < a.value ? tone : 'bg-border',
                                )}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </dl>
                )}

                {verdict.risk && (
                  <div className="mt-6 border border-warning/30 bg-warning/5 p-5">
                    <div className="flex items-center gap-2">
                      <Icon name="shield" size={15} className="text-warning" />
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-warning">
                        Where this could break
                      </span>
                    </div>
                    <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-text/80">{verdict.risk}</p>
                    <p className="mt-2 text-xs text-muted">
                      We surface the strongest argument against the idea, with its source, inside the pack.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Is this for you?, the concrete fit signals, when the pack carries them */}
            {(pack.market || pack.whoPays || pack.timeToFirstRevenue) && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">Is this for you?</h2>
                {/* The engine's own tags, in the buyer's words. Absent facets render nothing:
                    "Effort to build" used to print the legacy `effortTag` string, which was never
                    defined to mean how much of delivery is machine-doable (spec 2.3). */}
                <FacetChips pack={pack} className="mt-4" />
                <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {pack.market && (
                    <div className="flex flex-col border border-border bg-surface p-5 sm:col-span-3">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Market
                      </span>
                      <span className="mt-1.5 text-sm font-semibold text-text">
                        {marketLabel(pack.market)}
                      </span>
                      {/* State it plainly: the research is about this jurisdiction, and the
                          pack is still sold in GBP. Leaving that implicit invites a refund. */}
                      <span className="mt-1.5 text-xs leading-relaxed text-muted">
                        The opportunity, its evidence and its economics are researched for this
                        market. The pack itself is priced and sold in GBP.
                      </span>
                    </div>
                  )}
                  {pack.whoPays && (
                    <div className="flex flex-col border border-border bg-surface p-5 sm:col-span-3">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Who pays
                      </span>
                      <span className="mt-1.5 text-sm leading-relaxed text-text/80">{pack.whoPays}</span>
                    </div>
                  )}
                  {pack.timeToFirstRevenue && (
                    <div className="flex flex-col border border-border bg-surface p-5">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Time to first revenue
                      </span>
                      <span className="mt-1.5 text-sm font-semibold text-text">{pack.timeToFirstRevenue}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* The per-pack table of contents. The generic four-asset breakdown is higher up the page. */}
            <div className="mt-12">
              <h2 className="text-xl font-bold tracking-tight text-text">The table of contents</h2>
              <p className="mt-2 max-w-[60ch] text-sm text-muted">
                Exactly what this pack covers, plus a blurred look at the document you receive.
              </p>

              {/* Blurred deliverable preview. Grey rectangles said "a document exists"; this
                  page's whole claim is that a SPECIFIC, sourced document exists, and a skeleton
                  is the one element on the page that could be identical for a pack with nothing
                  behind it. So the preview is now the pack's own text, the same headings and
                  sourced lines rendered elsewhere on this page, set as a document and blurred.
                  Blur is a legible-shape effect: what shows through is real structure, real
                  paragraph lengths, real tables. Nothing is invented to fill it; when there is
                  no real content to show, `PreviewDocument` renders the neutral skeleton. */}
              <PreviewDocument pack={pack} />

              {/* Per-pack contents only. The generic four-asset list now lives once, above, so it
                  cannot contradict this section. */}
              {pack.whatYouGet && pack.whatYouGet.length > 0 && (
                <ul className="mt-6 list-none space-y-3 p-0">
                  {pack.whatYouGet.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-3 border border-border bg-surface p-5"
                    >
                      <span className="mt-0.5 font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span className="text-sm leading-relaxed text-text/80">{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* A look inside, real sourced lines lifted straight from the pack */}
            {pack.sampleExtract && pack.sampleExtract.length > 0 && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">A look inside</h2>
                <p className="mt-2 text-sm text-muted">
                  Real, sourced lines taken straight from the pack. This is the level of grounding behind
                  every claim you are buying.
                </p>
                {/* Peek inside: a page you are looking at the top of. The fade is over the page
                    itself, never over invented text, every line below is really in the pack, and
                    nothing is blurred to imply content that does not exist. */}
                <div className="relative mt-6 overflow-hidden border border-border bg-surface">
                  <div className="flex items-center gap-2 border-b border-border bg-bg/60 px-5 py-3">
                    <Icon name="briefcase" size={14} className="text-primary" />
                    <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
                      Extract · verification dossier
                    </span>
                  </div>
                  <ul className="list-none space-y-3 p-6 pb-16">
                    {pack.sampleExtract.map((line, i) => (
                      <li
                        key={i}
                        className="border-l-2 border-l-success pl-4 text-sm leading-relaxed text-text/80"
                      >
                        {line}
                      </li>
                    ))}
                  </ul>
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white via-white/85 to-transparent" />
                  <span className="absolute inset-x-0 bottom-4 text-center text-xs font-semibold text-muted">
                    The rest of this section, and three more documents, are in the pack.
                  </span>
                </div>
              </div>
            )}

            {/* The receipts */}
            <div className="mt-12 border border-border bg-surface p-6">
              <div className="mb-3 flex items-center gap-2.5">
                <Icon name="verified" className="text-success" size={18} />
                <span className="font-mono text-xs font-bold uppercase tracking-widest text-text">The receipts</span>
              </div>
              <p className="max-w-[64ch] text-sm leading-relaxed text-text/70">
                Every figure and claim in this pack is traced to external evidence you can open and check.
                No hand waving, no vibes. Audit reference{' '}
                <span className="font-mono text-xs text-muted">{pack.dossierRef}</span>.
              </p>
              <Link
                href="/sample"
                className="mt-4 inline-flex items-center gap-1.5 text-sm font-bold text-primary hover:underline"
              >
                Want to see the depth first? Read the free sample report
                <Icon name="arrowRight" size={14} />
              </Link>
            </div>

            {/* Hides itself unless at least two packs genuinely score (AC-21). */}
            <SimilarPacks pack={pack} all={catalog} />
          </div>

          {/* Right: Checkout (desktop sticky) */}
          <div className="hidden w-full shrink-0 lg:block lg:w-80">
            <div className="sticky top-24 border border-border bg-surface p-7">
              {checkoutBody}
            </div>
          </div>
        </div>

        {/* Sticky mobile checkout bar, keeps price + CTA above the fold on phones. */}
        {canCheckout && !clientSecret && (
          <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface p-3 pb-[env(safe-area-inset-bottom)] lg:hidden">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="text-xs font-medium text-muted">One time</span>
                <span className="ml-2 text-lg font-black tracking-tight text-text">{priceLabel}</span>
              </div>
              <button
                onClick={handleBuy}
                disabled={checkingOut}
                className="bg-text px-5 py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {checkingOut ? 'Opening…' : `Buy, ${priceLabel}`}
              </button>
            </div>
          </div>
        )}

        {/* Back to top, desktop-only, revealed after scrolling. */}
        {showBackToTop && (
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="fixed bottom-6 right-4 z-20 hidden rounded-full border border-border bg-surface p-3 shadow-md transition-colors hover:bg-bg lg:block"
            aria-label="Back to top"
          >
            <Icon name="trending-up" size={16} />
            <span className="sr-only">Back to top</span>
          </button>
        )}
      </Section>
    </MarketingLayout>
  );
}

/**
 * The blurred look inside the deliverable.
 *
 * Built from the pack's OWN text, `whatYouGet` as the section headings a real build spec
 * carries, `sampleExtract` as the sourced body lines, the modelled economics as the figures
 * table. Nothing here is generated to fill space: every string is one the engine wrote and this
 * page already renders in full elsewhere, which is exactly why it is safe to show blurred.
 *
 * Falls back to the neutral skeleton when a pack carries neither bullets nor extracts (older
 * packs, and any pack whose bundle is incomplete). Showing a plausible-looking fake document for
 * a pack with nothing behind it is the single worst thing this element could do.
 */
function PreviewDocument({ pack }: { pack: PackDetails }) {
  const headings = pack.whatYouGet ?? [];
  const body = pack.sampleExtract ?? [];
  const figures = Object.entries(pack.financialSnapshot ?? {}).filter(
    ([, v]) => typeof v === 'string' && v.trim(),
  );
  const hasRealContent = headings.length > 0 || body.length > 0;

  return (
    <div className="relative mt-6 overflow-hidden border border-border bg-surface">
      {/* aria-hidden + a fixed height: this is an image of a document, not content. A screen
          reader gets the real, unblurred lists further down the page instead, and the clamp
          stops a pack with many bullets rendering a metre of blur. */}
      <div aria-hidden className="max-h-[320px] select-none overflow-hidden p-7 blur-[5px]">
        {hasRealContent ? (
          <div className="space-y-3">
            <p className="text-[13px] font-black leading-tight tracking-tight text-text">{pack.title}</p>
            {headings.slice(0, 2).map((h, i) => (
              <div key={`h-${i}`} className="space-y-1.5">
                <p className="text-[11px] font-bold uppercase tracking-widest text-primary">
                  {String(i + 1).padStart(2, '0')} · {h}
                </p>
                {body.slice(i * 2, i * 2 + 2).map((line, j) => (
                  <p key={`b-${i}-${j}`} className="text-[10px] leading-relaxed text-text/70">
                    {line}
                  </p>
                ))}
              </div>
            ))}
            {figures.length > 0 && (
              <div className="flex gap-3 pt-1">
                {figures.slice(0, 3).map(([label, value]) => (
                  <div key={label} className="flex-1 rounded-lg bg-bg p-2.5">
                    <p className="text-[8px] font-bold uppercase tracking-widest text-muted">{label}</p>
                    <p className="mt-1 text-[13px] font-black text-text">{value}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* No real content to show. Neutral shapes that claim nothing. */
          <div className="space-y-2.5">
            <div className="h-3 w-2/5 rounded bg-text/80" />
            <div className="h-2 w-full rounded bg-text/15" />
            <div className="h-2 w-11/12 rounded bg-text/15" />
            <div className="h-2 w-10/12 rounded bg-text/15" />
            <div className="mt-4 h-3 w-1/3 rounded bg-primary/70" />
            <div className="h-2 w-full rounded bg-text/15" />
            <div className="h-2 w-9/12 rounded bg-text/15" />
          </div>
        )}
      </div>
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-white via-white/70 to-white/30">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-xs font-bold text-text shadow-sm">
          <Icon name="lock" size={14} className="text-muted" />
          Unlocks the moment you buy
        </span>
      </div>
    </div>
  );
}

/** Share buttons: copy link, X, LinkedIn. URL via useSyncExternalStore to keep SSR clean. */
function ShareRow({ title }: { title: string }) {
  const [copied, setCopied] = React.useState(false);

  const url = React.useSyncExternalStore(
    subscribeToNothing,
    () => window.location.origin + window.location.pathname,
    () => '',
  );

  const handleCopy = React.useCallback(() => {
    track('pack_shared', 'copy');
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [url]);

  const btnClass =
    'rounded-full border border-border bg-surface p-2 text-muted hover:text-text hover:border-text/30 transition-colors';

  return (
    <div className="mt-4 flex items-center gap-2">
      {/* Copy link */}
      <button type="button" onClick={handleCopy} className={btnClass} aria-label="Copy link">
        {copied ? (
          <span className="font-mono text-[10px] font-bold text-success">Copied ✓</span>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        )}
      </button>

      {/* X (Twitter) */}
      <a
        href={`https://x.com/intent/tweet?text=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`}
        target="_blank"
        rel="noopener noreferrer"
        className={btnClass}
        onClick={() => track('pack_shared', 'x')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
      </a>

      {/* LinkedIn */}
      <a
        href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`}
        target="_blank"
        rel="noopener noreferrer"
        className={btnClass}
        onClick={() => track('pack_shared', 'linkedin')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
      </a>
    </div>
  );
}

export const getServerSideProps: GetServerSideProps = async ({ params }) => {
  try {
    const id = params?.id as string;
    // Fetched together, not in series: the "same mechanics" row needs the catalogue, and paying
    // two sequential round trips before first byte would be a real cost for a decorative row.
    // The catalogue is best-effort, a failure there must not 404 a page someone is buying from.
    const [pack, catalog] = await Promise.all([
      fetchPackDetails(id),
      fetchCatalog().catch(() => [] as Pack[]),
    ]);
    return {
      props: { pack, catalog },
    };
  } catch (error) {
    console.error('Error fetching pack details:', error);
    const message =
      error instanceof Error ? error.message : 'Could not load pack details.';
    return {
      props: { pack: null, catalog: [], error: message },
    };
  }
};

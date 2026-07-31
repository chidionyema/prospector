import React, { useState } from 'react';
import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { productJsonLd } from '@/lib/productJsonLd';
import { Icon, CoverArt } from '@/components/ui';
import type { IconName } from '@/components/ui/Icon';
import { cx } from '@/components/ui/cx';
import { Section } from '@/components/marketing/blocks';
import { PackContentsSection, PACK_CONTENTS } from '@/components/marketing/PackContents';
import { createEmbeddedCheckout, createStripeCheckout, fetchCatalog, fetchPackDetails, formatPrice, freshnessLabel, marketLabel, scoreAxes, splitVerdict, Pack, PackDetails } from '@/lib/api/client';
import { EmbeddedCheckoutPanel } from '@/components/checkout/EmbeddedCheckoutPanel';
import { resolveStripeCheckout } from '@/lib/checkoutRoute';
import { PREOPENED_CHECKOUT_PARAM, preopenedClientSecret } from '@/lib/preopenedCheckout';
import { stripeConfigured } from '@/lib/stripe';
import { FacetChips } from '@/components/discovery/FacetChips';
import { SimilarPacks } from '@/components/discovery/SimilarPacks';
import { initPaddle, openPaddleCheckout, paddleConfigured } from '@/lib/paddle';
import { LEGAL } from '@/lib/config';
import { coverFor } from '@/lib/cover';
import { paybackEquation } from '@/lib/payback';
import { AddToCartButton } from '@/components/cart/AddToCartButton';

interface PackPageProps {
  pack: PackDetails;
  /** The rest of the catalogue, for the "same mechanics" row. Empty when that fetch failed —
   *  a catalogue outage must never take down a page someone is trying to buy from. */
  catalog: Pack[];
}

/**
 * The six attacks every idea must survive before it can be listed.
 * Framed as the attack that failed (refutational), not a positive rubber stamp:
 * refutational two-sided framing out-persuades one-sided "validated" claims
 * (Allen 1991, O'Keefe 1999, Eisend 2006).
 */
const CHECKS = [
  'We tried to prove the pain was imagined. It was real.',
  'We tried to show the value would not last. It held.',
  'We tried to prove incumbents own the space. There was room.',
  'We tried to find that no one would pay. A payer was there.',
  'We tried to show it cannot reach a market. A route existed.',
  'We tried to find a legal landmine. It came back clean.',
];

// The deliverable list lives in one shared place (PackContents) so this page and the homepage can
// never drift into promising different things for the same £49.

export default function PackPage({ pack, catalog }: PackPageProps) {
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  /** What this page has decided about the overlay, which is NOT the same question as whether it
   *  is open — see `clientSecret` below.
   *   - `undefined`: nothing decided yet, so a pre-opened session in the URL is free to win.
   *   - `null`: decided closed. Also every provider and build that pays through the hosted
   *     redirect instead; null is not "failed".
   *   - a string: this session is open. */
  const [checkoutSession, setCheckoutSession] = useState<string | null | undefined>(undefined);

  // A session created out of band opens the overlay directly, so the live render can be proven
  // on a smoke-test-priced session instead of a full-price one. Ignored unless the value has the
  // shape of a client secret; see lib/preopenedCheckout for why this leaks nothing.
  const router = useRouter();
  const preopened = preopenedClientSecret(router.query[PREOPENED_CHECKOUT_PARAM]);

  // Derived, not copied into state by an effect. The URL is already a source of truth, so the
  // effect that used to mirror it into state bought nothing and cost two things: a first paint
  // with the overlay shut before the effect ran, and a re-open bug waiting to happen — closing
  // sets null, and an effect keyed on `preopened` would put it straight back. The three-state
  // above is what keeps "not decided yet" distinguishable from "closed": only the former defers
  // to the query string.
  const clientSecret = checkoutSession === undefined ? preopened : checkoutSession;

  const axes = scoreAxes(pack.financialSnapshot);
  const verdict = splitVerdict(pack.qaVerdictSummary);

  const provider = pack.paymentProvider || 'paddle';
  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';
  const priceLabel = formatPrice(pack.price);
  const payback = paybackEquation(pack.price, pack.financialSnapshot);

  const handleBuy = async () => {
    setCheckingOut(true);
    setCheckoutError(null);

    try {
      if (provider === 'stripe') {
        await handleStripeCheckout(pack);
      } else {
        await handlePaddleCheckout(pack);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      setCheckoutError(message || 'Checkout failed. Please try again.');
    } finally {
      setCheckingOut(false);
    }
  };

  const handleStripeCheckout = async (pack: PackDetails) => {
    // Embedded is preferred but never required. Two separate reasons it may not happen — no
    // Stripe.js key in this build, or a server that answered with a hosted URL anyway — and
    // both land on exactly the redirect that existed before embedded checkout was added.
    //
    // The buy button is deliberately NOT gated on `stripeConfigured`: gating it on the
    // publishable key once hid every buy button in production when the key was left out of the
    // web build args (see hasProvisionedPrice below). That failure must not come back through
    // this path, so a missing key degrades the SURFACE, never the sale.
    // resolveStripeCheckout owns the "embedded is preferred but never required" guarantee, and
    // is unit-tested for every way the embedded attempt can fail — including a THROW, which
    // previously escaped to handleBuy and rendered "Checkout failed" for a completable sale.
    // createStripeCheckout already refuses any URL that is not Stripe's hosted checkout.
    const route = await resolveStripeCheckout({
      stripeConfigured,
      requestEmbedded: () => createEmbeddedCheckout(pack.id),
      requestHosted: () => createStripeCheckout(pack.id),
    });

    if (route.kind === 'embedded') {
      setCheckoutSession(route.clientSecret);
      return;
    }
    window.location.href = route.url;
  };

  /**
   * The overlay opened but cannot work in this browser — send the buyer to hosted checkout.
   *
   * resolveStripeCheckout's fallback only covers a failed session REQUEST; a session that is
   * issued and then cannot render had no escape at all, and the buyer saw Stripe's own "cannot
   * be reached" message with nowhere to go (LIVE_RAIL_SMOKE_TEST.md, 2026-07-31).
   *
   * A new hosted session is requested rather than reusing the embedded one: an embedded session
   * has no `url`, so there is nothing to redirect to. The panel closes first, so a hosted request
   * that itself fails leaves a visible error on the pack page instead of a frozen overlay.
   */
  const handleEmbeddedUnreachable = async () => {
    setCheckoutSession(null);
    try {
      window.location.href = await createStripeCheckout(pack.id);
    } catch {
      setCheckoutError(
        'Checkout could not load in this browser. Please try another browser, or disable any ad or privacy blocker for this page.',
      );
    }
  };

  const handlePaddleCheckout = async (pack: PackDetails) => {
    await initPaddle();
    openPaddleCheckout(pack.providerPriceId);
  };

  // Stripe checkout is a server-issued redirect to Stripe's HOSTED page (handleStripeCheckout
  // above); it never boots Stripe.js, so the publishable key has no bearing on whether a pack
  // can be bought. Gating on it silently hid every buy button in production once the key was
  // left out of the web build args — a sales outage with no error anywhere. Gate instead on the
  // one thing that must actually be true: the pack points at a real provisioned price.
  const hasProvisionedPrice =
    typeof pack.providerPriceId === 'string' &&
    pack.providerPriceId.length > 0 &&
    !pack.providerPriceId.startsWith('price_stub');

  const canCheckout =
    (provider === 'stripe' && hasProvisionedPrice) ||
    (provider !== 'stripe' && paddleConfigured);

  const notifyHref =
    `mailto:${LEGAL.supportEmail}` +
    `?subject=${encodeURIComponent(`Notify me when "${pack.title}" opens`)}` +
    `&body=${encodeURIComponent(`Please email me the moment this pack is available to buy: ${pack.title} (${pack.id}).`)}`;

  // Shared checkout body — rendered in the desktop sticky card and the mobile purchase bar.
  // Deliberately an element VALUE, not a component defined during render: a component declared
  // inline is a new type on every render, so React unmounts and remounts the subtree and the
  // checkout button loses its state mid-purchase. The same element object can be placed twice —
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
          on this page, 400px below, inside "Modelled economics". No new engine field — the only
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
          {/* The same hedge as the Modelled economics box below — a model, not a forecast, and
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
            className="mt-4 w-full rounded-xl bg-text py-4 text-sm font-bold uppercase tracking-wide text-white shadow-[0_4px_16px_rgba(15,23,42,0.18)] transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.24)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          >
            {/* Not "Redirecting…": the embedded path opens a panel in place and never navigates,
                so that label promised a page change that never came. This wording is true of both
                routes — the overlay and the hosted redirect. */}
            {checkingOut ? 'Opening secure checkout…' : `Get instant access — ${priceLabel}`}
          </button>
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
            className="mt-4 block w-full rounded-xl bg-text py-4 text-center text-sm font-bold uppercase tracking-wide text-white shadow-[0_4px_16px_rgba(15,23,42,0.18)] transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.24)] active:translate-y-0"
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
        jsonLd={productJsonLd(pack)}
      />

      {clientSecret && (
        <EmbeddedCheckoutPanel
          clientSecret={clientSecret}
          title={pack.title}
          onClose={() => setCheckoutSession(null)}
          onUnreachable={handleEmbeddedUnreachable}
        />
      )}

      <Section bg="bg" width="6xl" className="!pt-8 !pb-24">
        {/* Breadcrumb */}
        <Link
          href="/#catalog"
          className="inline-flex items-center gap-2 text-sm font-semibold text-muted transition-colors hover:text-text"
        >
          <Icon name="arrowRight" size={14} className="rotate-180" />
          All packs
        </Link>

        <div className="mt-6 flex flex-col gap-12 lg:flex-row">
          {/* Left: Content */}
          <div className="flex-1">
            {/* Cover */}
            <div className={`relative mb-8 h-44 overflow-hidden rounded-2xl ${coverFor(pack.id)}`}>
              <CoverArt title={pack.title} />
              <span className="absolute left-5 top-5 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-3 py-1.5 text-xs font-bold uppercase tracking-wide text-text shadow-sm">
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

            {(freshnessLabel(pack.verifiedAt) ||
              (typeof pack.sourceCount === 'number' && pack.sourceCount > 0) ||
              verdict.summary) && (
              <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs font-medium text-muted">
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

            {/* Mobile purchase bar — keeps price + CTA above the fold on small screens */}
            <div className="mt-8 rounded-2xl border border-border bg-white p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] lg:hidden">
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

            {/* Cleared all six checks — the proof block */}
            <div className="mt-12">
              <h2 className="text-xl font-bold tracking-tight text-text">Six ways we tried to kill it</h2>
              <p className="mt-2 text-sm text-muted">
                Each check is an attack, not a rubber stamp. Every claim that survived is backed by a real
                source you can open. Ideas that fail any one of the six never reach the store.
              </p>
              <ul className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {CHECKS.map((check) => (
                  <li
                    key={check}
                    className="flex items-center gap-3 rounded-lg border border-border bg-white px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
                  >
                    <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-success/10 text-success">
                      <Icon name="check" size={13} />
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

            {/* The stress test, scored — show the stress. Real per-pack scores, including the
                weak axes, plus the surfaced main risk. Hiding the cons would kill the pros. */}
            {(axes.length > 0 || verdict.risk) && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">The stress test, scored</h2>
                <p className="mt-2 max-w-[60ch] text-sm text-muted">
                  We score every survivor on six axes, out of five. We show you the weak ones too. A high
                  bar is a strength, a low bar is a trade you should know about before you build.
                </p>

                {axes.length > 0 && (
                  <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                    {axes.map((a) => {
                      const tone =
                        a.value >= 4 ? 'bg-success' : a.value === 3 ? 'bg-primary' : 'bg-warning';
                      return (
                        <div key={a.label} className="flex flex-col gap-1.5">
                          <div className="flex items-baseline justify-between gap-2">
                            <dt className="text-sm font-semibold text-text">{a.label}</dt>
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
                  <div className="mt-6 rounded-xl border border-warning/30 bg-warning/5 p-5">
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

            {/* Is this for you? — the concrete fit signals, when the pack carries them */}
            {(pack.market || pack.whoPays || pack.timeToFirstRevenue) && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">Is this for you?</h2>
                {/* The engine's own tags, in the buyer's words. Absent facets render nothing:
                    "Effort to build" used to print the legacy `effortTag` string, which was never
                    defined to mean how much of delivery is machine-doable (spec 2.3). */}
                <FacetChips pack={pack} className="mt-4" />
                <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {pack.market && (
                    <div className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] sm:col-span-3">
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
                    <div className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] sm:col-span-3">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Who pays
                      </span>
                      <span className="mt-1.5 text-sm leading-relaxed text-text/80">{pack.whoPays}</span>
                    </div>
                  )}
                  {pack.timeToFirstRevenue && (
                    <div className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
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
                  behind it. So the preview is now the pack's own text — the same headings and
                  sourced lines rendered elsewhere on this page — set as a document and blurred.
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
                      className="flex items-start gap-3 rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
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

            {/* A look inside — real sourced lines lifted straight from the pack */}
            {pack.sampleExtract && pack.sampleExtract.length > 0 && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">A look inside</h2>
                <p className="mt-2 text-sm text-muted">
                  Real, sourced lines taken straight from the pack. This is the level of grounding behind
                  every claim you are buying.
                </p>
                {/* Peek inside: a page you are looking at the top of. The fade is over the page
                    itself, never over invented text — every line below is really in the pack, and
                    nothing is blurred to imply content that does not exist. */}
                <div className="relative mt-6 overflow-hidden rounded-2xl border border-border bg-white shadow-[0_18px_40px_rgba(0,0,0,0.07)]">
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
            <div className="mt-12 rounded-xl border border-border bg-white p-6">
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
            <div className="sticky top-24 rounded-2xl border border-border bg-white p-7 shadow-[0_20px_50px_rgba(0,0,0,0.06)]">
              {checkoutBody}
            </div>
          </div>
        </div>
      </Section>
    </MarketingLayout>
  );
}

/**
 * The blurred look inside the deliverable.
 *
 * Built from the pack's OWN text — `whatYouGet` as the section headings a real build spec
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
    <div className="relative mt-6 overflow-hidden rounded-2xl border border-border bg-white shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
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
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-white px-4 py-2 text-xs font-bold text-text shadow-sm">
          <Icon name="lock" size={14} className="text-muted" />
          Unlocks the moment you buy
        </span>
      </div>
    </div>
  );
}

export const getServerSideProps: GetServerSideProps = async ({ params }) => {
  try {
    const id = params?.id as string;
    // Fetched together, not in series: the "same mechanics" row needs the catalogue, and paying
    // two sequential round trips before first byte would be a real cost for a decorative row.
    // The catalogue is best-effort — a failure there must not 404 a page someone is buying from.
    const [pack, catalog] = await Promise.all([
      fetchPackDetails(id),
      fetchCatalog().catch(() => [] as Pack[]),
    ]);
    return {
      props: { pack, catalog },
    };
  } catch (error) {
    console.error('Error fetching pack details:', error);
    return {
      notFound: true,
    };
  }
};

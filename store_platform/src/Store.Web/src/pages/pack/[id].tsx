import React, { useState } from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon, CoverArt } from '@/components/ui';
import { Section } from '@/components/marketing/blocks';
import { fetchPackDetails, formatPrice, freshnessLabel, PackDetails } from '@/lib/api/client';
import { initPaddle, openPaddleCheckout, paddleConfigured } from '@/lib/paddle';
import { stripeConfigured } from '@/lib/stripe';
import { API_BASE_URL, LEGAL } from '@/lib/config';
import { coverFor } from '@/lib/cover';

interface PackPageProps {
  pack: PackDetails;
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

const INSIDE = [
  { label: 'Blueprint', desc: 'The opportunity, the evidence, and why it is worth building.' },
  { label: 'GTM plan', desc: 'Who pays, where to find them, and how to reach them.' },
  { label: 'Build Kit', desc: 'The stack, the sequence, and the first moves to revenue.' },
  { label: 'The receipts', desc: 'Every claim traced to a source you can open.' },
];

export default function PackPage({ pack }: PackPageProps) {
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const provider = pack.paymentProvider || 'paddle';
  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';
  const priceLabel = formatPrice(pack.price);

  const handleBuy = async () => {
    setCheckingOut(true);
    setCheckoutError(null);

    try {
      if (provider === 'stripe') {
        await handleStripeCheckout(pack);
      } else {
        await handlePaddleCheckout(pack);
      }
    } catch (err: any) {
      setCheckoutError(err.message || 'Checkout failed. Please try again.');
    } finally {
      setCheckingOut(false);
    }
  };

  const handleStripeCheckout = async (pack: PackDetails) => {
    const res = await fetch(`${API_BASE_URL}/packs/${pack.id}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Failed to start checkout: ${text}`);
    }
    const { url } = await res.json();
    // Defence in depth: only ever redirect to Stripe's hosted checkout. Refuse any other
    // value so a compromised/buggy API response can't turn this into an open redirect.
    if (typeof url !== 'string' || !url.startsWith('https://checkout.stripe.com/')) {
      throw new Error('Unexpected checkout URL');
    }
    window.location.href = url;
  };

  const handlePaddleCheckout = async (pack: PackDetails) => {
    await initPaddle();
    openPaddleCheckout(pack.providerPriceId);
  };

  const canCheckout =
    (provider === 'stripe' && stripeConfigured) ||
    (provider !== 'stripe' && paddleConfigured);

  const notifyHref =
    `mailto:${LEGAL.supportEmail}` +
    `?subject=${encodeURIComponent(`Notify me when "${pack.title}" opens`)}` +
    `&body=${encodeURIComponent(`Please email me the moment this pack is available to buy: ${pack.title} (${pack.id}).`)}`;

  // Shared checkout body — rendered in the desktop sticky card and the mobile purchase bar.
  const CheckoutBody = () => (
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

      {checkoutError && (
        <div className="mt-4 rounded-lg border border-danger/20 bg-danger/5 p-3 text-xs text-danger">
          {checkoutError}
        </div>
      )}

      {canCheckout ? (
        <button
          onClick={handleBuy}
          disabled={checkingOut}
          className="mt-4 w-full rounded-xl bg-text py-4 text-sm font-bold uppercase tracking-wide text-white shadow-[0_4px_16px_rgba(15,23,42,0.18)] transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.24)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
        >
          {checkingOut ? 'Redirecting…' : `Get this pack for ${priceLabel}`}
        </button>
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
        {[
          { icon: 'download', text: 'Instant download the moment you pay' },
          { icon: 'lock', text: `Secure checkout via ${providerLabel}` },
          { icon: 'mail', text: 'A private link sent straight to you' },
        ].map((feat, i) => (
          <div key={i} className="flex items-center gap-3 text-xs font-medium text-muted">
            <Icon name={feat.icon as any} size={14} className="text-text/60" />
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
      <Seo title={`${pack.title} · A business idea that survived our filter`} />

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
            <p className="mt-5 text-lg leading-relaxed text-text/80">{pack.oneLine}</p>
            {pack.subhead && (
              <p className="mt-3 text-base leading-relaxed text-text/60">{pack.subhead}</p>
            )}

            {(freshnessLabel(pack.verifiedAt) ||
              (typeof pack.sourceCount === 'number' && pack.sourceCount > 0) ||
              pack.qaVerdictSummary) && (
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
                {pack.qaVerdictSummary && <span>{pack.qaVerdictSummary}</span>}
              </div>
            )}

            {/* Mobile purchase bar — keeps price + CTA above the fold on small screens */}
            <div className="mt-8 rounded-2xl border border-border bg-white p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] lg:hidden">
              <CheckoutBody />
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

            {/* Is this for you? — the concrete fit signals, when the pack carries them */}
            {(pack.whoPays || pack.effortTag || pack.timeToFirstRevenue) && (
              <div className="mt-12">
                <h2 className="text-xl font-bold tracking-tight text-text">Is this for you?</h2>
                <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {pack.whoPays && (
                    <div className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] sm:col-span-3">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Who pays
                      </span>
                      <span className="mt-1.5 text-sm leading-relaxed text-text/80">{pack.whoPays}</span>
                    </div>
                  )}
                  {pack.effortTag && (
                    <div className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        Effort to build
                      </span>
                      <span className="mt-1.5 text-sm font-semibold capitalize text-text">{pack.effortTag}</span>
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

            {/* What's inside — per-pack specifics when present, generic cards otherwise */}
            <div className="mt-12">
              <h2 className="text-xl font-bold tracking-tight text-text">What&apos;s inside</h2>
              {pack.whatYouGet && pack.whatYouGet.length > 0 ? (
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
              ) : (
                <ul className="mt-6 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2">
                  {INSIDE.map((item, i) => (
                    <li key={i} className="flex flex-col rounded-xl border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span className="mt-1 text-base font-bold text-text">{item.label}</span>
                      <span className="mt-1.5 text-sm leading-relaxed text-text/70">{item.desc}</span>
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
                <ul className="mt-6 list-none space-y-3 p-0">
                  {pack.sampleExtract.map((line, i) => (
                    <li
                      key={i}
                      className="rounded-xl border border-border border-l-2 border-l-success bg-white px-5 py-4 text-sm leading-relaxed text-text/80 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
                    >
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* The receipts */}
            <div className="mt-12 rounded-xl border border-border bg-white p-6">
              <div className="mb-3 flex items-center gap-2.5">
                <Icon name="verified" className="text-success" size={18} />
                <span className="font-mono text-xs font-bold uppercase tracking-widest text-text">The receipts</span>
              </div>
              <p className="text-sm leading-relaxed text-text/70">
                Every figure and claim in this pack is traced to external evidence you can open and check.
                No hand waving, no vibes. Audit reference{' '}
                <span className="font-mono text-xs text-muted">{pack.dossierRef}</span>.
              </p>
            </div>
          </div>

          {/* Right: Checkout (desktop sticky) */}
          <div className="hidden w-full shrink-0 lg:block lg:w-80">
            <div className="sticky top-24 rounded-2xl border border-border bg-white p-7 shadow-[0_20px_50px_rgba(0,0,0,0.06)]">
              <CheckoutBody />
            </div>
          </div>
        </div>
      </Section>
    </MarketingLayout>
  );
}

export const getServerSideProps: GetServerSideProps = async ({ params }) => {
  try {
    const id = params?.id as string;
    const pack = await fetchPackDetails(id);
    return {
      props: { pack },
    };
  } catch (error) {
    console.error('Error fetching pack details:', error);
    return {
      notFound: true,
    };
  }
};

import React, { useState } from 'react';
import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { Section } from '@/components/marketing/blocks';
import { fetchPackDetails, PackDetails } from '@/lib/api/client';
import { initPaddle, openPaddleCheckout, paddleConfigured } from '@/lib/paddle';
import { getStripe, stripeConfigured } from '@/lib/stripe';
import { API_BASE_URL } from '@/lib/config';

interface PackPageProps {
  pack: PackDetails;
}

export default function PackPage({ pack }: PackPageProps) {
  const [checkingOut, setCheckingOut] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const provider = pack.paymentProvider || 'paddle';
  const providerLabel = provider === 'stripe' ? 'Stripe' : 'Paddle';

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
    // Call the backend to create a Stripe Checkout Session, then redirect.
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
    window.location.href = url;
  };

  const handlePaddleCheckout = async (pack: PackDetails) => {
    await initPaddle();
    openPaddleCheckout(pack.providerPriceId);
  };

  const canCheckout =
    (provider === 'stripe' && stripeConfigured) ||
    (provider !== 'stripe' && paddleConfigured);

  return (
    <MarketingLayout>
      <Seo title={`${pack.title} - Prospector Store`} />

      <Section bg="bg" width="6xl" className="!pt-12 !pb-24">
        <div className="flex flex-col md:flex-row gap-12">
          {/* Left: Content */}
          <div className="flex-1">
            <div className="mb-8">
              <span className="font-mono text-xs font-bold text-primary uppercase tracking-widest bg-primary/5 px-3 py-1.5 rounded-full border border-primary/20">
                Small Business Pack
              </span>
              <h1 className="text-4xl md:text-5xl font-black text-text tracking-tighter mt-6 leading-tight">
                {pack.title}
              </h1>
            </div>

            <div className="prose prose-slate max-w-none">
              <p className="text-lg text-text/80 leading-relaxed mb-8">
                {pack.oneLine}
              </p>
              
              <h3 className="text-xl font-bold text-text mb-4 mt-12">What's inside:</h3>
              <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4 list-none p-0">
                {[
                  { label: '01. Blueprint', desc: 'Detailed build specification' },
                  { label: '02. GTM Plan', desc: 'Marketing and launch strategy' },
                  { label: '03. Build Kit', desc: 'Financials and ops plan' },
                  { label: '04. QA Report', desc: 'Grounded verification audit' }
                ].map((item, i) => (
                  <li key={i} className="bg-white border border-border rounded-lg p-4 flex flex-col shadow-sm">
                    <span className="font-mono text-[10px] font-bold text-primary uppercase mb-1">{item.label}</span>
                    <span className="text-sm font-medium text-text">{item.desc}</span>
                  </li>
                ))}
              </ul>

              <div className="mt-12 p-6 bg-surface2 border border-border rounded-xl">
                <div className="flex items-center gap-3 mb-4">
                  <Icon name="vouched" className="text-success" size={20} />
                  <span className="font-bold text-sm uppercase tracking-widest font-mono">Verified Grounding</span>
                </div>
                <p className="text-xs text-muted leading-relaxed font-mono">
                  Source: {pack.dossierRef}<br />
                  Every figure and claim in this pack is traced to external evidence passed by the Prospector engine.
                </p>
              </div>
            </div>
          </div>

          {/* Right: Checkout Sidebar */}
          <div className="w-full md:w-80 shrink-0">
            <div className="bg-white border border-border rounded-2xl p-8 shadow-[0_20px_50px_rgba(0,0,0,0.05)] sticky top-24">
              <div className="mb-8">
                <span className="text-xs font-bold text-muted uppercase tracking-widest font-mono">Price</span>
                <div className="text-4xl font-black text-text mt-1">{pack.price}</div>
              </div>

              {checkoutError && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                  {checkoutError}
                </div>
              )}

              <button
                onClick={handleBuy}
                disabled={!canCheckout || checkingOut}
                className="w-full bg-primary text-white font-bold py-4 rounded-xl hover:bg-primary/90 transition-all shadow-lg shadow-primary/20 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {checkingOut ? 'Redirecting…' : 'Buy Now'}
              </button>

              {!canCheckout && (
                <p className="mt-2 text-xs text-amber-600 font-medium">
                  {providerLabel} is not configured. Set API keys in environment.
                </p>
              )}

              <div className="mt-8 space-y-4">
                {[
                  { icon: 'shield', text: `Secure delivery via ${providerLabel}` },
                  { icon: 'mail', text: 'Instant download link' },
                  { icon: 'lock', text: provider === 'stripe' ? 'VAT calculated at checkout' : 'VAT & receipts handled' }
                ].map((feat, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs text-muted font-medium">
                    <Icon name={feat.icon as any} size={14} />
                    {feat.text}
                  </div>
                ))}
              </div>
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
      props: { pack }
    };
  } catch (error) {
    console.error('Error fetching pack details:', error);
    return {
      notFound: true
    };
  }
};

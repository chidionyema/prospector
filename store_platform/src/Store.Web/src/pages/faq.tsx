import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { PageHero, Section, CtaBand } from '@/components/marketing/blocks';
import { Seo } from '@/components/Seo';
import { LEGAL } from '@/lib/config';

const FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: 'What am I actually buying?',
    a: (
      <>
        A £49 pack: a grounded business opportunity dossier with a Blueprint, a go to market plan, and a Build Kit. It&apos;s a digital download, yours to read and build from as soon as payment clears.
      </>
    ),
  },
  {
    q: 'What makes a pack "grounded"?',
    a: (
      <>
        Every pack passed the Prospector engine&apos;s six checks (real pain, durable value, room past incumbents, a solvent payer, a distribution route, and legality) and survived an adversarial review. Every claim and number cites a retrievable source, or it isn&apos;t in the pack.
      </>
    ),
  },
  {
    q: 'How do I get the pack after I pay?',
    a: (
      <>
        Checkout runs through Stripe. As soon as payment succeeds you get a time-limited download link, so the pack is in your hands within seconds.
      </>
    ),
  },
  {
    q: 'Can I get a refund?',
    a: (
      <>
        Yes. Every pack comes with a 14 day money back guarantee, no questions asked. If it is not what you expected, email us within 14 days of purchase and we refund you. The full terms are on the{' '}
        <Link href="/refund" className="text-primary font-bold hover:underline">refund policy</Link>{' '}page.
      </>
    ),
  },
  {
    q: 'Is a pack financial or investment advice?',
    a: (
      <>
        No. A pack is research and information only, not financial, legal, or investment advice. It&apos;s an evidence backed starting point, and what you do with it is your decision.
      </>
    ),
  },
  {
    q: 'Are the opportunities guaranteed to work?',
    a: (
      <>
        No, and we won&apos;t pretend otherwise. We guarantee the analysis is grounded and sourced, not that the business will succeed. Execution is yours.
      </>
    ),
  },
  {
    q: 'Can I share or resell a pack?',
    a: (
      <>
        No. A pack is licensed for your own personal use, with no redistribution, resale, or use as training data. The details are in the{' '}
        <Link href="/terms" className="font-semibold text-text underline underline-offset-2">Terms of Service</Link>.
      </>
    ),
  },
  {
    q: 'Is the store live right now?',
    a: (
      <>
        Yes. Everything on this site works today, and new packs are published as they clear the filter.
      </>
    ),
  },
  {
    q: 'Can I have my data removed?',
    a: (
      <>
        Of course. Email us at{' '}
        <a href={`mailto:${LEGAL.supportEmail}`} className="text-primary font-bold hover:underline">{LEGAL.supportEmail}</a>{' '}
        or read how we handle data in the{' '}
        <Link href="/privacy" className="font-semibold text-text underline underline-offset-2">Privacy Policy</Link>.
      </>
    ),
  },
];

export default function Faq() {
  return (
    <MarketingLayout>
      <Seo
        title="FAQ"
        description="The packs, the payment, and the guarantees. Common questions about the Prospector Store."
      />

      <PageHero
        eyebrow="FAQ"
        title={<span className="leading-tight tracking-tighter">Common questions.</span>}
        lead="What you're buying, how it's delivered, and what we do and don't promise."
      />

      <Section
        bg="white"
        width="7xl"
        title={<span className="font-black">Buying a pack</span>}
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-12 mt-12 md:mt-16 items-start">

          <div className="space-y-6">
            {FAQS.map((item, i) => (
              <div key={i} className="bg-white border border-border p-8 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
                <h2 className="text-lg font-black text-text mb-4 leading-tight group-hover:text-primary transition-standard">{item.q}</h2>
                <div className="text-base text-text/80 leading-relaxed">{item.a}</div>
              </div>
            ))}
          </div>

          <aside className="space-y-6 lg:sticky lg:top-24">
            <div className="bg-white border border-border p-6 rounded-lg shadow-[0_8px_30px_rgba(0,0,0,0.04)] transition-standard hover:shadow-[0_12px_40px_rgba(0,0,0,0.06)] group">
              <h4 className="font-bold text-[10px] uppercase tracking-widest text-text mb-4">Contact Support</h4>
              <div className="space-y-4 font-mono text-[11px]">
                <div className="flex flex-col border-b border-border/60 pb-4">
                  <span className="text-muted uppercase font-bold tracking-tight mb-1">Email</span>
                  <a href={`mailto:${LEGAL.supportEmail}`} className="font-bold text-primary break-all hover:underline">{LEGAL.supportEmail}</a>
                </div>
                <div className="flex flex-col">
                  <span className="text-muted uppercase font-bold tracking-tight mb-1">Response Time</span>
                  <span className="font-bold text-text">&lt; 1 business day</span>
                </div>
              </div>
            </div>
          </aside>

        </div>
      </Section>

      <CtaBand
        title="Browse the catalogue."
        lead=""
        primary={{ href: '/', label: 'Browse the packs' }}
      />
    </MarketingLayout>
  );
}

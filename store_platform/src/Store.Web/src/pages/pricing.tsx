import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { PACK_CONTENTS } from '@/components/marketing/PackContents';
import { BRAND, LEGAL } from '@/lib/config';

/**
 * L4 - The pricing page.
 *
 * One product, one price. The audit (§6) said the buyer who searches for
 * "mumchimp pricing" finds nothing. The fix is a single page that answers
 * every pricing question in one place: the price, what's included, what's
 * not, the refund policy, the trust surface. The page links to the catalogue
 * (the buy action) and to /refund (the legal/policy detail).
 *
 * Out of scope: a pricing-tier matrix (we sell one product, tiers would
 * be theatre). The page is intentionally flat: the same content a buyer
 * would ask a salesperson, in writing.
 */
export default function PricingPage() {
  return (
    <MarketingLayout>
      <Seo
        title="Pricing - £49 per pack, every pack"
        description="One price, every pack. £49 one-time, no subscription, no upsell, 14 day money back. Every claim cited."
      />

      <section className="mx-auto max-w-3xl px-6 py-16 md:py-24">
        <p className="mb-3 font-mono text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Pricing
        </p>
        <h1 className="text-4xl font-black leading-[1.05] tracking-tight text-text md:text-6xl">
          £49 a pack.
        </h1>
        <p className="mt-4 max-w-[60ch] text-lg leading-relaxed text-text/75 md:text-xl">
          One price, every pack. One payment, yours forever. No subscription,
          no seat fees, no upsell, no drip-feed. If a pack survives six checks
          it is listed. If it does not, it is in the{' '}
          <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">
            kill log
          </Link>
          .
        </p>

        {/* What's included */}
        <div className="mt-12">
          <h2 className="text-2xl font-bold tracking-tight text-text md:text-3xl">
            What you get for £49
          </h2>
          <p className="mt-2 max-w-[60ch] text-base text-muted">
            Every pack is the same shape: {PACK_CONTENTS.length} documents, sourced
            and cited. No tier, no upsell, no add-on. The list below is
            identical for every pack on the shelf.
          </p>
          <ul className="mt-6 space-y-3">
            {PACK_CONTENTS.map((item) => (
              <li
                key={item.filename}
                className="flex items-start gap-3 border border-border bg-surface p-4"
              >
                <span aria-hidden className="mt-0.5 text-xl">
                  {item.emoji}
                </span>
                <div>
                  <p className="text-sm font-bold text-text">{item.title}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-muted">
                    {item.filename}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* What's not included */}
        <div className="mt-12">
          <h2 className="text-2xl font-bold tracking-tight text-text md:text-3xl">
            What you do not get
          </h2>
          <p className="mt-2 max-w-[60ch] text-base text-muted">
            Honesty about the limits is part of the brand.
          </p>
          <ul className="mt-6 space-y-3">
            {[
              'A guarantee that the business will succeed. A pack is grounded research, not a promise of outcome.',
              'Live updates. Packs are a one-time artefact, dated at publish. The kill log is the live surface.',
              'Personal coaching. The pack is the deliverable. If you want a person, that is a different product, sold elsewhere.',
              'A subscription, dashboard, or seat. The pack is a file you own.',
            ].map((line) => (
              <li key={line} className="flex items-start gap-3 border border-border bg-surface p-4">
                <span aria-hidden className="mt-0.5 text-base font-bold text-muted">×</span>
                <span className="text-sm leading-relaxed text-text/80">{line}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Trust + refund */}
        <div className="mt-12 grid gap-4 sm:grid-cols-2">
          <div className="border border-border bg-surface p-5">
            <div className="flex items-center gap-2">
              <Icon name="shield" size={16} className="text-success" />
              <h3 className="text-sm font-bold text-text">14 day money back</h3>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-text/75">
              If the pack is not what the description said, email{' '}
              <a href={`mailto:${LEGAL.supportEmail}`} className="font-semibold text-text underline underline-offset-2">
                {LEGAL.supportEmail}
              </a>
              {' '}within 14 days and we refund in full. No forms, no friction.
              The full policy is on the{' '}
              <Link href="/refund" className="font-semibold text-text underline underline-offset-2">
                refund page
              </Link>
              .
            </p>
          </div>
          <div className="border border-border bg-surface p-5">
            <div className="flex items-center gap-2">
              <Icon name="verified" size={16} className="text-success" />
              <h3 className="text-sm font-bold text-text">Every claim cited</h3>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-text/75">
              Every figure in every pack links to a retrievable source. Open
              the QA report inside the pack and trace any claim to its
              origin. The 1,080 ideas we killed are in the{' '}
              <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">
                kill log
              </Link>
              .
            </p>
          </div>
        </div>

        {/* Buy CTA */}
        <div className="mt-14 border border-text bg-surface p-8 text-center">
          <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
            {BRAND.name}
          </p>
          <h2 className="mt-2 text-3xl font-black tracking-tight text-text md:text-4xl">
            £49. Yours forever.
          </h2>
          <p className="mt-2 text-sm text-muted">
            {`Pick one pack. The same price for every pack on the shelf.`}
          </p>
          <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/#catalog"
              className="inline-flex items-center justify-center gap-2 bg-text px-8 py-4 text-sm font-bold uppercase tracking-wide text-bg transition-all hover:bg-text/90"
            >
              Browse the packs
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link
              href="/sample"
              className="inline-flex items-center justify-center gap-2 border border-text/20 px-8 py-4 text-sm font-bold uppercase tracking-wide text-text transition-colors hover:bg-bg"
            >
              Read a free sample first
            </Link>
          </div>
        </div>
      </section>
    </MarketingLayout>
  );
}

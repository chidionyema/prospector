import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Icon } from '@/components/ui';
import { PACK_CONTENTS } from '@/components/marketing/PackContents';
import { BRAND, LEGAL } from '@/lib/config';
import { GetServerSideProps } from 'next';
import { fetchCatalog } from '@/lib/api/client';
import { priceRange, priceSentence, formatGbp, type PriceRange } from '@/lib/priceRange';

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
 *
 * SERVER-RENDERED SINCE 2026-08-05. It was static, with "£49" written into the title, the meta
 * description, the h1, a section heading and the closing CTA. The segment price ladder
 * (`feat(pricing)` #105/#107) ended one-price, and the live shelf now runs £29 to £199 -- so the
 * one page on the site whose entire job is to answer "what does it cost" was the page most
 * confidently wrong. Every figure below is now computed from the catalogue this request fetched.
 *
 * The degradation is deliberate: when the catalogue cannot be read, `range` is null and the page
 * renders its structure with NO price claim rather than a remembered one. A pricing page that
 * quotes a number it could not verify is worse than a pricing page that says "see the pack".
 */
export default function PricingPage({ range }: { range: PriceRange | null }) {
  return (
    <MarketingLayout>
      <Seo
        title={range ? `Pricing - ${range.label} per pack` : 'Pricing'}
        description={
          range
            ? `${priceSentence(range)} 14 day money back. Every claim cited.`
            : 'One payment per pack, no subscription, no upsell, 14 day money back. Every claim cited.'
        }
      />

      <section className="mx-auto max-w-3xl px-6 py-16 md:py-24">
    <p className="mb-3 text-caption font-bold uppercase tracking-[0.2em] text-muted">
          Pricing
        </p>
        <h1 className="text-h1 font-black leading-[1.05] tracking-tight text-text md:text-display">
          {range ? range.headline : 'One payment per pack.'}
        </h1>
        <p className="mt-4 max-w-[60ch] text-body leading-relaxed text-text/75 md:text-h2">
          {/* Was "One price, every pack." The mode is stated alongside the spread on purpose:
              quoting only "from £29" when most packs are dearer is the airline-fare move. */}
          {range ? priceSentence(range) : 'One payment, yours forever. The price is on each pack\'s own page.'}{' '}
          No seat fees, no drip-feed. If a pack survives six checks
          it is listed. If it does not, it is in the{' '}
          <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">
            kill log
          </Link>
          .
        </p>

        {/* What's included */}
        <div className="mt-12">
          <h2 className="text-h2 font-bold tracking-tight text-text md:text-h1">
            What you get, at every price
          </h2>
          <p className="mt-2 max-w-[60ch] text-body text-muted">
            Every pack is the same shape: {PACK_CONTENTS.length} documents, sourced
            and cited. No tier, no upsell, no add-on. The list below is
            identical for every pack on the shelf
            {range && !range.uniform
              ? `, whether it is ${formatGbp(range.min)} or ${formatGbp(range.max)}. The price reflects the size of the opportunity, never the size of the download`
              : ''}
            .
          </p>
          <ul className="mt-6 space-y-3">
            {PACK_CONTENTS.map((item) => (
              <li
                key={item.filename}
                className="flex items-start gap-3 border border-border bg-surface p-4"
              >
                <span aria-hidden className="mt-0.5 text-h2">
                  {item.emoji}
                </span>
                <div>
                  <p className="text-meta font-bold text-text">{item.title}</p>
                  <p className="mt-0.5 font-mono text-caption text-muted">
                    {item.filename}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* What's not included */}
        <div className="mt-12">
          <h2 className="text-h2 font-bold tracking-tight text-text md:text-h1">
            What you do not get
          </h2>
          <p className="mt-2 max-w-[60ch] text-body text-muted">
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
                <span aria-hidden className="mt-0.5 text-body font-bold text-muted">×</span>
                <span className="text-meta leading-relaxed text-text/80">{line}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Trust + refund */}
        <div className="mt-12 grid gap-4 sm:grid-cols-2">
          <div className="border border-border bg-surface p-5">
            <div className="flex items-center gap-2">
              <Icon name="shield" size={16} className="text-success" />
              <h3 className="text-meta font-bold text-text">14 day money back</h3>
            </div>
            <p className="mt-2 text-meta leading-relaxed text-text/75">
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
              <h3 className="text-meta font-bold text-text">Every claim cited</h3>
            </div>
            <p className="mt-2 text-meta leading-relaxed text-text/75">
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
     <p className="text-caption font-bold uppercase tracking-widest text-muted">
            {BRAND.name}
          </p>
          <h2 className="mt-2 text-h1 font-black tracking-tight text-text md:text-h1">
            {range ? `${range.label}. Yours forever.` : 'Yours forever.'}
          </h2>
          <p className="mt-2 text-meta text-muted">
            Pick one pack. One payment, and the price is on the pack&apos;s own page.
          </p>
          <div className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/#catalog"
              className="inline-flex items-center justify-center gap-2 bg-text px-8 py-4 text-meta font-bold uppercase tracking-wide text-bg transition-all hover:bg-text/90"
            >
              Browse the packs
              <Icon name="arrowRight" size={14} />
            </Link>
            <Link
              href="/sample"
              className="inline-flex items-center justify-center gap-2 border border-text/20 px-8 py-4 text-meta font-bold uppercase tracking-wide text-text transition-colors hover:bg-bg"
            >
              Read a free sample first
            </Link>
          </div>
        </div>
      </section>
    </MarketingLayout>
  );
}

/*
 * The catalogue is fetched for its prices only. `fetchCatalog` already returns the full listing
 * the home page renders, so this costs the same call the shelf makes and no new endpoint.
 *
 * A failed fetch is not an error page: `range` is null, and every price claim above simply does
 * not render. The page still answers what is in a pack, what is not, and the refund terms.
 */
export const getServerSideProps: GetServerSideProps<{ range: PriceRange | null }> = async () => {
  const packs = await fetchCatalog().catch(() => []);
  return { props: { range: priceRange(packs ?? []) } };
};

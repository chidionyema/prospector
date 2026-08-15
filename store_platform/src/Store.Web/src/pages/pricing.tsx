import React from 'react';
import Link from 'next/link';
import MarketingLayout from '@/components/marketing/MarketingLayout';
import { Seo } from '@/components/Seo';
import { Button, Icon, textLinkClass } from '@/components/ui';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { BRAND, LEGAL } from '@/lib/config';
import { GetStaticProps } from 'next';
import { fetchCatalog } from '@/lib/api/client';
import { priceRange, priceLadder, priceSentence, formatGbp, type PriceRange, type LadderRung } from '@/lib/priceRange';
import PriceLadder from '@/components/marketing/PriceLadder';
import { ComparisonBlock, MethodCostAnchor } from '@/components/marketing/PriceArgument';
import killTotals from '@/data/kill-log-totals.json';

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
export default function PricingPage({ range, ladder }: { range: PriceRange | null; ladder: LadderRung[] }) {
  return (
    <MarketingLayout>
      <Seo
        title={range ? `Pricing - ${range.label} per pack` : 'Pricing'}
        description={
          range
            ? `${priceSentence(range)} 14 day money back. Every claim cited.`
            : 'One payment per pack, no subscription, 14 day money back. Every claim cited.'
        }
      />

      <section className="mx-auto max-w-3xl px-6 pt-10 pb-16 md:pt-14 md:py-24">
        <p className="mb-3 text-caption font-medium text-subtle">Pricing</p>
        <h1 className="text-h1 font-semibold text-text">
          {range ? range.headline : 'One payment per pack.'}
        </h1>
        <p className="mt-4 max-w-[60ch] text-body text-muted">
          {/* Was "One price, every pack." The mode is stated alongside the spread on purpose:
              quoting only "from £29" when most packs are dearer is the airline-fare move. */}
          {/* "No seat fees, no drip-feed" is cut, along with "no upsell" in the fallback meta
              description above. All three are the same promise as "One payment. No subscription."
              directly beside them, and the section below states each one as a thing you do not get,
              which is the honest place for it: a denial in a headline block reads as a boast, and
              the same denial in "What you do not get" reads as a limit. */}
          {range ? priceSentence(range) : 'One payment, yours forever. The price is on each pack\'s own page.'}{' '}
          If a pack survives the checks
          it is listed. If it does not, it is in the{' '}
          <Link href="/kill-log" className={textLinkClass()}>
            kill log
          </Link>
          .
        </p>

        {/*
          COST ANCHOR, PROMOTED TO POSITION 2 (email §5).
          It used to render at the bottom of the page, far below the ladder. The page a buyer
          opens to answer "what does it cost" was the one page that did not say so until the
          reader had scrolled past the contents list and the limits list. The anchor is the only
          argument here that does not move with the catalogue: a research firm publishes a price
          and the price is the price.
        */}
        <div className="mt-12">
          <MethodCostAnchor range={range} />
        </div>

        {/* WHY ONE PACK COSTS MORE THAN ANOTHER, stated as its own block. */}
        {range && !range.uniform && (
          <div className="mt-12">
            <h2 className="text-h2 font-semibold text-text md:text-h1">
              What changes is the size of the opportunity. The pack doesn’t.
            </h2>
            <PriceLadder rungs={ladder} className="mt-6" />
            <p className="mt-8 max-w-[60ch] text-body text-muted">
              Two things set the rung, not a guess: how big the idea could realistically become,
              and which market it targets. US-market packs sit one price step higher, because the
              market they address is bigger. A weekend side business and a
              venture-scale one get the same{' '}
              {PACK_DOCUMENTS.length} documents, researched to the same standard and held to the same
              bar. What differs is how much is on the table if it works, so a cheaper pack is not a
              thinner one.
            </p>
          </div>
        )}

        {/* What's included */}
        <div className="mt-12">
          <h2 className="text-h2 font-semibold text-text">What you get, at every price</h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            Every pack is the same shape: {PACK_DOCUMENTS.length} documents, sourced
            and cited. No tier, no add-on. The list below is
            identical for every pack on the shelf
            {range && !range.uniform ? `, whether it is ${formatGbp(range.min)} or ${formatGbp(range.max)}` : ''}
            .
          </p>
          {/* Two columns from `sm` up, matching `PackContents` (the same items, rendered on the
              pack page). Stacked full-width, nine rows ran the length of a 1440px viewport with
              ~900px of empty card to the right of every line (desktop-pricing-fold.png,
              2026-08-06), and pushed the price argument below them a full screen further down.

              2026-08-15: the filename line under each title is GONE, and this page stops being
              "the bare-filenames half" of the §5.3 ownership split. The split survives -- the
              enumerated manifest with real archive entries is still index.tsx's, via
              `PackContentsSection` -- but these nine are sections of the reader now, so their
              `.md` names are true of our source tree and false of the buyer's download folder.
              A filename that does not appear in the zip is worse than no filename: this page's
              argument is "every pack is the same shape whatever it costs", and the shape is the
              documents. */}
          <ul className="mt-6 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
            {PACK_DOCUMENTS.map((item) => (
              <li
                key={item.section}
                className="flex items-start gap-3 rounded-md border border-border bg-surface p-4"
              >
                {/* The emoji is not rendered (brand v3): nine emoji stacked down a list is the
                    single loudest thing on a page about a professional research product, and each
                    one renders as a different vendor's artwork per OS. */}
                <Icon name="check" size={16} className="mt-0.5 flex-none text-success" />
                <div className="min-w-0">
                  <p className="text-meta font-medium text-text">{item.title}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* What's not included. THIS is the sitewide owner of the honest limits: /how-it-works
            states the one-line version and links to `#what-you-do-not-get` here, so the anchor is
            part of the contract, not decoration. Renaming it breaks that link silently. */}
        <div className="mt-12">
          <h2 id="what-you-do-not-get" className="scroll-mt-24 text-h2 font-semibold text-text">
            What you do not get
          </h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            Honesty about the limits is part of the brand.
          </p>
          <ul className="mt-6 space-y-3">
            {[
              'A guarantee that the business will succeed. A pack is evidence-backed research, not a promise of outcome.',
              'Live updates. Packs are a one-time artefact, dated at publish. The kill log is the live surface.',
              'Personal coaching. The pack is the deliverable. If you want a person, that is a different product, sold elsewhere.',
              'A subscription, dashboard, or seat. The pack is a file you own.',
            ].map((line) => (
              <li key={line} className="flex items-start gap-3 rounded-md border border-border bg-surface p-4">
                <span aria-hidden className="mt-0.5 text-meta text-subtle">×</span>
                <span className="text-meta leading-relaxed text-muted">{line}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Trust + refund */}
        <div className="mt-12 grid gap-4 sm:grid-cols-2">
          <div className="rounded-md border border-border bg-surface p-5">
            <div className="flex items-center gap-2">
              <Icon name="shield" size={16} className="text-success" />
              <h3 className="text-meta font-semibold text-text">14 day money back</h3>
            </div>
            <p className="mt-2 text-meta leading-relaxed text-muted">
              If the pack is not what the description said, email{' '}
              <a href={`mailto:${LEGAL.supportEmail}`} className={textLinkClass()}>
                {LEGAL.supportEmail}
              </a>
              {' '}within 14 days and we refund in full. No forms, no friction.
              The full policy is on the{' '}
              <Link href="/refund" className={textLinkClass()}>
                refund page
              </Link>
              .
            </p>
          </div>
          <div className="rounded-md border border-border bg-surface p-5">
            <div className="flex items-center gap-2">
              <Icon name="verified" size={16} className="text-success" />
              <h3 className="text-meta font-semibold text-text">Every claim cited</h3>
            </div>
            <p className="mt-2 text-meta leading-relaxed text-muted">
              {/* Was "Every figure in every pack links to a retrievable source." Our own zero-LLM
                  probe falsifies that sentence: 15 of the 50 packs then on sale asserted at least
                  one figure that appears in NO passage the run retrieved (programme doc §33). The
                  claim now states what the engine actually enforces -- every verdict ships the
                  passages it was ruled on -- rather than a per-figure guarantee nothing checked.
                  Do not restore an "every figure" promise until 33-A gates the shelf on it. */}
              Every verdict ships with the sources it was ruled on. Open
              the QA report inside the pack and trace any claim to its{' '}
              {/* Was the literal "1,080". Every other kill count on the site reads
                  `kill-log-totals.json`, so this one number drifted the moment the engine ran
                  again -- on the page whose whole subject is what the price buys. */}
              origin. The {killTotals.killed.toLocaleString('en-GB')} ideas we killed are in the{' '}
              <Link href="/kill-log" className={textLinkClass()}>
                kill log
              </Link>
              .
            </p>
          </div>
        </div>

        {/* The subscription comparison, once (email §5).
            The previous two-up grid (feed vs pack) was five rows long. The email cuts it to
            three rows -- the three facts a buyer actually compares on: cost cadence, what
            arrives, and what happens on cancel. The other two are restatements of those three. */}
        <div className="mt-14">
          <ComparisonBlock range={range} />
        </div>

        {/* Buy CTA -- email §5 closing.
            The price spread is COMPUTED from the catalogue this render has, never typed
            (`noHardcodedPrice.test.ts` is the guard: a £29/£149 hardcoded headline drifts the
            moment a rung moves; a `range.min`/`range.max` headline moves with it). On a catalogue
            the page cannot read, the spread is omitted and the line falls back to a single
            statement that is true at any price. */}
        <div className="mt-14 rounded-md border border-border bg-surface2 p-8">
          <p className="text-caption font-medium text-subtle">{BRAND.name}</p>
          <h2 className="mt-2 text-h2 font-semibold text-text">
            {range && !range.uniform
              ? `${formatGbp(range.min)} to ${formatGbp(range.max)}. Yours forever.`
              : 'One payment. Yours forever.'}
          </h2>
          <p className="mt-3 max-w-[60ch] text-body text-muted">
            One payment per pack, no subscription. Read a free sample first if you’d like to see
            the rigour before you buy.
          </p>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Link href="/#catalog">
              <Button size="lg" fullWidth className="sm:w-auto">
                Browse the packs
                <Icon name="arrowRight" size={16} />
              </Button>
            </Link>
            <Link href="/sample">
              <Button variant="secondary" size="lg" fullWidth className="sm:w-auto">
                Read a free sample first
              </Button>
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
 *
 * ISR, not `getServerSideProps` (measured 2026-08-14): this function reads no `context` at all --
 * no visitor-specific input exists on a pricing page whose numbers are the same for everyone --
 * so every hit was paying a live `/catalog` round trip for two figures that only change when the
 * engine publishes. 300s revalidate matches `kill-log.tsx`'s ISR window for the same reason.
 */
export const getStaticProps: GetStaticProps<{
  range: PriceRange | null;
  ladder: LadderRung[];
}> = async () => {
  const packs = (await fetchCatalog().catch(() => [])) ?? [];
  // Same fetch, two derivations. `ladder` is `[]` on a failed fetch, and `PriceLadder` renders
  // nothing below two rungs, so the drawing disappears with the rest of the price claims rather
  // than drawing a shelf nobody could read.
  return { props: { range: priceRange(packs), ladder: priceLadder(packs) }, revalidate: 300 };
};

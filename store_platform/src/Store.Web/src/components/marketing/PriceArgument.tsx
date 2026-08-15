import React from 'react';
import Link from 'next/link';
import { buttonClasses, Icon } from '@/components/ui';
import { PACK_DOCUMENTS } from '@/components/marketing/PackContents';
import { SourcedCaveat, SourcedFigure } from '@/components/marketing/SourcedFigure';
import { citedFigure } from '@/lib/sources';
import { formatGbp, type PriceRange } from '@/lib/priceRange';

/**
 * The two price arguments, moved out of `pages/index.tsx` on 2026-08-06 (brand v3).
 *
 * They were stacked at the bottom of the home page, adding roughly four thousand pixels of
 * argument between the shelf and the footer on a page that already ran sixteen thousand. Neither
 * is deleted: both are carefully sourced, and both belong on /pricing, which is the page a buyer
 * opens when the question is "why does this cost what it costs". The home page's job is to show
 * the product.
 *
 * ---
 *
 * `MethodCostAnchor` prices the WORK, not the outcome.
 *
 * Two temptations were declined, and both would have produced a bigger number:
 *
 * A UK agency guide priced B2B market research at £15k to £80k, which is the figure a marketer
 * would pick. It is not comparable: that range buys depth interviews and commissioned surveys,
 * primary research a pack does not contain and does not claim to. Anchoring against it would
 * inflate the gap by pricing work we do not do.
 *
 * The second was to convert euros to pounds so both sides of the comparison shared a unit. That
 * needs an exchange rate the source does not print, which would make the headline number partly
 * ours. The currencies stay as published and the reader does the last step, because a comparison
 * this favourable has to be checkable to be worth making at all.
 *
 * The caveat renders with the figure rather than under an asterisk: their deliverable answers a
 * question a client brings them, and a pack answers one we chose. That difference is the actual
 * reason the price can be what it is, so burying it would be arguing badly as well as dishonestly.
 */
export function MethodCostAnchor({ range }: { range: PriceRange | null }) {
  const documentary = citedFigure('documentary-research');
  return (
    <div className="rounded-md border border-border bg-surface p-6 md:p-8">
      {/* h2, not h3. This is a top-level section of the page and is styled `text-h2` to say so;
          the tag disagreed with the type scale, and on /pricing that disagreement skipped a level
          and tripped axe's `heading-order`. The rule: the tag follows the ROLE, and the type scale
          follows the tag -- never the other way round. */}
      <h2 className="text-h2 font-semibold text-text">What this costs when you commission it</h2>
      <p className="mt-3 max-w-[60ch] text-body text-muted">
        A pack is desk research: published sources, read until a claim either holds or dies. Firms
        sell that by the project, and publish what they charge for it.
      </p>

      {/* Two plates, one border weight. The old pair leaned on a green ring around the right-hand
          cell to signal "this is the good one", which is the shape of a pricing table trying to
          steer rather than a comparison trying to inform. The numbers make the point unaided. */}
      <dl className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-md border border-border bg-surface2 p-5">
          <dt className="text-caption font-medium text-subtle">
            {documentary.publisher},{' '}
            {new Date(documentary.publishedOn ?? documentary.checkedOn).getFullYear()} price list
          </dt>
          <dd className="mt-2 text-meta text-text">
            <SourcedFigure id="documentary-research" />
            <span className="mt-1 block text-caption text-subtle">for {documentary.of}</span>
          </dd>
        </div>
        <div className="rounded-md border border-border bg-surface2 p-5">
          <dt className="text-caption font-medium text-subtle">A pack, already run</dt>
          <dd className="mt-2 text-meta text-text">
            <span className="font-mono font-semibold text-text">{range ? range.label : 'One payment'}</span>
            <span className="mt-1 block text-caption text-subtle">
              one payment, {PACK_DOCUMENTS.length} documents, every claim sourced
            </span>
          </dd>
        </div>
      </dl>

      <p className="mt-5 max-w-[80ch] text-caption leading-relaxed text-subtle">
        <SourcedCaveat id="documentary-research" />
      </p>
    </div>
  );
}

/** Why one payment rather than a subscription, with both sides' prices cited. */
export function ComparisonBlock({ range }: { range: PriceRange | null }) {
  /*
    COMPARISON TABLE, CUT TO THREE ROWS (email §5).
    The table was five rows and every additional row was a restatement of the three facts a
    buyer actually compares on: how often you pay, what arrives, and what happens on cancel.
    Cutting it makes the comparison read in a single glance, which is what the buyer came for
    on a pricing page.
  */
  const rows: { label: string; feed: string; pack: string }[] = [
    { label: 'You pay', feed: 'every year, forever', pack: 'once' },
    { label: 'You get', feed: 'raw leads to vet yourself', pack: `one vetted opportunity, ${PACK_DOCUMENTS.length} documents` },
    { label: 'If you cancel', feed: 'you keep nothing', pack: 'it was never a subscription' },
  ];
  return (
    <div>
      {/* The number is the mode, not the floor: this heading is an argument about paying ONCE,
          and quoting the cheapest pack under it would make the comparison flattering rather than
          representative. */}
      <h2 className="text-h2 font-semibold text-text">
        Why {range ? `${formatGbp(range.mode)} once` : 'one payment'}, not another subscription
      </h2>
      <p className="mt-3 max-w-[60ch] text-body text-muted">
        Idea feeds and trend tools sell you the search. We sell you the answer to one.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Left: the category being compared against */}
        <div className="flex flex-col rounded-md border border-border bg-surface2 p-6">
          <div className="flex items-center gap-2">
            <Icon name="close" size={16} className="text-subtle" />
            <span className="text-body font-semibold text-text">Subscription idea feeds</span>
          </div>
          <p className="mt-2 text-meta text-muted">
            <SourcedFigure id="idea-feed-entry-plan" />
          </p>
          <p className="mt-1 text-caption leading-relaxed text-subtle">
            <SourcedCaveat id="idea-feed-entry-plan" />
          </p>
          <dl className="mt-6 space-y-4">
            {rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-0.5">
                <dt className="text-caption font-medium text-subtle">{r.label}</dt>
                <dd className="text-meta text-muted">{r.feed}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Right: the offer */}
        <div className="flex flex-col rounded-md border border-border-strong bg-surface p-6">
          <div className="flex items-center gap-2">
            <Icon name="check" size={16} className="text-success" />
            <span className="text-body font-semibold text-text">A Mumchimp pack</span>
          </div>
          {/* Mono wraps the amount only. The clause around it is a sentence, and the line above
              (`A pack, already run`) already sets the pattern: figure in the data voice, prose in
              the sans. Setting the whole line in mono put "yours forever" in the evidence voice. */}
          <p className="mt-2 text-meta font-medium text-text">
            {range ? (
              <>
                <span className="font-mono">{formatGbp(range.mode)}</span> one time, yours forever
              </>
            ) : (
              'One payment, yours forever'
            )}
          </p>
          <dl className="mt-6 space-y-4">
            {rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-0.5">
                <dt className="text-caption font-medium text-subtle">{r.label}</dt>
                <dd className="text-meta text-text">{r.pack}</dd>
              </div>
            ))}
          </dl>
          <Link
            href="/#catalog"
            className={buttonClasses({ size: 'lg', className: 'mt-6' })}
          >
            Browse the packs <Icon name="arrowRight" size={16} />
          </Link>
        </div>
      </div>
    </div>
  );
}

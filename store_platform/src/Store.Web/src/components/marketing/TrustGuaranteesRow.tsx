import React from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui';
import { cx } from '@/components/ui/cx';
import killTotals from '@/data/kill-log-totals.json';

/**
 * N1 - The single "Trust & guarantees" row.
 *
 * The audit (§4.13) found the trust facts scattered across the page in five
 * different shapes. The fix is one row, one place. Five facts, sourced from
 * the same kill-log totals the rest of the site uses, so the counts stay
 * in sync with the kill log automatically.
 *
 * The row is the canonical "what am I actually buying?" surface: price, refund,
 * volume of vetting, the kill count, the live count. The buyer who scans the
 * page from top to bottom sees the trust once, definitively, and links to
 * the rest of the trust surface from here.
 */
export default function TrustGuaranteesRow({
  className,
  listed,
  price,
}: {
  className?: string;
  listed?: number;
  /*
   * The price fact, computed by the caller from the packs it already has
   * (`priceRange(packs)`). It was the hardcoded string "£49 once" while 13 of the 61 live packs
   * were not £49 -- and this row is the page's canonical "what am I actually buying?" surface,
   * so it was the most load-bearing wrong number on the site. Omitted (no catalogue to hand)
   * falls back to the claim that is true at any price: one payment.
   */
  price?: { label: string; uniform: boolean };
}) {
  // Source: the canonical kill-log totals. killed + passed is the total
  // "researched" figure. Those two are historical, so a build-time snapshot is
  // the right shape for them.
  //
  // The live count is NOT. `kill-log-totals.json` is frozen at build time, and the
  // home page renders the same claim twice from two different sources: index.tsx
  // reads `stats.listed` off the live `/catalog`, this row read `totals.shown`.
  // On 2026-08-05 the live catalog held 61 packs while the JSON still said
  // `"shown": 60`, so the page shipped "61 live now" and "60 live now" on one
  // scroll. Publishing a pack without a redeploy widens the gap indefinitely.
  //
  // So the live figure is a prop now, passed from whatever already holds the live
  // stats. The snapshot stays only as the fallback for callers with nothing live
  // to hand (the count is then stale but at least not self-contradicting on a page
  // that has the real number elsewhere).
  const totals = killTotals as { killed: number; passed: number; live?: number; shown?: number };
  const killed = totals.killed;
  const live = listed ?? totals.live ?? totals.shown ?? 0;

  /*
   * THREE facts, down from five (brand v3, 2026-08-06).
   *
   * The five-up grid was doing two different jobs at once: three of the cells were guarantees
   * (what you get if you buy) and two were volume statistics (how much was rejected). Mixed into
   * one centred row of icon-in-a-circle pills, neither read as either. The statistics now live
   * where they are evidence rather than reassurance -- the filter-log card above the fold and the
   * method band -- and this row is only the purchase terms.
   *
   * `listed` and `killed` are still read below so the row's kill-log sentence stays true to the
   * same source, and so callers that already pass `listed` do not have to change.
   */
  const facts: { icon: 'money' | 'shield' | 'verified'; label: string }[] = [
    { icon: 'shield', label: '14-day money back' },
    { icon: 'verified', label: 'Every claim sourced' },
    {
      icon: 'money',
      label: price ? (price.uniform ? `One-time payment, ${price.label}` : 'One-time payment') : 'One-time payment',
    },
  ];

  return (
    <section aria-label="Trust and guarantees" className={cx('border-t border-border', className)}>
      <div className="mx-auto max-w-6xl px-6 py-6 md:px-8">
        {/* No pills, no borders, no circles, left-aligned. These are three short factual lines;
            dressing each one in its own container implied three separate offers. */}
        <ul className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:gap-8">
          {facts.map((fact) => (
            <li key={fact.label} className="flex items-center gap-2 text-meta text-muted">
              <Icon name={fact.icon} size={16} />
              {fact.label}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-caption text-subtle">
          {killed.toLocaleString('en-GB')} ideas were killed to list these {live}. The{' '}
          <Link href="/kill-log" className="text-accent underline underline-offset-2 hover:text-accent-hover">kill log</Link>
          {' '}has every one, with the sourced reason why.
        </p>
      </div>
    </section>
  );
}

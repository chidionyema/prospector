import React from 'react';
import Link from 'next/link';
import { textLinkClass } from '@/components/ui';
import { cx } from '@/components/ui/cx';
// No `kill-log-totals.json` import: this row stopped printing counts on 2026-08-14 and the import
// is what would make a future edit reach for one without noticing the page already states them.

/**
 * N1 - The single "Trust & guarantees" row.
 *
 * The audit (§4.13) found the trust facts scattered across the page in five
 * different shapes. The fix is one row, one place. Five facts, sourced from
 * the same kill-log totals the rest of the site uses, so the counts stay
 * in sync with the kill log automatically.
 *
 * The row is the canonical "what am I actually buying?" surface: price, refund, sourcing, and a
 * link to the evidence. It carried the kill count and the live count too until 2026-08-14, which
 * is what made it the fourth telling of the kill statistic on one scroll; it is the purchase
 * terms now, and the counts are stated once, above the shelf, from the live catalogue.
 */
export default function TrustGuaranteesRow({
  className,
  price,
  layout = 'row',
}: {
  className?: string;
  /*
   * `row` is the standalone band this component shipped as: its own centred max-w-6xl container
   * with its own vertical padding, rendered as a sibling between two sections.
   *
   * `stack` is the same three facts as a column, with NO container of its own, for a caller that
   * has already placed it -- on the home page that is the closing band, where the terms sit in the
   * right-hand column beside the closing argument instead of in a band of their own. The band was
   * split out because three consecutive full-width bands (argument / terms / a second CTA) closed
   * the page saying the same thing three times, each with an empty right half; see the note at the
   * merge site in `pages/index.tsx`.
   */
  layout?: 'row' | 'stack';
  /*
   * ACCEPTED AND IGNORED as of 2026-08-14, deliberately not deleted. This row no longer prints a
   * live count (see the kill-sentence note below), but `listed` is passed by callers that hold the
   * live `/catalog` stats, and dropping it from the type would be a compile error at every one of
   * them for a change that is purely about what this row says. It stays in the contract so a
   * caller can keep passing the live figure, and so restoring a count here can never reintroduce
   * the build-time-snapshot bug the comment history below records.
   */
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
  /* THE COUNTS ARE GONE FROM THIS ROW (2026-08-14). Kept as history because the reasoning below
     is still live the moment anyone puts a number back here.

     This row used to read the canonical kill-log totals: `killed + passed` is the "researched"
     figure, and those two are historical, so a build-time snapshot was the right shape for them.
     The LIVE count never was. `kill-log-totals.json` is frozen at build time, and the home page
     rendered the same claim twice from two different sources -- index.tsx read `stats.listed` off
     the live `/catalog`, this row read `totals.shown`. On 2026-08-05 the live catalog held 61
     packs while the JSON still said `"shown": 60`, so the page shipped "61 live now" and "60 live
     now" on one scroll, and publishing a pack without a redeploy widened the gap indefinitely.
     That is why `listed` became a prop, and why it is still accepted above.

     Both counts are now stated once, above the shelf, from the live source. */

  /*
   * THREE facts, down from five (brand v3, 2026-08-06).
   *
   * The five-up grid was doing two different jobs at once: three of the cells were guarantees
   * (what you get if you buy) and two were volume statistics (how much was rejected). Mixed into
   * one centred row of icon-in-a-circle pills, neither read as either. The statistics now live
   * where they are evidence rather than reassurance -- the filter-log card above the fold and the
   * method band -- and this row is only the purchase terms.
   *
   * As of 2026-08-14 neither statistic is read here at all: the volume figures were the last
   * duplicate of a number the page already states above the shelf. `listed` is still accepted so
   * callers do not have to change (see the note on the prop).
   */
  const facts: { label: string }[] = [
    { label: '14-day money back' },
    { label: 'Every claim sourced' },
    {
      label: price ? (price.uniform ? `One-time payment, ${price.label}` : 'One-time payment') : 'One-time payment',
    },
  ];

  // No `border-t` here. This row's only call site (index.tsx) renders it as the literal next
  // sibling after a `</SectionBand>`, and every `SectionBand` already carries its own
  // unconditional `border-b` (blocks.tsx). A second, independent top border on this section
  // sat flush against that one with zero gap between them -- the same doubled-hairline defect
  // already fixed once on this page (the old `border-y` on the "New this week" band), just via
  // a different mechanism (two sibling elements each drawing an edge, not one element drawing
  // two). If this component ever gets a second call site that is NOT preceded by a bordered
  // band, give that caller its own `border-t` via `className`, not this one.
  const stacked = layout === 'stack';

  return (
    <section aria-label="Trust and guarantees" className={cx(className)}>
      <div className={stacked ? undefined : 'mx-auto max-w-[1080px] px-5 py-6'}>
        {/* No pills, no borders, no circles, left-aligned. These are three short factual lines;
            dressing each one in its own container implied three separate offers. */}
        {/* THE DRAWING'S `.guarantees` (`mockups/index.html` section 15): three mono pills, no
            icons. The 2026-08-14 note above -- "No pills, no borders, no circles" -- was a ruling
            against the row it replaced, which was icon-in-a-circle pills mixed with volume
            statistics. Everything that ruling objected to is still gone: no icons, no circles, no
            statistics. What comes back is only the drawing's own hairline pill, which is what the
            structure check in `scripts/sections.mjs` reported this page never emitting. */}
        <ul className="guarantees list-none p-0">
          {facts.map((fact) => (
            <li key={fact.label}>
              <span className="pillx">{fact.label}</span>
            </li>
          ))}
        </ul>
        <p className={cx('klog', stacked ? 'mt-5 border-t border-border pt-5' : 'mt-4')}>
          {/* THE KILL COUNT IS NOT REPEATED HERE (founder, 2026-08-14). The number of killed ideas
              was stated four times on one scroll; removing `LiveKillCard` from the home page took
              out one of them and left this one, which the note at that removal site in
              `pages/index.tsx` records as the last duplicate with no prop to suppress it. It is a
              sentence now, not a statistic: the counts are stated once, above the shelf, from the
              live catalogue, and this row is the purchase terms.

              The LINK stays, because the kill log is the evidence behind the three terms above it
              and this row is where a buyer decides whether to believe them.

              The promise stays worded as "every kill that came with an argument" rather than
              "every one". /kill-log publishes a sample, not the whole log, and it says so in its
              own copy -- promising the complete log on the page that links to it is the exact
              overclaim the kill log exists to disprove. So this says what the log HOLDS ("the
              ideas that failed"), never how many of them, and never "every".

              No dash in the sentence (founder standing rule on copy): the clause it would have
              joined is a relative clause instead. */}
          The{' '}
          <Link href="/kill-log" className={textLinkClass()}>kill log</Link>
          {' '}publishes the ideas that failed these checks, each with the sourced reason why.
        </p>
      </div>
    </section>
  );
}

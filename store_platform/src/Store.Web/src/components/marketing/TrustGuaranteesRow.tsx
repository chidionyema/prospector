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
export default function TrustGuaranteesRow({ className, listed }: { className?: string; listed?: number }) {
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
  const passed = totals.passed;
  const live = listed ?? totals.live ?? totals.shown ?? 0;
  const researched = killed + passed;

  const facts: { icon: 'money' | 'shield' | 'verified' | 'shield' | 'released'; label: string; value: string }[] = [
    { icon: 'money', value: '£49 once', label: 'no subscription, no renewal' },
    { icon: 'shield', value: '14 day money back', label: 'no questions, no forms' },
    { icon: 'verified', value: `${researched.toLocaleString('en-GB')} researched`, label: 'every one cited' },
    { icon: 'shield', value: `${killed.toLocaleString('en-GB')} killed`, label: 'the ones that did not survive' },
    { icon: 'released', value: `${live} live now`, label: 'yours to read' },
  ];

  return (
    <section
      aria-label="Trust and guarantees"
      className={cx(
        'border-y border-border bg-bg/40',
        className,
      )}
    >
      <div className="mx-auto max-w-6xl px-6 py-6 md:px-8 md:py-8">
    <p className="mb-4 text-center text-caption font-bold uppercase tracking-widest text-muted">
          Trust and guarantees
        </p>
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {facts.map((fact) => (
            <li
              key={fact.value}
              className="flex flex-col items-center gap-1 text-center"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-surface2 text-text/70">
                <Icon name={fact.icon} size={14} />
              </span>
              <span className="text-meta font-bold text-text">{fact.value}</span>
              <span className="text-caption text-muted">{fact.label}</span>
            </li>
          ))}
        </ul>
        <p className="mt-5 text-center text-caption text-muted">
          The <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">kill log</Link>
          {' '}is the audit trail behind these numbers. Every killed idea is there, with the sourced reason why.
        </p>
      </div>
    </section>
  );
}

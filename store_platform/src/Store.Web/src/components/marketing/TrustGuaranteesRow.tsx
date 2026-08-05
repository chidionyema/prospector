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
export default function TrustGuaranteesRow({ className }: { className?: string }) {
  // Source: the canonical kill-log totals. killed + passed is the total
  // "researched" figure. live (the listings count) is exposed separately
  // in killTotals for callers that need it. All three live in the same JSON
  // file the kill-log page renders, so a single source of truth.
  const totals = killTotals as { killed: number; passed: number; live?: number; shown?: number };
  const killed = totals.killed;
  const passed = totals.passed;
  const live = totals.live ?? totals.shown ?? 0;
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
        <p className="mb-4 text-center font-mono text-[10px] font-bold uppercase tracking-widest text-muted">
          Trust and guarantees
        </p>
        <ul className="grid grid-cols-2 gap-4 md:grid-cols-5">
          {facts.map((fact) => (
            <li
              key={fact.value}
              className="flex flex-col items-center gap-1 text-center"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Icon name={fact.icon} size={14} />
              </span>
              <span className="text-sm font-bold text-text">{fact.value}</span>
              <span className="text-[11px] text-muted">{fact.label}</span>
            </li>
          ))}
        </ul>
        <p className="mt-5 text-center text-[11px] text-muted">
          The <Link href="/kill-log" className="font-semibold text-text underline underline-offset-2">kill log</Link>
          {' '}is the audit trail behind these numbers. Every killed idea is there, with the sourced reason why.
        </p>
      </div>
    </section>
  );
}

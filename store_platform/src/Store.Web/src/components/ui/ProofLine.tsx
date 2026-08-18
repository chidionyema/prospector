import React from 'react';

import { cx } from '@/components/ui/cx';

/**
 * The one place the site says how much evidence is behind a pack.
 *
 * MASTER-BRIEF section 10 asks for one proof-line format sitewide. There were four, and they
 * disagreed on the wording rather than on the number: "12 sources", "6 checks · 12 sources ·
 * verified 2026-08-01", "12 sources cited", and "12 cited sources, six of them quoted below". Each
 * one was written where it stood, so nobody ever saw them side by side.
 *
 * The differences were never decisions. What differs legitimately between those four places is how
 * much of the proof fits: a catalogue row has space for a count, a report header has space for the
 * count, the check total and the date. So the format is one decision here, and each call site
 * chooses which PARTS it shows, never how they are worded.
 *
 * THE SEPARATOR IS A MIDDOT, and the parts are ordered widest-to-narrowest: checks (a property of
 * the method), sources (a property of this pack), date (a property of this run). Reading left to
 * right that goes from what is always true to what was true on one day.
 */

/** "1 source" / "12 sources". The singular case is real: a pack can clear on one strong source. */
export function sourcesLabel(count: number): string {
  return `${count} ${count === 1 ? 'source' : 'sources'}`;
}

/** "6 checks" / "1 check". */
export function checksLabel(count: number): string {
  return `${count} ${count === 1 ? 'check' : 'checks'}`;
}

/**
 * The date only, never the time.
 *
 * `verifiedAt` is a full ISO timestamp with microseconds and a UTC offset. Printing the time of
 * day implies a precision that means nothing about a research run, and the bare ISO date is the
 * one format that is unambiguous to a reader in any market, which matters on a page selling UK and
 * US research side by side. A slice, not a formatter, for the same reason: a formatter would apply
 * the reader's locale and print a different date to a reader either side of midnight UTC.
 */
export function verifiedLabel(verifiedAt: string): string {
  return `verified ${verifiedAt.slice(0, 10)}`;
}

export function ProofLine({
  sources,
  checks,
  verifiedAt,
  className,
}: {
  sources: number;
  checks?: number;
  verifiedAt?: string;
  className?: string;
}) {
  const parts = [
    typeof checks === 'number' ? checksLabel(checks) : null,
    sourcesLabel(sources),
    verifiedAt ? verifiedLabel(verifiedAt) : null,
  ].filter(Boolean);

  return (
    <p className={cx('font-mono text-caption text-subtle', className)}>{parts.join(' · ')}</p>
  );
}

export default ProofLine;

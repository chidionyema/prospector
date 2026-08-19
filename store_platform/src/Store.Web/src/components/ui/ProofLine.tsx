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

/**
 * THE CARD AND ROW PROOF LINE, and the only one (fix prompt D4, 2026-08-18).
 *
 * `mockups/index.html` draws exactly two forms of it inside `a.row`:
 *
 *     <p class="proof num"><b>41</b> sources</p>
 *     <p class="proof num"><b>17×</b> payback · <b>28</b> sources</p>
 *
 * The shelf was emitting three, and the difference was wording rather than fact: "38 sources"
 * from `sourcesLabel`, "16 cited sources behind it" and "2× the price back in month one,
 * modelled" from `packLeadStat`. The last two are labels written for the featured card's 44px
 * `.stat` device, where there is room for a sentence. On a 12.5px row there is not, and the
 * nowrap `truncate` they carried is what ran the line off the right edge of the card at 390px.
 *
 * `<b>` on the figure and plain text on the noun, because `.proof b` is the only weight the
 * drawing's stylesheet sets here. NOTHING ELSE GOES IN `.proof`. The row's market note is a fact about the
 * READER rather than about the pack, so it sits in the row's `.top` eyebrow, not here.
 */
export function CardProof({
  sources,
  payback,
  className,
  /* `span` for the three-up tile. Its `.foot` is a `<span>` in the drawing
     (`mockups/index.html` section 5), and a `<p>` inside a `<span>` is invalid HTML: the parser
     closes the span, so the price that follows ended up outside the foot it is laid out in. The
     row's proof line stays a `<p>`, which is what the drawing writes there. */
  as: Tag = 'p',
}: {
  sources?: number | null;
  payback?: number | null;
  className?: string;
  as?: 'p' | 'span';
}) {
  const parts: React.ReactNode[] = [];
  if (typeof payback === 'number' && payback > 0) {
    // dash-free-ignore -- the multiplication sign is U+00D7, not a dash; named here so a reader
    // checking the ban does not have to look it up.
    parts.push(
      <React.Fragment key="payback">
        <b>{payback}×</b> payback
      </React.Fragment>,
    );
  }
  if (typeof sources === 'number' && sources > 0) {
    parts.push(
      <React.Fragment key="sources">
        <b>{sources}</b> {sources === 1 ? 'source' : 'sources'}
      </React.Fragment>,
    );
  }
  if (parts.length === 0) return null;

  return (
    <Tag className={cx('proof num', className)}>
      {parts.map((part, i) => (
        <React.Fragment key={i}>
          {i > 0 && ' \u00B7 '}
          {part}
        </React.Fragment>
      ))}
    </Tag>
  );
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

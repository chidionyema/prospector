import React from 'react';

import { citedFigure } from '@/lib/sources';

/**
 * A price we did not set, rendered with the page it came from.
 *
 * The component takes an id, never a string. That is the whole design: there is no prop through
 * which a hand-typed number can enter this component, so a figure on the marketing pages either
 * resolves to a row in `sources.ts`, publisher, URL, date read, or it does not render at all.
 * The previous arrangement failed precisely because the number and its provenance were separable,
 * and the number outlived the provenance.
 *
 * The citation is a real anchor, not a footnote marker. A buyer deciding whether £49 is a lot of
 * money should be able to check the comparison in one click, on the seller's own page, and see
 * for themselves that we did not choose the flattering end of it.
 */
export function SourcedFigure({ id, className }: { id: string; className?: string }) {
  const source = citedFigure(id);
  return (
    <span className={className}>
      <span className="font-semibold text-text">{source.figure}</span>{' '}
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="whitespace-nowrap text-accent underline decoration-dotted underline-offset-2 transition-colors hover:text-accent-hover"
      >
        {source.publisher}
        <span className="sr-only">, opens the source in a new tab</span>
      </a>
      {/* The date travels with the price because a price is perishable. A figure checked eight
          months ago and rendered as present tense is the next version of the same problem. */}
      {/* `--subtle`, not `--faint`: the date is information a buyer is entitled to read, and
          `--faint` is 2.56:1 and declared as never carrying information (globals.css:43). */}
      <span className="text-subtle">, checked {formatChecked(source.checkedOn)}</span>
    </span>
  );
}

/**
 * The caveat, rendered separately so a placement can put it where there is room.
 *
 * It is a distinct export rather than an option on `SourcedFigure` so that dropping it is a
 * visible deletion in a diff rather than a flag flipped to false.
 */
export function SourcedCaveat({ id, className }: { id: string; className?: string }) {
  const source = citedFigure(id);
  if (!source.caveat) return null;
  return <span className={className}>{source.caveat}</span>;
}

function formatChecked(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  // Constructed in UTC and formatted in UTC, so the rendered date cannot shift by one under a
  // negative-offset timezone and make server and client markup disagree.
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

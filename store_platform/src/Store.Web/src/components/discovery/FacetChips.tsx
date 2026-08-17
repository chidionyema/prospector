import React from 'react';

import { cx } from '@/components/ui/cx';
import type { Pack } from '@/lib/api/client';
import { label, shortLabel, type FacetKind } from '@/lib/facets';

/**
 * The facet chips on a card or a palette row.
 *
 * Renders only what the engine actually tagged. A pack with no facets renders nothing at all,
 * no "Uncategorised" chip, no placeholder, because a chip is a claim and an untagged pack has
 * no claim to make. Copy comes from `lib/facets.ts`, never from the raw enum token.
 */
export function FacetChips({
  pack,
  compact = false,
  max = 4,
  omit,
  className,
}: {
  pack: Pack;
  /** Compact uses the short copy ("B2C") for dense rows like the command palette. */
  compact?: boolean;
  max?: number;
  /**
   * A facet the SURFACE already states, which must not be repeated on every card.
   *
   * Measured on /collections/b2c-business-ideas, 2026-08-14: the `B2C` chip rendered on all 31 cards,
   * because the page's whole selection rule is `payer === 'b2c'`. A chip that is true of every
   * card on a shelf distinguishes none of them, and it takes the first chip slot -- so `max` then
   * cut a facet that DID vary off the end of the row. Same defect the market chip had on the home
   * shelf ("For UK rules" on all 63 cards) and the same fix: state it once, on the page.
   *
   * Passed by the landing page as the `{kind, value}` it filters on, so the two can never
   * disagree; nothing else omits anything.
   */
  omit?: { kind: FacetKind; value: string } | null;
  className?: string;
}) {
  const text = compact ? shortLabel : label;
  const chips: string[] = [];

  const push = (kind: FacetKind, value: string | null | undefined) => {
    if (omit && omit.kind === kind && omit.value === value) return;
    const rendered = text(kind, value);
    if (rendered) chips.push(rendered);
  };

  push('payer', pack.payer);
  push('effort', pack.effort);
  push('commitment', pack.commitment);
  push('mechanism', pack.mechanism);
  for (const advantage of pack.advantages ?? []) push('advantage', advantage);

  if (chips.length === 0) return null;

  return (
    <ul className={cx('flex flex-wrap items-center gap-1.5', className)}>
      {chips.slice(0, max).map((chip) => (
        <li
          key={chip}
          className="inline-flex items-center rounded-sm border border-border bg-surface2 px-2.5 py-0.5 text-caption font-medium text-muted"
        >
          {chip}
        </li>
      ))}
    </ul>
  );
}

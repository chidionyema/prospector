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
  className,
}: {
  pack: Pack;
  /** Compact uses the short copy ("B2C") for dense rows like the command palette. */
  compact?: boolean;
  max?: number;
  className?: string;
}) {
  const text = compact ? shortLabel : label;
  const chips: string[] = [];

  const push = (kind: FacetKind, value: string | null | undefined) => {
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
          className="rounded-full bg-bg px-2.5 py-1 text-caption font-semibold text-text/70 ring-1 ring-inset ring-border"
        >
          {chip}
        </li>
      ))}
    </ul>
  );
}

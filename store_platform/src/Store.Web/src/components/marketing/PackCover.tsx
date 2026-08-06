import React from 'react';
import { cx } from '@/components/ui/cx';
import { categoryFor } from '@/lib/category';
import type { Pack } from '@/lib/api/client';

export interface PackCoverProps {
  pack: Pack;
  /** Optional className passthrough for layout (margin, padding). */
  className?: string;
}

/**
 * The pack's identity plate: sector, dossier number, market. One line, on the detail page.
 *
 * WHAT THIS REPLACED (brand v3, 2026-08-06), and why every part of it went:
 *
 * This was a 16:9 (or 1:1) coloured plate: a 135deg two-stop sector gradient, a paper-grain
 * overlay, two radial vignettes, a 180px sector icon bleeding off the bottom-right corner, and the
 * pack title set in `font-serif font-bold` white over a black gradient scrim, with the ID above it
 * in `uppercase tracking-[0.2em]`.
 *
 * It was decorative in the strict sense: it carried the title (repeated verbatim in the `<h1>`
 * immediately below it), the ID, and the sector, and it conveyed no information those three plain
 * elements do not. On the detail page it pushed the actual `<h1>`, the price and the buy button
 * roughly 550px down the page, so on a 1280x720 viewport the fold contained a gradient and nothing
 * to buy. On the shelf it made sixty-one dossiers read as sixty-one colourful tiles.
 *
 * The three facts it carried survive here, at 44px instead of 550px, in the same shape as the
 * plate on the product card so a buyer arriving from the shelf sees the row they just clicked.
 *
 * The `variant` prop is gone rather than kept as a no-op: there is no square form any more,
 * because the product card renders this row itself and does not import a component to do it.
 */
export default function PackCover({ pack, className }: PackCoverProps) {
  const cat = categoryFor(pack);

  return (
    <div
      className={cx(
        'flex h-11 items-center justify-between gap-3 rounded-md border border-border bg-surface2 px-4',
        className,
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        {/* The dot is the only colour here, and it is decorative in the a11y sense: the sector
            name sits immediately beside it, so nothing is encoded in hue alone. */}
        <span className={cx('h-2 w-2 flex-none rounded-full', cat.dot)} aria-hidden="true" />
        {cat.tagged && <span className="truncate text-caption font-medium text-muted">{cat.label}</span>}
      </span>
      {/* Mono, because these are identifiers rather than prose: the dossier reference a buyer
          quotes in a support email, and the market the listing is priced for. */}
      <span className="flex flex-none items-center gap-2 font-mono text-caption text-subtle">
        {pack.market && <span>{pack.market.toUpperCase()}</span>}
        <span aria-hidden="true">·</span>
        <span>№ {pack.id.slice(0, 6).toUpperCase()}</span>
      </span>
    </div>
  );
}

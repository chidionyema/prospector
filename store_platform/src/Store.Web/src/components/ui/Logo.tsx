import React from 'react';
import { cx } from './cx';
import { BRAND } from '@/lib/config';

interface LogoProps {
  className?: string;
  /**
   * Flip the lockup for the dark `band` / footer: the tile goes WHITE with an ink punch, and the
   * wordmark inverts to light. On light backgrounds (default) the tile is ink (`--band`) and the
   * struck octagon is white. The mark always contrasts its ground in both hue and lightness.
   */
  onDark?: boolean;
  /** Only render the mark tile, omitting the wordmark (used in the sticky header). */
  monogramOnly?: boolean;
}

/**
 * Brand lockup: an "assay hallmark" mark + the configurable wordmark (BRAND.name).
 *
 * The mark is a struck octagonal punch with the PASS check knocked out of it — an assay hallmark, the
 * stamp that certifies a thing has been tested and is genuine. That is the product: every verdict is a
 * grounded receipt, and only what clears the filter is struck. The octagonal cartouche (not a generic
 * round badge) is the ownable shape; it is a solid monochrome fill (one ink tile, one struck octagon)
 * so it reads at favicon size and carries no inherited identity. The wordmark renders from the single
 * configurable `BRAND.name` (lib/config) so the name matches the page title, OG/Twitter meta, both
 * footers, and email at once. We emphasise the first word and mute the rest.
 *
 * Source of truth for the favicon/app icon too: public/icon.svg mirrors this mark.
 */
export function Logo({ className, onDark = false, monogramOnly = false }: LogoProps) {
  const tile = onDark ? 'var(--surface, #ffffff)' : 'var(--band, #0f172a)';
  const glass = onDark ? 'var(--band, #0f172a)' : 'var(--surface, #ffffff)';
  const textColor = onDark ? 'text-white' : 'text-text';

  const mark = (
    <svg viewBox="0 0 40 40" className="h-9 w-9 flex-none" aria-hidden="true">
      <rect x="0" y="0" width="40" height="40" rx="9" fill={tile} />
      {/* assay hallmark: an octagonal punch (the certified cartouche) with the PASS check struck out */}
      <polygon points="15,8 25,8 32,15 32,25 25,32 15,32 8,25 8,15" fill={glass} />
      <path
        d="M13.5 20.2 L18 24.7 L27.5 14.8"
        fill="none"
        stroke={tile}
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );

  if (monogramOnly) {
    return <span className={cx('inline-flex', className)}>{mark}</span>;
  }

  const [first, ...rest] = BRAND.name.split(' ');
  const tail = rest.join(' ');

  return (
    <div className={cx('flex items-center gap-2.5', className)}>
      {mark}
      <span className="sr-only">{BRAND.name}</span>
      <span aria-hidden="true" className="whitespace-nowrap font-sans text-xl font-bold tracking-tight leading-none">
        <span className={textColor}>{first}</span>
        {tail && <span className={cx('font-semibold', onDark ? 'text-white/55' : 'text-muted')}> {tail}</span>}
      </span>
    </div>
  );
}

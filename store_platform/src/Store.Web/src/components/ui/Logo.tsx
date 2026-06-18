import React from 'react';
import { cx } from './cx';
import { BRAND } from '@/lib/config';

interface LogoProps {
  className?: string;
  /**
   * Flip the lockup for a dark ground (the `band` / footer-on-ink case): the wordmark inverts to
   * light, and the compact `P` tile becomes white with an ink letter.
   */
  onDark?: boolean;
  /** Render only the compact `P` tile (used where a full wordmark will not fit). */
  monogramOnly?: boolean;
}

/**
 * Brand lockup: a typographic wordmark, no pictogram.
 *
 * A drawn mark (a loupe, an assay punch) kept reading as a stock icon and dating the brand; a
 * confidently-set wordmark does not. So the identity IS the name: the first word in ink, the rest
 * muted, tight tracking. Size comes from the caller's `className` (e.g. `text-xl` in the header,
 * `text-3xl` in the footer) so one component serves every placement. The wordmark renders from the
 * single configurable `BRAND.name` (lib/config) so it always matches the page title, OG/Twitter
 * meta, both footers, and email.
 *
 * `monogramOnly` is the only compact form — a `P` tile — kept for tight spots and for favicon
 * parity (public/icon.svg mirrors it).
 */
export function Logo({ className, onDark = false, monogramOnly = false }: LogoProps) {
  const textColor = onDark ? 'text-white' : 'text-text';
  const mutedColor = onDark ? 'text-white/55' : 'text-muted';

  if (monogramOnly) {
    return (
      <span
        aria-label={BRAND.name}
        className={cx(
          'inline-flex h-9 w-9 flex-none items-center justify-center rounded-[10px] font-sans text-xl font-black leading-none',
          onDark ? 'bg-white text-text' : 'bg-band text-white',
          className,
        )}
      >
        P
      </span>
    );
  }

  const [first, ...rest] = BRAND.name.split(' ');
  const tail = rest.join(' ');

  return (
    <span className={cx('inline-flex items-baseline whitespace-nowrap font-sans font-bold tracking-tight leading-none', className)}>
      <span className="sr-only">{BRAND.name}</span>
      <span aria-hidden="true" className={textColor}>
        {first}
      </span>
      {tail && (
        <span aria-hidden="true" className={cx('ml-1.5 font-semibold', mutedColor)}>
          {tail}
        </span>
      )}
    </span>
  );
}

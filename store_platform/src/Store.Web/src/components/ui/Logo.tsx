import React from 'react';
import { cx } from './cx';
import { BRAND } from '@/lib/config';

interface LogoProps {
  className?: string;
  /** Render only the compact initial tile (used where a full wordmark will not fit). */
  monogramOnly?: boolean;
}

/**
 * Brand lockup: a typographic wordmark, no pictogram.
 *
 * ONE colour, ONE weight, no dot (founder decision, 2026-08-06).
 *
 * What this replaces: "Mum" in ink + "chimp" in grey + a vermillion full stop. Three decisions
 * inside eight characters, and none of them carried meaning -- the split fell mid-word, so the
 * two-tone treatment read as a rendering fault rather than as a lockup, and the coloured period
 * is the single most dated device in tech branding. A name set once, in one weight, with the
 * tracking closed up slightly, is the whole identity. Vercel and Linear do exactly this.
 *
 * Size comes from the caller's `className` (e.g. `text-h2` in the header) so one component serves
 * every placement. The wordmark renders from the configurable `BRAND.name` (lib/config) so it
 * always matches the page title, OG/Twitter meta, both footers, and email.
 *
 * The `onDark` prop is gone with the dark band: v3 has no dark chrome, so there is no ground for
 * an inverted lockup to sit on.
 *
 * `monogramOnly` is the only compact form, a single-initial tile, kept for tight spots and for
 * favicon parity (public/icon.svg mirrors it). The letter is derived from `BRAND.wordmark` rather
 * than hardcoded, so renaming the brand cannot leave the tile and the favicon disagreeing.
 */
export function Logo({ className, monogramOnly = false }: LogoProps) {
  const { first, second } = BRAND.wordmark;

  if (monogramOnly) {
    return (
      <span
        aria-label={BRAND.name}
        className={cx(
          'inline-flex h-9 w-9 flex-none items-center justify-center rounded-md bg-text font-sans text-h2 font-semibold leading-none text-white',
          className,
        )}
      >
        {first.charAt(0)}
      </span>
    );
  }

  return (
    // aria-hidden on the visible text + an sr-only full name: the rendered string is assembled
    // from two config fields, and a screen reader should hear the brand once, not the halves.
    <span
      className={cx(
        'inline-flex whitespace-nowrap font-sans font-semibold leading-none tracking-[-0.02em] text-text',
        className,
      )}
    >
      <span className="sr-only">{BRAND.name}</span>
      <span aria-hidden="true">{`${first}${second}`}</span>
    </span>
  );
}

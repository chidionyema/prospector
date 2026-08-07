import React from 'react';
import { cx } from './cx';
import { BRAND } from '@/lib/config';

interface LogoProps {
  className?: string;
  /** Render only the compact initial tile (used where a full wordmark will not fit). */
  monogramOnly?: boolean;
}

/**
 * Brand lockup: a strata mark plus the wordmark.
 *
 * ONE colour, ONE weight, no dot (founder decision, 2026-08-06). Those three constraints STAND --
 * the lockup is still a single ink, a single weight, and there is no coloured full stop.
 *
 * What changed on 2026-08-07, by founder decision: the "no pictogram" half. Set alone, the
 * wordmark used the same family and weight as an `<h2>`, so in the header it was typographically
 * indistinguishable from a heading -- there was nothing there to read as identity. The mark is
 * the fix, and it is deliberately NOT a decorative flourish of the kind the 2026-08-06 decision
 * threw out: it is drawn in the site's own existing visual language (see `BrandMark` below).
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
 * `monogramOnly` is the only compact form, kept for tight spots and for favicon parity
 * (public/icon.svg mirrors it). It is now the mark alone rather than a lettered tile, which is
 * also what makes the favicon honest: an "M" in a tab strip is a letter shared with several
 * thousand other sites, whereas the mark is the one this brand actually owns.
 */
/**
 * The brand mark: a stratigraphy tile.
 *
 * WHY THIS SHAPE, and not an arbitrary glyph. Every product on this site already carries a mark
 * made of horizontal strata (`lib/packMark.ts`), on the stated reasoning that a shop selling
 * sourced research cannot illustrate itself with stock photography, so its identity has to be
 * COMPUTED from the thing it identifies. The brand mark is the ur-form of that system: the same
 * layered-bands language the 57 packs speak, drawn once and deliberately rather than seeded from a
 * hash. Set the brand beside any pack mark and they are visibly the same alphabet.
 *
 * Hand-authored, NOT `strata(BRAND.name)`. A hashed brand mark would be an arbitrary shape that
 * happens to be stable -- fine for a pack, wrong for an identity, which has to survive being 16px
 * in a browser tab. Three bands, staggered, with the inset stack reading left-aligned so it holds
 * together as one object at any size.
 *
 * Knocked out of a solid tile rather than drawn as ink bands on nothing, for two reasons: it keeps
 * the existing monogram's silhouette (this replaces a `bg-text` rounded tile holding an "M", so
 * every place that reserved space for the monogram still gets the same footprint), and a solid
 * shape survives small sizes and busy backgrounds, where hairline bars break up.
 *
 * Sized in `em` so one component serves the 28px header lockup and the footer alike: the mark
 * always matches the wordmark it stands next to, with no per-placement size prop.
 */
function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 100 100"
      className={cx('h-[1.06em] w-[1.06em] flex-none', className)}
    >
      <rect width="100" height="100" rx="22" fill="currentColor" />
      {/* Knocked out in the page background rather than in white, so the mark stays correct if the
          lockup is ever set on a tinted surface. */}
      {[
        { y: 24, w: 64 },
        { y: 44, w: 40 },
        { y: 64, w: 56 },
      ].map((b) => (
        <rect key={b.y} x={18} y={b.y} width={b.w} height={12} rx={3} className="fill-bg" />
      ))}
    </svg>
  );
}

export function Logo({ className, monogramOnly = false }: LogoProps) {
  const { first, second } = BRAND.wordmark;

  if (monogramOnly) {
    // The compact form is now the mark itself, not a lettered tile. Two different marks for one
    // brand is worse than either alone: the header would have shown a strata tile and the tight
    // slots an "M", and a reader has no way to learn that those are the same company.
    return (
      <span
        aria-label={BRAND.name}
        role="img"
        className={cx('inline-flex flex-none text-h2 leading-none text-text', className)}
      >
        <BrandMark />
      </span>
    );
  }

  return (
    // aria-hidden on the visible text + an sr-only full name: the rendered string is assembled
    // from two config fields, and a screen reader should hear the brand once, not the halves.
    <span
      className={cx(
        'inline-flex items-center gap-[0.34em] whitespace-nowrap font-sans font-semibold leading-none tracking-[-0.02em] text-text',
        className,
      )}
    >
      <span className="sr-only">{BRAND.name}</span>
      <BrandMark />
      <span aria-hidden="true">{`${first}${second}`}</span>
    </span>
  );
}

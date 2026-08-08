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
 * in a browser tab. Three bands, centred, descending in width: a funnel. See the band list in
 * `BrandMark` for why it is centred rather than left-aligned -- briefly, left-aligned horizontal
 * bars in a dark tile are the text/document glyph, and the mark was being read as a list-view
 * toggle rather than as identity.
 *
 * Knocked out of a solid tile rather than drawn as ink bands on nothing, for two reasons: it keeps
 * the existing monogram's silhouette (this replaces a `bg-text` rounded tile holding an "M", so
 * every place that reserved space for the monogram still gets the same footprint), and a solid
 * shape survives small sizes and busy backgrounds, where hairline bars break up.
 *
 * Sized in `em` so one component serves the 28px header lockup and the footer alike: the mark
 * always matches the wordmark it stands next to, with no per-placement size prop.
 *
 * SIZED TO THE CAP HEIGHT, NOT THE EM BOX (2026-08-08). It was `1.06em`, which is a measurement
 * of the FONT rather than of the letters: at the header's 24px the em box is 24px but the capital
 * M beside it is 16.32px tall (measured off Switzer via canvas `actualBoundingBoxAscent`), so a
 * 25.44px tile stood 56% taller than every letterform next to it and the lockup read as an icon
 * with a caption. The pairing a reader actually sees is tile-against-cap, so that is the ratio to
 * set: 0.82em is 19.7px here, a 1.21 overshoot on the cap. Solid marks want to sit slightly proud
 * of the caps rather than flush -- flush reads as slightly sunk, because the tile has no serifs or
 * overshoot of its own to carry the eye.
 *
 * `standalone` restores the full em size for `monogramOnly`. The cap-height ratio only makes sense
 * beside letters; with no wordmark to pair against, the mark is the whole object and should fill
 * its slot. Both sizes are written as literal classes rather than interpolated, because Tailwind
 * scans source text and never sees a class assembled at runtime.
 */
function BrandMark({ className, standalone = false }: { className?: string; standalone?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 100 100"
      className={cx(
        standalone ? 'h-[1em] w-[1em]' : 'h-[0.82em] w-[0.82em]',
        'flex-none',
        className,
      )}
    >
      {/* rx 14, not 22. 22% of the tile is app-icon round, and it became the roundest object on
          the site the day v3.1 took `--radius-sm` and `--radius-md` to 2px (tokens.css) and
          squared off 139 of the 187 `rounded-*` call sites. A brand mark is allowed its own
          geometry, but not a geometry that contradicts the system it is meant to be the ur-form
          of: at the header's 19.7px, rx 14 renders as 2.8px, which sits with the 2px corners
          everywhere else instead of against them. */}
      <rect width="100" height="100" rx="14" fill="currentColor" />
      {/* Knocked out in the page background rather than in white, so the mark stays correct if the
          lockup is ever set on a tinted surface.

          CENTRED AND DESCENDING (2026-08-08). These were three LEFT-ALIGNED bands of ragged width
          (64/40/56), and left-aligned horizontal bars inside a dark rounded tile is the universal
          text/document/list primitive -- Material's `subject` and `format_align_left`, reader
          mode, every "list view" toggle ever drawn. In a header, beside five nav items, it parsed
          as a control rather than as identity.

          Rendering the alternatives side by side at 19.7/32/16px is what settled it, and it also
          killed the obvious fix: making the widths monotonic while keeping the left margin
          (64/52/38) is WORSE, because a stack of left-aligned lines with a short last one is
          precisely the paragraph glyph. The shared left margin was the problem, not the raggedness
          -- text always shares a left edge, so nothing that keeps one escapes the read.

          Centring the bands and descending the widths makes it a funnel, which is the one shape
          that is both unmistakably not a list and exactly what this business does: 1,444 ideas in
          at the top, 80 out at the bottom. It stays in the strata alphabet the 57 pack marks are
          drawn from (`lib/packMark.ts`) -- still horizontal bands, still knocked out of a solid
          tile -- so the brand and the products remain visibly the same system.

          Symmetric by construction: 3 bands x 14 + 2 gaps x 10 = 62, centred in 100 leaves 19
          above and 19 below. `x` is always (100 - w) / 2. */}
      {[
        { y: 19, x: 10, w: 80 },
        { y: 43, x: 24, w: 52 },
        { y: 67, x: 38, w: 24 },
      ].map((b) => (
        <rect key={b.y} x={b.x} y={b.y} width={b.w} height={14} rx={2} className="fill-bg" />
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
        <BrandMark standalone />
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

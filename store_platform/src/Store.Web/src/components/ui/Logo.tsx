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
 * ── v4, 2026-08-09: EXPLICIT FOUNDER OVERRIDE of the v3 "ONE weight" rule below ──────────────
 * "Mum" now sets `font-bold` (700) against "chimp" at `font-normal` (400) -- see the wordmark
 * render below. The single objection that produced the ONE-weight rule (2026-08-06) was that the
 * font loaded then (Geist, static 400/500/600) would SYNTHESISE any heavier ask, smearing a fake
 * bold onto the one string that is the brand. That objection no longer holds: the sans face is
 * now self-hosted Switzer, declared `font-weight: 100 900` as a true variable axis
 * (`tokens.css`, the `@font-face` block), so 700 renders as a real intermediate weight, not a
 * synthesis. The ink stays single (`text-text`, no second colour) and there is still no dot --
 * only the "one weight" third of the 2026-08-06 rule is what changes here. Still ONE colour, ONE
 * name, no punctuation.
 *
 * What changed on 2026-08-07, by founder decision: the "no pictogram" half. Set alone, the
 * wordmark used the same family and weight as an `<h2>`, so in the header it was typographically
 * indistinguishable from a heading -- there was nothing there to read as identity. The mark is
 * the fix, and it is deliberately NOT a decorative flourish of the kind the 2026-08-06 decision
 * threw out: it is drawn in the site's own existing visual language (see `BrandMark` below).
 *
 * What v3 replaced: "Mum" in ink + "chimp" in grey + a vermillion full stop. That treatment's
 * failure was never the weight contrast -- it was that three decisions landed inside eight
 * characters (a colour split, a second muted colour, a coloured period) and the split fell
 * mid-word, so it read as a rendering fault. v4 keeps v3's fix for two of those three (one ink,
 * no dot) and reintroduces contrast through weight alone, which is a typographic device, not a
 * colour one, and does not fall mid-word the way the old grey half did -- it sets each whole
 * half, "Mum" and "chimp", at its own weight.
 *
 * Size comes from the caller's `className` (e.g. `text-h2` in the header) so one component serves
 * every placement. The wordmark renders from the configurable `BRAND.name` (lib/config) so it
 * always matches the page title, OG/Twitter meta, both footers, and email.
 *
 * The `onDark` prop is gone with the dark band: v3 has no dark chrome, so there is no ground for
 * an inverted lockup to sit on.
 *
 * `monogramOnly` is the compact form, kept for tight spots and for favicon parity (public/icon.svg
 * mirrors it) -- and, as of this pass, actually WIRED to a breakpoint: it was declared and
 * documented but had no call site with `monogramOnly` set anywhere in the app (`grep -rn
 * monogramOnly src --include='*.tsx'` matched only this file, 2026-08-09), so the full wordmark
 * lockup rendered at every width including the phone header it was explicitly sized for tight
 * spots to avoid. `MarketingLayout.tsx` now swaps to this form below `md`. It is the mark alone
 * rather than a lettered tile, which is also what makes the favicon honest: an "M" in a tab strip
 * is a letter shared with several thousand other sites, whereas the mark is the one this brand
 * actually owns.
 */
/**
 * The brand mark: a funnel cut from three strata.
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
 * in a browser tab.
 *
 * THE TILE IS GONE -- founder decision, 2026-08-14, choosing option D from a sheet of six concepts
 * rendered side by side at 16/24/32/48px, as a 180px iOS tile, and swapped into the live header at
 * 1280 and 390. The tile had been rejected three times, and twice the fix changed a PARAMETER:
 * band alignment (2026-08-08), cut corner and radius (2026-08-09). The verdict did not move,
 * because a rounded square with bars knocked out of it is the generic app-icon silhouette whatever
 * the corner does -- so no radius, band width or colour was ever going to answer it. What changes
 * here is the CONCEPT: there is no container. The mark IS the funnel -- three slabs narrowing in
 * width and in height at once, wide intake at the top and one thing out at the bottom, which is
 * what the engine does (1,444 ideas in, 80 on the shelf).
 *
 * It stays inside the strata alphabet the pack marks are drawn from (`lib/packMark.ts`): still
 * horizontal bands, still stacked, still descending. What it drops is the frame around them.
 *
 * DRAWN AS THREE SOLID SLABS, not as one shape with bands knocked out of it. The tile knocked its
 * bands out in `fill-bg`, which quietly made the mark depend on the surface behind it: right on
 * the white storefront, wrong on any other ground, and in `public/icon.svg` those knockouts were
 * white ink that would have shown as bars against a dark browser tab strip. Three closed paths in
 * `currentColor` have no such dependency -- one colour, any ground, and `--brand-mark` recolours
 * all of it.
 *
 * The known objection, recorded because it was accepted rather than missed: a funnel is also the
 * generic filter glyph. It was taken on the argument that here the funnel is the business, not a
 * control -- and unlike the tile's app-icon read, this one was judged in the live header beside
 * the real nav before it shipped.
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
        /* Founder override, 2026-08-08 (see --brand-mark in tokens.css for the collision this
           carries): the mark alone breaks the ONE colour / no-brand-colour rule the rest of the
           lockup still holds. The wordmark next to it stays ink -- only the tile takes the
           accent, which is why this class sits here and not on the parent `<span>`. */
        'text-brand-mark',
        className,
      )}
    >
      {/* THE GEOMETRY, so a future edit does not have to re-derive it. The funnel's edges run from
          (3, 6) and (97, 6) down to (37, 94) and (63, 94). The three slabs are that trapezoid cut
          by two horizontal gaps, at y=38..46 and y=70..78, so each slab is both narrower AND
          shorter than the one above it: 32, 24 and 16 units tall. Two things descend at once,
          which is what stops the stack reading as a list of equal rows.

          The slab corners are square. `--radius-sm` is 2px sitewide (`tokens.css`, "ONE RADIUS,
          2px, AND NO PILLS") and a 2-unit radius on a 100-unit viewBox is 0.32px at the 16px
          favicon -- a rounding that cannot be seen at the size that matters and that softens the
          diagonal edge at the size that does. The mark's own geometry is the exception the token
          block already allows; it does not contradict the system, it just declines a radius.

          Coordinates are literal rather than computed from the edge equations at render time: the
          favicon in `public/icon.svg` carries the same three paths as static text, and two
          derivations of one shape are two shapes waiting to diverge. */}
      <path d="M 3 6 L 97 6 L 84.64 38 L 15.36 38 Z" fill="currentColor" />
      <path d="M 18.45 46 L 81.55 46 L 72.27 70 L 27.73 70 Z" fill="currentColor" />
      <path d="M 30.82 78 L 69.18 78 L 63 94 L 37 94 Z" fill="currentColor" />
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
        'inline-flex items-center gap-[0.34em] whitespace-nowrap font-sans leading-none tracking-[-0.02em] text-text',
        className,
      )}
    >
      <span className="sr-only">{BRAND.name}</span>
      <BrandMark />
      {/* One wrapper span, not two loose ones: the outer element is a flex container with
          `gap-[0.34em]` so the icon sits clear of the wordmark, but flex `gap` lands between
          EVERY adjacent flex-item sibling, not just the ones a developer meant to space. Two
          bare spans here were both direct flex children, so the gap opened up between "Mum"
          and "chimp" too, rendering the wordmark as two words with a visible space -- the
          opposite of the "reads as one word" comment this replaced. Nesting both halves inside
          one non-flex span makes them a single flex child again: weight still differs between
          them (both stay `text-text`, no colour split; Tailwind reads utility classes from
          source text, so `font-bold`/`font-normal` still need their own elements), but no gap
          utility can reach between them, so `${first}${second}` reads as one word exactly as it
          did when it was a single string. */}
      <span aria-hidden="true">
        <span className="font-bold">{first}</span>
        <span className="font-normal">{second}</span>
      </span>
    </span>
  );
}

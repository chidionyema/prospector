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
        /* Founder override, 2026-08-08 (see --brand-mark in tokens.css for the collision this
           carries): the mark alone breaks the ONE colour / no-brand-colour rule the rest of the
           lockup still holds. The wordmark next to it stays ink -- only the tile takes the
           accent, which is why this class sits here and not on the parent `<span>`. */
        'text-brand-mark',
        className,
      )}
    >
      {/* CUT CORNER, not a plain rounded rect -- explicit founder override, 2026-08-09, of the
          rx-14 tile above. A solid rounded square with three knocked-out bars inside it is the
          generic-app-icon silhouette itself (Slack, Notion, a hundred others), independent of
          what radius it uses; a reader flagged that read directly ("feels a bit generic and
          boxed-in") against THIS shape, so tightening the radius alone would not have answered
          the complaint. The fix gives the tile a feature the generic silhouette does not have: one
          corner (top-right) is cut at a straight 22-unit diagonal instead of rounded, so the tile
          itself echoes the funnel narrowing inside it rather than being a neutral frame around it.
          The other three corners round at `r=2`, which -- unlike the rx-14 this replaces --
          finally MATCHES the sitewide `--radius-sm`/`--radius-md` (`tokens.css`, "ONE RADIUS, 2px,
          AND NO PILLS", 2026-08-08) instead of standing out against it; the previous comment's own
          reasoning ("a brand mark is allowed its own geometry, but not one that contradicts the
          system") argued for exactly this rounding value, just not for cutting a corner too.
          Authored as a path, not a rect, since a rect cannot express one straight-cut corner. */}
      <path
        d="M 2 0 L 78 0 L 100 22 L 100 98 A 2 2 0 0 1 98 100 L 2 100 A 2 2 0 0 1 0 98 L 0 2 A 2 2 0 0 1 2 0 Z"
        fill="currentColor"
      />
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
        'inline-flex items-center gap-[0.34em] whitespace-nowrap font-sans leading-none tracking-[-0.02em] text-text',
        className,
      )}
    >
      <span className="sr-only">{BRAND.name}</span>
      <BrandMark />
      {/* Two spans, not one string: weight is the only thing that differs between them (both
          stay `text-text`, no colour split), and Tailwind reads utility classes from source text,
          so `font-bold`/`font-normal` have to sit on their own elements rather than be
          interpolated. `whitespace-nowrap` + no gap between the spans keeps them reading as one
          word, exactly as `${first}${second}` did when it was a single string. */}
      <span aria-hidden="true" className="font-bold">{first}</span>
      <span aria-hidden="true" className="font-normal">{second}</span>
    </span>
  );
}

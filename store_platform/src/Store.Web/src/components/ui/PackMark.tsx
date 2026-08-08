import { markTransitionName, strata } from '@/lib/packMark';
import { cx } from '@/components/ui/cx';

/**
 * The generative per-pack mark.
 *
 * Draws `lib/packMark.ts`'s stratigraphy as an SVG in `currentColor`, so the mark takes the
 * category's ink from whatever wraps it and the twelve-hue sector scale keeps working exactly as
 * it does today. Colour therefore still means SECTOR; only the form means THIS PACK. That split
 * is deliberate -- if the mark chose its own hue from the hash, the shelf would gain 57 colours
 * and the sector scale would stop being readable at all.
 *
 * It is `aria-hidden` and carries no title. The mark identifies a pack to the EYE, for scanning;
 * it is not information, and every fact it sits beside (sector, title, sources, price) is already
 * in the text. Announcing "decorative pattern" to a screen reader 57 times is pure noise.
 */
export function PackMark({
  id,
  className,
  /**
   * Opts this mark into the shared-element morph on navigation. Only ONE element per page may
   * claim a given name, so this must be false everywhere the same pack can appear twice on one
   * screen -- the "recently viewed" rail and the shelf both render the same card, and a duplicate
   * name silently kills every view transition on the document rather than just this one.
   */
  morph = false,
  /**
   * Raises the strata out of the furniture range. OFF everywhere by default, and ON only for the
   * detail-page masthead.
   *
   * WHY THIS EXISTS. `strata()` caps opacity at 0.34 for a stated reason: on a shelf card the mark
   * sits BEHIND a title and a chip, so anything stronger competes with the text. That ceiling is
   * correct there and wrong on the detail page, where the mark sits alone on a pale tint with no
   * text over it. At 0.10-0.34 of the sector ink, on `cat.tint`, what renders is a stack of pale
   * horizontal bars of varying width -- which is the exact visual idiom of a LOADING PLACEHOLDER.
   * `components/ui/Skeleton.tsx` is that idiom, in this same UI kit: `bg-border/60`, rounded, and
   * bar-shaped. A buyer meeting that above the fold on a paid product page reads an unfinished
   * render, not an identity.
   *
   * So the fix is contrast, not geometry: the form still means THIS PACK (same seed, same bands,
   * same insets, so the shelf-to-detail morph still lands on the same shape), it is simply drawn
   * as a deliberate graphic rather than a ghost. Clamped at 0.86 so it stays ink-on-tint and never
   * goes flat black.
   */
  emphasis = false,
  /**
   * Which way the strata run. THE RULE: bands run PERPENDICULAR TO THE BOX'S LONG AXIS.
   *
   * WHY THIS EXISTS. The mark is a 0-1 viewBox with `preserveAspectRatio="none"`, so one geometry
   * is stretched into every box it lands in. Exactly ONE of the three call sites is TALL: the row
   * card's spine, measured 32x48 (`pages/index.tsx:284-292`, whose own comment says the form was
   * drawn for that orientation). There `across` is correct and the mark reads as a core sample.
   *
   * The other two are not, and the aspect ratios were MEASURED in the browser rather than read off
   * the class list -- an earlier revision of this comment claimed the lead card was tall on the
   * strength of `h-36 sm:h-44 lg:w-[34%]`, and it is not: 2.4:1 on a phone, 2.0:1 at `sm`, and
   * 305x305 at `lg` where `h-auto` lets a flex row stretch it square. The detail masthead is
   * `h-20 w-full sm:h-24`, which measures 704x96 -- a 7.3:1 box.
   *
   * Stretched into either, the bands become flat lines of RAGGED WIDTH with varying left insets
   * -- which is, precisely, the geometry of a text-line loading placeholder.
   * `components/ui/Skeleton.tsx` is that idiom in this same kit (`bg-border/60`, rounded, bar
   * shaped), so what a buyer meets above the fold on a paid product page is a ragged bar stack:
   * an unfinished render, not an identity. This was WORST on `professional-services`, which was
   * grey (#374151) until 2026-08-08 and is now olive (`styles/tokens.css:217`) -- but recolouring
   * it does not fix this and never did. The skeleton read is GEOMETRY. A coloured ragged bar
   * stack is still a ragged bar stack.
   *
   * `emphasis` was the previous attempt at this and could not have worked -- it raises opacity,
   * and opacity is not what makes the shape read as text. The fix has to be the AXIS.
   *
   * `down` transposes the same bands into columns read left to right. It is not a different mark:
   * the seed, the band count, the thicknesses and the insets are identical, so the shelf-to-detail
   * morph still lands on the same set of divisions and the identity survives the rotation. It
   * simply stops the long axis running along the bands.
   */
  axis = 'across',
}: {
  id: string;
  className?: string;
  morph?: boolean;
  emphasis?: boolean;
  axis?: 'across' | 'down';
}) {
  const bands = strata(id);

  return (
    <svg
      aria-hidden
      focusable="false"
      className={cx('pointer-events-none block h-full w-full', className)}
      /* A 0-1 viewBox with `preserveAspectRatio="none"` lets the same geometry fill a wide card
         cover and a tall detail-page rail without recomputing anything: the strata stretch, and
         stretching is what keeps the layer reading as a layer, PROVIDED the bands run across the
         box's short axis -- which is what `axis` is for. A uniform-scale fit would letterbox and
         leave dead margin. */
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      style={morph ? { viewTransitionName: markTransitionName(id) } : undefined}
    >
      {bands.map((b, i) => {
        /* A hairline gap between bands, subtracted from the THICKNESS rather than added to the
           offset, so the column still ends flush at the far edge. `Math.max` keeps a very thin
           band from going negative and disappearing entirely. */
        const thickness = Math.max(b.h - 0.006, 0.004);
        /* The transpose, and the whole of it. `down` swaps the two axes: the band's position
           along the stack (`b.y`) becomes its x, its thickness becomes its width, and its inset
           (`b.x`, capped at 22% by `strata()`) becomes an inset from the TOP -- so every column
           ends flush at y=1 exactly as every band ended flush at x=1. Same numbers, same
           divisions, one axis swap. */
        const r =
          axis === 'down'
            ? { x: b.y, y: b.x, width: thickness, height: b.w }
            : { x: b.x, y: b.y, width: b.w, height: thickness };
        return (
        <rect
          key={i}
          x={r.x}
          y={r.y}
          width={r.width}
          height={r.height}
          fill="currentColor"
          /* 2.6x lifts the 0.10-0.34 furniture range to 0.26-0.88 before the clamp, so the
             faintest band in the set still reads as drawn rather than as a gap. The multiply is
             applied here rather than in `strata()` on purpose: the geometry stays one function
             with one output, so the two renderings cannot drift into different shapes and break
             the morph. */
          opacity={emphasis ? Math.min(b.o * 2.6, 0.86) : b.o}
        />
        );
      })}
    </svg>
  );
}

export default PackMark;

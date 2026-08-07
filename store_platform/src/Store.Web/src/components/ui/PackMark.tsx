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
}: {
  id: string;
  className?: string;
  morph?: boolean;
  emphasis?: boolean;
}) {
  const bands = strata(id);

  return (
    <svg
      aria-hidden
      focusable="false"
      className={cx('pointer-events-none block h-full w-full', className)}
      /* A 0-1 viewBox with `preserveAspectRatio="none"` lets the same geometry fill a wide card
         cover and a tall detail-page rail without recomputing anything: the strata stretch, and
         because they are horizontal bands stretching is exactly the behaviour that keeps the
         layer reading as a layer. A uniform-scale fit would letterbox and leave dead margin. */
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      style={morph ? { viewTransitionName: markTransitionName(id) } : undefined}
    >
      {bands.map((b, i) => (
        <rect
          key={i}
          x={b.x}
          y={b.y}
          width={b.w}
          /* A hairline gap between bands, subtracted from the height rather than added to the
             offset, so the column still ends flush at y=1. `Math.max` keeps a very thin band from
             going negative and disappearing entirely. */
          height={Math.max(b.h - 0.006, 0.004)}
          fill="currentColor"
          /* 2.6x lifts the 0.10-0.34 furniture range to 0.26-0.88 before the clamp, so the
             faintest band in the set still reads as drawn rather than as a gap. The multiply is
             applied here rather than in `strata()` on purpose: the geometry stays one function
             with one output, so the two renderings cannot drift into different shapes and break
             the morph. */
          opacity={emphasis ? Math.min(b.o * 2.6, 0.86) : b.o}
        />
      ))}
    </svg>
  );
}

export default PackMark;

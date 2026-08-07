import { cx } from '@/components/ui/cx';

/**
 * The source count, rendered as a physical bar.
 *
 * WHAT THIS REPLACES. Every card on the shelf carried `8 documents · N sources` in mono
 * (`pages/index.tsx:351` before this pass). The document half is the same on all 57 cards --
 * `PACK_CONTENTS.length` is a constant -- so it is zero-information ink repeated 57 times, and
 * because it sits FIRST it is what the eye reads first on every card. Counted in the served HTML
 * on 2026-08-07: 61 occurrences of `8 documents` on one page. The only number on that line that
 * varies between packs is the source count, and it was the half printed second, in the same size
 * and colour as the constant beside it.
 *
 * WHY TICKS AND NOT A PROPORTIONAL BAR. A proportional fill (`width: count/max`) is comparable
 * across cards but not countable, and it needs a `max` -- which is a property of whatever happens
 * to be on the shelf today, so the same pack would render a different bar as the catalogue grew.
 * That is a bar that changes without the product changing. One tick per source is countable AND
 * comparable (more sources is literally a longer run), and it is stable forever because it
 * depends on nothing but the pack.
 *
 * The number stays printed beside it. The bar is for scanning a grid; the digits are for anyone
 * who actually wants to know, and a chart without its figure is decoration.
 */
export function EvidenceBar({
  count,
  className,
  /**
   * Ticks stop being individually countable somewhere around forty and start being a texture.
   * Past the cap the run is drawn at full width and the numeral carries the exact value, so no
   * information is lost -- the bar just stops claiming to be countable when it no longer is.
   */
  cap = 40,
  label = true,
}: {
  count?: number | null;
  className?: string;
  cap?: number;
  label?: boolean;
}) {
  // A pack with no source count renders NOTHING, not a zero and not an empty track. An empty
  // evidence bar on a product whose pitch is evidence is the single worst thing this component
  // could draw: it says "we checked and found none", when the truth is "this field is absent".
  if (typeof count !== 'number' || count <= 0) return null;

  const shown = Math.min(count, cap);
  const over = count > cap;

  return (
    <span
      className={cx('inline-flex items-center gap-2', className)}
      /* One accessible name for the whole widget. Without this a screen reader announces forty
         empty <span>s and then a number. `aria-hidden` on the track is the other half. */
      role="img"
      aria-label={`${count} cited ${count === 1 ? 'source' : 'sources'}`}
    >
      <span aria-hidden className="flex items-end gap-px" style={{ height: 12 }}>
        {Array.from({ length: shown }, (_, i) => (
          <span
            key={i}
            className="w-px bg-survive"
            style={{
              /* Height walks a fixed 5-step cycle rather than a random one. A flat run of equal
                 ticks reads as a progress bar (i.e. "43 of 100"), which is a claim we are not
                 making; a varying skyline reads as a measurement. It is deterministic in the
                 INDEX, not in the pack, so it costs no seed and two packs with the same count
                 draw the same shape -- which is correct, because the same count IS the same fact. */
              height: [12, 7, 10, 5, 9][i % 5],
              /* The run fades toward its tail so a 40-tick bar does not out-shout a 12-tick one
                 purely by ink volume. The first ticks are the ones being compared. */
              opacity: 0.35 + 0.65 * (1 - i / Math.max(shown, 1)),
            }}
          />
        ))}
        {over && <span className="ml-0.5 w-px bg-survive/40" style={{ height: 12 }} />}
      </span>
      {label && (
        <span className="font-mono text-caption tabular-nums text-subtle">
          {count} sources
        </span>
      )}
    </span>
  );
}

export default EvidenceBar;

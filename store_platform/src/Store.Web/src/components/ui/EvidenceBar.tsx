import { cx } from '@/components/ui/cx';
import { EVIDENCE_TICK_CAP, evidenceLabel, evidenceRun } from '@/lib/evidenceTicks';

/**
 * The source count, rendered as a physical bar.
 *
 * THE SHAPE IS NO LONGER DECIDED HERE (2026-08-15). Tick count, the height cycle and the tail fade
 * moved to `lib/evidenceTicks.ts` because the link-preview card draws the same run through satori,
 * which shares no renderer with this file. This component now owns only its units (px, Tailwind
 * tokens) and its DOM. The reasoning behind each of those three decisions travelled with them --
 * read it there, not here.
 *
 * WHAT THIS REPLACES. Every card on the shelf carried `8 documents · N sources` in mono
 * (`pages/index.tsx:351` before this pass). The document half is the same on all 57 cards --
 * `PACK_DOCUMENTS.length` is a constant -- so it is zero-information ink repeated 57 times, and
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
  /** See `EVIDENCE_TICK_CAP` for why forty. */
  cap = EVIDENCE_TICK_CAP,
  label = true,
  /**
   * `instrument` is the same bar drawn for the dark cover plate (`--ins-bg`), and it exists
   * because the light one is UNREADABLE there, not because it looked nicer: `--survive` (#047857)
   * measures 1.9:1 on #0B0D0F. tokens.css states the rule this obeys -- survivors on the
   * instrument surface carry no hue, they are simply lit -- so the ticks become `--ins-survive`
   * (#FAFAFA, 18.65:1) and the label `--ins-muted` (#8A9099, 6.14:1).
   */
  tone = 'default',
  /**
   * `lg` is the cover-plate size: the run is the only artwork on the card, so it is drawn at a
   * size the eye reads as an object rather than as a footnote beside a number.
   */
  size = 'sm',
}: {
  count?: number | null;
  className?: string;
  cap?: number;
  label?: boolean;
  tone?: 'default' | 'instrument';
  size?: 'sm' | 'lg';
}) {
  // The two sizes are the SAME shape scaled, not two drawings: the 5-step height cycle is
  // multiplied by `track`, so a 26-source pack draws a recognisably identical skyline in the body,
  // on the cover, and on the link-preview card. `track` is the tallest step in each, which is what
  // the flex row is sized to.
  const lg = size === 'lg';
  const track = lg ? 22 : 12;

  const { ticks, over, shown } = evidenceRun(count, { cap, track });

  // A pack with no source count renders NOTHING, not a zero and not an empty track. An empty
  // evidence bar on a product whose pitch is evidence is the single worst thing this component
  // could draw: it says "we checked and found none", when the truth is "this field is absent".
  if (shown === 0 || typeof count !== 'number') return null;
  const tick = lg ? 'w-0.5' : 'w-px';
  const gap = lg ? 'gap-[1.5px]' : 'gap-px';
  const ink = tone === 'instrument' ? 'bg-ins-survive' : 'bg-survive';
  const labelInk = tone === 'instrument' ? 'text-ins-muted' : 'text-subtle';

  return (
    <span
      /* `min-w-0 max-w-full shrink overflow-hidden` is a HARD promise to whatever contains
         this: the tick run is a fixed intrinsic width (one `w-px` span per source plus a gap,
         so ~79px at the default cap) and until 2026-08-14 nothing stopped it pushing past its
         container. On a 390px phone the row card's bar ran past the card's right padding to
         the viewport edge and was clipped there. A component that can overflow its parent has
         to be caught at every call site or at none, so it is caught here. */
      className={cx('inline-flex min-w-0 max-w-full shrink items-center gap-2 overflow-hidden', className)}
      /* One accessible name for the whole widget. Without this a screen reader announces forty
         empty <span>s and then a number. `aria-hidden` on the track is the other half. */
      role="img"
      aria-label={evidenceLabel(count)}
    >
      {/* The drawing's `.spark` (`mockups/index.html:390`): the run of bars, bottom-aligned. */}
      <span aria-hidden className={cx('spark flex items-end', gap)} style={{ height: track }}>
        {ticks.map((t, i) => (
          <span key={i} className={cx(tick, ink)} style={{ height: t.height, opacity: t.opacity }} />
        ))}
        {over && (
          <span className={cx('ml-0.5 opacity-40', tick, ink)} style={{ height: track }} />
        )}
      </span>
      {label && (
        <span className={cx('font-mono text-caption tabular-nums', labelInk)}>
          {count} sources
        </span>
      )}
    </span>
  );
}

export default EvidenceBar;

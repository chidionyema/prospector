import { cx } from '@/components/ui/cx';
import { EVIDENCE_TICK_CAP, evidenceLabel, evidenceRun } from '@/lib/evidenceTicks';

/**
 * The source count, rendered as the drawing's `.spark-row`.
 *
 * THE MARKUP IS THE DRAWING'S, NOT OURS (2026-08-18, parity step 2). The bundle's featured card
 * writes exactly this:
 *
 *   <div class="spark-row">
 *     <div class="spark" aria-hidden="true"><i style="height:40%"></i>...</div>
 *     <span class="mono num">30 sources</span>
 *   </div>
 *
 * This component used to draw the same idea with a wrapper span, `span` ticks, and Tailwind
 * utilities for width, gap, height and colour. Every one of those utilities OUTRANKS the
 * stylesheet -- globals.css:8 imports mumchimp.css into `layer(components)` -- so `.spark`
 * (mumchimp.css:337) and `.spark i` (:338) were inert on the only page that used them. The bar
 * width, its 28px track and the brand fill now come from the stylesheet, and the only inline
 * style left is the per-tick height, which is data.
 *
 * The `size` and `tone` props are gone with them. `size` picked between a 22px and a 12px track;
 * the stylesheet declares one track, and a second size is a style that does not exist in it.
 * `tone="instrument"` repainted the run for the dark cover plate, and the cover plate has not
 * rendered through this component since 2026-08-15 -- it draws through satori from
 * `lib/evidenceTicks.ts`, which shares no renderer with this file.
 *
 * THE SHAPE IS NOT DECIDED HERE. Tick count, the height cycle and the tail fade live in
 * `lib/evidenceTicks.ts` for that same reason: two renderers, one run. Read the reasoning there.
 *
 * WHY TICKS AND NOT A PROPORTIONAL BAR. A proportional fill (`width: count/max`) is comparable
 * across cards but not countable, and it needs a `max` -- which is a property of whatever happens
 * to be on the shelf today, so the same pack would render a different bar as the catalogue grew.
 * One tick per source is countable AND comparable, and it depends on nothing but the pack.
 *
 * The number stays printed beside it. The bar is for scanning; the digits are for anyone who
 * actually wants to know, and a chart without its figure is decoration.
 */
export function EvidenceBar({
  count,
  className,
  /** See `EVIDENCE_TICK_CAP` for why forty. */
  cap = EVIDENCE_TICK_CAP,
  label = true,
}: {
  count?: number | null;
  className?: string;
  cap?: number;
  label?: boolean;
}) {
  /* The track the height cycle is measured against. `.spark` is `height:28px` (mumchimp.css:337),
     and the ticks are drawn as a percentage of it, exactly as the drawing writes them, so the
     stylesheet stays the one place the size is declared. */
  const TRACK = 28;
  const { ticks, over, shown } = evidenceRun(count, { cap, track: TRACK });

  // A pack with no source count renders NOTHING, not a zero and not an empty track. An empty
  // evidence bar on a product whose pitch is evidence is the single worst thing this component
  // could draw: it says "we checked and found none", when the truth is "this field is absent".
  if (shown === 0 || typeof count !== 'number') return null;
  const pct = (h: number) => `${Math.round((h / TRACK) * 100)}%`;

  return (
    <div
      className={cx('spark-row', className)}
      /* One accessible name for the whole widget. Without this a screen reader announces forty
         empty elements and then a number. `aria-hidden` on the track is the other half. */
      role="img"
      aria-label={evidenceLabel(count)}
    >
      <div aria-hidden className="spark">
        {ticks.map((t, i) => (
          <i key={i} style={{ height: pct(t.height), opacity: t.opacity }} />
        ))}
        {over && <i style={{ height: '100%', opacity: 0.4 }} />}
      </div>
      {label && <span className="mono num">{count} sources</span>}
    </div>
  );
}

export default EvidenceBar;

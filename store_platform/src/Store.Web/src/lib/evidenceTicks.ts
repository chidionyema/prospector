/**
 * THE CITED-SOURCE RUN, as geometry rather than as markup.
 *
 * WHY THIS IS A MODULE AND NOT A SECOND COPY. The run is drawn on two surfaces that share no
 * renderer: the shelf card draws it as DOM (`components/ui/EvidenceBar.tsx`) and the link-preview
 * card draws it through satori (`pages/og/pack/[id].tsx`), which rasterises a React tree to PNG and
 * supports only a subset of CSS. Two renderers is exactly the condition under which one drawing
 * becomes two drawings: `PackCardHeader`'s note records the same shape of failure happening to a
 * card header ("it was four hand-rolled headers in three files, and that is the whole reason the
 * shelf looked like two different shops"). A pack whose share card and shelf card disagree about
 * its own evidence is worse than either alone, because the two are compared side by side the moment
 * anyone posts a link.
 *
 * So the SHAPE lives here -- how many ticks, how tall each one, how faded -- and each surface owns
 * only its own units and its own way of emitting a rectangle.
 *
 * THE THREE DECISIONS ENCODED HERE, all of them inherited from `EvidenceBar` where they were made
 * and argued:
 *
 *  - ONE TICK PER SOURCE, not a proportional fill. A `width: count/max` bar is comparable across
 *    cards but not countable, and it needs a `max` -- a property of whatever happens to be on the
 *    shelf today, so the same pack would draw a different bar as the catalogue grew. That is a bar
 *    that changes without the product changing.
 *  - A FIXED 5-STEP HEIGHT CYCLE, indexed by position and not by the pack. A flat run of equal
 *    ticks reads as a progress bar ("43 of 100"), a claim this shop is not making; a varying
 *    skyline reads as a measurement. Keying it to the INDEX rather than to the pack costs no seed
 *    and means two packs with the same count draw the same shape -- which is correct, because the
 *    same count IS the same fact. It is also the determinism rule the deleted `PackCoverArt` cover
 *    carried, kept: the drawing is a function of the pack and nothing else.
 *  - A FADE TOWARD THE TAIL, so a 40-tick run does not out-shout a 12-tick one purely by ink
 *    volume. The first ticks are the ones being compared.
 */

/** One rectangle. `height` is in the caller's units (whatever `track` was given in); `opacity` is
 *  unitless and applies identically in DOM and in satori. */
export interface EvidenceTick {
  height: number;
  opacity: number;
}

export interface EvidenceRun {
  ticks: EvidenceTick[];
  /** True when `count` exceeded `cap`, i.e. the run is a truncation and the caller should draw the
   *  overflow marker. The exact figure is never lost -- it is printed as digits beside the run. */
  over: boolean;
  /** `min(count, cap)` -- how many ticks `ticks` actually holds. */
  shown: number;
}

/**
 * Ticks stop being individually countable somewhere around forty and start being a texture. Past
 * this the run is drawn at full width and the numeral carries the exact value, so no information is
 * lost -- the bar just stops claiming to be countable when it no longer is.
 *
 * Live range measured over the catalogue on 2026-08-14: 17-51 sources across 62 of 62 packs. So the
 * cap is inside the live range and the overflow marker is a real state, not a defensive branch.
 */
export const EVIDENCE_TICK_CAP = 40;

/** The height cycle, as twelfths of the track. Twelve is the shelf card's small track in px, which
 *  is why the numbers read as pixels -- they are a ratio, and every surface scales them. */
const HEIGHT_CYCLE = [12, 7, 10, 5, 9];

/**
 * Returns nothing to draw (`shown: 0`) for a pack with no source count.
 *
 * A pack with no source count must render NOTHING, not a zero and not an empty track. An empty
 * evidence bar on a product whose pitch is evidence is the single worst thing this drawing could
 * do: it says "we checked and found none", when the truth is "this field is absent". Callers check
 * `shown` and emit no container at all. No live pack is in this state; the branch exists so that
 * one never can be.
 */
export function evidenceRun(
  count: number | null | undefined,
  { cap = EVIDENCE_TICK_CAP, track = 12 }: { cap?: number; track?: number } = {},
): EvidenceRun {
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) {
    return { ticks: [], over: false, shown: 0 };
  }

  const shown = Math.min(Math.floor(count), cap);
  const ticks = Array.from({ length: shown }, (_, i) => ({
    height: (HEIGHT_CYCLE[i % HEIGHT_CYCLE.length] / 12) * track,
    opacity: 0.35 + 0.65 * (1 - i / Math.max(shown, 1)),
  }));

  return { ticks, over: count > cap, shown };
}

/** The run's accessible name, and the alt text of the PNG card. One name for the whole widget:
 *  without it a screen reader announces forty empty elements and then a number. */
export function evidenceLabel(count: number): string {
  return `${count} cited ${count === 1 ? 'source' : 'sources'}`;
}

import { useMemo } from 'react';

import { RESEARCH_STATS } from '@/lib/stats';
import { cx } from '@/components/ui/cx';
import { tightDecimal } from '@/components/ui/Money';

/**
 * Every idea the engine has researched, one mark each, with the packs on the shelf standing out
 * of the stubble.
 *
 * WHAT THIS REPLACES, AND WHY
 * ---------------------------
 * `AmbientKillColumn` was this same intent attempted as a right-hand column of drifting
 * struck-through names, and at the only breakpoint it rendered (`lg:`) it could not work.
 * Measured at a 1280px viewport: the hero is `lg:grid-cols-[1fr_420px]`, the column is
 * `right-0 w-[42%]` so it begins at x=822, and the opaque 420px featured card begins at x=940.
 * The column's own mask (`linear-gradient(to right, transparent, #000 55%)`) does not reach full
 * opacity until x=1118 -- 178px BEHIND the card. So the only part of it a visitor ever saw was
 * ~117px of the lowest-opacity fade, hard-clipped mid-word: "Appeal-E", "Brief-Wi". There is no
 * free horizontal band beside the featured card, so no mask tweak could have fixed it; the
 * component needed the full width it never had. This is that component's idea, given the width,
 * as a band under the hero rather than a layer behind it.
 *
 * THE LEGEND REFUSES TO STATE A PARTITION, DELIBERATELY
 * -----------------------------------------------------
 * The obvious caption -- lit marks survived, dim marks were killed -- is false, and false in the
 * exact way this site has already shipped once (c8e6ed0, "the home page asserted a partition that
 * did not close"). 1,364 were killed and 50 are on the shelf, and those do not sum to 1,444,
 * because an idea that cleared the gates but is not packaged yet belongs to neither group. So a
 * dim mark says "researched, not listed", which is true of every one of them, and the band prints
 * exactly one figure: the total, as the scale label of the picture it labels. The kill count is
 * stated in prose by the proof strip below, once. The survivor count is forbidden outright and
 * `lib/stats.ts` no longer exports it, so no surface can print it by accident.
 */

/** One mark per idea, at a 1.5px mark on a 1.5px gutter. Layout lives in `globals.css .pop-field`. */
const PITCH_CLASS = 'pop-field';

/**
 * The indices that are lit, spread evenly through the population and then jittered.
 *
 * Evenly-spaced survivors land in the same column of every row and print as diagonal banding --
 * an artefact of the grid, not anything in the data. So each lit mark is displaced inside its own
 * bucket by a seeded LCG: no `Math.random` and no `Date`, so the server and the client render
 * byte-identical HTML and hydration is clean, and the field is the same on every load.
 */
function litIndices(total: number, lit: number): number[] {
  if (total <= 0 || lit <= 0) return [];
  const bucket = total / lit;
  const out: number[] = [];
  let seed = 1444;
  for (let i = 0; i < lit; i += 1) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    out.push(Math.min(total - 1, Math.floor(i * bucket + (seed / 0x7fffffff) * bucket)));
  }
  return out;
}

/** How long the resolve takes to cross the whole field, in seconds. See `popRise` in globals.css. */
const SWEEP_S = 0.9;

/**
 * The marks, as one HTML string rather than 1,444 React elements.
 *
 * MEASURED, not assumed. React 19.2.7, production build, 1,444 nodes with 50 carrying a style
 * attribute: `renderToStaticMarkup` costs 17-98ms per render (median ~37ms over 5 warm runs) to
 * produce 11.6 KB. As a single string set through `dangerouslySetInnerHTML` the same bytes cost
 * one node -- React neither serialises the children on the server nor reconciles them on the
 * client, so the field also disappears from hydration entirely. That matters here specifically
 * because this sits on the page whose LCP budget is documented and defended all over
 * `pages/index.tsx`; 37ms of server time and 1,444 hydration nodes for a static picture is a bill
 * this screen does not have to pay.
 *
 * SAFE BY CONSTRUCTION, not by review. The only inputs are two integers, and every byte emitted
 * below is a literal in this function -- there is no interpolation of any string from any source.
 * Two numbers cannot express markup.
 */
function marksHtml(total: number, lit: number): string {
  const delays = new Map<number, string>();
  for (const i of litIndices(total, lit)) {
    delays.set(i, `${((i / total) * SWEEP_S).toFixed(2)}s`);
  }
  let html = '';
  for (let i = 0; i < total; i += 1) {
    const d = delays.get(i);
    html += d === undefined ? '<i></i>' : `<i class="on" style="--d:${d}"></i>`;
  }
  return html;
}

export function PopulationField({
  shelfCount,
  className,
}: {
  shelfCount: number;
  className?: string;
}) {
  const total = RESEARCH_STATS.researched;

  // Only the ~50 lit marks carry a style attribute; the ~1,394 dim ones serialise as a bare
  // `<i></i>`, which is the payload argument in globals.css. The delay is a fraction of the sweep,
  // so the survivors stand up left to right across the field, in the order the eye already travels.
  const html = useMemo(() => marksHtml(total, shelfCount), [total, shelfCount]);

  // `shelfCount` is read from the live catalogue at request time, so it is the one input here that
  // can change without a redeploy. Zero means that call failed; a field with nothing standing in it
  // would state something false about the shop, so the band does not render at all.
  if (shelfCount <= 0) return null;

  return (
    <div className={cx('border-t border-border pt-4', className)}>
      <div className="mb-3 flex items-baseline justify-between gap-6">
        {/* "these same checks" is the bridge sentence that used to close `HeroEvidenceStrip`
            directly above: that component shows ONE pack's eight verdicts, and this shows every
            idea they have ever been run against. The two only mean something adjacent, which is
            what they now are. */}
        <p className="text-caption text-subtle">Every idea put through these same checks, one mark each</p>
        {/* `tightDecimal` closes the thousands mark. In the house mono face every glyph gets the
            same advance, so the comma sat in a full cell and the total rendered `1 , 444` -- three
            tokens where the reader is being handed one figure. See its note in `ui/Money.tsx`. */}
        <p className="font-mono text-caption tabular-nums text-muted">
          {tightDecimal(total.toLocaleString('en-GB'))}
        </p>
      </div>

      {/* `role="img"` with one label, rather than 1,444 announced children: a screen reader must
          get the FACT the field expresses in a sentence, not walk a picket fence. The marks are
          presentational, so the container's label is the entire accessible content. */}
      <div
        className={PITCH_CLASS}
        role="img"
        aria-label={`${total.toLocaleString('en-GB')} ideas researched. ${RESEARCH_STATS.killed.toLocaleString('en-GB')} were killed on cited evidence. The tall marks are the packs on the shelf now.`}
        /* eslint-disable-next-line react/no-danger -- `marksHtml` takes two integers and emits
           only literals; see the measurement and the safety argument on that function. */
        dangerouslySetInnerHTML={{ __html: html }}
      />

      {/* THE LEGEND NAMES THE TWO MARKS AND COUNTS NEITHER, and that is a fix, not an omission.
          The first version of this line read "1,364 killed, every one with a cited reason" over a
          link to /kill-log -- which is, word for word and link for link, the last line of
          `HeroEvidenceStrip` 100px above it and the proof strip 300px below it. Three statements
          of the same number inside 450px of one screen is how a page that sells checked figures
          reads as though it cannot keep track of its own. The picture is what this band adds; the
          arithmetic is stated once, in prose, in the strip that already owns it. */}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-caption text-subtle">
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-[11px] w-[1.5px] bg-survive" />
          On the shelf now
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-[3px] w-[1.5px] bg-faint" />
          Researched, not listed
        </span>
      </div>
    </div>
  );
}

export default PopulationField;

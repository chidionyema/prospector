import React from 'react';

import { cx } from '@/components/ui/cx';
import { RESEARCH_STATS } from '@/lib/stats';
import type { GateBar } from '@/lib/killLog.server';

/**
 * THE CAUSE-COLOURED GRID (MASTER-BRIEF §7 `/kill-log`): every idea we researched, one cell each,
 * shaded by which check killed it.
 *
 * IT IS A RED RAMP, NOT A CATEGORICAL PALETTE, AND §2 IS WHY. "Colour is a contract": three
 * colours carry meaning site-wide -- teal survived, amber pushed back, red killed -- and red is
 * reserved so hard that the brief says using it where nothing died is a bug. Giving each cause its
 * own hue would put six or eight new meanings into a system a reader has learned has three, and the
 * first one that landed near teal or amber would read as a verdict it is not. So every kill cell is
 * red and the CAUSE is carried by strength: the commonest cause is the strongest red, and the ramp
 * steps down from there. The picture still answers the question the page exists to answer -- what
 * kills ideas most often -- and it answers it in the one colour that already means killed.
 *
 * ONE PATH PER CAUSE, NOT 1,444 NODES. Same discipline as `KillGrid`: the cells of a cause are a
 * single `<path>` of subpaths, so a grid of 1,444 cells is nine or ten DOM nodes. Zero client JS,
 * server-rendered, and the whole thing is `aria-hidden` behind a `<desc>` -- a screen reader gets
 * the sentence, not fourteen hundred unlabelled rectangles.
 *
 * THE ORDER IS FIXED AND MEANS SOMETHING. Causes descend by count, so the grid reads as a ranking
 * top to bottom before anyone reads the legend. Survivors are last, in teal, in the bottom-right
 * corner, for the same reason they are last in `KillGrid`: the eye crosses the whole field of dead
 * ideas before it reaches the ones that got through, which is the argument.
 *
 * IT PRINTS NO SURVIVOR COUNT. The teal block is drawn from `researched - killed` because that is
 * what is left when the kills are laid down, but no number is rendered for it and the legend names
 * it in words. Founder directive 2026-08-13, `lib/stats.ts`: the survivor count is not printed
 * anywhere, and a picture is not an exemption.
 */

/** Full strength first: the commonest cause is the strongest red.
 *
 *  WRITTEN OUT, NEVER BUILT WITH A TEMPLATE. Tailwind v4 scans source text for class names, so
 *  `fill-kill/${n}` produces no rule at all and the cells render invisible -- the same silent
 *  failure mode as an unmapped colour utility. These are literals so the scanner can see them. */
const RAMP = [
  'fill-kill',
  'fill-kill/85',
  'fill-kill/70',
  'fill-kill/60',
  'fill-kill/50',
  'fill-kill/40',
  'fill-kill/30',
  'fill-kill/25',
  'fill-kill/20',
] as const;

/** Anything past the ramp shares its last step rather than fading to nothing. A cause drawn at 0%
 *  opacity is a cause the picture claims does not exist. */
const TAIL = RAMP[RAMP.length - 1];

/** The side of the square field, derived from the population rather than typed. 38 x 38 = 1,444. */
function sideFor(total: number): number {
  return Math.ceil(Math.sqrt(total));
}

/** A cell's rectangle, `mark` wide, at the index's position in a `side`-wide field. */
function cell(index: number, side: number, mark: number): string {
  const x = (index % side) + (1 - mark) / 2;
  const y = Math.floor(index / side) + (1 - mark) / 2;
  return `M${x.toFixed(3)} ${y.toFixed(3)}h${mark}v${mark}h-${mark}z`;
}

/** One path covering `count` cells starting at `from`. Empty string for an empty run. */
export function runPath(from: number, count: number, side: number, mark: number): string {
  let d = '';
  for (let i = from; i < from + count; i += 1) d += cell(i, side, mark);
  return d;
}

/** 2:1 mark-to-pitch, the duty cycle that reads as a field of separate marks rather than a wash. */
const MARK = 0.66;

export interface CauseGridProps {
  /** Every cause with its FULL count, published or not. `KillIndex.distribution`. */
  distribution: readonly GateBar[];
  className?: string;
}

export function CauseGrid({ distribution, className }: CauseGridProps) {
  const { killed, researched } = RESEARCH_STATS;

  /* Descending by count, and ties broken by label so the picture is identical between visits. A
     signature that reshuffles is not a signature. */
  const causes = [...distribution]
    .filter((bar) => bar.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const counted = causes.reduce((sum, bar) => sum + bar.count, 0);

  /* The kills the distribution does not account for. `make_kill_log.py` drops kills whose only
     reason is a composite score below the bar, so this is normally a real number and not a bug --
     but it is drawn, because a grid that quietly omits it would show a smaller field than the
     count printed beside it. */
  const unattributed = Math.max(0, killed - counted);

  /* Never trust the arithmetic to be non-negative: if a regeneration ever put more kills in the
     distribution than `killed`, the grid would run off the end of the field rather than say so. */
  const total = Math.max(researched, counted + unattributed);
  const side = sideFor(total);
  const survivors = Math.max(0, total - counted - unattributed);

  /* THE FIELD IS THE DRAWING'S `.causegrid` (`mockups/kill-log.html:250-251`): a 44-column grid
     of square marks, one per idea, gap 1.5px, each mark `aspect-ratio:1` so the block sizes itself
     from the column width. It was an SVG of packed run paths in a 38x38 square, which is a
     different object on the page -- a square wash rather than a wide band of countable marks --
     and no amount of CSS on the SVG would have made it the drawn one. */
  const marks: string[] = [];
  causes.forEach((bar, i) => {
    const paint = (RAMP[i] ?? TAIL).replace('fill-', 'bg-');
    for (let k = 0; k < bar.count; k += 1) marks.push(paint);
  });
  for (let k = 0; k < unattributed; k += 1) marks.push('bg-faint');
  for (let k = 0; k < survivors; k += 1) marks.push('bg-survive');

  if (causes.length === 0) return null;

  return (
    <figure className={cx('sigcard', className)}>
      <div
        className="causegrid"
        role="img"
        aria-label={`Every idea we researched, one mark each, shaded by the check that killed it. Each of the ${researched.toLocaleString('en-GB')} marks is one idea; the strongest red is the commonest cause of death, and the teal block is what got through.`}
      >
        {marks.map((paint, i) => (
          <i key={i} className={paint} />
        ))}
      </div>

      {/* The legend is the key AND the ranking. Counts are the kill counts this page already
          publishes; the teal block carries no number, per the 2026-08-13 directive.
          `.legend` and `.swb` (`mockups/kill-log.html:252-253`) own the layout, the mono face and
          the rule above; the utilities that used to set those here are removed rather than
          layered, since mumchimp.css sits under the utility layer (globals.css:8). */}
      <div className="legend">
        {causes.map((bar, i) => (
          <span key={bar.gate}>
            <i aria-hidden className={cx('swb', (RAMP[i] ?? TAIL).replace('fill-', 'bg-'))} />
            <b className="tabular-nums">{bar.count.toLocaleString('en-GB')}</b> {bar.label}
          </span>
        ))}
        {unattributed > 0 && (
          <span>
            <i aria-hidden className="swb bg-faint" />
            <b className="tabular-nums">{unattributed.toLocaleString('en-GB')}</b> Killed on score alone
          </span>
        )}
        <span>
          <i aria-hidden className="swb bg-survive" />
          Came through the filter
        </span>
      </div>
    </figure>
  );
}

export default CauseGrid;

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

  let cursor = 0;
  const paths: React.ReactElement[] = [];

  causes.forEach((bar, i) => {
    paths.push(
      <path
        key={bar.gate}
        d={runPath(cursor, bar.count, side, MARK)}
        className={RAMP[i] ?? TAIL}
        aria-hidden="true"
      />,
    );
    cursor += bar.count;
  });

  if (unattributed > 0) {
    paths.push(
      <path
        key="__unattributed"
        d={runPath(cursor, unattributed, side, MARK)}
        className="fill-faint"
        aria-hidden="true"
      />,
    );
    cursor += unattributed;
  }

  if (survivors > 0) {
    paths.push(
      <path
        key="__survived"
        d={runPath(cursor, survivors, side, MARK)}
        className="fill-survive"
        aria-hidden="true"
      />,
    );
  }

  if (causes.length === 0) return null;

  return (
    <figure className={cx('rounded-card border border-line bg-surface p-4', className)}>
      <svg
        viewBox={`0 0 ${side} ${side}`}
        className="block w-full"
        shapeRendering="crispEdges"
        role="img"
        aria-label={`Every idea we researched, one cell each, shaded by the check that killed it.`}
      >
        <desc>
          {`Each of the ${researched.toLocaleString('en-GB')} cells is one idea. Red cells were killed on cited evidence, `}
          {`the strongest red being the commonest cause of death. The teal block is what got through.`}
        </desc>
        {paths}
      </svg>

      {/* The legend is the key AND the ranking. Counts are the kill counts this page already
          publishes; the teal block carries no number, per the 2026-08-13 directive. */}
      <ul className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1 font-mono text-caption text-subtle sm:grid-cols-2">
        {causes.map((bar, i) => (
          <li key={bar.gate} className="flex items-center gap-2">
            <span aria-hidden className={cx('inline-block size-[9px] rounded-sm', (RAMP[i] ?? TAIL).replace('fill-', 'bg-'))} />
            <span className="truncate">{bar.label}</span>
            <span className="ml-auto tabular-nums text-muted">{bar.count.toLocaleString('en-GB')}</span>
          </li>
        ))}
        {unattributed > 0 && (
          <li className="flex items-center gap-2">
            <span aria-hidden className="inline-block size-[9px] rounded-sm bg-faint" />
            <span className="truncate">Killed on score alone</span>
            <span className="ml-auto tabular-nums text-muted">{unattributed.toLocaleString('en-GB')}</span>
          </li>
        )}
        <li className="flex items-center gap-2">
          <span aria-hidden className="inline-block size-[9px] rounded-sm bg-survive" />
          <span className="truncate">Came through the filter</span>
        </li>
      </ul>
    </figure>
  );
}

export default CauseGrid;

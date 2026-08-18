import { RESEARCH_STATS } from '@/lib/stats';
import type { Pack } from '@/lib/api/client';
import { cx } from '@/components/ui/cx';
import { tightDecimal } from '@/components/ui/Money';

/**
 * THE KILL GRID (MASTER-BRIEF §7). The home page's signature device, in the hero.
 *
 * Every idea the engine has researched, one square each, in the order they were researched. The
 * packs on the shelf are the teal squares, and each one is a link to the pack it is.
 *
 * WHAT IT REPLACES, AND WHAT IT KEEPS. `PopulationField` was this same intent as a band UNDER the
 * hero, and it got the picture right: one mark per idea, the shelf standing out, and a legend that
 * refuses to state a partition. Two things it could not do. Its lit marks were positions chosen by
 * a seeded generator, so no mark WAS a pack -- a reader who noticed one had nothing to click and
 * nothing to read. And it emitted 1,444 `<i>` elements through `dangerouslySetInnerHTML`: one
 * node, but 11.6 KB of markup that says nothing about the data, and heavy enough that it had to be
 * placed after the hero in DOM order to keep it off the LCP path.
 *
 * THAT PLACEMENT ARGUMENT IS WHAT DISSOLVES HERE, which is why this can sit in the hero at all.
 * The whole field is ONE `<path>` plus one `<rect>` per listed pack -- around fifty nodes, not
 * fourteen hundred -- so there is no layout cost to defer. Zero client JS: no state, no effect, no
 * hydration. The survivor links are plain SVG `<a>` elements, so navigation is the browser's
 * rather than the router's, and the picture is complete in the first HTML byte.
 *
 * WHAT THE POSITIONS MEAN, AND WHAT THEY DO NOT. The survivors appear in the order they were
 * researched, oldest first, reading left to right and top to bottom. That is a true claim and it
 * is the only claim the picture makes. A cell's position does NOT encode a date: we know each
 * survivor's `verifiedAt`, and we do not know the dates of the 1,394 ideas that are not on the
 * shelf, so spacing survivors by date would mean inventing a distribution for everything around
 * them. Rank k of the survivors sits in bucket k of the field. Nothing in the caption, the legend
 * or the titles says otherwise.
 *
 * THE LEGEND NAMES THE TWO SQUARES AND COUNTS NEITHER, AND THAT IS A DELIBERATE DEPARTURE FROM THE
 * MOCKUP. `mockups/index.html:296` prints "1,364 killed / 68 survived" under the grid. The second
 * of those figures cannot ship. The founder's directive of 2026-08-13 is that the survivor count
 * is never printed -- "saying 80 when only 50 are listed should never happen regardless of the
 * reasons why survivors are unlisted" -- and `lib/stats.ts` enforces it by not exporting the
 * number at all, so this component could not print it without a new export and a new argument.
 * The two figures also do not partition the total: killed plus listed is short of researched,
 * because an idea that cleared the gates and is not packaged yet belongs to neither group. So the
 * only figure printed is the total, as the scale label of the picture it labels, and the kill
 * total stays in the proof strip that already owns it.
 */

/** One cell is 1 unit. Both marks are centred in their cell, so the gutter is even on all sides. */
const DEAD_SIDE = 0.66;
const LIVE_SIDE = 0.86;

/**
 * The dead cells as ONE path, which is the whole payload argument.
 *
 * 1,394 subpaths at ~18 characters each is ~25 KB of `d` attribute. It is also the most repetitive
 * 25 KB on the page -- the same handful of glyphs in the same order 1,394 times -- so it
 * compresses to a small fraction of that over the wire, and it costs the client ONE DOM node and
 * zero reconciliation. The alternatives were worse in ways that matter: 1,394 `<rect>` elements is
 * 1,394 nodes, which is the cost this device exists to avoid, and a `<pattern>` fill is smaller
 * still but cannot leave holes where the survivors are, so a teal square would sit ON a grey one
 * rather than instead of it.
 *
 * SAFE BY CONSTRUCTION. The inputs are two integers and a set of integers, and every byte emitted
 * is a literal in this function. Numbers cannot express markup.
 */
function deadPath(total: number, side: number, live: ReadonlySet<number>): string {
  const inset = (1 - DEAD_SIDE) / 2;
  let d = '';
  for (let i = 0; i < total; i += 1) {
    if (live.has(i)) continue;
    const col = (i % side) + inset;
    const row = Math.floor(i / side) + inset;
    d += `M${col} ${row}h${DEAD_SIDE}v${DEAD_SIDE}h-${DEAD_SIDE}z`;
  }
  return d;
}

export interface KillGridProps {
  /** The shelf, exactly as the page received it. Sorted here, never mutated. */
  packs: Pack[];
  className?: string;
}

export function KillGrid({ packs, className }: KillGridProps) {
  const total = RESEARCH_STATS.researched;

  // A live catalogue read that came back empty is an outage, not an empty shop. A field with
  // nothing standing in it would state something false about what is for sale, so it does not
  // render at all. Same rule, same reason, as the component this replaces.
  if (packs.length <= 0 || total <= 0) return null;

  // Square, and big enough to hold every idea. 1,444 gives 38, which is where the brief's
  // `viewBox="0 0 38 38"` comes from. Derived rather than typed, so the next batch cannot silently
  // overflow the last row.
  const side = Math.ceil(Math.sqrt(total));

  // Oldest first. `verifiedAt` is an ISO date string, so a far-future ISO date is the sentinel for
  // a pack that carries no date: it sorts last through the same comparison the real values use, so
  // there is no second code path to keep in step. An empty string would have won every comparison
  // and parked the undated packs at the head of a picture whose whole subject is order.
  const UNDATED_SORTS_LAST = '9999-12-31';
  const ordered = [...packs].sort((a, b) =>
    (a.verifiedAt ?? UNDATED_SORTS_LAST).localeCompare(b.verifiedAt ?? UNDATED_SORTS_LAST),
  );

  // Rank k of n sits in bucket k of the field. See the note above on what position means.
  const bucket = total / ordered.length;
  const placed = ordered.map((pack, k) => ({
    pack,
    index: Math.min(total - 1, Math.floor((k + 0.5) * bucket)),
  }));
  const live = new Set(placed.map((p) => p.index));

  const d = deadPath(total, side, live);
  // `tightDecimal` closes the thousands mark: in the house mono face every glyph takes the same
  // advance, so a comma sits in a full cell and `1,444` renders as `1 , 444` -- three tokens where
  // the reader is handed one figure. See `ui/Money.tsx`.
  const totalLabel = tightDecimal(total.toLocaleString('en-GB'));

  return (
    <figure className={cx('rounded-card border border-line bg-surface p-4', className)}>
      <svg
        viewBox={`0 0 ${side} ${side}`}
        className="block w-full"
        /* The marks are axis-aligned rectangles a few device pixels wide. Antialiasing turns those
           into a grey haze; `crispEdges` snaps them to the pixel grid, which is what makes the
           field read as a grid rather than as noise (MASTER-BRIEF §7). */
        shapeRendering="crispEdges"
        /* `group`, NOT `img`. §9 asks for "a single role=img with a full aria-label" AND for
           "interactive cells inside are links with accessible names", and those two cannot both be
           true: `role="img"` prunes the subtree, so it would hide every survivor link from
           assistive technology. The links are the point, so the picture is a group. SVG-AAM names
           a group from its first-child `<title>` and describes it from `<desc>`, which is why
           there is no `aria-labelledby` and no ids here -- ids would be a duplicate-id bug the day
           this renders twice on one page. */
        role="group"
      >
        <title>{`${totalLabel} ideas researched`}</title>
        <desc>
          {`One square per idea, oldest first. ${RESEARCH_STATS.killed.toLocaleString('en-GB')} were killed on cited evidence. The teal squares are the packs on the shelf now, and each one links to its pack.`}
        </desc>

        {/* Presentational. A screen reader must get the FACT the picture states, from the
            description above, rather than walk a picket fence of 1,394 announced cells. */}
        <path d={d} className="fill-faint" aria-hidden="true" />

        {/* Each survivor is its own element with its own name and its own destination. This is the
            half `PopulationField` could not do, and it is what makes the picture worth its pixels:
            a reader who notices a teal square can open the thing it stands for.

            THE TEAL SQUARE IS ALSO BIGGER, and that is the §9 rule "colour never the only signal"
            applied to a data graphic. 0.86 of a cell against 0.66 is a visible step at every
            viewport this renders at, so the shelf reads as raised out of the field for a reader
            who cannot separate the two hues.

            KNOWN COST, stated rather than hidden: this puts one tab stop per listed pack in the
            hero. It is accepted because what a keyboard user tabs through is the shelf in research
            order, each announced by its own title -- a list, not decoration. */}
        {placed.map(({ pack, index }) => (
          <a key={pack.id} href={`/pack/${pack.id}`}>
            <title>{pack.title}</title>
            <rect
              x={(index % side) + (1 - LIVE_SIDE) / 2}
              y={Math.floor(index / side) + (1 - LIVE_SIDE) / 2}
              width={LIVE_SIDE}
              height={LIVE_SIDE}
              className="fill-survive"
            />
          </a>
        ))}
      </svg>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-caption text-subtle">
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block size-[9px] rounded-sm bg-survive" />
          On the shelf now
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block size-[7px] rounded-sm bg-faint" />
          Researched, not listed
        </span>
        <span className="ml-auto tabular-nums text-muted">{totalLabel}</span>
      </div>

      <figcaption className="mt-3 border-t border-line pt-3 text-meta leading-relaxed text-muted">
        Every idea we have ever researched, one square each, oldest first. The teal ones are what
        you can buy.
      </figcaption>
    </figure>
  );
}

export default KillGrid;

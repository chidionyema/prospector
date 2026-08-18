import { RESEARCH_STATS } from '@/lib/stats';
import type { Pack } from '@/lib/api/client';
import { cx } from '@/components/ui/cx';
import { track } from '@/lib/analytics';
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
 * THE LEGEND PRINTS THE KILL COUNT AND WITHHOLDS THE SURVIVOR COUNT. `mockups/index.html:295-297`
 * prints "1,364 killed / 68 survived" under the grid. The first of those ships and the second
 * cannot. The founder's directive of 2026-08-13 is that the survivor count is never printed --
 * "saying 80 when only 50 are listed should never happen regardless of the reasons why survivors
 * are unlisted" -- and `lib/stats.ts` enforces it by not exporting the number at all, so this
 * component could not print it without a new export and a new argument. The kill total is under no
 * such fence: it counts finished kills rather than making a claim about what is buyable today.
 * The two figures also do not partition the total -- killed plus listed is short of researched,
 * because an idea that cleared the gates and is not packaged yet belongs to neither group -- which
 * is why the survivor entry is a NAME rather than a number with a gap in it.
 */

/**
 * One cell is 1 unit. Both marks are centred in their cell, so the gutter is even on all sides.
 *
 * THE NUMBERS COME FROM THE DRAWING, 2026-08-18. `mockups/index.html:74` lays the field out as
 * `grid-template-columns:repeat(38,1fr); gap:1.5px`, so at the 380px the hero column gives it the
 * pitch is ~10px and each square fills ~8.5px of it -- 85% of its cell. Ours filled 66%, which is
 * 43% of each cell's AREA against the drawing's 72%, and that is why the field read as a pale
 * scatter next to a solid block of grey. It was the largest single difference between our hero and
 * the mockup's, and no amount of colour work would have closed it.
 *
 * THE SIZE STEP SURVIVES THE RETUNE, and it is ours rather than the drawing's: the mockup draws
 * every cell the same size and separates the shelf by hue alone, which §9's "colour is never the
 * only signal" forbids. 0.96 against 0.80 is the same 0.16 of a cell the old pair carried, so a
 * reader who cannot separate teal from grey still sees the shelf standing out of the field.
 */
const DEAD_SIDE = 0.8;
const LIVE_SIDE = 0.96;

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

/**
 * A stable fraction in [0.06, 0.94) from a pack id, used to place a survivor inside its bucket.
 *
 * FNV-1a, eight lines, no dependency. It has to be a pure function of data the server and the
 * browser both hold, because the field is rendered once on the server and hydrated in the browser
 * and the two must agree mark for mark.
 *
 * The range is inset rather than [0, 1) so a survivor never lands hard against a bucket edge,
 * which is where two adjacent survivors would draw as a pair and reintroduce a texture.
 */
function offset01(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return 0.06 + (h / 0x100000000) * 0.88;
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

  /*
   * Rank k of n sits in bucket k of the field. See the note above on what position means.
   *
   * THE OFFSET INSIDE THE BUCKET IS DERIVED FROM THE PACK ID, and it is not decoration. Before
   * 2026-08-18 every survivor sat dead centre of its bucket, at `(k + 0.5) * bucket`. With 74
   * survivors in 1,444 cells the bucket is 19.5 and the row is 38, so consecutive survivors landed
   * 19.5 cells apart -- a hair over half a row -- and the half-cell drifted one column further
   * every pair. The field drew clean diagonal stripes across the whole hero. Compared side by side
   * with `mockups/index.html`, whose survivors are scattered, ours read as wallpaper: a regular
   * pattern is the one thing a picture of real outcomes must not look like, because a reader who
   * sees a repeat stops believing the marks are data.
   *
   * The offset is a hash of the pack id, so it is stable: the same catalogue draws the same field
   * on the server and in the browser, which `Math.random` could not do without breaking hydration,
   * and it changes only when the catalogue does. It stays strictly inside bucket k, so rank order
   * left to right and top to bottom is exactly as it was and the caption is still true.
   */
  const bucket = total / ordered.length;
  const placed = ordered.map((pack, k) => ({
    pack,
    index: Math.min(total - 1, Math.floor((k + offset01(pack.id)) * bucket)),
  }));
  const live = new Set(placed.map((p) => p.index));

  const d = deadPath(total, side, live);
  // `tightDecimal` closes the thousands mark: in the house mono face every glyph takes the same
  // advance, so a comma sits in a full cell and `1,444` renders as `1 , 444` -- three tokens where
  // the reader is handed one figure. See `ui/Money.tsx`.
  const totalLabel = tightDecimal(total.toLocaleString('en-GB'));
  const killedLabel = tightDecimal(RESEARCH_STATS.killed.toLocaleString('en-GB'));

  // `p-[18px]`, not `p-4`. The drawing's `.gridwrap` is `padding:18px` (`mockups/index.html:73`)
  // and Tailwind's scale has no 18px step, so the arbitrary value is the only way to draw the box
  // that was drawn. A JSX comment cannot sit here: it would be a second root child of the return.
  return (
    /* THE DRAWING'S OWN CLASSES (`mockups/index.html` section 2: `figure.gridwrap`, `.gridkey`
       with `i.sw.dead` / `i.sw.alive` swatches, `figcaption.gridcap`). They were Tailwind
       utilities holding the same numbers by hand. The FIELD stays an `<svg>` rather than the
       drawing's 1,444 `<i>` elements: 1,444 DOM nodes in the hero is the cost this component was
       written to avoid, and the squares are the same size, colour and gap either way. */
    <figure className={cx('gridwrap', className)}>
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
        {/* The PLAIN string, not `totalLabel`. `tightDecimal` returns a React node -- it wraps the
            thousands separator in a span to close the gap around it -- and interpolating a node
            into a template literal stringifies it, so this element read "[object Object] ideas
            researched" to every screen reader and in every accessibility tree. The kerning fix has
            nothing to offer inside <title>, which renders no markup. */}
        <title>{`${total.toLocaleString('en-GB')} ideas researched`}</title>
        <desc>
          {`One square per idea, oldest first. ${RESEARCH_STATS.killed.toLocaleString('en-GB')} were killed on cited evidence. The teal squares are the packs available now, and each one links to its pack.`}
        </desc>

        {/* Presentational. A screen reader must get the FACT the picture states, from the
            description above, rather than walk a picket fence of 1,394 announced cells. */}
        {/* THE DRAWING'S DEAD MARK is `--dead` (#DEDED7), not `--faint` (#A1A1AA). Measured
            2026-08-18: the drawing paints 1,382 dead cells in #DEDED7 and the built page had that
            colour nowhere on it, so the grid read as a field of mid-grey rather than as the pale
            ground the survivors stand out against. */}
        <path d={d} className="fill-dead" aria-hidden="true" />

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
          <a
            key={pack.id}
            href={`/pack/${pack.id}`}
            /* The href does the navigating, so this graphic still works with no JavaScript; the
               handler only records that the click came from the grid. `card_click` and not a
               name of its own, because the question is which surface sends readers to a pack and
               a separate name would sit outside every existing click-through report. */
            onClick={() => track('card_click', `grid:${pack.id}`)}
          >
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

      {/* THE LEGEND, REDRAWN TO THE MOCKUP ON 2026-08-18, with one figure still withheld.

          Order and the killed figure are the drawing's: `mockups/index.html:295-297` reads dead
          square then live square, and the dead entry carries "1,364 killed".

          THE RADIUS IS NOT the drawing's. `.sw` is `border-radius:2px` and this site's radius
          vocabulary has no 2px step -- `threeRadiiTwoShadows.test.ts` bounds it to sm/md/card/ctl
          and refused the arbitrary value, correctly: a bounded vocabulary is worth more than 2px
          of corner on a 9px chip. `rounded-sm` is the step that exists for exactly this ("controls
          under ~28px: checkbox, chip, small badge").

          WHAT IS STILL NOT PRINTED is the survivor count beside it. The founder's directive of
          2026-08-13 -- "saying 80 when only 50 are listed should never happen regardless of the
          reasons why survivors are unlisted" -- is enforced in `lib/stats.ts` by not exporting the
          number, so this file could not print it without a new export. `killed` IS exported and IS
          safe: it is a count of finished kills, not a claim about what is buyable today.

          THE TWO SWATCHES ARE DIFFERENT SIZES and the drawing's are not, for the same reason the
          marks themselves are: 9px against 7px is the legend telling the truth about a field whose
          live marks are larger. A uniform legend over a non-uniform field would describe a picture
          we do not draw. */}
      <div className="gridkey mt-4">
        <span>
          <i aria-hidden className="sw dead size-[7px]" />
          <b>{killedLabel}</b> killed
        </span>
        <span>
          <i aria-hidden className="sw alive" />
          Available now
        </span>
        {/* THE TOTAL IS NOT IN THIS ROW ANY MORE. It sat here hard right as `1,444 researched`,
            and at the hero column's width that pushed the legend onto two lines while the
            drawing keeps it on one (`mockups/index.html:295-297`, two entries, one row). The
            figure moved into the caption below, where it is a scale label in a sentence rather
            than a third legend entry competing with two swatches.

            The drawing's second entry, "68 survived", is still not printable: the founder's
            directive of 2026-08-13 and `lib/stats.ts` between them make the survivor count
            unavailable, so the shelf entry carries a name and no number.
            `killGrid.test.tsx` pins that the total stays visible somewhere a reader sees. */}
      </div>

      <figcaption className="gridcap">
        Every idea we have ever researched, one square each. The teal ones are what you can buy.
        All {totalLabel}, oldest first.
      </figcaption>
    </figure>
  );
}

export default KillGrid;

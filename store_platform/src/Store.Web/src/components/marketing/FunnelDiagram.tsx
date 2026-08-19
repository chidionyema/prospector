import Link from 'next/link';

import { RESEARCH_STATS } from '@/lib/stats';
import { cx } from '@/components/ui/cx';
import { textLinkClass } from '@/components/ui';

/**
 * THE FUNNEL, DRAWN.
 *
 * WHY IT EXISTS. The brief of 2026-08-15, Part Four: "There is a funnel in the logo mark and a
 * funnel in the proposition, and it currently appears as neither." Both halves are true. The mark
 * is three tapering slabs (`Logo.tsx::BrandMark`), the proposition is "1,444 in, 1,364 killed",
 * and between them the site had one picture of the population -- `KillGrid`, a flat field of
 * 1,444 squares in the home page hero -- which shows the SIZE of the intake and nothing about the
 * narrowing. This is the narrowing.
 *
 * WHAT IT MAY AND MAY NOT SAY, which is the whole design constraint here.
 *
 * The brief asks for "1,444 researched -> 1,364 killed -> what survives". The third term is
 * forbidden. On 2026-08-13 the founder cut the survivor figure sitewide -- "saying 80 when only 50
 * are listed should never happen regardless of the reasons why" -- and `lib/stats.ts` enforces it
 * by not exporting the number at all, so no surface can print it even by accident. The two
 * populations also do not partition: 1,364 killed and 50 listed do not sum to 1,444, because an
 * idea that cleared the gates and is not packaged yet is in neither group, and asserting a
 * partition that does not close is a defect this site has already shipped once (c8e6ed0).
 *
 * So the stub at the bottom of this funnel carries NO figure. It is a shape, and the sentence
 * under it points at the shelf, where the reader can count for themselves. The two numbers on the
 * diagram are the two numbers the page beside it already states, read from the same
 * `RESEARCH_STATS` -- the picture cannot disagree with the prose because it has no second source.
 *
 * THE TAPER IS TO SCALE, and that is the argument. `survivorFraction` is a WIDTH, never a figure:
 * it is the only place in the codebase that reconstructs the cut number, it is consumed by
 * geometry in the same expression, and it must never reach a text node. The bottom of the funnel
 * is 5.5% of the top because 5.5% is what survives; a funnel drawn to a comfortable-looking stub
 * would be decoration illustrating a claim rather than the claim itself.
 *
 * GEOMETRY. The three slabs are the brand mark's, re-derived at this aspect: a trapezoid from
 * y=16 to y=296, cut by two gaps at the mark's own proportions (the slabs are 32, 24 and 16 units
 * of the mark's 88), so each is both narrower AND shorter than the one above. The viewBox is 440
 * wide rather than the 720 the brief specifies as a maximum, because SVG type does not reflow:
 * at 440 the labels grow with the graphic, where a 720 viewBox would put them at 11px on a phone
 * -- under the brief's own 12px floor. MEASURED at a 390 viewport: the svg lays out 342px wide, so
 * the caption's 16 viewBox units render 12.4px and the figures' 30 render 23.3px. The captions were
 * 15 units and measured 11.7px, which is how close that floor is at this width -- do not lower
 * them without re-measuring.
 *
 * COLOUR. Ink at three opacities, no hue. `--brand-mark` is reserved to the logo tile by its own
 * token note, and SITE_SPEC §3's one-colour rule is the reason this reads as part of the page
 * rather than as an infographic dropped onto it. The stub is solid: the eye should land on what
 * is left, which is the only part of this picture a reader can go and buy.
 */

const TOP_Y = 16;
const BOTTOM_Y = 296;
const CENTRE_X = 220;
const TOP_HALF = 208;

/** See the docblock: a width, never a figure. Nothing may render this. */
const survivorFraction = 1 - RESEARCH_STATS.killed / RESEARCH_STATS.researched;
const BOTTOM_HALF = TOP_HALF * survivorFraction;

/** Half-width of the funnel at a given y, linear between the two edges. */
function halfWidthAt(y: number): number {
  const t = (y - TOP_Y) / (BOTTOM_Y - TOP_Y);
  return TOP_HALF - (TOP_HALF - BOTTOM_HALF) * t;
}

/** One slab of the funnel: the trapezoid between two heights. */
function slab(yTop: number, yBottom: number): string {
  const a = halfWidthAt(yTop);
  const b = halfWidthAt(yBottom);
  return [
    `M ${(CENTRE_X - a).toFixed(1)} ${yTop}`,
    `L ${(CENTRE_X + a).toFixed(1)} ${yTop}`,
    `L ${(CENTRE_X + b).toFixed(1)} ${yBottom}`,
    `L ${(CENTRE_X - b).toFixed(1)} ${yBottom}`,
    'Z',
  ].join(' ');
}

/* The mark's slabs are 32 / 24 / 16 of its 88 units, with 8-unit gaps. Same ratios, this height. */
const UNIT = (BOTTOM_Y - TOP_Y) / 88;
const SLAB_1 = [TOP_Y, TOP_Y + 32 * UNIT] as const;
const SLAB_2 = [TOP_Y + 40 * UNIT, TOP_Y + 64 * UNIT] as const;
const SLAB_3 = [TOP_Y + 72 * UNIT, BOTTOM_Y] as const;

function midY([a, b]: readonly [number, number]): number {
  return (a + b) / 2;
}

export function FunnelDiagram({ className }: { className?: string }) {
  const researched = RESEARCH_STATS.researched.toLocaleString('en-GB');
  const killed = RESEARCH_STATS.killed.toLocaleString('en-GB');

  return (
    <figure className={cx('max-w-[440px]', className)}>
      <svg
        viewBox="0 0 440 320"
        className="w-full"
        role="img"
        aria-label={`${researched} ideas researched. ${killed} were killed on cited evidence. What is left is what you can buy.`}
      >
        {/* Stroke matches the icon hand: 1.5 units at this scale is the same weight the 24px
            icons carry, which is the brief's "diagrams and icons must read as one hand". */}
        <g className="stroke-text" strokeWidth={1.5} strokeOpacity={0.35}>
          <path
            d={slab(SLAB_1[0], SLAB_1[1])}
            className="fill-text"
            fillOpacity={0.08}
          />
          <path
            d={slab(SLAB_2[0], SLAB_2[1])}
            className="fill-text"
            fillOpacity={0.16}
          />
          <path
            d={slab(SLAB_3[0], SLAB_3[1])}
            className="fill-text"
            fillOpacity={1}
          />
        </g>

        <g textAnchor="middle" className="fill-text">
          <text
            x={CENTRE_X}
            y={midY(SLAB_1) - 2}
            fontSize={30}
            fontWeight={600}
            className="tabular-nums"
          >
            {researched}
          </text>
          <text
            x={CENTRE_X}
            y={midY(SLAB_1) + 22}
            fontSize={16}
            className="fill-muted"
          >
            ideas researched
          </text>

          {/* TWO LINES, and the reason is geometry rather than taste (2026-08-16, founder:
              "killed on cited evidence is almost spilling out of container").

              The funnel NARROWS, so a caption's budget depends on the y it sits at, and only this
              one outgrew its slab. Set as one line the label's baseline was `midY(SLAB_2) + 22` =
              203.4, where `halfWidthAt` returns 76.4 -- a 152.9-unit slab -- and the phrase measures
              about 169 units (getBBox on the two halves gives 59.2 + 105.2 plus the space). So it
              hung roughly 8 units past each sloped edge. Nothing was clipped, the SVG is 440 wide
              and the text never left the box; it was simply wider than the shape it labels, on a
              shape whose whole job is to narrow. The slab above measures 313.7 units at its
              caption's y against 126.2 of text, which is why "ideas researched" never had this
              problem and stays one line.

              The two fixes that do NOT work here are worth recording so they are not retried. Type
              cannot shrink: this file's own measurement puts fontSize 16 at 12.4px on a 390
              viewport, already a fraction over the brief's 12px floor. And the copy cannot lose
              "cited" -- evidence being CITED is the site's whole claim, and "killed on evidence"
              would still clear the slab by only a few units.

              So the block splits and lifts. The figure moves up 10 units and the caption becomes two
              lines at 189.5 and 207.5. MEASURED THERE, in the browser, after the change: slab 172.6
              against text 59.2, and slab 147.3 against text 105.2 -- 113.4 and 42.1 units of
              clearance. The second line's descenders land near 211, inside the slab's bottom edge at
              219.6. The break falls after "killed on" because "cited evidence" is the phrase;
              splitting a noun off its adjective to even up two line lengths reads as a wrap rather
              than as a decision. The `aria-label` is untouched and still reads as one sentence -- the
              split is visual, and a screen reader must not hear it. */}
          <text
            x={CENTRE_X}
            y={midY(SLAB_2) - 12}
            fontSize={30}
            fontWeight={600}
            className="tabular-nums"
          >
            {killed}
          </text>
          <text
            x={CENTRE_X}
            y={midY(SLAB_2) + 8}
            fontSize={16}
            className="fill-muted"
          >
            killed on
          </text>
          <text
            x={CENTRE_X}
            y={midY(SLAB_2) + 26}
            fontSize={16}
            className="fill-muted"
          >
            cited evidence
          </text>
        </g>
      </svg>

      {/* The caption is HTML and not a third `<text>`: it carries a link, and a link inside an SVG
          is reachable but does not take the site's focus ring or hover treatment. It also states
          the one thing the shape cannot -- that the stub is countable, on a page the reader can
          open -- without putting a number on the diagram. */}
      <figcaption className="mt-3 max-w-[46ch] text-meta leading-relaxed text-muted">
        The stub at the bottom is what you can buy.{' '}
        <Link href="/ideas" className={textLinkClass()}>
          Count it yourself
        </Link>
        .
      </figcaption>
    </figure>
  );
}

export default FunnelDiagram;

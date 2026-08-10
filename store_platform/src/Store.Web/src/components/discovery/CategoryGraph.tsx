import React from 'react';
import Link from 'next/link';
import { cx } from '@/components/ui/cx';

export interface CategoryNode {
  /** Category slug used in the catalogue filter (?kind=b2b or similar). */
  kind: string;
  /** Buyer-facing label. */
  label: string;
  /** Number of packs in this category. */
  count: number;
  /** One-line description shown on hover. */
  description?: string;
}

export interface CategoryGraphProps {
  categories: CategoryNode[];
  /**
   * Optional: the path to navigate to when a node is clicked. The query string
   * `?kind=<kind>` is appended so the home page's filter state picks the
   * category up automatically. Default: `/?kind={kind}`.
   */
  filterPath?: (kind: string) => string;
  /** Optional className for the SVG container. */
  className?: string;
}

/**
 * 2D graph of categories. Each node is a circle sized by pack count, placed
 * at a deterministic position derived from the kind. Tapping a node navigates
 * to the catalogue filtered by that category.
 *
 * US-7 (audit §4.5): the /ideas page used to render 16 identical-feeling
 * category cards in a flat list. The graph makes the relationships visible
 * (operators cluster with trades, developers cluster with productised
 * services), and the size of each node is a visual proxy for "how many packs
 * are in this category" without the buyer having to read the count.
 *
 * The position is a 4x4 grid keyed by the category kind, so the layout is
 * deterministic across renders. A buyer who lands on /ideas twice sees the
 * same graph twice; the cognitive map they form on the first visit still
 * applies on the second.
 *
 * Keyboard: each node is a `<Link>` (renders as `<a>`), so it is focusable
 * and Enter activates it. Tab order follows the visual grid, top-left to
 * bottom-right.
 */
/**
 * Keyed by the REAL landing slugs (`src/lib/seo/landings.ts`'s `LANDINGS[].slug`), grouped by
 * `Landing.kind` (payer / commitment / effort / advantage / mechanism / sector) so related
 * categories sit in adjacent cells -- payer on row 0, advantage spanning rows 1-2, sector on
 * row 3, etc.
 *
 * This replaces a table that was keyed by short, invented names (`b2b`, `developers`,
 * `full_time`, `b2g`, ...) that never matched a real slug: `comm -12` against the actual 16
 * `LANDINGS` slugs returned zero overlap, so every render fell through to `positionFor`'s
 * index-based fallback below. That fallback happened to look reasonable on screen only because
 * `getServerSideProps` passes categories in `LANDINGS` declaration order, which is itself
 * kind-grouped -- the apparent clustering was an accident of array order, not this table. Keying
 * on the real slugs makes the intended grouping the actual mechanism again, so it survives
 * `LANDINGS` being reordered or a category being added/removed instead of silently reverting to
 * whatever position the array happens to place it at.
 */
const POSITIONS: Record<string, { x: number; y: number }> = {
  // payer
  'b2b-business-ideas': { x: 0, y: 0 },
  'b2c-business-ideas': { x: 1, y: 0 },
  // commitment
  'evening-business-ideas': { x: 2, y: 0 },
  'part-time-business-ideas': { x: 3, y: 0 },
  // effort
  'automated-business-ideas': { x: 0, y: 1 },
  'part-automated-business-ideas': { x: 1, y: 1 },
  // advantage
  'business-ideas-for-developers': { x: 2, y: 1 },
  'business-ideas-for-operators': { x: 3, y: 1 },
  'business-ideas-for-salespeople': { x: 0, y: 2 },
  // mechanism
  'productised-service-ideas': { x: 1, y: 2 },
  'vertical-software-ideas': { x: 2, y: 2 },
  'marketplace-and-broker-ideas': { x: 3, y: 2 },
  // sector
  'red-tape-and-licensing-ideas': { x: 0, y: 3 },
  'pay-and-worker-rights-ideas': { x: 1, y: 3 },
  'care-and-benefits-ideas': { x: 2, y: 3 },
  'trades-and-construction-ideas': { x: 3, y: 3 },
};

/** Fallback position for any kind not in the table: distributed by index, so a new category
 *  added to `LANDINGS` without a matching `POSITIONS` entry still renders somewhere sane instead
 *  of colliding at (0, 0). */
function positionFor(kind: string, index: number, cols: number, rows: number): { x: number; y: number } {
  if (POSITIONS[kind]) {
    const p = POSITIONS[kind];
    // A caller with fewer columns than the desktop table (the mobile layout) can't use the
    // desktop (x, y) pair directly -- re-flow by the same index instead so mobile always gets a
    // valid, in-bounds cell.
    if (cols === GRID_COLS && rows === GRID_ROWS) return p;
  }
  const col = index % cols;
  const row = Math.floor(index / cols) % rows;
  return { x: col, y: row };
}

const GRID_COLS = 4;
const GRID_ROWS = 4;
const SVG_WIDTH = 720;
const SVG_HEIGHT = 480;
const PADDING = 40;

/**
 * Mobile layout: 3 columns instead of 4. The earlier fix for illegible mobile labels (see the
 * comment on the wrapper `<div>` below) capped the SVG at its native 720px width and let it
 * scroll horizontally -- technically legible, but it meant a phone visitor had to pan or zoom to
 * see the whole graph, which is the complaint this layout exists to fix. Rendering a SEPARATE,
 * narrower SVG at full native font/circle size (not a scaled-down viewBox of the desktop one)
 * fits inside a phone's viewport with no horizontal scroll or zoom, at the cost of being taller
 * -- vertical scroll on a phone is the normal, expected way to see more content, unlike
 * horizontal scroll on a diagram.
 */
const GRID_COLS_MOBILE = 3;
const GRID_ROWS_MOBILE = 6;
const SVG_WIDTH_MOBILE = 360;
const SVG_HEIGHT_MOBILE = 648;
const PADDING_MOBILE = 24;

interface GridConfig {
  cols: number;
  rows: number;
  width: number;
  height: number;
  padding: number;
  /**
   * CSS `min-width` floor for the rendered SVG, in px. Only the desktop grid sets this
   * (to 720, its own native width): its wrapper has `overflow-x-auto`, so on a container
   * narrower than 720 the diagram scrolls horizontally rather than squashing illegibly.
   *
   * The mobile grid MUST leave this unset. `min-width` always wins over `width: 100%`
   * (`h-auto w-full` below), so a fixed 360 here pinned the mobile SVG to 360px wide
   * regardless of its actual container -- and the mobile wrapper has no `overflow-x-auto`
   * (deliberately: see the "no horizontal scroll or zoom" comment on GRID_COLS_MOBILE
   * above). Measured live on mumchimp.com/ideas 2026-08-10: at 320/360/375px viewports
   * (a small Android, a common Android, and an iPhone SE -- not edge cases) the card was
   * 272-327px wide but the SVG stayed pinned at 360px, so up to 4 circles rendered
   * 20-50px past the card's right/bottom border with nothing to clip or scroll them.
   * Leaving `minWidth` undefined lets `w-full` actually shrink the SVG (and everything
   * in its viewBox, proportionally) to fit whatever the container really is.
   */
  minWidth?: number;
}

/**
 * One SVG rendering of the graph at a given grid size. Pulled out of `CategoryGraph` so the
 * desktop (4x4, native 720px) and mobile (3x6, native 360px) variants share one implementation
 * instead of two hand-kept-in-sync copies -- both render at their OWN native font/circle sizes
 * (never a scaled `viewBox` of the other), which is what keeps mobile labels legible without a
 * `viewBox` downscale shrinking `fontSize` along with everything else.
 */
function GraphSvg({
  categories,
  grid,
  pathFor,
  ariaLabel,
}: {
  categories: CategoryNode[];
  grid: GridConfig;
  pathFor: (kind: string) => string;
  ariaLabel: string;
}) {
  const { cols, rows, width, height, padding, minWidth } = grid;
  const cellW = (width - padding * 2) / cols;
  const cellH = (height - padding * 2) / rows;
  // Size scale: the smallest category is 24px radius, the largest is 56px.
  const minCount = Math.min(...categories.map((c) => c.count), 1);
  const maxCount = Math.max(...categories.map((c) => c.count), 1);
  const range = Math.max(maxCount - minCount, 1);
  /**
   * 18-36px, down from 24-56px, because the label now sits BELOW the circle and has to fit in
   * the same cell.
   *
   * The old radius could not be kept. The cell is 100px tall ((480 - 80) / 4), so a 56px radius
   * was already a 112px circle in a 100px cell, and adding a label under it would have run the
   * label straight through the row beneath. At 36px the circle is 72px and leaves 28px for the
   * caption. Size still encodes count, over a smaller but honest range.
   */
  const radiusFor = (count: number): number => {
    const t = (count - minCount) / range;
    return 18 + t * 18;
  };

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-auto w-full"
      style={minWidth ? { minWidth } : undefined}
      role="img"
      aria-label={ariaLabel}
    >
      {categories.map((node, i) => {
        const pos = positionFor(node.kind, i, cols, rows);
        const cx = padding + cellW * (pos.x + 0.5);
        const cy = padding + cellH * (pos.y + 0.5);
        const r = radiusFor(node.count);
        return (
          <Link
            key={node.kind}
            href={pathFor(node.kind)}
            aria-label={`${node.label}, ${node.count} packs`}
            className="focus:outline-none focus-visible:ring-2 focus-visible:ring-focus rounded-full"
          >
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill="currentColor"
              fillOpacity={0.08}
              stroke="currentColor"
              strokeWidth={1.5}
              className="transition-all hover:fill-opacity-20"
            />
            {/* The COUNT goes inside, the label goes underneath. It used to be the other way
                around, and the label could not survive it: the widest text a circle of radius
                r can hold is its chord, about 1.6r, and the font was sized r / 3.2, so the
                character budget came out at ~9 REGARDLESS of how large the node was. Growing
                the circle grew the font in step and bought nothing. Every multi-word category
                therefore rendered clipped -- "Business ideas" as "Busin…" -- on the one page
                whose entire job is letting a visitor see what the catalogue contains.
                A count is two or three digits and always fits; a label never did. */}
            <text
              x={cx}
              y={cy + r / 3.4}
              textAnchor="middle"
              className="pointer-events-none select-none"
              fontSize={Math.max(12, r / 2.2)}
              fontWeight={600}
              fill="var(--text)"
            >
              {node.count}
            </text>
            {wrapLabel(node.label, cellW).map((lineText, lineIndex) => (
              <text
                key={lineText + lineIndex}
                x={cx}
                y={cy + r + 14 + lineIndex * 12}
                textAnchor="middle"
                className="pointer-events-none select-none"
                fontSize={11}
                fontWeight={500}
                fill="var(--text-muted, #78716C)"
              >
                {lineText}
              </text>
            ))}
          </Link>
        );
      })}
    </svg>
  );
}

const DESKTOP_GRID: GridConfig = {
  cols: GRID_COLS, rows: GRID_ROWS, width: SVG_WIDTH, height: SVG_HEIGHT, padding: PADDING,
  // Desktop wrapper below has `overflow-x-auto`: below 720px wide, scroll rather than squash.
  minWidth: SVG_WIDTH,
};
const MOBILE_GRID: GridConfig = {
  cols: GRID_COLS_MOBILE,
  rows: GRID_ROWS_MOBILE,
  width: SVG_WIDTH_MOBILE,
  height: SVG_HEIGHT_MOBILE,
  padding: PADDING_MOBILE,
  // No minWidth: the mobile wrapper has no overflow-x-auto by design (no horizontal
  // scroll on a phone), so the SVG must be free to shrink below its native 360px to
  // whatever the real container is -- see the GridConfig.minWidth comment above.
};

/**
 * The graph itself. An SVG with one circle per category, sized by pack count. Each circle is
 * a `<Link>` so the keyboard path is identical to the mouse path.
 */
export default function CategoryGraph({ categories, filterPath, className }: CategoryGraphProps) {
  const pathFor = filterPath ?? ((kind: string) => `/?kind=${encodeURIComponent(kind)}`);
  const ariaLabel = 'Catalogue categories, sized by pack count';

  return (
    <div
      className={cx(
        'rounded-md border border-border bg-surface p-4 md:p-6',
        className,
      )}
    >
      {/*
        Two separate SVGs, not one scaled by CSS/viewBox. `viewBox` scales the WHOLE svg as one
        vector -- including the label `fontSize`, which is set in the same user-space units as
        everything else (see `wrapLabel`'s LABEL_FONT_PX below). Shrinking the desktop 720-wide
        svg's viewBox to fit a ~320px mobile container downscaled it to ~0.44x, so the 11-unit
        label rendered at ~5px -- confirmed on the live mumchimp.com/ideas mobile view,
        2026-08-09. An intermediate fix capped the svg at its native 720px width and let it
        scroll horizontally, which kept labels legible but meant a phone visitor had to pan or
        zoom to see the whole graph. Rendering a SEPARATE, narrower 3-column layout at its own
        native size (`MOBILE_GRID`, below) fits a phone viewport with no horizontal scroll or
        zoom -- the same `hidden md:block` / `block md:hidden` breakpoint split already used for
        `Logo.tsx`'s compact form, so there is no JS viewport check to keep in sync with a CSS
        breakpoint.
      */}
      <div className="hidden md:block overflow-x-auto">
        <GraphSvg categories={categories} grid={DESKTOP_GRID} pathFor={pathFor} ariaLabel={ariaLabel} />
      </div>
      <div className="block md:hidden">
        <GraphSvg categories={categories} grid={MOBILE_GRID} pathFor={pathFor} ariaLabel={ariaLabel} />
      </div>
      <p className="mt-3 text-center text-caption text-muted">
        Tap a circle to filter the catalogue. Circle size reflects pack count.
      </p>
    </div>
  );
}

/** Label font size, and the average glyph width it produces. Used to turn a pixel budget into a
 *  character budget. 0.55em is the usual approximation for a humanist sans at small sizes; it is
 *  deliberately pessimistic, so the estimate errs towards wrapping early rather than overflowing. */
const LABEL_FONT_PX = 11;
const LABEL_GLYPH_RATIO = 0.55;
const LABEL_MAX_LINES = 2;

/**
 * Break a category label across at most two lines that fit the cell width.
 *
 * Wraps on word boundaries, so "Productised service" becomes two whole words rather than
 * "Productised s\u2026". Only when a single word is itself wider than the cell does this fall back to
 * cutting, and then it marks the cut. With a 160px cell (720 - 80 padding, over 4 columns) the
 * budget is ~26 characters per line against the ~9 the old in-circle label had.
 */
export function wrapLabel(label: string, cellWidth: number): string[] {
  const maxChars = Math.max(6, Math.floor(cellWidth / (LABEL_FONT_PX * LABEL_GLYPH_RATIO)));
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars) {
      current = candidate;
      continue;
    }
    if (current) lines.push(current);
    if (lines.length === LABEL_MAX_LINES) break;
    // A single word longer than the whole budget is the only case that still has to be cut.
    current = word.length > maxChars ? `${word.slice(0, maxChars - 1)}\u2026` : word;
  }
  if (current && lines.length < LABEL_MAX_LINES) lines.push(current);

  // Anything that did not fit in two lines is signalled, never dropped silently.
  const rendered = lines.join(' ').replace(/\u2026$/, '');
  if (rendered.length < label.trim().length && !lines[lines.length - 1].endsWith('\u2026')) {
    lines[lines.length - 1] = `${lines[lines.length - 1]}\u2026`;
  }
  return lines;
}

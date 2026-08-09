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
const POSITIONS: Record<string, { x: number; y: number }> = {
  // Buyers (top row, B2B on the left, B2C on the right).
  b2b: { x: 0, y: 0 },
  b2c: { x: 1, y: 0 },
  b2g: { x: 2, y: 0 },
  // Effort / commitment (second row).
  evenings: { x: 0, y: 1 },
  part_time: { x: 1, y: 1 },
  full_time: { x: 2, y: 1 },
  // Archetypes (third row, left to right by archetype).
  'vertical-software': { x: 0, y: 2 },
  'productised-service': { x: 1, y: 2 },
  marketplace: { x: 2, y: 2 },
  red_tape: { x: 3, y: 2 },
  pay_rights: { x: 3, y: 1 },
  benefits: { x: 3, y: 0 },
  // Specialised (bottom row).
  trades: { x: 0, y: 3 },
  mostly_automated: { x: 1, y: 3 },
  part_automated: { x: 2, y: 3 },
  developers: { x: 0, y: 2 },
  operators: { x: 1, y: 2 },
  salespeople: { x: 2, y: 2 },
  audience: { x: 3, y: 3 },
};

/** Fallback position for any kind not in the table: bottom-right, scaled by index. */
function positionFor(kind: string, index: number): { x: number; y: number } {
  if (POSITIONS[kind]) return POSITIONS[kind];
  // Distribute unknown kinds across a 4x4 grid by their index.
  const col = index % 4;
  const row = Math.floor(index / 4) % 4;
  return { x: col, y: row };
}

const GRID_COLS = 4;
const GRID_ROWS = 4;
const SVG_WIDTH = 720;
const SVG_HEIGHT = 480;
const PADDING = 40;

/**
 * The graph itself. An SVG with 16 nodes, sized by pack count. Each node is
 * a `<Link>` so the keyboard path is identical to the mouse path.
 */
export default function CategoryGraph({ categories, filterPath, className }: CategoryGraphProps) {
  const cellW = (SVG_WIDTH - PADDING * 2) / GRID_COLS;
  const cellH = (SVG_HEIGHT - PADDING * 2) / GRID_ROWS;
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

  const pathFor = filterPath ?? ((kind: string) => `/?kind=${encodeURIComponent(kind)}`);

  return (
    <div
      className={cx(
        'rounded-md border border-border bg-surface p-4 md:p-6',
        className,
      )}
    >
      {/*
        `overflow-x-auto` + `minWidth: SVG_WIDTH` on the svg itself, not just `w-full`.
        `viewBox` scales the WHOLE svg as one vector -- including the label `fontSize`, which is
        set in the same user-space units as everything else (see `wrapLabel`'s LABEL_FONT_PX
        below). At >=720px of container width that upscales cleanly, which is why this looked
        fine on desktop. At a ~320px mobile container it downscales to ~0.44x, so the 11-unit
        label rendered at ~5px -- confirmed on the live mumchimp.com/ideas mobile view, 2026-08-09
        -- with nothing in this file setting a floor. Capping the svg's own width at its native
        720 keeps every label at its designed, legible size at every viewport; the tradeoff is a
        horizontal scroll on phones, which is the standard way to keep a diagram legible rather
        than shrinking it below reading size (the full text list already below this graph on
        /ideas remains the no-scroll fallback for anyone who does not scroll it).
      */}
      <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="h-auto w-full"
        style={{ minWidth: SVG_WIDTH }}
        role="img"
        aria-label="Catalogue categories, sized by pack count"
      >
        {categories.map((node, i) => {
          const pos = positionFor(node.kind, i);
          const cx = PADDING + cellW * (pos.x + 0.5);
          const cy = PADDING + cellH * (pos.y + 0.5);
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
      </div>
      <p className="mt-3 text-center text-caption text-muted">
        Tap a node to filter the catalogue. Node size reflects pack count.
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

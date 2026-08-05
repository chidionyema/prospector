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
  const radiusFor = (count: number): number => {
    const t = (count - minCount) / range;
    return 24 + t * 32;
  };

  const pathFor = filterPath ?? ((kind: string) => `/?kind=${encodeURIComponent(kind)}`);

  return (
    <div
      className={cx(
        'border border-border bg-surface p-4 md:p-6',
        className,
      )}
    >
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="h-auto w-full"
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
              <text
                x={cx}
                y={cy + 4}
                textAnchor="middle"
                className="pointer-events-none select-none"
                fontSize={Math.max(10, r / 3.2)}
                fontWeight={600}
                fill="var(--text)"
              >
                {truncate(node.label, Math.floor(r / 6))}
              </text>
              <text
                x={cx}
                y={cy + r + 14}
                textAnchor="middle"
                className="pointer-events-none select-none"
                fontSize={10}
                fontWeight={500}
                fill="#78716C"
              >
                {node.count} packs
              </text>
            </Link>
          );
        })}
      </svg>
      <p className="mt-3 text-center text-caption text-muted">
        Tap a node to filter the catalogue. Node size reflects pack count.
      </p>
    </div>
  );
}

function truncate(s: string, maxChars: number): string {
  if (s.length <= maxChars) return s;
  return `${s.slice(0, Math.max(0, maxChars - 1))}\u2026`;
}

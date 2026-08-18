import React from 'react';
import Link from 'next/link';

import { cx } from '@/components/ui/cx';

/**
 * THE MOSAIC (MASTER-BRIEF §7 `/collections`): tiles sized by pack count.
 *
 * A grid of equal tiles says every collection is the same size. They are not: measured against the
 * live shelf, the largest holds several times what the smallest does, and a reader choosing where
 * to start is choosing partly on that. Sizing the tile by its count puts the answer in the layout,
 * where it is read before any number is.
 *
 * SIZE IS BANDED, NOT PROPORTIONAL. A tile with area proportional to its count would make the
 * smallest collections unreadable at 390px -- a five-pack tile beside a forty-pack tile is a
 * postage stamp -- and a link a thumb cannot hit is worse than a link that understates its size.
 * Three bands keep every tile at a legible minimum while still ranking the shelf by eye.
 *
 * EVERY TILE IS A PRE-FILTERED CATALOGUE URL, NOT A PAGE. The brief is explicit, and it is the
 * difference between sixteen shelves and sixteen documents to maintain: the collection is a VIEW
 * of the catalogue, so it must be the catalogue with a filter applied, sharing its cards, its
 * sort, its counts and its empty state. A separate page style is a second catalogue that drifts.
 *
 * THE SHORT NAME IS THE ONE THAT RENDERS. `Landing.h1` is written for a search engine ("Business
 * ideas where most of the work is automatable") and the live page CSS-truncated it to "Busin…".
 * §9 forbids truncating by character budget and the brief asks for a short display name instead,
 * so the tile takes `name` and the long form stays in the title attribute and on the page itself.
 */

export interface MosaicTile {
  /** The collection slug, used to build the catalogue URL. */
  slug: string;
  /** The SHORT display name. Never the SEO h1. */
  name: string;
  /** The long name, for the title attribute and assistive tech. */
  longName: string;
  /** How many packs are in it. Drives the band. */
  count: number;
}

export interface CollectionMosaicProps {
  tiles: readonly MosaicTile[];
  className?: string;
}

/**
 * Which of three size bands a tile falls in, measured against the biggest collection on the shelf
 * rather than against a typed threshold -- the shelf grows, and a hardcoded "40 is big" would make
 * every tile large the month the catalogue doubles.
 */
export function bandFor(count: number, max: number): 0 | 1 | 2 {
  if (max <= 0) return 0;
  const share = count / max;
  if (share >= 0.66) return 2;
  if (share >= 0.33) return 1;
  return 0;
}

/* Written out as literals, never built from a template. Tailwind scans source text for class
   names, so `col-span-${n}` produces no rule at all and the tile silently collapses to one
   column -- the same failure mode as an unmapped colour token, and just as invisible in review. */
const BAND_CLASS = [
  'sm:col-span-2 sm:row-span-1',
  'sm:col-span-3 sm:row-span-1',
  'sm:col-span-3 sm:row-span-2',
] as const;

const BAND_TITLE = ['text-body', 'text-h3', 'text-h3'] as const;

export function CollectionMosaic({ tiles, className }: CollectionMosaicProps) {
  const shown = tiles.filter((t) => t.count > 0);
  if (shown.length === 0) return null;

  /* Biggest first, ties broken by name, so the mosaic is identical between visits. A layout that
     reshuffles on every render is not a signature and is not learnable. */
  const ordered = [...shown].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const max = ordered[0].count;

  return (
    <ul
      className={cx(
        'grid list-none grid-cols-1 gap-3 p-0 sm:auto-rows-[7rem] sm:grid-cols-6',
        className,
      )}
    >
      {ordered.map((tile) => {
        const band = bandFor(tile.count, max);
        return (
          <li key={tile.slug} className={BAND_CLASS[band]}>
            <Link
              href={`/collections/${tile.slug}`}
              title={tile.longName}
              className="flex h-full min-h-[5.5rem] flex-col justify-between rounded-card border border-line bg-surface p-4 transition-colors hover:bg-surface3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link focus-visible:ring-offset-2"
            >
              {/* The accessible name is the LONG one. A screen reader user hearing "Evenings, 12
                  packs" out of context has less than a sighted reader who can see the heading the
                  mosaic sits under, so the tile carries the full sentence for them. */}
              <span className={cx('font-semibold leading-snug text-text', BAND_TITLE[band])}>
                <span aria-hidden>{tile.name}</span>
                <span className="sr-only">{tile.longName}</span>
              </span>
              <span className="mt-3 font-mono text-caption tabular-nums text-subtle">
                {tile.count} {tile.count === 1 ? 'pack' : 'packs'}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export default CollectionMosaic;

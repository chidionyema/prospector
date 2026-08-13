import React from 'react';
import Link from 'next/link';
import { cx } from '@/components/ui/cx';

export interface CategoryNode {
  /** The landing slug. Passed to `filterPath` to build the href. */
  kind: string;
  /** Buyer-facing label. */
  label: string;
  /** Number of packs in this category. */
  count: number;
  /** One line about what the category is. */
  description?: string;
  /**
   * `Landing.kind` -- payer / commitment / effort / advantage / mechanism / sector. This is the
   * "relatedness" US-7 asked the graph to make visible; see the note on GROUPS below.
   */
  group?: string;
  /** Pre-formatted GBP range for the packs behind this category, or null when none parses. */
  price?: string | null;
}

export interface CategoryGraphProps {
  categories: CategoryNode[];
  /**
   * The path a category navigates to. Default: `/?kind=<slug>` so the home page's filter picks
   * it up.
   */
  filterPath?: (kind: string) => string;
  /**
   * Group the rows by facet, with a caption per group. Off while a search is running: once a
   * query is typed the facet a result belongs to is no longer what is being looked at, and
   * captions over one-row groups read as noise.
   */
  grouped?: boolean;
  className?: string;
}

/**
 * The catalogue's categories, grouped by facet, each with its packs drawn one mark per pack.
 *
 * WHAT THIS REPLACED, AND WHY (US-7, audit §4.5)
 * ----------------------------------------------
 * This component was a 4x4 grid of grey circles in an SVG, sized by pack count, with the label
 * wrapped underneath. Two things were wrong with it, and only one of them was fixable by tuning.
 *
 *  1. IT WAS THE SECOND OF TWO OBJECTS LISTING THE SAME 14 CATEGORIES. `/ideas` rendered this
 *     graph under "Browse the shape of the catalogue" and then rendered every one of the same
 *     categories again under "All categories", with a description and a price range the graph
 *     did not have. Measured at 1440x900 on 2026-08-13 the two objects together ran from y=576
 *     to y=3980, and the first 950px of that was the circles: one navigation, twice, on the page
 *     whose whole job is showing a visitor what the catalogue contains.
 *  2. THE "RELATEDNESS" IT CLAIMED TO SHOW WAS INVISIBLE. The 4x4 POSITIONS table encoded the
 *     facet family (payer on row 0, mechanism on row 2, sector on row 3) -- and nothing on
 *     screen said so. No caption, no rule, no grouping cue. A visitor saw fourteen grey circles
 *     in a ragged grid whose last row held two of four, with two-line captions running into the
 *     row beneath. The information was in the source, not on the page.
 *
 * So the two objects are now ONE object, and the grouping is stated rather than encoded: a
 * caption per facet family ("Who pays for it", "Hours it needs from you", ...), taken from the
 * section headings `lib/seo/landings.ts` already organises itself by. US-7's requirements all
 * survive -- one node per category, size carries the pack count, every node is a `<Link>` so the
 * keyboard path equals the mouse path -- but they are carried by a row, not a circle, which is
 * what lets the description and the price range live in the same object instead of a second one.
 *
 * WHY MARKS AND NOT A BAR. One mark per pack is the same figure the home page draws for the whole
 * population (`PopulationField`, "one mark each") and the same one a pack's sources are drawn with
 * (`EvidenceBar`), in the same green that means "on the shelf" there. A category with 28 packs is
 * 28 marks: countable, not a length the eye has to trust. A bar of arbitrary scale would have been
 * a fifth way of drawing a quantity on a site that already has one.
 */

/**
 * The facet families, in the order `LANDINGS` declares them, with the captions that file already
 * uses as its own section headings. Anything whose `group` is not one of these still renders --
 * see `rest` below -- because a category silently vanishing from the page that exists to list
 * every category is the one failure this component must not have.
 */
const GROUPS: { key: string; label: string }[] = [
  { key: 'payer', label: 'Who pays for it' },
  { key: 'commitment', label: 'Hours it needs from you' },
  { key: 'effort', label: 'How much is automated' },
  { key: 'advantage', label: 'Skills you already have' },
  { key: 'mechanism', label: 'How it makes money' },
  { key: 'sector', label: 'Sector' },
];

/** Marks stop growing past this many; beyond it the run would outgrow its column. */
const MAX_MARKS = 40;

function CategoryRow({ node, href }: { node: CategoryNode; href: string }) {
  const marks = Math.min(node.count, MAX_MARKS);
  return (
    <li>
      <Link
        href={href}
        aria-label={`${node.label}, ${node.count} pack${node.count === 1 ? '' : 's'}${node.price ? `, ${node.price}` : ''}`}
        className={cx(
          'group -mx-3 grid gap-x-8 gap-y-3 rounded-md px-3 py-4',
          'border-t border-border',
          'transition-colors duration-[140ms] ease-[cubic-bezier(0.2,0,0,1)] hover:bg-surface2',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-focus',
          'md:grid-cols-[minmax(0,1fr)_auto] md:items-baseline',
        )}
      >
        <span className="min-w-0">
          <span className="block text-body font-semibold leading-snug text-text transition-colors group-hover:text-accent">
            {node.label}
          </span>
          {node.description && (
            <span className="mt-1 block max-w-[64ch] text-meta leading-relaxed text-muted">
              {node.description}
            </span>
          )}
        </span>

        <span className="flex items-center gap-4 md:justify-end">
          {/* Presentational: the count is spelled out immediately to the right of it, and the
              link's own aria-label carries both. A screen reader must not walk 28 pickets. */}
          <span aria-hidden className="flex items-end gap-[1.5px]">
            {Array.from({ length: marks }, (_, i) => (
              <span key={i} className="block h-3 w-[1.5px] bg-survive" />
            ))}
          </span>
          <span className="w-[3ch] text-right font-mono text-caption tabular-nums text-text">
            {node.count}
          </span>
          {/* The price shows at every width. It was `hidden sm:block` and that dropped the one
              fact a buyer is scanning for on the narrowest screen, where the choice is hardest --
              measured at 390px on 2026-08-13, the row used ~110px of 326 and had the room. Only
              the fixed 18ch column is held back to `sm`, because a fixed column is what makes the
              prices line up, and below `sm` there is nothing to line them up against. */}
          {node.price && (
            <span className="font-mono text-caption tabular-nums text-subtle sm:w-[18ch] sm:text-right">
              {node.price}
            </span>
          )}
        </span>
      </Link>
    </li>
  );
}

export default function CategoryGraph({ categories, filterPath, grouped = true, className }: CategoryGraphProps) {
  const pathFor = filterPath ?? ((kind: string) => `/?kind=${encodeURIComponent(kind)}`);

  const sections = React.useMemo(() => {
    if (!grouped) return [{ key: 'all', label: null as string | null, rows: categories }];
    const known = new Set(GROUPS.map((g) => g.key));
    const out = GROUPS.map((g) => ({
      key: g.key,
      label: g.label as string | null,
      rows: categories.filter((c) => c.group === g.key),
    })).filter((s) => s.rows.length > 0);
    const rest = categories.filter((c) => !c.group || !known.has(c.group));
    if (rest.length > 0) out.push({ key: 'rest', label: 'Everything else', rows: rest });
    return out;
  }, [categories, grouped]);

  return (
    <div className={cx('grid gap-10', className)}>
      {sections.map((section) => (
        <section key={section.key}>
          {/* `.toUpperCase()` on the VALUE, not `uppercase` in the class. House policy (asserted by
              `weightAndCasePolicy.test.ts`): CSS-only caps leave the accessible name in sentence
              case, so a screen reader and the screen disagree about what the caption says, and the
              caps cannot be undone per-locale. The label stays sentence-case in `GROUPS` because
              that is the string, and the caps are the voice. */}
          {section.label && (
            <h3 className="text-caption font-medium tracking-[0.08em] text-subtle">
              {section.label.toUpperCase()}
            </h3>
          )}
          <ul className={cx('list-none p-0', section.label && 'mt-2')}>
            {section.rows.map((node) => (
              <CategoryRow key={node.kind} node={node} href={pathFor(node.kind)} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

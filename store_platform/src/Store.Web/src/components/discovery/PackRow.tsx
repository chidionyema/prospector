import Link from 'next/link';
import React from 'react';

import { Icon } from '@/components/ui/Icon';
import { CATEGORY_LABEL } from '@/components/ui/PackCardHeader';
import { PriceText } from '@/components/ui/Money';
import { cx } from '@/components/ui/cx';
import { marketLabel, type Pack } from '@/lib/api/client';
import { categoryFor } from '@/lib/category';
import { useCurrency } from '@/lib/currency';
import { cardHeading, cardLine, listHeading } from '@/lib/discovery';
import { repairTruncation } from '@/lib/copy';
import { formatPriceForMarket, type Currency } from '@/lib/fx';
import { sourcesLabel } from '@/components/ui/ProofLine';
import { packMarket } from '@/lib/market';
import { packLeadStat, type PackLeadStat } from '@/lib/packStat';
import { trackCardClick } from '@/lib/analytics';
import { useCardImpressions } from '@/lib/useCardImpressions';

/**
 * ONE OF THE SITE'S TWO CARD FORMATS. The other is the Spotlight (`PackCard` in `pages/index.tsx`).
 *
 * The split is by JOB, not by size, and that is the whole reason there are two rather than three:
 * a Spotlight says "consider this one", a Row says "here is the list". The founder's brief
 * (`docs/MOBILE_DESIGN_BRIEF_2026-08-15.md`, Part One item 1) states the rule the site was
 * breaking: never more than one Spotlight in a vertical run, and no two card formats in the same
 * vertical list.
 *
 * WHAT THIS REPLACES. Three formats used to render packs: `lead` and `mid` and `row` weights of
 * `PackCard` (the home shelf ran all three in ONE vertical section, `index.tsx:1686-1755`), plus
 * `DossierCard`, a fourth format used by `PackGrid` on /collections/<slug> and by `SimilarPacks` on the
 * pack page. `mid` and `DossierCard` are both deleted; every surface that browsed packs -- the
 * catalogue tail, the other-market groups, the landing grids, the related rail -- now renders
 * THIS.
 *
 * WHY IT LIVES HERE AND NOT IN `pages/index.tsx`. `PackGrid`'s own docblock argued the opposite
 * ("`PackCard` is deliberately not exported ... this follows the shape `SimilarPacks` already
 * established instead, the same visual language, no shared state") and the outcome is the reason
 * the argument was wrong: "the same visual language" maintained by hand drifted into a different
 * card within days, which `DossierCard`'s own comments record twice -- it kept an 80px near-black
 * plate for a day after the founder had ruled that plate out, and it carried a doc comment
 * claiming to draw "the SAME drawing as `PackCoverArt`" after `PackCoverArt` had been deleted. A
 * shared token that is only shared by intention is not shared.
 *
 * NO BORDER, NO RADIUS, NO CARD CHROME. The divider comes from the parent's `divide-y`: the line
 * between two rows is structural, a box drawn around each row is not.
 */
export function PackRow({
  pack,
  currency,
  viewerMarket,
  viewed = false,
  observeRef,
  position,
}: {
  pack: Pack;
  /**
   * Optional. The home shelf already resolves a currency for the whole page and passes it; the
   * landing grids and the related rail are layout components with no business knowing about
   * money, so they let it come from context. Ambient by default is what stopped a related card
   * quoting GBP beside a converted headline (see `lib/currency.tsx`).
   */
  currency?: Currency;
  /** Suppresses the market flag when it would be true of every row on screen. */
  viewerMarket?: string;
  /** True when this pack is in the reader's `recentlyViewed` cookie. */
  viewed?: boolean;
  /**
   * Counts this row as seen when it scrolls into view. Comes from `useCardImpressions().observe`
   * in the list that renders the row, so one observer serves the whole list.
   *
   * Optional, and absent means the row is not counted. A row that reports a click but no sighting
   * would push the click-through rate above 100% for that surface, so any new call site that
   * tracks clicks must pass this too.
   */
  observeRef?: (node: HTMLElement | null) => void;
  /**
   * 1-based place in the list, sent with the click. Position is most of what a raw click count
   * measures on a long shelf, so the title A/B needs it to tell a better title from a higher one.
   */
  position?: number;
}) {
  const ambient = useCurrency();
  const cur = currency ?? ambient;
  const cat = categoryFor(pack);
  const stat = packLeadStat(pack);
  /* The evidence bar drops its numeral when the lead figure IS the source count: the bar exists
     to make two rows comparable at a glance, and printing the same number twice on one line is
     the duplication the cover removal was about. */
  const evidenceLabel = stat?.kind !== 'sources';
  const { heading, sub } = cardHeading(pack);
  // `repairTruncation` repairs the publish path's character-150 cut; `cardLine` then caps at a
  // word boundary so the row never shows a clause that stops mid-thought. See `cardLine`.
  //
  // THE ROW GETS ITS OWN BUDGET (founder review, 2026-08-16): 6 words, not `cardLine`'s 30-word
  // default. `cardLine`'s default is sized for the Spotlight card, which renders its line with no
  // CSS clamp at all (`pages/index.tsx:402`) -- so a 155-203 char output there just wraps to
  // however many lines it needs and nothing is ever cut. The row is different: the description
  // sits in a `line-clamp-2` box in a column measured at 179px wide on a 390px phone (this file's
  // own docblock above, "the text column runs L=80..R=259"). Measured with the real font
  // (Switzer, 14px/1.4, the site's `--text-meta`) against real prose in that exact column: only
  // 46-57 characters fit on two lines before the clamp starts eating words. That is almost
  // exactly the length of the two examples the founder quoted as broken -- "...the financier
  // covers the difference if copper" is 46 characters, the same number the measurement landed
  // on. At the 30-word default, `cardLine`'s own docblock records a 155-char median: roughly
  // three and a half times too long for this column, which is why the clamp was cutting mid-word
  // and mid-clause instead of never firing. Re-running `cardLine`'s exact algorithm (word cap,
  // then clause-boundary backoff, then dangling-word backoff) at maxWords=6 against five
  // realistic descriptions, the worst case is 2 lines at this column width; maxWords=7 already
  // overflows to 3 on the longest sample. 6 is the highest budget that keeps the clamp a safety
  // net that never fires, at the narrowest supported width.
  const line = cardLine(repairTruncation(pack.oneLine) || sub, 6);
  const price = formatPriceForMarket(pack.price, cur);

  return (
    <Link
      href={`/pack/${pack.id}`}
      /* THE WHOLE ROW IS THE THING SEEN AND THE THING CLICKED, so both halves of the measurement
         hang off this one element. `ref` counts the row as seen when half of it enters the
         viewport; `onClick` counts the click. Rows past the fold on the home shelf are `hidden`
         rather than unmounted, and a `display: none` element never intersects, so a card the
         reader never revealed is correctly not counted as seen. */
      ref={observeRef}
      onClick={() => trackCardClick(pack.id, position)}
      className={cx(
        'group flex items-center gap-4 px-3 py-4 sm:gap-5 sm:px-4',
        // Hover LIFTS to paper (`--surface`) rather than sinking to `--surface3`, which is now
        // the shelf's own ground -- a hover state painted the same colour as the surface under
        // it is not a hover state.
        'transition-colors hover:bg-surface',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      )}
    >
      <span className="min-w-0 flex-1">
        {/* TWO LINES ON A PHONE, ONE FROM `sm` UP. The reported defect was "cuts at ~50% of
            available width while empty space remains", and the space is real but it is not the
            title's to take: measured at 390px the text column runs L=80..R=259 and the price
            group starts at L=275, so the column ALREADY fills everything up to the 16px gap.
            The title needs 439px against 179px available -- 41% -- so a second line is the only
            thing that actually buys the words back. `line-clamp-2` still ellipses, so a
            pathological title cannot push the row open. */}
        {/* THE TITLE OWNS THE WHOLE COLUMN. The `seen` badge used to sit beside it in a flex
            wrapper, so a `flex-none` chip took its width off the top before the heading got a
            character, and the heading wrapped early around a four-letter word. The badge now
            rides in the meta row below, next to the category label, where it is still visible
            and costs the title nothing (founder, 2026-08-16, item 4).

            TWO LINES AT EVERY WIDTH (2026-08-15, brief item 3). The `sm:truncate` half of this
            is gone: `truncate` is a MID-WORD cut, so the widest viewport was the one place a
            title could still stop inside a word -- "Compliance evidence pack for gel man..." --
            which is the defect the brief names, and it was hiding on desktop precisely because
            it bites only the longest titles. `line-clamp-2` ellipses at a line box instead, so
            a pathological title still cannot push the row open. */}
        {/* RESERVED HEIGHT, not just a two-line cap (founder, 2026-08-16, item 2: "nothing sits
            on a grid" -- row heights varied with content, so the price/category/multiple line
            below landed at a different y on every row). `min-h` reserves the box for two lines
            even when the heading is one line or the pack has no line at all, so every row is the
            same height whether or not its content needs both lines. `text-body` is 1rem/1.55
            (tokens.css), so two line boxes are 2 * 1 * 1.55 = 3.1rem. This is a floor, not a
            fixed height: `line-clamp-2` still governs the ceiling, so a longer heading still
            wraps and clips at two lines instead of pushing the row taller. */}
        <span className="line-clamp-2 block min-h-[3.1rem] text-body font-semibold text-text">
          {listHeading(heading)}
        </span>
        {/* TWO LINES, not one (founder, 2026-08-16, item 3). `truncate` is a single line AND a
            mid-word cut, which is the same defect the title was carrying: `cardLine` had already
            capped the string at a word boundary, and then the one-line box cut it again inside a
            word. `line-clamp-2` fills both lines and ellipses only at a line box.
            RESERVED HEIGHT (item 2, same reasoning as the title above): `text-meta` is
            0.875rem/1.4 (tokens.css), so two line boxes are 2 * 0.875 * 1.4 = 2.45rem. Rendered
            unconditionally now (not gated on `line`) so a pack with no description still holds
            its slot instead of collapsing the row shorter than its neighbours. */}
        <span className="mt-0.5 line-clamp-2 block min-h-[2.45rem] text-meta text-muted">
          {line}
        </span>
        {/* THE CONTAINER WRAPS, and all three of `flex-wrap`, `min-w-0` here and `min-w-0` on the
            figure are load-bearing. Without them nothing on this line could yield, so the row
            overflowed and its items collided -- one cause behind three separately reported
            defects (overlapping meta items, the bar running past the padding, and the title
            truncating early because the overflow stole its space). */}
        <span className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {/* A FIXED COLUMN from `sm`, so the figure lands on the same x on every row. Sector
              labels run from "Sector" to "Care and benefits claims", so at natural width the
              figure started at a different x on nearly every row -- and on an untagged pack the
              slot collapsed and the whole run jumped left. That ragged left edge is what makes a
              column of rows read as unaligned even though every row is built identically. An
              untagged pack leaves the column EMPTY instead of closing it. Below `sm` the line
              wraps anyway, so a fixed column there would only steal width from a 390px row. */}
          {cat.tagged ? (
            <span className={cx('flex-none truncate text-caption sm:w-44', CATEGORY_LABEL, cat.ink)}>
              {cat.label.toUpperCase()}
            </span>
          ) : (
            <span className="hidden flex-none sm:block sm:w-44" aria-hidden />
          )}
          {/* The badge's new home. It reads as what it is here -- a note about the reader's own
              history, sitting with the other row metadata -- instead of competing with the title
              for the first line. */}
          {viewed && <span className="flex-none font-mono text-caption text-subtle">seen</span>}
          {stat && <PackFigure stat={stat} weight="row" />}
          {/* A NUMBER, not a bar (founder, 2026-08-16, item 5: "the sparkline is decoration
              wearing data's clothes"). The bar this replaced was `<EvidenceBar count=...
              label={false} cap={14} />` -- 12px ticks with no numeral, so a reader could not
              tell 6 sources from 14 without counting marks on a row. `evidenceLabel` only true
              when `stat.kind !== 'sources'` (declared above), i.e. exactly the branch where the
              row's lead figure is the price multiple, NOT the source count -- so this is the
              only place on the row the count is shown as text; `PackFigure` shows the multiple,
              not the count, in this branch. Confirmed by reading `packStat.ts` and `PackFigure`
              before cutting the bar: the count does not survive elsewhere in this branch, so
              cutting it silently would have dropped information rather than just decoration. */}
          {evidenceLabel && typeof pack.sourceCount === 'number' && pack.sourceCount > 0 && (
            <span className="flex-none font-mono text-caption text-subtle">
              {sourcesLabel(pack.sourceCount)}
            </span>
          )}
          {/* COMPARE LIKE WITH LIKE. `groupByMarket` buckets on `packMarket(pack)`, which
              case-folds and applies the null-is-uk rule, so testing the RAW field here would flag
              a correctly-placed pack as foreign on any casing variance. The guard on the raw
              field stays: a pack carrying no market makes no claim about jurisdiction. */}
          {pack.market && packMarket(pack) !== viewerMarket && (
            <span className="flex-none font-mono text-caption text-warning">
              {/* "market", not "rules" (founder, 2026-08-15). The flag warns that this pack is
                  for somewhere else, and somewhere else is the whole market -- the buyers, the
                  prices and the numbers -- not only its statute book. "US rules" also reads as a
                  claim that the pack is a compliance document, which it is not. */}
              {marketLabel(pack.market)} market
            </span>
          )}
        </span>
      </span>

      <span className="flex flex-none items-center gap-3 sm:gap-4">
        <PriceText className="text-body">{price}</PriceText>
        {/* THE ARROW IS A HOVER AFFORDANCE, so it costs 32px on the one device that cannot hover.
            Its whole job is `group-hover:translate-x-0.5`; on touch that never fires and the
            entire row is already a link. Handing those 32px back to the text column is what takes
            the two-line title from 358px of its 439px to 412px. */}
        <Icon
          name="arrowRight"
          size={15}
          className="hidden text-subtle transition-transform group-hover:translate-x-0.5 sm:block"
        />
      </span>
    </Link>
  );
}

/**
 * THE CARD'S VISUAL, AND IT IS A NUMBER. Shared by the Row and the Spotlight.
 *
 * The shelf card had no visual at all after the generated cover was removed on 2026-08-14: the
 * plate was a frame drawn for photography this shop does not have, and the mark inside it was a
 * hash of the pack id, which encodes nothing about the pack. What replaces them is the pack's own
 * strongest figure set at display-adjacent size -- a genuine visual that cannot be unearned,
 * because it is a number the engine computed about THIS pack. Which number, and the ladder that
 * guarantees it is never blank, is `lib/packStat.ts`.
 *
 * ONE DEVICE AT TWO SIZES, not two treatments (it was three; the `mid` weight is deleted with the
 * card format that used it). Figure over label on the Spotlight, figure beside label on the Row,
 * because a row has one line and no column to stack in.
 *
 * MONO ON THE FIGURE, SANS ON THE LABEL, and here the mono IS earned: tokens.css §3.2 states the
 * rule as "monospace is the site's promise that a string is checkable", and this is the engine's
 * own count. `tabular-nums` so two rows' figures align down a column, which is the whole point of
 * putting the same number in the same place on every one.
 */
export function PackFigure({
  stat,
  weight,
}: {
  stat: PackLeadStat;
  weight: 'spotlight' | 'row';
}) {
  if (weight === 'row') {
    /* `min-w-0` HERE AND ON THE LABEL, and the parent must be able to wrap. All three, or the row
       breaks in one of two opposite ways. The reported defect was collision: at 390px "48" printed
       over "US rules" as "48S rules". The cause was `min-w-0` on a box whose PARENT could not wrap
       and had no `min-w-0` of its own, so the meta line overflowed, this box was squeezed toward
       zero, and the `flex-none` digits painted outside their own box onto the next item. Removing
       `min-w-0` here stopped the collision by refusing to shrink at all -- measured at 390px, this
       box then sat at W=229 inside a W=179 column, hanging 50px into the price's lane. 229 is the
       automatic minimum size: `truncate` carries `white-space: nowrap`, so the label's min-content
       contribution is the whole 199px text run. `min-w-0` on the label sets the LABEL's own used
       minimum; only the parent's own `min-w-0` stops it being floored by that run. */
    return (
      <span className="flex min-w-0 max-w-full shrink items-baseline gap-1.5">
        <span className="flex-none font-mono text-body font-semibold tabular-nums text-text">
          {stat.figure}
        </span>
        <span className="min-w-0 truncate text-caption text-muted">{stat.label}</span>
      </span>
    );
  }

  return (
    <span className="block">
      <span className="block font-mono text-display tabular-nums leading-none text-text">
        {stat.figure}
      </span>
      <span className="mt-1.5 block text-meta text-muted">{stat.label}</span>
    </span>
  );
}

/**
 * A vertical list of Rows with the structural hairlines between them.
 *
 * Every surface that lists packs uses this, so "the divider is the parent's job" is enforced by
 * there being one parent rather than by four call sites remembering `divide-y`.
 */
export function PackRowList({
  packs,
  currency,
  viewerMarket,
  viewedIds,
  className,
}: {
  packs: readonly Pack[];
  currency?: Currency;
  viewerMarket?: string;
  viewedIds?: ReadonlySet<string>;
  className?: string;
}) {
  /* ONE OBSERVER FOR THE WHOLE LIST, and it is created before the empty-list return because a
     hook cannot run conditionally. Every surface that lists packs comes through here, so wiring
     the count once here covers the related rail, the landing grids and the recently-viewed strip
     without each of them remembering to. The home shelf's own tail is the exception: it renders
     `PackRow` directly to keep its per-row `hidden` class, so it runs its own copy of this hook. */
  const { observe } = useCardImpressions();
  if (packs.length === 0) return null;
  return (
    <ul className={cx('divide-y divide-border', className)}>
      {packs.map((pack, i) => (
        <li key={pack.id}>
          <PackRow
            pack={pack}
            currency={currency}
            viewerMarket={viewerMarket}
            viewed={viewedIds?.has(pack.id) ?? false}
            observeRef={observe(pack.id)}
            position={i + 1}
          />
        </li>
      ))}
    </ul>
  );
}

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
import { CardProof } from '@/components/ui/ProofLine';
import { packMarket } from '@/lib/market';
import { paybackMultiple, type PackLeadStat } from '@/lib/packStat';
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
 * `DossierCard`, a fourth format used by `PackGrid` on /ideas/<slug> and by `SimilarPacks` on the
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
  className,
}: {
  pack: Pack;
  /** Extra classes on the row itself. The home shelf hides its beyond-fold rows this way, because
      the rows must stay DIRECT children of the drawing's `.rows` card: a wrapping `<li>` makes
      every row its own parent's last child, and `.row:last-child{border-bottom:0}` then deletes
      every divider in the list. */
  className?: string;
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
  /* `packLeadStat` is gone from the ROW. It returns a figure welded to a sentence sized for the
     featured card's 44px `.stat`, and the row now renders `CardProof`, which takes the two raw
     numbers and supplies the drawing's own nouns. The `evidenceLabel` flag went with it: it
     existed to stop the row printing the source count twice, and there is now one place that
     prints it. */
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
  // RAISED FROM 6 TO 26, 2026-08-18. The reasoning above is sound for the column it was measured
  // in and that column no longer exists: the description ran beside a fixed 176px sector label in
  // a flex row, so six words was all that fitted on two lines. The row is the drawing's `.row`
  // now -- the sector moved up to an eyebrow and the text column runs the full width at 56ch --
  // and at six words the founder was reading truncated fragments on a wide screen: "AI turns
  // sound-meter readings and site", "An AI tool that pulls Florida", "Works out what a flat
  // owner". Those are not descriptions, they are the first half of one.
  //
  // 56ch over two lines is about 112 characters. At `cardLine`'s recorded 155-char median a 26
  // word budget lands just under that, so the clause-boundary backoff does the cutting at a comma
  // and `line-clamp-2` stays the safety net it was meant to be rather than the thing a reader
  // meets on every row.
  // NO WORD BUDGET (2026-08-18, fix prompt D3a). The 6-then-26 word cap argued above was a
  // server-side cut, and the founder read its output on the live shelf: "the tool emits a",
  // "turns every", "enabling UK deep-tech". `Infinity` keeps the first-sentence normalisation
  // and drops the cap; `.row .d`'s `-webkit-line-clamp:2` is the only clamp, and it clamps at
  // a rendered line rather than at a word count guessed from a column width.
  const line = cardLine(repairTruncation(pack.oneLine) || sub, Infinity);
  const price = formatPriceForMarket(pack.price, cur);
  const offMarket = Boolean(pack.market) && packMarket(pack) !== viewerMarket;

  /* THE DRAWING'S ROW (`mockups/index.html`, `.rows > a.row`). It emits the drawing's own class
     names, which `src/styles/mumchimp.css` styles: a two-column grid, the text in column one and
     the price stack in column two spanning all four rows. Every Tailwind class that used to
     re-state those numbers is gone, because the copied stylesheet already carries them. */
  return (
    <Link
      href={`/pack/${pack.id}`}
      ref={observeRef}
      onClick={() => trackCardClick(pack.id, position)}
      className={cx('row', className)}
    >
      {(cat.tagged || offMarket) && (
        <span className="top">
          {cat.tagged && <span className="eyebrow">{cat.label.toUpperCase()}</span>}
          {viewed && <span className="new">Seen</span>}
          {/* The market note. It is the one thing on the row that is about the READER rather
              than the pack, and a buyer who misses it buys research written for another country.
              It sits in the eyebrow, NOT in `.proof`: the proof line has exactly two forms
              ("41 sources", "17x payback . 28 sources") and anything else inside it is a third.
              "US . CA", not "US . CA market": the word restated what the border already says. */}
          {offMarket && pack.market && (
            <span className="market">{marketLabel(pack.market)}</span>
          )}
        </span>
      )}
      <h3>{listHeading(heading)}</h3>
      <p className="d">{line}</p>
      {/* ONE PROOF LINE (2026-08-18, fix prompt D4). This emitted up to three formats on one
          shelf -- "38 sources", "16 cited sources behind it", "2x the price back in month one,
          modelled" -- because the figure came from `packLeadStat`, whose labels are written for
          the 44px `.stat` device on the featured card, not for a 12.5px row. The longest of them
          also carried `truncate` (nowrap), which is what pushed the line past the right edge of
          the card at 390px. `CardProof` renders the drawing's own two forms and nothing else. */}
      <CardProof sources={pack.sourceCount} payback={paybackMultiple(pack)} />
      <span className="side">
        <PriceText className="price num">{price}</PriceText>
        <span className="view">View &rarr;</span>
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

  /* THE DRAWING'S `.stat` (`mockups/index.html` section 7): the figure at 44px and its label on
     the same baseline. It was two Tailwind spans re-stating those numbers; the copied stylesheet
     already carries them, and a hand-kept copy is how the featured card drifted from the drawing
     in the first place. */
  /* A `div`, not a `span`: `mockups/index.html` section 7 writes `<div class="stat">`, and
     `.stat` is `display:flex` (mumchimp.css:333). Structural parity compares tag names, because a
     block element and an inline one lay their children out differently the moment a utility or a
     browser default touches them. */
  return (
    <div className="stat">
      <span className="big num">{stat.figure}</span>
      <span className="lbl">{stat.label}</span>
    </div>
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
    /* THE DRAWING'S `.rows`: the whole list is one card -- white surface, 1px hairline, 12px
       radius, `overflow-hidden` so the first and last rows clip to the corners. It was a bare
       `divide-y` on the page ground, so a run of rows had no edges and read as loose text rather
       than as a shelf. */
    /* NO <ul>/<li>. The drawing's `.row:last-child{border-bottom:0}` is what removes the hairline
       above the card's bottom edge, and with a <li> between the container and the row every row
       is its own parent's last child, so the rule fires on all of them and the list loses every
       divider. The rows are links in a box; a list wrapper bought nothing else. */
    <div className={cx('rows', className)}>
      {packs.map((pack, i) => (
        <PackRow
          key={pack.id}
          pack={pack}
          currency={currency}
          viewerMarket={viewerMarket}
          viewed={viewedIds?.has(pack.id) ?? false}
          observeRef={observe(pack.id)}
          position={i + 1}
        />
      ))}
    </div>
  );
}


/*
 * THE DRAWING'S THREE-UP TILES (`mockups/index.html` section 5, `.three > a.htile`).
 *
 * The landing page showed its newest packs as three more rows, so the page ran as one unbroken
 * column of rows from the hero to the footer. The drawing breaks that column once, with three
 * tiles, and the copied stylesheet already carries every number they need.
 */
export function PackTileGrid({
  packs,
  currency,
  viewedIds,
  className,
}: {
  packs: Pack[];
  currency?: Currency;
  viewedIds?: Set<string>;
  className?: string;
}) {
  const ambient = useCurrency();
  const cur = currency ?? ambient;
  if (packs.length === 0) return null;
  return (
    <div className={cx('three', className)}>
      {packs.map((pack, i) => {
        const cat = categoryFor(pack);
        const { heading, sub } = cardHeading(pack);
        return (
          <Link
            key={pack.id}
            className="htile"
            href={`/pack/${pack.id}`}
            onClick={() => trackCardClick(pack.id, i + 1)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
              <span className="eyebrow">{cat.label}</span>
              {viewedIds?.has(pack.id) && <span className="new">Seen</span>}
            </div>
            <h4>{listHeading(heading)}</h4>
            <p>{cardLine(repairTruncation(pack.oneLine) || sub, Infinity)}</p>
            <span className="foot">
              {/* The same one proof line as the row (fix prompt D4), rendered as a `span`:
                  `.foot` is a `<span>` here, and a `<p>` inside it is invalid nesting. */}
              <CardProof as="span" sources={pack.sourceCount} payback={paybackMultiple(pack)} />
              <PriceText className="price num">{formatPriceForMarket(pack.price, cur)}</PriceText>
            </span>
          </Link>
        );
      })}
    </div>
  );
}

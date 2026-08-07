import { formatGbp, type LadderRung } from '@/lib/priceRange';
import { PACK_CONTENTS } from '@/components/marketing/PackContents';
import { cx } from '@/components/ui/cx';

/*
  THE PRICING PAGE HAS ONE IDEA. THIS IS IT, DRAWN.

  WHAT WAS THERE. Two paragraphs under the heading "Why one pack is £29 and another is £199",
  saying that price follows the size of the opportunity and never the size of the download. Both
  sentences are correct and neither is legible: the claim is a COMPARISON between two quantities,
  one that varies and one that does not, and a comparison set as prose asks the reader to hold both
  series in their head and do the differencing themselves. Almost nobody does. So the single
  objection this page exists to answer -- "am I being charged more for more paper?" -- was answered
  in a form that reads as reassurance rather than as evidence.

  WHY A DRAWING SETTLES IT AND A SENTENCE DOES NOT. The argument is entirely about the SHAPE of two
  columns placed side by side. One climbs. The other is the same token repeated at every height,
  identically, all the way down. A reader takes that in without reading a word, and can then check
  it: every rung here is a price the catalogue actually charges, and the constant column is
  `PACK_CONTENTS.length`, the same list rendered on the pack page and in the buyer's download.

  WHERE THE RUNGS COME FROM. `priceLadder(packs)` over the catalogue this request already fetched,
  not the seven rungs declared in `config.yaml:925`. Config states which prices are POSSIBLE; only
  the shelf states which are real, and a drawing of unoccupied rungs would be an illustration
  passed off as a measurement. See the note on `priceLadder` in `lib/priceRange.ts`.

  WHY BAR LENGTH IS RANK, NOT AMOUNT. The bars encode the ORDER of the rungs. Scaling them to the
  amounts would make the ladder a picture of the price, which is the axis the reader can already
  read off the numeral beside it, and would draw the cheapest rung as a 10% stub of the dearest,
  implying the smallest opportunity is a tenth of the largest. Nothing measures that. Rank claims
  only what is defensible: these are steps, in this order.
*/

export function PriceLadder({ rungs, className }: { rungs: LadderRung[]; className?: string }) {
  // Nothing honest to draw from one rung: a ladder with a single step is not a ladder, and the
  // page's own `range.uniform` branch already says "every pack is £X" in words.
  if (rungs.length < 2) return null;

  // Dearest at the top, so the drawing climbs the way the sentence does. The data arrives
  // cheapest-first because that is the useful order for every other consumer.
  const descending = [...rungs].reverse();
  const steps = rungs.length;

  return (
    <figure className={cx('m-0', className)}>
      {/* The two column heads ARE the argument, stated once, in the reader's words rather than
          ours. Everything below is the evidence for them. */}
      <div className="flex items-end justify-between gap-4 border-b border-border pb-3">
        <figcaption className="text-caption text-text">
          what changes: the size of the opportunity
        </figcaption>
        <span className="hidden text-right text-caption text-subtle sm:block">
          what does not: the pack
        </span>
      </div>

      <ul className="list-none p-0">
        {descending.map((rung, i) => {
          // `rank` counts up from the cheapest rung, so the bar grows down the page in the same
          // direction the price does. `+ 1` keeps the cheapest rung from rendering a zero-width
          // bar, which reads as missing data rather than as the bottom step.
          const rank = steps - i;
          const width = (rank / steps) * 100;
          const top = i === 0;
          return (
            <li
              key={rung.amount}
              className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border/60 py-4 last:border-b-0"
            >
              {/* The price. The dearest rung takes the display cut, not because it is the one we
                  want bought, but because a ladder whose every rung is set at the same size is not
                  drawn as a ladder at all. */}
              <span
                className={cx(
                  'w-[5.5rem] flex-none font-mono font-semibold leading-none tracking-tight text-text',
                  top ? 'text-h1' : 'text-h2',
                )}
              >
                {formatGbp(rung.amount)}
              </span>

              {/* The varying axis. `aria-hidden` because it carries no information the row does not
                  already state in text: a screen reader gets the price, the count and the constant
                  document line, which is the whole argument. A bar announced as "70 percent" would
                  invite the reader to believe something was measured at 70 percent. */}
              <span aria-hidden className="flex min-w-[6rem] flex-1 items-center">
                <span
                  className="h-1.5 rounded-full bg-text/80"
                  style={{ width: `${width}%` }}
                />
              </span>

              <span className="w-24 flex-none font-mono text-caption text-subtle">
                {rung.count} pack{rung.count === 1 ? '' : 's'}
              </span>

              {/* The constant. Identical string, identical position, identical size at every rung:
                  the repetition IS the point being made, so it is deliberately not collapsed into
                  a single note at the foot of the figure. Reading down this column and finding it
                  unchanged is the reader verifying the claim for themselves. */}
              <span className="w-full flex-none text-caption text-survive sm:w-auto sm:text-right">
                {PACK_CONTENTS.length} documents, every source cited
              </span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

export default PriceLadder;

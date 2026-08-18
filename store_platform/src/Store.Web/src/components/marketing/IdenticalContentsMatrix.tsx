import React from 'react';

import { cx } from '@/components/ui/cx';

/**
 * THE IDENTICAL-CONTENTS MATRIX (MASTER-BRIEF §7 `/pricing`): five price rungs, and the same
 * fourteen document marks on every single row.
 *
 * IT ANSWERS THE ONLY QUESTION A PRICE LADDER RAISES. A shelf running £29 to £199 makes a reader
 * assume the £29 pack is the cut-down one -- that is what every other ladder they have ever seen
 * means, and it is the reason a cheap tier depresses trust in the whole range rather than widening
 * it. Here the price is a function of the market the idea sits in, not of how much we put in the
 * box, and a paragraph saying so is an assertion. Fourteen identical marks repeated five times is
 * a proof a reader can check by looking.
 *
 * THE REPETITION IS THE MESSAGE, SO IT MUST NOT BE COMPRESSED. The obvious tidy-up is one row of
 * fourteen marks and a note that it applies to all five rungs. That is the same information and it
 * makes no argument at all: the reader has to take our word for the thing they were suspicious of.
 * Drawing it five times is the point, and it costs seventy small marks.
 *
 * ONE SOURCE FOR THE RUNGS. The prices come in as a prop from the catalogue, never typed here. A
 * pricing page carrying its own copy of the ladder is the §5.1 defect in its most expensive form:
 * the number a buyer is quoted on one page and charged on another.
 */

export interface PriceRung {
  /** The rung as rendered, e.g. "£49". Formatted by the caller, from the catalogue. */
  price: string;
  /**
   * What sits on this rung, in plain words. OPTIONAL, and the column disappears when no rung has
   * one.
   *
   * It is optional because the catalogue does not carry it. `LadderRung` (lib/priceRange.ts:98) is
   * an amount and a count, computed from the live shelf, and there is nowhere a per-rung sentence
   * could be read from. Writing one here would be a claim about what a price band contains that no
   * pack record supports, on the page where that matters most.
   */
  description?: string;
  /** How many packs are on it today. */
  count: number;
}

export interface IdenticalContentsMatrixProps {
  rungs: readonly PriceRung[];
  /** How many documents are in every pack. One number, from the pack contents manifest. */
  documents: number;
  className?: string;
}

export function IdenticalContentsMatrix({
  rungs,
  documents,
  className,
}: IdenticalContentsMatrixProps) {
  if (rungs.length === 0 || documents <= 0) return null;

  const marks = Array.from({ length: documents });
  // The column exists only if something can fill it. An empty middle column reads as a table that
  // failed to load, which is worse than a narrower table.
  const hasDescriptions = rungs.some((r) => Boolean(r.description));

  return (
    <figure className={cx('overflow-x-auto', className)}>
      <table className="w-full min-w-[38rem] border-collapse text-left">
        <caption className="sr-only">
          {`Every pack contains the same ${documents} documents, at every price. The price reflects the
            market the idea sits in, not the size of the pack.`}
        </caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2 pr-4 text-caption font-medium text-subtle">Price</th>
            {hasDescriptions && (
              <th scope="col" className="py-2 pr-4 text-caption font-medium text-subtle">What is on this rung</th>
            )}
            <th scope="col" className="py-2 pr-4 text-caption font-medium text-subtle">
              {/* Named, so the row of marks is not a decoration a reader has to interpret. */}
              {documents} documents
            </th>
            <th scope="col" className="w-16 py-2 text-right text-caption font-medium text-subtle">Packs</th>
          </tr>
        </thead>
        <tbody>
          {rungs.map((rung) => (
            <tr key={rung.price} className="border-b border-border align-baseline">
              <td className="py-3 pr-4 font-mono text-body tabular-nums text-text">{rung.price}</td>
              {hasDescriptions && (
                <td className="py-3 pr-4 max-w-[28ch] text-meta leading-snug text-muted">
                  {rung.description}
                </td>
              )}
              <td className="py-3 pr-4">
                {/* NEUTRAL INK, NOT TEAL. §2 gives teal one meaning -- an idea survived the filter
                    -- and a document is not an idea. A tick here in the survivor colour would put
                    a verdict on a contents list. */}
                <span className="flex flex-wrap gap-1" aria-hidden>
                  {marks.map((_, i) => (
                    <span key={i} className="block size-[7px] rounded-sm bg-text" />
                  ))}
                </span>
                <span className="sr-only">{`All ${documents} documents included`}</span>
              </td>
              <td className="py-3 text-right font-mono text-caption tabular-nums text-subtle">
                {rung.count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption className="mt-4 max-w-[68ch] text-meta leading-relaxed text-muted">
        Every pack has the same {documents} documents. The price follows the market the idea is in,
        not how much is in the box, so a cheaper pack is not a smaller one.
      </figcaption>
    </figure>
  );
}

export default IdenticalContentsMatrix;

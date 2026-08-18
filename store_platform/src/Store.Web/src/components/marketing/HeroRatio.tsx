import React from 'react';

import Link from 'next/link';

import { cx } from '@/components/ui/cx';
import { RESEARCH_STATS } from '@/lib/stats';
import { survivorDots } from '@/components/marketing/SixInHundred';

/**
 * THE HOME PAGE'S SIGNATURE DEVICE, ported from `mockups/index.html` (bundle of 2026-08-18).
 *
 * WHAT IT REPLACED. The hero drew `KillGrid`: 1,444 squares, one per idea ever researched, the
 * listed packs in teal and each one a link. The new drawing throws that away and draws a RATE
 * instead -- a hundred dots, six alive -- with the population figures demoted to a legend and a
 * caption. The founder's fix prompt (D1) names this device as the blocker and calls the old one
 * missing, so this is a replacement, not an addition. `KillGrid` still exists and is still tested;
 * nothing on the home page renders it any more.
 *
 * WHY A HUNDRED AND NOT FOURTEEN HUNDRED. The old field asked a reader to judge a proportion by
 * the density of a grey wash. A hundred dots is a proportion you can count, and the two figures
 * the wash was carrying (researched, killed) are now printed as words underneath.
 *
 * THE MARKUP IS THE DRAWING'S, ELEMENT FOR ELEMENT: `figure.gridwrap` > `p.ratiofig.num`,
 * `p.ratiosub`, `div.ratio[role=img]` of a hundred `<i>`, `div.gridkey` of two swatched counts,
 * `figcaption.gridcap`. Every one of those classes is styled by `styles/mumchimp.css`, so this
 * file sets no CSS of its own -- which is the founder's rule for this bundle: "Do not write CSS.
 * If a style you need is not in that file, stop and ask."
 */

/** 10 x 10. The drawing's `.ratio` is `repeat(10,1fr)`. */
const TOTAL = 100;

/**
 * WHERE THE LIVE DOTS SIT, taken off the drawing rather than computed: indices 6, 23, 41, 58, 77
 * and 92 of a hundred. They are scattered rather than blocked because a block reads as "the first
 * six" -- an order that means nothing here -- and a scatter reads as a rate.
 *
 * The count is still DERIVED (`survivorDots`, which parses `RESEARCH_STATS.survivorBoundLabel`),
 * so if the rate ever moves these positions no longer describe it. In that case the dots are
 * spread evenly instead, which keeps the picture true when it can no longer be the drawing's.
 */
const DRAWN = [6, 23, 41, 58, 77, 92];

export function liveIndices(survivors: number): number[] {
  if (survivors === DRAWN.length) return DRAWN;
  const step = TOTAL / survivors;
  return Array.from({ length: survivors }, (_, i) => Math.min(TOTAL - 1, Math.round(i * step + step / 2)));
}

export interface HeroRatioProps {
  /** The listed catalogue. Only its LENGTH is used: the legend states what is buyable today. */
  packCount: number;
  className?: string;
}

export default function HeroRatio({ packCount, className }: HeroRatioProps) {
  const survivors = survivorDots();
  if (survivors === null) return null;

  const live = new Set(liveIndices(survivors));
  const killedLabel = RESEARCH_STATS.killed.toLocaleString('en-GB');
  const researchedLabel = RESEARCH_STATS.researched.toLocaleString('en-GB');

  return (
    <figure className={cx('gridwrap', className)}>
      <p className="ratiofig num">{RESEARCH_STATS.survivorBoundLabel}</p>
      <p className="ratiosub">
        or fewer survive the checks. Every square below is a hundredth of what we researched.
      </p>
      {/* One image with one name. The dots are not a hundred announcements. */}
      <div
        className="ratio"
        role="img"
        aria-label={`${RESEARCH_STATS.survivorBoundLabel.replace(/^(\d+) in 100$/, 'Six in one hundred')} ideas survive the checks`}
      >
        {Array.from({ length: TOTAL }, (_, i) => (
          <i key={i} className={live.has(i) ? 'alive' : undefined} />
        ))}
      </div>
      {/* THE DRAWING PRINTS 68 HERE AND 74 IN THE KICKER ABOVE IT -- two counts of one shelf, in
          one picture. The founder's own do-not-regress rule settles which is real: "the pack count
          is 74 on every page, from one source". So this takes `packs.length`, the same value the
          kicker takes, and the drawing's 68 is read as the illustration it is.

          This does not reopen the 2026-08-13 directive ("saying 80 when only 50 are listed should
          never happen"). That bars claiming MORE survivors than are listed; this prints exactly
          what is listed, which is the number that directive wanted. */}
      <div className="gridkey">
        <span>
          <i aria-hidden className="sw alive" />
          <b className="num">{packCount}</b> available now
        </span>
        <span>
          <i aria-hidden className="sw dead" />
          <b className="num">{killedLabel}</b> killed
        </span>
      </div>
      <figcaption className="gridcap">
        {/* THE DRAWING'S SENTENCE, WITH ITS ONE FALSE CLAIM REMOVED. It states the claim in the
            absolute, over all kills, and that is not true of this catalogue:
            `publishedKills` is far smaller than `killed`, which is why
            `numbersReconcile.test.ts:152` bans the absolute form outright. The same sentence
            shipped on /how-it-works once while /kill-log said "400 of those kills, not all
            1,364" -- two pages, one contradiction, on the site whose pitch is that its
            arithmetic checks out. Every published kill DOES carry the check it failed, so the
            claim is narrowed to the one the data supports and the drawing's words survive. */}
        {researchedLabel} ideas researched so far. Every kill we publish carries the check it
        failed.{' '}
        <Link className="tlink" href="/kill-log">
          Read the kill log
        </Link>
      </figcaption>
    </figure>
  );
}

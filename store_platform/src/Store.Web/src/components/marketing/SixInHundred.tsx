import React from 'react';

import Link from 'next/link';

import { cx } from '@/components/ui/cx';
import { COMMON_CHECKS } from '@/lib/checks';
import { RESEARCH_STATS } from '@/lib/stats';

/**
 * "6 IN 100" (MASTER-BRIEF §7) -- the pack page's signature, above the six gates.
 *
 * A hundred dots, six of them teal. It is the same fact as `survivorBoundLabel`, which the page
 * already prints as words, in the one form a reader takes in without doing arithmetic: they see
 * how much of the field is grey before they read a single number.
 *
 * THE SIX IS PARSED FROM THE LABEL, NEVER TYPED. `RESEARCH_STATS.survivorBoundLabel` is derived
 * from `killed / researched` and re-derives every time the totals are regenerated. A hardcoded 6
 * here would be a second copy of that figure, drifting from the sentence beside it -- which is the
 * exact defect §5.1 of the brief is about (the pack count said four different things). One source,
 * two renderings.
 *
 * IT IS A BOUND, SO THE PICTURE MUST ROUND THE SAFE WAY. The real rate is BELOW the bound, so a
 * field with six teal dots overstates the survivors slightly and understates the kills slightly.
 * That is the honest direction for a claim we are making against ourselves; rounding the other way
 * would print a picture more flattering than the data.
 *
 * IT PRINTS NO COUNT. Six in a hundred is a rate, not a population, so the 2026-08-13 directive
 * (`lib/stats.ts`) is intact: nothing here can be multiplied back into the survivor count, because
 * nothing here names the total the rate applies to.
 *
 * A HUNDRED CIRCLES, NOT ONE PATH. `KillGrid` builds 1,364 dead cells as a single `<path>` because
 * 1,444 nodes is a real cost on a landing page. A hundred is 7% of that, and paying it buys dots
 * that are actually round without a page of arc arithmetic nobody can check. Still zero client JS,
 * still server-rendered, still `aria-hidden` -- the caption underneath carries the meaning.
 */

/** 10 x 10. The field is square because a square reads as "all of them" and a bar does not. */
const SIDE = 10;
const TOTAL = SIDE * SIDE;

/** In user units. Radius 0.3 of a 1-unit pitch leaves a 40% duty cycle, so the dots read as a field
 *  of separate marks rather than a texture. */
/**
 * The teal count, read off the label rather than declared.
 *
 * Returns `null` when the label is not the shape this expects, and the component then renders
 * nothing. A field with the wrong number of teal dots is a false claim; a field that is absent is a
 * missing illustration. The second failure is the one we can live with.
 */
export function survivorDots(label: string = RESEARCH_STATS.survivorBoundLabel): number | null {
  const match = /^(\d+)\s+in\s+100$/.exec(label.trim());
  if (!match) return null;
  const n = Number(match[1]);
  return Number.isInteger(n) && n > 0 && n < TOTAL ? n : null;
}

export interface SixInHundredProps {
  className?: string;
  /** Overridable for the test; production always takes the derived label. */
  label?: string;
}

export function SixInHundred({ className, label }: SixInHundredProps) {
  const survivors = survivorDots(label ?? RESEARCH_STATS.survivorBoundLabel);
  if (survivors === null) return null;

  const dots: React.ReactElement[] = [];
  for (let i = 0; i < TOTAL; i += 1) {
    /* The survivors sit at the end of the field, together. A reader counts a block; they do not
       count a scatter, and a scatter would move between renders unless we seeded it. */
    const alive = i >= TOTAL - survivors;
    dots.push(<i key={i} className={alive ? 'alive' : undefined} />);
  }

  /* `.sigcard` with a `.hd` head, a `.fig` figure, a `.cap` caption, a `.key` legend and a
     `.dotfield` of a hundred dots beside them, then the six `.gate` cells under it. This was an
     SVG figure with a caption; the drawing sets the same fact as markup the stylesheet already
     knows how to draw, and puts the six gates the number is ABOUT in the same card. */
  return (
    <figure className={cx('sigcard', className)}>
      <div className="hd">
        <div>
          <p className="fig num">{RESEARCH_STATS.survivorBoundLabel}</p>
          <figcaption className="cap">
            or fewer get through. This one did. Every check below was run against cited evidence,
            and the pack ships the sources so you can read them yourself.
          </figcaption>
          <p className="key">
            <span>
              <i className="sw9" style={{ background: 'var(--brand)' }} />
              <b>{survivors}</b> passed
            </span>
            <span>
              <i className="sw9" style={{ background: 'var(--dead)' }} />
              <b>{TOTAL - survivors}</b> didn&apos;t pass
            </span>
            <span>
              <Link href="/kill-log" prefetch={false} className="tlink">
                Read why they didn&apos;t pass
              </Link>
            </span>
          </p>
        </div>
        {/* Decoration, not a second sentence. The drawing labels the field as an image, but the
            caption beside it already says the same thing, so a screen reader would hear the rate
            twice. */}
        <div className="dotfield" aria-hidden="true">
          {dots}
        </div>
      </div>
      <div className="gates">
        {COMMON_CHECKS.map((check, i) => (
          <div key={check.id} className="gate">
            <b>{String(i + 1).padStart(2, '0')}</b>
            <span>{check.name}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

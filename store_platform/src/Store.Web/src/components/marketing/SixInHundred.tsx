import React from 'react';

import { cx } from '@/components/ui/cx';
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
const RADIUS = 0.3;

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
    /* The teal dots are the LAST ones in reading order, so the eye crosses the whole grey field
       before it reaches them. Scattering them would be prettier and would also make the picture
       change between renders unless we seeded it, and a signature that moves is not a signature. */
    const alive = i >= TOTAL - survivors;
    dots.push(
      <circle
        key={i}
        cx={(i % SIDE) + 0.5}
        cy={Math.floor(i / SIDE) + 0.5}
        r={RADIUS}
        className={alive ? 'fill-survive' : 'fill-faint'}
      />,
    );
  }

  return (
    <figure className={cx('rounded-card border border-line bg-surface p-4', className)}>
      <svg
        viewBox={`0 0 ${SIDE} ${SIDE}`}
        className="block w-full max-w-[220px]"
        role="presentation"
        aria-hidden="true"
      >
        {dots}
      </svg>
      <figcaption className="mt-3 text-meta leading-relaxed text-muted">
        <span>
          Fewer than {RESEARCH_STATS.survivorBoundLabel} ideas get through.
        </span>{' '}
        This one did. Every check below was run against cited evidence, and the pack ships the
        sources so you can read them yourself.
      </figcaption>
    </figure>
  );
}

export default SixInHundred;

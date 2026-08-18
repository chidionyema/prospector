import React from 'react';

import { cx } from '@/components/ui/cx';
import { RESEARCH_STATS } from '@/lib/stats';
import type { GateBar } from '@/lib/killLog.server';

/**
 * THE ATTRITION CASCADE (MASTER-BRIEF §7 `/how-it-works`): the whole population narrowing gate by
 * gate, with the real kill count subtracted at each one.
 *
 * Every other explanation of a filter on this site is a list of what the checks ARE. This is the
 * only one that shows what they DID, and it is the argument the page exists to make: a reader who
 * watches the bar lose two thirds of its width at one gate understands the filter is real in a way
 * that six paragraphs describing six checks cannot achieve.
 *
 * IT IS BUILT FROM THE SAME `distribution` THE KILL LOG DRAWS. One source, three renderings -- the
 * cause grid, the distribution bars and this. The alternative is a second table of counts on a
 * second page, which is the §5.1 defect the whole data-layer step exists to fix: the live site
 * stated 68, 74 and 63 packs on three pages because three surfaces each counted for themselves.
 *
 * IT PRINTS NO SURVIVOR COUNT, AND THE BRIEF ASKS FOR ONE. §7 says "down to 74". The founder
 * directive of 2026-08-13, which is encoded in `lib/stats.ts` (the count is not exported, only
 * `survivorBoundLabel` is), says that number is never printed. The directive wins, so the last band
 * is drawn to scale and named in words. Nothing is lost from the argument: every SUBTRACTION is a
 * published kill count, so the reader still sees the whole fall, and the rate is stated on the pack
 * pages as a bound. If the directive is lifted, the number goes in the final `<dd>` and nothing
 * else here changes.
 */

/** The minimum drawn width, so a gate that killed eleven ideas is still visibly a gate rather than
 *  a hairline that reads as a rendering fault. */
const MIN_WIDTH_PCT = 0.8;

export interface CascadeStep {
  label: string;
  /** How many were still in at the START of this gate. */
  before: number;
  /** How many this gate killed. */
  killed: number;
}

/**
 * The running subtraction, in the order the causes actually fired.
 *
 * Sorted by size, not by the engine's execution order, and that is a deliberate simplification the
 * page should not pretend otherwise about: the engine is kill-fast, so a cheap gate that fires
 * first takes ideas a later gate would also have killed, and no ordering of a single-cause
 * histogram can recover that. What this shows is honest as stated -- how many ideas each check was
 * the FIRST to kill -- which is exactly what `distribution` counts.
 */
export function cascadeSteps(distribution: readonly GateBar[], researched: number): CascadeStep[] {
  const causes = [...distribution]
    .filter((bar) => bar.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const steps: CascadeStep[] = [];
  let remaining = researched;
  for (const cause of causes) {
    // Never subtract past zero. If the totals and the distribution ever disagree, the cascade
    // must stop rather than draw a negative band and imply a population that does not exist.
    const killed = Math.min(cause.count, remaining);
    if (killed <= 0) break;
    steps.push({ label: cause.label, before: remaining, killed });
    remaining -= killed;
  }
  return steps;
}

export interface AttritionCascadeProps {
  distribution: readonly GateBar[];
  className?: string;
}

export function AttritionCascade({ distribution, className }: AttritionCascadeProps) {
  const { researched } = RESEARCH_STATS;
  const steps = cascadeSteps(distribution, researched);
  if (steps.length === 0) return null;

  const last = steps[steps.length - 1];
  const survived = last.before - last.killed;
  const pct = (n: number) => Math.max((n / researched) * 100, MIN_WIDTH_PCT);

  return (
    <figure className={cx('rounded-card border border-line bg-surface p-4 md:p-6', className)}>
      {/* A description list, not a table: each row is one label and one measurement, and `dl` is
          the shape a screen reader announces as a pair rather than as two unrelated cells. */}
      <dl className="m-0 space-y-3">
        <div>
          <dt className="text-caption text-subtle">Ideas researched</dt>
          <dd className="mt-1 ml-0 flex items-center gap-3">
            <span className="block h-4 bg-text" style={{ width: '100%' }} aria-hidden />
            <span className="w-16 shrink-0 text-right font-mono text-caption tabular-nums text-text">
              {researched.toLocaleString('en-GB')}
            </span>
          </dd>
        </div>

        {steps.map((step, i) => {
          /* THE LAST REMAINDER IS THE SURVIVOR COUNT, so it is not printed.
             Caught by `attritionCascade.test.tsx` on the first run of this component, which is
             exactly the defect the test was written for: the running total is a legitimate number
             on every row except the final one, where "what is left after the last gate" and "how
             many survived" are the same figure. Suppressing only the final band and letting this
             row print it would have satisfied the letter of the check and published the number. */
          const isLast = i === steps.length - 1;
          const left = step.before - step.killed;
          return (
            <div key={step.label}>
              <dt className="text-caption leading-snug text-muted">
                {step.label}
                {/* The subtraction, stated. The bar shows the fall; the number says exactly how
                    far, and this page's whole claim is that the numbers are checkable. */}
                <span className="ml-2 font-mono tabular-nums text-kill-strong">
                  −{step.killed.toLocaleString('en-GB')}
                </span>
              </dt>
              <dd className="mt-1 ml-0 flex items-center gap-3">
                <span className="block h-4 bg-text" style={{ width: `${pct(left)}%` }} aria-hidden />
                {/* Blank, not a dash. `dashFree.test.ts` bans em- and en-dashes from source, and a
                    placeholder glyph would be pretending to say something anyway. The width is
                    kept so the column of numbers above it stays aligned. */}
                <span className="w-16 shrink-0 text-right font-mono text-caption tabular-nums text-subtle">
                  {isLast ? '' : left.toLocaleString('en-GB')}
                </span>
              </dd>
            </div>
          );
        })}

        <div>
          <dt className="text-caption font-medium text-text">What is on the shelf</dt>
          <dd className="mt-1 ml-0 flex items-center gap-3">
            <span className="block h-4 bg-survive" style={{ width: `${pct(survived)}%` }} aria-hidden />
            {/* Deliberately no number. See the docblock: the 2026-08-13 directive, not an oversight
                and not a value we failed to compute. */}
            <span className="w-16 shrink-0" />
          </dd>
        </div>
      </dl>

      <figcaption className="mt-4 max-w-[68ch] text-meta leading-relaxed text-muted">
        Every idea we researched, and the check that was first to kill it. The checks stop at the
        first hard failure, so each idea is counted once, against the cheapest gate that killed it.
      </figcaption>
    </figure>
  );
}

export default AttritionCascade;

import React from 'react';
import { cx } from './cx';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Adds a quiet hover affordance (border-darken + 1px lift) — use for clickable list items. */
  interactive?: boolean;
}

/** Surface container — the quiet, bordered panel the brand leans on (UI-STANDARDS §2).
 *  Restrained register: a hairline border does the separation, not a drop shadow (the off-white
 *  --surface already lifts off the warm --bg). Interactive cards earn a quiet border-darken + 1px
 *  lift on hover rather than a heavier shadow (founder restraint review 2026-06-06). */
export function Card({ interactive = false, className, children, ...rest }: CardProps) {
  return (
    <div
      {...rest}
      className={cx(
        'rounded-lg border border-border bg-surface p-6 card-transition shadow-[0_1px_3px_rgba(0,0,0,0.02)]',
        interactive &&
          'transition-all duration-200 ease-out hover:-translate-y-0.5 hover:shadow-[0_12px_40px_rgba(15,23,42,0.04)] hover:border-primary/40',
        className,
      )}
    >
      {children}
    </div>
  );
}

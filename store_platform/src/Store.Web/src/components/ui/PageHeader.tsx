import React from 'react';
import { cx } from './cx';

export interface PageHeaderProps {
  /** Small uppercase context label above the title (e.g. "Dashboard", "Board"). */
  eyebrow?: string;
  title: React.ReactNode;
  /** One-line context under the title, keep it short and human. */
  description?: React.ReactNode;
  /** Optional right-aligned primary action (a Button or Link). */
  action?: React.ReactNode;
  className?: string;
}

/**
 * The header every authed page wears, eyebrow + title + one-line context + an optional primary action,
 * sitting on a hairline rule. This is the single element that gives the product a "designed" top instead
 * of a page that opens straight into a stack of cards (SITE-POLISH-SPEC §2.2). Restraint register: the
 * title carries the weight (display size, 600), the rule is a hairline, the action is the only colour.
 */
export function PageHeader({ eyebrow, title, description, action, className }: PageHeaderProps) {
  return (
    <header
      className={cx(
        'mb-8 flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between',
        className,
      )}
    >
      <div className="space-y-1.5">
        {eyebrow && (
          <p className="text-caption font-bold uppercase tracking-wide text-eyebrow">{eyebrow}</p>
        )}
        {/* `text-display` is 5.5rem / 88px with no responsive step built into the token, so this
            shipped an 88px heading at every width, including a 390px phone where /account's title
            overflowed its column. Scales up to the token only once there is room for it. */}
        <h1 className="text-h1 font-bold leading-tight tracking-tight text-text sm:text-h1 lg:text-display">{title}</h1>
        {description && <p className="max-w-2xl text-body font-normal leading-relaxed text-muted">{description}</p>}
      </div>
      {action && <div className="shrink-0 sm:pb-0.5">{action}</div>}
    </header>
  );
}

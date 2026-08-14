import React from 'react';
import { cx } from './cx';

export interface PageHeaderProps {
  /** Small context label above the title (e.g. "Dashboard", "Board"). Sentence case, not caps. */
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
 *
 * Brand v3 (2026-08-06): the eyebrow was `text-eyebrow`, a token deleted with the orange accent.
 * In Tailwind v4 an unmapped colour utility emits NO rule at all, so that line had been rendering
 * in inherited body ink -- visually a second, competing title -- rather than as a quiet label.
 */
export function PageHeader({ eyebrow, title, description, action, className }: PageHeaderProps) {
  return (
    <header
      className={cx(
        'mb-8 flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between',
        className,
      )}
    >
      <div>
        {eyebrow && <p className="mb-2 text-caption font-medium text-subtle">{eyebrow}</p>}
        {/* No `lg:text-display` any more (2026-08-14). `--text-display` is now the homepage hero
            step and nothing else -- it tops out at 72px, which is not a page-title size -- so
            every non-hero surface that used to step up into it sits on `text-h1` instead. The
            token carries its own clamp, so this is still responsive without a breakpoint here.
            No `leading-tight`/`tracking-tight`: both tokens already carry their own line-height and
            letter-spacing, and stacking the utilities on top applied the correction twice. */}
        <h1 className="text-h1 font-semibold text-text">{title}</h1>
        {description && <p className="mt-2 max-w-[60ch] text-body text-muted">{description}</p>}
      </div>
      {action && <div className="shrink-0 sm:pb-0.5">{action}</div>}
    </header>
  );
}

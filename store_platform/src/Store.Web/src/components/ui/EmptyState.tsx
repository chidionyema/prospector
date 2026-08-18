import React from 'react';
import { cx } from './cx';
import { Icon, type IconName } from './Icon';

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** Optional 24px glyph above the line. Quiet by design: `text-faint`, never illustrated. */
  icon?: IconName;
  /** Optional call-to-action (e.g. a Button). Kept as a slot so EmptyState owns no routing. */
  action?: React.ReactNode;
  className?: string;
}

/**
 * The calm "nothing here yet" panel, never an error, never alarming (UI-STANDARDS §2).
 *
 * Brand v3 (2026-08-06): the dashed border went (a dashed rule reads as a drop target or an
 * unfinished placeholder, and this panel is neither), the title dropped from `text-h2` to
 * `text-body font-semibold` so an absence never out-shouts the page's real heading, and the
 * description dropped to `text-meta`. No illustration, no gradient (spec §6.14).
 */
export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-center gap-2 rounded-md border border-border bg-surface px-6 py-16 text-center',
        className,
      )}
    >
      {icon && <Icon name={icon} size={24} className="text-faint" />}
      <p className="text-body font-semibold text-text">{title}</p>
      {description && <p className="max-w-sm lede">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

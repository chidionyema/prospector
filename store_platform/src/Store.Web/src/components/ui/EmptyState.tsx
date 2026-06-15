import React from 'react';
import { cx } from './cx';

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** Optional call-to-action (e.g. a Button). Kept as a slot so EmptyState owns no routing. */
  action?: React.ReactNode;
  className?: string;
}

/** The calm "nothing here yet" panel — never an error, never alarming (UI-STANDARDS §2). */
export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-surface px-6 py-12 text-center',
        className,
      )}
    >
      <p className="text-h2 font-semibold text-text">{title}</p>
      {description && <p className="max-w-sm text-small text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

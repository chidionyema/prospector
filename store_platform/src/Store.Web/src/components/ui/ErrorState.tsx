import React from 'react';
import { cx } from './cx';
import { Button } from './Button';

export interface ErrorStateProps {
  title?: string;
  /** A user-safe message — pass `ApiError.message`, never a raw stack or internal detail. */
  message: string;
  onRetry?: () => void;
  className?: string;
  /**
   * Element for the title. Defaults to a plain `p` — correct when ErrorState is an INLINE panel on a
   * page that already owns an `h1` (board, proposals). Pass `'h1'` only when ErrorState is the page's
   * SOLE content (e.g. the tokenless pitch-result outcomes), so the page still has a real heading for
   * screen-reader navigation — see docs/engineering/ACCESSIBILITY-STANDARDS.md.
   */
  titleAs?: 'p' | 'h1' | 'h2';
}

/** Recoverable error panel. Pairs with `ApiError` from the client (UI-STANDARDS §2-3). */
export function ErrorState({ title = 'Something went wrong', message, onRetry, className, titleAs: TitleTag = 'p' }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cx(
        'flex flex-col items-center gap-2 rounded-lg border border-border bg-surface px-6 py-12 text-center',
        className,
      )}
    >
      <TitleTag className="text-h2 font-semibold text-danger">{title}</TitleTag>
      <p className="max-w-sm text-small text-muted">{message}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} className="mt-2">
          Try again
        </Button>
      )}
    </div>
  );
}

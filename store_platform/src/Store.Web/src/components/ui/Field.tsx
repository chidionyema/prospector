import React from 'react';
import { cx } from './cx';

export interface FieldProps {
  label: string;
  /** id of the control this label points at. Hint/error ids derive as `${htmlFor}-hint`/`-error`. */
  htmlFor: string;
  hint?: string;
  error?: string;
  required?: boolean;
  hideLabel?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Presentational label/hint/error wrapper for any control (input, select, textarea). */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  hideLabel,
  children,
  className,
}: FieldProps) {
  return (
    <div className={cx('flex flex-col gap-1', className)}>
      <label
        htmlFor={htmlFor}
        className={cx('text-small font-semibold text-text', hideLabel && 'sr-only')}
      >
        {label}
        {required && <span className="text-danger"> *</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={`${htmlFor}-hint`} className="text-caption text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${htmlFor}-error`} role="alert" className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** Compute the aria-describedby value for a control given its id + which slots are present. */
export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

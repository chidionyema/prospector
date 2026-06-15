import React, { useId } from 'react';
import { cx } from './cx';
import { Icon } from './Icon';

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** The clickable label beside the box. */
  label: React.ReactNode;
  /** Optional secondary line under the label (e.g. a legal clarification). */
  hint?: React.ReactNode;
  error?: string;
}

/**
 * The only checkbox. A real native input drives state + a11y; a token-styled box renders on top via the
 * peer pattern (no raw HTML control look). Replaces the bare `<input type=checkbox>` boxes that made the
 * funding consent step read like a compliance form (SITE-POLISH-SPEC §2.6).
 */
export function Checkbox({ label, hint, error, id, className, disabled, ...rest }: CheckboxProps) {
  const autoId = useId();
  const inputId = id || autoId;
  const describedBy = [hint && `${inputId}-hint`, error && `${inputId}-error`].filter(Boolean).join(' ');
  return (
    <div className={cx('flex flex-col gap-1', className)}>
      <label
        htmlFor={inputId}
        className={cx(
          'group flex cursor-pointer items-start gap-3',
          disabled && 'cursor-not-allowed opacity-50',
        )}
      >
        <span className="relative mt-0.5 flex h-5 w-5 shrink-0">
          <input
            {...rest}
            id={inputId}
            type="checkbox"
            disabled={disabled}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy || undefined}
            className="peer sr-only"
          />
          <span
            aria-hidden="true"
            className={cx(
              'flex h-5 w-5 items-center justify-center rounded-[5px] border bg-surface text-on-primary transition-colors',
              'group-hover:border-muted/60',
              'peer-checked:border-primary peer-checked:bg-primary',
              'peer-focus-visible:ring-2 peer-focus-visible:ring-focus peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-bg',
              error ? 'border-danger' : 'border-border',
            )}
          >
            {/* The check inherits the box's on-primary (white): invisible on the white unchecked box,
                visible once peer-checked fills the box with primary. No sibling combinator needed. */}
            <Icon name="check" size={14} />
          </span>
        </span>
        <span className="space-y-0.5">
          <span className="block text-small text-text">{label}</span>
          {hint && (
            <span id={`${inputId}-hint`} className="block text-caption text-muted">
              {hint}
            </span>
          )}
        </span>
      </label>
      {error && (
        <p id={`${inputId}-error`} role="alert" className="text-caption text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

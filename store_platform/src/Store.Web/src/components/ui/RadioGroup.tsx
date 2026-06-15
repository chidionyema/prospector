import React, { useId } from 'react';
import { cx } from './cx';

export interface RadioOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Optional secondary line under the option label. */
  description?: React.ReactNode;
}

export interface RadioGroupProps<T extends string> {
  label: string;
  name: string;
  value: T | null;
  onChange: (value: T) => void;
  options: RadioOption<T>[];
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
}

/**
 * A vertical set of card-style radios — native inputs for a11y, the whole row a selectable surface that
 * lights up when checked (`has-[:checked]` + a pseudo dot). Use where a choice deserves room to breathe
 * (a funding option, an intro type) instead of a cramped inline radio list (SITE-POLISH-SPEC §2.6).
 */
export function RadioGroup<T extends string>({
  label,
  name,
  value,
  onChange,
  options,
  hint,
  error,
  required,
  className,
}: RadioGroupProps<T>) {
  const groupId = useId();
  return (
    <fieldset
      className={cx('flex flex-col gap-2', className)}
      aria-describedby={[hint && `${groupId}-hint`, error && `${groupId}-error`].filter(Boolean).join(' ') || undefined}
    >
      <legend className="text-small font-semibold text-text">
        {label}
        {required && <span className="text-danger"> *</span>}
      </legend>
      {hint && !error && (
        <p id={`${groupId}-hint`} className="text-caption text-muted">
          {hint}
        </p>
      )}
      <div className="flex flex-col gap-2">
        {options.map((opt) => (
          <label
            key={opt.value}
            className={cx(
              'flex cursor-pointer items-start gap-3 rounded-lg border bg-surface p-4 transition-colors',
              'hover:border-muted/50',
              'has-[:checked]:border-primary has-[:checked]:bg-primary/5',
              'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-focus has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-bg',
              error ? 'border-danger' : 'border-border',
            )}
          >
            <input
              type="radio"
              name={name}
              value={opt.value}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="peer sr-only"
            />
            <span
              aria-hidden="true"
              className={cx(
                'relative mt-0.5 h-5 w-5 shrink-0 rounded-full border border-border bg-surface transition-colors',
                'after:absolute after:inset-1.5 after:rounded-full after:bg-primary after:opacity-0 after:transition-opacity',
                'peer-checked:border-primary peer-checked:after:opacity-100',
              )}
            />
            <span className="space-y-0.5">
              <span className="block text-small font-semibold text-text">{opt.label}</span>
              {opt.description && (
                <span className="block text-caption text-muted">{opt.description}</span>
              )}
            </span>
          </label>
        ))}
      </div>
      {error && (
        <p id={`${groupId}-error`} role="alert" className="text-caption text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}

import React, { useId } from 'react';
import { cx } from './cx';
import { Field, describedBy } from './Field';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string;
  hideLabel?: boolean;
}

const controlClass = (invalid: boolean) =>
  cx(
    'w-full rounded-md border bg-surface px-3 py-2 text-body text-text transition-all duration-200',
    'placeholder:text-muted/60 placeholder:font-normal', // Muted placeholders
    'hover:border-muted/50',
    // High-fidelity focus bounds: an ambient 4px ring paired with Trust Blue border.
    'focus-visible:outline-none focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/10',
    'disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-bg',
    invalid ? 'border-danger focus-visible:border-danger focus-visible:ring-danger/10' : 'border-border',
  );

/** Labelled text input — label always present, error/hint slots, aria wired (UI-STANDARDS §2). */
export function Input({
  label,
  hint,
  error,
  required,
  hideLabel,
  id,
  className,
  ...rest
}: InputProps) {
  const autoId = useId();
  const inputId = id || autoId;
  return (
    <Field
      label={label}
      htmlFor={inputId}
      hint={hint}
      error={error}
      required={required}
      hideLabel={hideLabel}
    >
      <input
        {...rest}
        id={inputId}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(inputId, hint, error)}
        className={cx(controlClass(!!error), className)}
      />
    </Field>
  );
}

export { controlClass };

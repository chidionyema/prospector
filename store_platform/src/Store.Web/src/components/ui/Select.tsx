import React, { useId } from 'react';
import { cx } from './cx';
import { Field, describedBy } from './Field';
import { controlClass } from './Input';

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: string;
  error?: string;
  hideLabel?: boolean;
  /** The <option> elements. */
  children: React.ReactNode;
}

/** Labelled native select, styled to match Input (token border + soft focus ring) with a custom
 *  chevron so it never renders as a raw OS control (SITE-POLISH-SPEC §2.6). */
export function Select({
  label,
  hint,
  error,
  required,
  hideLabel,
  id,
  className,
  children,
  ...rest
}: SelectProps) {
  const autoId = useId();
  const selectId = id || autoId;
  return (
    <Field
      label={label}
      htmlFor={selectId}
      hint={hint}
      error={error}
      required={required}
      hideLabel={hideLabel}
    >
      <div className="relative">
        <select
          {...rest}
          id={selectId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(selectId, hint, error)}
          className={cx(controlClass(!!error), 'appearance-none pr-10', className)}
        >
          {children}
        </select>
        {/* Custom chevron — the native one is suppressed by appearance-none. Pure CSS so no icon import
            churn; sits inside the field, ignores pointer so the select still opens on click. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 h-2 w-2 -translate-y-[3px] rotate-45 border-b-2 border-r-2 border-muted"
        />
      </div>
    </Field>
  );
}

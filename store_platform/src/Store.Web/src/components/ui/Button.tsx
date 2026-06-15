import React from 'react';
import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'inverse' | 'inverseGhost' | 'prominent';

const VARIANTS: Record<ButtonVariant, string> = {
  // Prominent = Deep Slate/Navy for ultimate conversion (LinkedIn-Grade).
  prominent: cx(
    'bg-text text-white',
    'shadow-[0_1px_2px_rgba(15,23,42,0.05),0_4px_12px_rgba(15,23,42,0.03)] hover:shadow-2',
    'focus-visible:ring-text/20 focus-visible:ring-offset-2',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  // Primary = Trust Blue.
  primary: cx(
    'bg-primary text-on-primary',
    'shadow-[0_1px_2px_rgba(15,23,42,0.05),0_4px_12px_rgba(15,23,42,0.03)] hover:shadow-2',
    'focus-visible:ring-primary/20 focus-visible:ring-offset-2',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  secondary: cx(
    'bg-surface text-text border border-border shadow-[0_1px_2px_rgba(0,0,0,0.05)]',
    'hover:bg-bg/80 hover:border-muted/30',
    'focus-visible:ring-focus/20 focus-visible:ring-offset-2',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  ghost: cx(
    'bg-transparent text-muted border border-transparent',
    'hover:bg-bg hover:text-text hover:border-border/50',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  danger: cx(
    'bg-danger text-on-danger',
    'hover:bg-danger/90 hover:shadow-2',
    'focus-visible:ring-danger/20 focus-visible:ring-offset-2',
    'active:scale-[0.98]',
    'disabled:bg-faint disabled:text-text/40 disabled:cursor-not-allowed',
  ),
  // For the dark band only
  inverse: cx(
    'bg-white text-band',
    'hover:bg-white/90 hover:shadow-2',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  inverseGhost: cx(
    'bg-transparent text-white border border-white/35',
    'hover:border-white hover:bg-white/5',
    'active:scale-[0.98]',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Disables the button and shows a spinner. Money actions rely on this to prevent double-submit. */
  loading?: boolean;
  fullWidth?: boolean;
}

/** The only button. Owns the loading/disabled discipline money screens depend on (UI-STANDARDS §2-3). */
export function Button({
  variant = 'primary',
  loading = false,
  fullWidth = false,
  disabled,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all duration-200 active:scale-[0.96] active:duration-75',
        'focus-visible:outline-none focus-visible:ring-2',
        VARIANTS[variant as ButtonVariant],
        fullWidth && 'w-full',
        className,
      )}
    >
      {loading && (
        <span
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
}

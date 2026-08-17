import React, { useRef } from 'react';
import { cx } from './cx';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible group name (this is a radiogroup, not a tablist). */
  ariaLabel: string;
  fullWidth?: boolean;
  className?: string;
}

/**
 * A two-or-more segment switch, the generic version of ModeToggle. ARIA radiogroup with the roving
 * tabindex + arrow-key pattern (arrows move selection AND focus, with wrap; only the checked segment is
 * tabbable). The active segment is the one bright-blue affordance ("click"); the rest are quiet.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  fullWidth = false,
  className,
}: SegmentedControlProps<T>) {
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    let next: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % options.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + options.length) % options.length;
    if (next === null) return;
    e.preventDefault();
    onChange(options[next].value);
    btnRefs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cx('inline-flex rounded-md border border-border bg-surface2 p-0.5', fullWidth && 'flex w-full', className)}
    >
      {options.map((opt, index) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              btnRefs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(opt.value)}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={cx(
              /*
               * 44px on touch, unchanged from `sm` up. `px-3 py-1.5 text-caption` measured 28px
               * tall at 390px on 2026-08-15 -- the account page's PRIMARY navigation, 16px under
               * the 44x44 minimum WCAG 2.5.5 publishes and this codebase already enforces
               * explicitly on `Button` (`md: h-11 ... sm:h-10`), on `chipClasses` and on the
               * header's Search and Menu buttons. `inline-flex` goes with it: `min-h` alone grows
               * the box and leaves the label sitting on its old baseline.
               *
               * The `sm:` guard is the bargain those two already struck -- a pointer does not need
               * the target -- and this control has exactly ONE call site (the account tabs,
               * `components/account/AccountPanel.tsx:111`), so nothing else moves either way.
               */
              'inline-flex min-h-11 items-center justify-center sm:min-h-0',
              'rounded-sm px-3 py-1.5 text-caption font-medium transition-colors duration-[120ms] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
              fullWidth && 'flex-1',
              active ? 'bg-primary text-on-primary' : 'text-muted hover:text-text',
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

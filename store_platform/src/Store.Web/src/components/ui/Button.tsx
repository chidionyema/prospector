import React from 'react';
import { cx } from './cx';

/**
 * FOUR variants (brand v3, 2026-08-06). Three were deleted:
 *
 *  - `inverse` / `inverseGhost` existed solely to sit on the dark band. There are no dark
 *    surfaces left, so they had no ground to stand on.
 *  - `prominent` was byte-for-byte `primary` plus a hover the primary lacked. Two names for one
 *    button is not a feature: it guarantees the pair drifts the first time either is edited, and
 *    it makes "which button is the most important one on this page?" unanswerable from the code.
 *
 * The fill is INK, not a brand colour. The old vermillion #FF5A1F scored 3.12:1 against white --
 * below the 4.5:1 AA floor for its label size -- which is what forced the black-on-orange pairing
 * the whole site was wearing. Black on safety orange is hazard livery; it reads as a warning, not
 * as an invitation to pay. #171717 on white is 17.93:1.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

const VARIANTS: Record<ButtonVariant, string> = {
  primary: cx(
    'bg-primary text-on-primary',
    'hover:bg-primary-hover',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  // The hairline button. `border-strong` (#D4D4D8) rather than `border` (#E4E4E7) because a
  // control has to read as a control: at the lighter value the edge disappears once the button
  // sits on a card, which is exactly where secondary buttons live.
  secondary: cx(
    'bg-surface text-text border border-border-strong',
    'hover:border-text hover:bg-surface2',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  ghost: cx(
    'bg-transparent text-muted',
    'hover:bg-surface2 hover:text-text',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  // White on #DC2626 is 4.83:1, which clears AA for this label (14px/500).
  danger: cx(
    'bg-danger text-white',
    'hover:bg-danger-strong',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
};

/**
 * `lg` is for the two places where the button IS the screen: the buy box and the hero. Everywhere
 * else is `md`. A third size would only invite each page to pick its own.
 */
export type ButtonSize = 'md' | 'lg';

const BASE = cx(
  'inline-flex items-center justify-center gap-2 rounded-md font-medium',
  // transition-colors, not transition-all: `all` animated the transform too, which is why the
  // press felt spongy -- the 0.98 squash was easing over 200ms instead of snapping.
  'transition-colors duration-[120ms] ease-[cubic-bezier(0.2,0,0,1)]',
  'active:scale-[0.98]',
  // OUTLINE, not ring. A ring is an inset box-shadow, so it is invisible against a filled button
  // of a similar colour and it is clipped by any `overflow-hidden` ancestor -- both of which apply
  // here. An outline is drawn outside the border box and always shows.
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
);

const SIZES: Record<ButtonSize, string> = {
  md: 'h-10 px-4 text-meta',
  lg: 'h-12 px-6 text-body',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Disables the button and shows a spinner. Money actions rely on this to prevent double-submit. */
  loading?: boolean;
  fullWidth?: boolean;
}

/**
 * The shape, as a class string, for the case where the control has to be an `<a>`.
 *
 * A CTA that navigates must render an anchor: `<button onClick={router.push}>` is not
 * middle-clickable, not copyable, and invisible to a crawler. Before this existed every such CTA
 * on the marketing pages hand-rolled its own `inline-flex ... bg-primary px-6 py-3` string, which
 * is why the site shipped four different primary-CTA heights and two different hovers. Pages now
 * call this instead of inventing a shape.
 */
export function buttonClasses({
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  className?: string;
} = {}) {
  return cx(BASE, SIZES[size], VARIANTS[variant], fullWidth && 'w-full', className);
}

/**
 * The filter chip, as a class string.
 *
 * A chip is not a small `Button`: it is a toggle whose selected state has to be readable at a
 * glance across a row of twenty, so it carries an on/off state that `ButtonVariant` does not
 * model. It was hand-rolled in three places and came out three different ways (2026-08-06):
 *
 *   kill-log.tsx   rounded-full, `bg-text` when active
 *   FacetBar.tsx   rounded-full, `bg-primary` when active
 *   faq.tsx        SQUARE, `border-primary bg-primary/10` when active
 *
 * Three shapes for one control, on three pages a buyer visits in one session. `bg-primary` and
 * `bg-text` happen to resolve to the same ink today (globals.css), so two of them agreed by
 * coincidence rather than by construction -- the day `--primary` moves off ink, the shelf's
 * filters and the kill log's filters stop matching and nothing fails.
 *
 * Selected is a FILL, not a tint. `bg-primary/10` at 10% is a 1.1:1 change against white: on the
 * FAQ screenshot the selected chip and its neighbours were the same object at a glance.
 */
export function chipClasses({
  selected = false,
  /**
   * The applied-filter token: a selected chip with a trailing ✕ that removes it. Only the right
   * padding changes (the ✕ brings its own optical space) and the whole control gains a hover,
   * because unlike an ordinary chip it is a destructive click. Modelled here rather than passed
   * in as a `className` override, because `px-3` and `pr-2` have equal specificity and which one
   * wins depends on the order Tailwind happens to emit them, not on the order they are listed.
   */
  removable = false,
  className,
}: { selected?: boolean; removable?: boolean; className?: string } = {}) {
  return cx(
    'inline-flex h-8 items-center rounded-full border text-meta font-medium',
    removable ? 'gap-1.5 pl-3 pr-2' : 'px-3',
    'transition-colors duration-[120ms] ease-[cubic-bezier(0.2,0,0,1)]',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    selected
      ? cx('border-text bg-text text-white', removable && 'hover:border-primary-hover hover:bg-primary-hover')
      : 'border-border bg-surface text-muted hover:border-border-strong hover:text-text',
    className,
  );
}

/** The only button. Owns the loading/disabled discipline money screens depend on (UI-STANDARDS §2-3). */
export function Button({
  variant = 'primary',
  size = 'md',
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
      className={buttonClasses({ variant, size, fullWidth, className })}
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

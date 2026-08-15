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
 * The fill is --action, the ONE colour that means "do something" (tokens.css carries the whole
 * system and every measurement). Its literal has moved three times and the rule has not: ink,
 * then the navy #1B3F8B, and since the founder's palette review on 2026-08-15 the charcoal
 * #2D3436 -- the navy read as an orphan beside the teal identity. Before all of those it was
 * vermillion #FF5A1F, which scored 3.12:1 against white, below the AA floor for this label size,
 * and that is what forced the black-on-orange pairing the whole site used to wear.
 * White on #2D3436 is 12.68:1.
 *
 * The PAIR is what to read here, not either variant alone: charcoal fill, teal outline. `primary`
 * and `secondary` separate on hue as well as on weight, which is what stops "the second button"
 * from being the first one with its fill removed.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

const VARIANTS: Record<ButtonVariant, string> = {
  /*
   * The ONE filled button on the site, buy button included. A fifth variant `buy` used to sit
   * below this one carrying --azure, and it was deleted with that token: a site with two primary
   * fills teaches a reader nothing about either, which is the founder's "black buttons disappear
   * entirely -- no two primary colours".
   *
   * Its stated reason for being a separate VARIANT rather than a className override was correct
   * and is worth keeping: both would emit `bg-*`, and which one wins is decided by the order
   * Tailwind happens to write the two rules, not by class order -- a coin-flip on the buy button's
   * fill at every build. That is exactly why `PackBuyButton` now CALLS this variant instead of
   * overriding it.
   */
  primary: cx(
    'bg-primary text-on-primary',
    'hover:bg-primary-hover',
    // The press is a third shade, not an opacity: -14pp lightness reads as the control taking the
    // press, where a fade reads as the control going away. White on it is 15.16:1.
    'active:bg-action-active',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ),
  /* The hairline button, and since 2026-08-15 it is the TEAL half of the pair.
   *
   * It was `border-border-strong` + `text-text`: a grey outline round ink, i.e. the same two
   * neutrals the page is already made of. That was survivable while the primary button was navy,
   * because the pair separated on the primary's hue alone. Option B moves the primary to charcoal
   * #2D3436, which is close enough to --text #171717 that a grey-outlined ink button beside it
   * would be the same object twice -- one filled, one not -- and "black buttons disappear" is a
   * failure this palette has already shipped once (see --action in tokens.css).
   *
   * So the secondary now carries the brand: teal edge, teal label. That is what makes the two
   * buttons read as a designed PAIR rather than as a button and its ghost, and it is where the
   * founder's "teal for the logo, charts and key highlights" lands on a control.
   *
   * MEASURED: --brand-mark #0F766E is 5.32:1 on the warm canvas #FAF9F7 and 5.47:1 on --surface
   * #FFFFFF -- AA for the label at both. The EDGE clears WCAG 1.4.11's 3:1 for non-text UI by the
   * same numbers, which the old --border-strong (1.48:1) never did; that token's own comment in
   * tokens.css records it as "DECORATION ONLY ... not legal on a control", so this swap also
   * retires a documented violation rather than merely restyling one.
   */
  secondary: cx(
    'bg-surface text-brand-mark border border-brand-mark',
    'hover:bg-brand-mark hover:text-white',
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
  /*
   * 44px on touch, 40px from `sm` up. `h-10` everywhere put the site's PRIMARY actions -- "Browse
   * the catalogue", the newsletter's "Tell me when one survives", the shelf pager's "Next" -- at
   * 40px on a 390px screen, 4px under the 44x44 minimum this codebase already enforces explicitly
   * on the header's Search and Menu buttons (`min-h-11 min-w-11`), on `chipClasses`, and on both
   * footer link columns. Measured by DOM probe at 390px on 2026-08-13. `sm:h-10` means the desktop
   * rendering is unchanged to the pixel; only the touch viewport grows, which is the only viewport
   * the floor is about. `lg` (48px) already cleared it.
   */
  md: 'h-11 px-4 text-meta sm:h-10',
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
    /*
     * 44px on touch, 32px from `sm` up. `h-8` everywhere put the shelf's facet chips, the kill
     * log's gate filters and the FAQ's category filters at 32px tall on a 390px screen -- measured
     * on all three pages 2026-08-13 -- which is under the 44x44 minimum Apple's HIG and WCAG 2.5.5
     * both publish, on the primary control of each of those pages. It is not a contrast or a
     * labelling problem, so nothing on screen reads as wrong; it just misses, and a filter that
     * misses reads to the buyer as a filter that does not work. The desktop height is unchanged:
     * a pointer does not need the target and a 44px chip rail would dominate a page it only
     * qualifies.
     */
    'inline-flex h-11 items-center rounded-sm border text-meta font-medium sm:h-8',
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

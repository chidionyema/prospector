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
  /* THE FILL AND THE HOVER COME FROM `.btn` (mumchimp.css:20-21): `var(--ink)` on the label,
     `#000` on hover. `bg-primary` / `hover:bg-primary-hover` / `active:bg-action-active` are
     deleted, not kept beside them -- a utility outranks the class, so keeping one meant the
     shipped stylesheet could never paint the site's one filled button. Only the disabled state
     stays: the stylesheet has no `:disabled` rule, and a dead-looking control is the difference
     between "this is thinking" and "this is broken". */
  primary: 'disabled:opacity-40 disabled:cursor-not-allowed',
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

/*
 * THE SHAPE IS `.btn`, THE SHIPPED CLASS -- NOT A COPY OF IT (2026-08-18, parity step 1).
 *
 * Founder's spec: "Drop it in. Import it. The agent writes no CSS at all except page-level layout
 * that doesn't exist in it." This constant used to restate `mumchimp.css:20` in Tailwind --
 * inline-flex, gap 10px, 8px radius, weight 600, tracking -0.01em -- and the comment it carried
 * even quoted the stylesheet rule it was reproducing. Two copies of one control, and the copy is
 * what every button on the site was drawn from, so `.btn` was inert everywhere `Button` rendered.
 * The utilities are DELETED rather than layered: globals.css:8 imports the stylesheet into
 * `layer(components)`, so a utility that says the same thing wins and the class does nothing.
 *
 * WHAT STAYS, AND WHY EACH ONE IS NOT IN THE STYLESHEET:
 *
 *  - the focus outline. `mumchimp.css` declares no `:focus-visible` rule for `.btn`, and a control
 *    with no visible focus state fails WCAG 2.4.7. An OUTLINE, not a ring: a ring is an inset
 *    box-shadow, invisible against a filled button and clipped by any `overflow-hidden` ancestor.
 *  - the 44px touch floor, on `md` only (see SIZES).
 *
 * The press and the colour transition are gone from here because the stylesheet already has them:
 * `mumchimp.css:259` is `.btn:active{transform:scale(.985)}` and `:260` is the transition.
 */
const BASE = cx(
  'btn',
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
);

/* `md` IS THE STYLESHEET'S `.btn.sm` (mumchimp.css:24: 14.5px text, 10px/16px padding), and `lg`
   is plain `.btn` (16px, 13px/22px). The px values that used to be written here are gone with the
   rest of the copy. `min-h-11` survives on `md` alone and is the one number in this file that is
   ours: `.btn.sm` computes to ~40px, and 40px is 4px under the 44x44 touch minimum this codebase
   enforces on the header's Search and Menu buttons, on `chipClasses`, and on both footer link
   columns. Measured by DOM probe at 390px on 2026-08-13. `sm:min-h-0` hands the desktop rendering
   back to the stylesheet unchanged, because the floor is about the touch viewport only. */
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
  //
  // `lg` is the mockups' `.btn` exactly: 16px text in 13px of vertical padding on a 1.5 line box
  // is 50px tall, with 22px of horizontal padding. `md` is their `.btn.sm` (14.5px / 10px 16px),
  // kept at 44px on touch for the floor above and dropping to the drawn 40px from `sm`.
  md: 'sm min-h-11 sm:min-h-0',
  lg: '',
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
  /**
   * Let the label wrap and the chip grow, instead of holding one line at a fixed height.
   *
   * For a chip in a `flex-wrap` rail this is wrong -- it shrink-wraps its label, so there is
   * nothing to wrap against. It is for a chip in a GRID cell, where the column width is fixed by
   * the grid and a long label has nowhere to go. Measured 2026-08-15 on the StepFlow tiles at
   * 320px: "I can run operations" pushed its trailing count 45px PAST the tile's padding edge and
   * put four elements off-screen; at 390px the overshoot was 10px. A count cannot sit in a
   * right-aligned column when its own sibling is shoving it out of the box.
   *
   * Modelled here rather than passed as a `className`, for the reason `removable` gives above:
   * `h-11` and `h-auto` have equal specificity, so which one won would depend on the order
   * Tailwind happened to emit them. `min-h` keeps the 44px touch floor as a FLOOR, which is what
   * it was always meant to be, and `py-2` stops a two-line label sitting hard against the border.
   */
  wrap = false,
  className,
}: { selected?: boolean; removable?: boolean; wrap?: boolean; className?: string } = {}) {
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
    'inline-flex items-center rounded-sm border text-meta font-medium',
    // `sm:py-0` matters: the desktop chip must stay exactly 32px. `py-2` + a 20px line box is
    // 36px, so without it every wizard chip would grow 4px on a breakpoint where nothing wraps.
    wrap ? 'min-h-11 py-2 sm:min-h-8 sm:py-0' : 'h-11 sm:h-8',
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

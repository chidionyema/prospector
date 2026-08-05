import React from 'react';
import Link from 'next/link';
import { cx } from '@/components/ui/cx';
import { formatPrice, Pack } from '@/lib/api/client';
import { formatPriceForMarket, type Currency } from '@/lib/fx';
import { useRequestBuy } from '@/components/checkout/BuyDrawer';

export interface PackBuyButtonProps {
  pack: Pack;
  /**
   * Where this button is mounted, and therefore which existing buy flow runs on click.
   * Visual shape is identical across all four variants; only the flow changes.
   *
   *  - `card`:   the homepage grid card. Renders inside a `<Link>`; click opens the shelf
   *              `BuyDrawer` without navigating.
   *  - `drawer`: the buy affordance inside the shelf drawer. Expects the parent `<BuyDrawer>`
   *              to pass `buy` (its own `usePackCheckout.buy`) so the click runs the same
   *              checkout the drawer renders its embedded overlay from.
   *  - `detail`: the pack detail page's primary checkout panel. The page passes `buy`,
   *              `checkingOut`, and `canCheckout` so the button reads the same state the
   *              page's `EmbeddedCheckoutPanel` does.
   *  - `sticky`: the mobile sticky buy bar. Same checkout flow as the detail variant.
   */
  variant: 'card' | 'drawer' | 'detail' | 'sticky';
  /** Override the label. Defaults to `Unlock this pack · {formatPrice(pack.price)}`. */
  label?: string;
  /** Optional className passthrough for layout (width, margin, custom backgrounds). */
  className?: string;
  /** When true, the button is disabled (e.g., the pack is not yet buyable). */
  disabled?: boolean;
  /**
   * Mailto URL for the notify-me fallback when this pack is not yet buyable. Only
   * honoured on `detail` / `sticky` variants, where the checkout flow owns the
   * `canCheckout` state. Without this, a non-buyable pack still renders a buy button,
   * and the parent surface handles the "checkout opens shortly" path.
   */
  notifyHref?: string;
  /**
   * The buy flow. The drawer and detail variants MUST pass this (the parent surface owns
   * the embedded overlay state via `usePackCheckout`). The card variant omits it and
   * uses the `useRequestBuy` context to open the shelf drawer instead.
   */
  buy?: () => void | Promise<void>;
  /** Whether the buy flow is currently in flight. Required by `drawer` / `detail` / `sticky`. */
  checkingOut?: boolean;
  /** Whether the pack is currently buyable. Required by `detail` to enable the notify-me path. */
  canCheckout?: boolean;
  /**
   * The visitor's display currency, resolved from `Fly-Client-Country` in the page's
   * `getServerSideProps`. Defaults to GBP so any surface that has not been threaded through
   * renders exactly what it rendered before this prop existed.
   *
   * This exists because the CTA has to agree with the price above it. On a US request the pack
   * page headline read `$62.23` while this button read `Unlock this pack · £49` -- two prices,
   * two currencies, one fold. Founder decision (2026-08-05): local currency is the anchor
   * everywhere, and the GBP charge is disclosed next to the button instead.
   */
  currency?: Currency;
}

/**
 * The single, canonical buy action.
 *
 * US-1 (audit §4.1, §4.16) found the buy action labelled four different ways across the
 * same page ("Unlock for £49", "View vetted blueprint", "Get instant access, £49",
 * "Buy, £49"). The fix is exactly one component used by every entry point.
 *
 * Visual shape is invariant across `variant`; the variant only chooses which buy flow runs
 * on click. The click handler always calls `e.preventDefault()` and `e.stopPropagation()`
 * so the button is safe inside a `<Link>` card without navigating when bought.
 *
 *  - `card` flow: `useRequestBuy` from `BuyDrawerProvider` (returns `null` outside the
 *    provider; the click becomes a no-op in that case. The card's own `<Link>` is the
 *    learn action).
 *  - `drawer` / `detail` / `sticky` flow: the parent supplies `buy` from its own
 *    `usePackCheckout` instance. The button MUST NOT call `usePackCheckout` itself
 *    two instances would split the buy state between the button and the parent's
 *    `EmbeddedCheckoutPanel`, and the click would never open the overlay.
 *
 * When the pack is not yet buyable (`!canCheckout`) and `notifyHref` is provided, the
 * button swaps to a `Notify me` link so the existing mailto flow keeps working without
 * a second template string living in the page.
 */
export default function PackBuyButton({
  pack,
  variant,
  label,
  className,
  disabled,
  notifyHref,
  buy,
  checkingOut,
  canCheckout,
  currency = 'GBP',
}: PackBuyButtonProps) {
  // Card entry point: opens the shelf drawer. `null` outside the provider, the card's
  // `<Link>` is the learn action in that case, same behaviour as before the provider existed.
  const requestBuy = useRequestBuy();
  const isCardFlow = variant === 'card';

  const handleClick = (event: React.MouseEvent) => {
    // A PackCard is a <Link>. Without these two calls, buying also navigates away from
    // the shelf the drawer is going to overlay. The link's job is "show the evidence";
    // the button's job is "start the purchase". They are deliberately independent.
    event.preventDefault();
    event.stopPropagation();
    if (isCardFlow) {
      requestBuy?.(pack);
      return;
    }
    if (buy) {
      void buy();
    }
  };

  // GBP path stays on `formatPrice`: it strips a trailing `.00` from the API's price string and
  // does NOT add a currency symbol, because the API already sends one ("£49.00" -> "£49").
  // Prefixing another `£` here rendered the primary buy CTA as "Unlock this pack · ££49" on every
  // pack page, and the test guarding this label only matched /Unlock this pack/, so it stayed
  // green through the whole regression. Non-GBP goes through the FX formatter so the CTA quotes
  // the same number as the headline price directly above it.
  const priceLabel =
    currency === 'GBP' ? formatPrice(pack.price) : formatPriceForMarket(pack.price, currency);
  const canonicalLabel = `Unlock this pack · ${priceLabel}`;
  const visibleLabel = checkingOut ? 'Opening…' : label ?? canonicalLabel;

  // Canonical visual shape. Identical across every entry point; variant changes only the
  // buy flow, never the markup. Brand v2: --primary is vermillion `#FF5A1F` /
  // --primary-hover `#E64500` in globals.css; Tailwind v4 resolves `bg-primary` and
  // `hover:bg-primary-hover` to those custom-property-backed color tokens.
  const shapeClasses = cx(
    'inline-flex items-center justify-center',
    'rounded-md bg-primary text-on-primary',
    'text-meta font-bold',
    'px-6 py-3.5',
    'transition-all duration-150',
    'hover:bg-primary-hover',
    'active:scale-[0.98]',
    'disabled:cursor-not-allowed disabled:opacity-50',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2',
  );

  // Not buyable yet. The card / drawer flow cannot tell from here whether the drawer
  // WILL be buyable (the drawer's own `usePackCheckout` may differ), so it always
  // renders a buy button; the drawer itself shows the "checkout opens shortly" path
  // when `canCheckout` comes back false. The pack detail page owns the mailto
  // fallback and passes `notifyHref` down so this component can render the same
  // notification link the inline markup used to.
  if (!isCardFlow && canCheckout === false && notifyHref) {
    return (
      <Link href={notifyHref} className={cx(shapeClasses, className)}>
        Notify me
      </Link>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || checkingOut}
      aria-label={visibleLabel}
      className={cx(shapeClasses, className)}
    >
      {visibleLabel}
    </button>
  );
}

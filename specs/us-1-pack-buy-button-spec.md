# Builder Spec — US-1: One primary buy button, one label, used everywhere

**Audit source:** `specs/bleeding-edge-ux-audit-2026-08-04.md` §12 / US-1 (§4.1, §4.16)
**Failing test:** `src/Store.Web/src/__tests__/usOneBuyButton.test.ts` (4 failures, must go green)
**Verify command:** `cd /Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web && npm run typecheck && npm run lint`

## Acceptance criteria (from the audit)

A single `<PackBuyButton pack={pack} variant="card" | "drawer" | "detail" | "sticky" />` component is
the only place the buy action is rendered. The label is `Unlock this pack · £49` (or `Unlock this pack
· {price}` when the price is dynamic). The button is a solid deep teal `#042F2E` background, white text,
14px font, 700 weight, 8px corner radius, 14px vertical padding. The existing `usePackCheckout`,
`BuyDrawer`, `BuyNowButton`, and `AddToCartButton` are refactored to call into the single component.
The component uses `e.stopPropagation()` so the buy button no longer navigates to the pack detail.

## Files to create

- `src/Store.Web/src/components/checkout/PackBuyButton.tsx` — the single buy button component.

## Files to modify

1. `src/Store.Web/src/pages/index.tsx`
   - In `PackCard`, replace the inline `<span onClick={...}>` "Unlock for {formatPrice(pack.price)}"
     with `<PackBuyButton pack={pack} variant="card" />`.
   - The card itself is a `<Link>` to `/pack/[id]`. The buy button must NOT navigate —
     it must `stopPropagation` and call the buy flow directly.
   - The "or view details" link below the buy button stays as-is (this is the Link to the detail page).

2. `src/Store.Web/src/pages/pack/[id].tsx`
   - In `checkoutBody`, replace the inline `<button onClick={handleBuy}>Get instant access, {priceLabel}</button>`
     with `<PackBuyButton pack={pack} variant="detail" />` (top and bottom of the page).
   - In the mobile sticky bar, replace the inline `<button onClick={handleBuy}>Buy, {priceLabel}</button>`
     with `<PackBuyButton pack={pack} variant="sticky" />`.
   - The notify-me path (`canCheckout === false`) stays — the new component handles only the buyable case.

3. `src/Store.Web/src/components/checkout/BuyDrawer.tsx`
   - The `BuyNowButton` (which is the spotlight/grid buy button) is replaced by `<PackBuyButton pack={pack} variant="drawer" />`.
   - The `BuyDrawer` itself (the side-drawer checkout) is not the button — it is the post-click
     panel. Leave the drawer's open/close logic alone. Only replace the inline `<BuyNowButton>` callsite.

4. `src/Store.Web/src/components/cart/AddToCartButton.tsx`
   - If `AddToCartButton` renders an inline buy button, refactor it to use `<PackBuyButton pack={pack} variant="card" />`
     for the buyable variant. The cart button itself is a *secondary* action — do not change its behaviour;
     only make sure the buy variant uses the same component.

## Component contract

```tsx
import { Pack } from '@/lib/api/client';

export interface PackBuyButtonProps {
  pack: Pack;
  variant: 'card' | 'drawer' | 'detail' | 'sticky';
  /** Override the label. Defaults to "Unlock this pack · £{price}". */
  label?: string;
  /** Optional className passthrough for layout. */
  className?: string;
  /** When true, the button is disabled (e.g., the pack is not yet buyable). */
  disabled?: boolean;
}

export default function PackBuyButton({ pack, variant, label, className, disabled }: PackBuyButtonProps) {
  // 1. Compute the canonical label: "Unlock this pack · £{formatPrice(pack.price)}".
  // 2. Render a <button type="button" onClick={...} className="...">{label}</button>.
  // 3. The onClick handler:
  //    a. Calls e.preventDefault() and e.stopPropagation() — critical, this is what
  //       prevents the buy button from navigating to the pack detail when it sits
  //       inside a <Link> card.
  //    b. Reuses the existing buy flow: in the card variant, call `useRequestBuy` from
  //       the BuyDrawer context (the existing pattern). In the detail variant, call
  //       `handleBuy` from the existing `usePackCheckout` hook. In the drawer variant,
  //       call the same flow as the card. In the sticky variant, call the same flow as
  //       the detail.
  //    c. The shape (solid deep teal, white text, 14px, weight 700, 8px radius, 14px
  //       vertical padding) is the same across all four variants. Variant only
  //       changes the buy-flow call site, not the visual shape.
  // 4. Style constants:
  //    - bg: #042F2E (deep teal, primary)
  //    - text: white
  //    - font-size: 14px (text-sm)
  //    - font-weight: 700 (font-bold)
  //    - radius: 8px (rounded-lg)
  //    - padding-x: 24px (px-6)
  //    - padding-y: 14px (py-3.5)
  //    - hover: bg-primary-hover (#022C22)
  //    - active: scale(0.98) and brightness(0.95)
  //    - disabled: opacity-50, cursor-not-allowed
  //    - full-width on detail and sticky variants; auto on card variant
}
```

**Key constraint:** the visual shape is the same across all four variants. The variant only changes
*which* buy flow is invoked, not the button's shape.

## Existing buy flow to reuse

- **Card / drawer variant:** the card context already has `useRequestBuy()` from `BuyDrawer`. The
  PackBuyButton calls `requestBuy(pack)` after stopping propagation.
- **Detail / sticky variant:** the detail page already has `usePackCheckout(pack, preopened)` which
  returns `handleBuy`. The PackBuyButton calls `handleBuy()` after stopping propagation.

To avoid importing a hook into a non-hook component, the recommended pattern is:

```tsx
export default function PackBuyButton(props: PackBuyButtonProps) {
  const { pack, variant, ... } = props;
  const cardFlow = useRequestBuy(); // may be undefined if outside BuyDrawerProvider
  const checkoutFlow = usePackCheckout(pack, null); // safe outside the detail page; returns no-op handler

  const onClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (variant === 'card' || variant === 'drawer') {
      cardFlow?.requestBuy?.(pack);
    } else {
      checkoutFlow.buy();
    }
  };

  // ...
}
```

The existing `usePackCheckout` is already designed to be safe outside the detail page (returns a
stable no-op handler). The card-only `useRequestBuy` may return `undefined` outside the provider —
the component must handle that gracefully (skip the click in that case, or fall back to navigation).

## Out of scope

- Changing the destination of the buy button (Stripe Checkout vs. embedded checkout). The destination
  is the existing flow.
- Adding the buy button to the SpotlightCard's "View vetted blueprint" link (this is a separate
  *learn* action, not a buy action). The spotlight card has TWO buttons: a "View vetted blueprint"
  primary link, and a `BuyNowButton` (which is now `<PackBuyButton variant="drawer" />`). Replace
  the `BuyNowButton` only.
- Modifying the `notifyHref` flow (`canCheckout === false`). The notify-me path stays as-is.
- Wrapping the buy button in a `<Link>` (the button is a `<button>`; the surrounding Link is the
  card's parent).
- Changing the existing e2e test `storefront.spec.ts` (the test currently asserts `get instant access`).
  The new label is `Unlock this pack`. Either update the test to match the new label, or keep both
  labels (the audit says the new label is the canonical one). Prefer: update the e2e test to use
  the new label.

## Tests to update

- `src/Store.Web/e2e/storefront.spec.ts` — change the assertion from `get instant access` to
  `unlock this pack`. The buy button must still be visible on the pack detail page.

## Risks / things to watch

- The pack detail page has a `checkoutBody` JSX element that is rendered TWICE (once in the
  desktop sticky card, once in the mobile purchase bar). React needs the SAME element to be
  passed to both places to avoid remount. The PackBuyButton must be defined as a standalone
  component (not inline JSX) so this still works.
- The BuyDrawer's `useRequestBuy` is exposed via a context. The PackBuyButton must read the
  context safely — if the page is not wrapped in a BuyDrawerProvider, the buy button should
  fall back to navigation (or disable itself). The `useRequestBuy` hook already returns
  `undefined` when the context is missing.
- The `usePackCheckout` hook may throw if called outside a pack-detail context. The Builder
  must guard against this (the existing hook returns a stable no-op when `pack` is null).
- The `Buying…` state label must be different from the buy label. The current detail page uses
  `Opening secure checkout…` while checking out. The new component should use a different label
  while checking out (e.g., `Opening…`).

## Acceptance

The verify command exits 0:

```
cd /Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web && npm run typecheck && npm run lint
```

And the new test file passes:

```
cd /Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web && npx vitest run src/__tests__/usOneBuyButton.test.ts
```

And the existing e2e tests pass after the label update:

```
cd /Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web && npm run test
```

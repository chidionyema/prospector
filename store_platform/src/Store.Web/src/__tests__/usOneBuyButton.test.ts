import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function existsRelative(relativePath: string): boolean {
  return existsSync(fileURLToPath(new URL(relativePath, import.meta.url)));
}

/**
 * US-1 — One primary buy button, one label, used everywhere.
 *
 * The audit found the buy action labelled four different ways across one page
 * ("Unlock for £49", "View vetted blueprint", "Get instant access, £49", "Buy, £49").
 * The fix is a single `<PackBuyButton>` component used by every entry point.
 *
 * This test reads the source files and asserts the contract. It is the Architect's
 * architectural promise: when this test passes, the buy button is one component,
 * one label, one place — even if the rendered DOM drifts.
 */
describe('US-1 — One primary buy button', () => {
  const componentExists = existsRelative('../components/checkout/PackBuyButton.tsx');

  it('declares a single PackBuyButton component', () => {
    expect(componentExists, 'components/checkout/PackBuyButton.tsx must exist').toBe(true);
  });

  it('exports a default React component named PackBuyButton', () => {
    // Either default export or named export. The contract allows either.
    if (!componentExists) return;
    const source = readSource('../components/checkout/PackBuyButton.tsx');
    const exportsDefault = /export\s+default\s+function\s+PackBuyButton/.test(source);
    const exportsNamed = /export\s+function\s+PackBuyButton/.test(source);
    expect(exportsDefault || exportsNamed, 'PackBuyButton must be exported (default or named)').toBe(true);
  });

  it('encodes the canonical label "Unlock this pack"', () => {
    // The single label encoded in the source. The rendered text uses the buyer's price.
    if (!componentExists) return;
    const source = readSource('../components/checkout/PackBuyButton.tsx');
    expect(source, 'PackBuyButton must encode the canonical label').toMatch(/Unlock this pack/);
  });

  it('does not prepend a currency symbol to an already-formatted price', () => {
    // Regression guard. The label was `Unlock this pack · £${priceLabel}`, and
    // priceLabel comes from formatPrice() in lib/api/client.ts, which only strips a trailing
    // ".00" and never adds a symbol, because the API already sends "£49.00". So the primary
    // buy CTA on every pack page rendered "Unlock this pack · ££49".
    //
    // The assertion above stayed green throughout: /Unlock this pack/ matched either way. This
    // one pins the actual defect, a hardcoded currency symbol immediately before an interpolated
    // price that already carries one.
    if (!componentExists) return;
    const source = readSource('../components/checkout/PackBuyButton.tsx');
    expect(source, 'no hardcoded currency symbol before an interpolated price').not.toMatch(
      /[£$€]\s*\$\{\s*(priceLabel|price)\b/,
    );
  });

  it('renders a <button> element with stopPropagation on click', () => {
    // The audit: "the buy button is a <button> outside the link with e.stopPropagation()".
    // The PackCard is a <Link>; nested <button> + stopPropagation prevents navigation.
    if (!componentExists) return;
    const source = readSource('../components/checkout/PackBuyButton.tsx');
    const hasButton = /<button[\s>]/.test(source);
    expect(hasButton, 'PackBuyButton must render a <button>').toBe(true);
    const hasStopPropagation = /e\.stopPropagation\(\)/.test(source) ||
      /stopPropagation/.test(source);
    expect(hasStopPropagation, 'PackBuyButton must call stopPropagation on click').toBe(true);
  });

  it('accepts a variant prop', () => {
    // The contract: variant="card" | "drawer" | "detail" | "sticky".
    if (!componentExists) return;
    const source = readSource('../components/checkout/PackBuyButton.tsx');
    expect(source, 'PackBuyButton must accept a variant prop').toMatch(/variant/);
  });

  it('card surfaces use PackBuyButton (legacy "Unlock for" label is gone from index.tsx)', () => {
    // The homepage card grid must use the new component, not the legacy inline CTA.
    const page = readSource('../pages/index.tsx');
    // The audit identified the legacy label `Unlock for {pack.price}` as the canonical
    // antimatter. After US-1, this string must not appear in the rendered source.
    const legacyLabel = /Unlock for \{formatPrice/;
    expect(
      page.match(legacyLabel),
      'pages/index.tsx must not encode the legacy "Unlock for £" label (use PackBuyButton)',
    ).toBeNull();
  });

  it('pack detail uses PackBuyButton (legacy "Get instant access" label is gone)', () => {
    // The pack detail page must use the new component, not the legacy inline CTA.
    const page = readSource('../pages/pack/[id].tsx');
    const legacyLabel = /Get instant access/;
    expect(
      page.match(legacyLabel),
      'pages/pack/[id].tsx must not encode the legacy "Get instant access" label',
    ).toBeNull();
  });

  it('mobile sticky bar uses PackBuyButton (legacy "Buy, £" label is gone)', () => {
    // The mobile sticky buy bar must use the new component.
    const page = readSource('../pages/pack/[id].tsx');
    const legacyLabel = /Buy, \{priceLabel\}/;
    expect(
      page.match(legacyLabel),
      'mobile sticky bar must not use the legacy "Buy, £" label',
    ).toBeNull();
  });

  it('BuyDrawer (containing BuyNowButton) imports PackBuyButton', () => {
    // The audit identified BuyNowButton as a separate buy-flow component.
    // After US-1, BuyNowButton (defined in BuyDrawer.tsx) must be replaced by
    // the canonical PackBuyButton. The drawer itself stays as the post-click panel.
    const buyDrawer = readSource('../components/checkout/BuyDrawer.tsx');
    const importsBuyButton = /import[\s\S]*PackBuyButton[\s\S]*from\s+['"]@\/components\/checkout\/PackBuyButton['"]/.test(
      buyDrawer,
    );
    expect(
      importsBuyButton,
      'BuyDrawer.tsx must import PackBuyButton (the BuyNowButton is replaced)',
    ).toBe(true);
  });

  it('BuyNowButton is no longer exported from BuyDrawer', () => {
    // After US-1, the legacy BuyNowButton export is removed in favour of PackBuyButton.
    const buyDrawer = readSource('../components/checkout/BuyDrawer.tsx');
    const stillExports = /export\s+function\s+BuyNowButton/.test(buyDrawer);
    expect(
      stillExports,
      'BuyNowButton must be removed from BuyDrawer.tsx (replaced by PackBuyButton)',
    ).toBe(false);
  });
});

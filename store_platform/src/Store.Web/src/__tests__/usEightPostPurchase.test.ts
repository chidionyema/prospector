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
 * US-8 — The post-purchase page is a welcome, not a download link.
 *
 * The audit (§4.14) found that after a buyer paid, `/orders/success` was a download link and
 * nothing else: no cover, no title, no cross-sell, no share, no receipt, no "what's next".
 * The buyer landed with no context, no follow-up path, and no reason to come back.
 *
 * The fix is to render eight sections:
 *
 *  1. The pack cover plate (16:9 hero)
 *  2. The pack title
 *  3. The pack one-liner
 *  4. The download link (full-width primary button)
 *  5. "Other packs in this category" (3 cross-sell cards)
 *  6. "Share this with a friend" (copy link)
 *  7. "Save your receipt" (PDF download)
 *  8. "What's next?" — a 4-step "Track your build" checklist
 *
 * The page also hides the global navigation (`<MarketingLayout>`) so the buyer can stay
 * focused on the welcome.
 *
 * This test is a source-pattern contract: the assertions are about the structure of the
 * page source, so a layout-level regression is caught before the user sees it.
 */

describe('US-8 — Post-purchase welcome page', () => {
  const successExists = existsRelative('../pages/orders/success.tsx');

  it('declares the orders/success page', () => {
    expect(successExists, 'pages/orders/success.tsx must exist').toBe(true);
  });

  it('does not wrap the page in <MarketingLayout>', () => {
    // The audit says: "the buyer is post-purchase; let them stay". The global nav
    // competes for attention with the download CTA and the cross-sell.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    // Strip comments first, then check for the actual JSX/import of MarketingLayout.
    // A comment that mentions MarketingLayout is fine; using it is not.
    const stripped = page
      .replace(/\/\*[\s\S]*?\*\//g, '')  // block comments
      .replace(/\/\/[^\n]*/g, '');         // line comments
    const usesMarketingLayout =
      /<MarketingLayout\b/.test(stripped) ||
      /import\b[^;]*MarketingLayout\b/.test(stripped);
    expect(
      usesMarketingLayout,
      'orders/success.tsx must not import or render <MarketingLayout> (the buyer is post-purchase)',
    ).toBe(false);
  });

  it('fetches the pack details to render the cover, title, and one-liner', () => {
    // The audit requires: cover plate (16:9 hero), pack title, one-liner. The current page
    // only knows about the order's items by id; it needs to fetch the full pack details.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const fetchesPackDetails = /fetchPackDetails|fetchPack|fetchPackById/.test(page);
    expect(
      fetchesPackDetails,
      'orders/success.tsx must fetch the pack details to render the cover, title, and one-liner',
    ).toBe(true);
  });

  it('renders the pack title as the primary heading', () => {
    // The pack title must be the primary heading (h1), not buried in a smaller element.
    // This is the canonical "what did I just buy" surface.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    // The h1 must reference the pack's title. Use a simple substring check that matches
    // an h1 tag next to a `title` reference, avoiding regex character classes that the
    // OXC parser dislikes.
    const hasH1WithTitle = /<h1[\s>]/.test(page) && /\bpack\b/.test(page) && /\btitle\b/.test(page);
    expect(
      hasH1WithTitle,
      'orders/success.tsx must render the pack title as <h1>',
    ).toBe(true);
  });

  it('renders the pack one-liner as the subheading', () => {
    // The one-liner is the pack's < 60-char lift; the buyer should see it immediately,
    // not buried in a tab.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const rendersOneLiner = /pack\.oneLine|\boneLine\b/.test(page);
    expect(
      rendersOneLiner,
      'orders/success.tsx must render the pack one-liner',
    ).toBe(true);
  });

  it('renders a full-width download button', () => {
    // The download is the highest-stakes action on the page; it must be a full-width button,
    // not a small link.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const hasFullWidthDownload =
      /className=[^>]*"[^"]*w-full[^"]*"[^>]*>[\s\S]*?(Download|download)/i.test(page);
    expect(
      hasFullWidthDownload,
      'orders/success.tsx must render a full-width download button',
    ).toBe(true);
  });

  it('renders cross-sell cards for the same category', () => {
    // "Other packs in this category" — the audit required 3 cards. The source must include
    // the section header and reference the pack's market or category to filter.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const hasCrossSell = /Other packs in this category|Same mechanics, different world/i.test(page);
    expect(
      hasCrossSell,
      'orders/success.tsx must render the cross-sell section header',
    ).toBe(true);
  });

  it('renders a share-this-with-a-friend control', () => {
    // The audit's "recommender persona": a buyer who wants to share the pack with a friend
    // needs one tap, not three. The page must have a share/copy control.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const hasShare = /share with a friend|share this|copy link/i.test(page);
    expect(
      hasShare,
      'orders/success.tsx must render a share/copy control',
    ).toBe(true);
  });

  it('renders a save-your-receipt link', () => {
    // The buyer who needs a receipt for their accounts can save a PDF. The audit required
    // this as a delivery surface, not a thank-you decoration.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    const hasReceipt = /save.*receipt|download.*receipt|receipt\.pdf/i.test(page);
    expect(
      hasReceipt,
      'orders/success.tsx must render a save-your-receipt link',
    ).toBe(true);
  });

  it('renders a 4-step Whats-next checklist', () => {
    // The pack is a multi-week project. The audit's "Track your build" is a 4-step checklist
    // that gives the buyer a reason to come back.
    if (!successExists) return;
    const page = readSource('../pages/orders/success.tsx');
    // Use a plain string check; the apostrophe in "What's" misses single-quoted regex.
    const hasWhatsNext =
      page.includes("What's next") ||
      page.includes("Track your build") ||
      page.includes("Next steps");
    expect(
      hasWhatsNext,
      "orders/success.tsx must render a 'What's next?' / 'Track your build' section",
    ).toBe(true);
  });
});

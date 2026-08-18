import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

/**
 * US-4 — Mobile-first pack detail.
 *
 * The audit (§4.4) found the pack detail page was a 6,000-word essay on a 375px
 * viewport. The buy button was buried after scrolling 4,000 words of methodology.
 * The fix is to surface the buy action above the fold, collapse the methodology
 * behind disclosures, and put the strongest case against the idea *before* the
 * deliverables (US-6 owns the move; this story owns the mobile-first structure).
 *
 * Out of scope: desktop layout. The mobile layout is the focus. The desktop
 * layout keeps its two-column structure (the right rail is preserved on lg+).
 */
describe('US-4 — Mobile-first pack detail', () => {
  const page = readSource('../pages/pack/[id].tsx');

  it('renders the pack cover plate before the title on mobile', () => {
    // The cover is the first thing the buyer sees on mobile, the same way a
    // product page on any 2026 storefront leads with imagery.
    const coverBeforeTitle =
      page.indexOf('PackCover') < page.indexOf('<h1');
    expect(
      coverBeforeTitle,
      'pack/[id].tsx must render <PackCover> before the <h1> title',
    ).toBe(true);
  });

  it('keeps the price and the buy action reachable on mobile at any scroll position', () => {
    // REWRITTEN 2026-08-17, and the old version is the reason. It read:
    //
    //   page.indexOf('mt-8 border border-border bg-surface p-6 lg:hidden')
    //     < page.indexOf('How we tried to kill it')
    //
    // That class string never appeared in the page -- the live element carried `rounded-md` in
    // the middle of it -- so `indexOf` returned -1 and the assertion passed as `-1 < 4213`. It
    // was green for as long as it existed and it never once checked anything. A source scan for
    // a literal class string is exactly the assertion that fails this way, which is why the
    // replacement asserts on the STRUCTURE instead.
    //
    // MASTER-BRIEF §7 then deleted the block it was named after: "one sticky buy box, one
    // closing bar", against a live page rendering the full price panel twice plus a bar. The
    // inline `lg:hidden` copy is gone. What guarantees the audit's property now is the fixed
    // bar, which keeps price and button within a thumb from ANY scroll position -- strictly
    // more than a block that happened to sit above the methodology.
    expect(page).toContain('fixed inset-x-0 bottom-0');
    expect(page).not.toContain('lg:hidden">\n              {checkoutBody}');
  });

  it('collapses the six-check methodology behind a <details> disclosure', () => {
    // The audit: "collapse 'six checks' + 'scored axes' behind a single
    // 'Show me how this was vetted' disclosure." The buyer who cares will tap
    // to expand; the buyer who doesn't see the buy button first.
    const hasDetailsForChecks =
      /<details\b[^>]*>[\s\S]{0,2000}How we tried to kill it/.test(page) ||
      /<details\b[^>]*>[\s\S]{0,2000}show the methodology/i.test(page);
    expect(
      hasDetailsForChecks,
      'pack/[id].tsx must wrap the six-check methodology in a <details> disclosure',
    ).toBe(true);
  });

  it('collapses the scored axes behind a <details> disclosure', () => {
    const hasDetailsForAxes =
      /<details\b[^>]*>[\s\S]{0,2000}How it scores/.test(page) ||
      /<details\b[^>]*>[\s\S]{0,2000}the stress test/i.test(page);
    expect(
      hasDetailsForAxes,
      'pack/[id].tsx must wrap the scored axes in a <details> disclosure',
    ).toBe(true);
  });

  it('mobile sticky buy bar is always rendered (not hidden by scroll)', () => {
    // The audit: "the mobile sticky buy bar should be visible on page load, not
    // hidden behind scroll." The bar is rendered unconditionally when canCheckout
    // is true; it is not gated on a scroll position.
    const stickyUnconditional =
      /\{canCheckout && !clientSecret && \(\s*<div className="fixed inset-x-0 bottom-0/.test(page);
    expect(
      stickyUnconditional,
      'pack/[id].tsx must render the mobile sticky buy bar unconditionally (no scroll gate)',
    ).toBe(true);
  });

  it('mobile sticky buy bar uses the canonical PackBuyButton', () => {
    // The bar must use <PackBuyButton variant="sticky">, not a one-off button.
    // US-1 established the buy button as a single component; the sticky bar
    // must not regress to a local button.
    const stickyUsesPackBuyButton =
      /<PackBuyButton[\s\S]{0,500}variant=["']sticky["']/.test(page);
    expect(
      stickyUsesPackBuyButton,
      'pack/[id].tsx must use <PackBuyButton variant="sticky"> in the mobile sticky bar',
    ).toBe(true);
  });

  it('renders the deliverables before the methodology disclosures', () => {
    // The audit: "the deliverables are the question that stalls a digital
    // purchase... and it has to be answered before the trust argument." So
    // What's inside comes first, then the methodology (collapsed), then the
    // strongest case (US-6 will own the move).
    // The page uses a curly apostrophe ('); match either.
    const deliverablesIdx = Math.max(
      page.indexOf("What's inside your pack"),
      page.indexOf("What\u2019s inside your pack"),
    );
    /*
     * Scoped to the METHODOLOGY disclosures by name, not to `page.search(/<details\b/)`.
     *
     * The loose version broke on a change it should not have caught: the v3 pass collapsed the
     * modelled-economics table into a `<details>` inside the purchase panel, which is composed
     * higher in the file than the main column but renders in the right rail (and, on mobile, in
     * the buy drawer). "First <details> in source order" is therefore not the same question as
     * "first disclosure the buyer scrolls past", and only the second one is the audit's claim.
     */
    /*
     * "How we tried to kill it" LEFT THIS LIST ON 2026-08-18.
     *
     * `mockups/pack-detail.html:364` draws it as the page's FIRST section, open, ahead of the
     * deliverables. The drawing is the specification, so the page now follows it: the kill
     * attempt, then who could run it, then a look inside, then what you get. US-4's claim is
     * unchanged for the section it was actually about -- the scored axes stay behind the
     * deliverables, because a buyer meets the goods before the scoring method.
     */
    const methodologyIdx = Math.min(
      ...['How it scores'].map((s) => page.indexOf(s)).filter((i) => i > 0),
    );
    expect(deliverablesIdx, 'the deliverables heading must exist').toBeGreaterThan(0);
    expect(Number.isFinite(methodologyIdx), 'the methodology disclosures must exist').toBe(true);
    expect(
      deliverablesIdx < methodologyIdx,
      'pack/[id].tsx must render "What\u2019s inside your pack" before "How it scores"',
    ).toBe(true);
  });

  it('preserves the desktop two-column layout (right rail) on lg+', () => {
    // The mobile-first restructure must not regress the desktop layout. The
    // right-rail purchase card stays, with the same classes, on lg+.
    const keepsDesktopRail =
      // Width-agnostic on purpose: the claim is that the rail is hidden below `lg` and a
      // fixed-width block at `lg`, not that it is 20rem. The measure moved to the
      // drawing's 394px on 2026-08-18.
      /hidden w-full shrink-0 lg:block lg:w-/.test(page);
    expect(
      keepsDesktopRail,
      'pack/[id].tsx must keep the desktop right-rail purchase card (hidden below lg, shown on lg+)',
    ).toBe(true);
  });
});

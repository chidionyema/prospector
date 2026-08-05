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
 * L4 - The pricing page.
 *
 * The audit (§6) said: "The IA is missing four pages entirely: a real
 * /pricing page. The store sells one product at one price. The 'pricing'
 * page is a single page: '£49, every pack, what's included, what's not,
 * refund policy.' The buyer who searches for 'mumchimp pricing' finds
 * nothing."
 *
 * Out of scope (per the spec): a /blog, /about, or /case-studies. Those
 * require real content strategy and customer data; the pricing page is
 * the lowest-friction concrete page to ship.
 */
describe('L4 - The pricing page', () => {
  const pageExists = existsRelative('../pages/pricing.tsx');

  it('declares a /pricing page', () => {
    expect(pageExists, 'pages/pricing.tsx must exist').toBe(true);
  });

  it('takes its price from the catalogue rather than a literal', () => {
    /*
     * SUPERSEDED. This used to be `/£49|GBP\s*49|\$\{?49/.test(page)` -- "pages/pricing.tsx must
     * render the £49 price". Two things went wrong with it.
     *
     * First it became false. The segment price ladder (`feat(pricing)` #105/#107) ended
     * one-price, and on 2026-08-05 `GET https://api.mumchimp.com/catalog` returned 61 packs at
     * £29 x5, £49 x48, £79 x5, £99, £149, £199. A pricing page headed "£49 a pack" was wrong for
     * 13 of them.
     *
     * Second, and worse, a source-text regex for a NUMBER cannot tell rendered copy from a
     * comment. Once the page carried a comment explaining the old price, the assertion passed on
     * the comment -- green, and guarding nothing. So the contract asserted here is structural:
     * the page must fetch, and must not contain a hardcoded price in its JSX at all.
     */
    if (!pageExists) return;
    const page = readSource('../pages/pricing.tsx');
    expect(page, 'the pricing page must read the live catalogue').toMatch(/getServerSideProps/);
    expect(page).toMatch(/priceRange\(/);

    const jsx = page.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const literals = jsx.match(/£\s?\d+/g) ?? [];
    expect(literals, `hardcoded prices in JSX: ${literals.join(', ')}`).toEqual([]);
  });

  it('renders a "What\u2019s included" section', () => {
    if (!pageExists) return;
    const page = readSource('../pages/pricing.tsx');
    const hasIncluded = page.includes("What's included") || page.includes("What\u2019s included");
    expect(
      hasIncluded,
      'pages/pricing.tsx must render a "What\u2019s included" section',
    ).toBe(true);
  });

  it('renders the 14 day money back guarantee', () => {
    if (!pageExists) return;
    const page = readSource('../pages/pricing.tsx');
    const hasRefund = /14\s*day\s*(money\s*back)?/i.test(page);
    expect(
      hasRefund,
      'pages/pricing.tsx must render the 14 day money back guarantee',
    ).toBe(true);
  });

  it('renders a primary buy CTA that links to the catalogue', () => {
    if (!pageExists) return;
    const page = readSource('../pages/pricing.tsx');
    const hasBuyCta = /<Link\s+[^>]*href=["']\/?["']/.test(page) || /<Link\s+[^>]*href=["']\/#catalog["']/.test(page);
    expect(
      hasBuyCta,
      'pages/pricing.tsx must render a primary buy CTA linking to the catalogue',
    ).toBe(true);
  });

  it('links to the refund policy page', () => {
    if (!pageExists) return;
    const page = readSource('../pages/pricing.tsx');
    const hasRefundLink = /href=["']\/refund["']/.test(page);
    expect(
      hasRefundLink,
      'pages/pricing.tsx must link to /refund',
    ).toBe(true);
  });
});

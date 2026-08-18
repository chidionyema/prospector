import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Source-level contract test for the breadcrumb-on-storefront-routes pass.
 *
 * Mirrors the conventions of `uiPolishContract.test.ts` — read the source as text and assert
 * structural facts that the verify chain cannot catch on its own. Each `describe` block
 * corresponds to one numbered item in the spec so the failure output points at the section, not
 * at a mystery.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));
const read = (rel: string) => readFileSync(`${SRC}/${rel}`, 'utf8');

const ROUTES = [
  'pages/about.tsx', 'pages/account/index.tsx', 'pages/faq.tsx',
  'pages/how-it-works.tsx', 'pages/collections/index.tsx', 'pages/collections/[slug].tsx',
  'pages/kill-log.tsx', 'pages/orders/[token].tsx', 'pages/orders/success.tsx',
  'pages/pricing.tsx', 'pages/sample.tsx',
];

describe('every visual route offers a way back', () => {
  it.each(ROUTES)('%s passes breadcrumbs to MarketingLayout', (route) => {
    const src = read(route);
    expect(src).toMatch(/breadcrumbs=\{/);
    expect(src).toMatch(/label:\s*'Catalogue'/);
  });

  it('the three legal routes inherit their trail from LegalDoc', () => {
    expect(read('components/LegalDoc.tsx')).toMatch(/breadcrumbs=\{/);
  });

  it('pack/[id].tsx still renders its own Breadcrumbs', () => {
    expect(read('pages/pack/[id].tsx')).toMatch(/<Breadcrumbs/);
  });

  it('the home page does NOT carry a trail', () => {
    expect(read('pages/index.tsx')).not.toMatch(/breadcrumbs=\{/);
  });
});

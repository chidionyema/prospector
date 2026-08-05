import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function readSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

/**
 * N2 - Personalised catalogue.
 *
 * The audit (§5.1) said: "After a buyer views 1-2 packs, show a 'Based on
 * your browsing' row with similar packs. The SimilarPacks component already
 * exists; surface it on the catalog page."
 *
 * Out of scope: building a new personalisation engine. The audit's
 * prescription is the existing `similarPacks` algorithm, surfaced on the
 * home page when there is a recently viewed pack to anchor on.
 *
 * The mechanism: a server-side cookie set by the pack detail page,
 * read by the home page's getServerSideProps. The existing
 * `RecentlyViewed` row uses localStorage, which the lint rule forbids.
 * Cookie is the right shape for a single first-party signal.
 */
describe('N2 - Personalised catalogue', () => {
  const page = readSource('../pages/index.tsx');
  const packPage = readSource('../pages/pack/[id].tsx');

  it('pack detail page writes the recently-viewed cookie, not localStorage', () => {
    // The existing localStorage-based tracking is forbidden by the lint rule
    // (XSS-exfiltratable). N2 replaces it with a first-party cookie.
    // The pack detail page must set the cookie (server-side) when rendering.
    // Strip comments first so a docstring mentioning localStorage does not
    // trigger a false positive.
    const stripped = packPage
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '');
    const writesCookie =
      /res\.setHeader\(\s*['"]Set-Cookie['"][\s\S]*?recentlyViewed/.test(stripped);
    const usesLocalStorage = /localStorage/.test(stripped);
    expect(
      writesCookie && !usesLocalStorage,
      'pack/[id].tsx must write the recently-viewed cookie and not use localStorage',
    ).toBe(true);
  });

  it('home page reads the recently-viewed cookie in getServerSideProps', () => {
    // The cookie is the bridge between the pack detail page (writer) and the
    // home page (reader). The home page must read it server-side so the
    // personalised row is in the initial HTML, not added after hydration.
    const readsCookie = /cookies\.recentlyViewed|cookies\[['\"]recentlyViewed['\"]\]|req\.cookies/i.test(page);
    expect(
      readsCookie,
      'index.tsx must read the recently-viewed cookie in getServerSideProps',
    ).toBe(true);
  });

  it('home page renders a "Based on your browsing" row', () => {
    // The audit: the row's label is "Based on your browsing" when the
    // buyer has viewed a pack. Falls back to "Trending picks" otherwise.
    const hasPersonalisedRow = /Based on your browsing/i.test(page);
    expect(
      hasPersonalisedRow,
      'index.tsx must render a "Based on your browsing" row when the cookie is set',
    ).toBe(true);
  });

  it('personalised row uses the existing similarPacks algorithm', () => {
    // The audit: "the data already exists (SimilarPacks already computes
    // similarity)." The home page must call similarPacks, not a new
    // personalisation function.
    const usesSimilarPacks = /similarPacks\b/.test(page);
    expect(
      usesSimilarPacks,
      'index.tsx must use the existing similarPacks function for the personalised row',
    ).toBe(true);
  });
});

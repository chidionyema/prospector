import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * A COUNT OF WHAT IS ON THE SHELF RIGHT NOW IS READ WHEN THE VISITOR ASKS, OR IT IS NOT PRINTED.
 *
 * Measured 2026-08-19. `verify.mjs` C1 asserts every page states the same pack count, and it
 * failed minutes after a clean build: `/` and `/ideas` said 76, `/pricing` said 75. Both numbers
 * came from the same catalogue. `/pricing` used `getStaticProps` with `revalidate: 300`, so its
 * copy was generated when the build ran, and listing a pack does not trigger a redeploy.
 *
 * `/kill-log` carried the identical defect and C1 missed it, because that page writes the number
 * without the word "packs" after it and the check's regex needs both. A defect a check misses by
 * wording is still a defect, which is why this test reads the SOURCE rather than the rendered
 * page: it fails on the mechanism, not on a phrase.
 *
 * `stats.ts` states the same invariant in prose and enforces it by refusing to export a published
 * count. This is that rule, enforced for the pages.
 *
 * If a page here genuinely needs caching, the fix is to stop printing the live count on it, not
 * to widen this list.
 */
const PAGES_DIR = join(__dirname, '..', 'pages');
const LIVE_SOURCES = ['fetchCatalog', 'fetchCatalogStats'];

function pageFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return pageFiles(path);
    return /\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe('catalogue counts', () => {
  it('are never generated at build time', () => {
    const offenders = pageFiles(PAGES_DIR)
      .map((path) => ({ path, src: readFileSync(path, 'utf8') }))
      .filter(({ src }) => LIVE_SOURCES.some((fn) => src.includes(`${fn}(`)))
      .filter(({ src }) => /export const getStaticProps/.test(src) || /\brevalidate:/.test(src))
      .map(({ path }) => path.slice(path.indexOf('src/pages')));

    expect(
      offenders,
      `these pages read the live catalogue and then cache the result at build time, so the ` +
        `number they print drifts from every page that reads it at request time: ` +
        `${offenders.join(', ')}`,
    ).toEqual([]);
  });
});

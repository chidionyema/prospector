import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * THE PARITY HARNESS MUST COMPARE TWO REAL THINGS.
 *
 * `scripts/mockup_diff.mjs` screenshots a drawing and the built page beside it and writes
 * `docs/design/MOCKUP_DIFF.md`. Its PAIRS table is hand-maintained, and for as long as the
 * harness has existed one line of it named `collections.html`, which is not in the bundle,
 * against `/collections`, which answers 308. The static server returned its own 404 body for the
 * drawing and Next returned the redirect body for the page, so the harness measured two error
 * pages against each other and reported "collections: +2808px, 4.12x" in every report it ever
 * wrote. Meanwhile `ideas.html` was in the bundle and `/ideas` answered 200, and nothing compared
 * them.
 *
 * A fabricated row is worse than a missing one: it is a number on a design document that someone
 * works down. This test refuses a PAIRS entry that does not name a drawing on disk and a page in
 * the router, so the class cannot come back the next time a page is renamed.
 *
 * It reads the harness as text rather than importing it, because the harness imports playwright
 * and opens browsers at module load.
 *
 * Run via `npm test mockupPairs`.
 */
const WEB = fileURLToPath(new URL('..', import.meta.url)); // src/
const REPO = join(WEB, '..', '..', '..', '..'); // repo root, four up from Store.Web/src
const HARNESS = join(WEB, '..', 'scripts', 'mockup_diff.mjs');
const MOCKUPS = join(REPO, 'docs', 'design', 'mumchimp-build-bundle', 'mockups');
const PAGES = join(WEB, 'pages');

type Pair = { name: string; mock: string; route: string | null };

/** Parse the PAIRS literal out of the harness source. A `route` of `process.env...|| null` is
 *  a page the harness discovers at run time and cannot be checked here. */
function pairs(): Pair[] {
  const src = readFileSync(HARNESS, 'utf8');
  const block = src.match(/const PAIRS = \[([\s\S]*?)\n\];/);
  expect(block, 'PAIRS table not found in scripts/mockup_diff.mjs').toBeTruthy();
  const out: Pair[] = [];
  for (const line of block![1].split('\n')) {
    const m = line.match(/\{\s*name:\s*'([^']+)',\s*mock:\s*'([^']+)',\s*route:\s*([^}]+?)\s*\}/);
    if (!m) continue;
    const routeExpr = m[3].trim();
    const literal = routeExpr.match(/^'([^']*)'$/);
    out.push({ name: m[1], mock: m[2], route: literal ? literal[1] : null });
  }
  return out;
}

/** Next pages router: `/x` is pages/x.tsx or pages/x/index.tsx; `/` is pages/index.tsx. */
function routeResolves(route: string): boolean {
  const rel = route.replace(/^\/+/, '') || 'index';
  return ['.tsx', '.ts', '/index.tsx', '/index.ts'].some((suffix) =>
    existsSync(join(PAGES, rel + suffix)),
  );
}

const PAIRS = pairs();

describe('mockup_diff PAIRS names drawings and pages that exist', () => {
  it('finds the table at all', () => {
    expect(PAIRS.length).toBeGreaterThan(8);
  });

  it('every drawing named is in the mockup bundle', () => {
    const missing = PAIRS.filter((p) => !existsSync(join(MOCKUPS, p.mock)));
    expect(missing.map((p) => `${p.name} -> ${p.mock}`), 'no such drawing').toEqual([]);
  });

  it('every literal route named is a page in the router', () => {
    const missing = PAIRS.filter((p) => p.route !== null && !routeResolves(p.route));
    expect(missing.map((p) => `${p.name} -> ${p.route}`), 'no such page').toEqual([]);
  });

  it('names each drawing once, so no page is measured twice', () => {
    const mocks = PAIRS.map((p) => p.mock);
    expect(mocks.length - new Set(mocks).size, 'duplicate drawing in PAIRS').toBe(0);
  });

  /* Both halves of the check have to be able to say no, or the two assertions above pass by
     being unable to fail. The dead route this was written for cannot be named here: it is banned
     from source by collectionsRename.test.ts, which is the right ban. The docblock names it. */
  it('both halves can actually refuse something', () => {
    expect(existsSync(join(MOCKUPS, 'no-such-drawing.html'))).toBe(false);
    expect(routeResolves('/no-such-page')).toBe(false);
  });

  /* Vacuity: both roots have to be the real directories, or every assertion above is checking
     an empty list against an empty list. */
  it('is looking at the real bundle and the real router', () => {
    expect(existsSync(join(MOCKUPS, 'index.html'))).toBe(true);
    expect(existsSync(join(PAGES, 'index.tsx'))).toBe(true);
  });
});

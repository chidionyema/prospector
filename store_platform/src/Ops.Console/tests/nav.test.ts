/**
 * The nav is a map, so it can be checked against the territory.
 *
 * Two failures this pins, both of which have shipped in consoles before: a nav entry pointing at a
 * page that does not exist (a dead tab), and a page with no nav entry (a screen you can only reach
 * by typing the URL — which is how the Money and Data screens would have landed unreachable).
 *
 * It also pins the reason the nav was regrouped: a single flat strip of thirteen destinations ran
 * off the side of a 390px phone, so the last entries were reachable only by swiping a strip that
 * gave no sign it could be swiped.
 */
import { readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { GROUPS, activeScreen } from '@/lib/nav';

const PAGES_DIR = fileURLToPath(new URL('../src/pages', import.meta.url));

/** Routes with no nav entry by design: the wrapper, the door, and detail routes reached by link. */
const NOT_IN_NAV = new Set(['/_app', '/_document', '/login']);

function routes(dir: string, prefix = ''): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name === 'api') continue;
    const full = `${dir}/${name}`;
    if (statSync(full).isDirectory()) {
      out.push(...routes(full, `${prefix}/${name}`));
    } else if (/\.tsx$/.test(name)) {
      const stem = name.replace(/\.tsx$/, '');
      if (stem.startsWith('[')) continue; // a detail route, reached from its list
      out.push(stem === 'index' ? prefix || '/' : `${prefix}/${stem}`);
    }
  }
  return out;
}

const ROUTES = routes(PAGES_DIR);
const NAV_HREFS = GROUPS.flatMap((g) => g.screens.map((s) => s.href));

describe('the nav matches the pages', () => {
  it('finds the pages at all', () => {
    expect(ROUTES.length).toBeGreaterThan(8);
  });

  it('every nav entry has a page', () => {
    expect(NAV_HREFS.filter((h) => !ROUTES.includes(h))).toEqual([]);
  });

  it('every screen is reachable from the nav', () => {
    const orphans = ROUTES.filter((r) => !NOT_IN_NAV.has(r) && !NAV_HREFS.includes(r));
    expect(orphans).toEqual([]);
  });

  it('has no duplicate destinations', () => {
    expect(new Set(NAV_HREFS).size).toBe(NAV_HREFS.length);
  });
});

describe('neither row is long enough to scroll off a phone', () => {
  // 390px is the iPhone width the console is read at. Short pills wrap onto more lines; thirteen
  // flat destinations did not fit at all. The numbers are the budget, not a description of today's
  // list. The ceiling moved from six to seven when the Shop group landed: the group row WRAPS, so
  // one more short label costs a line of header, not a sideways scroll. Raise it again only with a
  // measurement at 390px, never because the list grew.
  //
  // The screen ceiling moved from four to five on 2026-08-20, when Reports landed beside Docs in
  // the Data group. Measured, not assumed. Two angles, because a raised ceiling is not something
  // this file can put back once a page depends on it:
  //   code — `Shell.tsx:102` and `Shell.tsx:121` are both `flex flex-wrap`, so neither row can
  //     scroll sideways at any width; a longer row costs a line of header;
  //   browser — `e2e/mobile.spec.ts` walked eleven screens with the Data group at FIVE screens,
  //     `/audit` and `/reports` among them, and every one measured
  //     `documentElement.scrollWidth - clientWidth <= 0`. 6 passed, 0 failed: 390x844 in 17.6s and
  //     320x568 in 25.3s, so the wider row holds at 320px too, not only at the 390px this comment
  //     asks for.
  // Read that against a fresh `next build`. An earlier run of the same spec reported `/config`
  // overflowing by 7px at 320px; the server is `next start`, so it was serving a stale `.next` and
  // the 7px was the old bundle, not the code. Build before you believe a phone measurement.
  it('at most seven groups', () => {
    expect(GROUPS.length).toBeLessThanOrEqual(7);
  });

  it('at most five screens in a group', () => {
    for (const g of GROUPS) expect(g.screens.length).toBeLessThanOrEqual(5);
  });

  it('labels stay short enough to sit on one line', () => {
    for (const g of GROUPS) {
      expect(g.label.length).toBeLessThanOrEqual(9);
      for (const s of g.screens) expect(s.label.length).toBeLessThanOrEqual(11);
    }
  });
});

describe('the current screen is found by longest match', () => {
  it('root does not claim every path', () => {
    expect(activeScreen('/spend')?.screen.href).toBe('/spend');
    expect(activeScreen('/spend')?.group.label).toBe('Money');
    expect(activeScreen('/')?.screen.href).toBe('/');
  });

  it('a detail route stays inside its own group', () => {
    expect(activeScreen('/runs/abc123')?.screen.href).toBe('/runs');
    expect(activeScreen('/runs/abc123')?.group.label).toBe('Engine');
  });

  it('an unknown path matches nothing rather than guessing', () => {
    expect(activeScreen('/nowhere')).toBeNull();
  });

  it('the new screens are in the groups that own their question', () => {
    expect(activeScreen('/money')?.group.label).toBe('Money');
    expect(activeScreen('/data')?.group.label).toBe('Data');
  });

  it('the shop screens are in the Shop group', () => {
    for (const path of ['/orders', '/revenue', '/delivery', '/disputes']) {
      expect(activeScreen(path)?.group.label, path).toBe('Shop');
    }
  });

  it('one order stays inside Shop rather than falling back to the root', () => {
    expect(activeScreen('/orders/ord_123')?.screen.href).toBe('/orders');
    expect(activeScreen('/orders/ord_123')?.group.label).toBe('Shop');
  });
});

describe('Shop sits between Shelf and Money', () => {
  // The order is the walk an operator makes when a buyer says they paid and got nothing: what is
  // on offer, what actually sold, whether the rail that took the money is healthy.
  it('is in that position in the map', () => {
    const labels = GROUPS.map((g) => g.label);
    expect(labels.indexOf('Shop')).toBe(labels.indexOf('Shelf') + 1);
    expect(labels.indexOf('Money')).toBe(labels.indexOf('Shop') + 1);
  });
});

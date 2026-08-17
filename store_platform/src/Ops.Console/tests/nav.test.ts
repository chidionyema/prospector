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
const NOT_IN_NAV = new Set(['/_app', '/login']);

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
  // 390px is the iPhone width the console is read at. Six short pills fit on two wrapped lines;
  // thirteen did not fit at all. The numbers are the budget, not a description of today's list.
  it('at most six groups', () => {
    expect(GROUPS.length).toBeLessThanOrEqual(6);
  });

  it('at most four screens in a group', () => {
    for (const g of GROUPS) expect(g.screens.length).toBeLessThanOrEqual(4);
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
});

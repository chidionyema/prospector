import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The catalogue's click-through instrument has to be CALLED, not merely built.
 *
 * This file exists because the instrument shipped once with nothing calling it. The hook, the
 * click helper, the API endpoint and the read endpoint were all written and all tested, and the
 * storefront sent zero events, because no page passed the hook to a card. Every test passed and
 * the measurement did not exist.
 *
 * These are SOURCE checks, not render checks. There is no React render harness in this suite (no
 * `@testing-library/react` in `package.json`), so what can be proven cheaply is that the call
 * sites are present and that no card tracks a click without also counting a sighting. What these
 * cannot prove is that a real browser emits the beacons; that needs the deployed site and the
 * `/internal/analytics/card-ctr` reading.
 */

const SRC = fileURLToPath(new URL('..', import.meta.url));

function read(relativeToSrc: string): string {
  return readFileSync(join(SRC, relativeToSrc), 'utf8');
}

/** Every `.tsx`/`.ts` under `src/`, tests excluded, as `{ path, src }`. */
function walkSource(dir: string = SRC, out: { path: string; src: string }[] = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walkSource(path, out);
    else if (entry.endsWith('.tsx') || entry.endsWith('.ts')) {
      out.push({ path: path.slice(SRC.length), src: readFileSync(path, 'utf8') });
    }
  }
  return out;
}

/**
 * Every `<PackRow` element in the tree, as the text of its own props block.
 *
 * Deliberately crude: from the opening tag to the first `/>`, which is enough because every call
 * site is self-closing. A nested element inside `PackRow` would break this, and the test failing
 * is the right outcome then. It means the crude reader needs replacing, not skipping.
 */
function packRowElements(): { path: string; element: string }[] {
  const found: { path: string; element: string }[] = [];
  for (const { path, src } of walkSource()) {
    let from = 0;
    for (;;) {
      const open = src.indexOf('<PackRow\n', from);
      if (open === -1) break;
      const close = src.indexOf('/>', open);
      found.push({ path, element: src.slice(open, close === -1 ? open + 400 : close + 2) });
      from = open + 1;
    }
  }
  return found;
}

describe('card click-through instrument is wired to real call sites', () => {
  it('the row counts both halves on the element that is seen and clicked', () => {
    const src = read('components/discovery/PackRow.tsx');
    expect(src).toContain("import { trackCardClick } from '@/lib/analytics'");
    expect(src).toContain("import { useCardImpressions } from '@/lib/useCardImpressions'");
    // The sighting and the click hang off the same `<Link>`, so a row cannot be counted as
    // clicked without having been counted as seen.
    expect(src).toContain('ref={observeRef}');
    expect(src).toContain('onClick={() => trackCardClick(pack.id, position)}');
  });

  it('the shared list creates one observer and gives every row its id and place', () => {
    const src = read('components/discovery/PackRow.tsx');
    const list = src.slice(src.indexOf('export function PackRowList'));
    expect(list).toContain('const { observe } = useCardImpressions();');
    expect(list).toContain('observeRef={observe(pack.id)}');
    expect(list).toContain('position={i + 1}');
    // The hook must run before the empty-list return, or React sees a conditional hook.
    expect(list.indexOf('useCardImpressions()')).toBeLessThan(list.indexOf('packs.length === 0'));
  });

  it("the home shelf's own row list counts too", () => {
    // The shelf renders `PackRow` directly to keep its per-row `hidden` class, so it is the one
    // list that does not inherit the wiring from `PackRowList`.
    const src = read('pages/index.tsx');
    const shelf = src.slice(src.indexOf('function ShelfRows'), src.indexOf('function CatalogBrowser'));
    expect(shelf).toContain('const { observe } = useCardImpressions();');
    expect(shelf).toContain('observeRef={observe(pack.id)}');
    expect(shelf).toContain('position={i + 1}');
  });

  it('no card anywhere reports a click without also counting the sighting', () => {
    const elements = packRowElements();
    // A guard that finds nothing to guard is the failure this whole file is about.
    expect(elements.length).toBeGreaterThan(0);
    const unwired = elements.filter((e) => !e.element.includes('observeRef='));
    expect(unwired.map((e) => e.path)).toEqual([]);
  });

  it('every card call site passes a position, so a good title is not confused with a high one', () => {
    const missing = packRowElements()
      .filter((e) => !e.element.includes('position='))
      .map((e) => e.path);
    expect(missing).toEqual([]);
  });
});

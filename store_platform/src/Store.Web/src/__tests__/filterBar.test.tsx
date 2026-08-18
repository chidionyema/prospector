import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { resolveFlags, DEFAULT_FLAGS } from '@/lib/flags';
import {
  decodeDiscoveryState,
  encodeDiscoveryState,
  filterPacks,
  isFiltered,
  priceCeilings,
  pricePenceOf,
  EMPTY_DISCOVERY_STATE,
  type FacetedPack,
} from '@/lib/discovery';

/**
 * THE ONE FILTER SYSTEM (MASTER-BRIEF §7), and the flag §8 asks it to ship behind.
 *
 * Three things are pinned here and they fail in three different ways.
 *
 * The FLAG, because a flag that defaults the wrong way is a silent release: the old path would
 * vanish for every visitor the moment this merges, and the week of comparison §8 asks for would
 * never happen.
 *
 * The PRICE FACET, because it is new state in a URL codec that already round-trips six other
 * fields. A field that encodes and does not decode is a shared link that quietly drops a filter.
 *
 * The BAR'S WIRING, at the source level, because the defect it exists to fix is two controls
 * writing the same state. The assertion that matters is that the page renders ONE of the two
 * paths, never both.
 */

const SRC = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

const INDEX = SRC('../pages/index.tsx');
const BAR = SRC('../components/discovery/FilterBar.tsx');

// ---------------------------------------------------------------------------

describe('the filter bar flag', () => {
  it('is on by default, because the bar is what the drawing draws', () => {
    // It shipped off, for a week of comparison against the wizard. The comparison is over: the
    // mockups are the spec now, `mockups/index.html` section 6 is this bar, and no mockup on the
    // site draws `StepFlow` at all. The wizard stays reachable at `?ff=wizard` rather than being
    // deleted in the same change that stops rendering it.
    expect(DEFAULT_FLAGS.filterBar).toBe(true);
    expect(resolveFlags({}).filterBar).toBe(true);
  });

  it('is turned on by the environment, not by a rebuild', () => {
    for (const on of ['1', 'true', 'on', 'YES', ' True ']) {
      expect(resolveFlags({ MUMCHIMP_FILTER_BAR: on }).filterBar, on).toBe(true);
    }
    for (const off of ['0', 'false', 'off', 'no']) {
      expect(resolveFlags({ MUMCHIMP_FILTER_BAR: off }).filterBar, off).toBe(false);
    }
  });

  it('treats a typo as unset rather than as false', () => {
    // "flase" is not a decision to turn it off. It falls through to the default, which is what
    // an operator would want on the day they mistype the value that was already on.
    expect(resolveFlags({ MUMCHIMP_FILTER_BAR: 'flase' }).filterBar).toBe(DEFAULT_FLAGS.filterBar);
  });

  it('lets the URL force either path for one request', () => {
    expect(resolveFlags({}, { ff: 'filterbar' }).filterBar).toBe(true);
    expect(resolveFlags({ MUMCHIMP_FILTER_BAR: '1' }, { ff: 'wizard' }).filterBar).toBe(false);
    // Unknown value is not a vote. It falls back to the environment.
    expect(resolveFlags({ MUMCHIMP_FILTER_BAR: '1' }, { ff: 'nonsense' }).filterBar).toBe(true);
  });

  it('is read from the request environment, never from a build-time constant', () => {
    // NEXT_PUBLIC_* is inlined at build time, so a flag defined that way cannot be flipped
    // without a redeploy -- which is a release, not a flag. See `lib/flags.ts`.
    expect(SRC('../lib/flags.ts').replace(/\/\*[\s\S]*?\*\//g, '')).not.toContain('NEXT_PUBLIC');
    expect(INDEX).toContain('resolveFlags(process.env, context.query)');
  });
});

// ---------------------------------------------------------------------------

/** The live ladder, measured 2026-08-05 and recorded in `priceRange.ts`. */
function pack(id: string, price: string, extra: Partial<FacetedPack> = {}): FacetedPack {
  return { id, title: id, price, ...extra };
}

const SHELF: FacetedPack[] = [
  pack('a', '£29'),
  pack('b', '£49'),
  pack('c', '£49'),
  pack('d', '£79'),
  pack('e', '£199'),
];

describe('the price ceiling', () => {
  it('reads pence from the money rail field first, and the display string second', () => {
    expect(pricePenceOf(pack('x', '£49'))).toBe(4900);
    expect(pricePenceOf(pack('x', '£49', { pricePence: 4999 }))).toBe(4999);
    expect(pricePenceOf(pack('x', '£1,299.50'))).toBe(129950);
    expect(pricePenceOf(pack('x', ''))).toBeNull();
  });

  it('offers every distinct price except the dearest, ascending', () => {
    const offered = priceCeilings(SHELF, EMPTY_DISCOVERY_STATE);
    expect(offered.map((c) => c.pence)).toEqual([2900, 4900, 7900]);
    // A ceiling at the top price selects the whole shelf, so it is a control that does nothing.
    expect(offered.map((c) => c.pence)).not.toContain(19900);
  });

  it('counts what each ceiling would yield, not how many sit exactly on it', () => {
    const offered = priceCeilings(SHELF, EMPTY_DISCOVERY_STATE);
    expect(offered.map((c) => c.count)).toEqual([1, 3, 4]);
  });

  it('offers nothing on a uniform shelf, because that is not a choice', () => {
    const uniform = [pack('a', '£49'), pack('b', '£49')];
    expect(priceCeilings(uniform, EMPTY_DISCOVERY_STATE)).toEqual([]);
  });

  it('recomputes counts under the rest of the state, with its own constraint removed', () => {
    const tagged = [
      pack('a', '£29', { sector: 'employment_pay' }),
      pack('b', '£49', { sector: 'employment_pay' }),
      pack('c', '£79', { sector: 'compliance' }),
      pack('d', '£199', { sector: 'compliance' }),
    ];
    const state = { ...EMPTY_DISCOVERY_STATE, sector: 'employment_pay' as const, maxPence: 2900 };
    const offered = priceCeilings(tagged, state);
    // Options still come from the whole shelf, so they do not appear and vanish as the sector
    // moves; the COUNTS are what narrow.
    expect(offered.map((c) => c.pence)).toEqual([2900, 4900, 7900]);
    expect(offered.map((c) => c.count)).toEqual([1, 2, 2]);
  });

  it('keeps a pack whose price we cannot read', () => {
    // A parse failure is our defect, not an expensive pack. Hiding it turns a data bug into a
    // product nobody can find, on the facet a buyer is most likely to be using.
    const shelf = [pack('a', '£29'), pack('b', '')];
    expect(filterPacks(shelf, { ...EMPTY_DISCOVERY_STATE, maxPence: 2900 }).map((p) => p.id)).toEqual([
      'a',
      'b',
    ]);
  });

  it('filters inclusively at the ceiling', () => {
    const ids = (max: number | null) =>
      filterPacks(SHELF, { ...EMPTY_DISCOVERY_STATE, maxPence: max }).map((p) => p.id);
    expect(ids(4900)).toEqual(['a', 'b', 'c']);
    expect(ids(null)).toHaveLength(5);
  });

  it('round-trips through the URL', () => {
    const state = { ...EMPTY_DISCOVERY_STATE, advantage: [], maxPence: 7900 };
    const qs = encodeDiscoveryState(state);
    expect(qs).toContain('maxp=7900');
    expect(decodeDiscoveryState(qs).maxPence).toBe(7900);
  });

  it('drops a ceiling that is not a positive integer rather than clamping it', () => {
    // A stale or hand-edited URL degrades to the whole shelf. Clamping would invent a filter.
    for (const bad of ['-1', 'abc', '0', '4900.5', '']) {
      expect(decodeDiscoveryState(`maxp=${bad}`).maxPence, bad).toBeNull();
    }
  });

  it('counts as a filter, so the shelf knows it is narrowed', () => {
    expect(isFiltered({ ...EMPTY_DISCOVERY_STATE, maxPence: 4900 })).toBe(true);
    expect(isFiltered(EMPTY_DISCOVERY_STATE)).toBe(false);
  });
});

// ---------------------------------------------------------------------------

describe('the bar is one system, not a fourth one', () => {
  it('renders exactly one of the two paths', () => {
    // The whole defect §7 names is two controls writing one state. `shelfControls` is the single
    // name every render site uses, and the flag picks which block it is.
    expect(INDEX).toContain('const shelfControls = flags.filterBar ? barControls : wizardControls;');
  });

  it('keeps the wizard overlay on the wizard path only', () => {
    // `FilterSheet` renders `StepFlow`. On the bar path it would be the deleted control returning
    // through an overlay.
    expect(INDEX).toContain('{!flags.filterBar && (');
  });

  it('writes discovery state through the page own `apply`', () => {
    // Not its own router.replace, which would be a second writer and a second URL format.
    expect(BAR).not.toContain('useRouter');
    expect(BAR).not.toContain('router.replace');
    expect(INDEX).toContain('onChange={apply}');
  });

  it('carries the five controls §7 names', () => {
    for (const control of ['SearchTrigger', 'Category', 'Capability', 'Price', 'Sort packs']) {
      expect(BAR, control).toContain(control);
    }
  });

  it('keeps the four facets it does not show, in the model and in the URL', () => {
    // The bar shows sector and advantage. Removing the control is not removing the filter: a
    // link that sets `?payer=b2b` must still filter the shelf.
    const state = decodeDiscoveryState('payer=b2b&effort=automatable&mechanism=vertical_tool&commitment=evenings');
    expect(state.payer).toBe('b2b');
    expect(state.effort).toBe('automatable');
    expect(state.mechanism).toBe('vertical_tool');
    expect(state.commitment).toBe('evenings');
    expect(encodeDiscoveryState(state)).toContain('payer=b2b');
  });
});

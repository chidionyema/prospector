// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Build plan D2 — the pricing instrument.
 *
 * `price_viewed` (denominator) and `checkout_started` (numerator) are the only conversion
 * signal that fires often enough to judge a ladder change by; purchases are far too rare an
 * event to learn from. These tests hold the two properties that decide whether the instrument
 * measures anything at all: the beacon carries `pack_id` and `price_pence`, and the beacon is
 * a name the SERVER accepts.
 *
 * jsdom rather than the suite's default `environment: 'node'` because `track()` returns early
 * when `window` is undefined — under node every assertion below would pass vacuously against a
 * function that emitted nothing. The vitest config's own comment sanctions the per-file opt-in.
 */

const recordAnalyticsEvent = vi.fn();
vi.mock('@/lib/api/client', () => ({
  recordAnalyticsEvent: (...args: unknown[]) => recordAnalyticsEvent(...args),
}));

const { trackPriceEvent } = await import('@/lib/analytics');

// `__dirname`, matching every other test in this suite. `import.meta.url` is NOT usable here:
// vitest loads these files through a CommonJS transform, so it is not a `file:` URL and
// `fileURLToPath` throws "The URL must be of scheme file" — which fails the whole FILE rather
// than one assertion, so it reads as the suite being broken.
const SRC = join(__dirname, '..', '..');
/** `store_platform/`, three up from `store_platform/src/Store.Web/src`. */
const REPO = join(SRC, '..', '..', '..');

beforeEach(() => {
  recordAnalyticsEvent.mockClear();
});

describe('the beacon carries the fields the instrument is made of', () => {
  it('emits pack_id and price_pence on price_viewed', () => {
    trackPriceEvent('price_viewed', { id: 'fbd10d6bdfcd5e31', pricePence: 19900 });

    expect(recordAnalyticsEvent).toHaveBeenCalledTimes(1);
    const beacon = recordAnalyticsEvent.mock.calls[0][0] as { name: string; meta: string };
    expect(beacon.name).toBe('price_viewed');
    expect(JSON.parse(beacon.meta)).toEqual({
      pack_id: 'fbd10d6bdfcd5e31',
      price_pence: 19900,
    });
  });

  it('emits pack_id and price_pence on checkout_started', () => {
    trackPriceEvent('checkout_started', { id: '0cc434887c47cb9a', pricePence: 2900 });

    const beacon = recordAnalyticsEvent.mock.calls[0][0] as { name: string; meta: string };
    expect(beacon.name).toBe('checkout_started');
    expect(JSON.parse(beacon.meta)).toEqual({
      pack_id: '0cc434887c47cb9a',
      price_pence: 2900,
    });
  });

  it('sends the pence as a NUMBER, so a reader never has to parse "£49.00" back', () => {
    trackPriceEvent('price_viewed', { id: 'p', pricePence: 4900 });
    const meta = JSON.parse((recordAnalyticsEvent.mock.calls[0][0] as { meta: string }).meta);
    expect(typeof meta.price_pence).toBe('number');
  });

  it('emits NOTHING when the API is too old to serve pricePence', () => {
    // A beacon carrying null would be counted as a view at an unknown price, and a denominator
    // inflated by unknowns is worse than a smaller honest one. This is also what keeps web and
    // API deployable in either order.
    trackPriceEvent('price_viewed', { id: 'p' });
    trackPriceEvent('checkout_started', { id: 'p', pricePence: Number.NaN });

    expect(recordAnalyticsEvent).not.toHaveBeenCalled();
  });

  it('counts a repeat view rather than collapsing it', () => {
    // The unique index is FILTERED to checkout_completed, so nothing dedups these server-side.
    // A denominator that counted each (pack, price) once would measure distinct prices, not views.
    trackPriceEvent('price_viewed', { id: 'p', pricePence: 4900 });
    trackPriceEvent('price_viewed', { id: 'p', pricePence: 4900 });

    expect(recordAnalyticsEvent).toHaveBeenCalledTimes(2);

    const migration = readFileSync(
      join(REPO, 'src', 'Store.Catalog', 'Migrations', '20260731124037_DropAnalyticsSessionId.cs'),
      'utf8',
    );
    expect(migration).toContain('filter: "\\"Name\\" = \'checkout_completed\'');
  });
});

describe('both events are wired to a real surface', () => {
  // Source-level, matching this repo's convention (no RTL setup here). The property is
  // structural: which module fires the beacon, not what it renders.
  it('fires checkout_started from the ONE shared buy path, on intent', () => {
    const hook = readFileSync(join(SRC, 'lib', 'checkout', 'usePackCheckout.ts'), 'utf8');
    expect(hook).toContain("trackPriceEvent('checkout_started', pack)");

    // Before the try, not inside it. A numerator that only counted checkouts the provider
    // managed to open would hide exactly the failure a price change is most likely to cause.
    const emit = hook.indexOf("trackPriceEvent('checkout_started'");
    const tryBlock = hook.indexOf('try {', hook.indexOf('const buy = async'));
    expect(emit).toBeGreaterThan(-1);
    expect(emit).toBeLessThan(tryBlock);
  });

  it('fires price_viewed from the pack page, keyed on the price', () => {
    const packPage = readFileSync(join(SRC, 'pages', 'pack', '[id].tsx'), 'utf8');
    expect(packPage).toContain("trackPriceEvent('price_viewed', pack)");
    // Keyed on (id, pricePence): a price that changes under a client-side navigation is a
    // separate view, and folding two prices into one would erase the thing being measured.
    expect(packPage).toContain('[pack.id, pack.pricePence]');
  });

  it('serves pricePence from both catalogue reads, or the pack page has no price to report', () => {
    const program = readFileSync(join(REPO, 'src', 'Store.Api', 'Program.cs'), 'utf8');
    expect(program).toContain('p.PricePence,');
    expect(program).toContain('pack.PricePence,');
  });
});

describe('the client and server halves of the name contract agree', () => {
  /**
   * This drifted silently and in production. The storefront was emitting pack_shared,
   * basket_removed, matchmaker_answered, palette_search and copy_variant from live call sites;
   * none of them was in the server allowlist, so every one 400d and was counted nowhere. A
   * dropped beacon is indistinguishable from a visitor who never acted, so the bug reads as
   * "nobody uses this feature" — which is the worst possible failure for an instrument.
   */
  const names = (src: string, re: RegExp) => {
    const out = new Set<string>();
    for (const m of src.matchAll(re)) out.add(m[1]);
    return out;
  };

  it('every name the client can emit is a name the server accepts', () => {
    const client = readFileSync(join(SRC, 'lib', 'analytics.ts'), 'utf8');
    const server = readFileSync(
      join(REPO, 'src', 'Store.Api', 'Endpoints', 'AnalyticsEndpoints.cs'),
      'utf8',
    );

    const union = client.slice(
      client.indexOf('export type AnalyticsEventName'),
      client.indexOf(';', client.indexOf('export type AnalyticsEventName')),
    );
    const clientNames = names(union, /'([a-z_]+)'/g);
    const allowlist = server.slice(
      server.indexOf('AllowedNames = new'),
      server.indexOf('};', server.indexOf('AllowedNames = new')),
    );
    const serverNames = names(allowlist, /"([a-z_]+)"/g);

    expect(clientNames.size).toBeGreaterThan(0);
    expect(serverNames.size).toBeGreaterThan(0);
    expect([...clientNames].filter((n) => !serverNames.has(n))).toEqual([]);
  });

  it('includes the two pricing events on both sides', () => {
    const client = readFileSync(join(SRC, 'lib', 'analytics.ts'), 'utf8');
    const server = readFileSync(
      join(REPO, 'src', 'Store.Api', 'Endpoints', 'AnalyticsEndpoints.cs'),
      'utf8',
    );
    for (const name of ['price_viewed', 'checkout_started']) {
      expect(client).toContain(`'${name}'`);
      expect(server).toContain(`"${name}"`);
    }
  });
});

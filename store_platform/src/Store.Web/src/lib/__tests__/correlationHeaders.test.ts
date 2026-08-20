import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * The buyer's correlation id: that it is minted sanely, and that no call to our API forgets it.
 *
 * The scan below exists because forgetting one is invisible. A fetch without the header still
 * succeeds, returns the right data, and breaks nothing a user or a test would notice — the only
 * casualty is the trail, discovered months later by someone trying to follow a single purchase.
 */

const read = (rel: string) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');

describe('every call to our own API carries the correlation header', () => {
  const client = read('../api/client.ts');

  /** Each `fetch(` in the file, with enough of what follows to cover its options object. */
  const callSites = (source: string): string[] => {
    const sites: string[] = [];
    let at = source.indexOf('fetch(');
    while (at !== -1) {
      sites.push(source.slice(at, at + 400));
      at = source.indexOf('fetch(', at + 1);
    }
    return sites;
  };

  const ourApiCalls = callSites(client).filter((site) =>
    site.slice(0, site.indexOf('\n') + 200).includes('API_FETCH_BASE'),
  );

  it('finds the call sites at all', () => {
    // Non-vacuity. A scan that matched nothing would pass the assertion below forever, which is
    // the exact way a source-scanning guard rots into a no-op.
    expect(ourApiCalls.length).toBeGreaterThanOrEqual(10);
  });

  it.each(ourApiCalls.map((site, i) => [i, site.split('\n')[0].trim(), site] as const))(
    'site %i — %s',
    (_i, _first, site) => {
      expect(site).toContain('correlated(');
    },
  );

  it('routes every account call through one correlated funnel', () => {
    const auth = read('../api/auth.ts');
    expect(auth).toContain('headers: correlated({');
  });

  it('leaves the third-party FX call alone', () => {
    // The id is ours and means nothing to open-er-api.com. Sending it would leak our trace key to
    // a third party and force a CORS preflight on a request that currently needs none.
    const fx = client.slice(client.indexOf("fetch('https://open.er-api.com"));
    expect(fx.slice(0, 200)).not.toContain('correlated');
  });
});

describe('the id itself', () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  const withBrowser = (storage?: Partial<Storage>) => {
    const store = new Map<string, string>();
    vi.stubGlobal('window', {
      sessionStorage: storage ?? {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    });
  };

  it('is stable for the whole tab', async () => {
    withBrowser();
    const { correlationId } = await import('../api/correlation');
    expect(correlationId()).toBe(correlationId());
  });

  it('survives the API sanitiser unchanged', async () => {
    // Store.Api keeps only [A-Za-z0-9._-] and truncates at 64. An id that does not survive that
    // filter would be silently rewritten, and the two ends would name one visit differently.
    withBrowser();
    const { correlationId } = await import('../api/correlation');
    const id = correlationId();
    expect(id).toMatch(/^[A-Za-z0-9._-]+$/);
    expect(id!.length).toBeLessThanOrEqual(64);
  });

  it('still produces an id when sessionStorage throws', async () => {
    // Safari private mode. Losing the id here would silently drop the trail for those buyers.
    withBrowser({
      getItem: () => {
        throw new Error('storage disabled');
      },
      setItem: () => {
        throw new Error('storage disabled');
      },
    });
    const { correlationId } = await import('../api/correlation');
    const id = correlationId();
    expect(id).toBeTruthy();
    expect(correlationId()).toBe(id);
  });

  it('mints nothing on the server', async () => {
    // A server render is not a buyer action. Minting one per render would fill the logs with ids
    // no browser ever sends again.
    const { correlationId, correlated } = await import('../api/correlation');
    expect(correlationId()).toBeNull();
    expect(correlated({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
    });
  });

  it('adds the header the API reads, and keeps the caller’s own headers', async () => {
    withBrowser();
    const { correlated, CORRELATION_HEADER } = await import('../api/correlation');
    const headers = correlated({ 'Content-Type': 'application/json' });
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers[CORRELATION_HEADER]).toBeTruthy();
    // The name Store.Api actually looks for: Common/HttpContextExtensions.cs CorrelationIdHeader.
    expect(CORRELATION_HEADER).toBe('X-Correlation-Id');
  });
});

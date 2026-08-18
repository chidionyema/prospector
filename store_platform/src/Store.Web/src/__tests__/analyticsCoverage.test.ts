// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Captures what the beacon would post, instead of posting it.
 *
 * `vi.hoisted` is required rather than stylistic: `vi.mock` is hoisted above every import, and
 * the factory runs while `@/lib/analytics` is being imported, which is before a plain `const`
 * at the top of this file has been evaluated.
 */
const { sent } = vi.hoisted(() => ({
  sent: [] as Array<{ name: string; meta: string | null }>,
}));

vi.mock('@/lib/api/client', () => ({
  recordAnalyticsEvent: (event: { name: string; meta?: string | null }) => {
    sent.push({ name: event.name, meta: event.meta ?? null });
    return Promise.resolve();
  },
}));

import {
  CARD_META_LIMIT,
  SCROLL_DEPTH_THRESHOLDS,
  filterChangeMeta,
  startScrollDepthTracking,
} from '@/lib/analytics';

/**
 * The event allowlist is enforced on both sides. A name in the TypeScript union that is missing
 * from `AllowedNames` gets a 400 from the API, and a dropped beacon looks exactly like a visitor
 * who never acted, so the drift is invisible in the data it corrupts.
 *
 * `AnalyticsNameContractTests` pins the same pair from the C# side. This file is the other half,
 * and it fails in the web lane, which is the lane a storefront change usually runs.
 */
/* Paths come off `process.cwd()`, which vitest sets to the package root. The sibling tests use
   `import.meta.url`, and that is a file URL only under the node environment. This file runs under
   jsdom for the scroll listener, where `import.meta.url` is an http URL and `fileURLToPath`
   throws before a single assertion runs. */
const WEB_ROOT = process.cwd();
const ANALYTICS_TS = resolve(WEB_ROOT, 'src/lib/analytics.ts');
const ANALYTICS_CS = resolve(WEB_ROOT, '../Store.Api/Endpoints/AnalyticsEndpoints.cs');

/**
 * The event names in the `AnalyticsEventName` union, read from source.
 *
 * Line by line, and only lines that start a union member. Both lists carry long comments, and a
 * scanner that matched anywhere in the block would pick names out of the prose.
 */
function clientNames(source: string): string[] {
  const lines = source.slice(source.indexOf('export type AnalyticsEventName =')).split('\n');
  const names: string[] = [];
  for (const line of lines) {
    const match = /^\s*\|\s*'([a-z0-9_]+)'/.exec(line);
    if (match) names.push(match[1]);
    if (/'\s*;\s*$/.test(line)) break;
  }
  return names;
}

/** The event names in the `AllowedNames` HashSet, read from source. */
function serverNames(source: string): string[] {
  const lines = source
    .slice(source.indexOf('AllowedNames = new(StringComparer.Ordinal)'))
    .split('\n');
  const names: string[] = [];
  for (const line of lines) {
    if (/^\s*\};/.test(line)) break;
    const match = /^\s*"([a-z0-9_]+)",\s*$/.exec(line);
    if (match) names.push(match[1]);
  }
  return names;
}

describe('the analytics name allowlist', () => {
  const client = clientNames(readFileSync(ANALYTICS_TS, 'utf8'));
  const server = serverNames(readFileSync(ANALYTICS_CS, 'utf8'));

  it('reads a real list out of both files', () => {
    // Guards the two scanners above. One that silently returned nothing would make every
    // assertion below vacuously true, which is the failure mode of a source-reading test.
    expect(client.length).toBeGreaterThan(15);
    expect(server.length).toBeGreaterThan(15);
  });

  it('holds exactly the same names on both sides', () => {
    expect([...client].sort()).toEqual([...server].sort());
  });

  it('carries every MASTER-BRIEF section 9 signal that nothing else covered', () => {
    for (const name of [
      'filter_change',
      'filter_zero_results',
      'catalogue_page_more',
      'band_view',
      'email_submit',
      'scroll_depth',
      'kill_row_click',
      'featured_click',
    ]) {
      expect(client).toContain(name);
      expect(server).toContain(name);
    }
  });

  it('did not rename the four brief names an existing event already serves', () => {
    // A rename would 400 every beacon until the API deployed, and would strand the history under
    // the old name. The events stay. The mapping is written into the docblock instead.
    for (const kept of ['page_view', 'card_click', 'sample_cta_clicked']) {
      expect(client).toContain(kept);
      expect(server).toContain(kept);
    }
    for (const briefName of [
      'landing_view',
      'grid_survivor_click',
      'pack_row_click',
      'sample_cta_click',
    ]) {
      expect(client).not.toContain(briefName);
    }
  });

  it('explains each un-added brief name in the analytics docblock', () => {
    const source = readFileSync(ANALYTICS_TS, 'utf8');
    for (const briefName of [
      'landing_view',
      'grid_survivor_click',
      'pack_row_click',
      'sample_cta_click',
    ]) {
      expect(source).toContain(briefName);
    }
  });
});

describe('filter_change meta', () => {
  it('is dimension, value and result count in one compact string', () => {
    expect(filterChangeMeta('sector', 'saas', 12)).toBe('sector:saas:12');
  });

  it('reports a cleared filter as any, so it cannot be read as a value', () => {
    expect(filterChangeMeta('payer', null, 63)).toBe('payer:any:63');
  });

  it('never carries the text a visitor typed into the search box', () => {
    expect(filterChangeMeta('q', 'my competitor ltd', 3)).toBe('q:set:3');
    expect(filterChangeMeta('q', null, 63)).toBe('q:cleared:63');
  });

  it('reduces a value that did not come from the facet list to facet-key characters', () => {
    // A query string in a facet value would mean something built the discovery state wrongly.
    // The beacon must not carry it through either way.
    expect(filterChangeMeta('sector', '/x?token=abc123', 0)).toBe('sector:-x-token-abc123:0');
  });

  it('fits the server meta limit', () => {
    expect(filterChangeMeta('commitment', 'weekend-project', 1000).length).toBeLessThanOrEqual(
      CARD_META_LIMIT,
    );
  });
});

describe('scroll depth', () => {
  beforeEach(() => {
    sent.length = 0;
    // The stub runs the callback straight away, so a test can read the measurement the real page
    // would take on the next frame without waiting for one.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function setPageHeight(scrollHeight: number, innerHeight: number, scrollY: number) {
    Object.defineProperty(document.documentElement, 'scrollHeight', {
      configurable: true,
      value: scrollHeight,
    });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: innerHeight });
    Object.defineProperty(window, 'scrollY', { configurable: true, value: scrollY });
  }

  it('reports every threshold once and only once per page view', () => {
    setPageHeight(4000, 1000, 0);
    const stop = startScrollDepthTracking();

    // A quarter of a 4000px page is on screen at the top, so 25 is met on arrival.
    expect(sent.map((e) => e.meta)).toEqual(['25']);

    setPageHeight(4000, 1000, 1000);
    window.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('scroll'));
    expect(sent.map((e) => e.meta)).toEqual(['25', '50']);

    setPageHeight(4000, 1000, 3000);
    window.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('scroll'));
    expect(sent.map((e) => e.meta)).toEqual(['25', '50', '75', '100']);
    expect(sent.every((e) => e.name === 'scroll_depth')).toBe(true);

    stop();
  });

  it('counts a page shorter than the viewport as fully read', () => {
    setPageHeight(500, 1000, 0);
    const stop = startScrollDepthTracking();
    expect(sent.map((e) => e.meta)).toEqual(SCROLL_DEPTH_THRESHOLDS.map((t) => String(t)));
    stop();
  });

  it('stops listening once every threshold has been reported', () => {
    const removed: string[] = [];
    const realRemove = window.removeEventListener.bind(window);
    vi.spyOn(window, 'removeEventListener').mockImplementation((type, listener, options) => {
      removed.push(String(type));
      realRemove(type, listener as EventListener, options as EventListenerOptions);
    });
    setPageHeight(500, 1000, 0);
    startScrollDepthTracking();
    expect(removed).toContain('scroll');
    expect(removed).toContain('resize');
  });

  it('registers the scroll listener as passive, so it cannot block the gesture', () => {
    const options: unknown[] = [];
    const realAdd = window.addEventListener.bind(window);
    vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, opts) => {
      if (type === 'scroll') options.push(opts);
      realAdd(type, listener as EventListener, opts as AddEventListenerOptions);
    });
    setPageHeight(4000, 1000, 0);
    const stop = startScrollDepthTracking();
    expect(options).toEqual([{ passive: true }]);
    stop();
  });
});

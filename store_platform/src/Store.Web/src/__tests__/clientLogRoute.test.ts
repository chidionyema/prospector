/**
 * `POST /api/client-log` is the storefront's only route into the central log.
 *
 * The thing worth pinning is not that it works; it is WHERE THE KEY IS. The ingest is reachable
 * only on Fly's private network and authenticates with `STORE_INTERNAL_API_KEY`, so the browser
 * cannot be the client. This route is the hop, and the last test in this file is the one that
 * fails if somebody moves the shipper into a page and publishes the key in client JavaScript.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { NextApiRequest, NextApiResponse } from 'next';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import handler from '@/pages/api/client-log';
import { counters, reset } from '@/lib/centralLog';

const KEY = 'test-ingest-key';
const URL_ = 'http://ingest.invalid/internal/logs';
const SRC = fileURLToPath(new URL('..', import.meta.url));

let saved: Record<string, string | undefined> = {};

function makeRes() {
  const res = {
    statusCode: 0,
    headers: {} as Record<string, string>,
    body: undefined as unknown,
    ended: false,
    setHeader(name: string, value: string) {
      res.headers[name] = value;
      return res;
    },
    status(code: number) {
      res.statusCode = code;
      return res;
    },
    json(payload: unknown) {
      res.body = payload;
      res.ended = true;
      return res;
    },
    end() {
      res.ended = true;
      return res;
    },
  };
  return res;
}

function makeReq(over: Partial<NextApiRequest> = {}): NextApiRequest {
  return {
    method: 'POST',
    headers: {},
    body: {},
    ...over,
  } as NextApiRequest;
}

function bodyOf(fetchMock: ReturnType<typeof vi.fn>, call = 0) {
  const [, init] = fetchMock.mock.calls[call] as unknown as [string, RequestInit];
  return JSON.parse(String(init.body).trim().split('\n')[0]) as Record<string, unknown>;
}

beforeEach(() => {
  saved = {
    STORE_INTERNAL_API_KEY: process.env.STORE_INTERNAL_API_KEY,
    PROSPECTOR_LOG_INGEST_URL: process.env.PROSPECTOR_LOG_INGEST_URL,
  };
  process.env.STORE_INTERNAL_API_KEY = KEY;
  process.env.PROSPECTOR_LOG_INGEST_URL = URL_;
  reset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  reset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

describe('POST /api/client-log', () => {
  it('ships the crash as store-web and answers 204 with no body', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 204 }) as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    const res = makeRes();
    await handler(
      makeReq({
        headers: { 'x-correlation-id': 'corr-123', 'user-agent': 'Safari/1' },
        body: {
          where: 'ErrorBoundary',
          message: 'Cannot read properties of undefined',
          stack: 'at Pack (pack.tsx:12)',
          componentStack: '\n at Pack',
        },
      }),
      res as unknown as NextApiResponse,
    );

    expect(res.statusCode).toBe(204);
    expect(res.body).toBeUndefined();
    expect(res.headers['Cache-Control']).toBe('no-store');

    const line = bodyOf(fetchMock);
    expect(line.svc).toBe('store-web');
    expect(line.evt).toBe('web.client_error');
    expect(line.lvl).toBe('error');
    expect(line.msg).toBe('Cannot read properties of undefined');
    // The id that joins this crash to the buyer's API calls either side of it.
    expect(line.corr).toBe('corr-123');
    const ctx = line.ctx as Record<string, unknown>;
    expect(ctx.where).toBe('ErrorBoundary');
    expect(ctx.stack).toBe('at Pack (pack.tsx:12)');
    expect(ctx.ua).toBe('Safari/1');
  });

  it('answers 405 to anything but POST', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const res = makeRes();
    await handler(makeReq({ method: 'GET' }), res as unknown as NextApiResponse);
    expect(res.statusCode).toBe(405);
    expect(res.headers.Allow).toBe('POST');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('still answers 204 when the ingest is unreachable', async () => {
    // The buyer's page is already broken. A reporter that 500s here would turn a recovered
    // crash into a second one.
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    }));
    const res = makeRes();
    await handler(makeReq({ body: { message: 'boom' } }), res as unknown as NextApiResponse);
    expect(res.statusCode).toBe(204);
    expect(counters.failed_posts).toBe(1);
  });

  it('writes the crash to stderr as well, which is the copy that survives an unconfigured ingest',
    async () => {
      delete process.env.STORE_INTERNAL_API_KEY;
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);
      const res = makeRes();
      await handler(makeReq({ body: { message: 'boom' } }), res as unknown as NextApiResponse);
      expect(fetchMock).not.toHaveBeenCalled();
      expect(console.error).toHaveBeenCalled();
      const said = (console.error as unknown as { mock: { calls: unknown[][] } }).mock.calls
        .map((c) => String(c[0])).join('\n');
      expect(said).toContain('boom');
      expect(res.statusCode).toBe(204);
    });
});

describe('the ingest key stays on the server', () => {
  it('is never imported by anything the browser downloads', () => {
    // `lib/centralLog.ts` reads STORE_INTERNAL_API_KEY. Next bundles a module into the client
    // when a page or component imports it, so an import from anywhere but `pages/api/` would
    // publish the key. The check is a source scan because the failure is invisible at runtime:
    // the page still works, and the key is simply in the JavaScript.
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = path.join(dir, entry);
        if (statSync(full).isDirectory()) {
          walk(full);
          continue;
        }
        if (!/\.(ts|tsx)$/.test(entry)) continue;
        const rel = path.relative(SRC, full);
        if (rel.startsWith('pages/api/') || rel.startsWith('lib/centralLog') ||
            rel.includes('__tests__')) continue;
        if (/from ['"](@\/lib\/centralLog|.*\/centralLog)['"]/.test(readFileSync(full, 'utf8'))) {
          offenders.push(rel);
        }
      }
    };
    walk(SRC);
    expect(offenders, 'these reach the browser and would publish STORE_INTERNAL_API_KEY').toEqual([]);
  });
});

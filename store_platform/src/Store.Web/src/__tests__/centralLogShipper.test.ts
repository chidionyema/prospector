/**
 * The Node shipper's contract with `prospector/log_ingest.py`.
 *
 * Every assertion here is one the ingest or the design document already imposes, restated where
 * a change to this file would break it: the wire format (Part 4.4), the bearer header, the `svc`
 * regex that is the ingest's path-traversal gate, the redaction list that stops a token reaching
 * disk, and the two rules that keep a logging fault from becoming an outage -- it never throws,
 * and it drops rather than retrying.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { configured, counters, flush, ingestUrl, reset, ship, toLine } from '@/lib/centralLog';

const KEY = 'test-ingest-key';
const URL_ = 'http://ingest.invalid/internal/logs';

let saved: Record<string, string | undefined> = {};

function setEnv(key: string | undefined, url: string | undefined) {
  if (key === undefined) delete process.env.STORE_INTERNAL_API_KEY;
  else process.env.STORE_INTERNAL_API_KEY = key;
  if (url === undefined) delete process.env.PROSPECTOR_LOG_INGEST_URL;
  else process.env.PROSPECTOR_LOG_INGEST_URL = url;
}

/** A fetch that records what it was given and answers 204. */
function okFetch() {
  return vi.fn(async () => ({ ok: true, status: 204 }) as unknown as Response);
}

beforeEach(() => {
  // Restore, never assume: library code that leaves an env var behind fails other files, not
  // this one, which is the hardest kind of failure to attribute.
  saved = {
    STORE_INTERNAL_API_KEY: process.env.STORE_INTERNAL_API_KEY,
    PROSPECTOR_LOG_INGEST_URL: process.env.PROSPECTOR_LOG_INGEST_URL,
  };
  setEnv(KEY, URL_);
  reset();
});

afterEach(() => {
  reset();
  vi.unstubAllGlobals();
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

describe('the wire format', () => {
  it('is one NDJSON line per record, bearer-authenticated', async () => {
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);

    expect(ship({ svc: 'store-web', evt: 'web.client_error', lvl: 'error', msg: 'boom' })).toBe(true);
    expect(ship({ svc: 'store-web', evt: 'web.other' })).toBe(true);
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(URL_);
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${KEY}`);
    expect(headers['Content-Type']).toBe('application/x-ndjson');

    const lines = String(init.body).trim().split('\n');
    expect(lines).toHaveLength(2);
    const first = JSON.parse(lines[0]) as Record<string, unknown>;
    expect(first.svc).toBe('store-web');
    expect(first.evt).toBe('web.client_error');
    expect(first.lvl).toBe('error');
    expect(first.msg).toBe('boom');
    // The ingest sets `host` from the connection so a client cannot claim to be another
    // service. Sending one would be a claim it is entitled to overwrite.
    expect(first).not.toHaveProperty('host');
    // `log_ingest.py rfc3339` writes exactly three fractional digits and a Z.
    expect(String(first.ts)).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(counters.sent).toBe(2);
  });

  it('defaults an unset level to info rather than dropping the line', () => {
    expect(toLine({ svc: 'store-web', evt: 'x' }).lvl).toBe('info');
  });

  it('makes `evt` a machine name, so counting by it is possible', () => {
    expect(toLine({ svc: 'store-web', evt: 'Web Client Error!' }).evt).toBe('web.client.error');
    expect(toLine({ svc: 'store-web', evt: '   ' }).evt).toBe('log.unnamed');
  });
});

describe('redaction', () => {
  it('replaces any ctx field whose NAME looks like a secret', () => {
    const line = toLine({
      svc: 'store-web',
      evt: 'x',
      ctx: {
        session_cookie: 'abc',
        api_key: 'sk-live-1',
        Authorization: 'Bearer y',
        private_pem: '-----BEGIN',
        where: 'ErrorBoundary',
        status: 500,
      },
    });
    expect(line.ctx).toEqual({
      session_cookie: '[redacted]',
      api_key: '[redacted]',
      Authorization: '[redacted]',
      private_pem: '[redacted]',
      where: 'ErrorBoundary',
      status: 500,
    });
  });

  it('uses the same names `prospector/log_shipper.py` uses', () => {
    // Both ends of one estate. A name redacted by the Python shipper and not by this one is a
    // token on disk, and the difference would only ever be noticed by reading the log file.
    for (const name of [
      'key', 'secret', 'token', 'password', 'passwd', 'credential',
      'authorization', 'auth', 'cookie', 'session', 'pem', 'private',
    ]) {
      const line = toLine({ svc: 'store-web', evt: 'x', ctx: { [`a_${name}_b`]: 'value' } });
      expect(line.ctx?.[`a_${name}_b`], `${name} travelled in the clear`).toBe('[redacted]');
    }
  });
});

describe('it cannot become an outage', () => {
  it('is a no-op with no key, and says so in a counter rather than in an exception', async () => {
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    setEnv(undefined, URL_);

    expect(configured()).toBe(false);
    expect(ship({ svc: 'store-web', evt: 'x' })).toBe(false);
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(counters.dropped_unconfigured).toBe(1);
  });

  it('swallows a fetch that throws', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    }));
    ship({ svc: 'store-web', evt: 'x' });
    await expect(flush()).resolves.toBeUndefined();
    expect(counters.failed_posts).toBe(1);
    expect(counters.sent).toBe(0);
  });

  it('drops a failed batch instead of retrying it', async () => {
    // A retry queue grows during exactly the outage that caused the failure. The ingest refuses
    // backpressure at the other end for the same reason; this is the same rule on this side.
    const fetchMock = vi.fn(async () => ({ ok: false, status: 503 }) as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    ship({ svc: 'store-web', evt: 'x' });
    await flush();
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(counters.failed_posts).toBe(1);
  });

  it('drops the OLDEST line when the buffer is full, and counts it', async () => {
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    for (let i = 0; i < 1200; i += 1) ship({ svc: 'store-web', evt: 'x', msg: `line-${i}` });
    expect(counters.dropped_full).toBe(200);
    await flush();
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
    const sentMessages = calls
      .flatMap(([, init]) => String(init.body).trim().split('\n'))
      .map((l) => (JSON.parse(l) as { msg: string }).msg);
    expect(sentMessages).toHaveLength(1000);
    // The newest survived; the first 200 are the ones that went.
    expect(sentMessages[0]).toBe('line-200');
    expect(sentMessages[sentMessages.length - 1]).toBe('line-1199');
  });
});

describe('the service name is a security gate, not a label', () => {
  it('refuses a name the ingest would turn into a path', () => {
    // `log_ingest.py` builds a FILENAME from `svc`. Its own regex is the gate; this one keeps a
    // bad name from ever being sent, so the failure is visible here and not as a silent 400.
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    for (const bad of ['../../../etc/cron.d/x', 'Store-Web', '', 'a'.repeat(33), '9web']) {
      expect(ship({ svc: bad, evt: 'x' }), `${bad} was accepted`).toBe(false);
    }
    expect(counters.dropped_malformed).toBe(5);
  });

  it('accepts the names the ingest already knows', () => {
    for (const good of ['store-web', 'console', 'store-api', 'engine']) {
      expect(ship({ svc: good, evt: 'x' }), `${good} was refused`).toBe(true);
    }
  });
});

describe('the default url', () => {
  it('is the engine over the private network when nothing overrides it', () => {
    setEnv(KEY, undefined);
    expect(ingestUrl()).toBe('http://prospector-engine.internal:8613/internal/logs');
  });
});

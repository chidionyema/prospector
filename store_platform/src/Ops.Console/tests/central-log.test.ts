/**
 * The console's events reach the central log, not just its own volume.
 *
 * `logConsoleEvent` already wrote two copies of every refused, failed or slow request: one to
 * stderr and one to `store/ops/console_events.jsonl`. Both are readable only by somebody with a
 * shell on the machine, so the console's own faults were the one thing the console could not
 * show. This adds a third destination -- the central ingest, as `svc: "console"` -- and these
 * tests pin that the third one cannot cost the request the other two already survive.
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { counters, reset } from '@/lib/centralLog';
import { levelFor, logConsoleEvent } from '@/lib/oplog';

const KEY = 'test-ingest-key';
const URL_ = 'http://ingest.invalid/internal/logs';

let dir = '';
let saved: Record<string, string | undefined> = {};

function okFetch() {
  return vi.fn(async () => ({ ok: true, status: 204 }) as unknown as Response);
}

function lines(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.flatMap(([, init]) =>
    String((init as RequestInit).body).trim().split('\n').map(
      (l) => JSON.parse(l) as Record<string, unknown>,
    ));
}

beforeEach(() => {
  saved = {
    STORE_INTERNAL_API_KEY: process.env.STORE_INTERNAL_API_KEY,
    PROSPECTOR_LOG_INGEST_URL: process.env.PROSPECTOR_LOG_INGEST_URL,
    PROSPECTOR_STORE_DIR: process.env.PROSPECTOR_STORE_DIR,
  };
  dir = mkdtempSync(join(tmpdir(), 'ops-central-log-'));
  process.env.PROSPECTOR_STORE_DIR = dir;
  process.env.STORE_INTERNAL_API_KEY = KEY;
  process.env.PROSPECTOR_LOG_INGEST_URL = URL_;
  reset();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(async () => {
  const { flush } = await import('@/lib/centralLog');
  await flush().catch(() => {});
  reset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

describe('every console event also goes to the central ingest', () => {
  it('arrives as svc console, with the kind as the event name', async () => {
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    logConsoleEvent({ kind: 'read_failed', view: 'money', status: 502, message: 'upstream died' });
    const { flush } = await import('@/lib/centralLog');
    await flush();

    const [line] = lines(fetchMock);
    expect(line.svc).toBe('console');
    expect(line.evt).toBe('console.read_failed');
    expect(line.lvl).toBe('error');
    expect(line.msg).toBe('upstream died');
    const ctx = line.ctx as Record<string, unknown>;
    expect(ctx.view).toBe('money');
    expect(ctx.status).toBe(502);
    // `kind` is already the event name and `ts`/`at` are the file copy's own stamp; repeating
    // them in ctx would make every console line carry three timestamps.
    expect(ctx).not.toHaveProperty('kind');
    expect(ctx).not.toHaveProperty('at');
  });

  it('grades the severity from the kind, because no call site passes one', () => {
    expect(levelFor('read_failed')).toBe('error');
    expect(levelFor('act_failed')).toBe('error');
    expect(levelFor('client_error')).toBe('error');
    expect(levelFor('read_refused')).toBe('warn');
    expect(levelFor('read_slow')).toBe('warn');
    expect(levelFor('signin_ok')).toBe('info');
  });

  it('never lets the password out, because the redaction is on the field NAME', async () => {
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    logConsoleEvent({
      kind: 'signin_failed',
      message: 'bad password',
      // `who` is the only identity field the console records; a call site that ever adds one of
      // these must not be able to publish it by naming it.
      detail: 'x',
      ...( { session_cookie: 'abc', api_token: 'sk-1' } as Record<string, string> ),
    });
    const { flush } = await import('@/lib/centralLog');
    await flush();
    const ctx = lines(fetchMock)[0].ctx as Record<string, unknown>;
    expect(ctx.session_cookie).toBe('[redacted]');
    expect(ctx.api_token).toBe('[redacted]');
  });

  it('cannot fail the request it is describing', async () => {
    vi.stubGlobal('fetch', () => {
      throw new Error('ECONNREFUSED');
    });
    expect(() => logConsoleEvent({ kind: 'read_failed', message: 'x' })).not.toThrow();
    const { flush } = await import('@/lib/centralLog');
    await expect(flush()).resolves.toBeUndefined();
  });

  it('is a silent no-op with no ingest key, and the other two copies still happen', () => {
    delete process.env.STORE_INTERNAL_API_KEY;
    const fetchMock = okFetch();
    vi.stubGlobal('fetch', fetchMock);
    logConsoleEvent({ kind: 'read_failed', message: 'x' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(counters.dropped_unconfigured).toBe(1);
    // stderr is one of the two that survive; the volume copy is covered by console-log.test.ts.
    expect(console.error).toHaveBeenCalled();
  });
});

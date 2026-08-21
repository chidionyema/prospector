/**
 * The console's own black box.
 *
 * On 2026-08-18 every tab rendered blank at once, the cause was an expired session, and NOTHING
 * anywhere recorded that. `fly logs --no-tail` returns 100 lines — about four minutes on a
 * generating daemon — so by the time it was reported the evidence had scrolled away and the
 * fault was reasoned about rather than read.
 *
 * These tests pin the three things that make the next occurrence readable: the refusal is
 * written down, the write can never cost the request, and the password never reaches the file.
 */
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { envelope, makeReq, makeRes } from './helpers';

const opsRead = vi.fn();
vi.mock('@/lib/ops', () => ({
  EXPECTED_CONTRACT: 1,
  opsRead: (...args: unknown[]) => opsRead(...args),
}));

const { default: readHandler } = await import('@/pages/api/ops/read/[view]');
const { default: sessionHandler } = await import('@/pages/api/ops/session');
const { KEEP, eventsPath, logConsoleEvent } = await import('@/lib/oplog');
const { mintSession, COOKIE_NAME } = await import('@/lib/auth');

const PASSWORD = 'test-password';
let dir = '';

function rows(): Record<string, unknown>[] {
  const p = eventsPath();
  if (!existsSync(p)) return [];
  return readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'ops-log-'));
  process.env.PROSPECTOR_STORE_DIR = dir;
  process.env.CONTROL_CENTER_PASSWORD = PASSWORD;
  opsRead.mockReset();
  opsRead.mockResolvedValue({ envelope: envelope(), exitCode: 0, stderr: '' });
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  rmSync(dir, { recursive: true, force: true });
  delete process.env.PROSPECTOR_STORE_DIR;
});

describe('the blank-tab signature is written down', () => {
  it('records the view and the reason when a read is refused', async () => {
    const { res, captured } = makeRes();
    await readHandler(makeReq({ query: { view: 'money' } }), res);

    expect(captured.status).toBe(401);
    const [row] = rows();
    expect(row).toMatchObject({
      kind: 'read_refused',
      view: 'money',
      status: 401,
      error_kind: 'unauthenticated',
    });
    // The timestamp is the whole point: "every panel at 14:02" is what identifies an expired
    // session, and a row with no time cannot say that.
    expect(typeof row!.at).toBe('string');
  });

  it('says so differently when no password is configured at all', async () => {
    delete process.env.CONTROL_CENTER_PASSWORD;
    const { res } = makeRes();
    await readHandler(makeReq({ query: { view: 'money' } }), res);
    expect(rows()[0]).toMatchObject({ kind: 'read_refused', error_kind: 'unconfigured' });
  });

  it('keeps the engine’s own reason when the engine is what failed', async () => {
    opsRead.mockResolvedValue({
      envelope: envelope({ ok: false, error: 'unable to open database file', error_kind: 'StoreUnreadable' }),
      exitCode: 1,
      stderr: '',
    });
    const cookie = `${COOKIE_NAME}=${encodeURIComponent(mintSession())}`;
    const { res, captured } = makeRes();
    await readHandler(makeReq({ query: { view: 'queue' }, cookie }), res);

    expect(captured.status).toBe(502);
    expect(rows()[0]).toMatchObject({
      kind: 'read_failed',
      view: 'queue',
      status: 502,
      error_kind: 'StoreUnreadable',
      error: 'unable to open database file',
    });
  });

  it('records a read that worked but was slow, because that is the warning shot', async () => {
    // Measured 2026-08-18 in the container, the slowest view was 2.32s. Six seconds is a change.
    //
    // The clock ADVANCES INSIDE the gateway call rather than on a call count. Counting calls
    // fails silently here: the auth gate reads Date.now() before the handler does, so a
    // `mockReturnValueOnce` is spent on the session check and the read measures zero.
    let nowMs = 1_000;
    vi.spyOn(Date, 'now').mockImplementation(() => nowMs);
    opsRead.mockImplementation(async () => {
      nowMs += 6_000;
      return { envelope: envelope(), exitCode: 0, stderr: '' };
    });
    const cookie = `${COOKIE_NAME}=${encodeURIComponent(mintSession())}`;
    const { res, captured } = makeRes();
    await readHandler(makeReq({ query: { view: 'metrics' }, cookie }), res);

    expect(captured.status).toBe(200);
    expect(rows()[0]).toMatchObject({ kind: 'read_slow', view: 'metrics', took_ms: 6_000 });
  });

  it('writes nothing at all when the read simply worked', async () => {
    const cookie = `${COOKIE_NAME}=${encodeURIComponent(mintSession())}`;
    const { res, captured } = makeRes();
    await readHandler(makeReq({ query: { view: 'status' }, cookie }), res);
    expect(captured.status).toBe(200);
    // A log that also carries every success is a log nobody reads. Every line here is a fault.
    expect(rows()).toHaveLength(0);
  });
});

describe('sign-ins bracket the story, and the password is not in it', () => {
  it('records a wrong password without recording the password', async () => {
    const { res, captured } = makeRes();
    await sessionHandler(
      makeReq({ method: 'POST', body: { password: 'hunter2-not-the-real-one' } }),
      res,
    );

    expect(captured.status).toBe(401);
    expect(rows()[0]).toMatchObject({ kind: 'signin_failed', status: 401 });
    expect(readFileSync(eventsPath(), 'utf8')).not.toContain('hunter2');
  });

  it('records the sign-in that ends a run of refusals', async () => {
    const { res, captured } = makeRes();
    await sessionHandler(makeReq({ method: 'POST', body: { password: PASSWORD } }), res);
    expect(captured.status).toBe(200);
    expect(rows()[0]).toMatchObject({ kind: 'signed_in' });
    expect(readFileSync(eventsPath(), 'utf8')).not.toContain(PASSWORD);
  });
});

describe('the logger cannot cost the request', () => {
  it('answers normally when the log cannot be written', async () => {
    // A FILE where the directory should be. mkdir throws ENOTDIR, which is the closest thing to
    // a read-only volume this test can make without root.
    const blocker = join(dir, 'blocked');
    writeFileSync(blocker, 'not a directory', 'utf8');
    process.env.PROSPECTOR_STORE_DIR = blocker;

    const { res, captured } = makeRes();
    await readHandler(makeReq({ query: { view: 'money' } }), res);

    expect(captured.status).toBe(401);
    expect((captured.body as { ok: boolean }).ok).toBe(false);
  });

  // 1005 synchronous appends, each re-reading the whole file: on an idle box this is under a
  // second, and vitest's default 5s timeout is an unwritten performance assertion sitting on top
  // of the bound this test is actually about. Measured 2026-08-21 at load average 442 -- five
  // sessions share this laptop -- it took over 9s and failed the commit gate of a diff that
  // contained no TypeScript at all. The timeout below is explicit so the test fails on the
  // BEHAVIOUR (a file that grows without bound) rather than on how busy the machine is.
  it('keeps the file bounded so it can never fill the volume', () => {
    for (let i = 0; i < KEEP * 2 + 5; i += 1) {
      logConsoleEvent({ kind: 'read_failed', view: `v${i}` });
    }
    const kept = rows();
    expect(kept.length).toBeGreaterThanOrEqual(KEEP);
    expect(kept.length).toBeLessThanOrEqual(KEEP * 2);
    // Trimming keeps the NEWEST. Losing the newest would be worse than not logging.
    expect(kept[kept.length - 1]).toMatchObject({ view: `v${KEEP * 2 + 4}` });
  }, 60_000);
});

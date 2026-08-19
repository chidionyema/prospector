/**
 * The one door in this console that answers without a session.
 *
 * Every other route in `pages/api` calls `requireAuth` first. This one deliberately does not,
 * because the whole feature is handing a URL to somebody with no account. That makes it the most
 * dangerous file in the app, so what is pinned here is not "does it work" but the four things
 * that keep the exception narrow:
 *
 *   1. It reaches exactly ONE python view, `share_open`, named as a literal. It cannot reach the
 *      authed `VIEWS` list, so a bug here cannot become a read of `money` or `spend`.
 *   2. Every refusal looks the same from outside. A revoked token that says "revoked" tells an
 *      attacker the token was real, which turns the endpoint into an oracle for guessing.
 *   3. Failures are rate limited per address, on the same limiter the login route uses.
 *   4. It is the ONLY route without the auth gate, asserted by scanning the source rather than by
 *      remembering — a second one could be added tomorrow and nobody would notice.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { envelope, makeRes } from './helpers';

const opsRead = vi.fn();
vi.mock('@/lib/ops', () => ({
  EXPECTED_CONTRACT: 1,
  opsRead: (...args: unknown[]) => opsRead(...args),
}));

const { default: handler } = await import('@/pages/api/s/[token]');
const { VIEWS } = await import('@/pages/api/ops/read/[view]');
const { _reset } = await import('@/lib/ratelimit');

const SRC = fileURLToPath(new URL('../src', import.meta.url));

/** The source with comments removed, for assertions about what the code does rather than says. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}

/** A request from a named address, which `makeReq` cannot express — the limiter keys on it. */
function req(init: { method?: string; query?: Record<string, string>; ip?: string }) {
  return {
    method: init.method ?? 'GET',
    query: init.query ?? {},
    headers: init.ip ? { 'fly-client-ip': init.ip } : {},
  } as never;
}

/** The gateway's real return shape. A test that invents a simpler one tests the invention. */
function ok(data: unknown) {
  return { envelope: envelope({ data }), exitCode: 0, stderr: '' };
}

function refused(error: string) {
  return { envelope: envelope({ ok: false, error, error_kind: 'PermissionError' }), exitCode: 0, stderr: '' };
}

beforeEach(() => {
  _reset();
  opsRead.mockReset();
  opsRead.mockResolvedValue(ok({ kind: 'file', name: 'README.md', text: '# readme\n' }));
});

describe('it serves a share without a session', () => {
  it('answers a valid token with whatever the engine returned', async () => {
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'abc' }, ip: '1.1.1.1' }), res);
    expect(captured.status).toBe(200);
    expect((captured.body as { kind: string }).kind).toBe('file');
  });

  it('passes the file name through so one link can browse a tree', async () => {
    const { res } = makeRes();
    await handler(req({ query: { token: 'abc', name: 'docs/GUIDE.md' }, ip: '1.1.1.1' }), res);
    expect(opsRead.mock.calls[0]![1]).toMatchObject({ token: 'abc', name: 'docs/GUIDE.md' });
  });

  it('records the caller so the founder can answer "what did they read"', async () => {
    const { res } = makeRes();
    await handler(req({ query: { token: 'abc' }, ip: '9.9.9.9' }), res);
    expect((opsRead.mock.calls[0]![1] as { viewer: string }).viewer).toBe('9.9.9.9');
  });
});

describe('it can only reach one view', () => {
  it('names share_open and nothing else', async () => {
    const { res } = makeRes();
    await handler(req({ query: { token: 'abc' }, ip: '1.1.1.1' }), res);
    expect(opsRead.mock.calls[0]![0]).toBe('share_open');
  });

  it('does not take the view from the request', async () => {
    const { res } = makeRes();
    await handler(req({ query: { token: 'abc', view: 'money' }, ip: '1.1.1.1' }), res);
    expect(opsRead.mock.calls[0]![0]).toBe('share_open');
  });

  it('share_open is absent from the authed view list, so the two doors cannot be confused', () => {
    expect([...VIEWS]).not.toContain('share_open');
  });

  it('the handler names exactly one view, as a literal', () => {
    const source = readFileSync(`${SRC}/pages/api/s/[token].ts`, 'utf8');
    // `[^(]*` rather than `[^>]*`: the call is generic over `Record<string, unknown>`, so the
    // type argument contains its own `>` and a stop-at-first-angle pattern matched nothing at all
    // — which read as "the handler names no view", a pass turned into a false alarm.
    const views = [...source.matchAll(/opsRead(?:<[^(]*>)?\(\s*'([a-z_]+)'/g)].map((m) => m[1]);
    expect(views).toEqual(['share_open']);
    // Against the CODE, not the comments. This file explains at length why it cannot reach the
    // authed `VIEWS` list, and a scan of the raw text failed on the explanation — a test that
    // punishes documenting the fence it is checking.
    expect(code(source)).not.toContain('VIEWS');
  });
});

describe('every refusal looks the same from outside', () => {
  it('a refused token and a missing one give the same status and words', async () => {
    opsRead.mockResolvedValue(refused('revoked on 2026-08-19 by console'));
    const a = makeRes();
    await handler(req({ query: { token: 'revoked-one' }, ip: '2.2.2.2' }), a.res);

    const b = makeRes();
    await handler(req({ query: {}, ip: '3.3.3.3' }), b.res);

    expect(a.captured.status).toBe(404);
    expect(b.captured.status).toBe(404);
    expect(a.captured.body).toEqual(b.captured.body);
  });

  it('never leaks the engine reason to the caller', async () => {
    opsRead.mockResolvedValue(refused('no such share 4f2a; expired 3 days ago'));
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'x' }, ip: '2.2.2.2' }), res);
    expect(JSON.stringify(captured.body)).not.toContain('4f2a');
    expect(JSON.stringify(captured.body)).not.toContain('expired 3 days');
  });

  it('a gateway that is down looks like a bad link, not a stack trace', async () => {
    opsRead.mockRejectedValue(new Error('the engine gateway did not answer within 120000ms'));
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'abc' }, ip: '2.2.2.2' }), res);
    expect(captured.status).toBe(404);
    expect(JSON.stringify(captured.body)).not.toContain('gateway');
  });

  it('is GET only', async () => {
    const { res, captured } = makeRes();
    await handler(req({ method: 'POST', query: { token: 'abc' }, ip: '1.1.1.1' }), res);
    expect(captured.status).toBe(405);
    expect(opsRead).not.toHaveBeenCalled();
  });
});

describe('guessing costs something', () => {
  it('locks an address out after repeated refusals', async () => {
    opsRead.mockResolvedValue(refused('nope'));
    for (let i = 0; i < 5; i++) {
      const { res } = makeRes();
      await handler(req({ query: { token: `guess-${i}` }, ip: '4.4.4.4' }), res);
    }
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'guess-6' }, ip: '4.4.4.4' }), res);
    expect(captured.status).toBe(429);
  });

  it('locks the guesser, not everybody', async () => {
    opsRead.mockResolvedValue(refused('nope'));
    for (let i = 0; i < 6; i++) {
      const { res } = makeRes();
      await handler(req({ query: { token: `guess-${i}` }, ip: '4.4.4.4' }), res);
    }
    opsRead.mockResolvedValue(ok({ kind: 'file', name: 'README.md', text: 'hi' }));
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'a-real-one' }, ip: '5.5.5.5' }), res);
    expect(captured.status).toBe(200);
  });

  it('a working link does not count against the address', async () => {
    for (let i = 0; i < 8; i++) {
      const { res, captured } = makeRes();
      await handler(req({ query: { token: 'good' }, ip: '6.6.6.6' }), res);
      expect(captured.status, `read ${i}`).toBe(200);
    }
  });
});

describe('it does not end up in a search index or a cache', () => {
  it('sets noindex and no-store', async () => {
    const { res, captured } = makeRes();
    await handler(req({ query: { token: 'abc' }, ip: '1.1.1.1' }), res);
    expect(captured.headers['X-Robots-Tag']).toContain('noindex');
    expect(captured.headers['Cache-Control']).toBe('no-store');
  });
});

describe('the exception stays exactly one file wide', () => {
  function apiRoutes(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
      const full = `${dir}/${name}`;
      if (statSync(full).isDirectory()) apiRoutes(full, out);
      else if (/\.tsx?$/.test(full)) out.push(full);
    }
    return out;
  }

  it('every other API route still calls requireAuth', () => {
    // Four, and every one of them is deliberate. `session` is the sign-in route itself.
    // `client-error` is the browser's crash reporter, which must work on a page that failed
    // before the session was read. `where` names the estate for somebody staring at the login
    // screen and carries no secret. `s/[token].ts` is the share door. Anything else appearing
    // here is a hole, not a feature.
    const EXEMPT = [
      '/pages/api/ops/session.ts',
      '/pages/api/ops/client-error.ts',
      '/pages/api/ops/where.ts',
      '/pages/api/s/[token].ts',
    ];
    // A CALL, not a mention. The share route's own docstring says the word `requireAuth` while
    // explaining why it does not call it, and a substring test read that as the gate being
    // present — the exact failure this test exists to catch, hidden by prose.
    const open = apiRoutes(`${SRC}/pages/api`)
      .filter((f) => !/requireAuth\s*\(/.test(readFileSync(f, 'utf8')))
      .map((f) => f.slice(SRC.length));
    expect(open.sort()).toEqual([...EXEMPT].sort());
  });

  it('the public page carries no console chrome and no ops client', () => {
    const page = readFileSync(`${SRC}/pages/s/[token].tsx`, 'utf8');
    expect(page).not.toContain('@/components/Shell');
    expect(page).not.toContain('@/lib/ops');
    expect(page).not.toContain('@/lib/useOps');
    // It talks to its own route and only its own route.
    const urls = [...page.matchAll(/\/api\/[a-z/]*/g)].map((m) => m[0]);
    expect([...new Set(urls)]).toEqual(['/api/s/']);
  });
});

/**
 * The gate that decides whether a page's HTML is served at all.
 *
 * Three things are graded here, and the third is the one that keeps working next month:
 *
 *   1. The Edge copy of the session check agrees with the Node one in `lib/auth.ts`. Two
 *      implementations of one security check will drift unless something compares them, so
 *      every case is asserted against BOTH.
 *   2. The public allow-list names the paths that must work without a session -- the door and
 *      the share links -- and nothing else.
 *   3. Every page in `src/pages` is gated unless it is on that list. A page added tomorrow
 *      fails this test rather than shipping open.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { beforeAll, describe, expect, it } from 'vitest';

const PASSWORD = 'a-test-password-that-is-not-a-real-one';

// lib/auth.ts reads the env var on every call, so setting it before the import is not required
// -- but the import must still happen after, because a future memoisation there would silently
// make every assertion below vacuous.
process.env.CONTROL_CENTER_PASSWORD = PASSWORD;

const PAGES_DIR = fileURLToPath(new URL('../src/pages', import.meta.url));

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = `${dir}/${name}`;
    if (statSync(full).isDirectory()) walk(full, out);
    else if (full.endsWith('.tsx')) out.push(full);
  }
  return out;
}

/** `src/pages/runs/index.tsx` -> `/runs`, `src/pages/orders/[id].tsx` -> `/orders/an-id`. */
function routeOf(file: string): string {
  const rel = file.slice(PAGES_DIR.length).replace(/\.tsx$/, '');
  const path = rel.replace(/\/index$/, '').replace(/\[[^\]]+\]/g, 'a-value');
  return path === '' ? '/' : path;
}

type Auth = typeof import('@/lib/auth');
type Edge = typeof import('@/lib/sessionEdge');
type NextPath = typeof import('@/lib/nextPath');

let auth: Auth;
let edge: Edge;
let nextPath: NextPath;

beforeAll(async () => {
  auth = await import('@/lib/auth');
  edge = await import('@/lib/sessionEdge');
  nextPath = await import('@/lib/nextPath');
});

describe('the edge session check agrees with the node one', () => {
  it('uses the same cookie name', () => {
    expect(edge.OPS_COOKIE_NAME).toBe(auth.COOKIE_NAME);
  });

  it('accepts a token the node side minted', async () => {
    const token = auth.mintSession();
    expect(auth.sessionValid(token)).toBe(true);
    await expect(edge.sessionValidEdge(token, PASSWORD)).resolves.toBe(true);
  });

  it('rejects a tampered signature on both sides', async () => {
    const [expires, mac] = auth.mintSession().split('.');
    // Flip one hex digit. Same length, so a length check alone cannot catch it.
    const forged = `${expires}.${mac![0] === '0' ? '1' : '0'}${mac!.slice(1)}`;
    expect(auth.sessionValid(forged)).toBe(false);
    await expect(edge.sessionValidEdge(forged, PASSWORD)).resolves.toBe(false);
  });

  it('rejects a forged expiry, which is the whole point of signing it', async () => {
    const [, mac] = auth.mintSession().split('.');
    const forged = `${Math.floor(Date.now() / 1000) + 999_999}.${mac}`;
    expect(auth.sessionValid(forged)).toBe(false);
    await expect(edge.sessionValidEdge(forged, PASSWORD)).resolves.toBe(false);
  });

  it('rejects an expired token on both sides', async () => {
    const token = auth.mintSession();
    const wayLater = Date.now() + (auth.SESSION_TTL_S + 60) * 1000;
    expect(auth.sessionValid(token, wayLater)).toBe(false);
    await expect(edge.sessionValidEdge(token, PASSWORD, wayLater)).resolves.toBe(false);
  });

  it.each([undefined, '', 'no-dot', '.', 'abc.def', 'notanumber.deadbeef'])(
    'rejects the malformed token %p on both sides',
    async (token) => {
      expect(auth.sessionValid(token)).toBe(false);
      await expect(edge.sessionValidEdge(token, PASSWORD)).resolves.toBe(false);
    },
  );

  it('refuses everything when no password is configured, rather than letting it through', async () => {
    const token = auth.mintSession();
    await expect(edge.sessionValidEdge(token, '')).resolves.toBe(false);
  });

  it('rejects a token signed with a different password', async () => {
    const token = auth.mintSession();
    await expect(edge.sessionValidEdge(token, `${PASSWORD}-rotated`)).resolves.toBe(false);
  });
});

describe('the public allow-list', () => {
  it.each([
    ['/login', 'the door itself; gating it is a redirect loop'],
    ['/s/some-token', 'a share link is handed to someone with no console session'],
    ['/api/ops/read/status', 'API routes answer JSON 401 through requireAuth, never a redirect'],
    ['/api/s/some-token', 'the session-less share read'],
    ['/_next/static/chunk.js', 'build output; gating it renders the login page unstyled'],
    ['/favicon.ico', 'not data'],
  ])('%s is public because %s', (path) => {
    expect(edge.isPublicPath(path)).toBe(true);
  });

  it.each(['/', '/money', '/shelf', '/config', '/runs/an-id', '/share', '/orders/an-id'])(
    '%s is gated',
    (path) => {
      expect(edge.isPublicPath(path)).toBe(false);
    },
  );
});

describe('no operator page is reachable without a session', () => {
  // The two Next wrappers are not routes, and the two entries below are public BY DESIGN --
  // each for a reason written out in lib/sessionEdge.ts. Everything else must be gated.
  const PUBLIC_BY_DESIGN = new Set(['/login', '/s/a-value']);

  const routes = walk(PAGES_DIR)
    .filter((f) => !/_app\.tsx$|_document\.tsx$/.test(f))
    .map(routeOf);

  it('found the pages to grade, so this test is not vacuous', () => {
    expect(routes.length).toBeGreaterThan(20);
    expect(routes).toContain('/');
    expect(routes).toContain('/login');
  });

  it.each(routes)('%s', (route) => {
    expect(edge.isPublicPath(route)).toBe(PUBLIC_BY_DESIGN.has(route));
  });
});

describe('the post-login redirect cannot be pointed off-site', () => {
  it.each([
    ['/money', '/money'],
    ['/runs/abc?tab=logs', '/runs/abc?tab=logs'],
    ['/', '/'],
  ])('keeps the same-origin path %p', (raw, want) => {
    expect(nextPath.safeNextPath(raw)).toBe(want);
  });

  it.each([
    'https://evil.example/steal',
    '//evil.example',
    '/\\evil.example',
    '/\\/evil.example',
    'javascript:alert(1)',
    '',
    undefined,
    42,
  ])('refuses %p and falls back to /', (raw) => {
    expect(nextPath.safeNextPath(raw)).toBe('/');
  });

  it('takes the first value when the query parameter is repeated', () => {
    expect(nextPath.safeNextPath(['/money', 'https://evil.example'])).toBe('/money');
  });
});

describe('the password is read per request, not baked into the bundle', () => {
  const source = readFileSync(fileURLToPath(new URL('../src/middleware.ts', import.meta.url)), 'utf8');

  it('reads CONTROL_CENTER_PASSWORD inside the handler', () => {
    // Next compiles middleware ahead of time. A `process.env.X` read at MODULE scope is
    // evaluated during `next build` and frozen into the bundle; a read inside the handler
    // is evaluated per request. The console is built by CI, which does not hold the
    // password, so a hoisted read would freeze the empty string and lock every operator
    // out of every page — the fence failing closed on its own operators.
    //
    // Measured 2026-08-19 on a build made with no CONTROL_CENTER_PASSWORD set: starting
    // that same build WITH the password and a freshly minted cookie returned 200 for
    // /shelf, and 307 to /login?next=%2Fshelf without one. So the lookup is per request
    // today. This test is what keeps it that way.
    const handler = source.slice(source.indexOf('export async function middleware'));
    expect(handler).toContain('process.env.CONTROL_CENTER_PASSWORD');

    const beforeHandler = source.slice(0, source.indexOf('export async function middleware'));
    expect(beforeHandler).not.toContain('process.env');
  });
});

/**
 * The session check, in a form Next's middleware runtime can run.
 *
 * WHY A SECOND COPY. `lib/auth.ts` is the real gate and it stays the real gate: it runs in
 * Node, uses `node:crypto`, and every `/api/ops/*` route calls it first. Middleware runs in the
 * Edge runtime, where `node:crypto` does not exist, so importing `lib/auth.ts` there fails the
 * build. This module does the same arithmetic with Web Crypto, which both runtimes have.
 *
 * TWO COPIES OF A SECURITY CHECK IS A DRIFT RISK, so it is pinned rather than trusted:
 * `tests/middleware.test.ts` mints a token with `mintSession()` and asserts BOTH
 * implementations accept it, and that both reject a tampered one and an expired one. If they
 * ever disagree, that test fails.
 *
 * WHAT THIS IS FOR. It decides whether to serve a page's HTML at all. It is not the fence that
 * protects data — every read and write still passes `requireAuth` in `lib/auth.ts`. It exists
 * because the console used to serve the whole dashboard to anyone, then redirect to /login from
 * the BROWSER once a panel's fetch came back 401 (`lib/contract.ts:43`). Founder, 2026-08-19:
 * "i see the page before the login screen apprea". That is what this removes.
 */

/** Must equal `COOKIE_NAME` in lib/auth.ts. Pinned by tests/middleware.test.ts. */
export const OPS_COOKIE_NAME = 'ops_session';

const encoder = new TextEncoder();

async function hmacHex(key: string, payload: string): Promise<string> {
  const material = await crypto.subtle.importKey(
    'raw',
    encoder.encode(key),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', material, encoder.encode(payload));
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Compare without leaking where the first difference is. Unequal lengths are rejected up front,
 * which is safe here: both sides are fixed-width hex of a SHA-256 HMAC, so a length mismatch is
 * a malformed token rather than a near miss.
 */
function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/**
 * Same token shape as `mintSession()`: `<expiry-unix>.<hmac>`, keyed by the password itself, so
 * changing the password invalidates every live session.
 *
 * Returns false for every unusable input — no password configured, no cookie, a malformed
 * token, an expired one. An unconfigured console is locked, never open.
 */
export async function sessionValidEdge(
  token: string | undefined,
  password: string,
  now: number = Date.now(),
): Promise<boolean> {
  if (!token || !password) return false;
  const [expiresRaw, mac] = token.split('.');
  if (!expiresRaw || !mac) return false;
  const expires = Number(expiresRaw);
  if (!Number.isFinite(expires) || expires * 1000 < now) return false;
  return constantTimeEqual(await hmacHex(password, expiresRaw), mac);
}

/**
 * Paths that are served without a console session, and why each one has to be.
 *
 * This is the allow-list, so anything NOT named here is gated. A page added tomorrow is
 * therefore closed by default rather than open by default, which is the direction a mistake
 * should fall. `tests/middleware.test.ts` walks `src/pages` and fails if a new page is public
 * without being listed here deliberately.
 */
export function isPublicPath(pathname: string): boolean {
  // The door itself. Gating it would be a redirect loop.
  if (pathname === '/login') return true;
  // Share links. A share link is handed to someone who has no console session at all -- that is
  // the entire feature (task #55). Gating these would break every link already issued.
  if (pathname === '/s' || pathname.startsWith('/s/')) return true;
  // API routes answer JSON and carry their own gate (`requireAuth`). A redirect here would hand
  // the browser's `fetch` an HTML login page where it expects an envelope, so the client's 401
  // handling -- the thing that signs an operator out on expiry -- would stop working.
  if (pathname.startsWith('/api/')) return true;
  // Build output and static assets. No data, and gating them means the login page renders
  // unstyled.
  if (pathname.startsWith('/_next/')) return true;
  if (pathname === '/favicon.ico' || pathname === '/robots.txt') return true;
  return false;
}

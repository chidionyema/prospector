/**
 * One operator, one shared password, checked server-side.
 *
 * The same environment variable the Streamlit console uses (`CONTROL_CENTER_PASSWORD`), so there
 * is one password to remember rather than two to get out of step.
 *
 * FAIL CLOSED. With no password configured the console refuses everything and says why. An
 * unconfigured portal is locked, not open — `scripts/install_control_center_agent.sh` refuses to
 * install without the variable for the same reason, because launchd's KeepAlive would otherwise
 * restart a broken portal forever.
 *
 * THE NETWORK IS THE REAL FENCE. Bind one tailnet address, never 0.0.0.0. A password-only portal
 * on whatever wifi the laptop joins is not acceptable, and the single-address bind is what stops
 * it. This module cannot enforce that; `scripts/run_ops_console.sh` does.
 */
import crypto from 'node:crypto';
import type { NextApiRequest, NextApiResponse } from 'next';

export const COOKIE_NAME = 'ops_session';
export const SESSION_TTL_S = 12 * 60 * 60;

export function configuredPassword(): string {
  return process.env.CONTROL_CENTER_PASSWORD || '';
}

export function isConfigured(): boolean {
  return configuredPassword().length > 0;
}

/** Timing-safe compare. `crypto.timingSafeEqual` throws on unequal lengths, so hash first. */
export function passwordMatches(candidate: string): boolean {
  const expected = configuredPassword();
  if (!expected) return false;
  const a = crypto.createHash('sha256').update(candidate).digest();
  const b = crypto.createHash('sha256').update(expected).digest();
  return crypto.timingSafeEqual(a, b);
}

function sign(payload: string): string {
  return crypto.createHmac('sha256', configuredPassword()).update(payload).digest('hex');
}

/** `<expiry-unix>.<hmac>`. The password is the key, so changing it invalidates every session. */
export function mintSession(now = Date.now()): string {
  const expires = Math.floor(now / 1000) + SESSION_TTL_S;
  return `${expires}.${sign(String(expires))}`;
}

export function sessionValid(token: string | undefined, now = Date.now()): boolean {
  if (!token || !isConfigured()) return false;
  const [expiresRaw, mac] = token.split('.');
  if (!expiresRaw || !mac) return false;
  const expires = Number(expiresRaw);
  if (!Number.isFinite(expires) || expires * 1000 < now) return false;
  const want = sign(expiresRaw);
  if (want.length !== mac.length) return false;
  return crypto.timingSafeEqual(Buffer.from(want), Buffer.from(mac));
}

export function readCookie(req: NextApiRequest, name: string): string | undefined {
  const raw = req.headers.cookie;
  if (!raw) return undefined;
  for (const part of raw.split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return decodeURIComponent(rest.join('='));
  }
  return undefined;
}

export function setSessionCookie(res: NextApiResponse, token: string): void {
  res.setHeader(
    'Set-Cookie',
    // `Secure` is deliberately absent: the tailnet address is plain HTTP, and a Secure cookie
    // over HTTP is simply never sent, which reads as "the password did not work".
    `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${SESSION_TTL_S}`,
  );
}

export function clearSessionCookie(res: NextApiResponse): void {
  res.setHeader('Set-Cookie', `${COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0`);
}

export type AuthFailure = { status: number; body: { ok: false; error: string; reason: string } };

/**
 * The gate every API route calls first. Returns null when the request may proceed.
 */
export function requireAuth(req: NextApiRequest): AuthFailure | null {
  if (!isConfigured()) {
    return {
      status: 503,
      body: {
        ok: false,
        reason: 'unconfigured',
        error:
          'CONTROL_CENTER_PASSWORD is not set, so this console is locked. Set it in .env and ' +
          'restart. An unconfigured portal is closed, never open.',
      },
    };
  }
  if (!sessionValid(readCookie(req, COOKIE_NAME))) {
    return {
      status: 401,
      body: { ok: false, reason: 'unauthenticated', error: 'Sign in to use the console.' },
    };
  }
  return null;
}

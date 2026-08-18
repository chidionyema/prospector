/**
 * One operator, one shared password, checked server-side.
 *
 * The variable is `CONTROL_CENTER_PASSWORD`. It kept that name when the older Streamlit console
 * it was shared with was deleted (2026-08-18), because renaming it would have meant re-issuing
 * the secret on every machine and in Fly for no gain.
 *
 * FAIL CLOSED. With no password configured the console refuses everything and says why. An
 * unconfigured portal is locked, not open.
 *
 * THE NETWORK USED TO BE THE REAL FENCE, and it is not any more. Until 2026-08-18 the console
 * bound one private address and was reached over `fly proxy` from the founder's laptop, so the
 * password was a second lock behind a closed door. Founder, 2026-08-18: "relying on a tunnel on
 * this macbook to run operations is not smart" - a dashboard whose only door is the laptop dies
 * with the laptop, which is the dependency the whole migration exists to remove. The console now
 * answers on the open internet over HTTPS, so this password IS the fence. Three things carry that
 * weight: the timing-safe compare below, the Secure+HttpOnly+SameSite=Strict cookie, and the
 * per-address limiter in lib/ratelimit.ts.
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

/**
 * `secure` is decided by the CALLER from the request, not hardcoded, because both doors are
 * real: https://ops.mumchimp.com through Fly's proxy, and http://127.0.0.1:8611 for anyone
 * already inside the machine. A Secure cookie is never sent over plain HTTP, so hardcoding it
 * on would break the local door with the message "that password did not work" - the same
 * failure this comment warned about in the other direction before 2026-08-18.
 */
export function setSessionCookie(res: NextApiResponse, token: string, secure = false): void {
  res.setHeader(
    'Set-Cookie',
    `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict; ` +
      `Max-Age=${SESSION_TTL_S}${secure ? '; Secure' : ''}`,
  );
}

/** True when the request reached us over TLS. Fly terminates TLS and sets the header. */
export function isSecureRequest(req: NextApiRequest): boolean {
  const proto = req.headers['x-forwarded-proto'];
  const first = Array.isArray(proto) ? proto[0] : proto;
  return typeof first === 'string' && first.split(',')[0]!.trim() === 'https';
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

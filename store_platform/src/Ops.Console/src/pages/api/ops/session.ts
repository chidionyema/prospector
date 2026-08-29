/**
 * POST /api/ops/session   — sign in
 * DELETE /api/ops/session — sign out
 * GET /api/ops/session    — am I signed in, and is a password even configured
 *
 * The password is compared here, on the server. It never reaches client JavaScript, and the
 * cookie it mints is HttpOnly so the page cannot read it back.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

import { logConsoleEvent } from '@/lib/oplog';
import { opsRead } from '@/lib/ops';
import { clearFailures, clientKey, isLocked, recordFailure } from '@/lib/ratelimit';

import {
  COOKIE_NAME,
  clearSessionCookie,
  isConfigured,
  isSecureRequest,
  mintSession,
  passwordMatches,
  readCookie,
  sessionValid,
  setSessionCookie,
} from '@/lib/auth';

/**
 * Every console read spawns `python -m prospector.ops.console_api`, so the first one after a
 * deploy pays for a cold interpreter AND a cold page cache on the volume. Measured on
 * prospector-engine, 2026-08-19: the `status` view took 3.73s cold, then 0.98s and 0.94s warm;
 * a bare `import prospector.ops.console_api` is 0.32s and an empty interpreter 0.02s, so the
 * cold cost is the filesystem, not our imports. Founder the same day: the console is "slow to
 * load on first login".
 *
 * So warm it during the redirect the browser is already doing. This runs AFTER the cookie is
 * written and is never awaited: sign-in must not get slower to make the next page faster, and a
 * gateway that is down must not stop anyone signing in to find out why.
 *
 * Rate-limited to one spawn a minute. A page-refresh loop on the login form would otherwise be
 * a way to spawn interpreters on the engine, and this route is reachable before any session
 * exists.
 */
const PREWARM_EVERY_MS = 60_000;
let lastPrewarm = 0;

function prewarmGateway(now: number = Date.now()): void {
  if (now - lastPrewarm < PREWARM_EVERY_MS) return;
  lastPrewarm = now;
  void opsRead('status', {}).catch(() => {
    // A failed prewarm is not an error anyone needs to see. The page's own read will report it.
  });
}

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'GET') {
    return res.status(200).json({
      ok: true,
      configured: isConfigured(),
      signed_in: sessionValid(readCookie(req, COOKIE_NAME)),
      note: isConfigured()
        ? null
        : 'CONTROL_CENTER_PASSWORD is not set. The console is locked until it is.',
    });
  }

  if (req.method === 'DELETE') {
    logConsoleEvent({ kind: 'signed_out', who: clientKey(req.headers) });
    clearSessionCookie(res);
    return res.status(200).json({ ok: true, signed_in: false });
  }

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST, DELETE');
    return res.status(405).json({ ok: false, error: 'method not allowed' });
  }

  if (!isConfigured()) {
    return res.status(503).json({
      ok: false,
      error:
        'CONTROL_CENTER_PASSWORD is not set, so there is nothing to sign in against. Set it ' +
        'in .env and restart. An unconfigured portal is closed, never open.',
    });
  }

  // Checked BEFORE the password is compared, so a locked address cannot use this route as an
  // oracle at all - not even for timing.
  const who = clientKey(req.headers);
  if (isLocked(who)) {
    logConsoleEvent({ kind: 'signin_locked', who, status: 429 });
    return res.status(429).json({
      ok: false,
      error: 'Too many wrong passwords from this address. Wait fifteen minutes.',
    });
  }

  const password = String((req.body as { password?: unknown } | undefined)?.password ?? '');
  if (!passwordMatches(password)) {
    recordFailure(who);
    logConsoleEvent({ kind: 'signin_failed', who, status: 401 });
    // One message for a wrong password and for an empty one. Distinguishing them tells an
    // attacker which half they got right.
    return res.status(401).json({ ok: false, error: 'That password did not work.' });
  }

  clearFailures(who);
  // Sign-ins bracket the blank-tab story. A run of `read_refused` that stops the moment a
  // `signed_in` lands is an expired session and nothing worse; one that keeps going after it
  // is a real fault. Neither reading is available without both lines.
  logConsoleEvent({ kind: 'signed_in', who, status: 200 });
  setSessionCookie(res, mintSession(), isSecureRequest(req));
  prewarmGateway();
  return res.status(200).json({ ok: true, signed_in: true });
}

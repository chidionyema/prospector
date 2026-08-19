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
  return res.status(200).json({ ok: true, signed_in: true });
}

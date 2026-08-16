/**
 * POST /api/ops/session   — sign in
 * DELETE /api/ops/session — sign out
 * GET /api/ops/session    — am I signed in, and is a password even configured
 *
 * The password is compared here, on the server. It never reaches client JavaScript, and the
 * cookie it mints is HttpOnly so the page cannot read it back.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

import {
  COOKIE_NAME,
  clearSessionCookie,
  isConfigured,
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

  const password = String((req.body as { password?: unknown } | undefined)?.password ?? '');
  if (!passwordMatches(password)) {
    // One message for a wrong password and for an empty one. Distinguishing them tells an
    // attacker which half they got right.
    return res.status(401).json({ ok: false, error: 'That password did not work.' });
  }

  setSessionCookie(res, mintSession());
  return res.status(200).json({ ok: true, signed_in: true });
}

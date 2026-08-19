/**
 * GET /api/s/<token>[?name=<path>]
 *
 * THE ONLY ROUTE IN THIS CONSOLE THAT ANSWERS WITHOUT A SESSION. Everything else goes through
 * `requireAuth`. That is deliberate and it is the whole feature: the founder needs to hand a URL
 * to a consultant, or paste one into Claude on the web, and have it work with no account.
 *
 * Four things carry the weight, and none of them is the handler being careful:
 *
 *  1. It names exactly one python view, `share_open`, as a string literal. The authed gateway's
 *     `VIEWS` list does not contain it and this file cannot reach `VIEWS`, so a bug here cannot
 *     turn into a read of `money` or `spend`.
 *  2. What the token may see is decided inside `prospector.ops.share.open_share` — scope, expiry,
 *     revocation and the deny-list — not here. This handler has no opinion about paths.
 *  3. The per-address limiter from the login route is applied to failures, because an endpoint
 *     that answers anonymously is an endpoint someone will guess at.
 *  4. `noindex`, so a link that reaches a crawler does not reach a search index.
 *
 * Every refusal returns the same 404 and the same words. A revoked token that says "revoked"
 * tells whoever is probing that the token was real.
 */
import type { NextApiRequest, NextApiResponse } from 'next';

import { opsRead } from '@/lib/ops';
import { clientKey, isLocked, recordFailure } from '@/lib/ratelimit';

const GONE = 'This link is not valid. It may have expired, or been revoked.';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex, nofollow');

  if (req.method !== 'GET') {
    res.status(405).json({ error: 'GET only' });
    return;
  }

  const key = clientKey(req.headers);
  if (isLocked(key)) {
    res.status(429).json({ error: 'Too many attempts. Try again shortly.' });
    return;
  }

  const token = Array.isArray(req.query.token) ? req.query.token[0] : req.query.token;
  const name = Array.isArray(req.query.name) ? req.query.name[0] : req.query.name;
  if (!token) {
    res.status(404).json({ error: GONE });
    return;
  }

  // The viewer is recorded so the founder can answer "what did they actually read?" later. It is
  // the same address the limiter keys on, and it never reaches the rendered page.
  //
  // EVERY failure below lands on the same two lines. The engine says a great deal about why it
  // refused — expired, revoked, denied by pattern, no such token — and none of it comes out here.
  // A gateway that is simply down also lands here rather than 500ing with a stack trace, which is
  // the one case where hiding the reason costs the operator something; the console log keeps it.
  let out;
  try {
    out = await opsRead<Record<string, unknown>>('share_open', {
      token,
      name: name || '',
      viewer: key,
    });
  } catch {
    recordFailure(key);
    res.status(404).json({ error: GONE });
    return;
  }

  if (!out.envelope?.ok) {
    recordFailure(key);
    res.status(404).json({ error: GONE });
    return;
  }
  res.status(200).json(out.envelope.data);
}

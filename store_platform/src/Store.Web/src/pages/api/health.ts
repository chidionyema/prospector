import type { NextApiRequest, NextApiResponse } from 'next';

/**
 * Fly's readiness signal for this machine. `web.fly.toml` polls it; without a check block Fly has
 * no idea whether Next.js is serving yet, so it routes traffic to a machine that is still booting
 * and a rolling deploy shows visitors a gap rather than replacing one warm machine with another.
 *
 * DELIBERATELY does not touch the Store.Api. A health check is a claim about THIS process, and
 * making it depend on a downstream service inverts what it is for: an API blip would fail every
 * web machine's check at once, drain them all out of rotation, and turn a partial fault into a
 * total outage. The storefront survives an API outage by design (see `lib/catalogCache.ts`), so a
 * web machine that can serve pages is healthy even when the catalogue is unreachable.
 */
export default function handler(_req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  res.status(200).json({ status: 'ok' });
}

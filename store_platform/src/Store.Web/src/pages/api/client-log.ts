import type { NextApiRequest, NextApiResponse } from 'next';

import { CORRELATION_HEADER } from '@/lib/api/correlation';
import { flush, ship } from '@/lib/centralLog';

/**
 * POST /api/client-log. The storefront tells the server it broke.
 *
 * WHY THIS EXISTS. A render-time throw in the buyer's browser produced exactly one trace: a
 * `console.error` in that buyer's devtools (`components/ErrorBoundary.tsx`). Nobody here can
 * read that. So the one surface where a fault costs money, the shop front, was the one
 * surface the central log could not answer for. This route is the storefront's producer, and
 * `svc: "store-web"` is already a name `prospector/log_ingest.py` knows.
 *
 * WHY THE BROWSER DOES NOT POST TO THE INGEST DIRECTLY. `/internal/logs` is reachable only on
 * Fly's private network and it authenticates with `STORE_INTERNAL_API_KEY`. A browser could not
 * route to it, and giving it the key would publish the key in client JavaScript. The key stays
 * on this side of the wire; `lib/centralLog.ts` is never imported by a page.
 *
 * NO AUTH, DELIBERATELY. This fires when the page is already broken, and a route that needed a
 * good session would stay silent in exactly the case it exists for. Same reasoning as the
 * console's `api/ops/client-error.ts`. What stops it being a log hose: POST only, four fields,
 * each clipped, a 204 with no body so an anonymous caller learns nothing, and a shipper that
 * drops rather than queues when the ingest is down.
 */

const MAX_FIELD = 4096;

export const config = {
  // Next's default body cap is 1MB. A stack and a component stack are kilobytes; anything above
  // this is not an error report, and rejecting it here is cheaper than clipping it later.
  api: { bodyParser: { sizeLimit: '16kb' } },
};

function clip(value: unknown): string {
  return typeof value === 'string' ? value.slice(0, MAX_FIELD) : '';
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false, error: 'POST only' });
  }

  const body = (req.body ?? {}) as Record<string, unknown>;
  const where = clip(body.where) || 'unknown';
  const message = clip(body.message) || 'no message';
  const stack = clip(body.stack);
  const componentStack = clip(body.componentStack);

  // The correlation id joins this crash to the buyer's API calls either side of it. Preferred
  // from the header, which `correlated()` already sets on every call to our own API, so the id
  // is the same one Store.Api stamped on the checkout session.
  const header = req.headers[CORRELATION_HEADER.toLowerCase()];
  const corr = clip(Array.isArray(header) ? header[0] : header) || clip(body.corr);

  // stderr as well, always. It is the copy that still exists when the ingest is unreachable or
  // unconfigured, which is exactly when a crash is most likely to be worth reading.
  console.error(`[store-web client-error] where=${where} message=${message}`);
  if (stack) console.error(`[store-web client-error] stack=${stack}`);

  ship({
    svc: 'store-web',
    evt: 'web.client_error',
    lvl: 'error',
    msg: message,
    corr,
    ctx: { where, stack, component_stack: componentStack, ua: clip(req.headers['user-agent']) },
  });
  // Awaited so the line is gone before the machine can be recycled. `flush` swallows every
  // failure and the shipper's own timeout bounds it, so this cannot hang the response.
  await flush();

  return res.status(204).end();
}
